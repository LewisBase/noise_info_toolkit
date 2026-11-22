# -*- coding: utf-8 -*-
"""Versioned FastAPI surface over the new storage/DSP stack."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import (Depends, FastAPI, Header, HTTPException, Query, Request,
                    WebSocket, WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import Settings
from app.domain.calibration import Calibration
from app.dsp.event_detector import EventConfig
from app.services.event_bus import EventBus
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


class EventSettings(BaseModel):
    laf_minor_db: float = Field(85.0, ge=40, le=140)
    laf_moderate_db: float = Field(95.0, ge=40, le=160)
    laf_severe_db: float = Field(110.0, ge=40, le=180)
    impulse_minor_db: float = Field(6.0, ge=0, le=60)
    impulse_severe_db: float = Field(12.0, ge=0, le=80)
    rise_minor_db: float = Field(10.0, ge=0, le=60)
    rise_moderate_db: float = Field(15.0, ge=0, le=80)
    background_delta_db: float = Field(15.0, ge=0, le=80)
    background_tau_s: float = Field(300.0, ge=10, le=3600)
    peak_threshold_db: float = Field(140.0, ge=80, le=200)
    underrange_db: float = Field(30.0, ge=0, le=120)
    history_s: float = Field(16.0, ge=1, le=120)
    history_step_s: float = Field(0.1, ge=0.01, le=5)
    pre_s: float = Field(5.0, ge=0, le=60)
    post_s: float = Field(10.0, ge=0, le=120)
    max_s: float = Field(60.0, ge=1, le=600)
    min_gap_s: float = Field(2.0, ge=0, le=60)

    def to_config(self) -> EventConfig:
        data = self.model_dump()
        thresholds = {
            key: value for key, value in data.items()
            if key in EventConfig.__dataclass_fields__
        }
        return EventConfig(**thresholds)


class EventReview(BaseModel):
    state: str = Field(pattern="^(unreviewed|confirmed|false_positive)$")
    note: Optional[str] = None
    reviewer: Optional[str] = None


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
    event_bus = EventBus()
    service = ProcessingService(settings, db, event_bus=event_bus)

    def require_role(minimum: str):
        ranks = {"operator": 1, "calibrator": 2, "admin": 3}

        def dependency(x_api_key: str | None = Header(default=None)) -> str:
            role = settings.api_role(x_api_key)
            if role is None:
                raise HTTPException(status_code=401, detail="invalid API key")
            if ranks[role] < ranks[minimum]:
                raise HTTPException(status_code=403,
                                    detail=f"{minimum} role required")
            return role

        return dependency

    require_operator = require_role("operator")
    require_calibrator = require_role("calibrator")
    require_admin = require_role("admin")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        event_bus.attach_loop(asyncio.get_running_loop())
        app.state.service.start()
        try:
            yield
        finally:
            app.state.service.stop(timeout=30)
            db.close()

    app = FastAPI(title="Noise Info Toolkit API", version="1.1.0",
                  lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["*"],
    )
    app.state.repo = repo
    app.state.settings = settings
    app.state.service = service
    app.state.bus = event_bus

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
    def monitor_config(_: None = Depends(require_operator)):
        return {
            "watch_directory": str(settings.watch_dir),
            "retention_mode": settings.retention_mode,
            "processing": app.state.service.status(),
        }

    @app.post("/api/v1/monitor/start")
    def monitor_start(payload: MonitorStart,
                      _: None = Depends(require_operator)):
        directory = Path(payload.watch_directory).expanduser().resolve()
        if not settings.is_allowed_directory(directory):
            raise HTTPException(status_code=403,
                                detail="directory is outside allowed watch roots")
        if not directory.is_dir():
            # Do not mkdir arbitrary user input: a typo (or an error string)
            # must not silently create a new watch directory.
            raise HTTPException(status_code=400,
                                detail="directory not found or not a directory")
        app.state.service.stop(timeout=30)
        settings.watch_dir = directory
        replacement = ProcessingService(settings, db, event_bus=event_bus)
        replacement.start()
        app.state.service = replacement
        return {
            "status": "started",
            "watch_directory": str(directory),
            "processing": replacement.status(),
        }

    @app.post("/api/v1/monitor/stop")
    def monitor_stop(_: None = Depends(require_operator)):
        app.state.service.stop(timeout=30)
        exported = (repo.export_results_csv(settings.export_dir)
                    if settings.auto_export_on_stop else {})
        return {"status": "stopped", "processing": app.state.service.status(),
                "export": exported}

    @app.post("/api/v1/export")
    def export_results(_: None = Depends(require_operator)):
        return {"export": repo.export_results_csv(settings.export_dir)}

    @app.get("/api/v1/fs/dirs")
    def list_directories(path: Optional[str] = None,
                         _: None = Depends(require_operator)):
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

    def _stream_role(api_key: str | None) -> str | None:
        role = settings.api_role(api_key)
        if role is None:
            return None
        return role

    @app.get("/api/v1/stream")
    async def stream(request: Request, api_key: Optional[str] = None):
        if _stream_role(api_key) is None:
            raise HTTPException(status_code=401, detail="invalid API key")

        async def events():
            # EventSource reconnects automatically; tell it the retry delay.
            yield "retry: 5000\n\n"
            async for item in event_bus.subscribe():
                if await request.is_disconnected():
                    break
                payload = json.dumps(item, ensure_ascii=False)
                yield f"event: {item.get('type', 'message')}\ndata: {payload}\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache",
                     "X-Accel-Buffering": "no",
                     "Connection": "keep-alive"})

    @app.websocket("/api/v1/ws")
    async def websocket_stream(websocket: WebSocket,
                               api_key: Optional[str] = None):
        if _stream_role(api_key) is None:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            async for item in event_bus.subscribe():
                await websocket.send_json(item)
        except WebSocketDisconnect:
            return
        except Exception:
            try:
                await websocket.close(code=1011)
            except Exception:
                pass

    @app.get("/api/v1/channels")
    def channels(_: None = Depends(require_operator)):
        items = repo.list_channels()
        if not items:
            items = ["CH1"]
        return {"items": items}

    @app.get("/api/v1/event-config")
    def get_event_config(_: None = Depends(require_operator)):
        defaults = EventSettings()
        raw = repo.get_app_config("event_config") or {}
        merged = defaults.model_dump()
        merged.update({k: v for k, v in raw.items() if k in merged})
        return merged

    @app.put("/api/v1/event-config")
    def put_event_config(payload: EventSettings,
                         _: None = Depends(require_calibrator)):
        config = payload.to_config()
        data = payload.model_dump()
        if data["max_s"] < data["pre_s"] + data["post_s"]:
            raise HTTPException(
                status_code=422,
                detail="max_s must be >= pre_s + post_s")
        data["event_config"] = {
            k: getattr(config, k) for k in EventConfig.__dataclass_fields__
        }
        repo.set_app_config("event_config", data)
        return data

    @app.get("/api/v1/file-results")
    def file_results(channel: Optional[str] = None,
                     status: Optional[str] = None,
                     limit: int = Query(100, ge=1, le=500),
                     offset: int = Query(0, ge=0),
                     _: None = Depends(require_operator)):
        items = repo.list_file_results(channel=channel, status=status,
                                       limit=limit, offset=offset)
        return {"items": items, "count": len(items),
                "total": repo.count_file_results(channel, status),
                "limit": limit, "offset": offset}

    @app.get("/api/v1/file-results/{file_result_id}")
    def file_result(file_result_id: int,
                    _: None = Depends(require_operator)):
        item = repo.get_file_result(file_result_id)
        if item is None:
            raise HTTPException(status_code=404, detail="file result not found")
        return item

    @app.get("/api/v1/file-results/{file_result_id}/metrics")
    def file_result_metrics(file_result_id: int,
                            limit: int = Query(5000, ge=1, le=50000),
                            _: None = Depends(require_operator)):
        return {"items": repo.file_result_metrics(file_result_id, limit=limit)}

    @app.get("/api/v1/file-results/{file_result_id}/events")
    def file_result_events(file_result_id: int,
                           _: None = Depends(require_operator)):
        return {"items": repo.file_result_events(file_result_id)}

    @app.get("/api/v1/jobs")
    def jobs(status: Optional[str] = None,
             limit: int = Query(100, ge=1, le=500),
             _: None = Depends(require_operator)):
        return {"items": repo.list_jobs(status=status, limit=limit)}

    @app.get("/api/v1/whoami")
    def whoami(role: str = Depends(require_operator)):
        return {"role": role}

    @app.get("/api/v1/metrics/latest")
    def latest(channel: str = "CH1",
               since: Optional[datetime] = None,
               _: None = Depends(require_operator)):
        if since is not None and since.tzinfo is None:
            raise HTTPException(status_code=422,
                                detail="since must include timezone")
        row = repo.latest_time_history(channel, recorded_since=since)
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
                aggregate: str = Query("raw", pattern="^(raw|minute)$"),
                _: None = Depends(require_operator)):
        for value in (start, end):
            if value is not None and value.tzinfo is None:
                raise HTTPException(status_code=422,
                                    detail="start/end must include timezone")
        total = repo.count_time_history(channel, start=start, end=end)
        if aggregate == "minute":
            raw = repo.list_time_history(channel, start=start, end=end,
                                         limit=10000, offset=0)
            items = repo.aggregate_minutes(raw)
            total = len(items)
            items = items[offset:offset + limit]
        else:
            items = repo.list_time_history(channel, start=start, end=end,
                                           limit=limit, offset=offset)
        return {"items": items, "count": len(items), "total": total,
                "limit": limit, "offset": offset, "aggregate": aggregate}

    @app.get("/api/v1/sessions")
    def sessions(limit: int = Query(50, ge=1, le=500),
                 offset: int = Query(0, ge=0),
                 _: None = Depends(require_operator)):
        items = repo.list_sessions(limit=limit, offset=offset)
        return {"items": items, "count": len(items)}

    @app.get("/api/v1/sessions/current")
    def current_session(channel: str | None = None,
                        _: None = Depends(require_operator)):
        row = repo.current_session(channel)
        if row is None:
            raise HTTPException(status_code=404, detail="no active session")
        return row

    @app.post("/api/v1/sessions")
    def start_session(payload: SessionCreate, _: None = Depends(require_operator)):
        session_id = repo.create_session(
            channel=payload.channel, profile=payload.profile,
            device_id=payload.device_id, operator=payload.operator,
            organization=payload.organization,
            calibration_id=payload.calibration_id,
        )
        return {"session_id": session_id, "state": "running"}

    @app.post("/api/v1/sessions/{session_id}/stop")
    def stop_session(session_id: str, _: None = Depends(require_operator)):
        repo.close_session(session_id)
        return {"session_id": session_id, "state": "stopped"}

    @app.get("/api/v1/sessions/{session_id}/metrics")
    def session_metrics(session_id: str, channel: str = "CH1",
                        limit: int = Query(2000, ge=1, le=10000),
                        offset: int = Query(0, ge=0),
                        _: None = Depends(require_operator)):
        items = repo.list_time_history(
            channel, limit=limit, offset=offset, session_id=session_id)
        return {"items": items, "count": len(items),
                "limit": limit, "offset": offset}

    @app.get("/api/v1/sessions/{session_id}/events")
    def session_events(session_id: str, channel: str | None = None,
                       limit: int = Query(100, ge=1, le=500),
                       _: None = Depends(require_operator)):
        items = repo.list_events(session_id=session_id, channel=channel,
                                 limit=limit)
        return {"items": items, "count": len(items)}

    @app.post("/api/v1/events/{event_id}/review")
    def review_event(event_id: str, payload: EventReview,
                     _: None = Depends(require_operator)):
        try:
            item = repo.review_event(
                event_id, payload.state, payload.reviewer, payload.note)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if item is None:
            raise HTTPException(status_code=404, detail="event not found")
        return item

    @app.get("/api/v1/events/{event_id}/audio")
    def event_audio(event_id: str, _: None = Depends(require_operator)):
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
                        _: None = Depends(require_calibrator)):
        calibration = Calibration(
            name=payload.name, unit=payload.unit,
            pa_per_unit=payload.pa_per_unit, offset_pa=payload.offset_pa,
            offset_db=payload.offset_db, calibrated=payload.calibrated)
        calibration_id = repo.add_calibration(
            calibration, payload.name, payload.certificate)
        return {"id": calibration_id, "name": payload.name,
                "calibrated": payload.calibrated}

    @app.get("/api/v1/calibrations/current")
    def current_calibration(_: None = Depends(require_operator)):
        row = repo.current_calibration()
        if row is None:
            raise HTTPException(status_code=404, detail="no calibration")
        return row

    @app.get("/api/v1/system-events")
    def system_events(limit: int = Query(100, ge=1, le=500),
                      _: None = Depends(require_operator)):
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
    def retention_status(_: None = Depends(require_admin)):
        return {
            "mode": settings.retention_mode,
            "dry_run": settings.retention_dry_run,
            "delete_source_after_days": settings.delete_source_after_days,
            "event_retention_days": settings.event_retention_days,
            "audit": repo.retention_audit(limit=20),
        }

    @app.post("/api/v1/retention/preview")
    def retention_preview(_: None = Depends(require_admin)):
        service = retention_service()
        report = service.run(repo.task_jobs_for_retention(), dry_run=True)
        return {
            "mode": report.mode, "dry_run": report.dry_run,
            "candidates": report.candidates, "deleted": report.deleted,
        }

    @app.post("/api/v1/retention/run")
    def retention_run(_: None = Depends(require_admin)):
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
