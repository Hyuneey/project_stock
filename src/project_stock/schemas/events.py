from __future__ import annotations

from datetime import datetime

from pydantic import Field

from project_stock.schemas.common import SchemaBase


class EventCreate(SchemaBase):
    event_id: str | None = None
    event_type: str
    event_time: datetime
    first_seen_at: datetime | None = None
    available_from: datetime
    summary: str
    source_reliability: float = Field(default=3.0, ge=0, le=5)
    surprise_score: float = Field(default=3.0, ge=0, le=5)
    persistence_score: float = Field(default=3.0, ge=0, le=5)
    market_confirmation_score: float = Field(default=3.0, ge=0, le=5)
    status: str = "new"
    metadata_json: dict[str, object] | None = None
