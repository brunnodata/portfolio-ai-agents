import base64
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.schemas import ExtracaoLancamento

logger = logging.getLogger(__name__)
settings = get_settings()

EXTRACTION_SYSTEM_PROMPT = """Você é um assistente financeiro que extrai dados estruturados de mensagens de gastos.

Identifique a intenção: novo_gasto, correcao, consulta, resumo_mes, cadastro_cartao, confirmacao, outro.

Para gastos, extraia:
- estabelecimento (nome da loja/local)
- setor (mercado, ferramenta, lanche, cursos, viagem, gasolina, restaurante, outros)
- tipo: a_vista, assinatura, fixo, parcelado
- valor (número decimal)
- parcelas (ex: "1 de 12" ou null se à vista)
- data_hora (ISO 8601, use agora se não informado)

Liste em campos_faltantes os campos essenciais ausentes: estabelecimento, setor, tipo, valor.
confianca: 0.0 a 1.0 indicando certeza da extração.

Responda APENAS em JSON válido com os campos do schema."""

PENDING_FIELD_PROMPT = """O usuário está completando dados faltantes de um lançamento.
Campos já capturados: {capturados}
Campos faltantes: {faltantes}

Extraia APENAS a informação pendente da mensagem. Responda em JSON com os campos atualizados.
Se a mensagem indica um gasto/comando completamente novo sem relação, defina mudou_contexto=true."""

INTENT_PROMPT = """Analise se a nova mensagem do usuário está:
1. Completando dados pendentes de uma transação anterior
2. Ou iniciando um novo gasto/comando (mudança de contexto)

Contexto pendente: {pendente}
Nova mensagem: {mensagem}

Responda JSON: {{"relacionado": true/false, "motivo": "..."}}"""


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
            result = json.loads(response.choices[0].message.content or "{}")
            return not result.get("relacionado", True)
        except Exception:
            return False

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
        return ExtracaoLancamento(
            intencao=raw.get("intencao", "novo_gasto"),
            estabelecimento=raw.get("estabelecimento"),
            setor=raw.get("setor"),
            tipo=raw.get("tipo"),
            valor=valor,
            parcelas=raw.get("parcelas"),
            data_hora=data_hora,
            confianca=float(raw.get("confianca", 0.5)),
            campos_faltantes=raw.get("campos_faltantes", []),
            resposta_texto=raw.get("resposta_texto"),
            mudou_contexto=raw.get("mudou_contexto", False),
        )

    def _fallback_extraction(self, text: str) -> ExtracaoLancamento:
        import re

        lower = text.lower()
        intencao = "novo_gasto"
        if any(w in lower for w in ["apaga", "remove", "corrige", "corrigir"]):
            intencao = "correcao"
        elif "quanto" in lower and "gastei" in lower:
            intencao = "consulta"
        elif "resumo" in lower:
            intencao = "resumo_mes"

        valor = None
        match = re.search(r"(\d+)[,.](\d{2})|(\d+)\s*reais?", lower)
        if match:
            if match.group(1):
                valor = Decimal(f"{match.group(1)}.{match.group(2)}")
            else:
                valor = Decimal(match.group(3))

        campos_faltantes = []
        if valor is None:
            campos_faltantes.append("valor")

        return ExtracaoLancamento(
            intencao=intencao,
            valor=valor,
            confianca=0.3 if campos_faltantes else 0.6,
            campos_faltantes=campos_faltantes,
        )


ai_service = AIService()
