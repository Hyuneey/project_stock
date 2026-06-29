from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from project_stock.schemas.common import SchemaBase

EvidenceStance = Literal["supports", "contradicts", "neutral"]


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


class ThesisRelevanceResult(SchemaBase):
    event_id: str
    thesis_id: str
    relevance_score: float = Field(ge=0, le=100)
    relevance_reasons: list[str]
    matched_entity_ids: list[str]
    matched_keywords: list[str]


class EvidenceCandidate(SchemaBase):
    candidate_id: str
    event_id: str
    thesis_id: str
    scenario_id: str | None = None
    evidence_type: str
    claim: str
    supports_or_contradicts: EvidenceStance
    strength_score: float = Field(ge=0, le=5)
    relevance_score: float = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=100)
    source_event_type: str
    source_entity_ids: list[str]
    created_at: datetime
    metadata_json: dict[str, object] | None = None


class EvidenceGenerationResult(SchemaBase):
    candidate_count: int = 0
    appended_count: int = 0
    skipped_count: int = 0
    candidates: list[EvidenceCandidate] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    counts_by_thesis_id: dict[str, int] = Field(default_factory=dict)
    counts_by_stance: dict[str, int] = Field(default_factory=dict)
