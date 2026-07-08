import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from sqlalchemy import text

from app.api.routes import router
from app.config import get_settings
from app.database import Base, engine
from app.services.queue import message_queue
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE lancamentos ADD COLUMN IF NOT EXISTS item VARCHAR(200)"))
    message_queue.start(num_workers=2)
    start_scheduler()
    logger.info("%s iniciado", settings.app_name)
    yield
    stop_scheduler()
    await message_queue.stop()
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:
    logger.info("%s %s", request.method, request.url.path)
    response = await call_next(request)
    if response.status_code >= 400:
        logger.warning("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


app.include_router(router)
