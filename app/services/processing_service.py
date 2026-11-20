# -*- coding: utf-8 -*-
"""File watcher + single worker that runs the streaming pipeline into SQLite.

The watcher only enqueues paths; DSP/DB work happens in a separate worker so
that ``observer.join()`` never waits for a long file.
"""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Optional

from app.config import Settings
from app.dsp.event_detector import EventConfig
from app.io.tdms_source import TdmsChannelSource
from app.services.anomalies import AnomalyService
from app.services.event_audio import EventAudioCapture
from app.services.event_bus import EventBus
from app.services.streaming_pipeline import PipelineConfig, process_tdms_file
from app.storage import Database, Repository


def wait_stable(path: Path, stable_s: float = 2.0,
                timeout_s: float = 300.0) -> bool:
    deadline = time.monotonic() + timeout_s
    last = None
    changed_at = time.monotonic()
    while time.monotonic() < deadline:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return False
        signature = (stat.st_size, stat.st_mtime_ns)
        now = time.monotonic()
        if signature != last:
            last = signature
            changed_at = now
        elif now - changed_at >= stable_s:
            return True
        time.sleep(0.5)
    return False


class ProcessingService:
    def __init__(self, settings: Settings, database: Database | None = None,
                 queue_size: int = 1000, event_bus: EventBus | None = None):
        self.settings = settings
        self.database = database or Database(settings.db_path)
        self.repo = Repository(self.database)
        self.event_bus = event_bus
        self.anomalies = AnomalyService(sink=self._record_system_event)
        self._queue: queue.Queue[Path] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._observer = None
        self._last_error: str | None = None
        self._started = False
        self._captures: dict[tuple[str, str], EventAudioCapture] = {}

    def _record_system_event(self, event) -> int:
        event_id = self.repo.insert_system_event(event)
        if self.event_bus is not None:
            self.event_bus.publish({
                "type": "system_event",
                "item": {
                    "id": event_id, "code": event.code,
                    "severity": event.severity, "message": event.message,
                    "start_utc": event.start_utc.isoformat(),
                },
            })
        return event_id

    # ---------------- lifecycle ----------------
    def start(self) -> None:
        self._started = True
        self.scan_existing()
        self._start_watcher()
        self._worker.start()

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
        if self._worker.is_alive():
            self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            self.anomalies.record(
                "worker_stop_timeout", 2,
                f"worker still alive after {timeout}s")
        self._flush_captures()
        self._observer = None
        self._started = False

    def scan_existing(self) -> int:
        count = 0
        for path in sorted(self.settings.watch_dir.rglob("*.tdms")):
            if self._enqueue(path):
                count += 1
        return count

    def _enqueue(self, path: Path) -> bool:
        if path.suffix.lower() != ".tdms" or not path.is_file():
            return False
        try:
            self._queue.put_nowait(path)
            return True
        except queue.Full:
            self.anomalies.record("queue_overflow", 3,
                                  f"queue full while enqueueing {path}")
            return False

    def _start_watcher(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            self.anomalies.record("watchdog_missing", 2,
                                  "watchdog not installed; scan-only mode")
            return

        service = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    service._enqueue(Path(event.src_path))

            def on_moved(self, event):
                if not event.is_directory:
                    service._enqueue(Path(event.dest_path))

            def on_closed(self, event):
                if not event.is_directory:
                    service._enqueue(Path(event.src_path))

        self._observer = Observer()
        self._observer.schedule(Handler(), str(self.settings.watch_dir),
                                recursive=False)
        self._observer.start()

    # ---------------- worker ----------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                path = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if wait_stable(path, self.settings.stable_seconds):
                    self.process_path(path)
            except Exception as exc:  # keep the worker alive
                self._last_error = str(exc)
                self.anomalies.record("file_processing_error", 3,
                                      f"{path}: {exc}")

    def process_path(self, path: str | Path,
                     channel: str | None = None) -> None:
        path = Path(path)
        channels = [channel] if channel else TdmsChannelSource.list_channels(path)
        if not channels:
            channels = ["CH1"]
        for channel_name in channels:
            self._process_channel(path, channel_name)

    def _event_settings(self) -> tuple[EventConfig, float, float, float, float]:
        defaults = EventConfig()
        raw = self.repo.get_app_config("event_config") or {}
        fields = {
            name: raw.get(name, getattr(defaults, name))
            for name in defaults.__dataclass_fields__
        }
        try:
            event_config = EventConfig(**fields)
        except (TypeError, ValueError):
            event_config = defaults
        return (
            event_config,
            float(raw.get("pre_s", self.settings.event_pre_s)),
            float(raw.get("post_s", self.settings.event_post_s)),
            float(raw.get("max_s", self.settings.event_max_s)),
            float(raw.get("min_gap_s", self.settings.event_min_gap_s)),
        )

    def _process_channel(self, path: Path, channel: str) -> None:
        stat = path.stat()
        job = self.repo.get_or_create_job(
            file_path=str(path), channel=channel,
            file_size=stat.st_size, file_mtime_ns=stat.st_mtime_ns)
        if job["status"] == "done":
            return
        self.repo.mark_job(job["id"], "running")
        session_id = self.repo.get_or_create_session(channel)
        event_config, pre_s, post_s, max_s, min_gap_s = self._event_settings()
        config = PipelineConfig(
            read_window_s=self.settings.read_window_s,
            analysis_step_s=self.settings.analysis_step_s,
            persist_window_s=self.settings.persist_window_s,
            band_order=self.settings.band_order,
            event_pre_s=pre_s,
            event_post_s=post_s,
            event_max_s=max_s,
            event_min_gap_s=min_gap_s,
            event_dir=self.settings.event_dir,
            event_config=event_config,
        )
        try:
            key = (session_id, channel)
            result = process_tdms_file(
                path, config, channel=channel,
                capture=self._captures.get(key),
                flush_capture=False,
                on_window=lambda row: self._on_window(session_id, channel, row),
                on_event=lambda clip: self._on_event(session_id, channel, clip),
            )
            if result.capture is not None:
                self._captures[key] = result.capture
        except Exception as exc:
            self.repo.mark_job(job["id"], "failed", str(exc))
            raise
        self.repo.mark_job(job["id"], "done")

    def _on_window(self, session_id: str, channel: str, row) -> None:
        self.repo.insert_time_history(session_id, row)
        if self.event_bus is not None:
            latest = self.repo.latest_time_history(channel)
            if latest is not None:
                self.event_bus.publish({"type": "metric", "item": latest})

    def _on_event(self, session_id: str, channel: str, clip) -> None:
        self.repo.insert_event(session_id, channel, clip)
        if self.event_bus is not None:
            self.event_bus.publish({"type": "event", "item": clip.to_dict()})

    def _flush_captures(self) -> None:
        for (session_id, channel), capture in list(self._captures.items()):
            try:
                clip = capture.flush()
                if clip is not None:
                    self._on_event(session_id, channel, clip)
            except Exception as exc:
                self.anomalies.record(
                    "event_flush_error", 2,
                    f"{session_id}/{channel}: {exc}")
            finally:
                self._captures.pop((session_id, channel), None)

    def status(self) -> dict:
        return {
            "running": self._started,
            "monitoring": self._started,
            "watching": self._observer is not None,
            "queue_depth": self._queue.qsize(),
            "last_error": self._last_error,
            "retention_mode": self.settings.retention_mode,
            "watch_dir": str(self.settings.watch_dir),
            "worker_alive": self._worker.is_alive(),
        }
