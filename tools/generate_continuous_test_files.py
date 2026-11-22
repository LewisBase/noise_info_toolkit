# -*- coding: utf-8 -*-
"""Create a continuous sequence of 60 s TDMS files for monitoring tests."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from tools.generate_long_test_files import build, load_source, rms_to_pa, write_tdms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path,
                        default=Path("/home/lewisbase/temp_data/test2"))
    parser.add_argument("--out", type=Path,
                        default=Path("/home/lewisbase/github/noise_info_toolkit/test_data/continuous"))
    parser.add_argument("--files", type=int, default=12)
    parser.add_argument("--minutes", type=float, default=1.0)
    parser.add_argument("--level-db", type=float, default=82.0)
    parser.add_argument("--varied", action="store_true",
                        help="vary level per file and add bursts for SSE visibility")
    parser.add_argument("--fs", type=int, default=48000)
    args = parser.parse_args()
    arrays, fs = load_source(args.source)
    base = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)  # 20:00 Beijing
    total = args.files * args.minutes * 60
    source = rms_to_pa(build(arrays, total, fs), args.level_db)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index in range(args.files):
        start_sample = int(index * args.minutes * 60 * fs)
        length = int(args.minutes * 60 * fs)
        data = source[start_sample:start_sample + length].copy()
        if args.varied:
            levels = [76, 84, 79, 92, 78, 88, 81, 95, 77, 86, 90, 80]
            target = levels[index % len(levels)]
            current = float(np.sqrt(np.mean(data ** 2)))
            if current > 0:
                data = data * (20e-6 * 10 ** (target / 20.0) / current)
            if index % 3 == 0:
                t_local = np.arange(data.size) / fs
                at = 20.0
                mask = (t_local >= at) & (t_local < at + 1.0)
                data[mask] += 20e-6 * 10 ** (100 / 20.0) * np.sqrt(2) * np.sin(
                    2 * np.pi * 1000 * t_local[mask])
        start = base + timedelta(minutes=index * args.minutes)
        name = f"cont_{index:03d}_{start.strftime('%Y%m%d_%H%M%S')}.tdms"
        path = out / name
        write_tdms(path, {"Microphone": data}, fs, start, "Pa")
        manifest.append({
            "file": str(path), "duration_s": args.minutes * 60,
            "sample_rate": fs, "channel": "Microphone", "unit": "Pa",
            "start_utc": start.isoformat(), "level_db": args.level_db,
        })
        print("wrote", path, f"{path.stat().st_size / 1024**2:.1f} MiB")
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("manifest", out / "manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
