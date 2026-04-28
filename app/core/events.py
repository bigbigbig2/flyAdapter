from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import AsyncIterator
from typing import Any


class EventHub:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: set[queue.Queue[str]] = set()

    def publish(self, event: dict[str, Any]) -> None:
        payload = "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(payload)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.put_nowait(payload)
                except queue.Full:
                    pass

    def subscribe(self) -> queue.Queue[str]:
        subscriber: queue.Queue[str] = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[str]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    async def stream(self) -> AsyncIterator[str]:
        subscriber = self.subscribe()
        try:
            while True:
                yield await asyncio.to_thread(subscriber.get)
        finally:
            self.unsubscribe(subscriber)
