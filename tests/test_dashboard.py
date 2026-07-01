from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.dashboard.queries import (
    get_dashboard_snapshot,
    get_evidence_monitor,
    get_kor_semi_drilldown,
    get_latest_backtest_report,
    get_latest_decision_logs,
    get_latest_memo_links,
    get_latest_portfolio_review,
    get_latest_thesis_states,
    get_overview,
    get_scenario_emergency_monitor,
    get_thesis_evidence_summary,
    get_thesis_overview,
    get_thesis_related_decisions,
    get_thesis_related_events,
    get_thesis_scenario_triggers,
    get_top_thesis_evidence,
)
from project_stock.db.migrations import init_db
from project_stock.db.session import session_scope


def _remove_api_keys(monkeypatch) -> None:
    for env_var in (
        "DART_API_KEY",
        "OPEN_DART_API_KEY",
        "ECOS_API_KEY",
        "FRED_API_KEY",
        "KRX_AUTH_TOKEN",
        "KRX_API_KEY",
        "NEWS_API_KEY",
        "PROJECT_STOCK_ALLOW_NETWORK",
    ):
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


def _prepare_kor_semi_dashboard_demo(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch,
) -> tuple[str, Path]:
    _remove_api_keys(monkeypatch)
    runner = CliRunner()
    db_url = f"sqlite:///{tmp_path / 'kor_semi_dashboard.sqlite'}"
    memo_dir = tmp_path / "kor_semi_memos"
    result = runner.invoke(
        app,
        [
            "prepare-kor-semi-dashboard-demo",
            "--db-url",
            db_url,
            "--memo-dir",
            str(memo_dir),
            "--config",
            str(repo_root / "configs" / "real_data_smoke.kor_semi.example.yaml"),
            "--thesis-dir",
            str(repo_root / "thesis"),
            "--scenario-dir",
            str(repo_root / "scenarios" / "KOR_SEMI_MEMORY_UPCYCLE"),
            "--playbook-dir",
            str(repo_root / "playbooks"),
            "--big-flow-fixture",
            str(repo_root / "tests" / "fixtures" / "big_flow_kor_semi_v2.json"),
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


def test_kor_semi_dashboard_queries_empty_db_do_not_crash(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'empty_kor_semi.sqlite'}"
    init_db(db_url)

    with session_scope(db_url) as session:
        overview = get_thesis_overview(session, "KOR_SEMI_MEMORY_UPCYCLE")
        evidence = get_thesis_evidence_summary(session, "KOR_SEMI_MEMORY_UPCYCLE")
        drilldown = get_kor_semi_drilldown(session, tmp_path)

    assert overview["latest_state"] is None
    assert evidence == {"supports": 0, "contradicts": 0, "neutral": 0}
    assert drilldown["top_supporting_evidence"] == []
    assert drilldown["scenario_triggers"] == []
    assert drilldown["related_events"]["events"] == []


def test_prepare_kor_semi_dashboard_demo_command(tmp_path, repo_root, monkeypatch):
    db_url, memo_dir = _prepare_kor_semi_dashboard_demo(tmp_path, repo_root, monkeypatch)

    with session_scope(db_url) as session:
        overview = get_thesis_overview(session, "KOR_SEMI_MEMORY_UPCYCLE")
        evidence = get_thesis_evidence_summary(session, "KOR_SEMI_MEMORY_UPCYCLE")

    assert overview["latest_state"] is not None
    assert overview["big_flow_score"] is not None
    assert evidence["supports"] >= 1
    assert evidence["contradicts"] >= 1
    assert memo_dir.exists()


def test_kor_semi_dashboard_query_helpers_after_demo_data(tmp_path, repo_root, monkeypatch):
    db_url, memo_dir = _prepare_kor_semi_dashboard_demo(tmp_path, repo_root, monkeypatch)

    with session_scope(db_url) as session:
        supporting = get_top_thesis_evidence(session, "KOR_SEMI_MEMORY_UPCYCLE", "supports")
        contradicting = get_top_thesis_evidence(session, "KOR_SEMI_MEMORY_UPCYCLE", "contradicts")
        triggers = get_thesis_scenario_triggers(session, "KOR_SEMI_MEMORY_UPCYCLE")
        decisions = get_thesis_related_decisions(session, "KOR_SEMI_MEMORY_UPCYCLE")
        events = get_thesis_related_events(session, "KOR_SEMI_MEMORY_UPCYCLE")
        drilldown = get_kor_semi_drilldown(session, memo_dir)
    memos = get_latest_memo_links(memo_dir, thesis_id="KOR_SEMI_MEMORY_UPCYCLE")

    assert supporting
    assert contradicting
    assert triggers
    assert decisions
    assert any(decision["allowed_actions"] for decision in decisions)
    assert events["events_by_type"]
    assert events["financial_events"]
    assert events["market_events"]
    assert memos
    assert drilldown["memo_links"]
