# -*- coding: utf-8 -*-
import math

import pytest

from app.web.formatters import BAND_ORDER, band_series, energy_mean, fmt


def test_fmt_handles_missing_and_nonfinite() -> None:
    assert fmt(None) == "—"
    assert fmt(float("nan")) == "—"
    assert fmt(94.0) == "94.0 dB"
    assert fmt(12.345, "%", 2) == "12.35 %"


def test_energy_mean_is_energy_not_arithmetic() -> None:
    assert energy_mean([90.0, 90.0]) == 90.0
    result = energy_mean([80.0, 90.0])
    assert result is not None
    assert result == pytest.approx(87.4036, abs=1e-3)
    assert result > 85.0  # energy mean, not arithmetic mean


def test_band_series_order_and_nulls() -> None:
    names, values = band_series({"1kHz": 94.0})
    assert names == list(BAND_ORDER)
    assert values[4] == 94.0
    assert values[0] is None
    assert not any(isinstance(v, float) and math.isnan(v) for v in values)
