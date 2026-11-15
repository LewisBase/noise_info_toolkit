# -*- coding: utf-8 -*-
"""Multi-dimensional acoustic anomaly detector (D1-D4)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.domain.metrics import Metrics


@dataclass(frozen=True)
class EventConfig:
    laf_minor_db: float = 85.0
    laf_moderate_db: float = 95.0
    laf_severe_db: float = 110.0
    impulse_minor_db: float = 6.0
    impulse_severe_db: float = 12.0
    rise_minor_db: float = 10.0
    rise_moderate_db: float = 15.0
    background_delta_db: float = 15.0
    background_tau_s: float = 300.0
    peak_threshold_db: float = 140.0
    underrange_db: float = 30.0
    history_s: float = 16.0
    history_step_s: float = 0.1


@dataclass(slots=True)
class EventResult:
    event_type: int = 0
    severity: int = 0
    laf_db: Optional[float] = None
    las_db: Optional[float] = None
    impulse_db: float = 0.0
    rise_db: float = 0.0
    background_delta_db: float = 0.0
    trigger_laf_threshold: bool = False
    trigger_impulse: bool = False
    trigger_onset: bool = False
    trigger_background: bool = False
    is_overload: bool = False


class EventDetector:
    """Stateful D1-D4 detector.

    ``check`` must be called for every analysis step.  The detector only
    classifies; audio capture is handled by ``app.services.event_audio``.
    """

    def __init__(self, config: EventConfig | None = None):
        self.config = config or EventConfig()
        maxlen = int(self.config.history_s / self.config.history_step_s) + 2
        self._history: deque[tuple[float, float]] = deque(maxlen=maxlen)
        self._time = 0.0
        self._background_power: Optional[float] = None

    def reset(self) -> None:
        self._history.clear()
        self._time = 0.0
        self._background_power = None

    def _lookback(self, seconds: float) -> Optional[float]:
        target = self._time - seconds
        best: Optional[float] = None
        best_distance = float("inf")
        for timestamp, laf in self._history:
            distance = abs(timestamp - target)
            if distance < best_distance:
                best_distance = distance
                best = laf
        return best

    def check(self, metrics: Metrics) -> EventResult:
        result = EventResult(laf_db=metrics.laf, las_db=metrics.las)
        laf = metrics.laf
        las = metrics.las
        dt = metrics.duration_s if metrics.duration_s > 0 else 1.0

        if laf is not None and las is not None:
            result.impulse_db = laf - las

        if laf is not None and self._time > 0.5:
            past = self._lookback(0.5)
            if past is not None:
                result.rise_db = laf - past

        if metrics.laeq is not None and np.isfinite(metrics.laeq):
            power = 10.0 ** (metrics.laeq / 10.0)
            if self._background_power is None:
                self._background_power = power
            else:
                alpha = float(np.exp(-dt / self.config.background_tau_s))
                self._background_power = (
                    alpha * self._background_power + (1.0 - alpha) * power)
            if laf is not None and self._background_power > 0:
                result.background_delta_db = (
                    laf - 10.0 * np.log10(self._background_power))

        laf_minor = laf is not None and laf >= self.config.laf_minor_db
        laf_moderate = laf is not None and laf >= self.config.laf_moderate_db
        laf_severe = laf is not None and laf >= self.config.laf_severe_db
        impulse_minor = result.impulse_db >= self.config.impulse_minor_db
        impulse_severe = result.impulse_db >= self.config.impulse_severe_db
        rise_minor = result.rise_db >= self.config.rise_minor_db
        rise_moderate = result.rise_db >= self.config.rise_moderate_db
        background_trigger = (
            result.background_delta_db >= self.config.background_delta_db)

        if laf_severe or impulse_severe:
            result.event_type = 3
        elif laf_moderate or rise_moderate:
            result.event_type = 2
        elif laf_minor or rise_minor or impulse_minor or background_trigger:
            result.event_type = 1

        result.is_overload = (
            metrics.lzpeak is not None and np.isfinite(metrics.lzpeak)
            and metrics.lzpeak >= self.config.peak_threshold_db)
        if result.is_overload and result.event_type < 3:
            result.event_type = 3

        result.severity = {0: 0, 1: 20, 2: 50, 3: 80}[result.event_type]
        result.trigger_laf_threshold = laf_minor
        result.trigger_impulse = impulse_minor
        result.trigger_onset = rise_minor
        result.trigger_background = background_trigger

        if laf is not None:
            self._history.append((self._time, laf))
        self._time += dt
        metrics.event_type = result.event_type
        metrics.event_severity = result.severity
        return result
