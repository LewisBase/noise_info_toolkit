# -*- coding: utf-8 -*-
"""Noise dose standards, formulas and pure DoseState helpers."""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict


class DoseStandard(str, Enum):
    NIOSH = "NIOSH"
    OSHA_PEL = "OSHA_PEL"
    OSHA_HCA = "OSHA_HCA"
    EU_ISO = "EU_ISO"


@dataclass(frozen=True)
class DoseProfile:
    name: str
    criterion_level: float
    exchange_rate: float
    threshold: float = 0.0
    reference_duration: float = 8.0


PROFILES: Dict[str, DoseProfile] = {
    DoseStandard.NIOSH.value: DoseProfile(DoseStandard.NIOSH.value, 85.0, 3.0),
    DoseStandard.OSHA_PEL.value: DoseProfile(DoseStandard.OSHA_PEL.value, 90.0, 5.0),
    DoseStandard.OSHA_HCA.value: DoseProfile(DoseStandard.OSHA_HCA.value, 85.0, 5.0),
    DoseStandard.EU_ISO.value: DoseProfile(DoseStandard.EU_ISO.value, 85.0, 3.0),
}


def resolve_profile(standard: DoseStandard | str | DoseProfile) -> DoseProfile:
    if isinstance(standard, DoseProfile):
        return standard
    name = standard.value if isinstance(standard, DoseStandard) else str(standard)
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown dose standard: {name}") from exc


def calculate_dose_increment(laeq: float, duration_s: float,
                             standard: DoseStandard | str | DoseProfile) -> float:
    """Return dose percentage for one interval (0-100+)."""
    profile = resolve_profile(standard)
    if duration_s <= 0 or not math.isfinite(laeq) or laeq < profile.threshold:
        return 0.0
    exponent = (laeq - profile.criterion_level) / profile.exchange_rate
    return 100.0 * (duration_s / 3600.0 / profile.reference_duration) * (2.0 ** exponent)


def calculate_twa(total_dose_pct: float,
                  standard: DoseStandard | str | DoseProfile) -> float | None:
    """Time-weighted average.  None means "no exposure" instead of 0 dB."""
    if total_dose_pct <= 0 or not math.isfinite(total_dose_pct):
        return None
    profile = resolve_profile(standard)
    coefficient = 16.61 if profile.name.startswith("OSHA") else 10.0
    return coefficient * math.log10(total_dose_pct / 100.0) + profile.criterion_level


def calculate_lex(total_dose_pct: float,
                  standard: DoseStandard | str | DoseProfile) -> float | None:
    """LEX,8h from cumulative dose percentage."""
    if total_dose_pct <= 0 or not math.isfinite(total_dose_pct):
        return None
    profile = resolve_profile(standard)
    return 10.0 * math.log10(total_dose_pct / 100.0) + profile.criterion_level


def calculate_allowed_time(laeq: float,
                           standard: DoseStandard | str | DoseProfile) -> float:
    profile = resolve_profile(standard)
    if laeq < profile.threshold:
        return math.inf
    exponent = (laeq - profile.criterion_level) / profile.exchange_rate
    return profile.reference_duration / (2.0 ** exponent)


@dataclass(slots=True)
class DoseState:
    """Cumulative dose fraction and elapsed time (business-side state)."""
    cumulative_dose_frac: float = 0.0
    elapsed_hours: float = 0.0


def accumulate_dose(state: DoseState, dose_frac: float,
                    duration_s: float) -> DoseState:
    if duration_s <= 0 or dose_frac <= 0:
        return state
    return DoseState(
        cumulative_dose_frac=state.cumulative_dose_frac + float(dose_frac),
        elapsed_hours=state.elapsed_hours + float(duration_s) / 3600.0,
    )


def dose_to_pct(state: DoseState) -> float:
    return state.cumulative_dose_frac * 100.0


def dose_to_twa(state: DoseState, standard: DoseStandard | str) -> float | None:
    if state.elapsed_hours <= 0:
        return None
    return calculate_twa(dose_to_pct(state), standard)


def dose_to_lex8h(state: DoseState, standard: DoseStandard | str) -> float | None:
    return calculate_lex(dose_to_pct(state), standard)
