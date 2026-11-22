# -*- coding: utf-8 -*-
"""Start the field-deployment API (single worker, config-driven)."""
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
