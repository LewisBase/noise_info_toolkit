# -*- coding: utf-8 -*-
"""Small HTTP client shared by the Streamlit pages."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests


class ApiError(RuntimeError):
    pass


@dataclass
class ApiClient:
    base_url: str
    api_key: str | None = None
    timeout: float = 8.0

    def __post_init__(self) -> None:
        self._session = requests.Session()
        if self.api_key:
            self._session.headers["X-API-Key"] = self.api_key

    def _request(self, method: str, path: str, **kwargs) -> Any:
        response = self._session.request(
            method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
        if response.status_code >= 400:
            raise ApiError(f"{response.status_code}: {response.text[:300]}")
        if response.headers.get("content-type", "").startswith("audio/"):
            return response.content
        return response.json()

    def _get(self, endpoint: str, **params) -> Any:
        return self._request("GET", endpoint, params=params)

    def health(self) -> dict:
        return self._get("/health/ready")

    def monitor_config(self) -> dict:
        return self._get("/api/v1/monitor/config")

    def start_monitor(self, watch_directory: str,
                      channel: str | None = None) -> dict:
        payload = {"watch_directory": watch_directory}
        if channel:
            payload["channel"] = channel
        return self._request("POST", "/api/v1/monitor/start", json=payload)

    def stop_monitor(self) -> dict:
        return self._request("POST", "/api/v1/monitor/stop")

    def list_dirs(self, path: str | None = None) -> dict:
        params = {"path": path} if path else {}
        return self._get("/api/v1/fs/dirs", **params)

    def channels(self) -> list[str]:
        return self._get("/api/v1/channels").get("items", ["CH1"])

    def latest(self, channel: str) -> dict:
        return self._get("/api/v1/metrics/latest", channel=channel)

    def history(self, channel: str, start: datetime, end: datetime,
                limit: int = 1000, offset: int = 0) -> list[dict]:
        return self._get("/api/v1/metrics/history", channel=channel,
                         start=start.isoformat(), end=end.isoformat(),
                         limit=limit, offset=offset).get("items", [])

    def sessions(self) -> list[dict]:
        return self._get("/api/v1/sessions").get("items", [])

    def current_session(self, channel: str | None = None) -> dict | None:
        try:
            return self._get("/api/v1/sessions/current", channel=channel)
        except ApiError:
            return None

    def create_session(self, channel: str) -> dict:
        return self._request("POST", "/api/v1/sessions", json={"channel": channel})

    def stop_session(self, session_id: str) -> dict:
        return self._request("POST", f"/api/v1/sessions/{session_id}/stop")

    def session_metrics(self, session_id: str, channel: str) -> list[dict]:
        return self._get(f"/api/v1/sessions/{session_id}/metrics",
                         channel=channel).get("items", [])

    def events(self, session_id: str, channel: str | None = None,
               limit: int = 100) -> list[dict]:
        params = {"limit": limit}
        if channel:
            params["channel"] = channel
        return self._get(f"/api/v1/sessions/{session_id}/events",
                         **params).get("items", [])

    def event_audio(self, event_id: str) -> bytes:
        return self._request("GET", f"/api/v1/events/{event_id}/audio")

    def system_events(self, limit: int = 100) -> list[dict]:
        return self._get("/api/v1/system-events", limit=limit).get("items", [])

    def calibration(self) -> dict:
        return self._get("/api/v1/calibrations/current")

    def retention(self) -> dict:
        return self._get("/api/v1/retention/status")

    def retention_preview(self) -> dict:
        return self._request("POST", "/api/v1/retention/preview")
