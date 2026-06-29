from __future__ import annotations

from pydantic import Field

from project_stock.schemas.common import SchemaBase


class EvidenceCreate(SchemaBase):
    evidence_id: str | None = None
    event_id: str | None = None
    thesis_id: str | None = None
    scenario_id: str | None = None
    evidence_type: str
    claim: str
    supports_or_contradicts: str = "neutral"
    strength_score: float = Field(default=1.0, ge=0, le=5)
    source_ids_json: list[str] | None = None
    metadata_json: dict[str, object] | None = None
