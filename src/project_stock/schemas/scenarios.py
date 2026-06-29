from __future__ import annotations

from typing import Literal

from pydantic import Field

from project_stock.schemas.common import SchemaBase, ScenarioStatus

ComparisonOperator = Literal[">", ">=", "<", "<=", "==", "!="]


class TriggerCondition(SchemaBase):
    metric: str
    operator: ComparisonOperator
    value: float | int | str | bool


class TriggerGroup(SchemaBase):
    any_of: list[TriggerCondition] = Field(default_factory=list)


class ScenarioDefinition(SchemaBase):
    scenario_id: str
    thesis_id: str
    version: str
    status: ScenarioStatus
    scenario_type: str
    horizon: str
    description: str
    trigger: TriggerGroup
    expected_path: dict[str, str] = Field(default_factory=dict)
    risk_action: list[str] = Field(default_factory=list)
    thesis_action: dict[str, object] = Field(default_factory=dict)
    expiry: dict[str, object] = Field(default_factory=dict)


class ConditionEvaluation(SchemaBase):
    metric: str
    operator: ComparisonOperator
    expected: float | int | str | bool
    actual: float | int | str | bool | None = None
    matched: bool
    reason: str


class ScenarioMatchResult(SchemaBase):
    scenario_id: str
    thesis_id: str
    matched: bool
    match_score: float
    matched_conditions: list[ConditionEvaluation]
    missing_conditions: list[ConditionEvaluation]
