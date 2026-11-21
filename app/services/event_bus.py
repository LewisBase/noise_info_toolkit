# -*- coding: utf-8 -*-
"""In-process pub/sub used by SSE and WebSocket live streams.

The DSP worker runs in a plain thread, so ``publish`` hands events to the
asyncio loop with ``call_soon_threadsafe``.  Subscribers are bounded queues to
protect the API if a browser stops reading.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator


class EventBus:
    def __init__(self, max_queue: int = 200) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._max_queue = max_queue

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._broadcast, event)
        except RuntimeError:
            pass

    def _broadcast(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)
