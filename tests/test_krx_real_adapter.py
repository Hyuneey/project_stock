from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.db.models import Event, MarketTimeSeries
from project_stock.events.normalization import detect_market_events
from project_stock.evidence.generation import generate_evidence_candidates
from project_stock.ingest.krx import (
    KrxCollector,
    build_krx_raw_cache_path,
    load_krx_symbols,
    parse_krx_daily_market_response,
    parse_krx_number,
    resolve_krx_symbol,
)
from project_stock.ingest.real_data import (
    MissingApiKeyError,
    NetworkDisabledError,
    UnsupportedMarketDataTypeError,
    UnsupportedSymbolError,
    write_raw_response_cache,
)


runner = CliRunner()


def _fixture(repo_root, name: str):
    return repo_root / "tests" / "fixtures" / name


def _symbol_config(repo_root):
    return repo_root / "configs" / "krx.symbols.example.yaml"


def test_krx_symbol_config_loading(repo_root):
    symbols = load_krx_symbols(_symbol_config(repo_root))

    assert sorted(symbols) == ["000660", "005930", "KOSPI200", "SEMI_ETF_PROXY"]
    assert symbols["005930"].asset_type == "stock"
    assert symbols["KOSPI200"].asset_type == "index"


def test_unsupported_symbol_error(repo_root):
    with pytest.raises(UnsupportedSymbolError, match="Unsupported KRX symbol"):
        resolve_krx_symbol("123456", _symbol_config(repo_root))


def test_unsupported_market_data_type_error(tmp_path):
    config = tmp_path / "krx.symbols.yaml"
    config.write_text(
        """
symbols:
  - symbol: BAD
    name: Bad Symbol
    market: KOSPI
    asset_type: derivative
    currency: KRW
""",
        encoding="utf-8",
    )

    with pytest.raises(UnsupportedMarketDataTypeError, match="Unsupported KRX market data type"):
        resolve_krx_symbol("BAD", config)


def test_krx_fixture_parser(repo_root):
    symbol = resolve_krx_symbol("005930", _symbol_config(repo_root))
    payload = json.loads(_fixture(repo_root, "krx_daily_market_response.json").read_text(encoding="utf-8"))
    rows = parse_krx_daily_market_response(
        payload,
        symbol_config=symbol,
        collected_at=datetime(2026, 6, 30, 1, 0, tzinfo=UTC),
        raw_cache_path="data/raw/krx/sample.json",
    )

    assert len(rows) == 2
    assert rows[0].symbol == "005930"
    assert rows[0].frequency == "daily"
    assert rows[0].open == 69800
    assert rows[0].close == 70000
    assert rows[0].volume == 10000000
    assert rows[0].metadata_json["asset_type"] == "stock"
    assert rows[0].metadata_json["raw_cache_path"] == "data/raw/krx/sample.json"
    assert rows[0].available_from >= rows[0].timestamp
    assert rows[0].available_from >= rows[0].collected_at


def test_krx_number_parser():
    assert parse_krx_number("955,500,000,000") == 955500000000
    assert parse_krx_number("-") is None
    assert parse_krx_number("5.25%") == 5.25


def test_network_disabled_blocks_real_krx_fetch(repo_root, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)

    with pytest.raises(NetworkDisabledError, match="PROJECT_STOCK_ALLOW_NETWORK=true"):
        KrxCollector().fetch_daily(
            symbol="005930",
            start_date="2026-06-26",
            end_date="2026-06-29",
            symbol_config=_symbol_config(repo_root),
        )


def test_missing_credentials_error_if_auth_required(repo_root, monkeypatch):
    monkeypatch.setenv("PROJECT_STOCK_ALLOW_NETWORK", "true")
    monkeypatch.delenv("KRX_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("KRX_API_KEY", raising=False)

    with pytest.raises(MissingApiKeyError, match="KRX_AUTH_TOKEN or KRX_API_KEY"):
        KrxCollector().fetch_daily(
            symbol="005930",
            start_date="2026-06-26",
            end_date="2026-06-29",
            symbol_config=_symbol_config(repo_root),
            require_auth=True,
        )


def test_krx_doctor_works_without_network(repo_root, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    result = runner.invoke(
        app,
        [
            "krx-doctor",
            "--symbol-config",
            str(_symbol_config(repo_root)),
        ],
    )

    assert result.exit_code == 0
    assert '"PROJECT_STOCK_ALLOW_NETWORK": false' in result.output
    assert '"no_auto_trade": true' in result.output


def test_fixture_ingest_inserts_market_time_series(db_session, repo_root):
    result = KrxCollector().ingest_daily(
        db_session,
        symbol="005930",
        start_date="2026-06-26",
        end_date="2026-06-29",
        symbol_config=_symbol_config(repo_root),
        fixture=_fixture(repo_root, "krx_daily_market_response.json"),
    )
    rows = db_session.scalars(select(MarketTimeSeries).where(MarketTimeSeries.source_id == "KRX")).all()

    assert result.inserted_count == 2
    assert len(rows) == 2
    assert rows[0].available_from >= rows[0].timestamp
    assert rows[0].metadata_json["sector"] == "SEMICONDUCTOR"


def test_duplicate_daily_bars_skipped(db_session, repo_root):
    collector = KrxCollector()
    first = collector.ingest_daily(
        db_session,
        symbol="005930",
        start_date="2026-06-26",
        end_date="2026-06-29",
        symbol_config=_symbol_config(repo_root),
        fixture=_fixture(repo_root, "krx_daily_market_response.json"),
    )
    second = collector.ingest_daily(
        db_session,
        symbol="005930",
        start_date="2026-06-26",
        end_date="2026-06-29",
        symbol_config=_symbol_config(repo_root),
        fixture=_fixture(repo_root, "krx_daily_market_response.json"),
    )

    assert first.inserted_count == 2
    assert second.inserted_count == 0
    assert second.skipped_count == 2


def test_krx_raw_cache_path_generation_and_write(tmp_path):
    path = build_krx_raw_cache_path(
        "005930",
        "2026-06-26",
        "2026-06-29",
        datetime(2026, 6, 30, 0, 0, tzinfo=UTC),
        data_dir=tmp_path,
    )
    written = write_raw_response_cache({"records": []}, path)

    assert str(written).replace("\\", "/").endswith(
        "raw/krx/005930_2026-06-26_2026-06-29_20260630T000000Z.json"
    )
    assert json.loads(written.read_text(encoding="utf-8")) == {"records": []}


def test_ingest_krx_daily_fixture_command(db_url, repo_root):
    result = runner.invoke(
        app,
        [
            "ingest-krx-daily-fixture",
            "--fixture",
            str(_fixture(repo_root, "krx_daily_market_response.json")),
            "--symbol",
            "005930",
            "--start-date",
            "2026-06-26",
            "--end-date",
            "2026-06-29",
            "--symbol-config",
            str(_symbol_config(repo_root)),
            "--db-url",
            db_url,
        ],
    )

    assert result.exit_code == 0
    assert '"inserted_count": 2' in result.output


def test_market_event_detection_and_evidence_integration(db_session, repo_root):
    KrxCollector().ingest_daily(
        db_session,
        symbol="005930",
        start_date="2026-06-26",
        end_date="2026-06-29",
        symbol_config=_symbol_config(repo_root),
        fixture=_fixture(repo_root, "krx_daily_market_response.json"),
    )

    detected = detect_market_events(db_session)
    events = db_session.scalars(select(Event)).all()
    evidence = generate_evidence_candidates(db_session)

    assert detected.counts_by_event_type == {"market_large_move": 1}
    assert len(events) == 1
    assert detected.entity_count > 0
    assert evidence.candidate_count > 0
