"""Database engine, session management and schema bootstrap.

SQLite is the default and is a first-class choice here: one office, tens of
concurrent users, WAL enabled, and a nightly ``VACUUM INTO`` backup.  Point
``OFFICE_DB_URL`` at PostgreSQL to grow beyond that without code changes.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

log = logging.getLogger("office.db")

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    url = settings.database_url
    kwargs: dict = {"echo": False, "pool_pre_ping": True}

    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}

    _engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=15000")
                cursor.execute("PRAGMA temp_store=MEMORY")
                cursor.execute("PRAGMA cache_size=-16000")   # ~16 MB page cache
            finally:
                cursor.close()

    return _engine


def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency — one session per request.

    The middleware already opens a session for the request (it needs one to
    resolve the signed-in user).  Reusing it keeps a single identity map, so a
    handler may safely change the current user without tripping over
    "already attached to session" errors.
    """
    existing = getattr(request.state, "db", None)
    if existing is not None:
        yield existing
        return
    with Session(get_engine()) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background jobs and scripts."""
    with Session(get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def init_db() -> None:
    """Create any missing tables.

    Schema *changes* are applied by the migration runner (:mod:`app.migrations`)
    which is invoked on startup; ``create_all`` only ever adds new tables.
    """
    from . import models  # noqa: F401  (register all tables on the metadata)

    SQLModel.metadata.create_all(get_engine())
