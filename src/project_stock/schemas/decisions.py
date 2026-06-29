from __future__ import annotations

from datetime import datetime

from project_stock.schemas.common import SchemaBase


class DecisionCreate(SchemaBase):
    decision_id: str | None = None
    timestamp: datetime | None = None
    decision_type: str
    thesis_id: str | None = None
    scenario_id: str | None = None
    event_id: str | None = None
    action: str
    rationale: str
    portfolio_impact: str | None = None
    review_after: str | None = None
    metadata_json: dict[str, object] | None = None
