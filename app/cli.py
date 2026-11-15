# -*- coding: utf-8 -*-
"""Command-line entry points for field development and dry runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.services.retention import RetentionPolicy, RetentionService
from app.services.streaming_pipeline import PipelineConfig, process_tdms_file
from app.storage import Database, Repository


def cmd_process(args: argparse.Namespace) -> int:
    settings = Settings()
    path = Path(args.path)
    if not path.is_file():
        print(f"not a file: {path}")
        return 2
    db = Database(args.db or settings.db_path)
    repo = Repository(db)
    session_id = args.session_id or repo.create_session(
        args.channel, profile=args.profile)
    config = PipelineConfig(
        read_window_s=args.window_s,
        analysis_step_s=args.step_s,
        persist_window_s=args.persist_s,
        event_pre_s=settings.event_pre_s,
        event_post_s=settings.event_post_s,
        event_max_s=settings.event_max_s,
        event_min_gap_s=settings.event_min_gap_s,
        event_dir=Path(args.event_dir or settings.event_dir),
    )
    rows = []
    events = []
    result = process_tdms_file(
        path, config, channel=args.channel,
        on_window=lambda row: (repo.insert_time_history(session_id, row),
                               rows.append(row)),
        on_event=lambda clip: (repo.insert_event(session_id, args.channel, clip),
                               events.append(clip)),
    )
    print(json.dumps({
        "file": str(path),
        "session_id": session_id,
        "windows": len(result.metrics),
        "events": len(result.events),
        "summary_laeq": result.summary.laeq if result.summary else None,
    }, ensure_ascii=False, indent=2))
    db.close()
    return 0


def cmd_retention(args: argparse.Namespace) -> int:
    settings = Settings()
    db = Database(settings.db_path)
    repo = Repository(db)
    policy = RetentionPolicy(
        mode=settings.retention_mode,
        delete_source_after_days=settings.delete_source_after_days,
        event_retention_days=settings.event_retention_days,
        dry_run=settings.retention_dry_run,
        trash_dir=settings.trash_dir,
    )
    service = RetentionService(policy, audit_sink=repo.add_retention_audit)
    report = service.run(repo.task_jobs_for_retention(),
                         dry_run=not args.apply)
    for job_id in report.deleted_jobs:
        repo.mark_source_deleted(job_id)
    print(json.dumps({
        "mode": report.mode, "dry_run": report.dry_run,
        "candidates": report.candidates, "deleted": report.deleted,
        "skipped": report.skipped,
    }, ensure_ascii=False, indent=2))
    db.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    settings = Settings()
    uvicorn.run("app.api.app:app", host=args.host or settings.host,
                port=args.port or settings.port, reload=False,
                workers=1)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Noise Info Toolkit field CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("process", help="process one TDMS channel into SQLite")
    p.add_argument("path")
    p.add_argument("--channel", default="CH1")
    p.add_argument("--profile", default="NIOSH")
    p.add_argument("--db", default=None)
    p.add_argument("--event-dir", default=None)
    p.add_argument("--session-id", default=None)
    p.add_argument("--window-s", type=float, default=10.0)
    p.add_argument("--step-s", type=float, default=1.0)
    p.add_argument("--persist-s", type=float, default=10.0)
    p.set_defaults(func=cmd_process)

    r = sub.add_parser("retention", help="preview/run source-audio retention")
    r.add_argument("--apply", action="store_true",
                   help="actually move eligible files (production only)")
    r.set_defaults(func=cmd_retention)

    s = sub.add_parser("serve", help="run API v1 with uvicorn")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    s.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
