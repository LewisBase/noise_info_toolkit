# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from app.dsp.event_detector import EventResult
from app.services.event_audio import EventClip
from app.storage import Database, Repository


def test_event_roundtrip(tmp_path: Path) -> None:
    db = Database(tmp_path / "noise.db")
    repo = Repository(db)
    sid = repo.create_session("CH1")
    audio = tmp_path / "event.wav"
    audio.write_bytes(b"RIFF-fake-wav")
    sha = hashlib.sha256(audio.read_bytes()).hexdigest()
    clip = EventClip(
        event_id="evt-1", path=audio,
        event_start_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        event_end_utc=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        audio_start_utc=datetime(2025, 12, 31, 23, 59, 55, tzinfo=timezone.utc),
        audio_end_utc=datetime(2026, 1, 1, 0, 0, 11, tzinfo=timezone.utc),
        pre_s=5.0, post_s=10.0, severity=50, event_type=2,
        triggers=("laf",), sha256=sha, sample_rate=48000,
        audio_bytes=audio.stat().st_size, calibrated=True, level_unit="dB SPL",
    )
    repo.insert_event(sid, "CH1", clip, EventResult(event_type=2, severity=50))
    assert repo.event_count(sid, "CH1") == 1
    assert repo.has_verified_event_audio(sid, "CH1") is True
    events = repo.list_events(session_id=sid, channel="CH1")
    assert events[0]["event_id"] == "evt-1"
    assert events[0]["audio_sha256"] == sha
    db.close()
