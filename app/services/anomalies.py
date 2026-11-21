# -*- coding: utf-8 -*-
"""System anomaly recording and de-duplication."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional


@dataclass(frozen=True)
class SystemEvent:
    code: str
    severity: int
    message: str
    start_utc: datetime
    context: dict = field(default_factory=dict)


class AnomalyService:
    def __init__(self, sink: Optional[Callable[[SystemEvent], None]] = None,
                 dedupe_s: int = 300):
        self.sink = sink
        self.dedupe_s = int(dedupe_s)
        self._last: dict[str, datetime] = {}
        self.events: list[SystemEvent] = []

    def record(self, code: str, severity: int, message: str,
               context: dict | None = None,
               now: datetime | None = None) -> Optional[SystemEvent]:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if code in self._last:
            if now - self._last[code] < timedelta(seconds=self.dedupe_s):
                return None
        self._last[code] = now
        event = SystemEvent(code=code, severity=int(severity),
                            message=str(message), start_utc=now,
                            context=context or {})
        self.events.append(event)
        if self.sink is not None:
            self.sink(event)
        return event
