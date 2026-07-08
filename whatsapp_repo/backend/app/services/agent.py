import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.schemas import ExtracaoLancamento
from app.services.ai import ai_service
from app.services.evolution import evolution_client
from app.services.projecao import projecao_service
from app.services.repository import ESSENTIAL_FIELDS, conversa_repo, lancamento_repo
from app.models import Cartao, ConversaContexto, HistoricoMensagem, TransacaoPendente

logger = logging.getLogger(__name__)
settings = get_settings()

ORIGEM_MAP = {
    "texto": "whatsapp-texto",
    "audio": "whatsapp-audio",
    "imagem": "whatsapp-foto",
    "documento": "whatsapp-foto",
}


class AgentService:
    def __init__(self) -> None:
        self.repo = lancamento_repo
        self.conversa = conversa_repo

    async def _reply(self, db: AsyncSession, phone: str, msg: str, *, record: bool = True) -> str:
        """Envia resposta ao WhatsApp e opcionalmente grava na memória de conversa."""
        await evolution_client.send_text(phone, msg)
        if record:
            await self.conversa.add_message(db, phone, "assistant", msg)
        return msg

    async def _send_progress(self, phone: str, descricao: str) -> None:
        await evolution_client.send_text(phone, f"⏳ {descricao}")

    @staticmethod
    def _progress_description(
        ctx: ConversaContexto,
        pendente: TransacaoPendente | None,
        text: str,
    ) -> str:
        estado = ctx.estado
        if estado == "cadastro_cartao":
            return "Interpretando dados do cartão..."
        if estado == "escolher_cartao_padrao":
            return "Salvando cartão padrão e registrando gasto..."
        if estado == "escolher_cartao":
            return "Registrando gasto no cartão escolhido..."
        if estado == "aguardando_confirmacao":
            return "Confirmando lançamento..."
        if estado == "aguardando_apagar":
            return "Processando exclusão..."
        if estado in ("aguardando_correcao_confirmacao", "aguardando_correcao_campo"):
            return "Processando correção..."
        if estado == "aguardando_nome_personalizado":
            return "Salvando nome do estabelecimento..."
        if pendente:
            return "Completando dados do lançamento..."
        return "Analisando sua mensagem..."

    async def _interpretar_estado(self, estado: str, text: str, contexto: dict | None = None) -> dict:
        return await ai_service.interpret_state_response(estado, text, contexto or {})

    @staticmethod
    def _confirmacao_resposta(resposta: dict) -> str | None:
        valor = resposta.get("confirmacao") or resposta.get("cartao_padrao")
        if valor in ("sim", "nao"):
            return valor
        return None

    async def _resolve_cartao_id_from_dados(self, db: AsyncSession, dados: dict) -> int | None:
        cartao_id = dados.get("cartao_id")
        if cartao_id:
            return int(cartao_id)
        cartoes = await self.repo.list_cartoes(db)
        if cartoes:
            return cartoes[-1].id
        return None

    async def process_message(
        self,
        db: AsyncSession,
        phone: str,
        msg_info: dict,
        processed_text: str,
        notify_callback=None,
    ) -> str:
        await self.repo.ensure_setores(db)
        tipo = msg_info["tipo"]
        origem = ORIGEM_MAP.get(tipo, "whatsapp-texto")
        message_id = msg_info.get("message_id")
        key_id = msg_info.get("key_id")

        historico = HistoricoMensagem(
            message_id=message_id,
            key_id=key_id,
            tipo_mensagem=tipo,
            conteudo_original=processed_text,
            status="processando",
            phone_number=phone,
        )
        db.add(historico)
        await db.flush()

        ctx = await self.conversa.get_context(db, phone)
        pendente = await self.conversa.get_pendente_ativa(db, phone)

        if not msg_info.get("skip_hourglass"):
            await self._send_progress(phone, self._progress_description(ctx, pendente, processed_text))

        if pendente and not msg_info.get("skip_context_check"):
            mudou = await ai_service.check_context_change(
                pendente.campos_capturados, processed_text
            )
            if mudou:
                await self.conversa.discard_pendente(db, pendente)
                pendente = None

        if ctx.estado == "aguardando_confirmacao":
            return await self._handle_confirmation(db, phone, processed_text, ctx, notify_callback)

        if ctx.estado == "cadastro_cartao":
            return await self._handle_cadastro_cartao(db, phone, processed_text, ctx, historico, notify_callback)

        if ctx.estado in ("escolher_cartao", "escolher_cartao_padrao"):
            return await self._handle_escolha_cartao(db, phone, processed_text, ctx, historico, notify_callback)

        if ctx.estado == "aguardando_apagar":
            return await self._handle_apagar_confirmacao(db, phone, processed_text, ctx, notify_callback)

        if ctx.estado == "aguardando_correcao_confirmacao":
            return await self._handle_correcao_confirmacao(db, phone, processed_text, ctx, notify_callback)

        if ctx.estado == "aguardando_correcao_campo":
            return await self._handle_correcao_campo(db, phone, processed_text, ctx, notify_callback)

        if ctx.estado == "aguardando_nome_personalizado":
            return await self._handle_nome_personalizado(db, phone, processed_text, ctx)

        if pendente:
            return await self._handle_pendente_completion(
                db, phone, processed_text, pendente, origem, message_id, key_id, historico, notify_callback
            )

        extracao = await ai_service.extract_structured(
            processed_text, context_messages=ctx.mensagens
        )
        if not extracao.data_hora and msg_info.get("timestamp"):
            extracao.data_hora = msg_info["timestamp"]
        await self.conversa.add_message(db, phone, "user", processed_text)

        return await self._route_intent(
            db, phone, processed_text, extracao, origem, message_id, key_id, historico, notify_callback
        )

    async def _route_intent(
        self,
        db: AsyncSession,
        phone: str,
        text: str,
        extracao: ExtracaoLancamento,
        origem: str,
        message_id: str | None,
        key_id: str | None,
        historico: HistoricoMensagem,
        notify_callback,
    ) -> str:
        if extracao.intencao == "consulta":
            return await self._handle_consulta(db, phone, extracao)

        if extracao.intencao == "correcao":
            return await self._handle_correcao(db, phone, text, extracao)

        if extracao.intencao == "resumo_mes":
            return await self._handle_resumo(db, phone)

        if extracao.intencao == "cadastro_cartao":
            return await self._handle_cadastro_cartao_aberto(db, phone, text, historico, notify_callback)

        return await self._handle_novo_gasto(
            db, phone, extracao, origem, message_id, key_id, historico, notify_callback
        )

    async def _handle_novo_gasto(
        self,
        db: AsyncSession,
        phone: str,
        extracao: ExtracaoLancamento,
        origem: str,
        message_id: str | None,
        key_id: str | None,
        historico: HistoricoMensagem,
        notify_callback,
    ) -> str:
        extracao = self._apply_inferred_defaults(extracao)
        faltantes = self._check_missing_fields(extracao)
        if faltantes:
            return await self._create_partial_response(
                db, phone, extracao, faltantes, origem, message_id, key_id, historico
            )

        cartoes = await self.repo.list_cartoes(db)
        if not cartoes:
            await self.conversa.set_estado(
                db, phone, "cadastro_cartao",
                {"extracao": extracao.model_dump(mode="json"), "origem": origem, "message_id": message_id, "key_id": key_id},
            )
            return await self._reply(db, phone, self._format_cartao_request())

        cartao = await self._resolve_cartao(db, phone, cartoes)
        if cartao is None:
            lista = "\n".join(f"{i+1}. {c.banco_origem} ****{c.ultimos_4_digitos}" for i, c in enumerate(cartoes))
            await self.conversa.set_estado(
                db, phone, "escolher_cartao",
                {"extracao": extracao.model_dump(mode="json"), "origem": origem, "cartoes": [c.id for c in cartoes]},
            )
            msg = f"Em qual cartão registrar?\n{lista}\n\nResponda com o número."
            return await self._reply(db, phone, msg)

        needs_confirm = settings.always_confirm_mode or (
            extracao.valor and extracao.valor >= Decimal(str(settings.high_value_threshold))
        ) or extracao.confianca < 0.8

        if needs_confirm:
            await self.conversa.set_estado(
                db, phone, "aguardando_confirmacao",
                {
                    "extracao": extracao.model_dump(mode="json"),
                    "origem": origem,
                    "cartao_id": cartao.id,
                    "message_id": message_id,
                    "key_id": key_id,
                },
            )
            historico.status = "aguardando"
            return await self._reply(db, phone, self._format_confirmacao(extracao))

        return await self._persist_and_confirm(
            db, phone, extracao, cartao.id, origem, message_id, key_id, historico, notify_callback
        )

    async def _persist_and_confirm(
        self,
        db: AsyncSession,
        phone: str,
        extracao: ExtracaoLancamento,
        cartao_id: int,
        origem: str,
        message_id: str | None,
        key_id: str | None,
        historico: HistoricoMensagem,
        notify_callback,
    ) -> str:
        lanc, estab, is_novo = await self.repo.create_lancamento(
            db, extracao, cartao_id, origem, message_id, key_id
        )
        await projecao_service.atualizar_valores_futuros_cartao(db, cartao_id, extracao)
        historico.status = "processado"
        historico.conteudo_processado = json.dumps(extracao.model_dump(mode="json"), ensure_ascii=False)
        await self.conversa.set_estado(db, phone, None, {})

        msg = self._format_success(extracao, estabelecimento=estab.nome_exibicao)
        await self._reply(db, phone, f"✅ {msg}", record=False)
        await self.conversa.add_message(db, phone, "assistant", msg)

        if notify_callback:
            await notify_callback({"type": "lancamento_criado", "id": lanc.id})

        if is_novo:
            await self._check_novo_estabelecimento(db, phone, extracao, estab.id)
        return msg

    async def _create_partial_response(
        self,
        db: AsyncSession,
        phone: str,
        extracao: ExtracaoLancamento,
        faltantes: list[str],
        origem: str,
        message_id: str | None,
        key_id: str | None,
        historico: HistoricoMensagem,
    ) -> str:
        capturados = {
            k: str(v) if v is not None else None
            for k, v in {
                "item": extracao.item,
                "estabelecimento": extracao.estabelecimento,
                "setor": extracao.setor,  # já inferido — só para persistência interna
                "tipo": extracao.tipo,
                "valor": extracao.valor,
                "parcelas": extracao.parcelas,
                "data_hora": extracao.data_hora.isoformat() if extracao.data_hora else None,
            }.items()
            if v is not None
        }
        await self.conversa.create_pendente(
            db, phone, capturados, faltantes, origem, message_id, key_id, historico.id
        )
        historico.status = "pendente"
        historico.conteudo_processado = json.dumps({"capturados": capturados, "faltantes": faltantes})

        msg = self._format_partial(capturados, faltantes)
        return await self._reply(db, phone, msg)

    async def _handle_pendente_completion(
        self,
        db: AsyncSession,
        phone: str,
        text: str,
        pendente: TransacaoPendente,
        origem: str,
        message_id: str | None,
        key_id: str | None,
        historico: HistoricoMensagem,
        notify_callback,
    ) -> str:
        capturados = dict(pendente.campos_capturados)
        faltantes = self._fields_still_missing(capturados)
        if not faltantes:
            merged = self._apply_inferred_defaults(
                ExtracaoLancamento(
                    estabelecimento=capturados.get("estabelecimento"),
                    item=capturados.get("item"),
                    setor=capturados.get("setor"),
                    tipo=capturados.get("tipo"),
                    valor=Decimal(str(capturados["valor"])) if capturados.get("valor") else None,
                    parcelas=capturados.get("parcelas"),
                    data_hora=(
                        datetime.fromisoformat(capturados["data_hora"])
                        if capturados.get("data_hora")
                        else None
                    ),
                    confianca=0.9,
                )
            )
            pendente.status = "processado"
            cartoes = await self.repo.list_cartoes(db)
            cartao = await self._resolve_cartao(db, phone, cartoes)
            if not cartoes:
                await self.conversa.set_estado(
                    db, phone, "cadastro_cartao",
                    {
                        "extracao": merged.model_dump(mode="json"),
                        "origem": pendente.origem or origem,
                        "message_id": pendente.message_id or message_id,
                        "key_id": pendente.key_id or key_id,
                    },
                )
                return await self._reply(db, phone, self._format_cartao_request())
            if not cartao:
                lista = "\n".join(f"{i+1}. {c.banco_origem} ****{c.ultimos_4_digitos}" for i, c in enumerate(cartoes))
                await self.conversa.set_estado(
                    db, phone, "escolher_cartao",
                    {
                        "extracao": merged.model_dump(mode="json"),
                        "origem": pendente.origem or origem,
                        "cartoes": [c.id for c in cartoes],
                        "message_id": pendente.message_id or message_id,
                        "key_id": pendente.key_id or key_id,
                    },
                )
                msg = f"Em qual cartão registrar?\n{lista}\n\nResponda com o número."
                return await self._reply(db, phone, msg)
            return await self._persist_and_confirm(
                db, phone, merged, cartao.id, pendente.origem or origem,
                pendente.message_id or message_id, pendente.key_id or key_id,
                historico, notify_callback,
            )

        focus = {"capturados": pendente.campos_capturados, "faltantes": pendente.campos_faltantes}
        extracao = await ai_service.extract_structured(text, focus_pending=focus)

        if extracao.mudou_contexto:
            await self.conversa.discard_pendente(db, pendente)
            await self.conversa.add_message(db, phone, "user", text)
            return await self._route_intent(
                db, phone, text, extracao, origem, message_id, key_id, historico, notify_callback
            )

        extracao = self._apply_inferred_defaults(extracao)
        capturados = dict(pendente.campos_capturados)
        for field in ("item", "estabelecimento", "setor", "valor", "tipo", "parcelas"):
            val = getattr(extracao, field, None)
            if val is not None:
                capturados[field] = str(val) if field == "valor" else val

        faltantes = self._fields_still_missing(capturados)
        if faltantes:
            pendente.campos_capturados = capturados
            pendente.campos_faltantes = faltantes
            pendente.tentativas_imagem = (pendente.tentativas_imagem or 0) + 1
            if pendente.tentativas_imagem >= settings.retry_limit and origem == "whatsapp-foto":
                pendente.status = "erro"
                historico.status = "erro"
                msg = (
                    f"Não consegui processar a imagem após {settings.retry_limit} tentativas. "
                    "Tente digitar os dados manualmente."
                )
                return await self._reply(db, phone, msg)
            msg = self._format_partial(capturados, faltantes)
            return await self._reply(db, phone, msg)

        merged = self._apply_inferred_defaults(
            ExtracaoLancamento(
                estabelecimento=capturados.get("estabelecimento"),
                item=capturados.get("item"),
                setor=capturados.get("setor"),
                tipo=capturados.get("tipo"),
                valor=Decimal(capturados["valor"]) if capturados.get("valor") else None,
                parcelas=capturados.get("parcelas"),
                data_hora=(
                    datetime.fromisoformat(capturados["data_hora"])
                    if capturados.get("data_hora")
                    else None
                ),
                confianca=0.9,
            )
        )
        pendente.status = "processado"

        cartoes = await self.repo.list_cartoes(db)
        cartao = await self._resolve_cartao(db, phone, cartoes)
        if not cartoes:
            await self.conversa.set_estado(
                db, phone, "cadastro_cartao",
                {
                    "extracao": merged.model_dump(mode="json"),
                    "origem": pendente.origem or origem,
                    "message_id": pendente.message_id or message_id,
                    "key_id": pendente.key_id or key_id,
                },
            )
            return await self._reply(db, phone, self._format_cartao_request())
        if not cartao:
            lista = "\n".join(f"{i+1}. {c.banco_origem} ****{c.ultimos_4_digitos}" for i, c in enumerate(cartoes))
            await self.conversa.set_estado(
                db, phone, "escolher_cartao",
                {
                    "extracao": merged.model_dump(mode="json"),
                    "origem": pendente.origem or origem,
                    "cartoes": [c.id for c in cartoes],
                    "message_id": pendente.message_id or message_id,
                    "key_id": pendente.key_id or key_id,
                },
            )
            msg = f"Em qual cartão registrar?\n{lista}\n\nResponda com o número."
            return await self._reply(db, phone, msg)

        return await self._persist_and_confirm(
            db, phone, merged, cartao.id, pendente.origem or origem,
            pendente.message_id or message_id, pendente.key_id or key_id,
            historico, notify_callback,
        )

    async def _handle_confirmation(
        self, db: AsyncSession, phone: str, text: str, ctx, notify_callback
    ) -> str:
        dados = ctx.dados_estado or {}
        resposta = await self._interpretar_estado("aguardando_confirmacao", text, dados)
        confirmacao = self._confirmacao_resposta(resposta)
        if confirmacao == "sim":
            extracao = ExtracaoLancamento(**dados.get("extracao", {}))
            if extracao.valor:
                extracao.valor = Decimal(str(extracao.valor))
            cartao_id = dados.get("cartao_id")
            if not cartao_id:
                return await self._reply(db, phone, "Não encontrei o cartão para este lançamento. Tente novamente.")
            historico = HistoricoMensagem(
                tipo_mensagem="texto", conteudo_original=text, status="processando", phone_number=phone
            )
            db.add(historico)
            await db.flush()
            return await self._persist_and_confirm(
                db, phone, extracao, int(cartao_id), dados.get("origem", "whatsapp-texto"),
                dados.get("message_id"), dados.get("key_id"), historico, notify_callback,
            )
        if confirmacao == "nao":
            await self.conversa.set_estado(db, phone, None, {})
            return await self._reply(db, phone, "Lançamento cancelado.")
        return await self._reply(db, phone, "Não entendi. Confirma o lançamento? (sim/não)")

    async def _handle_cadastro_cartao_aberto(
        self, db: AsyncSession, phone: str, text: str, historico, notify_callback
    ) -> str:
        ctx = await self.conversa.get_context(db, phone)
        await self.conversa.set_estado(db, phone, "cadastro_cartao", ctx.dados_estado or {})
        return await self._handle_cadastro_cartao(db, phone, text, ctx, historico, notify_callback)

    async def _handle_cadastro_cartao(
        self, db: AsyncSession, phone: str, text: str, ctx, historico, notify_callback
    ) -> str:
        parsed = await ai_service.parse_cartao_data(text)
        if not parsed or not parsed.get("banco_origem"):
            msg = (
                "Não entendi os dados do cartão. Envie no formato:\n"
                "Banco: Nubank\nÚltimos 4 dígitos: 1234\nVencimento: 12/2028\nBandeira: Mastercard\nLimite: 5000"
            )
            return await self._reply(db, phone, msg)

        from datetime import date as date_type
        venc = parsed.get("vencimento")
        venc_date = None
        if venc:
            try:
                venc_date = date_type.fromisoformat(str(venc)[:10])
            except ValueError:
                pass

        cartao = await self.repo.create_cartao(db, {
            "banco_origem": parsed["banco_origem"],
            "ultimos_4_digitos": str(parsed.get("ultimos_4_digitos", "0000"))[-4:],
            "vencimento": venc_date,
            "bandeira": parsed.get("bandeira"),
            "limite_total": Decimal(str(parsed["limite_total"])) if parsed.get("limite_total") else None,
            "cartao_padrao": "nao",
        })

        dados = dict(ctx.dados_estado or {})
        dados["cartao_id"] = cartao.id
        await self.conversa.set_estado(db, phone, "escolher_cartao_padrao", dados)
        msg = (
            f"Cartão {cartao.banco_origem} ****{cartao.ultimos_4_digitos} cadastrado!\n"
            "Esse será seu cartão padrão? (sim/nao)\n"
            "Se não, você escolherá o cartão a cada lançamento."
        )
        return await self._reply(db, phone, msg)

    async def _handle_escolha_cartao(
        self, db: AsyncSession, phone: str, text: str, ctx, historico, notify_callback
    ) -> str:
        dados = dict(ctx.dados_estado or {})

        if ctx.estado == "escolher_cartao_padrao":
            cartao_id = await self._resolve_cartao_id_from_dados(db, dados)
            if not cartao_id:
                await self.conversa.set_estado(db, phone, None, {})
                return await self._reply(
                    db, phone,
                    "Não encontrei o cartão cadastrado. Envie os dados do cartão novamente.",
                )

            resposta = await self._interpretar_estado("escolher_cartao_padrao", text, dados)
            if self._confirmacao_resposta(resposta) == "sim":
                await self.repo.set_cartao_padrao(db, cartao_id)

            extracao = ExtracaoLancamento(**dados.get("extracao", {}))
            if extracao.valor:
                extracao.valor = Decimal(str(extracao.valor))
            await self.conversa.set_estado(db, phone, None, {})
            return await self._persist_and_confirm(
                db, phone, extracao, cartao_id, dados.get("origem", "whatsapp-texto"),
                dados.get("message_id"), dados.get("key_id"), historico, notify_callback,
            )

        if ctx.estado == "escolher_cartao":
            cartao_ids = dados.get("cartoes", [])
            cartoes = [c for c in await self.repo.list_cartoes(db) if c.id in cartao_ids]
            contexto = {
                "opcoes": [
                    f"{i + 1}. {c.banco_origem} ****{c.ultimos_4_digitos}"
                    for i, c in enumerate(cartoes)
                ]
            }
            resposta = await self._interpretar_estado("escolher_cartao", text, contexto)
            idx = resposta.get("indice")
            if idx is not None:
                try:
                    idx = int(idx) - 1
                except (TypeError, ValueError):
                    idx = -1
                if 0 <= idx < len(cartoes):
                    dados["cartao_id"] = cartoes[idx].id
                    extracao = ExtracaoLancamento(**dados.get("extracao", {}))
                    if extracao.valor:
                        extracao.valor = Decimal(str(extracao.valor))
                    needs_confirm = settings.always_confirm_mode or (
                        extracao.valor and extracao.valor >= Decimal(str(settings.high_value_threshold))
                    ) or extracao.confianca < 0.8
                    if needs_confirm:
                        await self.conversa.set_estado(db, phone, "aguardando_confirmacao", dados)
                        historico.status = "aguardando"
                        return await self._reply(db, phone, self._format_confirmacao(extracao))
                    await self.conversa.set_estado(db, phone, None, {})
                    return await self._persist_and_confirm(
                        db, phone, extracao, dados["cartao_id"], dados.get("origem", "whatsapp-texto"),
                        dados.get("message_id"), dados.get("key_id"), historico, notify_callback,
                    )
            return await self._reply(db, phone, "Não entendi. Responda com o número do cartão da lista.")

        return await self._reply(db, phone, "Não entendi sua escolha. Tente novamente.")

    async def _handle_consulta(self, db: AsyncSession, phone: str, extracao: ExtracaoLancamento) -> str:
        if extracao.tipo_consulta == "limite":
            return await self._handle_consulta_limite(db, phone)

        now = datetime.now(timezone.utc)
        if extracao.tipo_consulta == "setor" and extracao.setor:
            setor = extracao.setor.lower()
            total = await self.repo.sum_by_setor_mes(db, setor, now.month, now.year)
            msg = f"Você gastou R$ {total:,.2f} em {setor} este mês."
        else:
            total = await self.repo.sum_mes(db, now.month, now.year)
            msg = f"Você gastou R$ {total:,.2f} este mês."
        return await self._reply(db, phone, msg.replace(",", "X").replace(".", ",").replace("X", "."))

    async def _handle_consulta_limite(self, db: AsyncSession, phone: str) -> str:
        cartoes = await self.repo.list_cartoes(db)
        if not cartoes:
            return await self._reply(db, phone, "Nenhum cartão cadastrado ainda.")

        lines = ["💳 Limite do cartão:"]
        for cartao in cartoes:
            gasto = cartao.limite_em_uso
            if gasto is None:
                gasto = await self.repo.sum_lancamentos_cartao(db, cartao.id)
            gasto = gasto or Decimal("0")
            limite = cartao.limite_total
            disponivel = cartao.limite_restante
            if disponivel is None and limite is not None:
                disponivel = limite - gasto

            nome = f"{cartao.banco_origem} ****{cartao.ultimos_4_digitos}"
            if cartao.cartao_padrao == "sim":
                nome += " (padrão)"
            lines.append(f"\n{nome}")
            lines.append(f"Total gasto: R$ {gasto:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            if limite is not None:
                lines.append(f"Limite: R$ {limite:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            if disponivel is not None:
                lines.append(
                    f"Limite disponível: R$ {disponivel:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                )
            elif limite is None:
                lines.append("Limite não informado no cadastro do cartão.")

        return await self._reply(db, phone, "\n".join(lines))

    async def _handle_resumo(self, db: AsyncSession, phone: str) -> str:
        now = datetime.now(timezone.utc)
        total = await self.repo.sum_mes(db, now.month, now.year)
        por_setor = await self.repo.gastos_por_setor_mes(db, now.month, now.year)
        lines = [f"📊 Resumo de {now.strftime('%m/%Y')}:", f"Total: R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")]
        for setor, val in por_setor[:5]:
            lines.append(f"• {setor}: R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        msg = "\n".join(lines)
        return await self._reply(db, phone, msg)

    async def _handle_correcao(
        self, db: AsyncSession, phone: str, text: str, extracao: ExtracaoLancamento
    ) -> str:
        ultimo = await self.repo.get_ultimo_lancamento(db)
        if not ultimo:
            return await self._reply(db, phone, "Não há lançamentos para corrigir.")

        acao = extracao.acao_correcao
        if acao == "apagar":
            estab = ultimo.estabelecimento.nome_exibicao
            await self.conversa.set_estado(
                db, phone, "aguardando_apagar", {"lancamento_id": ultimo.id}
            )
            msg = f"Deseja apagar: {estab} — R$ {ultimo.valor} — {ultimo.setor.nome}? (Sim/Não)"
            return await self._reply(db, phone, msg)

        if acao == "editar":
            campos = extracao.campos_correcao or {}
            if not campos:
                await self.conversa.set_estado(
                    db, phone, "aguardando_correcao_campo",
                    {"lancamento_id": ultimo.id},
                )
                msg = (
                    f"Lançamento atual: {ultimo.estabelecimento.nome_exibicao} — "
                    f"R$ {ultimo.valor} — {ultimo.setor.nome} — {ultimo.tipo}\n"
                    "O que deseja corrigir?"
                )
                return await self._reply(db, phone, msg)

            patch = self._campos_correcao_para_extracao(campos)
            await self.conversa.set_estado(
                db, phone, "aguardando_correcao_confirmacao",
                {"lancamento_id": ultimo.id, "patch": patch.model_dump(mode="json")},
            )
            msg = self._format_correcao_confirmacao(ultimo, patch)
            return await self._reply(db, phone, msg)

        await self.conversa.set_estado(
            db, phone, "aguardando_correcao_campo",
            {"lancamento_id": ultimo.id},
        )
        return await self._reply(
            db, phone,
            "Não entendi o que deseja corrigir. Pode apagar o último lançamento ou informar o que alterar.",
        )

    async def _handle_correcao_campo(
        self, db: AsyncSession, phone: str, text: str, ctx, notify_callback
    ) -> str:
        dados = ctx.dados_estado or {}
        lanc = await self.repo.get_lancamento(db, dados["lancamento_id"])
        if not lanc:
            await self.conversa.set_estado(db, phone, None, {})
            return await self._reply(db, phone, "Lançamento não encontrado.")

        resposta = await self._interpretar_estado(
            "aguardando_correcao_campo",
            text,
            {
                "lancamento": {
                    "item": lanc.item,
                    "estabelecimento": lanc.estabelecimento.nome_exibicao,
                    "setor": lanc.setor.nome,
                    "tipo": lanc.tipo,
                    "valor": float(lanc.valor),
                    "parcelas": lanc.parcelas,
                }
            },
        )
        patch = self._campos_correcao_para_extracao(resposta)

        if not any([patch.item, patch.estabelecimento, patch.setor, patch.tipo, patch.valor, patch.parcelas]):
            return await self._reply(
                db, phone,
                "Não entendi a correção. Informe o que deseja alterar.",
            )

        await self.conversa.set_estado(
            db, phone, "aguardando_correcao_confirmacao",
            {"lancamento_id": lanc.id, "patch": patch.model_dump(mode="json")},
        )
        return await self._reply(db, phone, self._format_correcao_confirmacao(lanc, patch))

    async def _handle_correcao_confirmacao(
        self, db: AsyncSession, phone: str, text: str, ctx, notify_callback
    ) -> str:
        dados = ctx.dados_estado or {}
        resposta = await self._interpretar_estado("aguardando_correcao_confirmacao", text, dados)
        confirmacao = self._confirmacao_resposta(resposta)
        if confirmacao == "nao":
            await self.conversa.set_estado(db, phone, None, {})
            return await self._reply(db, phone, "Correção cancelada.")
        if confirmacao != "sim":
            return await self._reply(db, phone, "Não entendi. Confirma a correção? (sim/não)")

        patch_data = dados.get("patch", {})
        patch = ExtracaoLancamento(**patch_data)
        if patch.valor:
            patch.valor = Decimal(str(patch.valor))

        lanc = await self.repo.update_lancamento(db, dados["lancamento_id"], patch)
        await self.conversa.set_estado(db, phone, None, {})

        if not lanc:
            return await self._reply(db, phone, "Não foi possível corrigir o lançamento.")

        if notify_callback:
            await notify_callback({"type": "lancamento_atualizado", "id": lanc.id})

        msg = (
            f"✅ Lançamento atualizado: {lanc.estabelecimento.nome_exibicao} — "
            f"R$ {lanc.valor} — {lanc.setor.nome} — {lanc.tipo}"
        )
        return await self._reply(db, phone, msg)

    async def _handle_nome_personalizado(
        self, db: AsyncSession, phone: str, text: str, ctx
    ) -> str:
        dados = ctx.dados_estado or {}
        resposta = await self._interpretar_estado("aguardando_nome_personalizado", text, dados)
        await self.conversa.set_estado(db, phone, None, {})

        if resposta.get("recusou"):
            return await self._reply(db, phone, "Ok, mantive o nome original.")

        nome = resposta.get("nome")
        if resposta.get("aceitar_sugestao"):
            nome = dados.get("nome_sugerido", nome)

        if not nome:
            return await self._reply(db, phone, "Informe o nome personalizado que deseja guardar.")

        await self.repo.salvar_nome_personalizado(db, dados["estabelecimento_id"], nome)
        return await self._reply(db, phone, f"✅ Nome '{nome}' salvo para buscas futuras.")

    async def _handle_apagar_confirmacao(self, db: AsyncSession, phone: str, text: str, ctx, notify_callback) -> str:
        dados = ctx.dados_estado or {}
        resposta = await self._interpretar_estado("aguardando_apagar", text, dados)
        confirmacao = self._confirmacao_resposta(resposta)
        if confirmacao == "sim":
            await self.repo.delete_lancamento(db, dados["lancamento_id"])
            await self.conversa.set_estado(db, phone, None, {})
            if notify_callback:
                await notify_callback({"type": "lancamento_removido", "id": dados["lancamento_id"]})
            return await self._reply(db, phone, "✅ Lançamento removido.")
        if confirmacao == "nao":
            await self.conversa.set_estado(db, phone, None, {})
            return await self._reply(db, phone, "Operação cancelada.")
        return await self._reply(db, phone, "Não entendi. Confirma a exclusão? (sim/não)")

    async def _resolve_cartao(self, db, phone, cartoes):
        if len(cartoes) == 1:
            return cartoes[0]
        padrao = await self.repo.get_default_cartao(db)
        if padrao:
            return padrao
        return None

    async def _check_novo_estabelecimento(
        self, db: AsyncSession, phone: str, extracao: ExtracaoLancamento, estabelecimento_id: int
    ) -> None:
        nome = extracao.estabelecimento
        if nome and nome.lower() != "desconhecido":
            await self.conversa.set_estado(
                db, phone, "aguardando_nome_personalizado",
                {
                    "estabelecimento_id": estabelecimento_id,
                    "nome_sugerido": nome,
                },
            )
            msg = (
                f"Quer guardar '{nome}' como nome personalizado "
                f"para buscas futuras?\n"
                f"Você pode aceitar, recusar ou enviar outro nome."
            )
            await self._reply(db, phone, msg)

    @staticmethod
    def _apply_inferred_defaults(extracao: ExtracaoLancamento) -> ExtracaoLancamento:
        """Garante setor/tipo após interpretação. Nunca pergunta setor ao usuário."""
        if not extracao.setor:
            extracao.setor = "outros"
        if not extracao.tipo:
            extracao.tipo = "a_vista"
        if not extracao.item and extracao.setor and extracao.setor != "outros":
            extracao.item = extracao.setor
        return extracao

    @staticmethod
    def _check_missing_fields(extracao: ExtracaoLancamento) -> list[str]:
        missing = []
        if extracao.valor is None:
            missing.append("valor")
        # Sem indicação do que comprou: pede item (nunca setor)
        if not extracao.item and not extracao.estabelecimento:
            if not extracao.setor or extracao.setor == "outros":
                missing.append("item")
        return missing

    @staticmethod
    def _fields_still_missing(capturados: dict) -> list[str]:
        missing = [f for f in ESSENTIAL_FIELDS if not capturados.get(f)]
        if not capturados.get("item") and not capturados.get("estabelecimento"):
            setor = (capturados.get("setor") or "").lower()
            if not setor or setor == "outros":
                missing.append("item")
        return missing

    @staticmethod
    def _format_lancamento_resumo(extracao: ExtracaoLancamento, estabelecimento: str | None = None) -> str:
        valor = extracao.valor or Decimal("0")
        parts: list[str] = []
        if extracao.item:
            parts.append(extracao.item)
        parts.append(f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        nome = estabelecimento or extracao.estabelecimento
        if nome and nome.lower() != "desconhecido":
            parts.append(nome)
        elif extracao.setor:
            parts.append(extracao.setor)
        tipo = extracao.tipo or "a_vista"
        if tipo != "a_vista":
            parts.append(tipo.replace("_", " "))
        return " — ".join(parts)

    @staticmethod
    def _format_success(extracao: ExtracaoLancamento, estabelecimento: str | None = None) -> str:
        return f"Cadastrei: {AgentService._format_lancamento_resumo(extracao, estabelecimento)}"

    @staticmethod
    def _campos_correcao_para_extracao(campos: dict) -> ExtracaoLancamento:
        valor = campos.get("valor")
        if valor is not None:
            valor = Decimal(str(valor))
        return ExtracaoLancamento(
            item=campos.get("item"),
            estabelecimento=campos.get("estabelecimento"),
            setor=campos.get("setor"),
            tipo=campos.get("tipo"),
            valor=valor,
            parcelas=campos.get("parcelas"),
        )

    @staticmethod
    def _format_correcao_confirmacao(lanc, patch: ExtracaoLancamento) -> str:
        changes = []
        if patch.item:
            changes.append(f"item → {patch.item}")
        if patch.estabelecimento:
            changes.append(f"estabelecimento → {patch.estabelecimento}")
        if patch.setor:
            changes.append(f"setor → {patch.setor}")
        if patch.tipo:
            changes.append(f"tipo → {patch.tipo}")
        if patch.valor is not None:
            changes.append(f"valor → R$ {patch.valor}")
        if patch.parcelas:
            changes.append(f"parcelas → {patch.parcelas}")
        resumo = ", ".join(changes) if changes else "sem alterações"
        return (
            f"Confirma a correção do lançamento?\n"
            f"Atual: {lanc.estabelecimento.nome_exibicao} — R$ {lanc.valor} — {lanc.setor.nome}\n"
            f"Alterações: {resumo}\n(Sim/Não)"
        )

    @staticmethod
    def _format_partial(capturados: dict, faltantes: list[str]) -> str:
        labels = {"item": "o que comprou", "valor": "valor", "estabelecimento": "estabelecimento"}
        # Nunca mostre setor como "faltou" — é sempre inferido
        faltantes = [f for f in faltantes if f != "setor"]
        lines = ["⚠️ Capturei:"]
        for k, v in capturados.items():
            if k == "setor":
                continue  # não listamos setor como algo "capturado do usuário"
            lines.append(f"• {labels.get(k, k)}: {v}")
        if faltantes:
            faltantes_txt = ", ".join(labels.get(f, f) for f in faltantes)
            lines.append(f"❌ Faltou: {faltantes_txt}")
            lines.append("Você pode: digitar, enviar áudio ou reenviar a mídia.")
        return "\n".join(lines)

    @staticmethod
    def _format_confirmacao(extracao: ExtracaoLancamento) -> str:
        return (
            f"Confirma o lançamento?\n"
            f"{AgentService._format_lancamento_resumo(extracao)}\n"
            f"(Sim/Não)"
        )

    @staticmethod
    def _format_cartao_request() -> str:
        return (
            "Não encontrei cartão cadastrado. Informe os dados:\n"
            "Banco: [nome]\nÚltimos 4 dígitos: [XXXX]\n"
            "Vencimento: [MM/AAAA]\nBandeira: [Visa/Master/etc]\nLimite: [valor]"
        )


agent_service = AgentService()
