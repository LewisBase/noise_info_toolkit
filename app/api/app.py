# -*- coding: utf-8 -*-
"""Versioned FastAPI surface over the new storage/DSP stack."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import Settings
from app.domain.calibration import Calibration
from app.services.processing_service import ProcessingService
from app.services.retention import RetentionPolicy, RetentionService
from app.storage import Database, Repository


class CalibrationCreate(BaseModel):
    name: str
    unit: str = "Pa"
    pa_per_unit: float = 1.0
    offset_pa: float = 0.0
    offset_db: float = 0.0
    calibrated: bool = True
    certificate: Optional[str] = None


class MonitorStart(BaseModel):
    watch_directory: str
    channel: Optional[str] = None


class SessionCreate(BaseModel):
    channel: str = "CH1"
    profile: str = "NIOSH"
    device_id: Optional[str] = None
    operator: Optional[str] = None
    organization: Optional[str] = None
    calibration_id: Optional[int] = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings.db_path)
    repo = Repository(db)
    service = ProcessingService(settings, db)

    def require_key(x_api_key: str | None = Header(default=None)) -> None:
        if settings.api_key and x_api_key != settings.api_key:
            raise HTTPException(status_code=401, detail="invalid API key")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        app.state.service.start()
        try:
            yield
        finally:
            app.state.service.stop(timeout=30)
            db.close()

    app = FastAPI(title="Noise Info Toolkit API", version="1.1.0",
                  lifespan=lifespan)
    app.state.repo = repo
    app.state.settings = settings
    app.state.service = service

    def get_repo() -> Repository:
        return repo

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        try:
            channels = repo.list_channels()
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=503,
                                detail=f"database not ready: {exc}") from exc
        calibration = repo.current_calibration()
        return {
            "status": "ready",
            "database": str(settings.db_path),
            "watch_dir": str(settings.watch_dir),
            "watch_dir_exists": settings.watch_dir.is_dir(),
            "channels": channels,
            "retention_mode": settings.retention_mode,
            "processing": app.state.service.status(),
            "calibrated": bool(calibration and calibration["calibrated"]),
            "directory_guard": (
                "restricted" if settings.allowed_watch_roots else "unrestricted"),
            "allowed_watch_roots": [str(p) for p in settings.allowed_watch_roots],
        }

    @app.get("/api/v1/monitor/config")
    def monitor_config(_: None = Depends(require_key)):
        return {
            "watch_directory": str(settings.watch_dir),
            "retention_mode": settings.retention_mode,
            "processing": app.state.service.status(),
        }

    @app.post("/api/v1/monitor/start")
    def monitor_start(payload: MonitorStart,
                      _: None = Depends(require_key)):
        directory = Path(payload.watch_directory).expanduser().resolve()
        if not settings.is_allowed_directory(directory):
            raise HTTPException(status_code=403,
                                detail="directory is outside allowed watch roots")
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(status_code=400,
                                detail=f"cannot create directory: {exc}") from exc
        if not directory.is_dir():
            raise HTTPException(status_code=400, detail="not a directory")
        app.state.service.stop(timeout=30)
        settings.watch_dir = directory
        replacement = ProcessingService(settings, db)
        replacement.start()
        app.state.service = replacement
        return {
            "status": "started",
            "watch_directory": str(directory),
            "processing": replacement.status(),
        }

    @app.post("/api/v1/monitor/stop")
    def monitor_stop(_: None = Depends(require_key)):
        app.state.service.stop(timeout=30)
        return {"status": "stopped", "processing": app.state.service.status()}

    @app.get("/api/v1/fs/dirs")
    def list_directories(path: Optional[str] = None,
                         _: None = Depends(require_key)):
        target = Path(path).expanduser().resolve() if path else settings.watch_dir
        if not settings.is_allowed_directory(target):
            raise HTTPException(status_code=403,
                                detail="directory is outside allowed watch roots")
        if not target.is_dir():
            raise HTTPException(status_code=404, detail="directory not found")
        try:
            dirs = sorted(
                (item for item in target.iterdir()
                 if item.is_dir() and not item.name.startswith(".")),
                key=lambda p: p.name.lower())[:500]
        except OSError as exc:
            raise HTTPException(status_code=403,
                                detail=f"cannot list directory: {exc}") from exc
        return {
            "path": str(target),
            "parent": str(target.parent) if target.parent != target else None,
            "dirs": [{"name": item.name, "path": str(item)} for item in dirs],
        }

    @app.get("/api/v1/channels")
    def channels(_: None = Depends(require_key)):
        items = repo.list_channels()
        if not items:
            items = ["CH1"]
        return {"items": items}

    @app.get("/api/v1/metrics/latest")
    def latest(channel: str = "CH1", _: None = Depends(require_key)):
        row = repo.latest_time_history(channel)
        if row is None:
            raise HTTPException(status_code=404,
                                detail=f"no metrics for channel {channel}")
        return row

    @app.get("/api/v1/metrics/history")
    def history(channel: str = "CH1",
                start: Optional[datetime] = None,
                end: Optional[datetime] = None,
                limit: int = Query(1000, ge=1, le=10000),
                offset: int = Query(0, ge=0),
                _: None = Depends(require_key)):
        for value in (start, end):
            if value is not None and value.tzinfo is None:
                raise HTTPException(status_code=422,
                                    detail="start/end must include timezone")
        items = repo.list_time_history(channel, start=start, end=end,
                                       limit=limit, offset=offset)
        return {"items": items, "count": len(items),
                "limit": limit, "offset": offset}

    @app.get("/api/v1/sessions")
    def sessions(limit: int = Query(50, ge=1, le=500),
                 offset: int = Query(0, ge=0),
                 _: None = Depends(require_key)):
        items = repo.list_sessions(limit=limit, offset=offset)
        return {"items": items, "count": len(items)}

    @app.get("/api/v1/sessions/current")
    def current_session(channel: str | None = None,
                        _: None = Depends(require_key)):
        row = repo.current_session(channel)
        if row is None:
            raise HTTPException(status_code=404, detail="no active session")
        return row

    @app.post("/api/v1/sessions")
    def start_session(payload: SessionCreate, _: None = Depends(require_key)):
        session_id = repo.create_session(
            channel=payload.channel, profile=payload.profile,
            device_id=payload.device_id, operator=payload.operator,
            organization=payload.organization,
            calibration_id=payload.calibration_id,
        )
        return {"session_id": session_id, "state": "running"}

    @app.post("/api/v1/sessions/{session_id}/stop")
    def stop_session(session_id: str, _: None = Depends(require_key)):
        repo.close_session(session_id)
        return {"session_id": session_id, "state": "stopped"}

    @app.get("/api/v1/sessions/{session_id}/metrics")
    def session_metrics(session_id: str, channel: str = "CH1",
                        limit: int = Query(2000, ge=1, le=10000),
                        offset: int = Query(0, ge=0),
                        _: None = Depends(require_key)):
        items = repo.list_time_history(
            channel, limit=limit, offset=offset, session_id=session_id)
        return {"items": items, "count": len(items),
                "limit": limit, "offset": offset}

    @app.get("/api/v1/sessions/{session_id}/events")
    def session_events(session_id: str, channel: str | None = None,
                       limit: int = Query(100, ge=1, le=500),
                       _: None = Depends(require_key)):
        items = repo.list_events(session_id=session_id, channel=channel,
                                 limit=limit)
        return {"items": items, "count": len(items)}

    @app.get("/api/v1/events/{event_id}/audio")
    def event_audio(event_id: str, _: None = Depends(require_key)):
        items = repo.list_events(limit=5000)
        row = next((e for e in items if e["event_id"] == event_id), None)
        if row is None or not row.get("audio_path"):
            raise HTTPException(status_code=404, detail="event audio not found")
        path = Path(row["audio_path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="audio file missing")
        return FileResponse(path, media_type="audio/wav", filename=path.name)

    @app.post("/api/v1/calibrations")
    def add_calibration(payload: CalibrationCreate,
                        _: None = Depends(require_key)):
        calibration = Calibration(
            name=payload.name, unit=payload.unit,
            pa_per_unit=payload.pa_per_unit, offset_pa=payload.offset_pa,
            offset_db=payload.offset_db, calibrated=payload.calibrated)
        calibration_id = repo.add_calibration(
            calibration, payload.name, payload.certificate)
        return {"id": calibration_id, "name": payload.name,
                "calibrated": payload.calibrated}

    @app.get("/api/v1/calibrations/current")
    def current_calibration(_: None = Depends(require_key)):
        row = repo.current_calibration()
        if row is None:
            raise HTTPException(status_code=404, detail="no calibration")
        return row

    @app.get("/api/v1/system-events")
    def system_events(limit: int = Query(100, ge=1, le=500),
                      _: None = Depends(require_key)):
        items = repo.list_system_events(limit=limit)
        return {"items": items, "count": len(items)}

    def retention_service() -> RetentionService:
        policy = RetentionPolicy(
            mode=settings.retention_mode,
            delete_source_after_days=settings.delete_source_after_days,
            event_retention_days=settings.event_retention_days,
            dry_run=settings.retention_dry_run,
            trash_dir=settings.trash_dir,
        )
        return RetentionService(policy, audit_sink=repo.add_retention_audit)

    @app.get("/api/v1/retention/status")
    def retention_status(_: None = Depends(require_key)):
        return {
            "mode": settings.retention_mode,
            "dry_run": settings.retention_dry_run,
            "delete_source_after_days": settings.delete_source_after_days,
            "event_retention_days": settings.event_retention_days,
            "audit": repo.retention_audit(limit=20),
        }

    @app.post("/api/v1/retention/preview")
    def retention_preview(_: None = Depends(require_key)):
        service = retention_service()
        report = service.run(repo.task_jobs_for_retention(), dry_run=True)
        return {
            "mode": report.mode, "dry_run": report.dry_run,
            "candidates": report.candidates, "deleted": report.deleted,
        }

    @app.post("/api/v1/retention/run")
    def retention_run(_: None = Depends(require_key)):
        service = retention_service()
        report = service.run(repo.task_jobs_for_retention(),
                             dry_run=settings.retention_dry_run)
        for job_id in report.deleted_jobs:
            repo.mark_source_deleted(job_id)
        return {
            "mode": report.mode, "dry_run": report.dry_run,
            "candidates": report.candidates, "deleted": report.deleted,
        }

    return app


app = create_app()
