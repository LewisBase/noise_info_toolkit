# -*- coding: utf-8 -*-
"""Lazy TDMS channel reader used by the streaming pipeline."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

import numpy as np

from app.domain.calibration import Calibration


def _first(props: dict, *names: str, default=None):
    lower = {str(k).lower(): v for k, v in props.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return default


def _to_utc(value: Any, fallback: Path) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(
            tzinfo=timezone.utc)
    if isinstance(value, np.datetime64):
        return value.astype("datetime64[us]").astype(datetime).replace(
            tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(
                tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback.stat().st_mtime, tz=timezone.utc)


class TdmsChannelSource:
    """Read one TDMS group/channel in 10 s windows without whole-file loading."""

    def __init__(self, path: str | Path, group: Optional[str] = None,
                 channel: Optional[str] = None, tdms_file: Any = None):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        if tdms_file is None:
            from nptdms import TdmsFile
            tdms_file = TdmsFile.open(str(self.path))
        self._tdms = tdms_file
        groups = list(self._tdms.groups())
        if not groups:
            raise ValueError(f"no groups in TDMS file: {self.path}")
        self.group = next((g for g in groups if g.name == group), groups[0])
        channels = list(self.group.channels())
        if not channels:
            raise ValueError(f"no channels in group {self.group.name}")
        self.channel = next((c for c in channels if c.name == channel), channels[0])
        self.properties = dict(getattr(self.channel, "properties", {}) or {})
        self.channel_name = str(getattr(self.channel, "name", channel or "CH1"))
        self.fs = self._read_sample_rate(self.properties)
        self.start_utc = _to_utc(
            _first(self.properties, "wf_start_time", "WF_Start_Time"),
            self.path)
        self.unit = str(_first(
            self.properties, "unit_string", "NI_UnitDescription", "Units",
            default="Pa"))
        self.total = int(len(self.channel))

    @staticmethod
    def _read_sample_rate(props: dict) -> int:
        increment = _first(props, "wf_increment", "WF_Increment")
        if increment is not None:
            try:
                value = 1.0 / float(increment)
                if np.isfinite(value) and value > 0:
                    return int(round(value))
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        for name in ("SampleRate", "sample_rate", "NI_Sample_Rate"):
            value = _first(props, name)
            if value is not None:
                try:
                    value = float(value)
                    if np.isfinite(value) and value > 0:
                        return int(round(value))
                except (TypeError, ValueError):
                    pass
        raise ValueError(
            f"cannot determine sample rate for {Path(props.get('file', 'TDMS'))}; "
            "refusing to guess 44100")

    def calibration(self) -> Calibration:
        return Calibration.from_tdms_properties(self.properties)

    def iter_windows(self, window_s: float = 10.0
                     ) -> Iterator[tuple[np.ndarray, datetime, float]]:
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        step = max(1, int(round(self.fs * window_s)))
        for offset in range(0, self.total, step):
            length = min(step, self.total - offset)
            raw = self.channel.read_data(offset, length, scaled=True)
            timestamp = self.start_utc + timedelta(seconds=offset / self.fs)
            yield np.asarray(raw, dtype=np.float64), timestamp, length / self.fs

    def close(self) -> None:
        close = getattr(self._tdms, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "TdmsChannelSource":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
