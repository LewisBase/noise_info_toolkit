# -*- coding: utf-8 -*-
"""Start the field-deployment API.

Legacy code remains in ``main.py`` for reference, but the field entrypoint is
the versioned API in ``app.api.app``.  Run exactly one worker: SQLite and the
file-processing service are single-writer/single-worker by design.
"""
from __future__ import annotations

import uvicorn

from app.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "app.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":
    main()
