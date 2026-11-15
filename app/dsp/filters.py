# -*- coding: utf-8 -*-
"""Filter design helpers.

All filters are designed and applied with SciPy/NumPy primitives:
  - ``zpk2sos`` / ``sosfreqz`` for A/C weighting sections;
  - ``butter(..., output="sos")`` for 1/3-octave band-pass filters;
  - ``sosfilt`` in :mod:`app.dsp.processor` for stateful streaming.

No hand-written biquad difference equations or coefficient tables are used.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.signal import butter, sosfreqz, zpk2sos

from app.domain.metrics import BAND_CENTERS_HZ, BAND_COUNT

# IEC 61672-1 analogue pole frequencies (Hz).
_A_POLES_HZ = (20.598997, 107.65265, 737.86223, 12194.217)
_C_POLES_HZ = (20.598997, 12194.217)
_BAND_FACTOR = 2.0 ** (1.0 / 6.0)


@dataclass(frozen=True)
class WeightingDesign:
    fs: int
    a_sos: np.ndarray
    a_gain: float
    c_sos: np.ndarray
    c_gain: float


@dataclass(frozen=True)
class BandDesign:
    fs: int
    centers: tuple[float, ...]
    sos: tuple[Optional[np.ndarray], ...]
    gains: tuple[Optional[float], ...]


def _matched_z(z: list[complex], p: list[complex], k: float,
               fs: int) -> tuple[list[complex], list[complex], float]:
    """Pole-zero matched-z mapping: z_d = exp(s * T).

    SciPy's ``zpk2sos`` handles the second-order section factorization.
    Matched-z avoids the high-frequency warping of a plain bilinear transform
    and is the same structural method used by the C++ implementation.
    """
    period = 1.0 / float(fs)
    zd = [complex(np.exp(complex(value) * period)) for value in z]
    pd = [complex(np.exp(complex(value) * period)) for value in p]
    if len(pd) > len(zd):
        zd.extend([0j] * (len(pd) - len(zd)))
    elif len(zd) > len(pd):
        pd.extend([0j] * (len(zd) - len(pd)))
    return zd, pd, float(k)


def _normalise_1k(sos: np.ndarray, fs: int) -> float:
    _, response = sosfreqz(sos, worN=[1000.0], fs=fs)
    magnitude = float(abs(response[0]))
    if not np.isfinite(magnitude) or magnitude <= 0:
        raise ValueError("invalid weighting design at 1 kHz")
    return 1.0 / magnitude


def design_weighting(fs: int = 48000) -> WeightingDesign:
    """Design A/C weighting with SciPy.

    The analogue prototype is the IEC 61672-1 pole set; the digital mapping is
    matched-z (implemented with NumPy), and SciPy performs SOS factorization and
    the 1 kHz response normalization.
    """
    fs = int(fs)
    if fs < 8000:
        raise ValueError("fs must be >= 8000 Hz")

    a_zeros = [0j] * 4
    a_poles = (
        [-2.0 * np.pi * _A_POLES_HZ[0]] * 2
        + [-2.0 * np.pi * _A_POLES_HZ[1]]
        + [-2.0 * np.pi * _A_POLES_HZ[2]]
        + [-2.0 * np.pi * _A_POLES_HZ[3]] * 2
    )
    za, pa, ka = _matched_z(a_zeros, a_poles, 1.0, fs)
    a_sos = zpk2sos(za, pa, ka, pairing="nearest")
    a_gain = _normalise_1k(a_sos, fs)

    c_zeros = [0j] * 2
    c_poles = (
        [-2.0 * np.pi * _C_POLES_HZ[0]] * 2
        + [-2.0 * np.pi * _C_POLES_HZ[1]] * 2
    )
    zc, pc, kc = _matched_z(c_zeros, c_poles, 1.0, fs)
    c_sos = zpk2sos(zc, pc, kc, pairing="nearest")
    c_gain = _normalise_1k(c_sos, fs)

    return WeightingDesign(fs, a_sos, a_gain, c_sos, c_gain)


def design_bands(fs: int = 48000, order: int = 4) -> BandDesign:
    """Design 9 one-third-octave Butterworth band-pass filters.

    Bands whose upper corner is at/above Nyquist are returned as ``None`` so
    upstream code can mark them unavailable instead of crashing.
    """
    fs = int(fs)
    if order < 1:
        raise ValueError("order must be >= 1")
    sos_items: list[Optional[np.ndarray]] = []
    gains: list[Optional[float]] = []
    for center in BAND_CENTERS_HZ:
        if center * _BAND_FACTOR >= fs / 2.0:
            sos_items.append(None)
            gains.append(None)
            continue
        low = center / _BAND_FACTOR
        high = center * _BAND_FACTOR
        sos = butter(order, [low, high], btype="band", fs=fs, output="sos")
        _, response = sosfreqz(sos, worN=[center], fs=fs)
        magnitude = float(abs(response[0]))
        if not np.isfinite(magnitude) or magnitude <= 0:
            raise ValueError(f"invalid band-pass design at {center} Hz")
        sos_items.append(sos)
        gains.append(1.0 / magnitude)
    return BandDesign(fs, tuple(BAND_CENTERS_HZ), tuple(sos_items), tuple(gains))


def response_db(sos: np.ndarray, gain: float, freqs: list[float],
                fs: int) -> np.ndarray:
    """Return the designed magnitude response in dB relative to 1 kHz."""
    _, h = sosfreqz(sos, worN=freqs, fs=fs)
    return 20.0 * np.log10(np.abs(h) * float(gain) + 1e-30)


IEC_A_REFERENCE_DB: dict[float, float] = {
    20: -50.5, 25: -44.7, 31.5: -39.4, 40: -34.6, 50: -30.2, 63: -26.2,
    80: -22.5, 100: -19.1, 125: -16.1, 160: -13.4, 200: -10.9, 250: -8.6,
    315: -6.6, 400: -4.8, 500: -3.2, 630: -1.9, 800: -0.8, 1000: 0.0,
    1250: 0.6, 1600: 1.0, 2000: 1.2, 2500: 1.3, 3150: 1.2, 4000: 1.0,
    5000: 0.5, 6300: -0.1, 8000: -1.1, 10000: -2.5, 12500: -4.3,
    16000: -6.6, 20000: -9.3,
}
IEC_C_REFERENCE_DB: dict[float, float] = {
    20: -6.2, 25: -4.4, 31.5: -3.0, 40: -2.0, 50: -1.3, 63: -0.8,
    80: -0.5, 100: -0.3, 125: -0.2, 160: -0.1, 200: 0.0, 250: 0.0,
    315: 0.0, 400: 0.0, 500: 0.0, 630: 0.0, 800: 0.0, 1000: 0.0,
    1250: 0.0, 1600: -0.1, 2000: -0.2, 2500: -0.3, 3150: -0.5,
    4000: -0.8, 5000: -1.3, 6300: -2.0, 8000: -3.0, 10000: -4.4,
    12500: -6.2, 16000: -8.5, 20000: -11.2,
}


def max_weighting_error(design: WeightingDesign,
                        reference: dict[float, float] | None = None,
                        kind: str = "A") -> float:
    """Maximum absolute error against IEC reference values (practical range)."""
    ref = reference or (IEC_A_REFERENCE_DB if kind == "A" else IEC_C_REFERENCE_DB)
    freqs = [float(f) for f in ref if f < design.fs / 2]
    sos = design.a_sos if kind == "A" else design.c_sos
    gain = design.a_gain if kind == "A" else design.c_gain
    actual = response_db(sos, gain, freqs, design.fs)
    expected = np.array([ref[f] for f in freqs])
    return float(np.max(np.abs(actual - expected)))
