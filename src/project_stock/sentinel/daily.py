from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import Field
from sqlalchemy.orm import Session

from project_stock.reports.render import render_report
from project_stock.schemas.common import SchemaBase
from project_stock.schemas.decisions import DecisionCreate
from project_stock.schemas.evidence import EvidenceCreate
from project_stock.storage.repository import Repository


class DailySentinelResult(SchemaBase):
    as_of: date
    event_count: int
    evidence_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    report_path: str | None = None


def run_daily_sentinel(
    as_of: date,
    db_session: Session,
    config: dict[str, object] | None = None,
) -> DailySentinelResult:
    config = config or {}
    repo = Repository(db_session)
    events = repo.list_events()
    evidence_ids: list[str] = []
    decision_ids: list[str] = []
    for event in events:
        evidence = repo.append_evidence(
            EvidenceCreate(
                event_id=event.event_id,
                thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
                evidence_type="daily_event_review",
                claim=event.summary,
                supports_or_contradicts="neutral",
                strength_score=event.surprise_score,
                metadata_json={"event_type": event.event_type},
            )
        )
        evidence_ids.append(evidence.evidence_id)
    decision = repo.append_decision(
        DecisionCreate(
            decision_type="daily_sentinel_review",
            thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
            action="record_risk_memo",
            rationale="Daily sentinel records event evidence and produces a risk memo.",
            portfolio_impact="No broker order execution is permitted.",
            review_after="next daily sentinel",
            metadata_json={"event_count": len(events)},
        )
    )
    decision_ids.append(decision.decision_id)

    report_path = config.get("report_path")
    if report_path is None:
        report_path = Path("data") / "processed" / f"daily_risk_memo_{as_of.isoformat()}.md"
    report_path = Path(str(report_path))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    memo = render_report(
        "daily_risk_memo.md.j2",
        {
            "as_of": as_of.isoformat(),
            "events": events,
            "emergency_levels": {},
            "triggered_scenarios": [],
            "allowed_actions": [],
            "forbidden_actions": ["llm_direct_trade_decision"],
            "evidence_ids": evidence_ids,
            "decision_ids": decision_ids,
        },
    )
    report_path.write_text(memo, encoding="utf-8")
    return DailySentinelResult(
        as_of=as_of,
        event_count=len(events),
        evidence_ids=evidence_ids,
        decision_ids=decision_ids,
        report_path=str(report_path),
    )
