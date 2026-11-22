# -*- coding: utf-8 -*-
"""SQLite engine/session management with WAL and busy timeout."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.path.as_posix()}",
            connect_args={"timeout": 30, "check_same_thread": False},
            pool_pre_ping=True,
        )
        event.listen(self.engine, "connect", self._set_pragmas)
        Base.metadata.create_all(self.engine)
        self._ensure_columns()
        self._session_factory = sessionmaker(
            bind=self.engine, autocommit=False, autoflush=False,
            expire_on_commit=False,
        )

    def _ensure_columns(self) -> None:
        """Add review columns to databases created before this version."""
        columns = {
            "events": {
                "review_state": "VARCHAR(20) NOT NULL DEFAULT 'unreviewed'",
                "reviewed_by": "VARCHAR(100)",
                "reviewed_at": "VARCHAR(32)",
                "review_note": "TEXT",
                "file_result_id": "INTEGER",
            },
            "time_history": {
                "file_result_id": "INTEGER",
                "recorded_at": "VARCHAR(32)",
            },
        }
        with self.engine.begin() as conn:
            for table, table_columns in columns.items():
                existing = {row[1] for row in conn.exec_driver_sql(
                    f"PRAGMA table_info({table})")}
                for name, ddl in table_columns.items():
                    if name not in existing:
                        conn.exec_driver_sql(
                            f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    @staticmethod
    def _set_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        self.engine.dispose()


# Convenience alias retained for the plan's code examples.
@contextmanager
def session_scope(database: Database) -> Iterator[Session]:
    with database.session_scope() as session:
        yield session
