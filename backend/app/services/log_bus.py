from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import AsyncIterator
from uuid import uuid4

from app.models import AgentLogEvent


class AgentLogBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[AgentLogEvent]] = set()
        self._recent: deque[AgentLogEvent] = deque(maxlen=100)

    async def publish(
        self,
        stage: str,
        message: str,
        *,
        customer_id: str | None = None,
        order_id: str | None = None,
        metadata: dict | None = None,
    ) -> AgentLogEvent:
        event = AgentLogEvent(
            id=str(uuid4()),
            customer_id=customer_id,
            order_id=order_id,
            stage=stage,
            message=message,
            metadata=metadata or {},
        )
        self._recent.append(event)
        for queue in list(self._subscribers):
            queue.put_nowait(event)
        return event

    async def stream(self, customer_id: str | None = None) -> AsyncIterator[str]:
        queue: asyncio.Queue[AgentLogEvent] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            for event in list(self._recent):
                if customer_id is None or event.customer_id == customer_id:
                    yield self._format_sse(event)
            while True:
                event = await queue.get()
                if customer_id is None or event.customer_id == customer_id:
                    yield self._format_sse(event)
        finally:
            self._subscribers.discard(queue)

    @staticmethod
    def _format_sse(event: AgentLogEvent) -> str:
        return f"data: {json.dumps(event.model_dump(mode='json'))}\n\n"


log_bus = AgentLogBus()
