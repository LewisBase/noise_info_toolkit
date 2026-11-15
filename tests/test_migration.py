# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from pathlib import Path

from tools.migrate_legacy_db import migrate


def _legacy_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE time_history (
      id INTEGER PRIMARY KEY, session_id TEXT, timestamp_utc TEXT,
      duration_s REAL, LAeq_dB REAL, LCeq_dB REAL, LZeq_dB REAL,
      LAFmax_dB REAL, LZpeak_dB REAL, LCpeak_dB REAL,
      dose_frac_niosh REAL, dose_frac_osha_pel REAL,
      dose_frac_osha_hca REAL, dose_frac_eu_iso REAL,
      wearing_state INTEGER, overload_flag INTEGER, underrange_flag INTEGER,
      kurtosis_total REAL, kurtosis_a_weighted REAL, kurtosis_c_weighted REAL,
      beta_kurtosis REAL, n_samples INTEGER, sum_x REAL, sum_x2 REAL,
      sum_x3 REAL, sum_x4 REAL, valid_flag INTEGER, artifact_flag INTEGER,
      freq_63hz_spl REAL, freq_125hz_spl REAL, freq_250hz_spl REAL,
      freq_500hz_spl REAL, freq_1khz_spl REAL, freq_2khz_spl REAL,
      freq_4khz_spl REAL, freq_8khz_spl REAL, freq_16khz_spl REAL,
      freq_63hz_n INTEGER, freq_63hz_s1 REAL, freq_63hz_s2 REAL,
      freq_63hz_s3 REAL, freq_63hz_s4 REAL,
      freq_1khz_n INTEGER, freq_1khz_s1 REAL, freq_1khz_s2 REAL,
      freq_1khz_s3 REAL, freq_1khz_s4 REAL
    );
    CREATE TABLE session_summary (
      id INTEGER PRIMARY KEY, session_id TEXT, profile_name TEXT,
      start_time_utc TEXT, end_time_utc TEXT, total_duration_h REAL
    );
    INSERT INTO session_summary VALUES
      (1, 'legacy-s1', 'NIOSH', '2026-01-01 00:00:00', '2026-01-01 01:00:00', 1.0);
    INSERT INTO time_history
      (session_id, timestamp_utc, duration_s, LAeq_dB, LCeq_dB, LZeq_dB,
       dose_frac_niosh, wearing_state, overload_flag, underrange_flag,
       kurtosis_total, n_samples, sum_x, sum_x2, sum_x3, sum_x4,
       valid_flag, artifact_flag, freq_1khz_spl, freq_1khz_n,
       freq_1khz_s1, freq_1khz_s2, freq_1khz_s3, freq_1khz_s4)
    VALUES ('legacy-s1', '2026-01-01 00:00:00', 1.0, 94.0, 94.0, 94.0,
            0.01, 1, 0, 0, 3.0, 48000, 0, 0, 0, 0,
            1, 0, 94.0, 48000, 0, 0, 0, 0);
    """)
    conn.commit()
    conn.close()


def test_migrate_legacy_time_history(tmp_path: Path) -> None:
    path = tmp_path / "noise.db"
    _legacy_db(path)
    report = migrate(path, backup=True)
    assert report["status"] == "migrated"
    assert report["time_history"] == 1
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    row = conn.execute(
        "SELECT laeq, dose_niosh, freq_spl_json FROM time_history").fetchone()
    assert row[0] == 94.0
    assert row[1] == 1.0
    assert "1kHz" in row[2]
    assert conn.execute(
        "SELECT COUNT(*) FROM legacy_time_history").fetchone()[0] == 1
    conn.close()
