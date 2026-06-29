from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def _ensure_sqlite_parent(db_url: str) -> None:
    if not db_url.startswith("sqlite:///"):
        return
    raw_path = db_url.replace("sqlite:///", "", 1)
    if raw_path == ":memory:":
        return
    Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(db_url: str) -> Engine:
    _ensure_sqlite_parent(db_url)
    return create_engine(db_url, future=True)


def make_session_factory(db_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=create_db_engine(db_url), future=True)


@contextmanager
def session_scope(db_url: str) -> Iterator[Session]:
    factory = make_session_factory(db_url)
    with factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
