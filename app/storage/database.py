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
        self._session_factory = sessionmaker(
            bind=self.engine, autocommit=False, autoflush=False,
            expire_on_commit=False,
        )

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
