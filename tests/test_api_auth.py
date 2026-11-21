# -*- coding: utf-8 -*-
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.config import Settings


def test_api_key_protects_data_routes(tmp_path: Path) -> None:
    settings = Settings(
        watch_dir=tmp_path / "audio", db_path=tmp_path / "db" / "noise.db",
        log_dir=tmp_path / "log", event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp", trash_dir=tmp_path / "trash",
        api_key="secret",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/api/v1/channels").status_code == 401
        ok = client.get("/api/v1/channels", headers={"X-API-Key": "secret"})
        assert ok.status_code == 200

        created = client.post("/api/v1/calibrations", headers={"X-API-Key": "secret"},
                              json={"name": "cal1", "unit": "Pa",
                                    "pa_per_unit": 1.0, "calibrated": True})
        assert created.status_code == 200
        ready = client.get("/health/ready").json()
        assert ready["calibrated"] is True
