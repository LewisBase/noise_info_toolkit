# -*- coding: utf-8 -*-
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.config import Settings


def test_monitor_start_stop_and_directory_listing(tmp_path: Path) -> None:
    watch = tmp_path / "watch"
    (watch / "child").mkdir(parents=True)
    settings = Settings(
        watch_dir=tmp_path / "audio", db_path=tmp_path / "db" / "noise.db",
        log_dir=tmp_path / "log", event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp", trash_dir=tmp_path / "trash",
    )
    with TestClient(create_app(settings)) as client:
        listing = client.get("/api/v1/fs/dirs", params={"path": str(watch)})
        assert listing.status_code == 200
        assert any(item["name"] == "child" for item in listing.json()["dirs"])

        started = client.post("/api/v1/monitor/start",
                              json={"watch_directory": str(watch)})
        assert started.status_code == 200
        assert started.json()["status"] == "started"
        config = client.get("/api/v1/monitor/config").json()
        assert config["watch_directory"] == str(watch.resolve())

        missing = client.post(
            "/api/v1/monitor/start",
            json={"watch_directory": str(tmp_path / "missing")})
        assert missing.status_code == 400

        stopped = client.post("/api/v1/monitor/stop")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"
