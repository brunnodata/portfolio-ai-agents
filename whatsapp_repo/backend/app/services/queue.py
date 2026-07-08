import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QueueItem:
    phone: str
    message_type: str
    payload: dict[str, Any]
    handler: Callable[..., Awaitable[None]]


class MessageQueue:
    """Fila assíncrona para processamento de áudio e imagem."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False

    async def enqueue(self, item: QueueItem) -> None:
        await self._queue.put(item)

    async def _worker(self, worker_id: int) -> None:
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                await item.handler(item.phone, item.message_type, item.payload)
            except Exception:
                logger.exception("Erro no worker %s", worker_id)
            finally:
                self._queue.task_done()

    def start(self, num_workers: int = 2) -> None:
        if self._running:
            return
        self._running = True
        for i in range(num_workers):
            self._workers.append(asyncio.create_task(self._worker(i)))

    async def stop(self) -> None:
        self._running = False
        for w in self._workers:
            w.cancel()
        self._workers.clear()


message_queue = MessageQueue()
