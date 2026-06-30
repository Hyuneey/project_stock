from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.dashboard.queries import (
    get_dashboard_snapshot,
    get_evidence_monitor,
    get_latest_backtest_report,
    get_latest_decision_logs,
    get_latest_portfolio_review,
    get_latest_thesis_states,
    get_overview,
    get_scenario_emergency_monitor,
)
from project_stock.db.migrations import init_db
from project_stock.db.session import session_scope


def _remove_api_keys(monkeypatch) -> None:
    for env_var in ("DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY", "NEWS_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)


def _prepare_dashboard_demo(tmp_path: Path, repo_root: Path, monkeypatch) -> tuple[str, Path]:
    _remove_api_keys(monkeypatch)
    runner = CliRunner()
    db_url = f"sqlite:///{tmp_path / 'dashboard_demo.sqlite'}"
    memo_dir = tmp_path / "memos"
    result = runner.invoke(
        app,
        [
            "prepare-dashboard-demo",
            "--db-url",
            db_url,
            "--memo-dir",
            str(memo_dir),
            "--thesis-dir",
            str(repo_root / "thesis"),
            "--scenario-dir",
            str(repo_root / "scenarios"),
            "--playbook-dir",
            str(repo_root / "playbooks"),
            "--fixture-dir",
            str(repo_root / "tests" / "fixtures" / "official"),
            "--portfolio-fixture",
            str(repo_root / "tests" / "fixtures" / "portfolio_holdings_core_satellite.json"),
            "--portfolio-config",
            str(repo_root / "configs" / "portfolio.example.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "dashboard_command" in result.output
    assert "no_auto_trade" in result.output
    return db_url, memo_dir


def test_dashboard_queries_empty_db_do_not_crash(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'empty.sqlite'}"
    init_db(db_url)

    with session_scope(db_url) as session:
        snapshot = get_dashboard_snapshot(session, db_url, tmp_path)

    assert all(value == 0 for value in snapshot["overview"]["counts"].values())
    assert snapshot["events"] == []
    assert snapshot["evidence"]["top_evidence"] == []
    assert snapshot["thesis_states"] == []
    assert snapshot["portfolio_review"] is None
    assert snapshot["backtest_validation"] is None


def test_prepare_dashboard_demo_command(tmp_path, repo_root, monkeypatch):
    db_url, memo_dir = _prepare_dashboard_demo(tmp_path, repo_root, monkeypatch)

    with session_scope(db_url) as session:
        overview = get_overview(session, db_url, memo_dir)

    assert overview["counts"]["Event"] > 0
    assert overview["counts"]["EvidenceLedger"] > 0
    assert overview["latest_memos"]


def test_dashboard_queries_after_demo_data(tmp_path, repo_root, monkeypatch):
    db_url, memo_dir = _prepare_dashboard_demo(tmp_path, repo_root, monkeypatch)

    with session_scope(db_url) as session:
        snapshot = get_dashboard_snapshot(session, db_url, memo_dir)

    assert snapshot["overview"]["counts"]["RawDocument"] > 0
    assert snapshot["overview"]["counts"]["DecisionLog"] > 0
    assert snapshot["events"]
    assert snapshot["backtest_validation"] is not None


def test_latest_thesis_state_query(tmp_path, repo_root, monkeypatch):
    db_url, memo_dir = _prepare_dashboard_demo(tmp_path, repo_root, monkeypatch)

    with session_scope(db_url) as session:
        states = get_latest_thesis_states(session)

    assert {state["thesis_id"] for state in states} >= {
        "KOR_SEMI_MEMORY_UPCYCLE",
        "AI_INFRASTRUCTURE",
    }
    assert all("transition_reasons" in state for state in states)
    assert memo_dir.exists()


def test_latest_evidence_counts(tmp_path, repo_root, monkeypatch):
    db_url, _memo_dir = _prepare_dashboard_demo(tmp_path, repo_root, monkeypatch)

    with session_scope(db_url) as session:
        evidence = get_evidence_monitor(session)

    assert evidence["counts_by_thesis"]["KOR_SEMI_MEMORY_UPCYCLE"]
    assert evidence["stance_counts"]
    assert evidence["top_evidence"]
    assert evidence["duplicate_evidence_skips"]


def test_latest_decision_logs_and_portfolio_review(tmp_path, repo_root, monkeypatch):
    db_url, _memo_dir = _prepare_dashboard_demo(tmp_path, repo_root, monkeypatch)

    with session_scope(db_url) as session:
        decisions = get_latest_decision_logs(session)
        portfolio = get_latest_portfolio_review(session)

    assert decisions
    assert any(decision["decision_type"] == "portfolio_review" for decision in decisions)
    assert portfolio is not None
    assert portfolio["risk_flags"]
    assert portfolio["no_auto_trade"] is True


def test_latest_scenario_triggers_and_backtest_report(tmp_path, repo_root, monkeypatch):
    db_url, memo_dir = _prepare_dashboard_demo(tmp_path, repo_root, monkeypatch)

    with session_scope(db_url) as session:
        scenario_emergency = get_scenario_emergency_monitor(session)
    backtest = get_latest_backtest_report(memo_dir)

    assert scenario_emergency["scenario_triggers"]
    assert backtest is not None
    assert backtest["return_risk_metrics"]
    assert backtest["diagnostic_metrics"]


def test_run_dashboard_prints_launch_command(tmp_path, monkeypatch):
    _remove_api_keys(monkeypatch)
    runner = CliRunner()
    db_url = f"sqlite:///{tmp_path / 'dashboard.sqlite'}"

    result = runner.invoke(
        app,
        [
            "run-dashboard",
            "--db-url",
            db_url,
            "--memo-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "streamlit" in result.output
    assert "app.py" in result.output
