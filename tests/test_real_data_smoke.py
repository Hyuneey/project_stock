from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.db.migrations import init_db
from project_stock.db.session import make_session_factory
from project_stock.operations.real_data_smoke import (
    DEFAULT_REAL_DATA_SMOKE_CONFIG,
    load_real_data_smoke_config,
    real_data_smoke_doctor_payload,
    run_real_data_smoke,
    validate_smoke_limits,
)

runner = CliRunner()


def _smoke_config(tmp_path: Path, repo_root: Path, **overrides: object) -> Path:
    payload = yaml.safe_load((repo_root / DEFAULT_REAL_DATA_SMOKE_CONFIG).read_text(encoding="utf-8"))
    payload["memo_dir"] = str(tmp_path / "memos")
    payload.update(overrides)
    path = tmp_path / "real_data_smoke.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _session(db_url: str):
    init_db(db_url)
    return make_session_factory(db_url)()


def test_smoke_config_loading(repo_root):
    config = load_real_data_smoke_config(repo_root / DEFAULT_REAL_DATA_SMOKE_CONFIG)

    assert config.smoke_id == "KOR_SEMI_REAL_DATA_SMOKE"
    assert config.thesis_ids == ["KOR_SEMI_MEMORY_UPCYCLE", "AI_INFRASTRUCTURE"]
    assert "DGS10" in config.fred_series
    assert "005930" in config.krx_symbols
    assert config.no_auto_trade is True


def test_real_data_smoke_doctor_works_without_network(repo_root, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_DART_API_KEY", raising=False)

    payload = real_data_smoke_doctor_payload(repo_root / DEFAULT_REAL_DATA_SMOKE_CONFIG)

    assert payload["network_enabled"] is False
    assert payload["no_auto_trade"] is True
    assert payload["safety_limits"]["estimated_records"] <= payload["safety_limits"]["max_records"]


def test_dry_run_makes_no_network_or_db_writes(tmp_path, repo_root, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    config_path = _smoke_config(tmp_path, repo_root)

    result = runner.invoke(app, ["run-real-data-smoke", "--config", str(config_path), "--dry-run"])

    assert result.exit_code == 0
    assert "dry_run" in result.output
    assert "dry_run_completed_without_network_or_database_writes" in result.output
    assert not (tmp_path / "test.sqlite").exists()


def test_missing_api_keys_report_exact_unavailable_sources(tmp_path, repo_root, db_url, monkeypatch):
    monkeypatch.setenv("PROJECT_STOCK_ALLOW_NETWORK", "true")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_DART_API_KEY", raising=False)
    config_path = _smoke_config(tmp_path, repo_root)

    result = runner.invoke(
        app,
        ["run-real-data-smoke", "--config", str(config_path), "--db-url", db_url],
    )

    assert result.exit_code == 1
    assert "FRED_API_KEY" in result.output
    assert "ECOS_API_KEY" in result.output
    assert "DART_API_KEY or OPEN_DART_API_KEY" in result.output


def test_network_disabled_blocks_real_smoke(tmp_path, repo_root, db_url, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    config_path = _smoke_config(tmp_path, repo_root)

    result = runner.invoke(
        app,
        ["run-real-data-smoke", "--config", str(config_path), "--db-url", db_url],
    )

    assert result.exit_code == 1
    assert "PROJECT_STOCK_ALLOW_NETWORK=true" in result.output


def test_fixture_smoke_end_to_end_counts_and_memo(tmp_path, repo_root, db_url, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    config_path = _smoke_config(tmp_path, repo_root)
    with _session(db_url) as session:
        result = run_real_data_smoke(config_path, mode="fixture", session=session)

    assert result.inserted_counts["FRED.indicator_observations"] == 4
    assert result.inserted_counts["BOK_ECOS.indicator_observations"] == 2
    assert result.inserted_counts["OPEN_DART.raw_documents"] == 2
    assert result.inserted_counts["OPEN_DART.financial_statement_line_items"] == 6
    assert result.inserted_counts["KRX.market_time_series"] == 2
    assert result.normalized_event_count > 0
    assert result.evidence_count > 0
    assert result.thesis_snapshot_count >= 1
    assert result.memo_path is not None
    memo = Path(result.memo_path).read_text(encoding="utf-8")
    assert "No auto-trade" in memo
    assert "Point-In-Time Limitations" in memo


def test_duplicate_fixture_smoke_skips_duplicates(tmp_path, repo_root, db_url):
    config_path = _smoke_config(tmp_path, repo_root)
    with _session(db_url) as session:
        first = run_real_data_smoke(config_path, mode="fixture", session=session)
        second = run_real_data_smoke(config_path, mode="fixture", session=session)

    assert first.evidence_count > 0
    assert second.inserted_counts["FRED.indicator_observations"] == 0
    assert second.skipped_duplicate_counts["FRED.indicator_observations"] == 4
    assert second.skipped_duplicate_counts["OPEN_DART.raw_documents"] == 2
    assert second.skipped_duplicate_counts["EvidenceLedger"] >= first.evidence_count
    assert second.thesis_snapshot_count == 0


def test_run_real_data_smoke_fixture_cli(tmp_path, repo_root, db_url):
    config_path = _smoke_config(tmp_path, repo_root)

    result = runner.invoke(
        app,
        ["run-real-data-smoke-fixture", "--config", str(config_path), "--db-url", db_url],
    )

    assert result.exit_code == 0
    assert '"mode": "fixture"' in result.output
    assert '"no_auto_trade": true' in result.output
    assert '"memo_path":' in result.output


def test_max_records_and_max_days_safety_guard(tmp_path, repo_root):
    records_config = load_real_data_smoke_config(_smoke_config(tmp_path, repo_root, max_records=1))
    with pytest.raises(ValueError, match="max_records"):
        validate_smoke_limits(records_config)

    days_config = load_real_data_smoke_config(_smoke_config(tmp_path, repo_root, max_days=1))
    with pytest.raises(ValueError, match="max_days"):
        validate_smoke_limits(days_config)


def test_no_broker_order_or_live_trading_logic_exists(repo_root):
    forbidden = {
        "place_order",
        "submit_order",
        "broker_execute",
        "live_buy",
        "live_sell",
        "auto_trade = True",
        "auto_trade=True",
    }
    python_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (repo_root / "src" / "project_stock").rglob("*.py")
    )

    assert [item for item in forbidden if item in python_text] == []
