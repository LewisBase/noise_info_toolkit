# -*- coding: utf-8 -*-
"""Generate longer TDMS test files from the recorder files in test2.

The source files have no wf_increment/wf_start_time, so generated files get
explicit metadata.  Output is intentionally not part of the repository.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from nptdms import ChannelObject, TdmsFile, TdmsWriter


def load_source(source_dir: Path) -> tuple[list[np.ndarray], int]:
    arrays = []
    fs = 48000
    for path in sorted(source_dir.glob("*.tdms")):
        with TdmsFile.open(str(path)) as tdms:
            channel = tdms.groups()[0].channels()[0]
            arrays.append(np.asarray(channel[:], dtype=np.float64))
    if not arrays:
        raise SystemExit(f"no TDMS in {source_dir}")
    # test2 files are 48 kHz, 60 s each
    return arrays, fs


def build(arrays: list[np.ndarray], seconds: float, fs: int) -> np.ndarray:
    source = np.concatenate(arrays)
    need = int(round(seconds * fs))
    if need <= source.size:
        return source[:need].copy()
    reps = int(np.ceil(need / source.size))
    return np.tile(source, reps)[:need].copy()


def rms_to_pa(data: np.ndarray, level_db: float) -> np.ndarray:
    target = 20e-6 * 10 ** (level_db / 20.0)
    current = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
    if current <= 0:
        return data.astype(np.float64)
    return data.astype(np.float64) * (target / current)


def write_tdms(path: Path, channels: dict[str, np.ndarray], fs: int,
               start: datetime, unit: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    objects = []
    for name, data in channels.items():
        props = {
            "wf_increment": 1.0 / fs,
            "wf_start_time": start,
            "unit_string": unit,
        }
        objects.append(ChannelObject("NoiseData", name,
                                     data.astype(np.float32), properties=props))
    with TdmsWriter(str(path)) as writer:
        writer.write_segment(objects)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path,
                        default=Path("/home/lewisbase/temp_data/test2"))
    parser.add_argument("--out", type=Path,
                        default=Path("/home/lewisbase/temp_data/test2_generated"))
    parser.add_argument("--fs", type=int, default=48000)
    parser.add_argument("--no-long20", action="store_true",
                        help="skip the 20 min file to save disk")
    args = parser.parse_args()
    arrays, fs = load_source(args.source)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    base = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)  # 20:00 Asia/Shanghai
    manifest = []

    specs = [
        ("long_02min_raw.tdms", 120, "raw", "Microphone", None, 0),
        ("long_05min_raw.tdms", 300, "raw", "Microphone", None, 10),
        ("long_10min_raw.tdms", 600, "raw", "Microphone", None, 20),
    ]
    if not args.no_long20:
        specs.append(("long_20min_raw.tdms", 1200, "raw", "Microphone", None, 30))

    for name, seconds, kind, channel, level, offset_min in specs:
        data = build(arrays, seconds, fs)
        path = out / name
        write_tdms(path, {channel: data}, fs,
                   base + timedelta(minutes=offset_min), "")
        manifest.append({
            "file": str(path), "duration_s": seconds, "sample_rate": fs,
            "channels": [channel], "unit": "", "kind": "raw",
        })
        print("wrote", path, f"{path.stat().st_size / 1024**2:.1f} MiB")

    # Pa-calibrated 5 min at 94 dB SPL (will generate LAF events at default 85).
    basic = rms_to_pa(build(arrays, 300, fs), 94.0)
    path = out / "long_05min_pa_94.tdms"
    write_tdms(path, {"Microphone": basic}, fs, base + timedelta(minutes=40), "Pa")
    manifest.append({"file": str(path), "duration_s": 300, "sample_rate": fs,
                     "channels": ["Microphone"], "unit": "Pa",
                     "kind": "94dB"})
    print("wrote", path, f"{path.stat().st_size / 1024**2:.1f} MiB")

    # 5 min Pa baseline 75 dB with 100 dB bursts every 45 s.
    event_data = rms_to_pa(build(arrays, 300, fs), 75.0)
    t = np.arange(event_data.size) / fs
    burst_level = 20e-6 * 10 ** (100 / 20.0)
    for at in np.arange(30.0, 300.0, 45.0):
        mask = (t >= at) & (t < at + 1.0)
        event_data[mask] += burst_level * np.sqrt(2) * np.sin(
            2 * np.pi * 1000 * t[mask])
    path = out / "long_05min_pa_events.tdms"
    write_tdms(path, {"Microphone": event_data}, fs,
               base + timedelta(minutes=50), "Pa")
    manifest.append({"file": str(path), "duration_s": 300, "sample_rate": fs,
                     "channels": ["Microphone"], "unit": "Pa",
                     "kind": "75dB+100dB bursts"})
    print("wrote", path, f"{path.stat().st_size / 1024**2:.1f} MiB")

    # 10 min dual-channel Pa file.
    dual_base = build(arrays, 600, fs)
    ch1 = rms_to_pa(dual_base, 82.0)
    ch2 = rms_to_pa(dual_base, 88.0)
    path = out / "long_10min_dual_pa.tdms"
    write_tdms(path, {"CH1": ch1, "CH2": ch2}, fs,
               base + timedelta(minutes=60), "Pa")
    manifest.append({"file": str(path), "duration_s": 600, "sample_rate": fs,
                     "channels": ["CH1", "CH2"], "unit": "Pa",
                     "kind": "dual 82/88dB"})
    print("wrote", path, f"{path.stat().st_size / 1024**2:.1f} MiB")

    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("manifest", out / "manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
