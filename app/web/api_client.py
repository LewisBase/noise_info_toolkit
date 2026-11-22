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

    def stream_url(self, channel: str | None = None,
                   since: str | None = None) -> str:
        from urllib.parse import quote
        base = self.base_url.rstrip("/")
        params = []
        if channel:
            params.append(f"channel={quote(channel)}")
        if since:
            params.append(f"since={quote(since)}")
        if self.api_key:
            params.append(f"api_key={quote(self.api_key)}")
        return f"{base}/api/v1/stream" + (("?" + "&".join(params)) if params else "")

    def whoami(self) -> dict:
        return self._get("/api/v1/whoami")

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

    def export_results(self) -> dict:
        return self._request("POST", "/api/v1/export")

    def list_dirs(self, path: str | None = None) -> dict:
        params = {"path": path} if path else {}
        return self._get("/api/v1/fs/dirs", **params)

    def channels(self) -> list[str]:
        return self._get("/api/v1/channels").get("items", ["CH1"])

    def event_config(self) -> dict:
        return self._get("/api/v1/event-config")

    def update_event_config(self, payload: dict) -> dict:
        return self._request("PUT", "/api/v1/event-config", json=payload)

    def file_results(self, channel: str | None = None,
                     status: str | None = None,
                     limit: int = 100, offset: int = 0,
                     created_since: str | None = None) -> dict:
        params = {"limit": limit, "offset": offset}
        if created_since:
            params["created_since"] = created_since
        if channel:
            params["channel"] = channel
        if status:
            params["status"] = status
        return self._get("/api/v1/file-results", **params)

    def file_result(self, file_result_id: int) -> dict:
        return self._get(f"/api/v1/file-results/{file_result_id}")

    def file_result_metrics(self, file_result_id: int) -> list[dict]:
        return self._get(
            f"/api/v1/file-results/{file_result_id}/metrics").get("items", [])

    def file_result_events(self, file_result_id: int) -> list[dict]:
        return self._get(
            f"/api/v1/file-results/{file_result_id}/events").get("items", [])

    def jobs(self, limit: int = 100) -> list[dict]:
        return self._get("/api/v1/jobs", limit=limit).get("items", [])

    def latest(self, channel: str, since: str | None = None) -> dict:
        params = {"channel": channel}
        if since:
            params["since"] = since
        return self._get("/api/v1/metrics/latest", **params)

    def history(self, channel: str, start: datetime, end: datetime,
                limit: int = 1000, offset: int = 0,
                aggregate: str = "raw",
                recorded_since: str | None = None) -> list[dict]:
        return self.history_page(channel, start, end, limit, offset,
                                 aggregate, recorded_since)["items"]

    def history_page(self, channel: str, start: datetime, end: datetime,
                     limit: int = 1000, offset: int = 0,
                     aggregate: str = "raw",
                     recorded_since: str | None = None) -> dict:
        params = {"channel": channel, "start": start.isoformat(),
                  "end": end.isoformat(), "limit": limit, "offset": offset,
                  "aggregate": aggregate}
        if recorded_since:
            params["recorded_since"] = recorded_since
        return self._get("/api/v1/metrics/history", **params)

    def sessions(self, started_since: str | None = None) -> list[dict]:
        params = {"started_since": started_since} if started_since else {}
        return self._get("/api/v1/sessions", **params).get("items", [])

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

    def review_event(self, event_id: str, state: str,
                     note: str | None = None,
                     reviewer: str | None = None) -> dict:
        return self._request("POST", f"/api/v1/events/{event_id}/review",
                             json={"state": state, "note": note,
                                   "reviewer": reviewer})

    def event_audio(self, event_id: str) -> bytes:
        return self._request("GET", f"/api/v1/events/{event_id}/audio")

    def system_events(self, limit: int = 100) -> list[dict]:
        return self._get("/api/v1/system-events", limit=limit).get("items", [])

    def calibration(self) -> dict:
        return self._get("/api/v1/calibrations/current")

    def add_calibration(self, payload: dict) -> dict:
        return self._request("POST", "/api/v1/calibrations", json=payload)

    def retention(self) -> dict:
        return self._get("/api/v1/retention/status")

    def retention_preview(self) -> dict:
        return self._request("POST", "/api/v1/retention/preview")
