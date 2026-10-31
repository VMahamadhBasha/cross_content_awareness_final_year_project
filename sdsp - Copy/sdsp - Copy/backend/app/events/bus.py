"""Event bus abstraction with an in-process queue and a Redis Streams implementation."""
import asyncio
import queue
from typing import AsyncIterator

from app.config import get_settings
from app.schemas import BusEvent

STREAM, GROUP, CONSUMER = "sdsp:events", "processors", "worker-1"


class InMemoryBus:
    """Thread-safe in-process bus used for development and tests."""

    def __init__(self) -> None:
        self._q: queue.Queue[BusEvent] = queue.Queue()
        self._closed = False

    def publish(self, event: BusEvent) -> None:
        """Put an event on the queue."""
        self._q.put(event)

    async def consume(self) -> AsyncIterator[tuple[str, BusEvent]]:
        """Yield events as they arrive until the bus is closed."""
        while not self._closed:
            try:
                yield "", await asyncio.to_thread(self._q.get, True, 0.5)
            except queue.Empty:
                continue

    def ack(self, token: str) -> None:
        """No-op acknowledgement."""

    def close(self) -> None:
        """Stop consumers."""
        self._closed = True


class RedisBus:
    """Redis Streams bus with a consumer group for at-least-once delivery."""

    def __init__(self, url: str) -> None:
        import redis

        self.r = redis.Redis.from_url(url, decode_responses=True)
        self._closed = False
        try:
            self.r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def publish(self, event: BusEvent) -> None:
        """Append an event to the stream."""
        self.r.xadd(STREAM, {"data": event.model_dump_json()}, maxlen=10000, approximate=True)

    async def consume(self) -> AsyncIterator[tuple[str, BusEvent]]:
        """Yield events for this consumer group."""
        while not self._closed:
            res = await asyncio.to_thread(self.r.xreadgroup, GROUP, CONSUMER, {STREAM: ">"}, 10, 1000)
            for _, messages in res or []:
                for msg_id, fields in messages:
                    yield msg_id, BusEvent.model_validate_json(fields["data"])

    def ack(self, token: str) -> None:
        """Acknowledge a processed message."""
        self.r.xack(STREAM, GROUP, token)

    def close(self) -> None:
        """Stop consumers."""
        self._closed = True


def make_bus():
    """Create a Redis bus when REDIS_URL is reachable, otherwise an in-memory bus."""
    url = get_settings().redis_url
    if url:
        try:
            bus = RedisBus(url)
            bus.r.ping()
            return bus
        except Exception:
            pass
    return InMemoryBus()
