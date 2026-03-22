from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import WebSocket


class LiveFeedBroker:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._dispatch_task: asyncio.Task[None] | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._dispatch_task is not None and not self._dispatch_task.done():
            return
        self._loop = loop
        self._queue = asyncio.Queue()
        self._dispatch_task = loop.create_task(self._dispatch_loop())

    async def stop(self) -> None:
        if self._dispatch_task is not None:
            self._dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dispatch_task
        self._dispatch_task = None
        self._queue = None
        for websocket in list(self._connections):
            with contextlib.suppress(Exception):
                await websocket.close()
        self._connections.clear()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    def publish(self, payload: dict[str, Any]) -> None:
        if self._loop is None or self._queue is None:
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, payload)

    async def _dispatch_loop(self) -> None:
        assert self._queue is not None
        while True:
            payload = await self._queue.get()
            dead_connections: list[WebSocket] = []
            for websocket in list(self._connections):
                try:
                    await websocket.send_json(payload)
                except Exception:
                    dead_connections.append(websocket)
            for websocket in dead_connections:
                self._connections.discard(websocket)


live_feed_broker = LiveFeedBroker()
