# -*- coding: utf-8 -*-
"""TDMS source tests with an injected fake channel (no nptdms needed)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from app.io.tdms_source import TdmsChannelSource


class FakeChannel:
    def __init__(self, data: np.ndarray, props: dict):
        self._data = data
        self.properties = props
        self.name = "CH1"

    def __len__(self) -> int:
        return int(self._data.size)

    def read_data(self, offset=0, length=None, scaled=True):
        end = None if length is None else offset + length
        return self._data[offset:end]


class FakeGroup:
    def __init__(self, channel):
        self.name = "NoiseData"
        self._channel = channel

    def channels(self):
        return [self._channel]


class FakeTdms:
    def __init__(self, channel):
        self._group = FakeGroup(channel)

    def groups(self):
        return [self._group]

    def close(self):
        pass


def _source(tmp_path: Path, props: dict, fs: int = 8000,
            fallback_fs: int | None = None) -> TdmsChannelSource:
    path = tmp_path / "x.tdms"
    path.write_bytes(b"tdms")
    channel = FakeChannel(np.arange(fs * 3, dtype=np.float64), props)
    return TdmsChannelSource(path, tdms_file=FakeTdms(channel),
                             fallback_fs=fallback_fs)


def test_reads_wf_increment_and_start(tmp_path: Path) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    source = _source(tmp_path, {
        "wf_increment": 1 / 8000,
        "wf_start_time": start,
        "unit_string": "Pa",
    })
    assert source.fs == 8000
    assert source.start_utc == start
    assert source.calibration().calibrated is True
    windows = list(source.iter_windows(1.0))
    assert len(windows) == 3
    assert windows[0][0].size == 8000
    assert windows[2][1] == start.replace(second=2)


def test_refuses_unknown_sample_rate(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sample rate"):
        _source(tmp_path, {"unit_string": "Pa"})


def test_uses_configured_fallback_sample_rate(tmp_path: Path) -> None:
    source = _source(tmp_path, {"unit_string": "Pa"}, fs=48000,
                    fallback_fs=48000)
    assert source.fs == 48000
    assert source.sample_rate_estimated is True
