import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.schemas import ExtracaoLancamento
from app.services.ai import ai_service
from app.services.evolution import evolution_client
from app.services.repository import ESSENTIAL_FIELDS, conversa_repo, lancamento_repo
from app.models import Cartao, HistoricoMensagem, TransacaoPendente

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

        await evolution_client.send_text(phone, "⏳")

        ctx = await self.conversa.get_context(db, phone)
        pendente = await self.conversa.get_pendente_ativa(db, phone)

        if pendente and not msg_info.get("skip_context_check"):
            mudou = await ai_service.check_context_change(
                pendente.campos_capturados, processed_text
            )
            if mudou or await self._is_new_intent(processed_text):
                await self.conversa.discard_pendente(db, pendente)
                pendente = None

        if ctx.estado == "aguardando_confirmacao":
            return await self._handle_confirmation(db, phone, processed_text, ctx, notify_callback)

        if ctx.estado == "cadastro_cartao":
            return await self._handle_cadastro_cartao(db, phone, processed_text, ctx, historico, notify_callback)

        if ctx.estado == "escolher_cartao_padrao":
            return await self._handle_escolha_cartao(db, phone, processed_text, ctx, historico, notify_callback)

        if ctx.estado == "aguardando_apagar":
            return await self._handle_apagar_confirmacao(db, phone, processed_text, ctx, notify_callback)

        if pendente:
            return await self._handle_pendente_completion(
                db, phone, processed_text, pendente, origem, message_id, key_id, historico, notify_callback
            )

        extracao = await ai_service.extract_structured(
            processed_text, context_messages=ctx.mensagens
        )
        await self.conversa.add_message(db, phone, "user", processed_text)

        return await self._route_intent(
            db, phone, extracao, origem, message_id, key_id, historico, notify_callback
        )

    async def _route_intent(
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
        if extracao.intencao == "consulta":
            return await self._handle_consulta(db, phone, extracao)

        if extracao.intencao == "correcao":
            return await self._handle_correcao(db, phone)

        if extracao.intencao == "resumo_mes":
            return await self._handle_resumo(db, phone)

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
            return self._format_cartao_request()

        cartao = await self._resolve_cartao(db, phone, cartoes)
        if cartao is None:
            lista = "\n".join(f"{i+1}. {c.banco_origem} ****{c.ultimos_4_digitos}" for i, c in enumerate(cartoes))
            await self.conversa.set_estado(
                db, phone, "escolher_cartao",
                {"extracao": extracao.model_dump(mode="json"), "origem": origem, "cartoes": [c.id for c in cartoes]},
            )
            return f"Em qual cartão registrar?\n{lista}\n\nResponda com o número."

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
            return self._format_confirmacao(extracao)

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
        lanc = await self.repo.create_lancamento(db, extracao, cartao_id, origem, message_id, key_id)
        historico.status = "processado"
        historico.conteudo_processado = json.dumps(extracao.model_dump(mode="json"), ensure_ascii=False)
        await self.conversa.set_estado(db, phone, None, {})

        msg = self._format_success(extracao)
        await evolution_client.send_text(phone, f"✅ {msg}")
        await self.conversa.add_message(db, phone, "assistant", msg)

        if notify_callback:
            await notify_callback({"type": "lancamento_criado", "id": lanc.id})

        await self._check_novo_estabelecimento(db, phone, extracao)
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
                "estabelecimento": extracao.estabelecimento,
                "setor": extracao.setor,
                "tipo": extracao.tipo,
                "valor": extracao.valor,
                "parcelas": extracao.parcelas,
            }.items()
            if v is not None
        }
        await self.conversa.create_pendente(
            db, phone, capturados, faltantes, origem, message_id, key_id, historico.id
        )
        historico.status = "pendente"
        historico.conteudo_processado = json.dumps({"capturados": capturados, "faltantes": faltantes})

        msg = self._format_partial(capturados, faltantes)
        await evolution_client.send_text(phone, msg)
        await self.conversa.add_message(db, phone, "assistant", msg)
        return msg

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
        focus = {"capturados": pendente.campos_capturados, "faltantes": pendente.campos_faltantes}
        extracao = await ai_service.extract_structured(text, focus_pending=focus)

        capturados = dict(pendente.campos_capturados)
        for field in ESSENTIAL_FIELDS:
            val = getattr(extracao, field, None)
            if val is not None:
                capturados[field] = str(val) if field == "valor" else val

        faltantes = [f for f in ESSENTIAL_FIELDS if not capturados.get(f)]
        if faltantes:
            pendente.campos_capturados = capturados
            pendente.campos_faltantes = faltantes
            pendente.tentativas_imagem = (pendente.tentativas_imagem or 0) + 1
            if pendente.tentativas_imagem >= 3 and origem == "whatsapp-foto":
                pendente.status = "erro"
                historico.status = "erro"
                msg = "Não consegui processar a imagem após 3 tentativas. Tente digitar os dados manualmente."
                await evolution_client.send_text(phone, msg)
                return msg
            msg = self._format_partial(capturados, faltantes)
            await evolution_client.send_text(phone, msg)
            return msg

        merged = ExtracaoLancamento(
            estabelecimento=capturados.get("estabelecimento"),
            setor=capturados.get("setor"),
            tipo=capturados.get("tipo"),
            valor=Decimal(capturados["valor"]) if capturados.get("valor") else None,
            parcelas=capturados.get("parcelas"),
            confianca=0.9,
        )
        pendente.status = "processado"

        cartoes = await self.repo.list_cartoes(db)
        cartao = await self._resolve_cartao(db, phone, cartoes)
        if not cartao:
            return self._format_cartao_request()

        return await self._persist_and_confirm(
            db, phone, merged, cartao.id, pendente.origem or origem,
            pendente.message_id or message_id, pendente.key_id or key_id,
            historico, notify_callback,
        )

    async def _handle_confirmation(
        self, db: AsyncSession, phone: str, text: str, ctx, notify_callback
    ) -> str:
        lower = text.lower().strip()
        dados = ctx.dados_estado or {}
        if lower in ("sim", "s", "confirmo", "ok", "yes"):
            extracao = ExtracaoLancamento(**dados.get("extracao", {}))
            if extracao.valor:
                extracao.valor = Decimal(str(extracao.valor))
            historico = HistoricoMensagem(
                tipo_mensagem="texto", conteudo_original=text, status="processando", phone_number=phone
            )
            db.add(historico)
            await db.flush()
            return await self._persist_and_confirm(
                db, phone, extracao, dados["cartao_id"], dados.get("origem", "whatsapp-texto"),
                dados.get("message_id"), dados.get("key_id"), historico, notify_callback,
            )
        await self.conversa.set_estado(db, phone, None, {})
        return "Lançamento cancelado."

    async def _handle_cadastro_cartao(
        self, db: AsyncSession, phone: str, text: str, ctx, historico, notify_callback
    ) -> str:
        parsed = await ai_service.parse_cartao_data(text)
        if not parsed or not parsed.get("banco_origem"):
            return (
                "Não entendi os dados do cartão. Envie no formato:\n"
                "Banco: Nubank\nÚltimos 4 dígitos: 1234\nVencimento: 12/2028\nBandeira: Mastercard\nLimite: 5000"
            )

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

        dados = ctx.dados_estado or {}
        dados["cartao_id"] = cartao.id
        await self.conversa.set_estado(db, phone, "escolher_cartao_padrao", dados)
        return (
            f"Cartão {cartao.banco_origem} ****{cartao.ultimos_4_digitos} cadastrado!\n"
            "Esse será seu cartão padrão? (sim/nao)\n"
            "Se não, você escolherá o cartão a cada lançamento."
        )

    async def _handle_escolha_cartao(
        self, db: AsyncSession, phone: str, text: str, ctx, historico, notify_callback
    ) -> str:
        dados = ctx.dados_estado or {}
        lower = text.lower().strip()

        if ctx.estado == "escolher_cartao_padrao":
            cartao = await db.get(Cartao, dados.get("cartao_id"))
            if lower in ("sim", "s", "yes"):
                if cartao:
                    cartao.cartao_padrao = "sim"
            await self.conversa.set_estado(db, phone, None, {})
            extracao = ExtracaoLancamento(**dados.get("extracao", {}))
            if extracao.valor:
                extracao.valor = Decimal(str(extracao.valor))
            return await self._persist_and_confirm(
                db, phone, extracao, dados["cartao_id"], dados.get("origem", "whatsapp-texto"),
                dados.get("message_id"), dados.get("key_id"), historico, notify_callback,
            )

        try:
            idx = int(lower) - 1
            cartao_ids = dados.get("cartoes", [])
            if 0 <= idx < len(cartao_ids):
                dados["cartao_id"] = cartao_ids[idx]
                await self.conversa.set_estado(db, phone, "aguardando_confirmacao", dados)
                extracao = ExtracaoLancamento(**dados.get("extracao", {}))
                return self._format_confirmacao(extracao)
        except ValueError:
            pass
        return "Responda com o número do cartão da lista."

    async def _handle_consulta(self, db: AsyncSession, phone: str, extracao: ExtracaoLancamento) -> str:
        now = datetime.now(timezone.utc)
        setor = (extracao.setor or "outros").lower()
        total = await self.repo.sum_by_setor_mes(db, setor, now.month, now.year)
        msg = f"Você gastou R$ {total:,.2f} em {setor} este mês.".replace(",", "X").replace(".", ",").replace("X", ".")
        await evolution_client.send_text(phone, msg)
        return msg

    async def _handle_resumo(self, db: AsyncSession, phone: str) -> str:
        now = datetime.now(timezone.utc)
        total = await self.repo.sum_mes(db, now.month, now.year)
        por_setor = await self.repo.gastos_por_setor_mes(db, now.month, now.year)
        lines = [f"📊 Resumo de {now.strftime('%m/%Y')}:", f"Total: R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")]
        for setor, val in por_setor[:5]:
            lines.append(f"• {setor}: R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        msg = "\n".join(lines)
        await evolution_client.send_text(phone, msg)
        return msg

    async def _handle_correcao(self, db: AsyncSession, phone: str) -> str:
        ultimo = await self.repo.get_ultimo_lancamento(db)
        if not ultimo:
            return "Não há lançamentos para remover."
        estab = ultimo.estabelecimento.nome_exibicao
        valor = ultimo.valor
        setor = ultimo.setor.nome
        await self.conversa.set_estado(db, phone, "aguardando_apagar", {"lancamento_id": ultimo.id})
        msg = f"Deseja apagar: {estab} — R$ {valor} — {setor}? (Sim/Não)"
        await evolution_client.send_text(phone, msg)
        return msg

    async def _handle_apagar_confirmacao(self, db: AsyncSession, phone: str, text: str, ctx, notify_callback) -> str:
        lower = text.lower().strip()
        dados = ctx.dados_estado or {}
        if lower in ("sim", "s", "confirmo"):
            await self.repo.delete_lancamento(db, dados["lancamento_id"])
            await self.conversa.set_estado(db, phone, None, {})
            msg = "✅ Lançamento removido."
            await evolution_client.send_text(phone, msg)
            if notify_callback:
                await notify_callback({"type": "lancamento_removido", "id": dados["lancamento_id"]})
            return msg
        await self.conversa.set_estado(db, phone, None, {})
        return "Operação cancelada."

    async def _resolve_cartao(self, db, phone, cartoes):
        if len(cartoes) == 1:
            return cartoes[0]
        padrao = await self.repo.get_default_cartao(db)
        if padrao:
            return padrao
        return None

    async def _check_novo_estabelecimento(self, db, phone, extracao: ExtracaoLancamento) -> None:
        setor = (extracao.setor or "").lower()
        if setor in ("gasolina", "restaurante", "mercado") and extracao.estabelecimento:
            msg = f"Quer guardar '{extracao.estabelecimento}' como nome personalizado para buscas futuras? (sim/nao)"
            await evolution_client.send_text(phone, msg)

    @staticmethod
    def _check_missing_fields(extracao: ExtracaoLancamento) -> list[str]:
        missing = []
        if not extracao.estabelecimento:
            missing.append("estabelecimento")
        if not extracao.setor:
            missing.append("setor")
        if not extracao.tipo:
            missing.append("tipo")
        if extracao.valor is None:
            missing.append("valor")
        return missing

    @staticmethod
    def _format_success(extracao: ExtracaoLancamento) -> str:
        tipo_label = (extracao.tipo or "a_vista").replace("_", " ")
        valor = extracao.valor or Decimal("0")
        return (
            f"Cadastrei: {extracao.estabelecimento} — "
            f"R$ {valor:,.2f} — {extracao.setor} — {tipo_label}"
        ).replace(",", "X").replace(".", ",").replace("X", ".")

    @staticmethod
    def _format_partial(capturados: dict, faltantes: list[str]) -> str:
        lines = ["⚠️ Capturei:"]
        for k, v in capturados.items():
            lines.append(f"• {k}: {v}")
        lines.append(f"❌ Faltou: {', '.join(faltantes)}")
        lines.append("Você pode: digitar, enviar áudio ou reenviar a mídia.")
        return "\n".join(lines)

    @staticmethod
    def _format_confirmacao(extracao: ExtracaoLancamento) -> str:
        return (
            f"Confirma o lançamento?\n"
            f"{extracao.estabelecimento} — R$ {extracao.valor} — {extracao.setor} — {extracao.tipo}\n"
            f"(Sim/Não)"
        )

    @staticmethod
    def _format_cartao_request() -> str:
        return (
            "Não encontrei cartão cadastrado. Informe os dados:\n"
            "Banco: [nome]\nÚltimos 4 dígitos: [XXXX]\n"
            "Vencimento: [MM/AAAA]\nBandeira: [Visa/Master/etc]\nLimite: [valor]"
        )

    @staticmethod
    async def _is_new_intent(text: str) -> bool:
        lower = text.lower()
        keywords = ["gastei", "paguei", "comprei", "apaga", "quanto", "resumo"]
        return any(k in lower for k in keywords)


agent_service = AgentService()
