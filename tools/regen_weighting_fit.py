# -*- coding: utf-8 -*-
"""Generate SciPy least-squares fitted A/C digital filters (48 kHz).

The fit is a standard SciPy ``least_squares`` optimisation over digital pole
locations, with the IEC analogue zeros mapped to z=1.  SciPy's ``zpk2sos``
produces the second-order sections; ``sosfilt`` applies them at runtime.

Usage:
    python -m tools.regen_weighting_fit --fs 48000
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import differential_evolution, least_squares
from scipy.signal import sosfreqz, zpk2sos

from app.dsp.filters import IEC_A_REFERENCE_DB, IEC_C_REFERENCE_DB

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "dsp" / "coefficients"


def _poles(rt: np.ndarray) -> list[complex]:
    result: list[complex] = []
    for index in range(0, len(rt), 2):
        radius = float(np.clip(rt[index], 1e-6, 0.999))
        angle = float(rt[index + 1])
        result.extend([radius * np.exp(1j * angle),
                       radius * np.exp(-1j * angle)])
    return result


def _response(poles: list[complex], nzero: int, freqs: np.ndarray,
              fs: int) -> np.ndarray:
    z = np.exp(-1j * 2.0 * np.pi * np.asarray(freqs) / fs)
    numerator = (1.0 - z) ** nzero
    denominator = np.ones_like(z, dtype=complex)
    for pole in poles:
        denominator *= 1.0 - pole * z
    return numerator / denominator


def _fit(reference: dict[float, float], nzero: int, npole: int,
         fs: int, seed: int = 1) -> tuple[float, np.ndarray, list[float]]:
    # Never fit above Nyquist: an aliased reference point corrupts the fit.
    freqs = np.array(sorted(f for f in reference if f < fs / 2), dtype=float)
    target = np.array([reference[f] for f in freqs], dtype=float)
    rng = np.random.default_rng(seed)
    best = None
    pairs = npole // 2
    for start in range(8):
        rt = np.zeros(npole)
        if start == 0:
            rt[0::2] = np.linspace(0.4, 0.995, pairs)
            rt[1::2] = np.linspace(0.001, 1.25, pairs)
        else:
            rt[0::2] = rng.uniform(0.2, 0.999, pairs)
            rt[1::2] = rng.uniform(0.0, 1.35, pairs)

        def cost(values):
            poles = _poles(values)
            h = _response(poles, nzero, freqs, fs)
            h0 = _response(poles, nzero, np.array([1000.0]), fs)[0]
            return 20.0 * np.log10(np.abs(h) / np.abs(h0) + 1e-30) - target

        lower = np.zeros(npole)
        upper = np.zeros(npole)
        lower[0::2] = 1e-5
        upper[0::2] = 0.999
        lower[1::2] = 0.0
        upper[1::2] = np.pi
        try:
            result = least_squares(cost, rt, bounds=(lower, upper),
                                   max_nfev=12000, xtol=1e-13, ftol=1e-13,
                                   gtol=1e-13)
        except Exception:
            continue
        error = float(np.max(np.abs(result.fun)))
        if best is None or error < best[0]:
            best = (error, result.x.copy(), result.fun)
    if best is None:
        raise RuntimeError("fit failed")
    return best


def _peaking_sos(f0: float, q: float, gain_db: float, fs: int) -> np.ndarray:
    """Standard RBJ peaking EQ, returned as one SciPy SOS section."""
    w0 = 2.0 * np.pi * f0 / fs
    a = 10.0 ** (gain_db / 40.0)
    alpha = np.sin(w0) / (2.0 * q)
    cos_w0 = np.cos(w0)
    b0 = 1.0 + alpha * a
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * a
    a0 = 1.0 + alpha / a
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / a
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def _build(reference: dict[float, float], nzero: int, npole: int,
           fs: int, peaking: bool = False) -> dict:
    error, rt, residuals = _fit(reference, nzero, npole, fs)
    poles = np.array(_poles(rt), dtype=complex)
    zeros = np.ones(nzero, dtype=complex)
    base_sos = zpk2sos(zeros, poles, 1.0, pairing="nearest")
    freqs = np.array(sorted(f for f in reference if f < fs / 2), dtype=float)
    expected = np.array([reference[f] for f in freqs])
    peaking_info = None
    if peaking:
        def objective(x):
            f0, q, gain_db = x
            if not (50.0 <= f0 <= min(2000.0, fs / 2 * 0.9)
                    and 0.2 <= q <= 8.0 and -6.0 <= gain_db <= 6.0):
                return 1e6
            sos = np.vstack([base_sos, _peaking_sos(f0, q, gain_db, fs)])
            _, h = sosfreqz(sos, worN=[1000.0], fs=fs)
            total_gain = 1.0 / abs(h[0])
            _, response = sosfreqz(sos, worN=freqs, fs=fs)
            actual = 20.0 * np.log10(np.abs(response) * total_gain + 1e-30)
            return float(np.max(np.abs(actual - expected)))

        result = differential_evolution(
            objective,
            bounds=[(50.0, min(2000.0, fs / 2 * 0.9)), (0.2, 8.0), (-6.0, 6.0)],
            tol=1e-6, maxiter=250, popsize=12, seed=2, polish=True)
        f0, q, gain_db = (float(v) for v in result.x)
        sos = np.vstack([base_sos, _peaking_sos(f0, q, gain_db, fs)])
        peaking_info = {"f0_hz": f0, "q": q, "gain_db": gain_db}
    else:
        sos = base_sos
    _, h = sosfreqz(sos, worN=[1000.0], fs=fs)
    gain = float(1.0 / abs(h[0]))
    _, response = sosfreqz(sos, worN=freqs, fs=fs)
    actual = 20.0 * np.log10(np.abs(response) * gain + 1e-30)
    max_error = float(np.max(np.abs(actual - expected)))
    payload = {
        "sos": [[float(v) for v in row] for row in sos],
        "gain": gain,
        "max_error_db": max_error,
        "n_poles": npole,
        "n_zeros": nzero,
    }
    if peaking_info is not None:
        payload["peaking"] = peaking_info
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fs", type=int, default=48000)
    args = parser.parse_args()
    fs = int(args.fs)
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "fs": fs,
        "version": "scipy-fit-v1",
        "a": _build(IEC_A_REFERENCE_DB, 4, 16, fs, peaking=True),
        "c": _build(IEC_C_REFERENCE_DB, 2, 6, fs, peaking=False),
    }
    path = OUT / f"weighting_{fs}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"wrote {path}")
    print("A max error", payload["a"]["max_error_db"])
    print("C max error", payload["c"]["max_error_db"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
