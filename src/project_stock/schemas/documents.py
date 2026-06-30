from __future__ import annotations

from datetime import datetime

from project_stock.schemas.common import SchemaBase


class RawDocumentCreate(SchemaBase):
    title: str
    body_text: str
    source_id: str | None = None
    published_at: datetime | None = None
    available_from: datetime | None = None
