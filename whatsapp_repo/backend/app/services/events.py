import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from app.services.dashboard import dashboard_service
from app.database import async_session_factory

logger = logging.getLogger(__name__)


class EventBroadcaster:
    """Broadcast de eventos para dashboard (SSE/WebSocket)."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def publish(self, event: dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except Exception:
                logger.debug("Falha ao publicar evento")

    async def event_stream(self) -> AsyncGenerator[str, None]:
        queue = self.subscribe()
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                event = await queue.get()
                if event.get("type") == "refresh":
                    async with async_session_factory() as db:
                        data = await dashboard_service.get_dashboard_data(db)
                        event["dashboard"] = json.loads(data.model_dump_json())
                yield f"data: {json.dumps(event, default=str)}\n\n"
        finally:
            self.unsubscribe(queue)


event_broadcaster = EventBroadcaster()
