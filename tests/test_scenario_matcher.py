from __future__ import annotations

import pytest

from project_stock.playbooks.executor import execute_playbook
from project_stock.scenarios.matcher import evaluate_condition, match_scenario
from project_stock.schemas.common import EmergencyLevel
from project_stock.schemas.playbooks import PlaybookDefinition
from project_stock.schemas.scenarios import ScenarioDefinition, ScenarioMatchResult, TriggerCondition


def _scenario(trigger: dict[str, object]) -> ScenarioDefinition:
    return ScenarioDefinition.model_validate(
        {
            "scenario_id": "SCN_TEST",
            "thesis_id": "THESIS_TEST",
            "version": "1.0",
            "status": "active",
            "scenario_type": "test",
            "horizon": "1 day",
            "description": "test scenario",
            "trigger": trigger,
        }
    )


def test_all_of_requires_all_required_conditions():
    scenario = _scenario(
        {
            "mode": "all_of",
            "required": [
                {"metric": "A", "operator": ">", "value": 10},
                {"metric": "B", "operator": "<", "value": 5},
            ],
        }
    )

    assert match_scenario(scenario, {"A": 11, "B": 4}).matched is True
    result = match_scenario(scenario, {"A": 11, "B": 8})
    assert result.matched is False
    assert result.match_score == 50.0


def test_min_score_requires_threshold():
    scenario = _scenario(
        {
            "mode": "min_score",
            "min_match_score": 67,
            "optional": [
                {"metric": "A", "operator": ">", "value": 10},
                {"metric": "B", "operator": ">", "value": 10},
                {"metric": "C", "operator": ">", "value": 10},
            ],
        }
    )

    assert match_scenario(scenario, {"A": 11, "B": 9, "C": 11}).matched is False
    assert match_scenario(scenario, {"A": 11, "B": 12, "C": 11}).matched is True


def test_min_score_mode_requires_positive_threshold():
    with pytest.raises(ValueError, match="min_match_score"):
        _scenario(
            {
                "mode": "min_score",
                "optional": [{"metric": "A", "operator": ">", "value": 10}],
            }
        )


def test_missing_metric_does_not_crash():
    condition = TriggerCondition(metric="MISSING", operator=">", value=1)

    result = evaluate_condition(condition, {})

    assert result.matched is False
    assert result.reason == "metric_missing"


def test_none_value_does_not_crash():
    condition = TriggerCondition(metric="A", operator=">", value=1)

    result = evaluate_condition(condition, {"A": None})

    assert result.matched is False
    assert result.reason == "metric_null"


def test_boolean_string_false_is_not_coerced_to_true():
    condition = TriggerCondition(metric="FLAG", operator="==", value=True)

    result = evaluate_condition(condition, {"FLAG": "false"})

    assert result.matched is False
    assert result.reason == "condition_not_met"


def test_malformed_metric_input_returns_reason():
    condition = TriggerCondition(metric="A", operator=">", value=1)

    result = evaluate_condition(condition, {"A": {"bad": "value"}})

    assert result.matched is False
    assert result.reason == "invalid_type_coercion"


def test_unmatched_scenario_does_not_activate_playbook():
    playbook = PlaybookDefinition.model_validate(
        {
            "playbook_id": "PB_TEST",
            "version": "1.0",
            "linked_scenarios": ["SCN_TEST"],
            "activation": {"emergency_level_min": "E3", "required_confirmation": []},
            "allowed_actions": ["no_new_buy"],
            "forbidden_actions": ["llm_direct_trade_decision"],
        }
    )
    unmatched = ScenarioMatchResult(
        scenario_id="SCN_TEST",
        thesis_id="THESIS_TEST",
        mode="any_of",
        matched=False,
        match_score=0,
        matched_conditions=[],
        missing_conditions=[],
    )

    result = execute_playbook(playbook, [unmatched], EmergencyLevel.E3)

    assert result.activated is False
    assert result.allowed_actions == []
