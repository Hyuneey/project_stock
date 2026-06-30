from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.db.models import FinancialStatementLineItem
from project_stock.events.financials import normalize_financial_events
from project_stock.evidence.generation import generate_evidence_candidates
from project_stock.ingest.opendart_financials import (
    OpenDartFinancialCollector,
    build_financial_raw_cache_path,
    financial_event_type,
    load_opendart_corp_codes,
    normalize_summary_account,
    parse_amount,
    parse_opendart_financial_statement_response,
    resolve_corp_code,
)
from project_stock.ingest.real_data import (
    MissingApiKeyError,
    MissingCorpCodeMappingError,
    NetworkDisabledError,
    UnsupportedReportCodeError,
    write_raw_response_cache,
)


runner = CliRunner()


def _fixture(repo_root, name: str):
    return repo_root / "tests" / "fixtures" / name


def _corp_config(repo_root):
    return repo_root / "configs" / "opendart.corp_codes.example.yaml"


def test_opendart_financial_fixture_parser(repo_root):
    payload = json.loads(
        _fixture(repo_root, "opendart_financial_statement_response.json").read_text(encoding="utf-8")
    )
    records = parse_opendart_financial_statement_response(
        payload,
        corp_code="00126380",
        stock_code="005930",
        bsns_year="2026",
        reprt_code="11013",
        raw_cache_path="data/raw/opendart/financial/sample.json",
        collected_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
    )

    assert len(records) == 6
    assert records[0].corp_code == "00126380"
    assert records[0].stock_code == "005930"
    assert records[0].account_name == "매출액"
    assert records[0].current_amount == 100000
    assert records[0].previous_amount == 80000
    assert records[0].available_from >= records[0].collected_at
    assert records[0].metadata_json["raw_cache_path"] == "data/raw/opendart/financial/sample.json"


def test_opendart_financial_amount_parsing():
    assert parse_amount("1,234") == 1234
    assert parse_amount("(5,000)") == -5000
    assert parse_amount("-10") == -10
    assert parse_amount("-") is None


def test_corp_code_lookup_by_stock_code(repo_root):
    corp_code, stock_code, company = resolve_corp_code(None, "005930", _corp_config(repo_root))

    assert corp_code == "00126380"
    assert stock_code == "005930"
    assert company is not None
    assert company.corp_name == "Samsung Electronics"


def test_missing_corp_code_mapping(repo_root):
    with pytest.raises(MissingCorpCodeMappingError, match="stock_code '123456'"):
        resolve_corp_code(None, "123456", _corp_config(repo_root))


def test_valid_corp_code_mapping_file(repo_root):
    mappings = load_opendart_corp_codes(_corp_config(repo_root))

    assert sorted(mappings) == ["000660", "005930"]


def test_unsupported_report_code_blocks_fetch(repo_root):
    with pytest.raises(UnsupportedReportCodeError, match="Unsupported OpenDART reprt_code"):
        OpenDartFinancialCollector().fetch_financials(
            corp_code=None,
            stock_code="005930",
            bsns_year="2026",
            reprt_code="99999",
            corp_code_config=_corp_config(repo_root),
            fixture=_fixture(repo_root, "opendart_financial_statement_response.json"),
        )


def test_network_disabled_blocks_real_financial_fetch(repo_root, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    monkeypatch.setenv("DART_API_KEY", "test-key")

    with pytest.raises(NetworkDisabledError, match="PROJECT_STOCK_ALLOW_NETWORK=true"):
        OpenDartFinancialCollector().fetch_financials(
            corp_code=None,
            stock_code="005930",
            bsns_year="2026",
            reprt_code="11013",
            corp_code_config=_corp_config(repo_root),
        )


def test_missing_api_key_gives_clear_error(repo_root, monkeypatch):
    monkeypatch.setenv("PROJECT_STOCK_ALLOW_NETWORK", "true")
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_DART_API_KEY", raising=False)

    with pytest.raises(MissingApiKeyError, match="DART_API_KEY or OPEN_DART_API_KEY"):
        OpenDartFinancialCollector().fetch_financials(
            corp_code=None,
            stock_code="005930",
            bsns_year="2026",
            reprt_code="11013",
            corp_code_config=_corp_config(repo_root),
        )


def test_fixture_ingest_inserts_line_items(db_session, repo_root):
    result = OpenDartFinancialCollector().ingest_financials(
        db_session,
        corp_code=None,
        stock_code="005930",
        bsns_year="2026",
        reprt_code="11013",
        corp_code_config=_corp_config(repo_root),
        fixture=_fixture(repo_root, "opendart_financial_statement_response.json"),
    )
    rows = db_session.scalars(select(FinancialStatementLineItem)).all()

    assert result.inserted_count == 6
    assert len(rows) == 6
    assert rows[0].available_from >= rows[0].collected_at


def test_duplicate_line_items_skipped(db_session, repo_root):
    collector = OpenDartFinancialCollector()

    first = collector.ingest_financials(
        db_session,
        corp_code=None,
        stock_code="005930",
        bsns_year="2026",
        reprt_code="11013",
        corp_code_config=_corp_config(repo_root),
        fixture=_fixture(repo_root, "opendart_financial_statement_response.json"),
    )
    second = collector.ingest_financials(
        db_session,
        corp_code=None,
        stock_code="005930",
        bsns_year="2026",
        reprt_code="11013",
        corp_code_config=_corp_config(repo_root),
        fixture=_fixture(repo_root, "opendart_financial_statement_response.json"),
    )

    assert first.inserted_count == 6
    assert second.inserted_count == 0
    assert second.skipped_count == 6


def test_financial_raw_cache_path_generation_and_write(tmp_path):
    path = build_financial_raw_cache_path(
        "00126380",
        "2026",
        "11013",
        datetime(2026, 6, 30, 0, 0, tzinfo=UTC),
        data_dir=tmp_path,
    )
    written = write_raw_response_cache({"status": "000"}, path)

    assert str(written).replace("\\", "/").endswith(
        "raw/opendart/financial/00126380_2026_11013_20260630T000000Z.json"
    )
    assert json.loads(written.read_text(encoding="utf-8")) == {"status": "000"}


def test_summary_account_mapping_and_financial_event_types():
    assert normalize_summary_account("매출액") == "revenue"
    assert normalize_summary_account("영업이익") == "operating_income"
    assert normalize_summary_account("자산총계") == "total_assets"
    assert financial_event_type("매출액", 100, 80) == "revenue_growth_candidate"
    assert financial_event_type("영업이익", -5, 10) == "margin_pressure_candidate"
    assert financial_event_type("부채총계", 260, 200) == "leverage_change_candidate"


def test_financial_event_normalization_and_evidence_integration(db_session, repo_root):
    OpenDartFinancialCollector().ingest_financials(
        db_session,
        corp_code=None,
        stock_code="005930",
        bsns_year="2026",
        reprt_code="11013",
        corp_code_config=_corp_config(repo_root),
        fixture=_fixture(repo_root, "opendart_financial_statement_response.json"),
    )

    normalization = normalize_financial_events(db_session)
    evidence = generate_evidence_candidates(db_session)

    assert normalization.inserted_event_ids
    assert "revenue_growth_candidate" in normalization.counts_by_event_type
    assert "margin_pressure_candidate" in normalization.counts_by_event_type
    assert evidence.candidate_count > 0


def test_ingest_opendart_financials_fixture_command(db_url, repo_root):
    result = runner.invoke(
        app,
        [
            "ingest-opendart-financials-fixture",
            "--fixture",
            str(_fixture(repo_root, "opendart_financial_statement_response.json")),
            "--stock-code",
            "005930",
            "--bsns-year",
            "2026",
            "--reprt-code",
            "11013",
            "--corp-code-config",
            str(_corp_config(repo_root)),
            "--db-url",
            db_url,
        ],
    )

    assert result.exit_code == 0
    assert '"inserted_count": 6' in result.output
