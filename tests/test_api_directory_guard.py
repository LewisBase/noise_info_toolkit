# -*- coding: utf-8 -*-
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.config import Settings


def test_directory_guard_rejects_outside_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    settings = Settings(
        watch_dir=allowed, db_path=tmp_path / "db" / "noise.db",
        log_dir=tmp_path / "log", event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp", trash_dir=tmp_path / "trash",
        allowed_watch_roots=[allowed],
    )
    with TestClient(create_app(settings)) as client:
        ok = client.get("/api/v1/fs/dirs", params={"path": str(allowed)})
        assert ok.status_code == 200
        denied = client.get("/api/v1/fs/dirs", params={"path": str(outside)})
        assert denied.status_code == 403
        started = client.post("/api/v1/monitor/start",
                              json={"watch_directory": str(outside)})
        assert started.status_code == 403
        ready = client.get("/health/ready").json()
        assert ready["directory_guard"] == "restricted"
