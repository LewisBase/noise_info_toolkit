# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from pathlib import Path

from app.domain.metrics import Metrics
from app.storage import Database, Repository


def test_file_result_links_metrics(tmp_path: Path) -> None:
    db = Database(tmp_path / "noise.db")
    repo = Repository(db)
    sid = repo.create_session("CH1")
    source = tmp_path / "CH1_001.tdms"
    source.write_bytes(b"x")
    stat = source.stat()
    fid = repo.get_or_create_file_result(
        str(source), "CH1", stat.st_size, stat.st_mtime_ns, session_id=sid)
    metrics = Metrics(
        timestamp_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration_s=10.0, laeq=94.0, lceq=94.0, lzeq=94.0,
        freq_spl=(94.0,) * 9, channel="CH1", calibrated=True)
    repo.insert_time_history(sid, metrics, file_result_id=fid)
    repo.finalize_file_result(fid, metrics, status="done",
                              sample_rate=48000, event_count=0)
    item = repo.get_file_result(fid)
    assert item["file_name"] == "CH1_001.tdms"
    assert item["status"] == "done"
    assert item["sample_rate"] == 48000
    assert repo.file_result_metrics(fid)[0]["file_result_id"] == fid
    assert repo.list_file_results(channel="CH1")[0]["id"] == fid
    db.close()


def test_file_result_api(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    from app.api.app import create_app
    from app.config import Settings

    settings = Settings(
        watch_dir=tmp_path / "audio", db_path=tmp_path / "db" / "noise.db",
        log_dir=tmp_path / "log", event_dir=tmp_path / "events",
        temp_dir=tmp_path / "temp", trash_dir=tmp_path / "trash",
        export_dir=tmp_path / "exports",
    )
    with TestClient(create_app(settings)) as client:
        repo = client.app.state.repo
        sid = repo.create_session("CH1")
        source = tmp_path / "CH1_002.tdms"
        source.write_bytes(b"x")
        stat = source.stat()
        fid = repo.get_or_create_file_result(
            str(source), "CH1", stat.st_size, stat.st_mtime_ns,
            session_id=sid)
        metrics = Metrics(
            timestamp_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            duration_s=10.0, laeq=94.0, channel="CH1", calibrated=True)
        repo.insert_time_history(sid, metrics, file_result_id=fid)
        repo.finalize_file_result(fid, metrics, sample_rate=48000)
        listing = client.get("/api/v1/file-results", params={"channel": "CH1"})
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        detail = client.get(f"/api/v1/file-results/{fid}")
        assert detail.status_code == 200
        assert client.get(f"/api/v1/file-results/{fid}/metrics").json()["items"]
