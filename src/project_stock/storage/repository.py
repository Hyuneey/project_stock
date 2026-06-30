from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from project_stock.db.models import (
    DecisionLog,
    Event,
    EventEntity,
    EvidenceLedger,
    FinancialStatementLineItem,
    IndicatorObservation,
    MarketTimeSeries,
    RawDocument,
    ScenarioTriggerLog,
    Source,
    ThesisStateSnapshot,
)
from project_stock.schemas.decisions import DecisionCreate
from project_stock.schemas.documents import RawDocumentCreate
from project_stock.schemas.events import EventCreate
from project_stock.schemas.evidence import EvidenceCreate
from project_stock.schemas.financials import FinancialStatementLineItemCreate
from project_stock.schemas.indicators import IndicatorObservationCreate
from project_stock.schemas.market import MarketTimeSeriesCreate
from project_stock.normalize.time import safe_available_from
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
        url: str | None = None,
        language: str = "en",
        published_at: datetime | None = None,
        collected_at: datetime | None = None,
        available_from: datetime | None = None,
        checksum: str | None = None,
        raw_path: str | None = None,
        metadata_json: dict | None = None,
    ) -> RawDocument:
        collected_at = collected_at or utc_now()
        doc = RawDocument(
            doc_id=make_id("DOC"),
            source_id=source_id,
            title=title,
            body_text=body_text,
            url=url,
            language=language,
            published_at=published_at,
            collected_at=collected_at,
            available_from=safe_available_from(available_from, published_at, collected_at),
            checksum=checksum,
            raw_path=raw_path,
            metadata_json=metadata_json or {},
        )
        self.session.add(doc)
        self.session.flush()
        return doc

    def add_raw_document_create(self, document: RawDocumentCreate) -> RawDocument:
        return self.add_raw_document(**document.model_dump())

    def find_raw_document_by_checksum(
        self, checksum: str, source_id: str | None = None
    ) -> RawDocument | None:
        statement = select(RawDocument).where(RawDocument.checksum == checksum)
        if source_id is not None:
            statement = statement.where(RawDocument.source_id == source_id)
        return self.session.scalars(statement).first()

    def add_indicator_observation(
        self, observation_create: IndicatorObservationCreate
    ) -> IndicatorObservation:
        collected_at = observation_create.collected_at or utc_now()
        observation = IndicatorObservation(
            observation_id=make_id("OBS"),
            indicator_id=observation_create.indicator_id,
            observation_period=observation_create.observation_period,
            value=observation_create.value,
            unit=observation_create.unit,
            release_at=observation_create.release_at,
            collected_at=collected_at,
            available_from=safe_available_from(
                observation_create.available_from,
                observation_create.release_at,
                collected_at,
            ),
            vintage_date=observation_create.vintage_date,
            source_id=observation_create.source_id,
            consensus=observation_create.consensus,
            previous=observation_create.previous,
            revised_previous=observation_create.revised_previous,
            surprise_value=observation_create.surprise_value,
            surprise_z=observation_create.surprise_z,
            metadata_json=observation_create.metadata_json or {},
        )
        self.session.add(observation)
        self.session.flush()
        return observation

    def find_financial_statement_line_item(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str,
        fs_div: str,
        sj_div: str,
        account_name: str,
    ) -> FinancialStatementLineItem | None:
        statement = select(FinancialStatementLineItem).where(
            FinancialStatementLineItem.corp_code == corp_code,
            FinancialStatementLineItem.bsns_year == bsns_year,
            FinancialStatementLineItem.reprt_code == reprt_code,
            FinancialStatementLineItem.fs_div == fs_div,
            FinancialStatementLineItem.sj_div == sj_div,
            FinancialStatementLineItem.account_name == account_name,
        )
        return self.session.scalars(statement).first()

    def add_financial_statement_line_item(
        self, line_item_create: FinancialStatementLineItemCreate
    ) -> FinancialStatementLineItem:
        collected_at = line_item_create.collected_at or utc_now()
        item = FinancialStatementLineItem(
            statement_id=line_item_create.statement_id or make_id("FIN"),
            corp_code=line_item_create.corp_code,
            stock_code=line_item_create.stock_code,
            bsns_year=line_item_create.bsns_year,
            reprt_code=line_item_create.reprt_code,
            fs_div=line_item_create.fs_div,
            sj_div=line_item_create.sj_div,
            account_name=line_item_create.account_name,
            current_amount=line_item_create.current_amount,
            previous_amount=line_item_create.previous_amount,
            currency=line_item_create.currency,
            source_id=line_item_create.source_id,
            collected_at=collected_at,
            available_from=safe_available_from(line_item_create.available_from, collected_at),
            metadata_json=line_item_create.metadata_json or {},
        )
        self.session.add(item)
        self.session.flush()
        return item

    def add_market_time_series(self, series_create: MarketTimeSeriesCreate) -> MarketTimeSeries:
        collected_at = series_create.collected_at or utc_now()
        series = MarketTimeSeries(
            series_id=make_id("MKT"),
            symbol=series_create.symbol,
            timestamp=series_create.timestamp,
            frequency=series_create.frequency,
            open=series_create.open,
            high=series_create.high,
            low=series_create.low,
            close=series_create.close,
            volume=series_create.volume,
            value=series_create.value,
            source_id=series_create.source_id,
            collected_at=collected_at,
            available_from=safe_available_from(
                series_create.available_from,
                series_create.timestamp,
                collected_at,
            ),
            adjusted_flag=series_create.adjusted_flag,
            metadata_json=series_create.metadata_json or {},
        )
        self.session.add(series)
        self.session.flush()
        return series

    def add_event(self, event_create: EventCreate) -> Event:
        event = Event(
            event_id=event_create.event_id or make_id("EVT", event_create.event_time),
            event_type=event_create.event_type,
            event_time=event_create.event_time,
            first_seen_at=event_create.first_seen_at or utc_now(),
            available_from=safe_available_from(
                event_create.available_from,
                event_create.event_time,
                event_create.first_seen_at,
            ),
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

    def append_thesis_snapshot(
        self,
        thesis_id: str,
        version: str,
        status: str,
        as_of: datetime,
        state_reason: str,
        big_flow_score: float | None = None,
        metadata_json: dict | None = None,
    ) -> ThesisStateSnapshot:
        snapshot = ThesisStateSnapshot(
            snapshot_id=make_id("THS", as_of),
            thesis_id=thesis_id,
            version=version,
            status=status,
            as_of=as_of,
            big_flow_score=big_flow_score,
            state_reason=state_reason,
            metadata_json=metadata_json or {},
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def list_events(self) -> list[Event]:
        return list(self.session.scalars(select(Event).order_by(Event.event_time)).all())

    def list_events_with_entities(self) -> list[Event]:
        return list(
            self.session.scalars(
                select(Event).options(selectinload(Event.entities)).order_by(Event.event_time)
            ).all()
        )

    def find_event_by_source_record(
        self,
        source_table: str,
        source_record_id: str,
        event_type: str | None = None,
    ) -> Event | None:
        for event in self.list_events():
            metadata = event.metadata_json or {}
            if (
                metadata.get("source_table") == source_table
                and metadata.get("source_record_id") == source_record_id
                and (event_type is None or event.event_type == event_type)
            ):
                return event
        return None

    def list_evidence(self) -> list[EvidenceLedger]:
        return list(
            self.session.scalars(select(EvidenceLedger).order_by(EvidenceLedger.created_at)).all()
        )

    def list_decisions(self) -> list[DecisionLog]:
        return list(self.session.scalars(select(DecisionLog).order_by(DecisionLog.timestamp)).all())

    def list_thesis_snapshots(self, thesis_id: str | None = None) -> list[ThesisStateSnapshot]:
        statement = select(ThesisStateSnapshot).order_by(ThesisStateSnapshot.as_of)
        if thesis_id is not None:
            statement = statement.where(ThesisStateSnapshot.thesis_id == thesis_id)
        return list(self.session.scalars(statement).all())

    def latest_thesis_snapshot(self, thesis_id: str) -> ThesisStateSnapshot | None:
        statement = (
            select(ThesisStateSnapshot)
            .where(ThesisStateSnapshot.thesis_id == thesis_id)
            .order_by(ThesisStateSnapshot.as_of.desc(), ThesisStateSnapshot.created_at.desc())
        )
        return self.session.scalars(statement).first()

    def list_indicator_observations(self) -> list[IndicatorObservation]:
        return list(
            self.session.scalars(
                select(IndicatorObservation).order_by(IndicatorObservation.indicator_id)
            ).all()
        )

    def list_financial_statement_line_items(self) -> list[FinancialStatementLineItem]:
        return list(
            self.session.scalars(
                select(FinancialStatementLineItem).order_by(
                    FinancialStatementLineItem.corp_code,
                    FinancialStatementLineItem.bsns_year,
                    FinancialStatementLineItem.reprt_code,
                    FinancialStatementLineItem.account_name,
                )
            ).all()
        )

    def list_market_time_series(self) -> list[MarketTimeSeries]:
        return list(
            self.session.scalars(select(MarketTimeSeries).order_by(MarketTimeSeries.symbol)).all()
        )


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
