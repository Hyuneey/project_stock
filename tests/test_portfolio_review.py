from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.db.models import DecisionLog
from project_stock.portfolio.review import (
    calculate_portfolio_exposure,
    evaluate_portfolio_flags,
    load_portfolio_config,
    load_portfolio_snapshot,
    review_portfolio_snapshot,
)
from project_stock.schemas.portfolio import PortfolioConfig, PortfolioHolding, PortfolioSnapshot, ThesisExposureBand
from project_stock.storage.repository import Repository


def _fixture(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures" / "portfolio_holdings_core_satellite.json"


def _config(repo_root: Path) -> Path:
    return repo_root / "configs" / "portfolio.example.yaml"


def _remove_api_keys(monkeypatch) -> None:
    for env_var in ("DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY", "NEWS_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)


def _append_state(db_session, thesis_id: str, status: str) -> None:
    Repository(db_session).append_thesis_snapshot(
        thesis_id=thesis_id,
        version="1.0",
        status=status,
        as_of=datetime(2026, 6, 28, tzinfo=UTC),
        state_reason=f"Test state {status}.",
        metadata_json={"test": True},
    )


def test_portfolio_config_loading(repo_root):
    config = load_portfolio_config(_config(repo_root))

    assert config.portfolio_id == "PERSONAL_CORE_SATELLITE"
    assert config.base_currency == "KRW"
    assert config.max_theme_exposure["KOR_SEMI_MEMORY_UPCYCLE"] == 0.25


def test_holdings_fixture_validation(repo_root):
    config = load_portfolio_config(_config(repo_root))
    snapshot = load_portfolio_snapshot(_fixture(repo_root), config, date(2026, 6, 29))

    assert snapshot.portfolio_id == config.portfolio_id
    assert len(snapshot.holdings) == 6
    assert any(holding.symbol == "005930" for holding in snapshot.holdings)


def test_exposure_calculation(repo_root):
    config = load_portfolio_config(_config(repo_root))
    snapshot = load_portfolio_snapshot(_fixture(repo_root), config, date(2026, 6, 29))

    exposure = calculate_portfolio_exposure(snapshot)

    assert exposure.total_market_value == 80000000
    assert exposure.cash_ratio == 0.3125
    assert exposure.total_equity_exposure == 0.6875
    assert exposure.foreign_currency_exposure["USD"] == 0.1375


def test_theme_and_thesis_exposure_calculation(repo_root):
    config = load_portfolio_config(_config(repo_root))
    snapshot = load_portfolio_snapshot(_fixture(repo_root), config, date(2026, 6, 29))

    exposure = calculate_portfolio_exposure(snapshot)

    assert exposure.theme_exposure["KOR_SEMI_MEMORY_UPCYCLE"] == 0.55
    assert exposure.thesis_exposure["KOR_SEMI_MEMORY_UPCYCLE"] == 0.55
    assert exposure.thesis_exposure["AI_INFRASTRUCTURE"] == 0.1375


def test_concentration_warning(repo_root):
    config = load_portfolio_config(_config(repo_root))
    snapshot = load_portfolio_snapshot(_fixture(repo_root), config, date(2026, 6, 29))
    exposure = calculate_portfolio_exposure(snapshot)

    flags = evaluate_portfolio_flags(
        exposure,
        config,
        {"KOR_SEMI_MEMORY_UPCYCLE": "active", "AI_INFRASTRUCTURE": "watch"},
    )

    assert any(flag.flag_type == "concentration_warning" for flag in flags)
    assert any(flag.symbol == "005930" for flag in flags)


def test_deteriorating_thesis_high_exposure_creates_reduce_risk_review(repo_root):
    config = load_portfolio_config(_config(repo_root))
    snapshot = load_portfolio_snapshot(_fixture(repo_root), config, date(2026, 6, 29))
    exposure = calculate_portfolio_exposure(snapshot)

    flags = evaluate_portfolio_flags(
        exposure,
        config,
        {"KOR_SEMI_MEMORY_UPCYCLE": "deteriorating", "AI_INFRASTRUCTURE": "active"},
    )

    assert any(
        flag.flag_type == "reduce_risk_review"
        and flag.thesis_id == "KOR_SEMI_MEMORY_UPCYCLE"
        for flag in flags
    )


def test_active_thesis_low_exposure_creates_under_exposed_review():
    config = PortfolioConfig(
        portfolio_id="TEST",
        base_currency="KRW",
        thesis_exposure_map={"AI_INFRASTRUCTURE": ThesisExposureBand(review_min=0.08)},
    )
    snapshot = PortfolioSnapshot(
        portfolio_id="TEST",
        as_of=date(2026, 6, 29),
        base_currency="KRW",
        holdings=[
            PortfolioHolding(
                symbol="CASH",
                name="Cash",
                market_value=950,
                currency="KRW",
                asset_type="cash",
            ),
            PortfolioHolding(
                symbol="AI_SMALL",
                name="AI small proxy",
                market_value=50,
                currency="KRW",
                asset_type="equity",
                theme_ids=["AI_INFRASTRUCTURE"],
                thesis_ids=["AI_INFRASTRUCTURE"],
                sector="Technology",
            ),
        ],
    )
    exposure = calculate_portfolio_exposure(snapshot)

    flags = evaluate_portfolio_flags(exposure, config, {"AI_INFRASTRUCTURE": "active"})

    assert any(flag.flag_type == "under_exposed_review" for flag in flags)


def test_missing_thesis_state_warning(repo_root):
    config = load_portfolio_config(_config(repo_root))
    snapshot = load_portfolio_snapshot(_fixture(repo_root), config, date(2026, 6, 29))
    exposure = calculate_portfolio_exposure(snapshot)

    flags = evaluate_portfolio_flags(exposure, config, {})

    assert any(flag.flag_type == "missing_thesis_state_warning" for flag in flags)


def test_decision_log_append_and_memo_creation(db_session, repo_root, tmp_path):
    _append_state(db_session, "KOR_SEMI_MEMORY_UPCYCLE", "deteriorating")
    _append_state(db_session, "AI_INFRASTRUCTURE", "active")
    config = load_portfolio_config(_config(repo_root))
    snapshot = load_portfolio_snapshot(_fixture(repo_root), config, date(2026, 6, 29))

    result = review_portfolio_snapshot(db_session, snapshot, config, memo_dir=tmp_path)
    decision = db_session.scalar(select(DecisionLog).where(DecisionLog.decision_type == "portfolio_review"))

    assert result.decision_id
    assert decision is not None
    assert decision.action == "review_only"
    assert decision.portfolio_impact == "human_review_required"
    assert decision.metadata_json["risk_flags"]
    memo = Path(result.memo_path or "")
    assert memo.exists()
    assert "No auto-trade" in memo.read_text(encoding="utf-8")


def test_cli_run_portfolio_review_demo(tmp_path, repo_root, monkeypatch):
    _remove_api_keys(monkeypatch)
    runner = CliRunner()
    db_url = f"sqlite:///{tmp_path / 'portfolio_demo.sqlite'}"

    result = runner.invoke(
        app,
        [
            "run-portfolio-review-demo",
            "--db-url",
            db_url,
            "--portfolio-fixture",
            str(_fixture(repo_root)),
            "--portfolio-config",
            str(_config(repo_root)),
            "--memo-dir",
            str(tmp_path),
            "--thesis-dir",
            str(repo_root / "thesis"),
            "--scenario-dir",
            str(repo_root / "scenarios"),
        ],
    )

    assert result.exit_code == 0
    assert "risk_flags" in result.output
    assert "decision_id" in result.output
