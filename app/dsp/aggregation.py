# -*- coding: utf-8 -*-
"""Duration-weighted aggregation of streaming metric windows."""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np

from app.domain.metrics import BAND_COUNT, FreqBandMoments, Metrics
from app.dsp.processor import kurtosis_from_moments


def _power_to_db(power: float, reference_pressure: float = 20e-6) -> Optional[float]:
    if not np.isfinite(power) or power <= 0:
        return None
    return float(10.0 * np.log10(power) - 20.0 * np.log10(reference_pressure))


def energy_average(values: Iterable[Optional[float]],
                   weights: Iterable[float]) -> Optional[float]:
    total_weight = 0.0
    total_power = 0.0
    for value, weight in zip(values, weights):
        if value is None or not np.isfinite(value) or weight <= 0:
            continue
        total_power += (10.0 ** (float(value) / 10.0)) * float(weight)
        total_weight += float(weight)
    if total_weight <= 0 or total_power <= 0:
        return None
    return float(10.0 * np.log10(total_power / total_weight))


def _max_optional(values: Iterable[Optional[float]]) -> Optional[float]:
    valid = [float(v) for v in values if v is not None and np.isfinite(v)]
    return max(valid) if valid else None


def aggregate_segments(segments: Sequence[Metrics],
                       channel: str | None = None) -> Metrics:
    if not segments:
        raise ValueError("cannot aggregate empty segments")
    total_duration = sum(float(s.duration_s) for s in segments)
    if total_duration <= 0:
        raise ValueError("total duration must be positive")
    weights = [float(s.duration_s) for s in segments]
    last = segments[-1]

    out = Metrics(
        timestamp_utc=segments[0].timestamp_utc,
        duration_s=total_duration,
        channel=channel if channel is not None else last.channel,
    )
    out.laeq = energy_average((s.laeq for s in segments), weights)
    out.lceq = energy_average((s.lceq for s in segments), weights)
    out.lzeq = energy_average((s.lzeq for s in segments), weights)

    out.lafmax = _max_optional(s.lafmax for s in segments)
    out.lasmax = _max_optional(s.lasmax for s in segments)
    out.lcsmax = _max_optional(s.lcsmax for s in segments)
    out.lzpeak = _max_optional(s.lzpeak for s in segments)
    out.lcpeak = _max_optional(s.lcpeak for s in segments)
    out.lapeak = _max_optional(s.lapeak for s in segments)

    # Instantaneous time-weighted values are represented by the last window.
    out.laf = last.laf
    out.las = last.las
    out.lcf = last.lcf
    out.lcs = last.lcs

    out.freq_spl = tuple(
        energy_average((s.freq_spl[i] for s in segments), weights)
        for i in range(BAND_COUNT)
    )
    out.freq_moments = tuple(
        FreqBandMoments(
            n=sum(s.freq_moments[i].n for s in segments),
            s1=sum(s.freq_moments[i].s1 for s in segments),
            s2=sum(s.freq_moments[i].s2 for s in segments),
            s3=sum(s.freq_moments[i].s3 for s in segments),
            s4=sum(s.freq_moments[i].s4 for s in segments),
        )
        for i in range(BAND_COUNT)
    )

    out.dose_frac_niosh = sum(s.dose_frac_niosh for s in segments)
    out.dose_frac_osha_pel = sum(s.dose_frac_osha_pel for s in segments)
    out.dose_frac_osha_hca = sum(s.dose_frac_osha_hca for s in segments)
    out.dose_frac_eu_iso = sum(s.dose_frac_eu_iso for s in segments)

    out.n_samples = sum(s.n_samples for s in segments)
    out.s1 = sum(s.s1 for s in segments)
    out.s2 = sum(s.s2 for s in segments)
    out.s3 = sum(s.s3 for s in segments)
    out.s4 = sum(s.s4 for s in segments)
    out.beta_kurtosis = kurtosis_from_moments(
        out.n_samples, out.s1, out.s2, out.s3, out.s4)
    out.kurtosis_total = out.beta_kurtosis
    out.kurtosis_a = _max_optional(s.kurtosis_a for s in segments)
    out.kurtosis_c = _max_optional(s.kurtosis_c for s in segments)

    out.overload = any(s.overload for s in segments)
    out.underrange = any(s.underrange for s in segments)
    out.wearing = all(s.wearing for s in segments)
    out.valid = all(s.valid for s in segments)
    out.artifact = any(s.artifact for s in segments)
    out.event_type = max(s.event_type for s in segments)
    out.event_severity = max(s.event_severity for s in segments)
    out.calibrated = all(s.calibrated for s in segments)
    out.level_unit = last.level_unit
    return out


def aggregate_minutes(windows: Sequence[Metrics],
                      channel: str | None = None) -> Metrics:
    """Aggregate six 10 s windows (or any duration) into a minute row."""
    return aggregate_segments(windows, channel=channel)
