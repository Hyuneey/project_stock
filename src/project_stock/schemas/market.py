from __future__ import annotations

from datetime import datetime

from project_stock.schemas.common import SchemaBase


class MarketSeriesPoint(SchemaBase):
    symbol: str
    timestamp: datetime
    frequency: str
    value: float | None = None
    close: float | None = None
