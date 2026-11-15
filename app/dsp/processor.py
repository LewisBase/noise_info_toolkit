# -*- coding: utf-8 -*-
"""Stateful streaming noise processor built on NumPy/SciPy.

The processor receives calibrated Pa samples in analysis-sized blocks
(default 1 s), keeps A/C, 1/3-octave and exponential time-weighting state
between calls, and returns a :class:`~app.domain.metrics.Metrics` object.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
from scipy.signal import lfilter, sosfilt

from app.domain.calibration import Calibration
from app.domain.dose import DoseStandard, calculate_dose_increment
from app.domain.metrics import BAND_COUNT, FreqBandMoments, Metrics
from app.dsp.filters import BandDesign, WeightingDesign


@dataclass(frozen=True)
class QCThresholds:
    overload_db: float = 140.0
    underrange_db: float = 30.0
    wearing_db: float = 40.0


def power_to_db(power: float, reference_pressure: float = 20e-6) -> Optional[float]:
    if not np.isfinite(power) or power <= 0.0:
        return None
    return float(10.0 * np.log10(power) - 20.0 * np.log10(reference_pressure))


def peak_to_db(peak: float, reference_pressure: float = 20e-6) -> Optional[float]:
    if not np.isfinite(peak) or peak <= 0.0:
        return None
    return float(20.0 * np.log10(peak / reference_pressure))


def kurtosis_from_moments(n: int, s1: float, s2: float,
                          s3: float, s4: float) -> Optional[float]:
    if n < 2 or not all(np.isfinite(v) for v in (s1, s2, s3, s4)):
        return None
    mu = s1 / n
    m2 = s2 / n - mu * mu
    if not np.isfinite(m2) or m2 <= 1e-30:
        return None
    m4 = s4 / n - 4.0 * mu * s3 / n + 6.0 * mu * mu * s2 / n - 3.0 * mu ** 4
    beta = m4 / (m2 * m2)
    return float(beta) if np.isfinite(beta) and beta >= 0.0 else None


class SosChain:
    """Stateful SciPy SOS filter (transposed direct form II)."""

    def __init__(self, sos: np.ndarray, gain: float = 1.0):
        self.sos = np.asarray(sos, dtype=np.float64)
        self.gain = float(gain)
        self.zi = np.zeros((self.sos.shape[0], 2), dtype=np.float64)

    def process(self, samples: np.ndarray) -> np.ndarray:
        filtered, self.zi = sosfilt(self.sos, samples, zi=self.zi)
        return filtered * self.gain

    def reset(self) -> None:
        self.zi.fill(0.0)


def _one_pole(samples: np.ndarray, alpha: float,
              state: float) -> tuple[np.ndarray, float]:
    """Exponential time weighting: y[n] = a*y[n-1] + (1-a)*x[n]."""
    result, _ = lfilter([1.0 - alpha], [1.0, -alpha], samples,
                        zi=[alpha * float(state)])
    return result, float(result[-1])


class StreamingNoiseProcessor:
    def __init__(self, fs: int, weighting: WeightingDesign,
                 bands: BandDesign, calibration: Calibration,
                 qc: QCThresholds | None = None):
        if int(fs) != int(weighting.fs) or int(fs) != int(bands.fs):
            raise ValueError("filter designs do not match sample rate")
        self.fs = int(fs)
        self.calibration = calibration
        self.qc = qc or QCThresholds()
        self._a = SosChain(weighting.a_sos, weighting.a_gain)
        self._c = SosChain(weighting.c_sos, weighting.c_gain)
        self._bands = [
            None if sos is None else SosChain(sos, gain)
            for sos, gain in zip(bands.sos, bands.gains)
        ]
        self._laf_a = 0.0
        self._las_a = 0.0
        self._laf_c = 0.0
        self._las_c = 0.0
        self._alpha_f = float(np.exp(-1.0 / (0.125 * self.fs)))
        self._alpha_s = float(np.exp(-1.0 / (1.0 * self.fs)))

    def reset(self) -> None:
        self._a.reset()
        self._c.reset()
        for band in self._bands:
            if band is not None:
                band.reset()
        self._laf_a = self._las_a = self._laf_c = self._las_c = 0.0

    def process_block(self, samples: np.ndarray,
                      timestamp_utc: datetime,
                      duration_s: float | None = None,
                      channel: str = "") -> Metrics:
        x = np.asarray(samples, dtype=np.float64).reshape(-1)
        if x.size == 0:
            raise ValueError("empty audio block")
        duration = float(duration_s) if duration_s is not None else x.size / self.fs
        artifact = not bool(np.isfinite(x).all())
        if artifact:
            x = np.where(np.isfinite(x), x, 0.0)

        weighted_a = self._a.process(x)
        weighted_c = self._c.process(x)
        a2 = weighted_a * weighted_a
        c2 = weighted_c * weighted_c
        z2 = x * x

        laf_a_series, self._laf_a = _one_pole(a2, self._alpha_f, self._laf_a)
        las_a_series, self._las_a = _one_pole(a2, self._alpha_s, self._las_a)
        laf_c_series, self._laf_c = _one_pole(c2, self._alpha_f, self._laf_c)
        las_c_series, self._las_c = _one_pole(c2, self._alpha_s, self._las_c)

        band_spl: list[Optional[float]] = []
        band_moments: list[FreqBandMoments] = []
        for band in self._bands:
            if band is None:
                band_spl.append(None)
                band_moments.append(FreqBandMoments())
                continue
            y = band.process(x)
            y2 = y * y
            band_spl.append(power_to_db(float(np.mean(y2))))
            band_moments.append(FreqBandMoments(
                n=int(y.size),
                s1=float(y.sum()),
                s2=float(y2.sum()),
                s3=float((y2 * y).sum()),
                s4=float((y2 * y2).sum()),
            ))

        n = int(x.size)
        metrics = Metrics(
            timestamp_utc=timestamp_utc,
            duration_s=duration,
            channel=channel,
            laeq=power_to_db(float(np.mean(a2))),
            lceq=power_to_db(float(np.mean(c2))),
            lzeq=power_to_db(float(np.mean(z2))),
            laf=power_to_db(self._laf_a),
            las=power_to_db(self._las_a),
            lcf=power_to_db(self._laf_c),
            lcs=power_to_db(self._las_c),
            lafmax=power_to_db(float(np.max(laf_a_series))),
            lasmax=power_to_db(float(np.max(las_a_series))),
            lcsmax=power_to_db(float(np.max(las_c_series))),
            lzpeak=peak_to_db(float(np.max(np.abs(x)))),
            lcpeak=peak_to_db(float(np.max(np.abs(weighted_c)))),
            lapeak=peak_to_db(float(np.max(np.abs(weighted_a)))),
            n_samples=n,
            s1=float(x.sum()),
            s2=float(z2.sum()),
            s3=float((z2 * x).sum()),
            s4=float((z2 * z2).sum()),
            freq_spl=tuple(band_spl),
            freq_moments=tuple(band_moments),
            calibrated=bool(self.calibration.calibrated),
            level_unit="dB SPL" if self.calibration.calibrated else "dBFS",
        )
        metrics.beta_kurtosis = kurtosis_from_moments(
            metrics.n_samples, metrics.s1, metrics.s2, metrics.s3, metrics.s4)
        metrics.kurtosis_total = metrics.beta_kurtosis
        metrics.kurtosis_a = kurtosis_from_moments(
            n, float(weighted_a.sum()), float(a2.sum()),
            float((a2 * weighted_a).sum()), float((a2 * a2).sum()))
        metrics.kurtosis_c = kurtosis_from_moments(
            n, float(weighted_c.sum()), float(c2.sum()),
            float((c2 * weighted_c).sum()), float((c2 * c2).sum()))
        metrics.artifact = artifact
        metrics.valid = not artifact

        if self.calibration.calibrated:
            metrics.overload = (
                metrics.lzpeak is not None and metrics.lzpeak > self.qc.overload_db)
            metrics.underrange = (
                metrics.laeq is not None and metrics.laeq < self.qc.underrange_db)
            metrics.wearing = (
                metrics.laeq is not None and metrics.laeq > self.qc.wearing_db)
            if metrics.laeq is not None:
                for standard, attr in (
                    (DoseStandard.NIOSH, "dose_frac_niosh"),
                    (DoseStandard.OSHA_PEL, "dose_frac_osha_pel"),
                    (DoseStandard.OSHA_HCA, "dose_frac_osha_hca"),
                    (DoseStandard.EU_ISO, "dose_frac_eu_iso"),
                ):
                    setattr(metrics, attr,
                            calculate_dose_increment(
                                metrics.laeq, duration, standard) / 100.0)
        else:
            metrics.overload = False
            metrics.underrange = False
            metrics.wearing = True
        return metrics

    @property
    def band_count(self) -> int:
        return BAND_COUNT
