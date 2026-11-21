# -*- coding: utf-8 -*-
from app.storage.repository import Repository


def test_minute_aggregation_is_energy_correct() -> None:
    rows = [
        {"timestamp_utc": "2026-01-01T00:00:00+00:00", "duration_s": 10,
         "laeq": 90.0, "lzpeak": 95.0, "dose_niosh": 0.01,
         "freq_spl": {"1kHz": 90.0}, "n_samples": 10},
        {"timestamp_utc": "2026-01-01T00:00:10+00:00", "duration_s": 10,
         "laeq": 90.0, "lzpeak": 96.0, "dose_niosh": 0.02,
         "freq_spl": {"1kHz": 90.0}, "n_samples": 10},
        {"timestamp_utc": "2026-01-01T00:01:00+00:00", "duration_s": 10,
         "laeq": 80.0, "lzpeak": 85.0, "dose_niosh": 0.03,
         "freq_spl": {"1kHz": 80.0}, "n_samples": 10},
    ]
    out = Repository.aggregate_minutes(rows)
    assert len(out) == 2
    assert out[0]["laeq"] == 90.0
    assert out[0]["lzpeak"] == 96.0
    assert out[0]["dose_niosh"] == 0.03
    assert out[1]["laeq"] == 80.0
    assert out[1]["freq_spl"]["1kHz"] == 80.0
