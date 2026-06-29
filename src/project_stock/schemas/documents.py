from __future__ import annotations

from datetime import datetime

from project_stock.schemas.common import SchemaBase


class RawDocumentCreate(SchemaBase):
    title: str
    body_text: str
    source_id: str | None = None
    url: str | None = None
    language: str = "en"
    published_at: datetime | None = None
    collected_at: datetime | None = None
    available_from: datetime | None = None
    checksum: str | None = None
    raw_path: str | None = None
    metadata_json: dict[str, object] | None = None
