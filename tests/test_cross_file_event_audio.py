# -*- coding: utf-8 -*-
"""Event audio must survive a chunk boundary inside one session/channel."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

nptdms = pytest.importorskip("nptdms")
from nptdms import ChannelObject, TdmsWriter

from app.config import Settings
from app.services.processing_service import ProcessingService
from app.storage import Database


def _write(path: Path, start: datetime, fs: int = 8000,
           seconds: int = 2) -> None:
    t = np.arange(fs * seconds) / fs
    rms = 20e-6 * 10 ** (94 / 20)
    signal = rms * np.sqrt(2) * np.sin(2 * np.pi * 1000 * t)
    with TdmsWriter(str(path)) as writer:
        writer.write_segment([ChannelObject(
            "NoiseData", "CH1", signal,
            properties={"wf_increment": 1 / fs, "wf_start_time": start,
                        "unit_string": "Pa"})])


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        watch_dir=tmp_path / "audio", db_path=tmp_path / "db" / "noise.db",
        log_dir=tmp_path / "log", event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp", trash_dir=tmp_path / "trash",
        retention_mode="debug",
    )


def test_event_audio_spans_two_tdms_files(tmp_path: Path) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = tmp_path / "CH1_a.tdms"
    second = tmp_path / "CH1_b.tdms"
    _write(first, start)
    _write(second, start + timedelta(seconds=2))

    settings = _settings(tmp_path)
    db = Database(settings.db_path)
    service = ProcessingService(settings, db)
    service.process_path(first)
    service.process_path(second)
    service.stop()   # flushes the session-level capture

    events = service.repo.list_events(channel="CH1")
    assert len(events) == 1
    path = Path(events[0]["audio_path"])
    assert path.is_file()
    # 2 s from the first file + 2 s from the second, no post-trigger yet.
    assert path.stat().st_size > 4 * 8000  # float WAV header + samples
    db.close()
