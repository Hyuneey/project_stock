from __future__ import annotations

import operator
from typing import Callable

from project_stock.schemas.scenarios import (
    ConditionEvaluation,
    ScenarioDefinition,
    ScenarioMatchResult,
    TriggerCondition,
)

OPERATORS: dict[str, Callable[[object, object], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def _coerce_pair(actual: object, expected: object) -> tuple[object, object]:
    if isinstance(expected, bool):
        return bool(actual), expected
    if isinstance(expected, (int, float)):
        return float(actual), float(expected)
    return str(actual), str(expected)


def evaluate_condition(
    condition: TriggerCondition,
    metrics: dict[str, object],
) -> ConditionEvaluation:
    if condition.metric not in metrics:
        return ConditionEvaluation(
            metric=condition.metric,
            operator=condition.operator,
            expected=condition.value,
            actual=None,
            matched=False,
            reason="metric_missing",
        )
    actual, expected = _coerce_pair(metrics[condition.metric], condition.value)
    matched = OPERATORS[condition.operator](actual, expected)
    return ConditionEvaluation(
        metric=condition.metric,
        operator=condition.operator,
        expected=condition.value,
        actual=metrics[condition.metric],
        matched=matched,
        reason="matched" if matched else "condition_not_met",
    )


def match_scenario(
    scenario: ScenarioDefinition,
    metrics: dict[str, object],
) -> ScenarioMatchResult:
    conditions = scenario.trigger.any_of
    evaluations = [evaluate_condition(condition, metrics) for condition in conditions]
    matched_conditions = [evaluation for evaluation in evaluations if evaluation.matched]
    missing_conditions = [evaluation for evaluation in evaluations if not evaluation.matched]
    match_score = round((len(matched_conditions) / len(conditions) * 100) if conditions else 0.0, 2)
    return ScenarioMatchResult(
        scenario_id=scenario.scenario_id,
        thesis_id=scenario.thesis_id,
        matched=bool(matched_conditions),
        match_score=match_score,
        matched_conditions=matched_conditions,
        missing_conditions=missing_conditions,
    )


def match_scenarios(
    scenarios: list[ScenarioDefinition],
    metrics: dict[str, object],
) -> list[ScenarioMatchResult]:
    return [match_scenario(scenario, metrics) for scenario in scenarios]
