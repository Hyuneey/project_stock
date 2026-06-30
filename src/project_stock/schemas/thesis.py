from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from project_stock.schemas.common import SchemaBase, ThesisStatus

ThesisState = ThesisStatus


class ThesisAssumption(SchemaBase):
    id: str
    statement: str


class ThesisStateHistoryItem(SchemaBase):
    date: date
    state: ThesisStatus
    reason: str


class ThesisDefinition(SchemaBase):
    thesis_id: str
    version: str
    status: ThesisStatus
    title: str
    created_at: date
    last_reviewed_at: date
    time_horizon: dict[str, str]
    core_claim: str
    beneficiaries: dict[str, list[str]] = Field(default_factory=dict)
    core_assumptions: list[ThesisAssumption]
    invalidation_conditions: list[str]
    state_history: list[ThesisStateHistoryItem]


class ThesisEvidenceSummary(SchemaBase):
    evidence_id: str
    event_id: str | None = None
    evidence_type: str
    claim: str
    supports_or_contradicts: str
    strength_score: float = Field(ge=0, le=5)
    created_at: datetime


class ThesisStateEvaluationInput(SchemaBase):
    thesis_id: str
    as_of: date
    previous_state: ThesisState | None = None
    lookback_days: int | None = Field(default=None, ge=1)
    minimum_evidence_count: int = Field(default=2, ge=0)
    big_flow_score: float | None = Field(default=None, ge=0, le=100)
    crowding_flag: bool = False


class ThesisStateEvaluationResult(SchemaBase):
    thesis_id: str
    previous_state: ThesisState | None = None
    proposed_state: ThesisState
    confidence_score: float = Field(ge=0, le=100)
    support_score: float = Field(ge=0)
    contradiction_score: float = Field(ge=0)
    neutral_score: float = Field(ge=0)
    net_evidence_score: float
    risk_score: float = Field(ge=0)
    big_flow_score: float | None = Field(default=None, ge=0, le=100)
    evidence_count: int = Field(ge=0)
    top_supporting_evidence: list[ThesisEvidenceSummary] = Field(default_factory=list)
    top_contradicting_evidence: list[ThesisEvidenceSummary] = Field(default_factory=list)
    transition_reasons: list[str] = Field(default_factory=list)
    recommended_review_action: str
    no_auto_trade: bool = True
    invalidation_warnings: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ThesisLifecycleTransition(SchemaBase):
    thesis_id: str
    previous_state: ThesisState | None = None
    proposed_state: ThesisState
    changed: bool
    reason: str
    snapshot_id: str | None = None


class ThesisReviewResult(SchemaBase):
    as_of: date
    evaluation_count: int = 0
    snapshot_count: int = 0
    skipped_duplicate_snapshot_count: int = 0
    memo_path: str | None = None
    evaluations: list[ThesisStateEvaluationResult] = Field(default_factory=list)
    transitions: list[ThesisLifecycleTransition] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    no_auto_trade: bool = True
