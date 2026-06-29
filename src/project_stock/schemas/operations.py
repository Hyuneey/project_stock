from __future__ import annotations

from datetime import date

from pydantic import Field

from project_stock.schemas.common import EmergencyLevel, SchemaBase
from project_stock.schemas.playbooks import PlaybookExecutionResult
from project_stock.schemas.scenarios import ScenarioMatchResult


class DailyReviewResult(SchemaBase):
    as_of: date
    inserted_raw_counts: dict[str, int] = Field(default_factory=dict)
    inserted_event_count: int = 0
    mapped_entity_count: int = 0
    evidence_candidate_count: int = 0
    appended_evidence_count: int = 0
    skipped_duplicate_evidence_count: int = 0
    scenario_match_count: int = 0
    decision_log_count: int = 0
    memo_path: str | None = None
    warnings: list[str] = Field(default_factory=list)
    new_events_by_type: dict[str, int] = Field(default_factory=dict)
    evidence_counts_by_thesis: dict[str, int] = Field(default_factory=dict)
    evidence_counts_by_stance: dict[str, int] = Field(default_factory=dict)
    matched_scenarios: list[ScenarioMatchResult] = Field(default_factory=list)
    playbook_results: list[PlaybookExecutionResult] = Field(default_factory=list)


class IntradayReviewResult(SchemaBase):
    event_id: str
    emergency_level: EmergencyLevel
    emergency_score: float
    matched_scenarios: list[ScenarioMatchResult] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    appended_evidence_count: int = 0
    decision_log_count: int = 0
    memo_path: str | None = None
    thesis_action: str = "defer_to_close_review"
    evidence_candidate_count: int = 0
    skipped_duplicate_evidence_count: int = 0
    playbook_results: list[PlaybookExecutionResult] = Field(default_factory=list)
