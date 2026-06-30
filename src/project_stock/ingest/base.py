from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session


class Ingestor(Protocol):
    def ingest(self, session: Session) -> int:
        ...
