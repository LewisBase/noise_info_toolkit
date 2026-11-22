# -*- coding: utf-8 -*-
"""Migrate the legacy Python DB schema to the field-deployment schema.

Only the old ``time_history`` table conflicts with the new schema by name.
The script:

1. backs up the DB;
2. renames ``time_history`` to ``legacy_time_history``;
3. creates the new tables via :class:`app.storage.Database`;
4. copies legacy sessions / time history / events into the new rows;
5. leaves all ``legacy_*`` tables intact for audit/rollback.

Usage:
    python -m tools.migrate_legacy_db --db Database/noise_info.db --backup
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.storage import Database

BAND_COLUMNS = (
    ("63Hz", "freq_63hz"), ("125Hz", "freq_125hz"),
    ("250Hz", "freq_250hz"), ("500Hz", "freq_500hz"),
    ("1kHz", "freq_1khz"), ("2kHz", "freq_2khz"),
    ("4kHz", "freq_4khz"), ("8kHz", "freq_8khz"),
    ("16kHz", "freq_16khz"),
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({name})")}


def _utc(value) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def migrate(db_path: Path, backup: bool = True, dry_run: bool = False) -> dict:
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    if backup and not dry_run:
        backup_path = db_path.with_suffix(
            db_path.suffix + f".bak-{datetime.now(timezone.utc):%Y%m%d%H%M%S}")
        shutil.copy2(db_path, backup_path)
    else:
        backup_path = None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "time_history"):
            return {"status": "no-legacy-time-history", "backup": str(backup_path)}
        cols = _columns(conn, "time_history")
        if "LAeq_dB" not in cols:
            return {"status": "already-new-schema", "backup": str(backup_path)}
        if _table_exists(conn, "legacy_time_history"):
            return {"status": "legacy-table-already-exists",
                    "backup": str(backup_path)}
        if dry_run:
            count = conn.execute("SELECT COUNT(*) FROM time_history").fetchone()[0]
            return {"status": "dry-run", "legacy_rows": count,
                    "backup": str(backup_path)}

        conn.execute("ALTER TABLE time_history RENAME TO legacy_time_history")
        conn.commit()
    finally:
        conn.close()

    # Create the new schema.  The old time_history name is now free.
    database = Database(db_path)
    report = {"status": "migrated", "backup": str(backup_path),
              "sessions": 0, "time_history": 0, "events": 0}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        legacy_cols = _columns(conn, "legacy_time_history")

        # Sessions from legacy summaries and distinct time-history ids.
        session_ids = set()
        if _table_exists(conn, "session_summary"):
            for row in conn.execute("SELECT * FROM session_summary"):
                session_ids.add(str(row["session_id"]))
        for row in conn.execute(
                "SELECT DISTINCT session_id FROM legacy_time_history "
                "WHERE session_id IS NOT NULL"):
            session_ids.add(str(row["session_id"]))
        for sid in sorted(session_ids):
            start = None
            end = None
            duration = 0.0
            profile = "NIOSH"
            if _table_exists(conn, "session_summary"):
                summary = conn.execute(
                    "SELECT * FROM session_summary WHERE session_id=?",
                    (sid,)).fetchone()
                if summary is not None:
                    start = _utc(summary["start_time_utc"])
                    end = _utc(summary["end_time_utc"])
                    duration = float(summary["total_duration_h"] or 0) * 3600.0
                    profile = summary["profile_name"] or "NIOSH"
            if start is None:
                first = conn.execute(
                    "SELECT MIN(timestamp_utc) FROM legacy_time_history "
                    "WHERE session_id=?", (sid,)).fetchone()[0]
                start = _utc(first) or datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO sessions "
                "(id, channel, profile, start_time_utc, end_time_utc, state, "
                " total_duration_s, created_at) "
                "VALUES (?, 'CH1', ?, ?, ?, 'stopped', ?, ?)",
                (sid, profile, start, end, duration,
                 datetime.now(timezone.utc).isoformat()))
            report["sessions"] += 1

        rows = conn.execute("SELECT * FROM legacy_time_history").fetchall()
        for row in rows:
            data = {key: row[key] for key in row.keys()}
            sid = data.get("session_id") or "legacy-unknown"
            if sid == "legacy-unknown":
                conn.execute(
                    "INSERT OR IGNORE INTO sessions "
                    "(id, channel, profile, start_time_utc, state, created_at) "
                    "VALUES (?, 'CH1', 'NIOSH', ?, 'stopped', ?)",
                    (sid, datetime.now(timezone.utc).isoformat(),
                     datetime.now(timezone.utc).isoformat()))
            timestamp = _utc(data.get("timestamp_utc")) or datetime.now(
                timezone.utc).isoformat()
            freq_spl = {}
            freq_moments = {}
            for name, prefix in BAND_COLUMNS:
                freq_spl[name] = data.get(f"{prefix}_spl")
                freq_moments[name] = [
                    data.get(f"{prefix}_n", 0),
                    data.get(f"{prefix}_s1", 0.0),
                    data.get(f"{prefix}_s2", 0.0),
                    data.get(f"{prefix}_s3", 0.0),
                    data.get(f"{prefix}_s4", 0.0),
                ]
            conn.execute(
                "INSERT INTO time_history ("
                "session_id, channel, timestamp_utc, duration_s, laeq, lceq, "
                "lzeq, lafmax, lzpeak, lcpeak, dose_niosh, dose_osha_pel, "
                "dose_osha_hca, dose_eu_iso, overload, underrange, wearing, "
                "valid, artifact, event_type, event_severity, kurtosis_total, "
                "kurtosis_a, kurtosis_c, beta_kurtosis, n_samples, s1, s2, s3, s4, "
                "freq_spl_json, freq_moments_json, calibrated, level_unit) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, "CH1", timestamp,
                 data.get("duration_s") or 1.0,
                 data.get("LAeq_dB"), data.get("LCeq_dB"), data.get("LZeq_dB"),
                 data.get("LAFmax_dB"), data.get("LZpeak_dB"), data.get("LCpeak_dB"),
                 float(data.get("dose_frac_niosh") or 0) * 100.0,
                 float(data.get("dose_frac_osha_pel") or 0) * 100.0,
                 float(data.get("dose_frac_osha_hca") or 0) * 100.0,
                 float(data.get("dose_frac_eu_iso") or 0) * 100.0,
                 bool(data.get("overload_flag")), bool(data.get("underrange_flag")),
                 bool(data.get("wearing_state", True)),
                 bool(data.get("valid_flag", True)), bool(data.get("artifact_flag")),
                 0, 0, data.get("kurtosis_total"),
                 data.get("kurtosis_a_weighted"), data.get("kurtosis_c_weighted"),
                 data.get("beta_kurtosis"), data.get("n_samples", 0),
                 data.get("sum_x", 0.0), data.get("sum_x2", 0.0),
                 data.get("sum_x3", 0.0), data.get("sum_x4", 0.0),
                 _json(freq_spl), _json(freq_moments), 0, "dB SPL"))
            report["time_history"] += 1

        if _table_exists(conn, "event_log"):
            for row in conn.execute("SELECT * FROM event_log"):
                data = {key: row[key] for key in row.keys()}
                conn.execute(
                    "INSERT OR IGNORE INTO events ("
                    "event_id, session_id, channel, category, event_type, severity, "
                    "start_time_utc, end_time_utc, duration_s, trigger_flags_json, "
                    "lzpeak_db, lcpeak_db, audio_path, retention_state, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(data.get("event_id") or f"legacy-{data.get('id')}"),
                     data.get("session_id"), "CH1", "acoustic",
                     1, 20, _utc(data.get("start_time_utc")),
                     _utc(data.get("end_time_utc")), data.get("duration_s"),
                     _json([str(data.get("trigger_type") or "legacy")]),
                     data.get("LZpeak_dB"), data.get("LCpeak_dB"),
                     data.get("audio_file_path"), "retained",
                     datetime.now(timezone.utc).isoformat()))
                report["events"] += 1
        conn.commit()
    finally:
        conn.close()
        database.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("Database/noise_info.db"))
    parser.add_argument("--backup", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(args.db, backup=args.backup,
                             dry_run=args.dry_run),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
