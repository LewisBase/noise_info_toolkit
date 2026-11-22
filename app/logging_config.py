# -*- coding: utf-8 -*-
"""File logging shared by the API and the processing worker."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED: set[Path] = set()


def configure_logging(log_dir: str | Path) -> Path:
    path = Path(log_dir) / "backend.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path in _CONFIGURED:
        return path
    handler = RotatingFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=7, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "app"):
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    _CONFIGURED.add(path)
    return path
