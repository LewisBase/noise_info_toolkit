# -*- coding: utf-8 -*-
"""Repository helpers for the field-deployment storage schema."""
from __future__ import annotations

import csv
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy import func, select

from app.domain.metrics import Metrics
from app.services.event_audio import EventClip
from app.services.retention import AuditEntry, SourceJob
from .database import Database
from .models import (
    AppConfigRow, CalibrationRow, EventReviewAuditRow, EventRow,
    FileResultRow, JobRow, RetentionAuditRow, SessionRow, SystemEventRow,
    TimeHistoryRow,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


class Repository:
    def __init__(self, database: Database):
        self.db = database

    # ---------------- runtime configuration ----------------
    def get_app_config(self, key: str) -> dict | None:
        with self.db.session_scope() as db:
            row = db.get(AppConfigRow, key)
            if row is None:
                return None
            try:
                value = json.loads(row.value_json)
            except (TypeError, ValueError):
                return None
            return value if isinstance(value, dict) else None

    def set_app_config(self, key: str, value: dict) -> None:
        now = datetime.now(timezone.utc)
        payload = json.dumps(value, ensure_ascii=False)
        with self.db.session_scope() as db:
            row = db.get(AppConfigRow, key)
            if row is None:
                row = AppConfigRow(key=key, value_json=payload, updated_at=now)
                db.add(row)
            else:
                row.value_json = payload
                row.updated_at = now

    # ---------------- calibrations ----------------
    def add_calibration(self, calibration, name: str,
                        certificate: str | None = None) -> int:
        now = datetime.now(timezone.utc)
        with self.db.session_scope() as db:
            row = db.execute(
                select(CalibrationRow).where(CalibrationRow.name == name)
            ).scalars().first()
            if row is None:
                row = CalibrationRow(name=name, created_at=now)
                db.add(row)
            row.unit = calibration.unit
            row.pa_per_unit = calibration.pa_per_unit
            row.offset_pa = calibration.offset_pa
            row.offset_db = calibration.offset_db
            row.calibrated = calibration.calibrated
            row.certificate = certificate
            db.flush()
            return int(row.id)

    def current_calibration(self) -> dict | None:
        with self.db.session_scope() as db:
            row = db.execute(
                select(CalibrationRow).order_by(
                    CalibrationRow.created_at.desc()).limit(1)
            ).scalars().first()
            if row is None:
                return None
            return {
                "id": row.id, "name": row.name, "unit": row.unit,
                "pa_per_unit": row.pa_per_unit, "offset_pa": row.offset_pa,
                "offset_db": row.offset_db, "calibrated": row.calibrated,
                "certificate": row.certificate,
                "created_at": row.created_at.isoformat(),
            }

    # ---------------- sessions ----------------
    def create_session(self, channel: str, profile: str = "NIOSH",
                       device_id: str | None = None,
                       operator: str | None = None,
                       organization: str | None = None,
                       calibration_id: int | None = None,
                       session_id: str | None = None) -> str:
        session_id = session_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with self.db.session_scope() as db:
            if db.get(SessionRow, session_id) is None:
                db.add(SessionRow(
                    id=session_id, channel=channel, profile=profile,
                    device_id=device_id, operator=operator,
                    organization=organization, calibration_id=calibration_id,
                    start_time_utc=now, state="running", created_at=now,
                ))
        return session_id

    def get_or_create_session(self, channel: str,
                              profile: str = "NIOSH") -> str:
        with self.db.session_scope() as db:
            row = db.execute(
                select(SessionRow).where(
                    SessionRow.channel == channel,
                    SessionRow.state == "running",
                ).order_by(SessionRow.start_time_utc.desc())
            ).scalars().first()
            if row is not None:
                return row.id
        return self.create_session(channel=channel, profile=profile)

    def close_session(self, session_id: str, total_duration_s: float = 0.0) -> None:
        now = datetime.now(timezone.utc)
        with self.db.session_scope() as db:
            row = db.get(SessionRow, session_id)
            if row is not None:
                row.state = "stopped"
                row.end_time_utc = now
                row.total_duration_s = float(total_duration_s)

    def current_session(self, channel: str | None = None) -> dict | None:
        with self.db.session_scope() as db:
            stmt = select(SessionRow).where(SessionRow.state == "running")
            if channel:
                stmt = stmt.where(SessionRow.channel == channel)
            row = db.execute(
                stmt.order_by(SessionRow.start_time_utc.desc())
            ).scalars().first()
            return self._session_dict(row) if row else None

    def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self.db.session_scope() as db:
            rows = db.execute(
                select(SessionRow).order_by(
                    SessionRow.start_time_utc.desc()).offset(offset).limit(limit)
            ).scalars().all()
            return [self._session_dict(r) for r in rows]

    @staticmethod
    def _session_dict(row: SessionRow) -> dict:
        return {
            "id": row.id,
            "session_id": row.id,
            "channel": row.channel,
            "profile_name": row.profile,
            "profile": row.profile,
            "device_id": row.device_id,
            "operator": row.operator,
            "organization": row.organization,
            "calibration_id": row.calibration_id,
            "start_time": row.start_time_utc.isoformat() if row.start_time_utc else None,
            "end_time": row.end_time_utc.isoformat() if row.end_time_utc else None,
            "state": row.state,
            "total_duration_s": row.total_duration_s,
        }

    # ---------------- jobs ----------------
    def get_or_create_job(self, file_path: str, channel: str,
                          file_size: int, file_mtime_ns: int,
                          session_id: str | None = None) -> dict:
        now = datetime.now(timezone.utc)
        with self.db.session_scope() as db:
            row = db.execute(
                select(JobRow).where(
                    JobRow.file_path == str(file_path),
                    JobRow.channel == channel,
                    JobRow.file_size == int(file_size),
                    JobRow.file_mtime_ns == int(file_mtime_ns),
                )
            ).scalars().first()
            if row is None:
                row = JobRow(
                    id=str(uuid.uuid4()), file_path=str(file_path),
                    channel=channel, file_size=int(file_size),
                    file_mtime_ns=int(file_mtime_ns), session_id=session_id,
                    status="pending", created_at=now,
                )
                db.add(row)
            return self._job_dict(row)

    @staticmethod
    def _job_dict(row: JobRow) -> dict:
        return {
            "id": row.id, "file_path": row.file_path, "channel": row.channel,
            "file_size": row.file_size, "file_mtime_ns": row.file_mtime_ns,
            "session_id": row.session_id, "status": row.status,
            "attempts": row.attempts, "last_error": row.last_error,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "source_retained": row.source_retained,
        }

    def list_jobs(self, status: str | None = None,
                  limit: int = 100) -> list[dict]:
        with self.db.session_scope() as db:
            stmt = select(JobRow)
            if status:
                stmt = stmt.where(JobRow.status == status)
            rows = db.execute(
                stmt.order_by(JobRow.created_at.desc()).limit(limit)
            ).scalars().all()
            return [self._job_dict(row) for row in rows]

    def mark_job(self, job_id: str, status: str, error: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        with self.db.session_scope() as db:
            row = db.get(JobRow, job_id)
            if row is None:
                return
            row.status = status
            row.last_error = error
            if status == "running":
                row.started_at = now
                row.attempts = int(row.attempts or 0) + 1
            if status in ("done", "failed", "quarantined"):
                row.finished_at = now
            if status == "failed":
                row.attempts = int(row.attempts or 0)

    def task_jobs_for_retention(self) -> list[SourceJob]:
        with self.db.session_scope() as db:
            rows = db.execute(
                select(JobRow).where(JobRow.status == "done")
            ).scalars().all()
            result: list[SourceJob] = []
            for row in rows:
                count = db.execute(
                    select(func.count(EventRow.id)).where(
                        EventRow.session_id == row.session_id,
                        EventRow.channel == row.channel,
                    )
                ).scalar_one()
                verified = True
                if count:
                    bad = db.execute(
                        select(func.count(EventRow.id)).where(
                            EventRow.session_id == row.session_id,
                            EventRow.channel == row.channel,
                            (EventRow.audio_sha256.is_(None))
                            | (EventRow.audio_sha256 == ""),
                        )
                    ).scalar_one()
                    verified = int(bad) == 0
                active = db.execute(
                    select(func.count(EventRow.id)).where(
                        EventRow.session_id == row.session_id,
                        EventRow.channel == row.channel,
                        EventRow.retention_state == "active",
                    )
                ).scalar_one()
                result.append(SourceJob(
                    id=row.id, file_path=Path(row.file_path),
                    file_size=row.file_size, file_mtime_ns=row.file_mtime_ns,
                    finished_at=row.finished_at or row.created_at,
                    status=row.status, has_events=bool(count),
                    event_audio_verified=verified, active_event=bool(active),
                ))
            return result

    def mark_source_deleted(self, job_id: str) -> None:
        with self.db.session_scope() as db:
            row = db.get(JobRow, job_id)
            if row is not None:
                row.source_retained = False
                row.source_deleted_at = datetime.now(timezone.utc)

    # ---------------- export ----------------
    def export_results_csv(self, export_dir: Path,
                           limit: int = 200000) -> dict[str, str]:
        """Write all metric/event rows to timestamped UTF-8-BOM CSVs.

        This is the field hand-off format; JSON columns are serialized so the
        table remains one row per 10 s window.
        """
        export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        paths: dict[str, str] = {}
        with self.db.session_scope() as db:
            rows = db.execute(
                select(TimeHistoryRow).order_by(
                    TimeHistoryRow.timestamp_utc.asc()).limit(limit)
            ).scalars().all()
            metrics = [self._metric_dict(row) for row in rows]
            event_rows = db.execute(
                select(EventRow).order_by(EventRow.start_time_utc.asc())
            ).scalars().all()
            events = [self._event_dict(row) for row in event_rows]
            file_rows = db.execute(
                select(FileResultRow).order_by(FileResultRow.created_at.asc())
            ).scalars().all()
            files = [self._file_result_dict(row) for row in file_rows]
        if metrics:
            path = export_dir / f"results_{stamp}.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                fieldnames = list(metrics[0].keys())
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in metrics:
                    clean = dict(row)
                    for key in ("freq_spl", "freq_moments"):
                        clean[key] = json.dumps(clean.get(key), ensure_ascii=False)
                    writer.writerow(clean)
            paths["metrics"] = str(path)
        if files:
            path = export_dir / f"file_results_{stamp}.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                fieldnames = list(files[0].keys())
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(files)
            paths["file_results"] = str(path)
        if events:
            path = export_dir / f"events_{stamp}.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                fieldnames = list(events[0].keys())
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in events:
                    clean = dict(row)
                    for key in ("trigger_flags",):
                        clean[key] = json.dumps(clean.get(key), ensure_ascii=False)
                    writer.writerow(clean)
            paths["events"] = str(path)
        return paths

    # ---------------- file results ----------------
    def get_or_create_file_result(self, file_path: str, channel: str,
                                  file_size: int, file_mtime_ns: int,
                                  job_id: str | None = None,
                                  session_id: str | None = None) -> int:
        now = datetime.now(timezone.utc)
        path = Path(file_path)
        with self.db.session_scope() as db:
            row = db.execute(
                select(FileResultRow).where(
                    FileResultRow.file_path == str(path),
                    FileResultRow.channel == channel,
                    FileResultRow.file_size == int(file_size),
                    FileResultRow.file_mtime_ns == int(file_mtime_ns),
                )
            ).scalars().first()
            if row is None:
                row = FileResultRow(
                    file_path=str(path), file_name=path.name,
                    file_size=int(file_size), file_mtime_ns=int(file_mtime_ns),
                    channel=channel, job_id=job_id, session_id=session_id,
                    status="pending", created_at=now, updated_at=now,
                )
                db.add(row)
            else:
                row.job_id = job_id or row.job_id
                row.session_id = session_id or row.session_id
                row.updated_at = now
            db.flush()
            return int(row.id)

    def finalize_file_result(self, file_result_id: int, metrics, status: str = "done",
                             error: str | None = None, event_count: int = 0,
                             sample_rate: int | None = None) -> None:
        now = datetime.now(timezone.utc)
        with self.db.session_scope() as db:
            row = db.get(FileResultRow, file_result_id)
            if row is None:
                return
            row.status = status
            row.error = error
            row.updated_at = now
            if metrics is not None:
                row.start_time_utc = metrics.timestamp_utc
                row.end_time_utc = (metrics.timestamp_utc
                                    + timedelta(
                                        seconds=float(metrics.duration_s)))
                row.duration_s = float(metrics.duration_s)
                row.laeq = metrics.laeq
                row.lceq = metrics.lceq
                row.lzeq = metrics.lzeq
                row.laf = metrics.laf
                row.las = metrics.las
                row.lcf = metrics.lcf
                row.lcs = metrics.lcs
                row.lafmax = metrics.lafmax
                row.lasmax = metrics.lasmax
                row.lcsmax = metrics.lcsmax
                row.lzpeak = metrics.lzpeak
                row.lcpeak = metrics.lcpeak
                row.lapeak = metrics.lapeak
                row.dose_niosh = metrics.dose_frac_niosh * 100.0
                row.dose_osha_pel = metrics.dose_frac_osha_pel * 100.0
                row.dose_osha_hca = metrics.dose_frac_osha_hca * 100.0
                row.dose_eu_iso = metrics.dose_frac_eu_iso * 100.0
                row.calibrated = metrics.calibrated
                row.level_unit = metrics.level_unit
            if sample_rate:
                row.sample_rate = int(sample_rate)
            row.event_count = int(event_count)

    def update_file_result_counts(self, file_result_id: int,
                                  overload_count: int,
                                  invalid_ratio: float) -> None:
        with self.db.session_scope() as db:
            row = db.get(FileResultRow, file_result_id)
            if row is not None:
                row.overload_count = int(overload_count)
                row.invalid_ratio = float(invalid_ratio)
                row.updated_at = datetime.now(timezone.utc)

    def list_file_results(self, channel: str | None = None,
                          status: str | None = None,
                          limit: int = 100, offset: int = 0) -> list[dict]:
        with self.db.session_scope() as db:
            stmt = select(FileResultRow)
            if channel:
                stmt = stmt.where(FileResultRow.channel == channel)
            if status:
                stmt = stmt.where(FileResultRow.status == status)
            rows = db.execute(
                stmt.order_by(FileResultRow.created_at.desc())
                .offset(offset).limit(limit)
            ).scalars().all()
            return [self._file_result_dict(row) for row in rows]

    def count_file_results(self, channel: str | None = None,
                           status: str | None = None) -> int:
        with self.db.session_scope() as db:
            stmt = select(func.count(FileResultRow.id))
            if channel:
                stmt = stmt.where(FileResultRow.channel == channel)
            if status:
                stmt = stmt.where(FileResultRow.status == status)
            return int(db.execute(stmt).scalar_one())

    def get_file_result(self, file_result_id: int) -> dict | None:
        with self.db.session_scope() as db:
            row = db.get(FileResultRow, file_result_id)
            return self._file_result_dict(row) if row else None

    def file_result_metrics(self, file_result_id: int,
                            limit: int = 5000) -> list[dict]:
        with self.db.session_scope() as db:
            rows = db.execute(
                select(TimeHistoryRow).where(
                    TimeHistoryRow.file_result_id == file_result_id)
                .order_by(TimeHistoryRow.timestamp_utc.asc()).limit(limit)
            ).scalars().all()
            return [self._metric_dict(row) for row in rows]

    def file_result_events(self, file_result_id: int) -> list[dict]:
        with self.db.session_scope() as db:
            rows = db.execute(
                select(EventRow).where(
                    EventRow.file_result_id == file_result_id)
                .order_by(EventRow.start_time_utc.asc())
            ).scalars().all()
            return [self._event_dict(row) for row in rows]

    @staticmethod
    def _file_result_dict(row: FileResultRow) -> dict:
        return {
            "id": row.id, "file_path": row.file_path,
            "file_name": row.file_name, "file_size": row.file_size,
            "file_mtime_ns": row.file_mtime_ns, "sha256": row.sha256,
            "channel": row.channel, "device_id": row.device_id,
            "job_id": row.job_id, "session_id": row.session_id,
            "start_time_utc": (row.start_time_utc.isoformat()
                               if row.start_time_utc else None),
            "end_time_utc": (row.end_time_utc.isoformat()
                             if row.end_time_utc else None),
            "duration_s": row.duration_s, "sample_rate": row.sample_rate,
            "calibrated": row.calibrated, "level_unit": row.level_unit,
            "laeq": row.laeq, "lceq": row.lceq, "lzeq": row.lzeq,
            "laf": row.laf, "las": row.las, "lcf": row.lcf, "lcs": row.lcs,
            "lafmax": row.lafmax, "lasmax": row.lasmax, "lcsmax": row.lcsmax,
            "lzpeak": row.lzpeak, "lcpeak": row.lcpeak, "lapeak": row.lapeak,
            "dose_niosh": row.dose_niosh, "dose_osha_pel": row.dose_osha_pel,
            "dose_osha_hca": row.dose_osha_hca, "dose_eu_iso": row.dose_eu_iso,
            "event_count": row.event_count, "overload_count": row.overload_count,
            "invalid_ratio": row.invalid_ratio, "status": row.status,
            "error": row.error, "processor_version": row.processor_version,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

    # ---------------- time history ----------------
    def insert_time_history(self, session_id: str, metrics: Metrics,
                            file_result_id: int | None = None) -> int:
        row = TimeHistoryRow(
            session_id=session_id,
            file_result_id=file_result_id,
            channel=metrics.channel,
            timestamp_utc=metrics.timestamp_utc,
            recorded_at=datetime.now(timezone.utc),
            duration_s=metrics.duration_s,
            laeq=metrics.laeq, lceq=metrics.lceq, lzeq=metrics.lzeq,
            laf=metrics.laf, las=metrics.las, lcf=metrics.lcf, lcs=metrics.lcs,
            lafmax=metrics.lafmax, lasmax=metrics.lasmax, lcsmax=metrics.lcsmax,
            lzpeak=metrics.lzpeak, lcpeak=metrics.lcpeak, lapeak=metrics.lapeak,
            dose_niosh=metrics.dose_frac_niosh * 100.0,
            dose_osha_pel=metrics.dose_frac_osha_pel * 100.0,
            dose_osha_hca=metrics.dose_frac_osha_hca * 100.0,
            dose_eu_iso=metrics.dose_frac_eu_iso * 100.0,
            overload=metrics.overload, underrange=metrics.underrange,
            wearing=metrics.wearing, valid=metrics.valid,
            artifact=metrics.artifact, event_type=metrics.event_type,
            event_severity=metrics.event_severity,
            kurtosis_total=metrics.kurtosis_total,
            kurtosis_a=metrics.kurtosis_a, kurtosis_c=metrics.kurtosis_c,
            beta_kurtosis=metrics.beta_kurtosis,
            n_samples=metrics.n_samples, s1=metrics.s1, s2=metrics.s2,
            s3=metrics.s3, s4=metrics.s4,
            freq_spl_json=_json({
                name: value for name, value in zip(
                    ("63Hz", "125Hz", "250Hz", "500Hz", "1kHz",
                     "2kHz", "4kHz", "8kHz", "16kHz"), metrics.freq_spl)
            }),
            freq_moments_json=_json({
                name: moments.as_list() for name, moments in zip(
                    ("63Hz", "125Hz", "250Hz", "500Hz", "1kHz",
                     "2kHz", "4kHz", "8kHz", "16kHz"), metrics.freq_moments)
            }),
            calibrated=metrics.calibrated, level_unit=metrics.level_unit,
        )
        with self.db.session_scope() as db:
            db.add(row)
            db.flush()
            return int(row.id)

    def list_channels(self) -> list[str]:
        with self.db.session_scope() as db:
            rows = db.execute(
                select(TimeHistoryRow.channel).distinct()
            ).scalars().all()
            return sorted(str(r) for r in rows if r)

    def latest_time_history(self, channel: str,
                            recorded_since: datetime | None = None,
                            session_id: str | None = None) -> dict | None:
        with self.db.session_scope() as db:
            stmt = select(TimeHistoryRow).where(
                TimeHistoryRow.channel == channel)
            if recorded_since is not None:
                stmt = stmt.where(
                    TimeHistoryRow.recorded_at >= recorded_since)
            if session_id is not None:
                stmt = stmt.where(TimeHistoryRow.session_id == session_id)
            row = db.execute(
                stmt.order_by(TimeHistoryRow.timestamp_utc.desc()).limit(1)
            ).scalars().first()
            return self._metric_dict(row) if row else None

    def list_time_history(self, channel: str,
                          start: datetime | None = None,
                          end: datetime | None = None,
                          limit: int = 1000, offset: int = 0,
                          session_id: str | None = None) -> list[dict]:
        with self.db.session_scope() as db:
            stmt = select(TimeHistoryRow).where(TimeHistoryRow.channel == channel)
            if session_id is not None:
                stmt = stmt.where(TimeHistoryRow.session_id == session_id)
            if start is not None:
                stmt = stmt.where(TimeHistoryRow.timestamp_utc >= start)
            if end is not None:
                stmt = stmt.where(TimeHistoryRow.timestamp_utc <= end)
            rows = db.execute(
                stmt.order_by(TimeHistoryRow.timestamp_utc.asc())
                .offset(offset).limit(limit)
            ).scalars().all()
            return [self._metric_dict(r) for r in rows]

    def count_time_history(self, channel: str,
                           start: datetime | None = None,
                           end: datetime | None = None,
                           session_id: str | None = None) -> int:
        with self.db.session_scope() as db:
            stmt = select(func.count(TimeHistoryRow.id)).where(
                TimeHistoryRow.channel == channel)
            if session_id is not None:
                stmt = stmt.where(TimeHistoryRow.session_id == session_id)
            if start is not None:
                stmt = stmt.where(TimeHistoryRow.timestamp_utc >= start)
            if end is not None:
                stmt = stmt.where(TimeHistoryRow.timestamp_utc <= end)
            return int(db.execute(stmt).scalar_one())

    @staticmethod
    def aggregate_minutes(rows: list[dict]) -> list[dict]:
        """Group 10 s API rows into energy-correct minute rows."""
        groups: dict[str, list[dict]] = {}
        for row in rows:
            try:
                stamp = datetime.fromisoformat(row["timestamp_utc"])
                key = stamp.replace(second=0, microsecond=0).isoformat()
            except (KeyError, TypeError, ValueError):
                continue
            groups.setdefault(key, []).append(row)

        def energy(values, weights):
            power = 0.0
            total = 0.0
            for value, weight in zip(values, weights):
                if value is None or not math.isfinite(float(value)) or weight <= 0:
                    continue
                power += 10 ** (float(value) / 10.0) * float(weight)
                total += float(weight)
            return 10 * math.log10(power / total) if total > 0 and power > 0 else None

        def peak(key):
            vals = [r.get(key) for r in rows_for if r.get(key) is not None]
            return max(vals) if vals else None

        output: list[dict] = []
        for key, rows_for in sorted(groups.items()):
            weights = [float(r.get("duration_s") or 0.0) for r in rows_for]
            first = rows_for[0]
            item = dict(first)
            item["timestamp_utc"] = key
            item["duration_s"] = sum(weights)
            for name in ("laeq", "lceq", "lzeq"):
                item[name] = energy((r.get(name) for r in rows_for), weights)
            for name in ("lafmax", "lasmax", "lcsmax", "lzpeak", "lcpeak",
                         "lapeak"):
                item[name] = peak(name)
            for name in ("laf", "las", "lcf", "lcs"):
                item[name] = rows_for[-1].get(name)
            for name in ("dose_niosh", "dose_osha_pel", "dose_osha_hca",
                         "dose_eu_iso"):
                item[name] = sum(float(r.get(name) or 0.0) for r in rows_for)
            freq: dict[str, list[float]] = {}
            for row in rows_for:
                for name, value in (row.get("freq_spl") or {}).items():
                    if value is not None:
                        freq.setdefault(name, []).append(float(value))
            item["freq_spl"] = {
                name: energy(values, [1.0] * len(values))
                for name, values in freq.items()
            }
            item["n_samples"] = sum(int(r.get("n_samples") or 0) for r in rows_for)
            for name in ("s1", "s2", "s3", "s4"):
                item[name] = sum(float(r.get(name) or 0.0) for r in rows_for)
            item["overload"] = any(bool(r.get("overload")) for r in rows_for)
            item["underrange"] = any(bool(r.get("underrange")) for r in rows_for)
            item["wearing"] = all(bool(r.get("wearing")) for r in rows_for)
            item["valid"] = all(bool(r.get("valid")) for r in rows_for)
            item["artifact"] = any(bool(r.get("artifact")) for r in rows_for)
            item["event_type"] = max(int(r.get("event_type") or 0)
                                     for r in rows_for)
            item["event_severity"] = max(int(r.get("event_severity") or 0)
                                         for r in rows_for)
            item["calibrated"] = all(bool(r.get("calibrated")) for r in rows_for)
            output.append(item)
        return output

    @staticmethod
    def _metric_dict(row: TimeHistoryRow) -> dict:
        return {
            "id": row.id,
            "session_id": row.session_id,
            "file_result_id": row.file_result_id,
            "channel": row.channel,
            "timestamp_utc": row.timestamp_utc.isoformat(),
            "recorded_at": (row.recorded_at.isoformat()
                            if row.recorded_at else None),
            "duration_s": row.duration_s,
            "laeq": row.laeq, "lceq": row.lceq, "lzeq": row.lzeq,
            "laf": row.laf, "las": row.las, "lcf": row.lcf, "lcs": row.lcs,
            "lafmax": row.lafmax, "lasmax": row.lasmax, "lcsmax": row.lcsmax,
            "lzpeak": row.lzpeak, "lcpeak": row.lcpeak, "lapeak": row.lapeak,
            "dose_niosh": row.dose_niosh, "dose_osha_pel": row.dose_osha_pel,
            "dose_osha_hca": row.dose_osha_hca, "dose_eu_iso": row.dose_eu_iso,
            "overload": row.overload, "underrange": row.underrange,
            "wearing": row.wearing, "valid": row.valid, "artifact": row.artifact,
            "event_type": row.event_type, "event_severity": row.event_severity,
            "kurtosis_total": row.kurtosis_total, "kurtosis_a": row.kurtosis_a,
            "kurtosis_c": row.kurtosis_c, "beta_kurtosis": row.beta_kurtosis,
            "n_samples": row.n_samples, "s1": row.s1, "s2": row.s2,
            "s3": row.s3, "s4": row.s4,
            "freq_spl": json.loads(row.freq_spl_json) if row.freq_spl_json else {},
            "freq_moments": json.loads(row.freq_moments_json) if row.freq_moments_json else {},
            "calibrated": row.calibrated, "level_unit": row.level_unit,
        }

    # ---------------- events ----------------
    def insert_event(self, session_id: str, channel: str, clip: EventClip,
                     result=None, file_result_id: int | None = None) -> int:
        payload = clip.to_dict()
        row = EventRow(
            event_id=clip.event_id, session_id=session_id,
            file_result_id=file_result_id, channel=channel,
            category="acoustic", event_type=clip.event_type,
            severity=clip.severity,
            start_time_utc=clip.event_start_utc,
            end_time_utc=clip.event_end_utc,
            duration_s=(clip.event_end_utc - clip.event_start_utc).total_seconds(),
            trigger_flags_json=_json(list(clip.triggers)),
            audio_start_utc=clip.audio_start_utc,
            audio_end_utc=clip.audio_end_utc,
            audio_path=str(clip.path), audio_sha256=clip.sha256,
            audio_bytes=clip.audio_bytes, retention_state="retained",
            metadata_json=_json({
                "pre_s": clip.pre_s, "post_s": clip.post_s,
                "calibrated": clip.calibrated, "level_unit": clip.level_unit,
                "sample_rate": clip.sample_rate, "payload": payload,
            }),
            created_at=datetime.now(timezone.utc),
        )
        if result is not None:
            row.laf_db = getattr(result, "laf_db", None)
            row.las_db = getattr(result, "las_db", None)
            row.impulse_db = getattr(result, "impulse_db", None)
            row.rise_db = getattr(result, "rise_db", None)
            row.background_delta_db = getattr(result, "background_delta_db", None)
        with self.db.session_scope() as db:
            db.add(row)
            db.flush()
            return int(row.id)

    def list_events(self, session_id: str | None = None,
                    channel: str | None = None,
                    limit: int = 100, offset: int = 0) -> list[dict]:
        with self.db.session_scope() as db:
            stmt = select(EventRow)
            if session_id:
                stmt = stmt.where(EventRow.session_id == session_id)
            if channel:
                stmt = stmt.where(EventRow.channel == channel)
            rows = db.execute(
                stmt.order_by(EventRow.start_time_utc.desc())
                .offset(offset).limit(limit)
            ).scalars().all()
            return [self._event_dict(r) for r in rows]

    @staticmethod
    def _event_dict(row: EventRow) -> dict:
        return {
            "id": row.id, "event_id": row.event_id,
            "session_id": row.session_id,
            "file_result_id": row.file_result_id, "channel": row.channel,
            "category": row.category, "event_type": row.event_type,
            "severity": row.severity,
            "start_time_utc": row.start_time_utc.isoformat(),
            "end_time_utc": row.end_time_utc.isoformat() if row.end_time_utc else None,
            "duration_s": row.duration_s,
            "trigger_flags": json.loads(row.trigger_flags_json) if row.trigger_flags_json else [],
            "laf_db": row.laf_db, "las_db": row.las_db,
            "impulse_db": row.impulse_db, "rise_db": row.rise_db,
            "background_delta_db": row.background_delta_db,
            "audio_path": row.audio_path, "audio_sha256": row.audio_sha256,
            "audio_bytes": row.audio_bytes,
            "retention_state": row.retention_state,
            "review_state": getattr(row, "review_state", "unreviewed"),
            "reviewed_by": getattr(row, "reviewed_by", None),
            "reviewed_at": (row.reviewed_at.isoformat()
                            if getattr(row, "reviewed_at", None) else None),
            "review_note": getattr(row, "review_note", None),
        }

    def review_event(self, event_id: str, state: str, reviewer: str | None,
                     note: str | None = None) -> dict | None:
        if state not in ("unreviewed", "confirmed", "false_positive"):
            raise ValueError("invalid review state")
        now = datetime.now(timezone.utc)
        with self.db.session_scope() as db:
            row = db.execute(
                select(EventRow).where(EventRow.event_id == event_id)
            ).scalars().first()
            if row is None:
                return None
            row.review_state = state
            row.reviewed_by = reviewer
            row.reviewed_at = now
            row.review_note = note
            db.add(EventReviewAuditRow(
                event_id=event_id, state=state, reviewer=reviewer,
                note=note, created_at=now))
            db.flush()
            return self._event_dict(row)

    def event_count(self, session_id: str, channel: str | None = None) -> int:
        with self.db.session_scope() as db:
            stmt = select(func.count(EventRow.id)).where(
                EventRow.session_id == session_id)
            if channel:
                stmt = stmt.where(EventRow.channel == channel)
            return int(db.execute(stmt).scalar_one())

    def has_verified_event_audio(self, session_id: str,
                                 channel: str | None = None) -> bool:
        with self.db.session_scope() as db:
            stmt = select(EventRow).where(
                EventRow.session_id == session_id,
                EventRow.audio_sha256.is_not(None),
                EventRow.audio_sha256 != "",
            )
            if channel:
                stmt = stmt.where(EventRow.channel == channel)
            return db.execute(stmt.limit(1)).scalars().first() is not None

    # ---------------- system anomalies / retention ----------------
    def insert_system_event(self, event) -> int:
        row = SystemEventRow(
            code=event.code, severity=event.severity, message=event.message,
            context_json=_json(event.context), start_utc=event.start_utc,
            created_at=event.start_utc,
        )
        with self.db.session_scope() as db:
            db.add(row)
            db.flush()
            return int(row.id)

    def list_system_events(self, limit: int = 100) -> list[dict]:
        with self.db.session_scope() as db:
            rows = db.execute(
                select(SystemEventRow).order_by(
                    SystemEventRow.start_utc.desc()).limit(limit)
            ).scalars().all()
            return [{
                "id": r.id, "code": r.code, "severity": r.severity,
                "message": r.message,
                "context": json.loads(r.context_json) if r.context_json else {},
                "start_utc": r.start_utc.isoformat(),
                "resolved": r.resolved,
            } for r in rows]

    def add_retention_audit(self, entry: AuditEntry) -> int:
        row = RetentionAuditRow(
            target_path=entry.target_path, action=entry.action,
            reason=entry.reason, mode=entry.mode, dry_run=entry.dry_run,
            bytes=entry.bytes, created_at=entry.created_at,
        )
        with self.db.session_scope() as db:
            db.add(row)
            db.flush()
            return int(row.id)

    def retention_audit(self, limit: int = 100) -> list[dict]:
        with self.db.session_scope() as db:
            rows = db.execute(
                select(RetentionAuditRow).order_by(
                    RetentionAuditRow.created_at.desc()).limit(limit)
            ).scalars().all()
            return [{
                "target_path": r.target_path, "action": r.action,
                "reason": r.reason, "mode": r.mode, "dry_run": r.dry_run,
                "bytes": r.bytes, "created_at": r.created_at.isoformat(),
            } for r in rows]
