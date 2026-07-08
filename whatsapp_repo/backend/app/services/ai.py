import base64
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.schemas import ExtracaoLancamento
from app.services.llm_cost import llm_cost_tracker

logger = logging.getLogger(__name__)
settings = get_settings()

EXTRACTION_SYSTEM_PROMPT = """Você é o Interpretador do GastoZap: analisa a mensagem do usuário e devolve JSON estruturado.
Nunca peça classificação de setor ao usuário — você SEMPRE infere o setor.

Identifique a intenção: novo_gasto, correcao, consulta, resumo_mes, cadastro_cartao, confirmacao, outro.

Para intenção **consulta**, defina também **tipo_consulta**:
- "limite": pergunta sobre limite do cartão, saldo disponível ou quanto ainda pode gastar
- "setor": pergunta sobre gasto em uma categoria específica (preencha setor inferido)
- "total_mes": pergunta sobre gasto total do mês sem categoria específica

Interprete pelo significado da mensagem, não por palavras-chave fixas.

Para intenção **correcao**, extraia também:
- acao_correcao: "apagar" ou "editar" (somente se ficar claro na mensagem)
- campos_correcao: objeto com campos a alterar (item, estabelecimento, setor, tipo, valor, parcelas)
- lancamento_alvo: "ultimo" (padrão) ou "especifico"

Para intenção **cadastro_cartao**, o usuário está informando dados de um cartão de crédito.

Para gastos (novo_gasto), extraia:
- item (o que comprou / descrição curta: compras, computador, gasolina, lanche…). OBRIGATÓRIO se der para inferir.
- estabelecimento (nome da loja/local) — opcional; só preencha se aparecer na mensagem
- setor (SEMPRE preencha; você INFERE, nunca peça): mercado, ferramenta, lanche, cursos, viagem, gasolina, restaurante, assinatura, outros
- tipo: a_vista, assinatura, fixo, parcelado — default a_vista
- valor (número decimal)
- parcelas (ex: "1 de 12" ou null se à vista)
- data_hora (ISO 8601; use agora se não informado)

Regras de inferência de setor (exemplos):
- mercado / supermercado / vendas / compras de casa → mercado
- posto / combustível / gasolina → gasolina
- restaurante / iFood / marmita → restaurante
- padaria / lanche / café → lanche
- Kalunga / papelaria / ferramenta → ferramenta (ou outros se for eletrônico)
- Netflix / Spotify → assinatura
- Se inconsistente ou vago → outros

campos_faltantes: liste SOMENTE o que o usuário ainda precisa informar: valor e/ou item (descrição do que comprou).
NUNCA inclua setor, tipo ou estabelecimento em campos_faltantes.
Se o usuário não informou o estabelecimento, deixe null — não peça automaticamente.

confianca: 0.0 a 1.0.
Responda APENAS em JSON válido com os campos do schema."""

PENDING_FIELD_PROMPT = """O usuário está completando dados faltantes de um lançamento.
Campos já capturados: {capturados}
Campos faltantes: {faltantes}

Extraia a informação pendente. Você deve INFERIR setor a partir do item/estabelecimento/mensagem
(nunca peça setor). Atualize item, valor, estabelecimento se mencionados e preencha setor inferido.
Se a mensagem indica um gasto/comando completamente novo sem relação, defina mudou_contexto=true.
Responda em JSON."""

INTENT_PROMPT = """Analise se a nova mensagem do usuário está:
1. Completando dados pendentes de uma transação anterior
2. Ou iniciando um novo gasto/comando (mudança de contexto)

Interprete pelo significado, não por palavras exatas.

Contexto pendente: {pendente}
Nova mensagem: {mensagem}

Responda JSON: {{"relacionado": true/false, "motivo": "..."}}"""

STATE_RESPONSE_PROMPT = """Você interpreta respostas em fluxos de conversa financeiros.
Interprete pelo significado da mensagem, não por palavras exatas.

Estado atual: {estado}
Contexto: {contexto}
Mensagem do usuário: {mensagem}

Retorne JSON conforme o estado:

- aguardando_confirmacao, aguardando_correcao_confirmacao, aguardando_apagar:
  {{"confirmacao": "sim" | "nao" | "indefinido"}}

- escolher_cartao_padrao:
  {{"cartao_padrao": "sim" | "nao" | "indefinido"}}

- escolher_cartao:
  {{"indice": <número inteiro da opção na lista, base 1, ou null>}}

- aguardando_nome_personalizado:
  {{"aceitar_sugestao": <true/false>, "nome": <nome informado ou null>, "recusou": <true/false>}}

- aguardando_correcao_campo:
  {{"item": ..., "estabelecimento": ..., "setor": ..., "tipo": ..., "valor": ..., "parcelas": ...}}
  (somente campos mencionados; valor numérico se houver)
"""


class AIService:
    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self.model = settings.openai_model

    async def transcribe_audio(self, audio_bytes: bytes, filename: str = "audio.ogg") -> str:
        if not self.client:
            return ""
        try:
            import io

            buffer = io.BytesIO(audio_bytes)
            buffer.name = filename
            transcript = await self.client.audio.transcriptions.create(
                model=settings.whisper_model, file=buffer, language="pt"
            )
            return transcript.text
        except Exception:
            logger.exception("Erro na transcrição")
            return ""

    async def extract_from_image(self, image_bytes: bytes, caption: str = "") -> str:
        if not self.client:
            return caption
        try:
            b64 = base64.b64encode(image_bytes).decode()
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extraia todos os dados visíveis desta nota fiscal ou extrato: estabelecimento, valor, data, itens. Responda em texto livre em português.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            },
                        ],
                    }
                ],
                max_tokens=1000,
            )
            usage = getattr(response, "usage", None)
            if usage:
                llm_cost_tracker.track_usage(
                    getattr(usage, "prompt_tokens", 0),
                    getattr(usage, "completion_tokens", 0),
                )
            return response.choices[0].message.content or caption
        except Exception:
            logger.exception("Erro no OCR/visão")
            return caption

    async def extract_structured(
        self,
        text: str,
        context_messages: list[dict[str, str]] | None = None,
        focus_pending: dict[str, Any] | None = None,
    ) -> ExtracaoLancamento:
        if not self.client:
            return self._fallback_extraction(text)

        messages: list[dict[str, str]] = [{"role": "system", "content": EXTRACTION_SYSTEM_PROMPT}]
        if context_messages:
            for msg in context_messages[-10:]:
                messages.append(msg)
        if focus_pending:
            messages.append(
                {
                    "role": "system",
                    "content": PENDING_FIELD_PROMPT.format(
                        capturados=json.dumps(focus_pending.get("capturados", {}), ensure_ascii=False),
                        faltantes=json.dumps(focus_pending.get("faltantes", []), ensure_ascii=False),
                    ),
                }
            )
        messages.append({"role": "user", "content": text})

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            usage = getattr(response, "usage", None)
            if usage:
                llm_cost_tracker.track_usage(
                    getattr(usage, "prompt_tokens", 0),
                    getattr(usage, "completion_tokens", 0),
                )
            raw = json.loads(response.choices[0].message.content or "{}")
            return self._parse_extraction(raw)
        except Exception:
            logger.exception("Erro na extração estruturada")
            return self._fallback_extraction(text)

    async def check_context_change(self, pendente: dict[str, Any], mensagem: str) -> bool:
        if not self.client:
            return False
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": INTENT_PROMPT.format(
                            pendente=json.dumps(pendente, ensure_ascii=False),
                            mensagem=mensagem,
                        ),
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            usage = getattr(response, "usage", None)
            if usage:
                llm_cost_tracker.track_usage(
                    getattr(usage, "prompt_tokens", 0),
                    getattr(usage, "completion_tokens", 0),
                )
            result = json.loads(response.choices[0].message.content or "{}")
            return not result.get("relacionado", True)
        except Exception:
            return False

    async def interpret_state_response(
        self, estado: str, text: str, contexto: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.client:
            return self._fallback_state_response(estado, text, contexto or {})

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": STATE_RESPONSE_PROMPT.format(
                            estado=estado,
                            contexto=json.dumps(contexto or {}, ensure_ascii=False),
                            mensagem=text,
                        ),
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            usage = getattr(response, "usage", None)
            if usage:
                llm_cost_tracker.track_usage(
                    getattr(usage, "prompt_tokens", 0),
                    getattr(usage, "completion_tokens", 0),
                )
            return json.loads(response.choices[0].message.content or "{}")
        except Exception:
            logger.exception("Erro ao interpretar resposta de estado")
            return self._fallback_state_response(estado, text, contexto or {})

    @staticmethod
    def _fallback_state_response(estado: str, text: str, contexto: dict[str, Any]) -> dict[str, Any]:
        """Sem modelo disponível: não inventa intenção por palavras-chave."""
        if estado == "escolher_cartao":
            try:
                idx = int(text.strip())
                return {"indice": idx}
            except ValueError:
                return {"indice": None}
        return {}

    async def parse_cartao_data(self, text: str) -> dict[str, Any] | None:
        if not self.client:
            return None
        prompt = """Extraia dados de cartão de crédito do texto. Campos: banco_origem, ultimos_4_digitos, vencimento (YYYY-MM-DD), bandeira, limite_total.
Responda JSON ou null se não for cadastro de cartão."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": f"{prompt}\n\n{text}"}],
                response_format={"type": "json_object"},
            )
            usage = getattr(response, "usage", None)
            if usage:
                llm_cost_tracker.track_usage(
                    getattr(usage, "prompt_tokens", 0),
                    getattr(usage, "completion_tokens", 0),
                )
            return json.loads(response.choices[0].message.content or "{}")
        except Exception:
            return None

    def _parse_extraction(self, raw: dict[str, Any]) -> ExtracaoLancamento:
        valor = raw.get("valor")
        if valor is not None:
            valor = Decimal(str(valor))
        data_hora = raw.get("data_hora")
        if isinstance(data_hora, str):
            try:
                data_hora = datetime.fromisoformat(data_hora.replace("Z", "+00:00"))
            except ValueError:
                data_hora = None
        tipo_consulta = raw.get("tipo_consulta")
        if tipo_consulta not in ("limite", "setor", "total_mes"):
            tipo_consulta = None
        intencao = raw.get("intencao", "novo_gasto")
        if intencao not in (
            "novo_gasto", "correcao", "consulta", "resumo_mes", "cadastro_cartao", "confirmacao", "outro"
        ):
            intencao = "novo_gasto"
        acao_correcao = raw.get("acao_correcao")
        if acao_correcao not in ("apagar", "editar"):
            acao_correcao = None
        # Setor nunca é pedido ao usuário — remove se a IA colocar em campos_faltantes
        faltantes = [
            f for f in (raw.get("campos_faltantes") or [])
            if f not in ("setor", "tipo", "tipo_pagamento")
        ]
        setor = raw.get("setor") or "outros"
        return ExtracaoLancamento(
            intencao=intencao,
            estabelecimento=raw.get("estabelecimento"),
            item=raw.get("item"),
            setor=setor,
            tipo=raw.get("tipo") or "a_vista",
            valor=valor,
            parcelas=raw.get("parcelas"),
            data_hora=data_hora,
            confianca=float(raw.get("confianca", 0.5)),
            campos_faltantes=faltantes,
            resposta_texto=raw.get("resposta_texto"),
            mudou_contexto=raw.get("mudou_contexto", False),
            acao_correcao=acao_correcao,
            campos_correcao=raw.get("campos_correcao"),
            lancamento_alvo=raw.get("lancamento_alvo", "ultimo"),
            tipo_consulta=tipo_consulta,
        )

    def _fallback_extraction(self, text: str) -> ExtracaoLancamento:
        """Modo degradado sem OpenAI: extrai apenas valor numérico, sem inferir intenção."""
        import re

        valor = None
        match = re.search(r"(\d+)[,.](\d{2})|(\d+)\s*reais?", text.lower())
        if match:
            if match.group(1):
                valor = Decimal(f"{match.group(1)}.{match.group(2)}")
            else:
                valor = Decimal(match.group(3))

        campos_faltantes = []
        if valor is None:
            campos_faltantes.append("valor")

        return ExtracaoLancamento(
            intencao="novo_gasto",
            valor=valor,
            confianca=0.2,
            campos_faltantes=campos_faltantes,
        )


ai_service = AIService()
