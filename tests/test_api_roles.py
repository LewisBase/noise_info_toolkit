# -*- coding: utf-8 -*-
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.config import Settings

OP = {"X-API-Key": "op"}
CAL = {"X-API-Key": "cal"}
ADM = {"X-API-Key": "adm"}


def test_role_matrix(tmp_path: Path) -> None:
    watch = tmp_path / "watch"
    watch.mkdir()
    settings = Settings(
        watch_dir=tmp_path / "audio", db_path=tmp_path / "db" / "noise.db",
        log_dir=tmp_path / "log", event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp", trash_dir=tmp_path / "trash",
        operator_api_key="op", calibrator_api_key="cal", admin_api_key="adm",
        allowed_watch_roots=[tmp_path],
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/channels").status_code == 401
        assert client.get("/api/v1/channels", headers=OP).status_code == 200
        assert client.get("/api/v1/fs/dirs", headers=OP).status_code == 200
        assert client.get("/api/v1/fs/dirs", headers=ADM).status_code == 200

        assert client.post("/api/v1/calibrations", headers=OP,
                           json={"name": "c", "unit": "Pa"}).status_code == 403
        assert client.post("/api/v1/calibrations", headers=CAL,
                           json={"name": "cal1", "unit": "Pa"}).status_code == 200

        assert client.post("/api/v1/retention/preview",
                           headers=OP).status_code == 403
        assert client.post("/api/v1/retention/preview",
                           headers=ADM).status_code == 200

        assert client.get("/api/v1/whoami", headers=CAL).json()["role"] == "calibrator"
        assert client.get("/api/v1/stream?api_key=bad").status_code == 401
