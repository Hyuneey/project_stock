from __future__ import annotations

from datetime import datetime

from project_stock.schemas.common import SchemaBase


class MarketSeriesPoint(SchemaBase):
    symbol: str
    timestamp: datetime
    frequency: str
    value: float | None = None
    close: float | None = None


class MarketTimeSeriesCreate(SchemaBase):
    symbol: str
    timestamp: datetime
    frequency: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    value: float | None = None
    source_id: str | None = None
    collected_at: datetime | None = None
    available_from: datetime | None = None
    adjusted_flag: bool = False
    metadata_json: dict[str, object] | None = None
