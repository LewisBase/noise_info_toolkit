# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.config import Settings
from app.domain.calibration import Calibration
from app.dsp.filters import design_bands, design_weighting
from app.dsp.processor import QCThresholds, StreamingNoiseProcessor


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        watch_dir=tmp_path / "audio", db_path=tmp_path / "db" / "noise.db",
        log_dir=tmp_path / "log", event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp", trash_dir=tmp_path / "trash",
        retention_mode="debug",
    )


def _metrics():
    fs = 8000
    t = np.arange(fs) / fs
    x = 20e-6 * np.sqrt(2) * 10 ** (94 / 20) * np.sin(2 * np.pi * 1000 * t)
    p = StreamingNoiseProcessor(
        fs, design_weighting(fs), design_bands(fs), Calibration.pa(),
        QCThresholds())
    return p.process_block(x, datetime(2026, 1, 1, tzinfo=timezone.utc), 1.0, "CH1")


def test_api_latest_history_and_health(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["retention_mode"] == "debug"

        created = client.post("/api/v1/sessions", json={"channel": "CH1"})
        assert created.status_code == 200
        sid = created.json()["session_id"]
        app.state.repo.insert_time_history(sid, _metrics())

        latest = client.get("/api/v1/metrics/latest", params={"channel": "CH1"})
        assert latest.status_code == 200
        assert latest.json()["laeq"] == _metrics().laeq

        hist = client.get("/api/v1/metrics/history", params={
            "channel": "CH1",
            "start": "2025-12-31T00:00:00+00:00",
            "end": "2026-01-02T00:00:00+00:00",
        })
        assert hist.status_code == 200
        assert hist.json()["count"] == 1
        assert hist.json()["total"] == 1
        minute = client.get("/api/v1/metrics/history", params={
            "channel": "CH1", "aggregate": "minute",
            "start": "2025-12-31T00:00:00+00:00",
            "end": "2026-01-02T00:00:00+00:00",
        })
        assert minute.status_code == 200
        assert minute.json()["aggregate"] == "minute"
        assert minute.json()["count"] == 1

        # A naive datetime must be rejected, not silently compared as text.
        bad = client.get("/api/v1/metrics/history", params={
            "channel": "CH1", "start": "2026-01-01T00:00:00"})
        assert bad.status_code == 422

        assert client.get("/api/v1/retention/status").json()["mode"] == "debug"
        assert client.post("/api/v1/retention/preview").json()["deleted"] == 0
