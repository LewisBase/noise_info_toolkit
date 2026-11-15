# -*- coding: utf-8 -*-
"""Calibration and raw-unit conversion.

The DSP layer always receives Pa.  TDMS files may contain Pa, volts or ADC
counts; this module is the single place where the conversion happens.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if np.isfinite(result) else default


@dataclass(frozen=True)
class Calibration:
    name: str
    unit: str
    pa_per_unit: float = 1.0
    offset_pa: float = 0.0
    offset_db: float = 0.0
    calibrated: bool = False

    def to_pa(self, raw: np.ndarray) -> np.ndarray:
        """Convert raw samples to Pa (or relative units when uncalibrated)."""
        data = np.asarray(raw, dtype=np.float64)
        data = data * float(self.pa_per_unit) + float(self.offset_pa)
        if self.offset_db:
            data = data * (10.0 ** (float(self.offset_db) / 20.0))
        return data

    @classmethod
    def pa(cls, offset_db: float = 0.0) -> "Calibration":
        return cls("default-pa", "Pa", 1.0, 0.0, offset_db, True)

    @classmethod
    def uncalibrated(cls, unit: str = "counts") -> "Calibration":
        return cls("uncalibrated", unit, 1.0, 0.0, 0.0, False)

    @classmethod
    def from_tdms_properties(cls, props: Mapping[str, Any]) -> "Calibration":
        """Build a calibration from common NI-DAQmx/TDMS channel properties.

        Supported properties (case-insensitive lookup):
          - unit_string / NI_UnitDescription / Units
          - Sensor_Sensitivity / mic_sensitivity_mv_pa  (mV/Pa)
          - preamp_gain_db
          - adc_counts_per_pa
          - calibration_offset_db
        """
        lower = {str(k).lower(): v for k, v in props.items()}

        def get(*names: str, default=None):
            for name in names:
                if name.lower() in lower:
                    return lower[name.lower()]
            return default

        unit = str(get("unit_string", "ni_unitdescription", "units",
                        default="Pa")).strip()
        unit_norm = unit.lower().replace(" ", "")
        gain_db = _as_float(get("preamp_gain_db", "preampgaindb"), 0.0) or 0.0
        gain_linear = 10.0 ** (gain_db / 20.0)
        offset_db = _as_float(get("calibration_offset_db", "offset_db"), 0.0) or 0.0
        offset_pa = _as_float(get("offset_pa", "dc_offset"), 0.0) or 0.0
        sens_mv = _as_float(get("sensor_sensitivity", "mic_sensitivity_mv_pa",
                                "sensitivity_mv_pa"))

        if unit_norm in ("pa", "pascal", "pascals"):
            return cls("tdms-pa", "Pa", 1.0, offset_pa, offset_db, True)

        if unit_norm in ("v", "volt", "volts"):
            if sens_mv is None or sens_mv <= 0:
                return cls("uncalibrated", "V", 1.0, offset_pa, offset_db, False)
            # V -> Pa: 1000 / (mV/Pa), then divide preamp gain
            return cls("tdms-v", "V", 1000.0 / sens_mv / gain_linear,
                       offset_pa, offset_db, True)

        if unit_norm in ("mv", "millivolt", "millivolts"):
            if sens_mv is None or sens_mv <= 0:
                return cls("uncalibrated", "mV", 1.0, offset_pa, offset_db, False)
            return cls("tdms-mv", "mV", 1.0 / sens_mv / gain_linear,
                       offset_pa, offset_db, True)

        counts_per_pa = _as_float(get("adc_counts_per_pa", "counts_per_pa"))
        if counts_per_pa is not None and counts_per_pa > 0:
            return cls("tdms-counts", "counts", 1.0 / counts_per_pa / gain_linear,
                       offset_pa, offset_db, True)

        return cls("uncalibrated", unit or "counts", 1.0,
                   offset_pa, offset_db, False)
