"""
In-process async publish/subscribe registry.

docs/ARCHITECTURE.md §4 (revised in docs/PRODUCT_EXPERIENCE.md §8.1): the
prototype backend is one FastAPI process, so every producer and consumer of
an event lives in the same process - a network-hop broker (Redis Streams,
Kafka) would add a container, a connection pool, and a live-demo failure
mode for zero benefit at this scale. The interface below
(`publish(topic, payload)` / `subscribe(topic, handler)`) is deliberately
broker-agnostic so swapping in Redis Streams or Kafka once a second backend
process genuinely exists is a one-file change, not a redesign.
"""
import asyncio
from collections import defaultdict
from typing import Awaitable, Callable, DefaultDict, List

from app.core.logging_config import get_logger

logger = get_logger(__name__)

Handler = Callable[[dict], Awaitable[None]]


class EventDispatcher:
    def __init__(self) -> None:
        self._subscribers: DefaultDict[str, List[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        if handler in self._subscribers.get(topic, []):
            self._subscribers[topic].remove(handler)

    async def publish(self, topic: str, payload: dict) -> None:
        handlers = list(self._subscribers.get(topic, []))
        logger.info(
            "event.published",
            extra={"extra_fields": {"topic": topic, "subscriber_count": len(handlers)}},
        )
        if not handlers:
            return
        results = await asyncio.gather(
            *(handler(payload) for handler in handlers), return_exceptions=True
        )
        for result in results:
            if isinstance(result, Exception):
                logger.error(
                    "event.handler_failed",
                    extra={"extra_fields": {"topic": topic, "error": str(result)}},
                )


# Process-wide singleton - every module imports this same instance.
dispatcher = EventDispatcher()
