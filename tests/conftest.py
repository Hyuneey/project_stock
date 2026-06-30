from __future__ import annotations

from pathlib import Path

import pytest

from project_stock.db.migrations import init_db
from project_stock.db.session import make_session_factory


@pytest.fixture()
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.sqlite'}"


@pytest.fixture()
def db_session(db_url: str):
    init_db(db_url)
    factory = make_session_factory(db_url)
    with factory() as session:
        yield session
        session.rollback()
