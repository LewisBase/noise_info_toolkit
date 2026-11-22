# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.domain.calibration import Calibration
from app.dsp.filters import design_bands, design_weighting
from app.dsp.processor import QCThresholds, StreamingNoiseProcessor
from app.storage import Database, Repository


def _metrics():
    fs = 8000
    t = np.arange(fs) / fs
    x = 20e-6 * np.sqrt(2) * 10 ** (94 / 20) * np.sin(2 * np.pi * 1000 * t)
    p = StreamingNoiseProcessor(
        fs, design_weighting(fs), design_bands(fs), Calibration.pa(),
        QCThresholds())
    return p.process_block(x, datetime(2026, 1, 1, tzinfo=timezone.utc), 1.0, "CH1")


def test_time_history_roundtrip(tmp_path: Path) -> None:
    db = Database(tmp_path / "noise.db")
    repo = Repository(db)
    sid = repo.create_session("CH1")
    metrics = _metrics()
    repo.insert_time_history(sid, metrics)
    latest = repo.latest_time_history("CH1")
    assert latest is not None
    assert latest["laeq"] == metrics.laeq
    assert latest["freq_spl"]["1kHz"] == metrics.freq_spl[4]
    history = repo.list_time_history("CH1")
    assert len(history) == 1
    db.close()


def test_session_lifecycle(tmp_path: Path) -> None:
    db = Database(tmp_path / "noise.db")
    repo = Repository(db)
    sid = repo.create_session("CH1", operator="tester")
    assert repo.current_session("CH1")["id"] == sid
    repo.close_session(sid, 3.0)
    assert repo.current_session("CH1") is None
    assert repo.list_sessions()[0]["state"] == "stopped"
    db.close()


def test_one_running_session_per_channel(tmp_path: Path) -> None:
    from app.storage import Database, Repository
    db = Database(tmp_path / "sessions.db")
    repo = Repository(db)
    first = repo.create_session("CH1")
    second = repo.create_session("CH1")
    current = repo.current_session("CH1")
    assert current["id"] == second
    sessions = {item["id"]: item for item in repo.list_sessions()}
    assert sessions[first]["state"] == "stopped"
    assert sessions[second]["state"] == "running"
    db.close()
