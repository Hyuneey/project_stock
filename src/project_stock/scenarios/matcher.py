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


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
        raise ValueError("invalid_boolean_string")
    if isinstance(value, int) and not isinstance(value, bool):
        if value in {0, 1}:
            return bool(value)
        raise ValueError("invalid_boolean_integer")
    raise TypeError("invalid_boolean_type")


def _coerce_pair(actual: object, expected: object) -> tuple[object, object]:
    if isinstance(expected, bool):
        return _coerce_bool(actual), expected
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
    metric_value = metrics[condition.metric]
    if metric_value is None:
        return ConditionEvaluation(
            metric=condition.metric,
            operator=condition.operator,
            expected=condition.value,
            actual=None,
            matched=False,
            reason="metric_null",
        )
    try:
        actual, expected = _coerce_pair(metric_value, condition.value)
        matched = OPERATORS[condition.operator](actual, expected)
    except (TypeError, ValueError):
        return ConditionEvaluation(
            metric=condition.metric,
            operator=condition.operator,
            expected=condition.value,
            actual=metric_value,
            matched=False,
            reason="invalid_type_coercion",
        )
    except Exception as exc:
        return ConditionEvaluation(
            metric=condition.metric,
            operator=condition.operator,
            expected=condition.value,
            actual=metric_value,
            matched=False,
            reason=f"evaluation_error:{exc.__class__.__name__}",
        )
    return ConditionEvaluation(
        metric=condition.metric,
        operator=condition.operator,
        expected=condition.value,
        actual=metric_value,
        matched=matched,
        reason="matched" if matched else "condition_not_met",
    )


def _matches_trigger(
    mode: str,
    required_evaluations: list[ConditionEvaluation],
    optional_evaluations: list[ConditionEvaluation],
    match_score: float,
    min_match_score: float,
) -> bool:
    required_ok = all(evaluation.matched for evaluation in required_evaluations)
    if required_evaluations and not required_ok:
        return False

    evaluations = required_evaluations + optional_evaluations
    if not evaluations:
        return False

    threshold_ok = match_score >= min_match_score
    if mode == "all_of":
        return required_ok and threshold_ok
    if mode == "min_score":
        return required_ok and threshold_ok
    optional_ok = any(evaluation.matched for evaluation in optional_evaluations)
    if required_evaluations and not optional_evaluations:
        return required_ok and threshold_ok
    return optional_ok and threshold_ok


def match_scenario(
    scenario: ScenarioDefinition,
    metrics: dict[str, object],
) -> ScenarioMatchResult:
    required_evaluations = [
        evaluate_condition(condition, metrics) for condition in scenario.trigger.required_conditions
    ]
    optional_evaluations = [
        evaluate_condition(condition, metrics) for condition in scenario.trigger.optional_conditions
    ]
    evaluations = required_evaluations + optional_evaluations
    matched_conditions = [evaluation for evaluation in evaluations if evaluation.matched]
    missing_conditions = [evaluation for evaluation in evaluations if not evaluation.matched]
    match_score = round((len(matched_conditions) / len(evaluations) * 100) if evaluations else 0.0, 2)
    matched = _matches_trigger(
        scenario.trigger.mode,
        required_evaluations,
        optional_evaluations,
        match_score,
        scenario.trigger.min_match_score,
    )
    return ScenarioMatchResult(
        scenario_id=scenario.scenario_id,
        thesis_id=scenario.thesis_id,
        mode=scenario.trigger.mode,
        matched=matched,
        match_score=match_score,
        matched_conditions=matched_conditions,
        missing_conditions=missing_conditions,
    )


def match_scenarios(
    scenarios: list[ScenarioDefinition],
    metrics: dict[str, object],
) -> list[ScenarioMatchResult]:
    return [match_scenario(scenario, metrics) for scenario in scenarios]
