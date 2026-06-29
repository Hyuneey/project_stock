from __future__ import annotations

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from project_stock.db.base import Base
from project_stock.utils.clock import utc_now


class Source(Base):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500))
    reliability_default: Mapped[float] = mapped_column(Float, default=3.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    raw_documents: Mapped[list[RawDocument]] = relationship(back_populates="source")


class RawDocument(Base):
    __tablename__ = "raw_documents"

    doc_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.source_id"))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    published_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    available_from: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128))
    raw_path: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    source: Mapped[Source | None] = relationship(back_populates="raw_documents")


class MarketTimeSeries(Base):
    __tablename__ = "market_time_series"

    series_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    timestamp: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    frequency: Mapped[str] = mapped_column(String(40), nullable=False)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    value: Mapped[float | None] = mapped_column(Float)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.source_id"))
    collected_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    available_from: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    adjusted_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IndicatorObservation(Base):
    __tablename__ = "indicator_observations"

    observation_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    indicator_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    observation_period: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(80))
    release_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    available_from: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    vintage_date: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.source_id"))
    consensus: Mapped[float | None] = mapped_column(Float)
    previous: Mapped[float | None] = mapped_column(Float)
    revised_previous: Mapped[float | None] = mapped_column(Float)
    surprise_value: Mapped[float | None] = mapped_column(Float)
    surprise_z: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Event(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    event_time: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    first_seen_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_reliability: Mapped[float] = mapped_column(Float, default=3.0, nullable=False)
    surprise_score: Mapped[float] = mapped_column(Float, default=3.0, nullable=False)
    persistence_score: Mapped[float] = mapped_column(Float, default=3.0, nullable=False)
    market_confirmation_score: Mapped[float] = mapped_column(Float, default=3.0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="new", nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    entities: Mapped[list[EventEntity]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventEntity(Base):
    __tablename__ = "event_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    event: Mapped[Event] = relationship(back_populates="entities")


class EvidenceLedger(Base):
    __tablename__ = "evidence_ledger"

    evidence_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.event_id"))
    thesis_id: Mapped[str | None] = mapped_column(String(120), index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(120), index=True)
    evidence_type: Mapped[str] = mapped_column(String(80), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    supports_or_contradicts: Mapped[str] = mapped_column(String(40), default="neutral", nullable=False)
    strength_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source_ids_json: Mapped[list | None] = mapped_column(JSON)
    immutable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)


class DecisionLog(Base):
    __tablename__ = "decision_logs"

    decision_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    timestamp: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decision_type: Mapped[str] = mapped_column(String(80), nullable=False)
    thesis_id: Mapped[str | None] = mapped_column(String(120), index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(120), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.event_id"))
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    portfolio_impact: Mapped[str | None] = mapped_column(Text)
    review_after: Mapped[str | None] = mapped_column(String(120))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ThesisStateSnapshot(Base):
    __tablename__ = "thesis_state_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    thesis_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False)
    as_of: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    big_flow_score: Mapped[float | None] = mapped_column(Float)
    state_reason: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ScenarioTriggerLog(Base):
    __tablename__ = "scenario_trigger_logs"

    trigger_log_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    thesis_id: Mapped[str | None] = mapped_column(String(120), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.event_id"))
    triggered_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    result_state: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _raise_append_only_update(mapper: object, connection: object, target: object) -> None:
    raise RuntimeError(f"{target.__class__.__name__} is append-only and cannot be updated.")


def _raise_append_only_delete(mapper: object, connection: object, target: object) -> None:
    raise RuntimeError(f"{target.__class__.__name__} is append-only and cannot be deleted.")


for _append_only_model in (EvidenceLedger, DecisionLog):
    sqlalchemy_event.listen(_append_only_model, "before_update", _raise_append_only_update)
    sqlalchemy_event.listen(_append_only_model, "before_delete", _raise_append_only_delete)
