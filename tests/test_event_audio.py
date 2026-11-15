# -*- coding: utf-8 -*-
"""Event audio capture and retention policy tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from app.domain.metrics import EVENT_MINOR
from app.dsp.event_detector import EventResult
from app.services.anomalies import AnomalyService
from app.services.event_audio import EventAudioCapture
from app.services.retention import (
    RetentionPolicy,
    RetentionService,
    SourceJob,
    can_delete_source,
)


def _event() -> EventResult:
    return EventResult(
        event_type=EVENT_MINOR,
        severity=20,
        laf_db=90.0,
        las_db=80.0,
        trigger_laf_threshold=True,
    )


def test_event_audio_keeps_pre_and_post(tmp_path: Path) -> None:
    fs = 1000
    capture = EventAudioCapture(
        fs=fs, out_dir=tmp_path, pre_s=1.0, post_s=2.0,
        max_s=10.0, min_gap_s=0.0)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clip = None
    for i in range(6):
        ts = t0 + timedelta(seconds=i)
        result = _event() if i == 3 else EventResult()
        clip = capture.push(np.ones(fs, dtype=np.float32), ts, result)
    assert clip is not None
    assert clip.path.is_file()
    assert clip.pre_s == pytest.approx(1.0)
    assert clip.post_s == pytest.approx(2.0, abs=1e-6)
    assert clip.audio_start_utc == t0 + timedelta(seconds=2)
    assert clip.audio_end_utc == t0 + timedelta(seconds=6)
    sr, data = wavfile.read(clip.path)
    assert sr == fs
    assert data.size == 4 * fs
    assert clip.sha256
    assert capture.flush() is None


def test_event_audio_flush_at_boundary(tmp_path: Path) -> None:
    capture = EventAudioCapture(fs=1000, out_dir=tmp_path,
                                pre_s=1.0, post_s=2.0)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    capture.push(np.ones(1000, dtype=np.float32), t0, _event())
    clip = capture.flush()
    assert clip is not None
    assert clip.path.is_file()
    assert clip.post_s == pytest.approx(0.0, abs=1e-6)


def _job(tmp_path: Path, *, active: bool = False,
         verified: bool = True) -> SourceJob:
    path = tmp_path / "CH1_test.tdms"
    path.write_bytes(b"0" * 1024)
    stat = path.stat()
    return SourceJob(
        id="job-1",
        file_path=path,
        file_size=stat.st_size,
        file_mtime_ns=stat.st_mtime_ns,
        finished_at=datetime.now(timezone.utc) - timedelta(days=10),
        status="done",
        has_events=True,
        event_audio_verified=verified,
        active_event=active,
    )


def test_debug_mode_never_deletes(tmp_path: Path) -> None:
    job = _job(tmp_path)
    policy = RetentionPolicy(mode="debug", dry_run=False)
    report = RetentionService(policy).run([job])
    assert report.mode == "debug"
    assert report.deleted == 0
    assert report.candidates == 1
    assert job.file_path.exists()


def test_production_dry_run_does_not_move(tmp_path: Path) -> None:
    job = _job(tmp_path)
    policy = RetentionPolicy(mode="production", dry_run=True,
                             trash_dir=tmp_path / "trash")
    report = RetentionService(policy).run([job])
    assert report.dry_run is True
    assert report.deleted == 0
    assert job.file_path.exists()


def test_production_moves_eligible_source(tmp_path: Path) -> None:
    job = _job(tmp_path)
    policy = RetentionPolicy(mode="production", dry_run=False,
                             trash_dir=tmp_path / "trash")
    report = RetentionService(policy).run([job])
    assert report.deleted == 1
    assert not job.file_path.exists()
    moved = list((tmp_path / "trash").rglob("CH1_test.tdms"))
    assert len(moved) == 1


@pytest.mark.parametrize("active,verified,reason", [
    (True, True, "active_event"),
    (False, False, "event_audio_missing_or_bad_sha"),
])
def test_production_skips_guarded_jobs(tmp_path: Path, active: bool,
                                       verified: bool, reason: str) -> None:
    job = _job(tmp_path, active=active, verified=verified)
    policy = RetentionPolicy(mode="production", dry_run=False)
    ok, why = can_delete_source(job, datetime.now(timezone.utc), policy)
    assert not ok
    assert why == reason
    assert job.file_path.exists()


def test_anomaly_deduplicates() -> None:
    service = AnomalyService(dedupe_s=300)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert service.record("db_write_error", 3, "boom", now=now) is not None
    assert service.record("db_write_error", 3, "boom", now=now) is None
    assert len(service.events) == 1
