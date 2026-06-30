from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from project_stock.db.models import (
    DecisionLog,
    Event,
    EventEntity,
    EvidenceLedger,
    RawDocument,
    ScenarioTriggerLog,
    Source,
)
from project_stock.schemas.decisions import DecisionCreate
from project_stock.schemas.events import EventCreate
from project_stock.schemas.evidence import EvidenceCreate
from project_stock.utils.clock import utc_now
from project_stock.utils.ids import make_id


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_source(
        self,
        source_id: str,
        name: str,
        source_type: str,
        url: str | None = None,
        reliability_default: float = 3.0,
        notes: str | None = None,
    ) -> Source:
        source = self.session.get(Source, source_id)
        if source:
            return source
        source = Source(
            source_id=source_id,
            name=name,
            source_type=source_type,
            url=url,
            reliability_default=reliability_default,
            notes=notes,
        )
        self.session.add(source)
        self.session.flush()
        return source

    def add_raw_document(
        self,
        title: str,
        body_text: str,
        source_id: str | None = None,
        published_at: datetime | None = None,
        available_from: datetime | None = None,
        metadata_json: dict | None = None,
    ) -> RawDocument:
        doc = RawDocument(
            doc_id=make_id("DOC"),
            source_id=source_id,
            title=title,
            body_text=body_text,
            published_at=published_at,
            available_from=available_from or published_at or utc_now(),
            metadata_json=metadata_json or {},
        )
        self.session.add(doc)
        self.session.flush()
        return doc

    def add_event(self, event_create: EventCreate) -> Event:
        event = Event(
            event_id=event_create.event_id or make_id("EVT", event_create.event_time),
            event_type=event_create.event_type,
            event_time=event_create.event_time,
            first_seen_at=event_create.first_seen_at or utc_now(),
            summary=event_create.summary,
            source_reliability=event_create.source_reliability,
            surprise_score=event_create.surprise_score,
            persistence_score=event_create.persistence_score,
            market_confirmation_score=event_create.market_confirmation_score,
            status=event_create.status,
            metadata_json=event_create.metadata_json or {},
        )
        self.session.add(event)
        self.session.flush()
        return event

    def add_event_entities(self, event_id: str, entities: list[dict[str, object]]) -> list[EventEntity]:
        rows: list[EventEntity] = []
        for entity in entities:
            row = EventEntity(
                event_id=event_id,
                entity_type=str(entity["entity_type"]),
                entity_id=str(entity["entity_id"]),
                relevance_score=float(entity.get("relevance_score", 1.0)),
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        return rows

    def append_evidence(self, evidence_create: EvidenceCreate) -> EvidenceLedger:
        evidence = EvidenceLedger(
            evidence_id=evidence_create.evidence_id or make_id("EVD"),
            event_id=evidence_create.event_id,
            thesis_id=evidence_create.thesis_id,
            scenario_id=evidence_create.scenario_id,
            evidence_type=evidence_create.evidence_type,
            claim=evidence_create.claim,
            supports_or_contradicts=evidence_create.supports_or_contradicts,
            strength_score=evidence_create.strength_score,
            source_ids_json=evidence_create.source_ids_json or [],
            immutable=True,
            metadata_json=evidence_create.metadata_json or {},
        )
        self.session.add(evidence)
        self.session.flush()
        return evidence

    def append_decision(self, decision_create: DecisionCreate) -> DecisionLog:
        decision = DecisionLog(
            decision_id=decision_create.decision_id or make_id("DEC"),
            timestamp=decision_create.timestamp or utc_now(),
            decision_type=decision_create.decision_type,
            thesis_id=decision_create.thesis_id,
            scenario_id=decision_create.scenario_id,
            event_id=decision_create.event_id,
            action=decision_create.action,
            rationale=decision_create.rationale,
            portfolio_impact=decision_create.portfolio_impact,
            review_after=decision_create.review_after,
            metadata_json=decision_create.metadata_json or {},
        )
        self.session.add(decision)
        self.session.flush()
        return decision

    def append_scenario_trigger(
        self,
        scenario_id: str,
        thesis_id: str | None,
        event_id: str | None,
        match_score: float,
        result_state: str,
        metadata_json: dict | None = None,
    ) -> ScenarioTriggerLog:
        trigger = ScenarioTriggerLog(
            trigger_log_id=make_id("TRG"),
            scenario_id=scenario_id,
            thesis_id=thesis_id,
            event_id=event_id,
            match_score=match_score,
            result_state=result_state,
            metadata_json=metadata_json or {},
        )
        self.session.add(trigger)
        self.session.flush()
        return trigger

    def list_events(self) -> list[Event]:
        return list(self.session.scalars(select(Event).order_by(Event.event_time)).all())

    def list_evidence(self) -> list[EvidenceLedger]:
        return list(
            self.session.scalars(select(EvidenceLedger).order_by(EvidenceLedger.created_at)).all()
        )

    def list_decisions(self) -> list[DecisionLog]:
        return list(self.session.scalars(select(DecisionLog).order_by(DecisionLog.timestamp)).all())


def create_evidence_from_event(
    event: Event,
    thesis_id: str,
    scenario_id: str | None = None,
    supports_or_contradicts: str = "neutral",
    session: Session | None = None,
) -> EvidenceLedger | EvidenceCreate:
    evidence = EvidenceCreate(
        event_id=event.event_id,
        thesis_id=thesis_id,
        scenario_id=scenario_id,
        evidence_type="event",
        claim=event.summary,
        supports_or_contradicts=supports_or_contradicts,
        strength_score=max(1.0, min(5.0, event.surprise_score)),
        metadata_json={"event_type": event.event_type},
    )
    if session is None:
        return evidence
    return Repository(session).append_evidence(evidence)
