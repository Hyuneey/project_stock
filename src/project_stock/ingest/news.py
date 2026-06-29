from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from project_stock.ingest.base import CollectorIngestResult, OfficialCollector
from project_stock.ingest.sources import register_official_sources
from project_stock.normalize.dedupe import text_checksum
from project_stock.normalize.time import safe_available_from
from project_stock.schemas.common import SchemaBase
from project_stock.schemas.documents import RawDocumentCreate
from project_stock.storage.repository import Repository


class NewsRssRecord(SchemaBase):
    title: str
    body_text: str
    url: str | None = None
    published_at: datetime
    collected_at: datetime | None = None
    available_from: datetime | None = None
    language: str = "en"
    checksum: str | None = None
    source_id: str = "NEWS_RSS"


class NewsRssCollector(OfficialCollector[NewsRssRecord, RawDocumentCreate]):
    collector_id = "news_rss"
    source_id = "NEWS_RSS"
    api_key_env_var = "NEWS_API_KEY"

    def raw_schema(self) -> type[NewsRssRecord]:
        return NewsRssRecord

    def normalize(self, raw_records: list[NewsRssRecord]) -> list[RawDocumentCreate]:
        documents: list[RawDocumentCreate] = []
        for record in raw_records:
            collected_at = record.collected_at or record.published_at
            checksum = record.checksum or text_checksum(
                f"{record.title}|{record.url or ''}|{record.published_at.isoformat()}"
            )
            documents.append(
                RawDocumentCreate(
                    source_id=self.source_id,
                    title=record.title,
                    body_text=record.body_text,
                    url=record.url,
                    language=record.language,
                    published_at=record.published_at,
                    collected_at=collected_at,
                    available_from=safe_available_from(
                        record.available_from,
                        record.published_at,
                        collected_at,
                    ),
                    checksum=checksum,
                    metadata_json={"collector": self.collector_id},
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
        inserted_ids: list[str] = []
        skipped_count = 0
        for record in records:
            if record.checksum and repo.find_raw_document_by_checksum(record.checksum, self.source_id):
                skipped_count += 1
                continue
            inserted_ids.append(repo.add_raw_document_create(record).doc_id)
        return CollectorIngestResult(
            collector_id=self.collector_id,
            source_id=self.source_id,
            inserted_count=len(inserted_ids),
            skipped_count=skipped_count,
            record_ids=inserted_ids,
        )
