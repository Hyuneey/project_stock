from __future__ import annotations

from pydantic import Field

from project_stock.schemas.common import EmergencyLevel, SchemaBase


class BigFlowScoreInput(SchemaBase):
    thesis_id: str
    secular: float = Field(ge=0, le=100)
    industry: float = Field(ge=0, le=100)
    earnings: float = Field(ge=0, le=100)
    valuation: float = Field(ge=0, le=100)
    market: float = Field(ge=0, le=100)
    macro: float = Field(ge=0, le=100)
    risk_penalty: float = Field(ge=0, le=100)


class BigFlowScoreResult(SchemaBase):
    thesis_id: str
    score: float
    state_hint: str
    components: dict[str, float]
    risk_penalty: float
    rationale: str


class EmergencyImpactInput(SchemaBase):
    source_reliability: float = Field(ge=0, le=5)
    relevance: float = Field(ge=0, le=5)
    surprise: float = Field(ge=0, le=5)
    transmission: float = Field(ge=0, le=5)
    market_confirmation: float = Field(ge=0, le=5)
    exposure: float = Field(ge=0, le=5)


class EmergencyImpactResult(SchemaBase):
    eis: float
    emergency_level: EmergencyLevel
    recommended_risk_actions: list[str]
    forbidden_actions: list[str]
    requires_close_review: bool


class ThesisImpactInput(SchemaBase):
    relevance: float = Field(ge=0, le=5)
    surprise: float = Field(ge=0, le=5)
    transmission: float = Field(ge=0, le=5)
    persistence: float = Field(ge=0, le=5)
    market_confirmation: float = Field(ge=0, le=5)
    priced_in_penalty: float = Field(default=0, ge=0, le=100)


class ThesisImpactResult(SchemaBase):
    tis: float
    impact_level: str
    rationale: str
