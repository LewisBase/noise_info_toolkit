# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from app.config import Settings


def _settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(
        watch_dir=tmp_path / "audio",
        db_path=tmp_path / "db" / "noise.db",
        log_dir=tmp_path / "log",
        event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp",
        trash_dir=tmp_path / "trash",
        **kwargs,
    )


def test_defaults_are_debug_and_10s(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.read_window_s == 10.0
    assert settings.analysis_step_s == 1.0
    assert settings.persist_window_s == 10.0
    assert settings.retention_mode == "debug"
    assert settings.event_pre_s == 5.0
    assert settings.event_post_s == 10.0


def test_invalid_window_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _settings(tmp_path, read_window_s=0)


def test_invalid_retention_mode_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _settings(tmp_path, retention_mode="delete-everything")
