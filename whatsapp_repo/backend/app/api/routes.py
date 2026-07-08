import logging
from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.database import async_session_factory, get_db
from app.schemas import (
    CartaoCreate,
    CartaoResponse,
    CartaoUpdate,
    DashboardData,
    LoginRequest,
    TokenResponse,
    WebhookMessage,
)
from app.services.agent import agent_service
from app.services.ai import ai_service
from app.services.dashboard import dashboard_service
from app.services.events import event_broadcaster
from app.services.evolution import evolution_client
from app.services.llm_cost import llm_cost_tracker
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
    if not settings.webhook_secret and not settings.evolution_api_key:
        return
    allowed = {settings.webhook_secret, settings.evolution_api_key} - {""}
    if secret not in allowed:
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


def _parse_vencimento(value: str | None) -> date_type | None:
    if not value:
        return None
    try:
        return date_type.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _cartao_to_response(cartao) -> CartaoResponse:
    valores = cartao.valores_futuros or {}
    return CartaoResponse(
        id=cartao.id,
        banco_origem=cartao.banco_origem,
        ultimos_4_digitos=cartao.ultimos_4_digitos,
        vencimento=cartao.vencimento.isoformat() if cartao.vencimento else None,
        bandeira=cartao.bandeira,
        limite_total=float(cartao.limite_total) if cartao.limite_total is not None else None,
        limite_em_uso=float(cartao.limite_em_uso) if cartao.limite_em_uso is not None else None,
        limite_restante=float(cartao.limite_restante) if cartao.limite_restante is not None else None,
        qt_assinaturas=cartao.qt_assinaturas or 0,
        valores_futuros={k: float(v) for k, v in valores.items()},
        cartao_padrao=cartao.cartao_padrao,
        obs=cartao.obs,
    )


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
        logger.info("Webhook ignorado: evento=%s", event)
        return {"status": "ignored", "event": event}

    data = webhook.data or body.get("data", body)
    if isinstance(data, list):
        data = data[0] if data else {}

    if evolution_client.is_outgoing_message(data):
        logger.info("Webhook ignorado: mensagem enviada pelo proprio numero (fromMe)")
        return {"status": "ignored", "reason": "fromMe"}

    phone = evolution_client.extract_phone_from_payload(data)
    if not phone:
        logger.info("Webhook sem telefone no payload")
        return {"status": "no_phone"}

    verify_whitelist(phone)
    msg_info = evolution_client.extract_message_info(data)
    logger.info("Webhook recebido: phone=%s tipo=%s", phone, msg_info["tipo"])

    if msg_info["tipo"] in ("audio", "imagem", "documento"):
        await evolution_client.send_text(phone, "⏳ Processando mídia...")

        async def media_handler(p: str, mtype: str, payload: dict) -> None:
            async with async_session_factory() as session:
                text = payload.get("text", "")
                if mtype == "audio" and payload.get("media_bytes"):
                    text = await ai_service.transcribe_audio(payload["media_bytes"])
                elif mtype in ("imagem", "documento") and payload.get("media_bytes"):
                    text = await ai_service.extract_from_image(payload["media_bytes"], payload.get("caption", ""))
                info = {**payload["msg_info"], "skip_hourglass": True}
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
        logger.info("Webhook sem texto extraido")
        return {"status": "empty"}

    result = await agent_service.process_message(db, phone, msg_info, text, notify_dashboard)
    logger.info("Webhook processado para %s", phone)
    return {"status": "processed", "response": result}


@router.get("/api/dashboard", response_model=DashboardData)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    _user=Depends(verify_token),
    setor: str | None = None,
    tipo: str | None = None,
    mes: int | None = None,
    ano: int | None = None,
):
    try:
        return await dashboard_service.get_dashboard_data(db, setor=setor, tipo=tipo, mes=mes, ano=ano)
    except Exception as e:
        logger.exception("Erro ao carregar dashboard")
        raise HTTPException(status_code=500, detail=f"Erro ao carregar dashboard: {e}") from e


@router.get("/api/cartoes", response_model=list[CartaoResponse])
async def list_cartoes(
    db: AsyncSession = Depends(get_db),
    _user=Depends(verify_token),
):
    cartoes = await lancamento_repo.list_cartoes(db)
    return [_cartao_to_response(c) for c in cartoes]


@router.post("/api/cartoes", response_model=CartaoResponse, status_code=status.HTTP_201_CREATED)
async def create_cartao(
    body: CartaoCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(verify_token),
):
    cartao = await lancamento_repo.create_cartao(
        db,
        {
            "banco_origem": body.banco_origem.strip(),
            "ultimos_4_digitos": body.ultimos_4_digitos[-4:],
            "vencimento": _parse_vencimento(body.vencimento),
            "bandeira": body.bandeira,
            "limite_total": body.limite_total,
            "cartao_padrao": body.cartao_padrao or "nao",
            "obs": body.obs,
        },
    )
    return _cartao_to_response(cartao)


@router.patch("/api/cartoes/{cartao_id}", response_model=CartaoResponse)
async def update_cartao(
    cartao_id: int,
    body: CartaoUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(verify_token),
):
    payload = body.model_dump(exclude_unset=True)
    if "vencimento" in payload:
        payload["vencimento"] = _parse_vencimento(payload.get("vencimento"))
    if payload.get("ultimos_4_digitos"):
        payload["ultimos_4_digitos"] = payload["ultimos_4_digitos"][-4:]
    cartao = await lancamento_repo.update_cartao(db, cartao_id, payload)
    if not cartao:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cartão não encontrado")
    return _cartao_to_response(cartao)


@router.patch("/api/cartoes/{cartao_id}/padrao", response_model=CartaoResponse)
async def set_cartao_padrao(
    cartao_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(verify_token),
):
    cartao = await lancamento_repo.set_cartao_padrao(db, cartao_id)
    if not cartao:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cartão não encontrado")
    return _cartao_to_response(cartao)


@router.delete("/api/cartoes/{cartao_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cartao(
    cartao_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(verify_token),
):
    ok, msg = await lancamento_repo.delete_cartao(db, cartao_id)
    if not ok:
        status_code = status.HTTP_404_NOT_FOUND if msg == "Cartão não encontrado" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=msg)


@router.get("/api/lancamentos")
async def list_lancamentos(
    db: AsyncSession = Depends(get_db),
    _user=Depends(verify_token),
    limit: int = 50,
    setor: str | None = None,
    tipo: str | None = None,
    mes: int | None = None,
    ano: int | None = None,
    cartao_id: int | None = None,
):
    lancamentos = await lancamento_repo.list_filtrados(
        db, setor=setor, tipo=tipo, mes=mes, ano=ano, cartao_id=cartao_id, limit=limit
    )
    return [
        {
            "id": l.id,
            "item": l.item,
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


@router.get("/api/admin/llm-cost")
async def admin_llm_cost(_user=Depends(verify_token)):
    return llm_cost_tracker.snapshot()


@router.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
