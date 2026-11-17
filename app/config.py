# -*- coding: utf-8 -*-
"""Application configuration (absolute paths, no CWD dependence).

All runtime directories are created/validated at startup.  Retention defaults
to ``debug``: the field-deployment baseline must never delete source audio
before explicit production sign-off.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="NIT_",
        extra="ignore",
    )

    app_root: Path = PROJECT_ROOT
    watch_dir: Path = PROJECT_ROOT / "audio_files"
    db_path: Path = PROJECT_ROOT / "Database" / "noise_info.db"
    log_dir: Path = PROJECT_ROOT / "log"
    event_dir: Path = PROJECT_ROOT / "audio_events"
    temp_dir: Path = PROJECT_ROOT / "temp"
    trash_dir: Path = PROJECT_ROOT / "trash"

    host: str = "127.0.0.1"
    port: int = 8000
    api_key: str | None = None
    backend_url: str = "http://127.0.0.1:8000"
    timezone: str = "Asia/Shanghai"

    require_calibration: bool = True
    read_window_s: float = 10.0
    analysis_step_s: float = 1.0
    persist_window_s: float = 10.0
    band_order: int = 4
    stable_seconds: float = 2.0
    max_file_bytes: int = 20 * 1024 ** 3
    allowed_watch_roots: list[Path] = Field(default_factory=list)

    event_pre_s: float = 5.0
    event_post_s: float = 10.0
    event_max_s: float = 60.0
    event_min_gap_s: float = 2.0
    event_audio_subtype: str = "FLOAT"

    retention_mode: str = "debug"
    delete_source_after_days: float = 7.0
    event_retention_days: float = 365.0
    retention_dry_run: bool = True

    @model_validator(mode="after")
    def _prepare(self) -> "Settings":
        if not (0 < self.analysis_step_s <= self.read_window_s <= 60):
            raise ValueError("require 0 < analysis_step_s <= read_window_s <= 60")
        ratio = self.persist_window_s / self.analysis_step_s
        if abs(ratio - round(ratio)) > 1e-9:
            raise ValueError("persist_window_s must be a multiple of analysis_step_s")
        if self.retention_mode not in ("debug", "production"):
            raise ValueError("retention_mode must be debug or production")
        if self.event_pre_s < 0 or self.event_post_s < 0:
            raise ValueError("event pre/post must be >= 0")
        if self.event_max_s < self.event_pre_s + self.event_post_s:
            raise ValueError("event_max_s must be >= event_pre_s + event_post_s")
        # Relative .env paths must not depend on the service working directory.
        for field_name in ("watch_dir", "db_path", "log_dir", "event_dir",
                           "temp_dir", "trash_dir"):
            value = getattr(self, field_name)
            if not value.is_absolute():
                setattr(self, field_name, (PROJECT_ROOT / value).resolve())
        self.allowed_watch_roots = [
            root.expanduser().resolve() for root in self.allowed_watch_roots
        ]
        for directory in (
            self.watch_dir, self.db_path.parent, self.log_dir,
            self.event_dir, self.temp_dir, self.trash_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
            if not directory.is_dir():
                raise ValueError(f"not a directory: {directory}")
        return self

    def is_allowed_directory(self, path: Path) -> bool:
        """Return True when the directory is inside an allowed watch root.

        An empty allow-list keeps development/demo compatibility but should not
        be used for an exposed deployment; ``/health/ready`` reports that state.
        """
        resolved = Path(path).expanduser().resolve()
        if not self.allowed_watch_roots:
            return True
        return any(resolved == root or root in resolved.parents
                   for root in self.allowed_watch_roots)
