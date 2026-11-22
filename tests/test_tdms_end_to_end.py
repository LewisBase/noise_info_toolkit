# -*- coding: utf-8 -*-
"""Real nptdms end-to-end vertical slice (skipped if nptdms is absent)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

nptdms = pytest.importorskip("nptdms")
from nptdms import ChannelObject, TdmsWriter

from app.services.streaming_pipeline import PipelineConfig, process_tdms_file


def test_real_tdms_file(tmp_path: Path) -> None:
    fs, seconds = 8000, 3
    t = np.arange(fs * seconds) / fs
    rms = 20e-6 * 10 ** (94 / 20)
    signal = (rms * np.sqrt(2) * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)
    path = tmp_path / "CH1_real.tdms"
    channel = ChannelObject(
        "NoiseData", "CH1", signal,
        properties={
            "wf_increment": 1.0 / fs,
            "wf_start_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "unit_string": "Pa",
        })
    with TdmsWriter(str(path)) as writer:
        writer.write_segment([channel])

    result = process_tdms_file(
        path,
        PipelineConfig(read_window_s=1.0, analysis_step_s=1.0,
                       persist_window_s=1.0, event_dir=tmp_path / "events"),
    )
    assert result.channel == "CH1"
    assert result.summary is not None
    assert result.summary.duration_s == pytest.approx(3.0)
    assert result.summary.laeq == pytest.approx(94.0, abs=0.7)
    assert len(result.metrics) == 3
    # 94 dB steady tone intentionally exceeds the 85 dB LAF minor threshold.
    assert len(result.events) == 1
    assert result.events[0].path.is_file()
