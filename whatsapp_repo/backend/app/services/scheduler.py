import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.database import async_session_factory
from app.services.evolution import evolution_client
from app.services.repository import conversa_repo

logger = logging.getLogger(__name__)
settings = get_settings()
scheduler = AsyncIOScheduler()


async def daily_pending_alert() -> None:
    async with async_session_factory() as db:
        pendentes = await conversa_repo.list_pendentes_hoje(db)
        if not pendentes:
            return

        phones = {p.phone_number for p in pendentes}
        for phone in phones:
            items = [p for p in pendentes if p.phone_number == phone]
            lines = ["Ei, ficaram pendentes alguns lançamentos de hoje. Quer completar agora?", ""]
            for i, p in enumerate(items, 1):
                cap = p.campos_capturados or {}
                fal = p.campos_faltantes or []
                lines.append(f"{i}. Capturado: {cap} | Faltando: {', '.join(fal)}")
            await evolution_client.send_text(phone, "\n".join(lines))
        await db.commit()


async def card_expiry_alert() -> None:
    async with async_session_factory() as db:
        cartoes = await conversa_repo.get_cartoes_vencendo(db, settings.card_expiry_alert_months)
        if not cartoes:
            return
        for cartao in cartoes:
            phones = settings.whitelist_phones
            for phone in phones:
                msg = (
                    f"⚠️ Alerta: o cartão {cartao.banco_origem} ****{cartao.ultimos_4_digitos} "
                    f"vence em {cartao.vencimento}. Faltam menos de {settings.card_expiry_alert_months} meses."
                )
                await evolution_client.send_text(phone, msg)


def start_scheduler() -> None:
    scheduler.add_job(
        daily_pending_alert,
        CronTrigger(hour=settings.daily_alert_hour, minute=settings.daily_alert_minute),
        id="daily_pending_alert",
        replace_existing=True,
    )
    scheduler.add_job(
        card_expiry_alert,
        CronTrigger(hour=9, minute=0, day=1),
        id="card_expiry_alert",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler iniciado")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
