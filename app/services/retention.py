# -*- coding: utf-8 -*-
"""Source-audio retention policy.

Debug is the default and never deletes anything.  Production deletion is
guarded by dry-run, grace period, verified event audio, file identity checks
and an audit trail.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional


@dataclass(frozen=True)
class SourceJob:
    id: str
    file_path: Path
    file_size: int
    file_mtime_ns: int
    finished_at: datetime
    status: str = "done"
    has_events: bool = False
    event_audio_verified: bool = True
    active_event: bool = False


@dataclass(frozen=True)
class RetentionPolicy:
    mode: str = "debug"                 # debug | production
    delete_source_after_days: float = 7.0
    event_retention_days: float = 365.0
    dry_run: bool = True
    trash_dir: Path = Path("trash")

    def __post_init__(self) -> None:
        if self.mode not in ("debug", "production"):
            raise ValueError("mode must be debug or production")
        if self.delete_source_after_days < 0:
            raise ValueError("delete_source_after_days must be >= 0")


@dataclass(frozen=True)
class AuditEntry:
    target_path: str
    action: str
    reason: str
    mode: str
    dry_run: bool
    bytes: int
    created_at: datetime


@dataclass
class RetentionReport:
    mode: str
    dry_run: bool
    candidates: int = 0
    deleted: int = 0
    skipped: int = 0
    audit: list[AuditEntry] = field(default_factory=list)


def source_eligible(job: SourceJob, now: datetime,
                    policy: RetentionPolicy) -> tuple[bool, str]:
    """File/DB-only eligibility, independent of debug/production mode."""
    if job.status != "done":
        return False, "job_not_done"
    if job.has_events and not job.event_audio_verified:
        return False, "event_audio_missing_or_bad_sha"
    if job.active_event:
        return False, "active_event"
    if not job.file_path.is_file():
        return False, "file_missing"
    stat = job.file_path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (job.file_size, job.file_mtime_ns):
        return False, "file_changed"
    age = now - job.finished_at
    if age < timedelta(days=policy.delete_source_after_days):
        return False, "grace_period"
    return True, "eligible"


def can_delete_source(job: SourceJob, now: datetime,
                      policy: RetentionPolicy) -> tuple[bool, str]:
    """Deletion permission for the current mode."""
    if policy.mode != "production":
        return False, "debug_mode"
    return source_eligible(job, now, policy)


class RetentionService:
    def __init__(self, policy: RetentionPolicy,
                 audit_sink: Optional[Callable[[AuditEntry], None]] = None):
        self.policy = policy
        self.audit_sink = audit_sink
        self.audit: list[AuditEntry] = []

    def _record(self, target: Path, action: str, reason: str,
                dry_run: bool, bytes_: int) -> None:
        entry = AuditEntry(
            target_path=str(target), action=action, reason=reason,
            mode=self.policy.mode, dry_run=dry_run, bytes=bytes_,
            created_at=datetime.now(timezone.utc),
        )
        self.audit.append(entry)
        if self.audit_sink is not None:
            self.audit_sink(entry)

    def run(self, jobs: Iterable[SourceJob],
            now: datetime | None = None,
            dry_run: bool | None = None) -> RetentionReport:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        # Debug is a hard no-delete mode, regardless of a dry_run=False caller.
        if self.policy.mode == "debug":
            report = RetentionReport(mode="debug", dry_run=True)
            for job in jobs:
                eligible, reason = source_eligible(job, now, self.policy)
                if eligible:
                    report.candidates += 1
                    self._record(job.file_path, "preview", reason,
                                 True, job.file_size)
            return report

        dry = self.policy.dry_run if dry_run is None else bool(dry_run)
        report = RetentionReport(mode="production", dry_run=dry)
        for job in jobs:
            eligible, reason = can_delete_source(job, now, self.policy)
            if not eligible:
                report.skipped += 1
                self._record(job.file_path, "skip", reason,
                             dry, job.file_size)
                continue
            report.candidates += 1
            if dry:
                self._record(job.file_path, "preview", reason,
                             True, job.file_size)
                continue
            try:
                self._move_to_trash(job.file_path)
            except OSError as exc:
                report.skipped += 1
                self._record(job.file_path, "skip", f"move_failed:{exc}",
                             False, job.file_size)
                continue
            report.deleted += 1
            self._record(job.file_path, "trash", reason,
                         False, job.file_size)
        return report

    def _move_to_trash(self, source: Path) -> Path:
        """Move, never delete, source audio.  Physical deletion is later."""
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        target_dir = self.policy.trash_dir / day
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        if target.exists():
            target = target_dir / f"{source.stem}_{source.stat().st_mtime_ns}{source.suffix}"
        shutil.move(str(source), str(target))
        return target
