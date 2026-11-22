# -*- coding: utf-8 -*-
"""Pure formatting helpers for the Streamlit UI (testable without Streamlit)."""
from __future__ import annotations

import math
from typing import Iterable, Mapping, Optional

import numpy as np

BAND_ORDER = ("63Hz", "125Hz", "250Hz", "500Hz", "1kHz",
              "2kHz", "4kHz", "8kHz", "16kHz")


def fmt(value, unit: str = "dB", digits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"{number:.{digits}f} {unit}"


def energy_mean(values: Iterable[Optional[float]]) -> Optional[float]:
    valid = [float(v) for v in values if v is not None and np.isfinite(v)]
    if not valid:
        return None
    return float(10.0 * np.log10(np.mean(10.0 ** (np.asarray(valid) / 10.0))))


def band_series(freq_spl: Mapping[str, float] | None) -> tuple[list[str], list]:
    freq_spl = freq_spl or {}
    return list(BAND_ORDER), [freq_spl.get(name) for name in BAND_ORDER]


def local_timestamp(iso_utc: str, tz) -> str:
    from datetime import datetime
    value = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
