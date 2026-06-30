from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

import yaml
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from project_stock.db.models import Event, IndicatorObservation, MarketTimeSeries, RawDocument, Source
from project_stock.events.mapper import map_entities, map_symbol_entity
from project_stock.ingest.official_bundle import ingest_official_mock_bundle
from project_stock.ingest.sources import register_official_sources
from project_stock.normalize.time import safe_available_from
from project_stock.schemas.common import SchemaBase
from project_stock.schemas.events import EventCreate
from project_stock.storage.repository import Repository
from project_stock.utils.ids import make_id


DEFAULT_MARKET_THRESHOLD_PATH = Path("configs/market_event_thresholds.yaml")


class EventNormalizationResult(SchemaBase):
    inserted_event_ids: list[str] = Field(default_factory=list)
    skipped_count: int = 0
    counts_by_event_type: dict[str, int] = Field(default_factory=dict)
    entity_count: int = 0


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _source_reliability(session: Session, source_id: str | None) -> float:
    if source_id is None:
        return 3.0
    source = session.get(Source, source_id)
    return float(source.reliability_default) if source else 3.0


def _source_record_id(document: RawDocument) -> str:
    if document.source_id == "NEWS_RSS" and document.checksum:
        return document.checksum
    return document.doc_id


def _has_close_duplicate(
    repo: Repository,
    event_type: str,
    event_time: datetime,
    entities: list[dict[str, object]],
    window_minutes: int,
) -> bool:
    entity_keys = {(str(entity["entity_type"]), str(entity["entity_id"])) for entity in entities}
    if not entity_keys:
        return False
    for existing in repo.list_events_with_entities():
        if existing.event_type != event_type:
            continue
        existing_keys = {
            (entity.entity_type, entity.entity_id)
            for entity in existing.entities
        }
        if not entity_keys.intersection(existing_keys):
            continue
        delta = abs(_utc_naive(existing.event_time) - _utc_naive(event_time))
        if delta <= timedelta(minutes=window_minutes):
            return True
    return False


def _insert_event_with_entities(
    session: Session,
    event_create: EventCreate,
    entities: list[dict[str, object]],
    source_table: str,
    source_record_id: str,
    close_duplicate_window_minutes: int = 60,
) -> tuple[Event | None, int]:
    repo = Repository(session)
    if repo.find_event_by_source_record(source_table, source_record_id, event_create.event_type):
        return None, 0
    if _has_close_duplicate(
        repo,
        event_create.event_type,
        event_create.event_time,
        entities,
        close_duplicate_window_minutes,
    ):
        return None, 0
    event = repo.add_event(event_create)
    entity_rows = repo.add_event_entities(event.event_id, entities)
    return event, len(entity_rows)


def _result_from_inserted(inserted: list[tuple[Event, int]], skipped_count: int) -> EventNormalizationResult:
    counts = Counter(event.event_type for event, _ in inserted)
    return EventNormalizationResult(
        inserted_event_ids=[event.event_id for event, _ in inserted],
        skipped_count=skipped_count,
        counts_by_event_type=dict(counts),
        entity_count=sum(entity_count for _, entity_count in inserted),
    )


def classify_opendart_document(document: RawDocument) -> str:
    metadata = document.metadata_json or {}
    text = f"{document.title} {document.body_text} {metadata.get('report_name', '')}".lower()
    if any(keyword in text for keyword in ("guidance", "forecast", "outlook")):
        return "earnings_guidance"
    if any(keyword in text for keyword in ("earnings revision", "eps revision", "profit revision")):
        return "earnings_revision_candidate"
    if any(keyword in text for keyword in ("dividend", "buyback", "split", "merger")):
        return "corporate_action_candidate"
    if any(keyword in text for keyword in ("risk", "litigation", "uncertainty", "going concern")):
        return "risk_disclosure_candidate"
    return "disclosure_received"


def classify_news_document(document: RawDocument) -> str:
    text = f"{document.title} {document.body_text}".lower()
    if any(keyword in text for keyword in ("fed", "policy", "rate", "inflation", "central bank")):
        return "macro_policy_headline"
    if any(keyword in text for keyword in ("war", "sanction", "geopolitical", "oil", "middle east")):
        return "geopolitical_risk_headline"
    if any(keyword in text for keyword in ("semiconductor", "memory", "hbm", "sector")):
        return "sector_news_headline"
    if any(keyword in text for keyword in ("samsung", "sk hynix", "005930", "000660")):
        return "company_news_headline"
    return "unclassified_news"


def normalize_events_from_documents(session: Session) -> EventNormalizationResult:
    documents = session.scalars(select(RawDocument).order_by(RawDocument.published_at)).all()
    inserted: list[tuple[Event, int]] = []
    skipped_count = 0
    for document in documents:
        if document.source_id == "OPEN_DART":
            event_type = classify_opendart_document(document)
        elif document.source_id == "NEWS_RSS":
            event_type = classify_news_document(document)
        else:
            continue
        source_record_id = _source_record_id(document)
        event_time = document.published_at or document.available_from
        first_seen_at = document.available_from
        metadata = {
            "source_table": "raw_documents",
            "source_record_id": source_record_id,
            "source_id": document.source_id,
            "doc_id": document.doc_id,
            "checksum": document.checksum,
            **(document.metadata_json or {}),
        }
        entities = map_entities(
            f"{document.title} {document.body_text} {document.source_id or ''} "
            f"{metadata.get('stock_code', '')}"
        )
        event_create = EventCreate(
            event_id=make_id("EVT", event_time),
            event_type=event_type,
            event_time=event_time,
            first_seen_at=first_seen_at,
            available_from=safe_available_from(document.available_from, document.available_from),
            summary=document.title,
            source_reliability=_source_reliability(session, document.source_id),
            surprise_score=3.0,
            persistence_score=2.0,
            market_confirmation_score=2.0,
            metadata_json=metadata,
        )
        event, entity_count = _insert_event_with_entities(
            session,
            event_create,
            entities,
            "raw_documents",
            source_record_id,
        )
        if event is None:
            skipped_count += 1
            continue
        inserted.append((event, entity_count))
    return _result_from_inserted(inserted, skipped_count)


def classify_indicator_event(observation: IndicatorObservation) -> str:
    indicator_id = observation.indicator_id.upper()
    surprise_z = observation.surprise_z
    if surprise_z is not None and surprise_z >= 1.0:
        return "macro_surprise_positive"
    if surprise_z is not None and surprise_z <= -1.0:
        return "macro_surprise_negative"
    if any(keyword in indicator_id for keyword in ("CPI", "PCE", "INFLATION")):
        return "inflation_surprise" if surprise_z is not None else "macro_indicator_release"
    if any(keyword in indicator_id for keyword in ("GDP", "INDPRO", "GROWTH")):
        return "growth_surprise" if surprise_z is not None else "macro_indicator_release"
    if any(keyword in indicator_id for keyword in ("RATE", "DGS", "YIELD", "FEDFUNDS")):
        return "rate_policy_relevant"
    return "macro_indicator_release"


def _indicator_surprise_score(observation: IndicatorObservation) -> float:
    if observation.surprise_z is None:
        return 3.0
    return max(0.0, min(5.0, 3.0 + abs(float(observation.surprise_z))))


def normalize_events_from_indicators(session: Session) -> EventNormalizationResult:
    observations = session.scalars(
        select(IndicatorObservation).order_by(IndicatorObservation.release_at)
    ).all()
    inserted: list[tuple[Event, int]] = []
    skipped_count = 0
    for observation in observations:
        event_type = classify_indicator_event(observation)
        source_record_id = observation.observation_id
        event_time = observation.release_at or observation.available_from
        metadata = {
            "source_table": "indicator_observations",
            "source_record_id": source_record_id,
            "source_id": observation.source_id,
            "indicator_id": observation.indicator_id,
            "observation_period": observation.observation_period,
            "consensus": observation.consensus,
            "previous": observation.previous,
            "revised_previous": observation.revised_previous,
            "surprise_value": observation.surprise_value,
            "surprise_z": observation.surprise_z,
            "vintage_date": observation.vintage_date,
        }
        entities = map_entities(f"{observation.indicator_id} rate yield inflation growth fed korea us")
        event_create = EventCreate(
            event_id=make_id("EVT", event_time),
            event_type=event_type,
            event_time=event_time,
            first_seen_at=observation.available_from,
            available_from=safe_available_from(observation.available_from, observation.available_from),
            summary=f"{observation.indicator_id} released for {observation.observation_period}",
            source_reliability=_source_reliability(session, observation.source_id),
            surprise_score=_indicator_surprise_score(observation),
            persistence_score=3.0,
            market_confirmation_score=2.5,
            metadata_json=metadata,
        )
        event, entity_count = _insert_event_with_entities(
            session,
            event_create,
            entities,
            "indicator_observations",
            source_record_id,
        )
        if event is None:
            skipped_count += 1
            continue
        inserted.append((event, entity_count))
    return _result_from_inserted(inserted, skipped_count)


def load_market_thresholds(path: Path | str = DEFAULT_MARKET_THRESHOLD_PATH) -> dict[str, float]:
    threshold_path = Path(path)
    if not threshold_path.exists():
        return {
            "large_move_pct": 2.5,
            "fx_stress_pct": 1.0,
            "rates_shock_abs": 0.15,
            "sector_relative_strength_pct": 2.5,
            "volatility_shock_pct": 8.0,
            "close_duplicate_window_minutes": 60,
        }
    return yaml.safe_load(threshold_path.read_text(encoding="utf-8"))


def _market_event_type(symbol: str, pct_move: float | None, abs_move: float, thresholds: dict[str, float]) -> str | None:
    symbol_upper = symbol.upper()
    if symbol_upper == "USDKRW" and pct_move is not None and abs(pct_move) >= thresholds["fx_stress_pct"]:
        return "fx_stress_move"
    if symbol_upper == "US10Y" and abs(abs_move) >= thresholds["rates_shock_abs"]:
        return "rates_shock_move"
    if symbol_upper == "SOX" and pct_move is not None and abs(pct_move) >= thresholds["sector_relative_strength_pct"]:
        return "sector_relative_strength_move"
    if symbol_upper == "VIX" and pct_move is not None and abs(pct_move) >= thresholds["volatility_shock_pct"]:
        return "volatility_shock_move"
    if pct_move is not None and abs(pct_move) >= thresholds["large_move_pct"]:
        return "market_large_move"
    return None


def detect_market_events(
    session: Session,
    thresholds_path: Path | str = DEFAULT_MARKET_THRESHOLD_PATH,
) -> EventNormalizationResult:
    thresholds = load_market_thresholds(thresholds_path)
    series_rows = session.scalars(
        select(MarketTimeSeries).order_by(MarketTimeSeries.symbol, MarketTimeSeries.timestamp)
    ).all()
    previous_by_symbol: dict[str, MarketTimeSeries] = {}
    inserted: list[tuple[Event, int]] = []
    skipped_count = 0
    for row in series_rows:
        previous = previous_by_symbol.get(row.symbol)
        previous_by_symbol[row.symbol] = row
        if previous is None:
            skipped_count += 1
            continue
        current_value = row.close if row.close is not None else row.value
        previous_value = previous.close if previous.close is not None else previous.value
        if current_value is None or previous_value is None:
            skipped_count += 1
            continue
        abs_move = float(current_value) - float(previous_value)
        pct_move = (abs_move / float(previous_value) * 100) if float(previous_value) != 0 else None
        event_type = _market_event_type(row.symbol, pct_move, abs_move, thresholds)
        if event_type is None:
            skipped_count += 1
            continue
        source_record_id = row.series_id
        metadata = {
            "source_table": "market_time_series",
            "source_record_id": source_record_id,
            "source_id": row.source_id,
            "symbol": row.symbol,
            "previous_series_id": previous.series_id,
            "previous_value": previous_value,
            "current_value": current_value,
            "absolute_move": abs_move,
            "pct_move": pct_move,
        }
        entities = map_symbol_entity(row.symbol)
        if row.symbol.upper() in {"005930", "000660", "SOX"}:
            entities.extend(map_entities("semiconductor memory AI Korea"))
        event_create = EventCreate(
            event_id=make_id("EVT", row.timestamp),
            event_type=event_type,
            event_time=row.timestamp,
            first_seen_at=row.available_from,
            available_from=safe_available_from(row.available_from, row.available_from),
            summary=f"{row.symbol} moved {pct_move:.2f}%" if pct_move is not None else f"{row.symbol} moved",
            source_reliability=_source_reliability(session, row.source_id),
            surprise_score=max(0.0, min(5.0, abs(pct_move or abs_move))),
            persistence_score=2.5,
            market_confirmation_score=4.0,
            metadata_json=metadata,
        )
        event, entity_count = _insert_event_with_entities(
            session,
            event_create,
            entities,
            "market_time_series",
            source_record_id,
            int(thresholds.get("close_duplicate_window_minutes", 60)),
        )
        if event is None:
            skipped_count += 1
            continue
        inserted.append((event, entity_count))
    return _result_from_inserted(inserted, skipped_count)


def merge_results(results: Iterable[EventNormalizationResult]) -> EventNormalizationResult:
    inserted_ids: list[str] = []
    skipped_count = 0
    entity_count = 0
    counts: Counter[str] = Counter()
    for result in results:
        inserted_ids.extend(result.inserted_event_ids)
        skipped_count += result.skipped_count
        entity_count += result.entity_count
        counts.update(result.counts_by_event_type)
    return EventNormalizationResult(
        inserted_event_ids=inserted_ids,
        skipped_count=skipped_count,
        counts_by_event_type=dict(counts),
        entity_count=entity_count,
    )


def normalize_events(session: Session) -> EventNormalizationResult:
    return merge_results(
        [
            normalize_events_from_documents(session),
            normalize_events_from_indicators(session),
            detect_market_events(session),
        ]
    )


def run_event_normalization_demo(
    session: Session,
    fixture_dir: Path,
) -> EventNormalizationResult:
    register_official_sources(session)
    ingest_official_mock_bundle(session, fixture_dir)
    return normalize_events(session)
