from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from project_stock.ingest.base import CollectorIngestResult, OfficialCollector
from project_stock.ingest.sources import register_official_sources
from project_stock.normalize.time import safe_available_from
from project_stock.schemas.common import SchemaBase
from project_stock.schemas.documents import RawDocumentCreate
from project_stock.storage.repository import Repository


class DartDisclosureRecord(SchemaBase):
    rcept_no: str
    corp_code: str
    stock_code: str | None = None
    report_name: str
    received_at: datetime
    title: str | None = None
    body_text: str | None = None
    summary: str | None = None
    collected_at: datetime | None = None
    available_from: datetime | None = None
    source_id: str = "OPEN_DART"


class OpenDartCollector(OfficialCollector[DartDisclosureRecord, RawDocumentCreate]):
    collector_id = "opendart"
    source_id = "OPEN_DART"
    api_key_env_var = "DART_API_KEY"

    def raw_schema(self) -> type[DartDisclosureRecord]:
        return DartDisclosureRecord

    def normalize(self, raw_records: list[DartDisclosureRecord]) -> list[RawDocumentCreate]:
        documents: list[RawDocumentCreate] = []
        for record in raw_records:
            collected_at = record.collected_at or record.received_at
            documents.append(
                RawDocumentCreate(
                    source_id=self.source_id,
                    title=record.title or record.report_name,
                    body_text=record.body_text or record.summary or "",
                    language="ko",
                    published_at=record.received_at,
                    collected_at=collected_at,
                    available_from=safe_available_from(
                        record.available_from,
                        record.received_at,
                        collected_at,
                    ),
                    metadata_json={
                        "rcept_no": record.rcept_no,
                        "corp_code": record.corp_code,
                        "stock_code": record.stock_code,
                        "report_name": record.report_name,
                    },
                )
            )
        return documents

    def ingest(
        self,
        session: Session,
        fixture: Path | None = None,
        mock: bool = True,
    ) -> CollectorIngestResult:
        register_official_sources(session)
        repo = Repository(session)
        records = self.normalize(self.fetch_raw(fixture=fixture, mock=mock))
        inserted_ids = [repo.add_raw_document_create(record).doc_id for record in records]
        return CollectorIngestResult(
            collector_id=self.collector_id,
            source_id=self.source_id,
            inserted_count=len(inserted_ids),
            record_ids=inserted_ids,
        )
