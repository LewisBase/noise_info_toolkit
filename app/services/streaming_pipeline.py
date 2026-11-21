# -*- coding: utf-8 -*-
"""File-level streaming pipeline: TDMS -> SciPy DSP -> windows/events.

This module is deliberately storage-agnostic: callers provide optional
``on_window`` / ``on_event`` callbacks and can persist results in any backend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

from app.dsp.aggregation import aggregate_segments
from app.dsp.event_detector import EventConfig, EventDetector
from app.dsp.filters import design_bands, design_weighting
from app.dsp.processor import QCThresholds, StreamingNoiseProcessor
from app.domain.metrics import Metrics
from app.services.event_audio import EventAudioCapture, EventClip
from app.io.tdms_source import TdmsChannelSource


@dataclass(frozen=True)
class PipelineConfig:
    read_window_s: float = 10.0
    analysis_step_s: float = 1.0
    persist_window_s: float = 10.0
    band_order: int = 4
    event_pre_s: float = 5.0
    event_post_s: float = 10.0
    event_max_s: float = 60.0
    event_min_gap_s: float = 2.0
    event_dir: Path = Path("audio_events")
    event_config: EventConfig = field(default_factory=EventConfig)

    def validate(self) -> None:
        if not (0 < self.analysis_step_s <= self.read_window_s <= 60):
            raise ValueError("require 0 < analysis_step_s <= read_window_s <= 60")
        ratio = self.persist_window_s / self.analysis_step_s
        if abs(ratio - round(ratio)) > 1e-9:
            raise ValueError("persist_window_s must be a multiple of analysis_step_s")


@dataclass
class FileProcessingResult:
    file_path: Path
    channel: str
    metrics: list[Metrics] = field(default_factory=list)
    events: list[EventClip] = field(default_factory=list)
    summary: Optional[Metrics] = None
    capture: Optional[EventAudioCapture] = None
    sample_rate: int = 0


def process_tdms_file(path: str | Path,
                      config: PipelineConfig | None = None,
                      channel: str | None = None,
                      on_window: Optional[Callable[[Metrics], None]] = None,
                      on_event: Optional[Callable[[EventClip], None]] = None,
                      source: TdmsChannelSource | None = None,
                      capture: EventAudioCapture | None = None,
                      flush_capture: bool = True
                      ) -> FileProcessingResult:
    """Process one TDMS channel in bounded 10 s windows / 1 s sub-blocks."""
    config = config or PipelineConfig()
    config.validate()
    path = Path(path)

    source = source or TdmsChannelSource(path, channel=channel)
    calibration = source.calibration()
    channel_name = channel or source.channel_name
    processor = StreamingNoiseProcessor(
        fs=source.fs,
        weighting=design_weighting(source.fs),
        bands=design_bands(source.fs, order=config.band_order),
        calibration=calibration,
        qc=QCThresholds(),
    )
    detector = EventDetector(config.event_config)
    if capture is None:
        capture = EventAudioCapture(
            fs=source.fs,
            out_dir=config.event_dir / channel_name,
            pre_s=config.event_pre_s,
            post_s=config.event_post_s,
            max_s=config.event_max_s,
            min_gap_s=config.event_min_gap_s,
            calibrated=calibration.calibrated,
            level_unit="dB SPL" if calibration.calibrated else "dBFS",
        )
    result = FileProcessingResult(file_path=path, channel=channel_name,
                                  sample_rate=int(source.fs))
    result.capture = capture
    pending: list[Metrics] = []
    persist_steps = max(1, int(round(config.persist_window_s / config.analysis_step_s)))
    step = max(1, int(round(config.analysis_step_s * source.fs)))

    try:
        for raw, window_start, _ in source.iter_windows(config.read_window_s):
            samples = calibration.to_pa(raw)
            for offset in range(0, samples.size, step):
                chunk = samples[offset:offset + step]
                if chunk.size == 0:
                    continue
                timestamp = window_start + timedelta(seconds=offset / source.fs)
                segment = processor.process_block(
                    chunk, timestamp, chunk.size / source.fs, channel_name)
                event_result = detector.check(segment)
                clip = capture.push(chunk, timestamp, event_result)
                if clip is not None:
                    result.events.append(clip)
                    if on_event is not None:
                        on_event(clip)
                pending.append(segment)
                if len(pending) >= persist_steps:
                    row = aggregate_segments(pending, channel_name)
                    result.metrics.append(row)
                    if on_window is not None:
                        on_window(row)
                    pending.clear()

        if pending:
            row = aggregate_segments(pending, channel_name)
            result.metrics.append(row)
            if on_window is not None:
                on_window(row)
        if flush_capture:
            clip = capture.flush()
            if clip is not None:
                result.events.append(clip)
                if on_event is not None:
                    on_event(clip)
        if result.metrics:
            result.summary = aggregate_segments(result.metrics, channel_name)
        return result
    finally:
        source.close()
