from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field
from sqlalchemy.orm import Session

from project_stock.events.classifier import event_from_document
from project_stock.events.mapper import map_entities
from project_stock.playbooks.executor import execute_playbooks
from project_stock.playbooks.loader import load_playbook_dir
from project_stock.scenarios.loader import load_scenario_dir
from project_stock.scenarios.matcher import match_scenarios
from project_stock.schemas.common import SchemaBase
from project_stock.schemas.playbooks import PlaybookExecutionResult
from project_stock.schemas.scenarios import ScenarioMatchResult
from project_stock.schemas.scoring import EmergencyImpactInput, EmergencyImpactResult
from project_stock.scoring.emergency import score_emergency_impact
from project_stock.storage.repository import Repository
from project_stock.schemas.decisions import DecisionCreate
from project_stock.schemas.evidence import EvidenceCreate


class EmergencyCheckResult(SchemaBase):
    event_id: str
    event_summary: str
    emergency_score: EmergencyImpactResult
    matched_scenarios: list[ScenarioMatchResult]
    playbook_results: list[PlaybookExecutionResult]
    allowed_actions: list[str]
    forbidden_actions: list[str]
    thesis_action: str = "defer_to_close_review"
    evidence_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def run_intraday_emergency_check(
    event_input: dict[str, Any],
    metrics: dict[str, Any],
    exposure_context: dict[str, Any],
    db_session: Session,
    scenario_dir: Path | str = "scenarios",
    playbook_dir: Path | str = "playbooks",
) -> EmergencyCheckResult:
    repo = Repository(db_session)
    event = repo.add_event(event_from_document(event_input))
    repo.add_event_entities(
        event.event_id,
        map_entities(f"{event_input.get('title', '')} {event_input.get('body_text', '')} {event.summary}"),
    )

    scenarios = load_scenario_dir(scenario_dir)
    playbooks = load_playbook_dir(playbook_dir)
    all_matches = match_scenarios(scenarios, metrics)
    matched_scenarios = [match for match in all_matches if match.matched]

    emergency_input = EmergencyImpactInput(
        source_reliability=float(
            exposure_context.get("source_reliability", event.source_reliability)
        ),
        relevance=float(exposure_context.get("relevance", 4.0)),
        surprise=float(exposure_context.get("surprise", event.surprise_score)),
        transmission=float(exposure_context.get("transmission", 4.0)),
        market_confirmation=float(
            exposure_context.get("market_confirmation", event.market_confirmation_score)
        ),
        exposure=float(exposure_context.get("exposure", 4.0)),
    )
    emergency_score = score_emergency_impact(emergency_input)
    playbook_results = execute_playbooks(
        playbooks,
        matched_scenarios,
        emergency_score.emergency_level,
        confirmations=list(exposure_context.get("confirmations", [])),
    )

    evidence_ids: list[str] = []
    for match in matched_scenarios:
        repo.append_scenario_trigger(
            scenario_id=match.scenario_id,
            thesis_id=match.thesis_id,
            event_id=event.event_id,
            match_score=match.match_score,
            result_state="triggered",
            metadata_json=match.model_dump(mode="json"),
        )
        evidence = repo.append_evidence(
            EvidenceCreate(
                event_id=event.event_id,
                thesis_id=match.thesis_id,
                scenario_id=match.scenario_id,
                evidence_type="scenario_trigger",
                claim=f"{event.summary} matched {match.scenario_id}",
                supports_or_contradicts="contradicts",
                strength_score=min(5.0, emergency_score.eis / 500),
                metadata_json={"match_score": match.match_score},
            )
        )
        evidence_ids.append(evidence.evidence_id)

    allowed_actions = _unique(
        emergency_score.recommended_risk_actions
        + [
            action
            for result in playbook_results
            if result.activated
            for action in result.allowed_actions
        ]
    )
    forbidden_actions = _unique(
        emergency_score.forbidden_actions
        + [action for result in playbook_results for action in result.forbidden_actions]
    )
    first_match = matched_scenarios[0] if matched_scenarios else None
    decision = repo.append_decision(
        DecisionCreate(
            decision_type="emergency_risk_review",
            thesis_id=first_match.thesis_id if first_match else None,
            scenario_id=first_match.scenario_id if first_match else None,
            event_id=event.event_id,
            action="defer_to_close_review",
            rationale=(
                "Emergency sentinel returns risk actions and forbids direct trade execution; "
                f"level={emergency_score.emergency_level.value}."
            ),
            portfolio_impact=", ".join(allowed_actions),
            review_after="next close review",
            metadata_json={
                "allowed_actions": allowed_actions,
                "forbidden_actions": forbidden_actions,
                "matched_scenarios": [match.scenario_id for match in matched_scenarios],
            },
        )
    )
    return EmergencyCheckResult(
        event_id=event.event_id,
        event_summary=event.summary,
        emergency_score=emergency_score,
        matched_scenarios=matched_scenarios,
        playbook_results=playbook_results,
        allowed_actions=allowed_actions,
        forbidden_actions=forbidden_actions,
        evidence_ids=evidence_ids,
        decision_ids=[decision.decision_id],
    )
