# -*- coding: utf-8 -*-
"""Core SciPy DSP regression tests (vertical slice)."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from app.domain.calibration import Calibration
from app.dsp.aggregation import aggregate_segments
from app.dsp.event_detector import EventConfig, EventDetector
from app.dsp.filters import design_bands, design_weighting
from app.dsp.processor import QCThresholds, StreamingNoiseProcessor


FS = 48000
REF = 20e-6


def tone(freq: float, spl: float, duration: float,
         fs: int = FS, phase: float = 0.0) -> np.ndarray:
    n = int(round(fs * duration))
    t = np.arange(n) / fs
    rms = REF * (10.0 ** (spl / 20.0))
    return (rms * np.sqrt(2.0) * np.sin(2.0 * np.pi * freq * t + phase)).astype(np.float64)


def make_processor(fs: int = FS) -> StreamingNoiseProcessor:
    return StreamingNoiseProcessor(
        fs=fs,
        weighting=design_weighting(fs),
        bands=design_bands(fs, order=4),
        calibration=Calibration.pa(),
        qc=QCThresholds(),
    )


def test_pure_tone_1k_94db() -> None:
    processor = make_processor()
    metrics = processor.process_block(
        tone(1000, 94, 1.0), datetime.now(timezone.utc), 1.0, "CH1")
    assert metrics.laeq == pytest.approx(94.0, abs=0.5)
    assert metrics.lceq == pytest.approx(94.0, abs=0.5)
    assert metrics.lzeq == pytest.approx(94.0, abs=0.5)
    assert metrics.freq_spl[4] == pytest.approx(94.0, abs=1.0)
    assert metrics.calibrated is True
    assert metrics.level_unit == "dB SPL"


def test_a_weighting_100hz() -> None:
    processor = make_processor()
    metrics = processor.process_block(
        tone(100, 94, 1.0), datetime.now(timezone.utc), 1.0)
    # IEC A-weighting at 100 Hz is -19.1 dB.
    assert metrics.laeq == pytest.approx(74.9, abs=1.5)


def test_silence_is_none_not_nan() -> None:
    processor = make_processor()
    metrics = processor.process_block(
        np.zeros(FS, dtype=np.float64), datetime.now(timezone.utc), 1.0)
    assert metrics.laeq is None
    assert metrics.lzeq is None
    assert metrics.freq_spl[4] is None
    assert metrics.valid is True
    assert metrics.artifact is False


def test_blocks_are_stateful() -> None:
    """20 Hz energy must be independent of block size when state is kept."""
    signal = tone(20, 94, 20.0)
    results = []
    for block_s in (1.0, 5.0, 10.0):
        processor = make_processor()
        step = int(round(FS * block_s))
        values = []
        for offset in range(0, signal.size - step + 1, step):
            m = processor.process_block(
                signal[offset:offset + step],
                datetime.now(timezone.utc), block_s)
            if m.laeq is not None:
                values.append(m.laeq)
        # Skip filter warm-up, then energy average.
        values = values[1:]
        energy = 10.0 * np.log10(np.mean(10.0 ** (np.array(values) / 10.0)))
        results.append(energy)
    assert max(results) - min(results) <= 0.5


def test_aggregate_10s_and_dose() -> None:
    processor = make_processor()
    segments = []
    for i in range(10):
        segments.append(processor.process_block(
            tone(1000, 94, 1.0), datetime.now(timezone.utc), 1.0, "CH1"))
    row = aggregate_segments(segments, "CH1")
    assert row.duration_s == pytest.approx(10.0)
    assert row.laeq == pytest.approx(94.0, abs=0.5)
    assert row.dose_frac_niosh > 0
    assert row.n_samples == 10 * FS


def test_event_detector_overload() -> None:
    detector = EventDetector(EventConfig())
    m = make_processor().process_block(
        tone(1000, 94, 1.0), datetime.now(timezone.utc), 1.0)
    m.lzpeak = 141.0
    result = detector.check(m)
    assert result.event_type == 3
    assert result.is_overload is True
    assert m.event_type == 3


def test_48k_band_design_marks_nyquist_limits() -> None:
    bands = design_bands(16000, order=4)
    assert bands.sos[-1] is None      # 16 kHz band above Nyquist
    assert bands.sos[0] is not None


def test_fitted_weighting_48k_class_limits() -> None:
    from app.dsp.filters import design_weighting, max_weighting_error
    design = design_weighting(48000)
    assert design.version == "scipy-fit-v1"
    assert max_weighting_error(design, kind="A") <= 1.5
    assert max_weighting_error(design, kind="C") <= 0.7
