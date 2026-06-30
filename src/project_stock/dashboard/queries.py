from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from project_stock.db.models import (
    DecisionLog,
    Event,
    EventEntity,
    EvidenceLedger,
    IndicatorObservation,
    MarketTimeSeries,
    RawDocument,
    ScenarioTriggerLog,
    ThesisStateSnapshot,
)


COUNT_MODELS = {
    "RawDocument": RawDocument,
    "IndicatorObservation": IndicatorObservation,
    "MarketTimeSeries": MarketTimeSeries,
    "Event": Event,
    "EventEntity": EventEntity,
    "EvidenceLedger": EvidenceLedger,
    "DecisionLog": DecisionLog,
    "ThesisStateSnapshot": ThesisStateSnapshot,
    "ScenarioTriggerLog": ScenarioTriggerLog,
}


def _iso(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    return value or {}


def get_table_counts(session: Session) -> dict[str, int]:
    return {
        name: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for name, model in COUNT_MODELS.items()
    }


def _max_iso(session: Session, column: Any) -> str | None:
    return _iso(session.scalar(select(func.max(column))))


def get_latest_available_dates(session: Session) -> dict[str, str | None]:
    return {
        "raw_documents_available_from": _max_iso(session, RawDocument.available_from),
        "indicator_observations_available_from": _max_iso(
            session,
            IndicatorObservation.available_from,
        ),
        "market_time_series_available_from": _max_iso(session, MarketTimeSeries.available_from),
        "events_available_from": _max_iso(session, Event.available_from),
        "decision_logs_timestamp": _max_iso(session, DecisionLog.timestamp),
        "thesis_state_snapshots_as_of": _max_iso(session, ThesisStateSnapshot.as_of),
        "scenario_trigger_logs_triggered_at": _max_iso(session, ScenarioTriggerLog.triggered_at),
    }


def get_latest_memos(memo_dir: Path | str, limit: int = 8) -> list[dict[str, str]]:
    root = Path(memo_dir)
    if not root.exists():
        return []
    files = sorted(
        [path for path in root.rglob("*.md") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "name": path.name,
            "path": str(path),
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        }
        for path in files[:limit]
    ]


def get_overview(session: Session, db_url: str, memo_dir: Path | str) -> dict[str, object]:
    return {
        "db_url": db_url,
        "counts": get_table_counts(session),
        "latest_available_dates": get_latest_available_dates(session),
        "latest_memos": get_latest_memos(memo_dir),
    }


def get_recent_events(
    session: Session,
    limit: int = 50,
    event_type: str | None = None,
    source_id: str | None = None,
) -> list[dict[str, object]]:
    rows = session.scalars(
        select(Event)
        .options(selectinload(Event.entities))
        .order_by(Event.available_from.desc(), Event.event_time.desc())
        .limit(max(limit * 4, limit))
    ).all()
    events: list[dict[str, object]] = []
    for event in rows:
        metadata = _metadata(event.metadata_json)
        event_source_id = metadata.get("source_id")
        if event_type and event.event_type != event_type:
            continue
        if source_id and event_source_id != source_id:
            continue
        events.append(
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "event_time": _iso(event.event_time),
                "available_from": _iso(event.available_from),
                "summary": event.summary,
                "source_id": event_source_id,
                "source_reliability": event.source_reliability,
                "surprise_score": event.surprise_score,
                "mapped_entities_count": len(event.entities),
            }
        )
        if len(events) >= limit:
            break
    return events


def get_event_filter_values(session: Session) -> dict[str, list[str]]:
    events = session.scalars(select(Event)).all()
    event_types = sorted({event.event_type for event in events})
    source_ids = sorted(
        {
            str((_metadata(event.metadata_json)).get("source_id"))
            for event in events
            if (_metadata(event.metadata_json)).get("source_id")
        }
    )
    return {"event_types": event_types, "source_ids": source_ids}


def _duplicate_skips_from_decisions(session: Session) -> list[dict[str, object]]:
    decisions = session.scalars(
        select(DecisionLog).order_by(DecisionLog.timestamp.desc()).limit(100)
    ).all()
    rows: list[dict[str, object]] = []
    for decision in decisions:
        metadata = _metadata(decision.metadata_json)
        skipped = metadata.get("skipped_duplicate_evidence_count")
        if skipped is None:
            skipped = metadata.get("skipped_count")
        if skipped is None:
            continue
        rows.append(
            {
                "decision_id": decision.decision_id,
                "decision_type": decision.decision_type,
                "timestamp": _iso(decision.timestamp),
                "skipped_duplicate_evidence_count": skipped,
            }
        )
    return rows


def get_evidence_monitor(session: Session, limit: int = 20) -> dict[str, object]:
    evidence_rows = session.scalars(
        select(EvidenceLedger).order_by(EvidenceLedger.created_at.desc())
    ).all()
    counts_by_thesis: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    stance_counts: Counter[str] = Counter()
    for evidence in evidence_rows:
        thesis_id = evidence.thesis_id or "UNLINKED"
        stance = evidence.supports_or_contradicts
        counts_by_thesis[thesis_id][stance] += 1
        stance_counts[stance] += 1

    top = sorted(
        evidence_rows,
        key=lambda row: (row.strength_score, row.created_at),
        reverse=True,
    )[:limit]
    return {
        "counts_by_thesis": {
            thesis_id: dict(sorted(stance_map.items()))
            for thesis_id, stance_map in sorted(counts_by_thesis.items())
        },
        "stance_counts": dict(sorted(stance_counts.items())),
        "top_evidence": [
            {
                "evidence_id": evidence.evidence_id,
                "event_id": evidence.event_id,
                "thesis_id": evidence.thesis_id,
                "scenario_id": evidence.scenario_id,
                "stance": evidence.supports_or_contradicts,
                "strength_score": evidence.strength_score,
                "claim": evidence.claim,
                "created_at": _iso(evidence.created_at),
            }
            for evidence in top
        ],
        "duplicate_evidence_skips": _duplicate_skips_from_decisions(session),
    }


def _top_snapshot_evidence(
    evidence_by_id: dict[str, EvidenceLedger],
    evidence_ids: list[str],
    stance: str,
) -> list[dict[str, object]]:
    rows = [
        evidence_by_id[evidence_id]
        for evidence_id in evidence_ids
        if evidence_id in evidence_by_id
        and evidence_by_id[evidence_id].supports_or_contradicts == stance
    ]
    rows = sorted(rows, key=lambda row: (row.strength_score, row.created_at), reverse=True)
    return [
        {
            "evidence_id": evidence.evidence_id,
            "claim": evidence.claim,
            "strength_score": evidence.strength_score,
            "event_id": evidence.event_id,
        }
        for evidence in rows[:3]
    ]


def get_latest_thesis_states(session: Session) -> list[dict[str, object]]:
    snapshots = session.scalars(
        select(ThesisStateSnapshot).order_by(
            ThesisStateSnapshot.thesis_id,
            ThesisStateSnapshot.as_of.desc(),
            ThesisStateSnapshot.created_at.desc(),
        )
    ).all()
    latest: dict[str, ThesisStateSnapshot] = {}
    for snapshot in snapshots:
        latest.setdefault(snapshot.thesis_id, snapshot)

    evidence_by_id = {
        evidence.evidence_id: evidence
        for evidence in session.scalars(select(EvidenceLedger)).all()
    }
    rows: list[dict[str, object]] = []
    for thesis_id, snapshot in sorted(latest.items()):
        metadata = _metadata(snapshot.metadata_json)
        evidence_ids = [str(value) for value in metadata.get("evidence_ids", [])]
        rows.append(
            {
                "snapshot_id": snapshot.snapshot_id,
                "thesis_id": thesis_id,
                "state": snapshot.status,
                "as_of": _iso(snapshot.as_of),
                "support_score": metadata.get("support_score"),
                "contradiction_score": metadata.get("contradiction_score"),
                "net_evidence_score": metadata.get("net_evidence_score"),
                "risk_score": metadata.get("risk_score"),
                "transition_reasons": metadata.get("transition_reasons", []),
                "top_supporting_evidence": _top_snapshot_evidence(
                    evidence_by_id,
                    evidence_ids,
                    "supports",
                ),
                "top_contradicting_evidence": _top_snapshot_evidence(
                    evidence_by_id,
                    evidence_ids,
                    "contradicts",
                ),
            }
        )
    return rows


def get_latest_decision_logs(
    session: Session,
    decision_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, object]]:
    statement = select(DecisionLog).order_by(DecisionLog.timestamp.desc()).limit(limit)
    if decision_type:
        statement = (
            select(DecisionLog)
            .where(DecisionLog.decision_type == decision_type)
            .order_by(DecisionLog.timestamp.desc())
            .limit(limit)
        )
    decisions = session.scalars(statement).all()
    return [
        {
            "decision_id": decision.decision_id,
            "timestamp": _iso(decision.timestamp),
            "decision_type": decision.decision_type,
            "thesis_id": decision.thesis_id,
            "scenario_id": decision.scenario_id,
            "event_id": decision.event_id,
            "action": decision.action,
            "rationale": decision.rationale,
            "portfolio_impact": decision.portfolio_impact,
            "metadata_json": _metadata(decision.metadata_json),
        }
        for decision in decisions
    ]


def get_latest_portfolio_review(session: Session) -> dict[str, object] | None:
    decisions = get_latest_decision_logs(session, decision_type="portfolio_review", limit=1)
    if not decisions:
        return None
    decision = decisions[0]
    metadata = decision["metadata_json"]
    return {
        "decision": decision,
        "portfolio_id": metadata.get("portfolio_id"),
        "as_of": metadata.get("as_of"),
        "exposure": metadata.get("exposure", {}),
        "risk_flags": metadata.get("risk_flags", []),
        "latest_thesis_states": metadata.get("latest_thesis_states", {}),
        "no_auto_trade": metadata.get("no_auto_trade", True),
    }


def _emergency_level_from_rationale(rationale: str) -> str | None:
    match = re.search(r"level=([A-Z][0-9])", rationale)
    return match.group(1) if match else None


def get_scenario_emergency_monitor(session: Session, limit: int = 25) -> dict[str, object]:
    triggers = session.scalars(
        select(ScenarioTriggerLog).order_by(ScenarioTriggerLog.triggered_at.desc()).limit(limit)
    ).all()
    emergency_decisions = get_latest_decision_logs(
        session,
        decision_type="emergency_risk_review",
        limit=1,
    )
    latest_emergency = emergency_decisions[0] if emergency_decisions else None
    if latest_emergency:
        metadata = latest_emergency["metadata_json"]
        latest_emergency = {
            **latest_emergency,
            "allowed_actions": metadata.get("allowed_actions", []),
            "forbidden_actions": metadata.get("forbidden_actions", []),
            "emergency_level": metadata.get("emergency_level")
            or _emergency_level_from_rationale(str(latest_emergency["rationale"])),
        }
    return {
        "scenario_triggers": [
            {
                "trigger_log_id": trigger.trigger_log_id,
                "scenario_id": trigger.scenario_id,
                "thesis_id": trigger.thesis_id,
                "event_id": trigger.event_id,
                "triggered_at": _iso(trigger.triggered_at),
                "match_score": trigger.match_score,
                "result_state": trigger.result_state,
                "metadata_json": _metadata(trigger.metadata_json),
            }
            for trigger in triggers
        ],
        "latest_emergency_review": latest_emergency,
    }


def _parse_markdown_table(section_lines: list[str]) -> dict[str, float | str]:
    parsed: dict[str, float | str] = {}
    for line in section_lines:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2 or cells[0] in {"Metric", "---"} or cells[1].startswith("---"):
            continue
        value: float | str
        try:
            value = float(cells[1])
        except ValueError:
            value = cells[1]
        parsed[cells[0]] = value
    return parsed


def _section(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            break
    if start is None:
        return []
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return lines[start:end]


def get_latest_backtest_report(memo_dir: Path | str) -> dict[str, object] | None:
    root = Path(memo_dir)
    candidates = sorted(
        root.rglob("backtest_validation_report_*.md") if root.exists() else [],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    path = candidates[0]
    markdown = path.read_text(encoding="utf-8")
    warnings = [
        line.removeprefix("- ").strip()
        for line in _section(markdown, "## Point-In-Time Warnings")
        if line.startswith("- ") and line.strip() != "- None."
    ]
    return {
        "path": str(path),
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        "return_risk_metrics": _parse_markdown_table(
            _section(markdown, "## Return And Risk Metrics")
        ),
        "cost_turnover_metrics": _parse_markdown_table(_section(markdown, "## Cost And Turnover")),
        "diagnostic_metrics": _parse_markdown_table(
            _section(markdown, "## Diagnostic Validation Metrics")
        ),
        "point_in_time_warnings": warnings,
    }


def get_dashboard_snapshot(
    session: Session,
    db_url: str,
    memo_dir: Path | str,
) -> dict[str, object]:
    return {
        "overview": get_overview(session, db_url, memo_dir),
        "events": get_recent_events(session),
        "event_filters": get_event_filter_values(session),
        "evidence": get_evidence_monitor(session),
        "thesis_states": get_latest_thesis_states(session),
        "portfolio_review": get_latest_portfolio_review(session),
        "scenario_emergency": get_scenario_emergency_monitor(session),
        "backtest_validation": get_latest_backtest_report(memo_dir),
        "latest_decisions": get_latest_decision_logs(session),
    }
