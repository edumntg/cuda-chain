"""In-process publish/subscribe for Server-Sent Events.

One coordinator process serves all SSE clients in v0.1. A multi-replica deployment
needs a shared bus (Redis) behind the same two functions.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    topic: str
    data: dict[str, Any]
    at: float = field(default_factory=time.time)

    def sse(self) -> str:
        return f"event: {self.topic}\ndata: {json.dumps(self.data, default=str)}\n\n"


class Bus:
    def __init__(self, history: int = 200):
        self._lock = threading.Lock()
        self._subs: list[tuple[set[str], asyncio.Queue[Event], asyncio.AbstractEventLoop]] = []
        self.recent: deque[Event] = deque(maxlen=history)

    def publish(self, topic: str, data: dict[str, Any]) -> None:
        ev = Event(topic, data)
        with self._lock:
            self.recent.append(ev)
            subs = list(self._subs)
        for topics, queue, loop in subs:
            if topics and topic not in topics and topic.split(":")[0] not in topics:
                continue
            loop.call_soon_threadsafe(queue.put_nowait, ev)

    def subscribe(self, topics: set[str]) -> Subscription:
        return Subscription(self, topics)


class Subscription:
    def __init__(self, bus: Bus, topics: set[str]):
        self.bus = bus
        self.topics = topics
        self.queue: asyncio.Queue[Event] = asyncio.Queue()
        self.loop = asyncio.get_event_loop()
        with bus._lock:
            bus._subs.append((topics, self.queue, self.loop))

    async def get(self, timeout: float) -> Event | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            return None

    def close(self) -> None:
        with self.bus._lock:
            self.bus._subs = [s for s in self.bus._subs if s[1] is not self.queue]
