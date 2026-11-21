# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.retention import RetentionPolicy, RetentionService
from app.storage import Database, Repository
from app.storage.models import JobRow


def _eligible_job(tmp_path: Path):
    db = Database(tmp_path / "noise.db")
    repo = Repository(db)
    source = tmp_path / "CH1.tdms"
    source.write_bytes(b"0123456789")
    stat = source.stat()
    job = repo.get_or_create_job(
        file_path=str(source), channel="CH1",
        file_size=stat.st_size, file_mtime_ns=stat.st_mtime_ns)
    repo.mark_job(job["id"], "done")
    with db.session_scope() as session:
        row = session.get(JobRow, job["id"])
        row.finished_at = datetime.now(timezone.utc) - timedelta(days=10)
    return db, repo, source


def test_retention_uses_repo_jobs(tmp_path: Path) -> None:
    db, repo, source = _eligible_job(tmp_path)
    jobs = repo.task_jobs_for_retention()
    assert len(jobs) == 1
    policy = RetentionPolicy(mode="production", dry_run=True,
                             trash_dir=tmp_path / "trash")
    report = RetentionService(policy).run(jobs)
    assert report.dry_run is True
    assert source.is_file()
    assert report.candidates == 1

    policy = RetentionPolicy(mode="production", dry_run=False,
                             trash_dir=tmp_path / "trash")
    report = RetentionService(policy).run(jobs)
    assert report.deleted == 1
    for job_id in report.deleted_jobs:
        repo.mark_source_deleted(job_id)
    assert not source.exists()
    db.close()
