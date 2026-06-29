from __future__ import annotations

from datetime import datetime

from project_stock.schemas.common import SchemaBase


class IndicatorPoint(SchemaBase):
    indicator_id: str
    observation_period: str
    value: float
    available_from: str


class IndicatorObservationCreate(SchemaBase):
    indicator_id: str
    observation_period: str
    value: float
    unit: str | None = None
    release_at: datetime | None = None
    collected_at: datetime | None = None
    available_from: datetime | None = None
    vintage_date: str | None = None
    source_id: str | None = None
    consensus: float | None = None
    previous: float | None = None
    revised_previous: float | None = None
    surprise_value: float | None = None
    surprise_z: float | None = None
    metadata_json: dict[str, object] | None = None
