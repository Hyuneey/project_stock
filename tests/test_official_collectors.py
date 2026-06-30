from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from project_stock.db.models import IndicatorObservation, MarketTimeSeries, RawDocument, Source
from project_stock.ingest.base import CollectorConfigError
from project_stock.ingest.dart import OpenDartCollector
from project_stock.ingest.ecos import EcosCollector
from project_stock.ingest.fred import FredCollector
from project_stock.ingest.krx import KrxCollector
from project_stock.ingest.news import NewsRssCollector
from project_stock.ingest.official_bundle import ingest_official_mock_bundle
from project_stock.ingest.sources import OFFICIAL_SOURCE_DEFINITIONS, register_official_sources
from project_stock.normalize.time import safe_available_from


def _fixture(repo_root, name: str):
    return repo_root / "tests" / "fixtures" / "official" / name


def test_register_official_sources(db_session):
    sources = register_official_sources(db_session)
    db_session.commit()

    source_ids = {source.source_id for source in sources}
    assert source_ids == {source.source_id for source in OFFICIAL_SOURCE_DEFINITIONS}
    assert db_session.scalar(select(Source).where(Source.source_id == "OPEN_DART")) is not None


def test_safe_available_from_never_precedes_source_times():
    published_at = datetime(2026, 6, 29, 1, 0, tzinfo=UTC)
    collected_at = datetime(2026, 6, 29, 1, 10, tzinfo=UTC)
    unsafe_available = datetime(2026, 6, 29, 1, 5, tzinfo=UTC)

    available_from = safe_available_from(unsafe_available, published_at, collected_at)

    assert available_from == collected_at


def test_opendart_mock_ingestion_to_raw_document(db_session, repo_root, monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)

    result = OpenDartCollector().ingest(
        db_session,
        fixture=_fixture(repo_root, "dart_disclosures.json"),
        mock=True,
    )
    document = db_session.scalar(select(RawDocument).where(RawDocument.source_id == "OPEN_DART"))

    assert result.inserted_count == 1
    assert document is not None
    assert document.available_from >= document.published_at
    assert document.available_from >= document.collected_at
    assert document.metadata_json["rcept_no"] == "20260629000123"


def test_ecos_mock_ingestion_to_indicator_observation(db_session, repo_root, monkeypatch):
    monkeypatch.delenv("ECOS_API_KEY", raising=False)

    result = EcosCollector().ingest(
        db_session,
        fixture=_fixture(repo_root, "ecos_indicators.json"),
        mock=True,
    )
    observation = db_session.scalar(
        select(IndicatorObservation).where(IndicatorObservation.source_id == "BOK_ECOS")
    )

    assert result.inserted_count == 1
    assert observation is not None
    assert observation.indicator_id == "ECOS_BASE_RATE"
    assert observation.available_from >= observation.release_at
    assert observation.available_from >= observation.collected_at


def test_fred_mock_ingestion_to_indicator_observation_with_vintage(db_session, repo_root, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    result = FredCollector().ingest(
        db_session,
        fixture=_fixture(repo_root, "fred_indicators.json"),
        mock=True,
    )
    observation = db_session.scalar(
        select(IndicatorObservation).where(IndicatorObservation.source_id == "FRED")
    )

    assert result.inserted_count == 1
    assert observation is not None
    assert observation.vintage_date == "2026-06-29"
    assert observation.metadata_json["vintage_support"] == "alfred_ready"


def test_krx_mock_ingestion_to_market_time_series(db_session, repo_root):
    result = KrxCollector().ingest(
        db_session,
        fixture=_fixture(repo_root, "krx_market.json"),
        mock=True,
    )
    series = db_session.scalar(select(MarketTimeSeries).where(MarketTimeSeries.source_id == "KRX"))

    assert result.inserted_count == 1
    assert series is not None
    assert series.symbol == "005930"
    assert series.available_from >= series.timestamp
    assert series.available_from >= series.collected_at


def test_news_mock_ingestion_dedupes_by_checksum(db_session, repo_root, monkeypatch):
    monkeypatch.delenv("NEWS_API_KEY", raising=False)
    collector = NewsRssCollector()

    first = collector.ingest(db_session, fixture=_fixture(repo_root, "news_rss.json"), mock=True)
    second = collector.ingest(db_session, fixture=_fixture(repo_root, "news_rss.json"), mock=True)
    documents = db_session.scalars(
        select(RawDocument).where(RawDocument.source_id == "NEWS_RSS")
    ).all()

    assert first.inserted_count == 1
    assert first.skipped_count == 1
    assert second.inserted_count == 0
    assert second.skipped_count == 2
    assert len(documents) == 1


def test_official_mock_bundle_ingests_each_collector(db_session, repo_root, monkeypatch):
    for env_var in ("DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY", "NEWS_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)

    results = ingest_official_mock_bundle(db_session, repo_root / "tests" / "fixtures" / "official")

    assert {result.source_id for result in results} == {
        "OPEN_DART",
        "BOK_ECOS",
        "FRED",
        "KRX",
        "NEWS_RSS",
    }
    assert sum(result.inserted_count for result in results) == 5
    assert sum(result.skipped_count for result in results) == 1


def test_real_fetch_requires_api_key_only_when_requested(repo_root, monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)

    collector = OpenDartCollector()
    mock_records = collector.fetch_raw(_fixture(repo_root, "dart_disclosures.json"), mock=True)

    assert len(mock_records) == 1
    with pytest.raises(CollectorConfigError, match="DART_API_KEY"):
        collector.fetch_raw(mock=False)
