from __future__ import annotations

from project_stock.schemas.common import SchemaBase


class IndicatorPoint(SchemaBase):
    indicator_id: str
    observation_period: str
    value: float
    available_from: str
