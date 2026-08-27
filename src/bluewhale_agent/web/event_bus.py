"""In-process fan-out for newly persisted trajectory events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from bluewhale_agent.trajectory.store import StoredEvent


class EventBus:
    """Publish each stored event to every currently connected subscriber."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[StoredEvent]] = set()

    def publish(self, event: StoredEvent) -> None:
        for queue in tuple(self._subscribers):
            queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[StoredEvent]]:
        queue: asyncio.Queue[StoredEvent] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)
