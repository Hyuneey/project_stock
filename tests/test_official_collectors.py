from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.db.models import IndicatorObservation, MarketTimeSeries, RawDocument, Source
from project_stock.events.normalization import normalize_events
from project_stock.evidence.generation import generate_evidence_candidates
from project_stock.ingest.dart import (
    OpenDartCollector,
    load_opendart_corp_codes,
    parse_opendart_disclosure_list_response,
)
from project_stock.ingest.ecos import (
    EcosCollector,
    load_ecos_series_config,
    parse_ecos_statistic_search_response,
)
from project_stock.ingest.fred import FredCollector, parse_fred_observation_response
from project_stock.ingest.krx import KrxCollector
from project_stock.ingest.news import NewsRssCollector
from project_stock.ingest.official_bundle import ingest_official_mock_bundle
from project_stock.ingest.real_data import (
    MissingApiKeyError,
    NetworkDisabledError,
    build_raw_cache_path,
    build_timestamped_raw_cache_path,
    write_raw_response_cache,
)
from project_stock.ingest.sources import OFFICIAL_SOURCE_DEFINITIONS, register_official_sources
from project_stock.normalize.time import safe_available_from

runner = CliRunner()


def _fixture(repo_root, name: str):
    return repo_root / "tests" / "fixtures" / "official" / name


def _root_fixture(repo_root, name: str):
    return repo_root / "tests" / "fixtures" / name


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


def test_fred_mock_ingestion_to_indicator_observation_with_vintage(
    db_session, repo_root, monkeypatch
):
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


def test_mock_dart_fetch_does_not_require_api_key(repo_root, monkeypatch):
    monkeypatch.setenv("PROJECT_STOCK_ALLOW_NETWORK", "true")
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_DART_API_KEY", raising=False)

    collector = OpenDartCollector()
    mock_records = collector.fetch_raw(_fixture(repo_root, "dart_disclosures.json"), mock=True)

    assert len(mock_records) == 1


def test_network_disabled_blocks_real_fetch(monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    monkeypatch.setenv("FRED_API_KEY", "test-key")

    with pytest.raises(NetworkDisabledError, match="PROJECT_STOCK_ALLOW_NETWORK=true"):
        FredCollector().fetch_series("DGS10", "2026-06-29", "2026-06-30")

    result = runner.invoke(
        app,
        [
            "fetch-fred-series",
            "--series-id",
            "DGS10",
            "--start-date",
            "2026-06-29",
            "--end-date",
            "2026-06-30",
        ],
    )
    assert result.exit_code == 1
    assert "Network access is disabled" in result.output


def test_missing_api_key_gives_clear_error(monkeypatch):
    monkeypatch.setenv("PROJECT_STOCK_ALLOW_NETWORK", "true")
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    with pytest.raises(MissingApiKeyError, match="FRED_API_KEY"):
        FredCollector().fetch_series("DGS10", "2026-06-29", "2026-06-30")

    result = runner.invoke(
        app,
        [
            "fetch-fred-series",
            "--series-id",
            "DGS10",
            "--start-date",
            "2026-06-29",
            "--end-date",
            "2026-06-30",
        ],
    )
    assert result.exit_code == 1
    assert "FRED_API_KEY" in result.output


def test_opendart_corp_code_config_loading(repo_root):
    mappings = load_opendart_corp_codes(repo_root / "configs" / "opendart.corp_codes.example.yaml")

    assert mappings["005930"].corp_code == "00126380"
    assert mappings["000660"].corp_name == "SK Hynix"


def test_opendart_network_disabled_blocks_real_fetch(repo_root, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    monkeypatch.setenv("DART_API_KEY", "test-key")

    with pytest.raises(NetworkDisabledError, match="PROJECT_STOCK_ALLOW_NETWORK=true"):
        OpenDartCollector().fetch_disclosures(
            corp_code=None,
            stock_code="005930",
            bgn_de="20260630",
            end_de="20260630",
            corp_code_config=repo_root / "configs" / "opendart.corp_codes.example.yaml",
        )

    result = runner.invoke(
        app,
        [
            "fetch-opendart-disclosures",
            "--stock-code",
            "005930",
            "--bgn-de",
            "20260630",
            "--end-de",
            "20260630",
            "--corp-code-config",
            str(repo_root / "configs" / "opendart.corp_codes.example.yaml"),
        ],
    )
    assert result.exit_code == 1
    assert "Network access is disabled" in result.output


def test_opendart_missing_api_key_gives_clear_error(repo_root, monkeypatch):
    monkeypatch.setenv("PROJECT_STOCK_ALLOW_NETWORK", "true")
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_DART_API_KEY", raising=False)

    with pytest.raises(MissingApiKeyError, match="DART_API_KEY or OPEN_DART_API_KEY"):
        OpenDartCollector().fetch_disclosures(
            corp_code=None,
            stock_code="005930",
            bgn_de="20260630",
            end_de="20260630",
            corp_code_config=repo_root / "configs" / "opendart.corp_codes.example.yaml",
        )

    result = runner.invoke(
        app,
        [
            "fetch-opendart-disclosures",
            "--stock-code",
            "005930",
            "--bgn-de",
            "20260630",
            "--end-de",
            "20260630",
            "--corp-code-config",
            str(repo_root / "configs" / "opendart.corp_codes.example.yaml"),
        ],
    )
    assert result.exit_code == 1
    assert "DART_API_KEY or OPEN_DART_API_KEY" in result.output


def test_real_data_doctor_works_without_network(monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("ECOS_API_KEY", raising=False)

    result = runner.invoke(app, ["real-data-doctor"])

    assert result.exit_code == 0
    assert "PROJECT_STOCK_ALLOW_NETWORK" in result.output
    assert "no_auto_trade" in result.output
    assert "point_in_time_caution" in result.output


def test_opendart_doctor_works_without_network(repo_root, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_DART_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "opendart-doctor",
            "--corp-code-config",
            str(repo_root / "configs" / "opendart.corp_codes.example.yaml"),
        ],
    )

    assert result.exit_code == 0
    assert "PROJECT_STOCK_ALLOW_NETWORK" in result.output
    assert "OPEN_DART_API_KEY" in result.output
    assert "no_auto_trade" in result.output


def test_fred_fixture_parser(repo_root):
    payload = json.loads(
        _fixture(repo_root, "fred_observations_response.json").read_text(encoding="utf-8")
    )
    records = parse_fred_observation_response(
        payload,
        series_id="DGS10",
        raw_cache_path="data/raw/fred/DGS10.json",
        collected_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
    )

    assert len(records) == 1
    assert records[0].indicator_id == "DGS10"
    assert records[0].value == 4.24
    assert records[0].available_from >= records[0].release_at
    assert records[0].available_from >= records[0].collected_at
    assert records[0].metadata_json["raw_cache_path"] == "data/raw/fred/DGS10.json"


def test_ecos_fixture_parser(repo_root):
    series = load_ecos_series_config(repo_root / "configs" / "ecos.series.example.yaml")[
        "ECOS_BASE_RATE"
    ]
    payload = json.loads(
        _fixture(repo_root, "ecos_statistic_search_response.json").read_text(encoding="utf-8")
    )
    records = parse_ecos_statistic_search_response(
        payload,
        series=series,
        raw_cache_path="data/raw/ecos/ECOS_BASE_RATE.json",
        collected_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
    )

    assert len(records) == 1
    assert records[0].indicator_id == "ECOS_BASE_RATE"
    assert records[0].value == 2.5
    assert records[0].available_from >= records[0].release_at
    assert records[0].available_from >= records[0].collected_at
    assert records[0].metadata_json["stat_code"] == "722Y001"


def test_opendart_disclosure_list_fixture_parser(repo_root):
    payload = json.loads(
        _root_fixture(repo_root, "opendart_disclosure_list_response.json").read_text(encoding="utf-8")
    )
    records = parse_opendart_disclosure_list_response(
        payload,
        raw_cache_path="data/raw/opendart/disclosure_list.json",
        collected_at=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
    )

    assert len(records) == 2
    assert records[0].rcept_no == "20260630000001"
    assert records[0].corp_name == "Samsung Electronics"
    assert records[0].received_at.hour == 15
    assert records[0].available_from >= records[0].received_at
    assert records[0].available_from >= records[0].collected_at
    assert records[0].metadata_json["raw_cache_path"] == "data/raw/opendart/disclosure_list.json"


def test_fred_ingest_from_fixture(db_url, repo_root, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    result = runner.invoke(
        app,
        [
            "ingest-fred-series",
            "--series-id",
            "DGS10",
            "--start-date",
            "2026-06-29",
            "--end-date",
            "2026-06-30",
            "--fixture",
            str(_fixture(repo_root, "fred_observations_response.json")),
            "--db-url",
            db_url,
        ],
    )

    assert result.exit_code == 0
    assert '"inserted_count": 1' in result.output


def test_ecos_ingest_from_fixture(db_url, repo_root, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    result = runner.invoke(
        app,
        [
            "ingest-ecos-series",
            "--indicator-id",
            "ECOS_BASE_RATE",
            "--start-date",
            "2026-06-29",
            "--end-date",
            "2026-06-30",
            "--fixture",
            str(_fixture(repo_root, "ecos_statistic_search_response.json")),
            "--series-config",
            str(repo_root / "configs" / "ecos.series.example.yaml"),
            "--db-url",
            db_url,
        ],
    )

    assert result.exit_code == 0
    assert '"inserted_count": 1' in result.output


def test_opendart_raw_document_mapping_and_available_from(db_session, repo_root):
    result = OpenDartCollector().ingest_disclosures(
        db_session,
        corp_code=None,
        stock_code=None,
        bgn_de="19700101",
        end_de="29991231",
        fixture=_root_fixture(repo_root, "opendart_disclosure_list_response.json"),
    )
    documents = db_session.scalars(
        select(RawDocument).where(RawDocument.source_id == "OPEN_DART")
    ).all()

    assert result.inserted_count == 2
    assert len(documents) == 2
    assert documents[0].metadata_json["rcept_no"] == "20260630000001"
    assert documents[0].metadata_json["report_nm"]
    assert documents[0].checksum == "opendart:20260630000001"
    assert documents[0].available_from >= documents[0].published_at
    assert documents[0].available_from >= documents[0].collected_at


def test_opendart_rcept_no_dedupe(db_session, repo_root):
    collector = OpenDartCollector()

    first = collector.ingest_disclosures(
        db_session,
        corp_code=None,
        stock_code=None,
        bgn_de="19700101",
        end_de="29991231",
        fixture=_root_fixture(repo_root, "opendart_disclosure_list_response.json"),
    )
    second = collector.ingest_disclosures(
        db_session,
        corp_code=None,
        stock_code=None,
        bgn_de="19700101",
        end_de="29991231",
        fixture=_root_fixture(repo_root, "opendart_disclosure_list_response.json"),
    )

    assert first.inserted_count == 2
    assert second.inserted_count == 0
    assert second.skipped_count == 2


def test_real_adapter_available_from_safety(db_session, repo_root):
    result = FredCollector().ingest_series(
        db_session,
        series_id="DGS10",
        start_date="2026-06-29",
        end_date="2026-06-30",
        fixture=_fixture(repo_root, "fred_observations_response.json"),
    )
    observation = db_session.scalar(
        select(IndicatorObservation).where(IndicatorObservation.observation_id == result.record_ids[0])
    )

    assert observation.available_from >= observation.release_at
    assert observation.available_from >= observation.collected_at
    assert observation.metadata_json["source"] == "FRED"


def test_raw_cache_path_generation():
    path = build_raw_cache_path("fred", "DGS10", "2026-06-29", "2026-06-30")

    assert str(path).replace("\\", "/") == "data/raw/fred/DGS10_2026-06-29_2026-06-30.json"


def test_write_raw_response_cache(tmp_path):
    path = write_raw_response_cache({"ok": True}, tmp_path / "fred" / "sample.json")

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}


def test_opendart_raw_cache_path_generation_and_write(tmp_path):
    cache_path = build_timestamped_raw_cache_path(
        "opendart",
        "disclosure_list_005930",
        datetime(2026, 6, 30, 0, 0, tzinfo=UTC),
        data_dir=tmp_path,
    )
    written = write_raw_response_cache({"status": "000"}, cache_path)

    assert str(written).replace("\\", "/").endswith(
        "raw/opendart/disclosure_list_005930_20260630T000000Z.json"
    )
    assert json.loads(written.read_text(encoding="utf-8")) == {"status": "000"}


def test_opendart_fixture_ingest_command(db_url, repo_root):
    result = runner.invoke(
        app,
        [
            "ingest-opendart-disclosures-fixture",
            "--fixture",
            str(_root_fixture(repo_root, "opendart_disclosure_list_response.json")),
            "--db-url",
            db_url,
        ],
    )

    assert result.exit_code == 0
    assert '"inserted_count": 2' in result.output


def test_opendart_normalization_and_evidence_integration(db_session, repo_root):
    OpenDartCollector().ingest_disclosures(
        db_session,
        corp_code=None,
        stock_code=None,
        bgn_de="19700101",
        end_de="29991231",
        fixture=_root_fixture(repo_root, "opendart_disclosure_list_response.json"),
    )

    normalization = normalize_events(db_session)
    evidence = generate_evidence_candidates(db_session)

    assert normalization.inserted_event_ids
    assert normalization.entity_count > 0
    assert evidence.candidate_count > 0
    assert any(item.thesis_id == "KOR_SEMI_MEMORY_UPCYCLE" for item in evidence.candidates)
