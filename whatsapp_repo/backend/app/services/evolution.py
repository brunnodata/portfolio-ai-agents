import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EvolutionAPIClient:
    def __init__(self) -> None:
        self.base_url = settings.evolution_api_url.rstrip("/")
        self.api_key = settings.evolution_api_key
        self.instance = settings.evolution_instance

    def _headers(self) -> dict[str, str]:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    async def send_text(self, phone: str, text: str) -> dict[str, Any] | None:
        number = self._normalize_phone(phone)
        url = f"{self.base_url}/message/sendText/{self.instance}"
        payload = {"number": number, "text": text}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=self._headers())
                response.raise_for_status()
                return response.json()
        except Exception:
            logger.exception("Falha ao enviar mensagem para %s", number)
            return None

    async def send_reaction(self, phone: str, message_id: str, emoji: str) -> None:
        number = self._normalize_phone(phone)
        url = f"{self.base_url}/message/sendReaction/{self.instance}"
        payload = {"key": {"remoteJid": f"{number}@s.whatsapp.net", "id": message_id}, "reaction": emoji}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(url, json=payload, headers=self._headers())
        except Exception:
            logger.debug("Reação não enviada (opcional)")

    async def get_media_base64(self, message_data: dict[str, Any]) -> bytes | None:
        url = f"{self.base_url}/chat/getBase64FromMediaMessage/{self.instance}"
        payload = {"message": message_data}
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload, headers=self._headers())
                response.raise_for_status()
                data = response.json()
                import base64

                b64 = data.get("base64") or data.get("data", {}).get("base64")
                if b64:
                    return base64.b64decode(b64)
        except Exception:
            logger.exception("Falha ao obter mídia")
        return None

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        digits = "".join(c for c in phone if c.isdigit())
        if not digits.startswith("55") and len(digits) <= 11:
            digits = "55" + digits
        return digits

    @staticmethod
    def is_outgoing_message(data: dict[str, Any]) -> bool:
        """Ignora mensagens enviadas pelo próprio bot (evita loop no webhook)."""
        key = data.get("key", {})
        return bool(key.get("fromMe") or data.get("fromMe"))

    @staticmethod
    def extract_phone_from_payload(data: dict[str, Any]) -> str | None:
        key = data.get("key", {})
        remote_jid = key.get("remoteJid", "")
        if "@" in remote_jid:
            return remote_jid.split("@")[0]
        return data.get("sender") or data.get("from")

    @staticmethod
    def extract_message_info(data: dict[str, Any]) -> dict[str, Any]:
        key = data.get("key", {})
        message = data.get("message", {})
        message_id = key.get("id")
        key_id = key.get("id")

        msg_type = "texto"
        content = ""
        media_data = None

        if "conversation" in message:
            content = message["conversation"]
        elif "extendedTextMessage" in message:
            content = message["extendedTextMessage"].get("text", "")
        elif "audioMessage" in message:
            msg_type = "audio"
            media_data = message["audioMessage"]
        elif "imageMessage" in message:
            msg_type = "imagem"
            media_data = message["imageMessage"]
            content = message["imageMessage"].get("caption", "")
        elif "documentMessage" in message:
            msg_type = "documento"
            media_data = message["documentMessage"]

        return {
            "message_id": message_id,
            "key_id": key_id,
            "tipo": msg_type,
            "conteudo": content,
            "media": media_data,
            "raw": data,
            "timestamp": datetime.fromtimestamp(
                data.get("messageTimestamp", 0), tz=timezone.utc
            )
            if data.get("messageTimestamp")
            else datetime.now(timezone.utc),
        }


evolution_client = EvolutionAPIClient()
