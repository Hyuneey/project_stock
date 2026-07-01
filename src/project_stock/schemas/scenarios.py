from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from project_stock.schemas.common import SchemaBase, ScenarioStatus

ComparisonOperator = Literal[">", ">=", "<", "<=", "==", "!="]
TriggerMode = Literal["any_of", "all_of", "min_score"]


def _merge_conditions(*groups: list["TriggerCondition"]) -> list["TriggerCondition"]:
    merged: list[TriggerCondition] = []
    for group in groups:
        for condition in group:
            if condition not in merged:
                merged.append(condition)
    return merged


class TriggerCondition(SchemaBase):
    metric: str
    operator: ComparisonOperator
    value: bool | float | int | str


class TriggerGroup(SchemaBase):
    mode: TriggerMode = "any_of"
    any_of: list[TriggerCondition] = Field(default_factory=list)
    all_of: list[TriggerCondition] = Field(default_factory=list)
    required: list[TriggerCondition] = Field(default_factory=list)
    optional: list[TriggerCondition] = Field(default_factory=list)
    min_match_score: float = Field(default=0.0, ge=0, le=100)

    @model_validator(mode="after")
    def validate_min_score_threshold(self) -> "TriggerGroup":
        if self.mode == "min_score" and self.min_match_score <= 0:
            raise ValueError("min_score mode requires min_match_score greater than 0")
        return self

    @property
    def required_conditions(self) -> list[TriggerCondition]:
        return _merge_conditions(self.required, self.all_of)

    @property
    def optional_conditions(self) -> list[TriggerCondition]:
        return _merge_conditions(self.optional, self.any_of)

    @property
    def all_conditions(self) -> list[TriggerCondition]:
        return self.required_conditions + self.optional_conditions


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
    evidence_to_watch: list[str] = Field(default_factory=list)
    risk_action: list[str] = Field(default_factory=list)
    thesis_action: dict[str, object] = Field(default_factory=dict)
    invalidation: dict[str, object] = Field(default_factory=dict)
    resolution: dict[str, object] = Field(default_factory=dict)
    expiry: dict[str, object] = Field(default_factory=dict)
    no_auto_trade: bool = True


class ConditionEvaluation(SchemaBase):
    metric: str
    operator: ComparisonOperator
    expected: bool | float | int | str
    actual: object | None = None
    matched: bool
    reason: str


class ScenarioMatchResult(SchemaBase):
    scenario_id: str
    thesis_id: str
    mode: TriggerMode
    matched: bool
    match_score: float
    matched_conditions: list[ConditionEvaluation]
    missing_conditions: list[ConditionEvaluation]
