# -*- coding: utf-8 -*-
"""ProcessingService -> SQLite end-to-end test (real TDMS)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

nptdms = pytest.importorskip("nptdms")
from nptdms import ChannelObject, TdmsWriter

from app.config import Settings
from app.services.processing_service import ProcessingService
from app.storage import Database


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        watch_dir=tmp_path / "audio", db_path=tmp_path / "db" / "noise.db",
        log_dir=tmp_path / "log", event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp", trash_dir=tmp_path / "trash",
        retention_mode="debug",
    )


def test_process_path_writes_rows_and_events(tmp_path: Path) -> None:
    fs, seconds = 8000, 3
    t = np.arange(fs * seconds) / fs
    rms = 20e-6 * 10 ** (94 / 20)
    signal = rms * np.sqrt(2) * np.sin(2 * np.pi * 1000 * t)
    path = tmp_path / "CH1.tdms"
    with TdmsWriter(str(path)) as writer:
        writer.write_segment([ChannelObject(
            "NoiseData", "CH1", signal,
            properties={
                "wf_increment": 1 / fs,
                "wf_start_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "unit_string": "Pa",
            })])

    settings = _settings(tmp_path)
    db = Database(settings.db_path)
    service = ProcessingService(settings, db)
    service.process_path(path)
    latest = service.repo.latest_time_history("CH1")
    assert latest is not None
    assert latest["laeq"] == pytest.approx(94.0, abs=0.7)
    events = service.repo.list_events(channel="CH1")
    assert len(events) == 1
    assert Path(events[0]["audio_path"]).is_file()
    # Debug retention must never delete source audio.
    assert path.is_file()
    db.close()
