from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from project_stock.backtest.validation import (
    compute_validation_metrics,
    load_backtest_config,
    load_market_returns,
    load_portfolio_snapshots,
    load_signal_snapshots,
    render_backtest_report,
    run_backtest,
    run_backtest_demo,
    validate_point_in_time_signals,
)
from project_stock.cli import app
from project_stock.schemas.backtest import BacktestConfig, BacktestSignalSnapshot


def _config(repo_root: Path) -> Path:
    return repo_root / "configs" / "backtest.example.yaml"


def _market_returns(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures" / "backtest_market_returns.csv"


def _thesis_states(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures" / "backtest_thesis_states.json"


def _portfolio_flags(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures" / "backtest_portfolio_flags.json"


def _portfolio_snapshots(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures" / "backtest_portfolio_snapshots.json"


def _load_inputs(repo_root: Path):
    config = load_backtest_config(_config(repo_root))
    returns = load_market_returns(_market_returns(repo_root))
    signals = load_signal_snapshots(_thesis_states(repo_root)) + load_signal_snapshots(
        _portfolio_flags(repo_root)
    )
    snapshots = load_portfolio_snapshots(_portfolio_snapshots(repo_root))
    return config, returns, signals, snapshots


def _with_policy(config: BacktestConfig, policy_name: str) -> BacktestConfig:
    return config.model_copy(
        update={
            "policy_name": policy_name,
            "policy": config.policy.model_copy(update={"policy_name": policy_name}),
        }
    )


def _without_costs(config: BacktestConfig) -> BacktestConfig:
    return config.model_copy(update={"transaction_cost_bps": 0.0, "slippage_bps": 0.0})


def _remove_api_keys(monkeypatch) -> None:
    for env_var in ("DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY", "NEWS_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)


def test_backtest_config_loading(repo_root):
    config = load_backtest_config(_config(repo_root))

    assert config.backtest_id == "MVP_FIXTURE_BACKTEST"
    assert config.no_auto_trade is True
    assert config.policy.thesis_symbol_map["KOR_SEMI_MEMORY_UPCYCLE"] == [
        "005930",
        "000660",
        "KODEX_SEMI",
    ]


def test_backtest_fixture_loading(repo_root):
    config, returns, signals, snapshots = _load_inputs(repo_root)

    assert config.start_date == date(2026, 1, 31)
    assert len(returns) == 36
    assert len(signals) == 5
    assert snapshots[0].exposures["CASH_KRW"] == 0.30


def test_point_in_time_signal_guard_rejects_future_signal():
    future_signal = BacktestSignalSnapshot(
        signal_id="FUTURE_SIGNAL",
        signal_date=date(2026, 4, 30),
        available_from=date(2026, 5, 31),
        signal_type="thesis_state",
        thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
        state="deteriorating",
    )

    with pytest.raises(ValueError, match="cannot be used early"):
        validate_point_in_time_signals([future_signal], strict=True)


def test_future_signal_is_ignored_until_available(repo_root):
    config, returns, _signals, snapshots = _load_inputs(repo_root)
    future_signal = BacktestSignalSnapshot(
        signal_id="FUTURE_SIGNAL",
        signal_date=date(2026, 4, 30),
        available_from=date(2026, 5, 31),
        signal_type="thesis_state",
        thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
        state="deteriorating",
    )

    result = run_backtest(config, returns, snapshots, [future_signal], strict_point_in_time=False)

    assert result.point_in_time_warnings
    assert not any(record.date == date(2026, 4, 30) for record in result.trade_records)
    assert any(record.date == date(2026, 5, 31) for record in result.trade_records)


def test_static_portfolio_performance_calculation(repo_root):
    config, returns, signals, snapshots = _load_inputs(repo_root)
    result = run_backtest(_with_policy(config, "static_portfolio"), returns, snapshots, signals)

    assert result.period_returns["2026-01-31"] == 0.01965
    assert result.metrics.average_turnover == 0.0
    assert result.metrics.transaction_cost_impact == 0.0


def test_thesis_state_risk_overlay_policy(repo_root):
    config, returns, signals, snapshots = _load_inputs(repo_root)
    result = run_backtest(config, returns, snapshots, signals)

    changed_symbols = {record.symbol for record in result.trade_records if record.date == date(2026, 4, 30)}

    assert {"005930", "000660", "KODEX_SEMI", "CASH_KRW"}.issubset(changed_symbols)
    assert all(record.hypothetical_only for record in result.trade_records)


def test_portfolio_review_flag_overlay_policy(repo_root):
    config, returns, signals, snapshots = _load_inputs(repo_root)
    result = run_backtest(
        _with_policy(config, "portfolio_review_flag_overlay"),
        returns,
        snapshots,
        signals,
    )

    assert any("over_exposed_review" in record.policy_reason for record in result.trade_records)
    assert result.metrics.hit_ratio_review_flags == 1.0


def test_transaction_cost_application(repo_root):
    config, returns, signals, snapshots = _load_inputs(repo_root)
    cost_result = run_backtest(config, returns, snapshots, signals)
    no_cost_result = run_backtest(_without_costs(config), returns, snapshots, signals)

    assert cost_result.metrics.transaction_cost_impact > 0
    assert no_cost_result.metrics.transaction_cost_impact == 0
    assert no_cost_result.metrics.cumulative_return > cost_result.metrics.cumulative_return


def test_max_drawdown_calculation(repo_root):
    config, returns, signals, snapshots = _load_inputs(repo_root)
    result = run_backtest(config, returns, snapshots, signals)

    assert result.metrics.max_drawdown < 0
    assert result.metrics.calmar_ratio is not None


def test_benchmark_relative_return(repo_root):
    config, returns, signals, snapshots = _load_inputs(repo_root)
    result = run_backtest(config, returns, snapshots, signals)

    assert result.metrics.benchmark_cumulative_return != 0
    assert result.metrics.benchmark_relative_return == round(
        result.metrics.cumulative_return - result.metrics.benchmark_cumulative_return,
        8,
    )


def test_validation_metrics(repo_root):
    config, returns, signals, _snapshots = _load_inputs(repo_root)
    metrics, counts = compute_validation_metrics(config, signals, returns)

    assert metrics["deterioration_precision"] == 1.0
    assert metrics["portfolio_flag_usefulness"] == 1.0
    assert counts["portfolio_review_flags"] == 1


def test_backtest_report_creation(repo_root, tmp_path):
    config, returns, signals, snapshots = _load_inputs(repo_root)
    result = run_backtest(config, returns, snapshots, signals)

    report = render_backtest_report(result, memo_dir=tmp_path)
    report_text = Path(report.report_path).read_text(encoding="utf-8")

    assert Path(report.report_path).exists()
    assert "No auto-trade" in report_text
    assert "Benchmark relative return" in report_text


def test_cli_run_backtest_demo(repo_root, tmp_path, monkeypatch):
    _remove_api_keys(monkeypatch)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run-backtest-demo",
            "--config",
            str(_config(repo_root)),
            "--market-returns",
            str(_market_returns(repo_root)),
            "--thesis-states",
            str(_thesis_states(repo_root)),
            "--portfolio-flags",
            str(_portfolio_flags(repo_root)),
            "--portfolio-snapshots",
            str(_portfolio_snapshots(repo_root)),
            "--memo-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "report_path" in result.output
    assert "benchmark_relative_return" in result.output


def test_run_backtest_demo_writes_report(repo_root, tmp_path):
    result, report = run_backtest_demo(
        config_path=_config(repo_root),
        market_returns_path=_market_returns(repo_root),
        thesis_states_path=_thesis_states(repo_root),
        portfolio_flags_path=_portfolio_flags(repo_root),
        portfolio_snapshots_path=_portfolio_snapshots(repo_root),
        memo_dir=tmp_path,
    )

    assert result.benchmark_metrics is not None
    assert Path(report.report_path).exists()
    assert report.no_auto_trade is True


def test_no_live_order_or_broker_execution_objects(repo_root):
    config, returns, signals, snapshots = _load_inputs(repo_root)
    result = run_backtest(config, returns, snapshots, signals)

    assert not hasattr(result, "orders")
    assert all(record.hypothetical_only for record in result.trade_records)
    assert all("broker" not in record.policy_reason.lower() for record in result.trade_records)
