from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from sqlalchemy.orm import Session

from project_stock.schemas.common import SchemaBase


RawRecordT = TypeVar("RawRecordT", bound=SchemaBase)
NormalizedRecordT = TypeVar("NormalizedRecordT", bound=SchemaBase)


class CollectorConfigError(RuntimeError):
    """Raised when a real collector fetch is requested without required configuration."""


class CollectorIngestResult(SchemaBase):
    collector_id: str
    source_id: str
    inserted_count: int
    skipped_count: int = 0
    record_ids: list[str]


class CollectorProtocol(Protocol[RawRecordT, NormalizedRecordT]):
    collector_id: str
    source_id: str

    def fetch_raw(self, fixture: Path | None = None, mock: bool = True) -> list[RawRecordT]:
        ...

    def normalize(self, raw_records: list[RawRecordT]) -> list[NormalizedRecordT]:
        ...

    def ingest(self, session: Session, fixture: Path | None = None, mock: bool = True) -> CollectorIngestResult:
        ...


class Ingestor(Protocol):
    def ingest(self, session: Session) -> int:
        ...


class OfficialCollector(ABC, Generic[RawRecordT, NormalizedRecordT]):
    collector_id: str
    source_id: str
    api_key_env_var: str | None = None

    def fetch_raw(self, fixture: Path | None = None, mock: bool = True) -> list[RawRecordT]:
        if mock:
            if fixture is None:
                raise ValueError("mock fixture path is required")
            return self._load_fixture(fixture)
        self._require_api_key()
        raise NotImplementedError("Real collector fetch is intentionally not implemented in this MVP.")

    def _require_api_key(self) -> str:
        if self.api_key_env_var is None:
            return ""
        api_key = os.getenv(self.api_key_env_var)
        if not api_key:
            raise CollectorConfigError(
                f"{self.collector_id} real fetch requires {self.api_key_env_var}."
            )
        return api_key

    def _load_fixture(self, fixture: Path) -> list[RawRecordT]:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        records = payload["records"] if isinstance(payload, dict) and "records" in payload else payload
        return [self.raw_schema().model_validate(record) for record in records]

    @abstractmethod
    def raw_schema(self) -> type[RawRecordT]:
        ...

    @abstractmethod
    def normalize(self, raw_records: list[RawRecordT]) -> list[NormalizedRecordT]:
        ...

    @abstractmethod
    def ingest(
        self,
        session: Session,
        fixture: Path | None = None,
        mock: bool = True,
    ) -> CollectorIngestResult:
        ...
