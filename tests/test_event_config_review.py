# -*- coding: utf-8 -*-
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.config import Settings
from app.domain.metrics import Metrics
from app.services.event_audio import EventClip
from app.storage import Database, Repository


def test_event_config_and_review(tmp_path: Path) -> None:
    settings = Settings(
        watch_dir=tmp_path / "audio", db_path=tmp_path / "db" / "noise.db",
        log_dir=tmp_path / "log", event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp", trash_dir=tmp_path / "trash",
    )
    with TestClient(create_app(settings)) as client:
        cfg = client.get("/api/v1/event-config").json()
        cfg.update({"laf_minor_db": 80, "pre_s": 3, "post_s": 6,
                    "max_s": 30, "min_gap_s": 1})
        assert client.put("/api/v1/event-config", json=cfg).status_code == 200
        assert client.get("/api/v1/event-config").json()["pre_s"] == 3

        repo = client.app.state.repo
        sid = repo.create_session("CH1")
        audio = tmp_path / "e.wav"
        audio.write_bytes(b"RIFF")
        clip = EventClip(
            event_id="evt-review", path=audio,
            event_start_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            event_end_utc=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
            audio_start_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            audio_end_utc=datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
            pre_s=0, post_s=1, severity=20, event_type=1,
            triggers=("laf",), sha256=hashlib.sha256(b"RIFF").hexdigest(),
            sample_rate=48000, audio_bytes=4, calibrated=False,
        )
        repo.insert_event(sid, "CH1", clip)
        response = client.post(
            "/api/v1/events/evt-review/review",
            json={"state": "false_positive", "note": "wind", "reviewer": "op"})
        assert response.status_code == 200
        assert response.json()["review_state"] == "false_positive"
        assert client.post("/api/v1/events/missing/review",
                           json={"state": "confirmed"}).status_code == 404
