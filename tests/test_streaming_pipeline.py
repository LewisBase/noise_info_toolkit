# -*- coding: utf-8 -*-
"""Pipeline vertical slice: fake TDMS -> SciPy DSP -> 1 s rows."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from app.io.tdms_source import TdmsChannelSource
from app.services.streaming_pipeline import PipelineConfig, process_tdms_file


class FakeChannel:
    def __init__(self, data: np.ndarray, props: dict):
        self._data = data
        self.properties = props
        self.name = "CH1"

    def __len__(self):
        return int(self._data.size)

    def read_data(self, offset=0, length=None, scaled=True):
        end = None if length is None else offset + length
        return self._data[offset:end]


class FakeGroup:
    name = "NoiseData"

    def __init__(self, channel):
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


def test_pipeline_3s_tone(tmp_path: Path) -> None:
    fs, seconds = 8000, 3
    t = np.arange(fs * seconds) / fs
    rms = 20e-6 * 10 ** (94 / 20)
    data = rms * np.sqrt(2) * np.sin(2 * np.pi * 1000 * t)
    channel = FakeChannel(data, {
        "wf_increment": 1 / fs,
        "wf_start_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "unit_string": "Pa",
    })
    path = tmp_path / "tone.tdms"
    path.write_bytes(b"tdms")
    source = TdmsChannelSource(path, tdms_file=FakeTdms(channel))
    rows = []
    result = process_tdms_file(
        path,
        PipelineConfig(read_window_s=1.0, analysis_step_s=1.0,
                       persist_window_s=1.0, event_dir=tmp_path / "events"),
        source=source,
        on_window=rows.append,
    )
    assert len(result.metrics) == 3
    assert len(rows) == 3
    assert result.summary is not None
    assert result.summary.duration_s == pytest.approx(3.0)
    assert result.summary.laeq == pytest.approx(94.0, abs=0.6)
    # A steady 94 dB tone is above the default LAF minor threshold (85 dB),
    # so it is intentionally captured as an acoustic event.
    assert len(result.events) == 1
    assert result.events[0].path.is_file()
