# -*- coding: utf-8 -*-
"""Bounded event audio capture (pre-trigger + post-trigger)."""
from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

try:  # production path
    import soundfile as sf
except ImportError:  # pragma: no cover - fallback for minimal environments
    sf = None

from app.dsp.event_detector import EventResult


@dataclass(slots=True)
class ActiveEvent:
    event_id: str
    start_utc: datetime
    event_end_utc: datetime
    pre: np.ndarray
    chunks: list[np.ndarray] = field(default_factory=list)
    post_left: int = 0
    severity: int = 0
    event_type: int = 0
    triggers: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class EventClip:
    event_id: str
    path: Path
    event_start_utc: datetime
    event_end_utc: datetime
    audio_start_utc: datetime
    audio_end_utc: datetime
    pre_s: float
    post_s: float
    severity: int
    event_type: int
    triggers: tuple[str, ...]
    sha256: str
    sample_rate: int
    audio_bytes: int
    calibrated: bool = False
    level_unit: str = "dBFS"

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "audio_path": str(self.path),
            "event_start_utc": self.event_start_utc.isoformat(),
            "event_end_utc": self.event_end_utc.isoformat(),
            "audio_start_utc": self.audio_start_utc.isoformat(),
            "audio_end_utc": self.audio_end_utc.isoformat(),
            "pre_s": round(self.pre_s, 3),
            "post_s": round(self.post_s, 3),
            "severity": self.severity,
            "event_type": self.event_type,
            "triggers": list(self.triggers),
            "sha256": self.sha256,
            "sample_rate": self.sample_rate,
            "audio_bytes": self.audio_bytes,
            "calibrated": self.calibrated,
            "level_unit": self.level_unit,
        }


def _write_wav(path: Path, data: np.ndarray, sample_rate: int,
               subtype: str = "FLOAT") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if sf is not None:
        sf.write(str(path), data, sample_rate, subtype=subtype)
        return
    # Minimal fallback for development machines without soundfile.
    from scipy.io import wavfile
    wavfile.write(str(path), sample_rate, np.asarray(data, dtype=np.float32))


class EventAudioCapture:
    """Per (session, channel) event audio buffer.

    Feed every analysis chunk.  The object keeps the last ``pre_s`` seconds and,
    while an event is active, appends chunks until ``post_s`` seconds after the
    last trigger.  Only the small clip is written to disk.
    """

    def __init__(self, fs: int, out_dir: str | Path,
                 pre_s: float = 5.0, post_s: float = 10.0,
                 max_s: float = 60.0, min_gap_s: float = 2.0,
                 subtype: str = "FLOAT", calibrated: bool = False,
                 level_unit: str = "dBFS"):
        if fs <= 0:
            raise ValueError("fs must be positive")
        self.fs = int(fs)
        self.out_dir = Path(out_dir)
        self.pre_n = max(1, int(self.fs * float(pre_s)))
        self.post_n = max(0, int(self.fs * float(post_s)))
        self.max_n = max(self.pre_n + self.post_n, int(self.fs * float(max_s)))
        self.min_gap = timedelta(seconds=float(min_gap_s))
        self.subtype = subtype
        self.calibrated = bool(calibrated)
        self.level_unit = level_unit
        self._ring = np.zeros(self.pre_n, dtype=np.float32)
        self._ring_len = 0
        self._active: Optional[ActiveEvent] = None
        self._last_end: Optional[datetime] = None

    def reset(self) -> None:
        self._ring.fill(0.0)
        self._ring_len = 0
        self._active = None
        self._last_end = None

    def _ring_push(self, chunk: np.ndarray) -> None:
        if chunk.size >= self.pre_n:
            self._ring[:] = chunk[-self.pre_n:]
            self._ring_len = self.pre_n
            return
        self._ring = np.roll(self._ring, -chunk.size)
        self._ring[-chunk.size:] = chunk
        self._ring_len = min(self.pre_n, self._ring_len + chunk.size)

    def _pre_snapshot(self) -> np.ndarray:
        if self._ring_len == 0:
            return np.empty(0, dtype=np.float32)
        return self._ring[-self._ring_len:].copy()

    @staticmethod
    def _triggers(result: EventResult) -> set[str]:
        triggers: set[str] = set()
        for name, flag in (
            ("laf", result.trigger_laf_threshold),
            ("impulse", result.trigger_impulse),
            ("onset", result.trigger_onset),
            ("background", result.trigger_background),
        ):
            if flag:
                triggers.add(name)
        if result.is_overload:
            triggers.add("overload")
        return triggers

    def push(self, chunk: np.ndarray, timestamp_utc: datetime,
             result: EventResult) -> Optional[EventClip]:
        samples = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return None

        if self._active is not None:
            event = self._active
            self._ring_push(samples)
            event.chunks.append(samples.copy())
            total = event.pre.size + sum(c.size for c in event.chunks)
            if result.event_type > 0 or result.is_overload:
                event.post_left = self.post_n
                event.event_end_utc = timestamp_utc + timedelta(
                    seconds=samples.size / self.fs)
                event.severity = max(event.severity, int(result.severity))
                event.event_type = max(event.event_type, int(result.event_type))
                event.triggers |= self._triggers(result)
            else:
                event.post_left -= samples.size
            if event.post_left <= 0 or total >= self.max_n:
                return self._finalize()
            return None

        if result.event_type > 0 or result.is_overload:
            if (self._last_end is not None
                    and timestamp_utc - self._last_end < self.min_gap):
                self._ring_push(samples)
                return None
            self._active = ActiveEvent(
                event_id=str(uuid.uuid4()),
                start_utc=timestamp_utc,
                event_end_utc=timestamp_utc + timedelta(
                    seconds=samples.size / self.fs),
                pre=self._pre_snapshot(),
                chunks=[samples.copy()],
                post_left=self.post_n,
                severity=int(result.severity),
                event_type=int(result.event_type),
                triggers=self._triggers(result),
            )
            self._ring_push(samples)
            return None

        self._ring_push(samples)
        return None

    def _finalize(self) -> EventClip:
        event = self._active
        self._active = None
        if event is None:
            raise RuntimeError("no active event")
        data = (np.concatenate([event.pre] + event.chunks)
                if event.chunks else event.pre)
        data = data[-self.max_n:].astype(np.float32, copy=False)
        pre_s = event.pre.size / self.fs
        audio_start = event.start_utc - timedelta(seconds=pre_s)
        audio_end = audio_start + timedelta(seconds=data.size / self.fs)
        event_samples = max(0, int(round(
            (event.event_end_utc - event.start_utc).total_seconds() * self.fs)))
        post_s = max(0.0, data.size / self.fs - pre_s - event_samples / self.fs)

        filename = (f"{event.start_utc:%Y%m%d_%H%M%S}_"
                    f"{event.event_id[:8]}.wav")
        path = self.out_dir / filename
        tmp = path.with_suffix(".tmp.wav")
        _write_wav(tmp, data, self.fs, subtype=self.subtype)
        os.replace(tmp, path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self._last_end = audio_end
        return EventClip(
            event_id=event.event_id,
            path=path,
            event_start_utc=event.start_utc,
            event_end_utc=event.event_end_utc,
            audio_start_utc=audio_start,
            audio_end_utc=audio_end,
            pre_s=pre_s,
            post_s=post_s,
            severity=event.severity,
            event_type=event.event_type,
            triggers=tuple(sorted(event.triggers)),
            sha256=digest,
            sample_rate=self.fs,
            audio_bytes=int(path.stat().st_size),
            calibrated=self.calibrated,
            level_unit=self.level_unit,
        )

    def flush(self) -> Optional[EventClip]:
        return self._finalize() if self._active is not None else None
