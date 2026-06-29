from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.db.models import Event, EventEntity, IndicatorObservation, RawDocument
from project_stock.ingest.dart import OpenDartCollector
from project_stock.ingest.ecos import EcosCollector
from project_stock.ingest.fred import FredCollector
from project_stock.ingest.krx import KrxCollector
from project_stock.ingest.news import NewsRssCollector
from project_stock.events.normalization import (
    detect_market_events,
    normalize_events,
    normalize_events_from_documents,
    normalize_events_from_indicators,
)
from project_stock.ingest.sources import register_official_sources
from project_stock.schemas.indicators import IndicatorObservationCreate
from project_stock.storage.repository import Repository


def _fixture(repo_root, name: str):
    return repo_root / "tests" / "fixtures" / "official" / name


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def test_opendart_raw_document_normalizes_to_event(db_session, repo_root):
    OpenDartCollector().ingest(db_session, fixture=_fixture(repo_root, "dart_disclosures.json"))

    result = normalize_events_from_documents(db_session)
    event = db_session.scalar(select(Event).where(Event.event_type == "disclosure_received"))
    document = db_session.scalar(select(RawDocument).where(RawDocument.source_id == "OPEN_DART"))

    assert result.counts_by_event_type["disclosure_received"] == 1
    assert event is not None
    assert document is not None
    assert event.available_from >= document.available_from
    assert event.metadata_json["source_record_id"] == document.doc_id


def test_news_raw_document_normalizes_to_event_and_entities(db_session, repo_root):
    NewsRssCollector().ingest(db_session, fixture=_fixture(repo_root, "news_rss.json"))

    result = normalize_events_from_documents(db_session)
    event = db_session.scalar(select(Event).where(Event.event_type == "sector_news_headline"))
    entities = db_session.scalars(select(EventEntity)).all()

    assert result.counts_by_event_type["sector_news_headline"] == 1
    assert event is not None
    assert any(entity.entity_id == "KOR_SEMI_MEMORY_UPCYCLE" for entity in entities)


def test_ecos_indicator_normalizes_to_macro_event(db_session, repo_root):
    EcosCollector().ingest(db_session, fixture=_fixture(repo_root, "ecos_indicators.json"))

    result = normalize_events_from_indicators(db_session)
    event = next(
        event
        for event in db_session.scalars(select(Event)).all()
        if event.metadata_json["source_id"] == "BOK_ECOS"
    )
    observation = db_session.scalar(
        select(IndicatorObservation).where(IndicatorObservation.source_id == "BOK_ECOS")
    )

    assert result.inserted_event_ids
    assert event.event_type == "rate_policy_relevant"
    assert observation is not None
    assert _naive(event.available_from) >= _naive(observation.available_from)


def test_fred_indicator_normalizes_to_macro_event(db_session, repo_root):
    FredCollector().ingest(db_session, fixture=_fixture(repo_root, "fred_indicators.json"))

    result = normalize_events_from_indicators(db_session)
    event = next(
        event
        for event in db_session.scalars(select(Event)).all()
        if event.metadata_json["source_id"] == "FRED"
    )

    assert result.inserted_event_ids
    assert event.event_type == "rate_policy_relevant"
    assert event.metadata_json["vintage_date"] == "2026-06-29"


def test_indicator_surprise_z_sets_surprise_score(db_session):
    register_official_sources(db_session)
    repo = Repository(db_session)
    observation = repo.add_indicator_observation(
        IndicatorObservationCreate(
            source_id="FRED",
            indicator_id="CPI",
            observation_period="2026-06",
            value=3.2,
            unit="percent",
            release_at=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
            available_from=datetime(2026, 6, 29, 12, 10, tzinfo=UTC),
            surprise_z=1.5,
            consensus=3.0,
            previous=2.9,
        )
    )

    result = normalize_events_from_indicators(db_session)
    event = db_session.get(Event, result.inserted_event_ids[0])

    assert event is not None
    assert event.event_type == "macro_surprise_positive"
    assert event.surprise_score == 4.5
    assert _naive(event.available_from) >= _naive(observation.available_from)
    assert event.metadata_json["consensus"] == 3.0


def test_market_time_series_large_move_detection(db_session, repo_root):
    KrxCollector().ingest(db_session, fixture=_fixture(repo_root, "krx_market_moves.json"))

    result = detect_market_events(db_session)
    event = db_session.scalar(select(Event).where(Event.event_type == "market_large_move"))
    entities = db_session.scalars(select(EventEntity)).all()

    assert result.counts_by_event_type["market_large_move"] == 1
    assert event is not None
    assert event.available_from >= event.event_time
    assert any(entity.entity_id == "005930" for entity in entities)


def test_event_normalization_dedupes_source_records(db_session, repo_root):
    OpenDartCollector().ingest(db_session, fixture=_fixture(repo_root, "dart_disclosures.json"))

    first = normalize_events_from_documents(db_session)
    second = normalize_events_from_documents(db_session)

    assert len(first.inserted_event_ids) == 1
    assert len(second.inserted_event_ids) == 0
    assert second.skipped_count == 1
    assert len(db_session.scalars(select(Event)).all()) == 1


def test_normalize_events_all_sources_creates_entities(db_session, repo_root, monkeypatch):
    for env_var in ("DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY", "NEWS_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)
    OpenDartCollector().ingest(db_session, fixture=_fixture(repo_root, "dart_disclosures.json"))
    EcosCollector().ingest(db_session, fixture=_fixture(repo_root, "ecos_indicators.json"))
    FredCollector().ingest(db_session, fixture=_fixture(repo_root, "fred_indicators.json"))
    NewsRssCollector().ingest(db_session, fixture=_fixture(repo_root, "news_rss.json"))

    result = normalize_events(db_session)

    assert result.inserted_event_ids
    assert result.entity_count > 0
    assert db_session.scalar(select(EventEntity)) is not None


def test_cli_event_normalization_demo(tmp_path, repo_root, monkeypatch):
    for env_var in ("DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY", "NEWS_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)
    runner = CliRunner()
    db_url = f"sqlite:///{tmp_path / 'demo.sqlite'}"

    result = runner.invoke(
        app,
        [
            "run-event-normalization-demo",
            "--fixture-dir",
            str(repo_root / "tests" / "fixtures" / "official"),
            "--db-url",
            db_url,
        ],
    )

    assert result.exit_code == 0
    assert "counts_by_event_type" in result.output
    assert "entity_count" in result.output
