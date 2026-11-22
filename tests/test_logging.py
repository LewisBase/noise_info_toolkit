# -*- coding: utf-8 -*-
from pathlib import Path

from app.api.app import create_app
from app.config import Settings


def test_backend_log_file_is_created(tmp_path: Path) -> None:
    log_dir = tmp_path / "log"
    settings = Settings(
        watch_dir=tmp_path / "audio", db_path=tmp_path / "db" / "noise.db",
        log_dir=log_dir, event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp", trash_dir=tmp_path / "trash",
        export_dir=tmp_path / "exports",
    )
    create_app(settings)
    assert (log_dir / "backend.log").is_file()
