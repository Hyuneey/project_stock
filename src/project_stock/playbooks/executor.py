from __future__ import annotations

from project_stock.schemas.common import EMERGENCY_LEVEL_ORDER, EmergencyLevel
from project_stock.schemas.playbooks import PlaybookDefinition, PlaybookExecutionResult
from project_stock.schemas.scenarios import ScenarioMatchResult


def execute_playbook(
    playbook: PlaybookDefinition,
    matched_scenarios: list[ScenarioMatchResult],
    emergency_level: EmergencyLevel,
    confirmations: list[str] | None = None,
) -> PlaybookExecutionResult:
    confirmations = confirmations or []
    matched_ids = {match.scenario_id for match in matched_scenarios if match.matched}
    scenario_linked = bool(matched_ids.intersection(playbook.linked_scenarios))
    level_ok = (
        EMERGENCY_LEVEL_ORDER[emergency_level]
        >= EMERGENCY_LEVEL_ORDER[playbook.activation.emergency_level_min]
    )
    confirmations_ok = all(item in confirmations for item in playbook.activation.required_confirmation)
    activated = scenario_linked and level_ok and confirmations_ok
    if activated:
        rationale = (
            f"{emergency_level.value} meets playbook threshold and linked scenario matched; "
            "returning risk-management actions only."
        )
        allowed_actions = playbook.allowed_actions
    else:
        rationale = "Activation criteria not met; no playbook risk action is enabled."
        allowed_actions = []
    return PlaybookExecutionResult(
        playbook_id=playbook.playbook_id,
        activated=activated,
        allowed_actions=allowed_actions,
        forbidden_actions=playbook.forbidden_actions,
        rationale=rationale,
    )


def execute_playbooks(
    playbooks: list[PlaybookDefinition],
    matched_scenarios: list[ScenarioMatchResult],
    emergency_level: EmergencyLevel,
    confirmations: list[str] | None = None,
) -> list[PlaybookExecutionResult]:
    return [
        execute_playbook(playbook, matched_scenarios, emergency_level, confirmations)
        for playbook in playbooks
    ]
