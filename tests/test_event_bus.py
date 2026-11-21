# -*- coding: utf-8 -*-
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.config import Settings
from app.services.event_bus import EventBus


def test_event_bus_delivers_in_process() -> None:
    async def scenario():
        bus = EventBus()
        bus.attach_loop(asyncio.get_running_loop())
        stream = bus.subscribe()
        async def first():
            return await stream.__anext__()
        task = asyncio.create_task(first())
        await asyncio.sleep(0)
        bus.publish({"type": "metric", "item": {"laeq": 94.0}})
        event = await asyncio.wait_for(task, timeout=2)
        await stream.aclose()
        return event

    event = asyncio.run(scenario())
    assert event["type"] == "metric"


def test_websocket_receives_published_event(tmp_path) -> None:
    settings = Settings(
        watch_dir=tmp_path / "audio", db_path=tmp_path / "db" / "noise.db",
        log_dir=tmp_path / "log", event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp", trash_dir=tmp_path / "trash",
    )
    with TestClient(create_app(settings)) as client:
        with client.websocket_connect("/api/v1/ws") as websocket:
            client.app.state.bus.publish(
                {"type": "metric", "item": {"laeq": 94.0}})
            event = websocket.receive_json()
        assert event["type"] == "metric"
