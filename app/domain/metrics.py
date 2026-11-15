# -*- coding: utf-8 -*-
"""Core metric data structures.

The goal is to keep one definition for all frequency-band data instead of
repeating 45 named fields in every module.  The database layer stores these
two tuples as JSON; API/UI expose them as dictionaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional

BAND_CENTERS_HZ: tuple[float, ...] = (
    63.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0
)
BAND_NAMES: tuple[str, ...] = (
    "63Hz", "125Hz", "250Hz", "500Hz", "1kHz",
    "2kHz", "4kHz", "8kHz", "16kHz",
)
BAND_COUNT = len(BAND_CENTERS_HZ)

EVENT_NONE = 0
EVENT_MINOR = 1
EVENT_MODERATE = 2
EVENT_SEVERE = 3
EVENT_NAMES = {
    EVENT_NONE: "NONE",
    EVENT_MINOR: "MINOR",
    EVENT_MODERATE: "MODERATE",
    EVENT_SEVERE: "SEVERE",
}


@dataclass(slots=True)
class FreqBandMoments:
    """Raw moments for one 1/3-octave band (n, S1, S2, S3, S4)."""
    n: int = 0
    s1: float = 0.0
    s2: float = 0.0
    s3: float = 0.0
    s4: float = 0.0

    def as_list(self) -> list[float]:
        return [self.n, self.s1, self.s2, self.s3, self.s4]


@dataclass(slots=True)
class Metrics:
    """Metrics for one analysis window (default 10 s).

    Atomic units:
      - levels are dB SPL when ``calibrated`` is true, otherwise relative dB;
      - ``dose_frac_*`` are fractions in [0, 1], not percentages;
      - ``freq_spl`` and ``freq_moments`` always have 9 elements.
    """
    timestamp_utc: datetime
    duration_s: float
    channel: str = ""

    laeq: Optional[float] = None
    lceq: Optional[float] = None
    lzeq: Optional[float] = None
    laf: Optional[float] = None
    las: Optional[float] = None
    lcf: Optional[float] = None
    lcs: Optional[float] = None
    lafmax: Optional[float] = None
    lasmax: Optional[float] = None
    lcsmax: Optional[float] = None
    lzpeak: Optional[float] = None
    lcpeak: Optional[float] = None
    lapeak: Optional[float] = None

    dose_frac_niosh: float = 0.0
    dose_frac_osha_pel: float = 0.0
    dose_frac_osha_hca: float = 0.0
    dose_frac_eu_iso: float = 0.0

    overload: bool = False
    underrange: bool = False
    wearing: bool = True
    valid: bool = True
    artifact: bool = False
    event_type: int = EVENT_NONE
    event_severity: int = 0

    kurtosis_total: Optional[float] = None
    kurtosis_a: Optional[float] = None
    kurtosis_c: Optional[float] = None
    beta_kurtosis: Optional[float] = None
    n_samples: int = 0
    s1: float = 0.0
    s2: float = 0.0
    s3: float = 0.0
    s4: float = 0.0

    freq_spl: tuple[Optional[float], ...] = (None,) * BAND_COUNT
    freq_moments: tuple[FreqBandMoments, ...] = field(
        default_factory=lambda: tuple(FreqBandMoments() for _ in range(BAND_COUNT))
    )

    calibrated: bool = False
    level_unit: str = "dBFS"

    def band_spl(self, name_or_index: str | int) -> Optional[float]:
        idx = (BAND_NAMES.index(name_or_index)
               if isinstance(name_or_index, str) else int(name_or_index))
        return self.freq_spl[idx]

    def band_moments(self, name_or_index: str | int) -> FreqBandMoments:
        idx = (BAND_NAMES.index(name_or_index)
               if isinstance(name_or_index, str) else int(name_or_index))
        return self.freq_moments[idx]

    @property
    def event_name(self) -> str:
        return EVENT_NAMES.get(int(self.event_type), "NONE")

    @property
    def dose_pct_niosh(self) -> float:
        return self.dose_frac_niosh * 100.0

    @property
    def dose_pct_osha_pel(self) -> float:
        return self.dose_frac_osha_pel * 100.0

    @property
    def dose_pct_osha_hca(self) -> float:
        return self.dose_frac_osha_hca * 100.0

    @property
    def dose_pct_eu_iso(self) -> float:
        return self.dose_frac_eu_iso * 100.0

    def to_dict(self, *, include_sets: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "duration_s": self.duration_s,
            "channel": self.channel,
            "laeq": self.laeq,
            "lceq": self.lceq,
            "lzeq": self.lzeq,
            "laf": self.laf,
            "las": self.las,
            "lcf": self.lcf,
            "lcs": self.lcs,
            "lafmax": self.lafmax,
            "lasmax": self.lasmax,
            "lcsmax": self.lcsmax,
            "lzpeak": self.lzpeak,
            "lcpeak": self.lcpeak,
            "lapeak": self.lapeak,
            "dose_frac_niosh": self.dose_frac_niosh,
            "dose_frac_osha_pel": self.dose_frac_osha_pel,
            "dose_frac_osha_hca": self.dose_frac_osha_hca,
            "dose_frac_eu_iso": self.dose_frac_eu_iso,
            "overload": self.overload,
            "underrange": self.underrange,
            "wearing": self.wearing,
            "valid": self.valid,
            "artifact": self.artifact,
            "event_type": self.event_type,
            "event_severity": self.event_severity,
            "kurtosis_total": self.kurtosis_total,
            "kurtosis_a": self.kurtosis_a,
            "kurtosis_c": self.kurtosis_c,
            "beta_kurtosis": self.beta_kurtosis,
            "n_samples": self.n_samples,
            "s1": self.s1,
            "s2": self.s2,
            "s3": self.s3,
            "s4": self.s4,
            "freq_spl": {
                name: self.freq_spl[i] for i, name in enumerate(BAND_NAMES)
            },
            "freq_moments": {
                name: self.freq_moments[i].as_list()
                for i, name in enumerate(BAND_NAMES)
            },
            "calibrated": self.calibrated,
            "level_unit": self.level_unit,
        }
        if include_sets:
            data["event_name"] = self.event_name
        return data


def freq_spl_dict(values: Iterable[Optional[float]]) -> dict[str, Optional[float]]:
    return {name: value for name, value in zip(BAND_NAMES, values)}


def freq_moments_dict(
    values: Iterable[FreqBandMoments],
) -> dict[str, list[float]]:
    return {name: m.as_list() for name, m in zip(BAND_NAMES, values)}
