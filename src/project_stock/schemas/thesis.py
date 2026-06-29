from __future__ import annotations

from datetime import date

from pydantic import Field

from project_stock.schemas.common import SchemaBase, ThesisStatus


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
