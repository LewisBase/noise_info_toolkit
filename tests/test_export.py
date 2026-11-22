# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from pathlib import Path

from app.domain.metrics import Metrics
from app.storage import Database, Repository


def test_export_results_csv(tmp_path: Path) -> None:
    db = Database(tmp_path / "noise.db")
    repo = Repository(db)
    sid = repo.create_session("CH1")
    metrics = Metrics(timestamp_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
                      duration_s=1.0, laeq=94.0, lceq=94.0, lzeq=94.0,
                      freq_spl=(94.0,) * 9, channel="CH1", calibrated=True)
    source = tmp_path / "CH1.tdms"
    source.write_bytes(b"x")
    stat = source.stat()
    fid = repo.get_or_create_file_result(
        str(source), "CH1", stat.st_size, stat.st_mtime_ns, session_id=sid)
    repo.insert_time_history(sid, metrics, file_result_id=fid)
    repo.finalize_file_result(fid, metrics, sample_rate=8000)
    paths = repo.export_results_csv(tmp_path / "exports")
    assert "metrics" in paths
    assert "file_results" in paths
    text = Path(paths["metrics"]).read_text(encoding="utf-8-sig")
    assert "timestamp_utc" in text
    assert "94.0" in text
    db.close()


def test_export_empty_returns_no_files(tmp_path: Path) -> None:
    db = Database(tmp_path / "noise.db")
    paths = Repository(db).export_results_csv(tmp_path / "exports")
    assert paths == {}
    db.close()
