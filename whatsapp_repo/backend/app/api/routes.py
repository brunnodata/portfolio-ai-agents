import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.database import async_session_factory, get_db
from app.schemas import DashboardData, LoginRequest, TokenResponse, WebhookMessage
from app.services.agent import agent_service
from app.services.ai import ai_service
from app.services.dashboard import dashboard_service
from app.services.events import event_broadcaster
from app.services.evolution import evolution_client
from app.services.queue import QueueItem, message_queue
from app.services.repository import lancamento_repo

logger = logging.getLogger(__name__)
settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter()
ALGORITHM = "HS256"


def create_access_token(data: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    payload = {**data, "exp": expire}
    return jwt.encode(payload, settings.api_secret_key, algorithm=ALGORITHM)


async def verify_token(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    token = authorization.split(" ", 1)[1]
    try:
        return jwt.decode(token, settings.api_secret_key, algorithms=[ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado ou inválido") from e


def verify_webhook_secret(request: Request) -> None:
    secret = request.headers.get("x-webhook-secret") or request.headers.get("apikey", "")
    if settings.webhook_secret and secret != settings.webhook_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook não autorizado")


def verify_whitelist(phone: str) -> None:
    if not settings.whitelist_phones:
        return
    normalized = evolution_client._normalize_phone(phone)
    allowed = [evolution_client._normalize_phone(p) for p in settings.whitelist_phones]
    if normalized not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Número não autorizado")


async def notify_dashboard(event: dict) -> None:
    await event_broadcaster.publish({"type": "refresh", **event})


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    if body.username != settings.dashboard_username or body.password != settings.dashboard_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")
    token = create_access_token({"sub": body.username})
    return TokenResponse(access_token=token)


@router.post("/webhook/evolution")
async def evolution_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    verify_webhook_secret(request)
    body = await request.json()
    webhook = WebhookMessage(**body) if isinstance(body, dict) else WebhookMessage()

    event = webhook.event or body.get("event", "")
    if event not in ("messages.upsert", "MESSAGES_UPSERT", "message"):
        return {"status": "ignored", "event": event}

    data = webhook.data or body.get("data", body)
    if isinstance(data, list):
        data = data[0] if data else {}

    phone = evolution_client.extract_phone_from_payload(data)
    if not phone:
        return {"status": "no_phone"}

    verify_whitelist(phone)
    msg_info = evolution_client.extract_message_info(data)

    if msg_info["tipo"] in ("audio", "imagem", "documento"):

        async def media_handler(p: str, mtype: str, payload: dict) -> None:
            async with async_session_factory() as session:
                text = payload.get("text", "")
                if mtype == "audio" and payload.get("media_bytes"):
                    text = await ai_service.transcribe_audio(payload["media_bytes"])
                elif mtype in ("imagem", "documento") and payload.get("media_bytes"):
                    text = await ai_service.extract_from_image(payload["media_bytes"], payload.get("caption", ""))
                info = payload["msg_info"]
                await agent_service.process_message(session, p, info, text, notify_dashboard)
                await session.commit()

        media_bytes = await evolution_client.get_media_base64(data)
        await message_queue.enqueue(
            QueueItem(
                phone=phone,
                message_type=msg_info["tipo"],
                payload={
                    "msg_info": msg_info,
                    "media_bytes": media_bytes,
                    "caption": msg_info.get("conteudo", ""),
                    "text": "",
                },
                handler=media_handler,
            )
        )
        return {"status": "queued", "type": msg_info["tipo"]}

    text = msg_info["conteudo"]
    if not text:
        return {"status": "empty"}

    result = await agent_service.process_message(db, phone, msg_info, text, notify_dashboard)
    return {"status": "processed", "response": result}


@router.get("/api/dashboard", response_model=DashboardData)
async def get_dashboard(db: AsyncSession = Depends(get_db), _user=Depends(verify_token)):
    return await dashboard_service.get_dashboard_data(db)


@router.get("/api/lancamentos")
async def list_lancamentos(
    db: AsyncSession = Depends(get_db),
    _user=Depends(verify_token),
    limit: int = 50,
):
    lancamentos = await lancamento_repo.list_recentes(db, limit)
    return [
        {
            "id": l.id,
            "estabelecimento": l.estabelecimento.nome_exibicao,
            "setor": l.setor.nome,
            "tipo": l.tipo,
            "valor": float(l.valor),
            "parcelas": l.parcelas,
            "data_hora": l.data_hora.isoformat(),
            "origem": l.origem,
        }
        for l in lancamentos
    ]


async def verify_token_query(token: str = "") -> dict:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    try:
        return jwt.decode(token, settings.api_secret_key, algorithms=[ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado ou inválido") from e


@router.get("/api/events")
async def sse_events(token: str = "", _user=Depends(verify_token_query)):
    return EventSourceResponse(event_broadcaster.event_stream())


@router.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
