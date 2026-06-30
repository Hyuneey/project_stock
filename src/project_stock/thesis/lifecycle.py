from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time
import hashlib
import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from project_stock.db.models import EvidenceLedger, ThesisStateSnapshot
from project_stock.events.normalization import normalize_events
from project_stock.evidence.generation import generate_and_append_evidence
from project_stock.ingest.sources import register_official_sources
from project_stock.operations.review_loop import (
    DEFAULT_OFFICIAL_FIXTURE_DIR,
    ingest_official_mock_bundle_idempotent,
)
from project_stock.reports.render import render_report
from project_stock.schemas.common import ThesisStatus
from project_stock.schemas.thesis import (
    ThesisDefinition,
    ThesisEvidenceSummary,
    ThesisLifecycleTransition,
    ThesisReviewResult,
    ThesisState,
    ThesisStateEvaluationInput,
    ThesisStateEvaluationResult,
)
from project_stock.storage.repository import Repository
from project_stock.thesis.loader import load_thesis_dir

DEFAULT_MEMO_DIR = Path("data/processed")
NO_AUTO_TRADE_DISCLAIMER = (
    "No auto-trade: thesis lifecycle states are review recommendations only and "
    "do not authorize broker order execution or LLM-directed buy/sell decisions."
)


def latest_state_reason(thesis: ThesisDefinition) -> str:
    if not thesis.state_history:
        return "No state history recorded."
    latest = sorted(thesis.state_history, key=lambda item: item.date)[-1]
    return latest.reason


def _as_of_datetime(as_of: date) -> datetime:
    return datetime.combine(as_of, time.min, tzinfo=UTC)


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-zA-Z0-9_]+", text.lower())
        if len(token) >= 4
    }


def _latest_snapshot_state(
    repo: Repository,
    thesis: ThesisDefinition,
    as_of: date,
) -> ThesisState | None:
    snapshots = [
        snapshot
        for snapshot in repo.list_thesis_snapshots(thesis.thesis_id)
        if (_as_date(snapshot.as_of) or as_of) < as_of
    ]
    snapshot = snapshots[-1] if snapshots else None
    if snapshot is not None:
        return ThesisStatus(snapshot.status)
    return thesis.status


def _evidence_summary(evidence: EvidenceLedger) -> ThesisEvidenceSummary:
    return ThesisEvidenceSummary(
        evidence_id=evidence.evidence_id,
        event_id=evidence.event_id,
        evidence_type=evidence.evidence_type,
        claim=evidence.claim,
        supports_or_contradicts=evidence.supports_or_contradicts,
        strength_score=evidence.strength_score,
        created_at=evidence.created_at,
    )


def _recency_weight(evidence: EvidenceLedger, as_of: date) -> float:
    evidence_date = _as_date(evidence.created_at)
    if evidence_date is None:
        return 1.0
    age_days = max(0, (as_of - evidence_date).days)
    if age_days <= 7:
        return 1.15
    if age_days <= 30:
        return 1.0
    if age_days <= 90:
        return 0.85
    return 0.70


def _within_lookback(
    evidence: EvidenceLedger,
    as_of: date,
    lookback_days: int | None,
) -> bool:
    if lookback_days is None:
        return True
    evidence_date = _as_date(evidence.created_at)
    if evidence_date is None:
        return True
    return 0 <= (as_of - evidence_date).days <= lookback_days


def _evidence_text(evidence: EvidenceLedger) -> str:
    metadata = evidence.metadata_json or {}
    source_metadata = metadata.get("source_event_metadata", {})
    return " ".join(
        [
            evidence.evidence_type,
            evidence.claim,
            evidence.supports_or_contradicts,
            str(metadata.get("source_event_type", "")),
            json.dumps(source_metadata, sort_keys=True, default=str),
        ]
    ).lower()


def _invalidation_warnings(
    thesis: ThesisDefinition,
    evidence_rows: list[EvidenceLedger],
) -> list[str]:
    warnings: list[str] = []
    for condition in thesis.invalidation_conditions:
        condition_tokens = _tokens(condition)
        if not condition_tokens:
            continue
        for evidence in evidence_rows:
            text_tokens = _tokens(_evidence_text(evidence))
            overlap = condition_tokens.intersection(text_tokens)
            if len(overlap) >= max(1, min(2, len(condition_tokens))):
                warnings.append(f"{condition}: {evidence.evidence_id}")
                break
    return warnings


def _score_evidence(
    evidence_rows: list[EvidenceLedger],
    as_of: date,
) -> tuple[float, float, float]:
    support_score = 0.0
    contradiction_score = 0.0
    neutral_score = 0.0
    for evidence in evidence_rows:
        weighted = round(float(evidence.strength_score) * _recency_weight(evidence, as_of), 4)
        if evidence.supports_or_contradicts == "supports":
            support_score += weighted
        elif evidence.supports_or_contradicts == "contradicts":
            contradiction_score += weighted
        else:
            neutral_score += weighted * 0.35
    return round(support_score, 2), round(contradiction_score, 2), round(neutral_score, 2)


def _confidence_score(evidence_count: int, net_evidence_score: float, risk_score: float) -> float:
    raw = 25.0 + min(45.0, evidence_count * 8.0) + min(25.0, abs(net_evidence_score) * 3.0)
    raw -= min(15.0, risk_score)
    return round(max(0.0, min(100.0, raw)), 2)


def _top_evidence(
    evidence_rows: list[EvidenceLedger],
    stance: str,
) -> list[ThesisEvidenceSummary]:
    filtered = [
        evidence
        for evidence in evidence_rows
        if evidence.supports_or_contradicts == stance
    ]
    ordered = sorted(filtered, key=lambda item: (item.strength_score, item.created_at), reverse=True)
    return [_evidence_summary(evidence) for evidence in ordered[:3]]


def _recommended_review_action(state: ThesisState) -> str:
    if state == ThesisStatus.invalidated:
        return "review_invalidation_and_archive_decision"
    if state == ThesisStatus.suspended:
        return "suspend_new_risk_and_review_at_close"
    if state == ThesisStatus.deteriorating:
        return "review_deterioration_evidence"
    if state == ThesisStatus.crowded:
        return "review_crowding_and_risk_budget"
    if state == ThesisStatus.core_overweight:
        return "review_conviction_and_risk_limits"
    if state == ThesisStatus.active:
        return "continue_active_monitoring"
    if state == ThesisStatus.archived:
        return "record_only_archived"
    return "continue_watchlist_review"


def _transition_state(
    evaluation_input: ThesisStateEvaluationInput,
    support_score: float,
    contradiction_score: float,
    neutral_score: float,
    invalidation_warnings: list[str],
    evidence_count: int,
) -> tuple[ThesisState, list[str]]:
    previous_state = evaluation_input.previous_state or ThesisStatus.candidate
    net = support_score - contradiction_score
    risk_score = contradiction_score + min(8.0, len(invalidation_warnings) * 3.0)
    reasons: list[str] = []

    if previous_state == ThesisStatus.archived:
        return ThesisStatus.archived, ["archived_state_is_terminal"]
    if previous_state == ThesisStatus.invalidated:
        return ThesisStatus.invalidated, ["invalidated_state_requires_explicit_archive"]

    if invalidation_warnings and (contradiction_score >= 8.0 or len(invalidation_warnings) >= 2):
        reasons.append("invalidation_conditions_confirmed")
        return ThesisStatus.invalidated, reasons
    if previous_state in {ThesisStatus.deteriorating, ThesisStatus.suspended} and contradiction_score >= 7.0:
        reasons.append("persistent_contradiction_after_deterioration")
        return ThesisStatus.suspended, reasons
    if previous_state in {ThesisStatus.watch, ThesisStatus.active} and contradiction_score >= 6.0:
        reasons.append("contradiction_score_above_deterioration_threshold")
        return ThesisStatus.deteriorating, reasons
    if invalidation_warnings:
        reasons.append("invalidation_keywords_detected")
        return ThesisStatus.deteriorating, reasons
    if previous_state == ThesisStatus.active and support_score >= 9.0:
        if evaluation_input.crowding_flag or risk_score >= 5.0:
            reasons.append("supportive_but_crowding_or_risk_high")
            return ThesisStatus.crowded, reasons
        if evaluation_input.big_flow_score is not None and evaluation_input.big_flow_score >= 80:
            reasons.append("very_strong_support_and_big_flow")
            return ThesisStatus.core_overweight, reasons
    if previous_state == ThesisStatus.watch and support_score >= 6.0 and contradiction_score <= 3.0:
        reasons.append("support_score_strong_and_contradiction_low")
        return ThesisStatus.active, reasons
    if (
        previous_state == ThesisStatus.candidate
        and evidence_count >= evaluation_input.minimum_evidence_count
        and net >= 1.0
    ):
        reasons.append("candidate_has_positive_evidence")
        return ThesisStatus.watch, reasons
    if support_score == 0 and contradiction_score == 0:
        reasons.append("no_directional_evidence")
        if previous_state == ThesisStatus.candidate:
            return ThesisStatus.candidate, reasons
        return ThesisStatus.watch, reasons
    reasons.append("state_unchanged_by_rules")
    return previous_state, reasons


def evaluate_thesis_state(
    thesis: ThesisDefinition,
    evidence_rows: list[EvidenceLedger],
    evaluation_input: ThesisStateEvaluationInput,
) -> ThesisStateEvaluationResult:
    evidence_rows = [
        evidence
        for evidence in evidence_rows
        if evidence.thesis_id == thesis.thesis_id
        and _within_lookback(evidence, evaluation_input.as_of, evaluation_input.lookback_days)
    ]
    support_score, contradiction_score, neutral_score = _score_evidence(
        evidence_rows,
        evaluation_input.as_of,
    )
    invalidation_warnings = _invalidation_warnings(thesis, evidence_rows)
    net_evidence_score = round(support_score - contradiction_score, 2)
    risk_score = round(contradiction_score + min(8.0, len(invalidation_warnings) * 3.0), 2)
    proposed_state, transition_reasons = _transition_state(
        evaluation_input,
        support_score,
        contradiction_score,
        neutral_score,
        invalidation_warnings,
        len(evidence_rows),
    )
    return ThesisStateEvaluationResult(
        thesis_id=thesis.thesis_id,
        previous_state=evaluation_input.previous_state,
        proposed_state=proposed_state,
        confidence_score=_confidence_score(len(evidence_rows), net_evidence_score, risk_score),
        support_score=support_score,
        contradiction_score=contradiction_score,
        neutral_score=neutral_score,
        net_evidence_score=net_evidence_score,
        risk_score=risk_score,
        big_flow_score=evaluation_input.big_flow_score,
        evidence_count=len(evidence_rows),
        top_supporting_evidence=_top_evidence(evidence_rows, "supports"),
        top_contradicting_evidence=_top_evidence(evidence_rows, "contradicts"),
        transition_reasons=transition_reasons,
        recommended_review_action=_recommended_review_action(proposed_state),
        invalidation_warnings=invalidation_warnings,
        evidence_ids=[evidence.evidence_id for evidence in evidence_rows],
    )


def _evaluation_fingerprint(evaluation: ThesisStateEvaluationResult) -> str:
    payload = {
        "thesis_id": evaluation.thesis_id,
        "previous_state": evaluation.previous_state.value if evaluation.previous_state else None,
        "proposed_state": evaluation.proposed_state.value,
        "support_score": evaluation.support_score,
        "contradiction_score": evaluation.contradiction_score,
        "neutral_score": evaluation.neutral_score,
        "net_evidence_score": evaluation.net_evidence_score,
        "risk_score": evaluation.risk_score,
        "big_flow_score": evaluation.big_flow_score,
        "evidence_ids": sorted(evaluation.evidence_ids),
        "invalidation_warnings": sorted(evaluation.invalidation_warnings),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _duplicate_snapshot(
    snapshots: list[ThesisStateSnapshot],
    thesis_id: str,
    as_of: date,
    fingerprint: str,
) -> ThesisStateSnapshot | None:
    for snapshot in snapshots:
        if snapshot.thesis_id != thesis_id:
            continue
        if _as_date(snapshot.as_of) != as_of:
            continue
        metadata = snapshot.metadata_json or {}
        if metadata.get("evaluation_fingerprint") == fingerprint:
            return snapshot
    return None


def _snapshot_reason(evaluation: ThesisStateEvaluationResult) -> str:
    reasons = ", ".join(evaluation.transition_reasons) or "state evaluated"
    return (
        f"Proposed {evaluation.proposed_state.value}: net={evaluation.net_evidence_score}, "
        f"support={evaluation.support_score}, contradiction={evaluation.contradiction_score}; {reasons}."
    )


def _append_evaluation_snapshot(
    repo: Repository,
    thesis: ThesisDefinition,
    evaluation: ThesisStateEvaluationResult,
    as_of: date,
    force: bool,
) -> tuple[ThesisLifecycleTransition, bool]:
    fingerprint = _evaluation_fingerprint(evaluation)
    duplicate = None if force else _duplicate_snapshot(
        repo.list_thesis_snapshots(thesis.thesis_id),
        thesis.thesis_id,
        as_of,
        fingerprint,
    )
    if duplicate is not None:
        return (
            ThesisLifecycleTransition(
                thesis_id=thesis.thesis_id,
                previous_state=evaluation.previous_state,
                proposed_state=evaluation.proposed_state,
                changed=evaluation.previous_state != evaluation.proposed_state,
                reason="duplicate_snapshot_skipped",
                snapshot_id=duplicate.snapshot_id,
            ),
            False,
        )
    snapshot = repo.append_thesis_snapshot(
        thesis_id=thesis.thesis_id,
        version=thesis.version,
        status=evaluation.proposed_state.value,
        as_of=_as_of_datetime(as_of),
        big_flow_score=evaluation.big_flow_score,
        state_reason=_snapshot_reason(evaluation),
        metadata_json={
            "evaluation_fingerprint": fingerprint,
            "evidence_ids": evaluation.evidence_ids,
            "support_score": evaluation.support_score,
            "contradiction_score": evaluation.contradiction_score,
            "neutral_score": evaluation.neutral_score,
            "net_evidence_score": evaluation.net_evidence_score,
            "risk_score": evaluation.risk_score,
            "confidence_score": evaluation.confidence_score,
            "transition_reasons": evaluation.transition_reasons,
            "recommended_review_action": evaluation.recommended_review_action,
            "invalidation_warnings": evaluation.invalidation_warnings,
            "no_auto_trade": True,
        },
    )
    return (
        ThesisLifecycleTransition(
            thesis_id=thesis.thesis_id,
            previous_state=evaluation.previous_state,
            proposed_state=evaluation.proposed_state,
            changed=evaluation.previous_state != evaluation.proposed_state,
            reason=_snapshot_reason(evaluation),
            snapshot_id=snapshot.snapshot_id,
        ),
        True,
    )


def evaluate_thesis_states(
    session: Session,
    as_of: date,
    thesis_dir: Path | str = "thesis",
    lookback_days: int | None = None,
    big_flow_scores: dict[str, float] | None = None,
    memo_dir: Path | str | None = DEFAULT_MEMO_DIR,
    force: bool = False,
) -> ThesisReviewResult:
    repo = Repository(session)
    theses = load_thesis_dir(thesis_dir)
    evidence_rows = repo.list_evidence()
    big_flow_scores = big_flow_scores or {}
    evaluations: list[ThesisStateEvaluationResult] = []
    transitions: list[ThesisLifecycleTransition] = []
    snapshot_count = 0
    skipped_count = 0
    for thesis in theses:
        previous_state = _latest_snapshot_state(repo, thesis, as_of)
        evaluation = evaluate_thesis_state(
            thesis,
            evidence_rows,
            ThesisStateEvaluationInput(
                thesis_id=thesis.thesis_id,
                as_of=as_of,
                previous_state=previous_state,
                lookback_days=lookback_days,
                big_flow_score=big_flow_scores.get(thesis.thesis_id),
            ),
        )
        transition, appended = _append_evaluation_snapshot(repo, thesis, evaluation, as_of, force)
        if appended:
            snapshot_count += 1
        else:
            skipped_count += 1
        evaluations.append(evaluation)
        transitions.append(transition)
    memo_path = None
    if memo_dir is not None:
        memo_path = render_thesis_review_memo(Path(memo_dir), as_of, evaluations, transitions)
    return ThesisReviewResult(
        as_of=as_of,
        evaluation_count=len(evaluations),
        snapshot_count=snapshot_count,
        skipped_duplicate_snapshot_count=skipped_count,
        memo_path=memo_path,
        evaluations=evaluations,
        transitions=transitions,
    )


def render_thesis_review_memo(
    memo_dir: Path,
    as_of: date,
    evaluations: list[ThesisStateEvaluationResult],
    transitions: list[ThesisLifecycleTransition],
) -> str:
    memo_dir.mkdir(parents=True, exist_ok=True)
    memo_path = memo_dir / f"thesis_review_memo_{as_of.isoformat()}.md"
    memo = render_report(
        "thesis_review_memo.md.j2",
        {
            "as_of": as_of.isoformat(),
            "evaluations": evaluations,
            "transitions": transitions,
            "disclaimer": NO_AUTO_TRADE_DISCLAIMER,
        },
    )
    memo_path.write_text(memo, encoding="utf-8")
    return str(memo_path)


def run_thesis_review_demo(
    session: Session,
    as_of: date,
    thesis_dir: Path | str = "thesis",
    scenario_dir: Path | str = "scenarios",
    fixture_dir: Path | str = DEFAULT_OFFICIAL_FIXTURE_DIR,
    memo_dir: Path | str = DEFAULT_MEMO_DIR,
) -> ThesisReviewResult:
    register_official_sources(session)
    ingest_official_mock_bundle_idempotent(session, Path(fixture_dir))
    normalize_events(session)
    generate_and_append_evidence(session, thesis_dir, scenario_dir)
    return evaluate_thesis_states(
        session=session,
        as_of=as_of,
        thesis_dir=thesis_dir,
        memo_dir=memo_dir,
    )


def archive_thesis(
    session: Session,
    thesis_id: str,
    as_of: date,
    thesis_dir: Path | str = "thesis",
    reason: str = "Explicit archive command.",
    force: bool = False,
) -> ThesisReviewResult:
    repo = Repository(session)
    theses = {thesis.thesis_id: thesis for thesis in load_thesis_dir(thesis_dir)}
    thesis = theses[thesis_id]
    previous_state = _latest_snapshot_state(repo, thesis, as_of)
    evaluation = ThesisStateEvaluationResult(
        thesis_id=thesis_id,
        previous_state=previous_state,
        proposed_state=ThesisStatus.archived,
        confidence_score=100.0,
        support_score=0.0,
        contradiction_score=0.0,
        neutral_score=0.0,
        net_evidence_score=0.0,
        risk_score=0.0,
        evidence_count=0,
        transition_reasons=["explicit_archive_command", reason],
        recommended_review_action="record_only_archived",
        evidence_ids=[],
    )
    transition, appended = _append_evaluation_snapshot(repo, thesis, evaluation, as_of, force)
    return ThesisReviewResult(
        as_of=as_of,
        evaluation_count=1,
        snapshot_count=1 if appended else 0,
        skipped_duplicate_snapshot_count=0 if appended else 1,
        evaluations=[evaluation],
        transitions=[transition],
    )


def evidence_counts_by_thesis(evidence_rows: list[EvidenceLedger]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for evidence in evidence_rows:
        if evidence.thesis_id:
            counts[evidence.thesis_id] += 1
    return dict(counts)
