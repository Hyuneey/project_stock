from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

from project_stock.config import DEFAULT_DB_URL
from project_stock.dashboard.queries import (
    get_dashboard_snapshot,
    get_evidence_monitor,
    get_event_filter_values,
    get_latest_backtest_report,
    get_latest_portfolio_review,
    get_latest_thesis_states,
    get_overview,
    get_recent_events,
    get_scenario_emergency_monitor,
)
from project_stock.db.migrations import init_db
from project_stock.db.session import session_scope


NO_AUTO_TRADE_DISCLAIMER = (
    "No auto-trade: this dashboard is a local review surface only. It does not "
    "create broker orders, live trading instructions, or LLM-directed buy/sell decisions."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Project Stock local dashboard")
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--memo-dir", default="data/processed")
    args, _unknown = parser.parse_known_args(argv)
    return args


def _table(st: Any, rows: object, empty_message: str) -> None:
    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.info(empty_message)


def _metric_grid(st: Any, values: dict[str, int]) -> None:
    columns = st.columns(3)
    for index, (label, value) in enumerate(values.items()):
        columns[index % len(columns)].metric(label, value)


def _render_overview(st: Any, db_url: str, memo_dir: Path) -> None:
    with session_scope(db_url) as session:
        overview = get_overview(session, db_url, memo_dir)
    st.subheader("Database")
    st.write(overview["db_url"])
    st.subheader("Counts")
    _metric_grid(st, overview["counts"])
    st.subheader("Latest Available Dates")
    st.dataframe(
        [{"field": key, "value": value} for key, value in overview["latest_available_dates"].items()],
        use_container_width=True,
    )
    st.subheader("Latest Memos")
    _table(st, overview["latest_memos"], "No memo artifacts found.")


def _render_event_monitor(st: Any, db_url: str) -> None:
    with session_scope(db_url) as session:
        filters = get_event_filter_values(session)
    event_type = st.selectbox("Event type", ["All"] + filters["event_types"])
    source_id = st.selectbox("Source", ["All"] + filters["source_ids"])
    with session_scope(db_url) as session:
        rows = get_recent_events(
            session,
            event_type=None if event_type == "All" else event_type,
            source_id=None if source_id == "All" else source_id,
        )
    _table(st, rows, "No events found.")


def _render_evidence_monitor(st: Any, db_url: str) -> None:
    with session_scope(db_url) as session:
        evidence = get_evidence_monitor(session)
    st.subheader("Evidence By Thesis")
    _table(
        st,
        [
            {"thesis_id": thesis_id, **counts}
            for thesis_id, counts in evidence["counts_by_thesis"].items()
        ],
        "No evidence rows found.",
    )
    st.subheader("Stance Counts")
    st.dataframe(
        [{"stance": key, "count": value} for key, value in evidence["stance_counts"].items()],
        use_container_width=True,
    )
    st.subheader("Top Evidence")
    _table(st, evidence["top_evidence"], "No evidence rows found.")
    st.subheader("Duplicate Evidence Skips")
    _table(
        st,
        evidence["duplicate_evidence_skips"],
        "No duplicate evidence skip metadata found in decision logs.",
    )


def _render_thesis_monitor(st: Any, db_url: str) -> None:
    with session_scope(db_url) as session:
        rows = get_latest_thesis_states(session)
    _table(st, rows, "No thesis state snapshots found.")


def _render_portfolio_review(st: Any, db_url: str) -> None:
    with session_scope(db_url) as session:
        review = get_latest_portfolio_review(session)
    if not review:
        st.info("No portfolio_review DecisionLog row found.")
        return
    st.subheader("Latest Portfolio Review")
    st.json(review["decision"])
    st.subheader("Exposure")
    exposure = review.get("exposure", {})
    if isinstance(exposure, dict):
        st.json(exposure)
    st.subheader("Risk Flags")
    _table(st, review.get("risk_flags", []), "No risk flags found.")
    st.info(NO_AUTO_TRADE_DISCLAIMER)


def _render_scenario_emergency(st: Any, db_url: str) -> None:
    with session_scope(db_url) as session:
        monitor = get_scenario_emergency_monitor(session)
    st.subheader("Scenario Triggers")
    _table(st, monitor["scenario_triggers"], "No scenario trigger logs found.")
    st.subheader("Latest Emergency Review")
    latest = monitor["latest_emergency_review"]
    if latest:
        st.json(latest)
    else:
        st.info("No emergency_risk_review DecisionLog row found.")


def _render_backtest_validation(st: Any, memo_dir: Path) -> None:
    report = get_latest_backtest_report(memo_dir)
    if not report:
        st.info("No backtest validation report artifact found.")
        return
    st.subheader("Latest Report")
    st.write(report["path"])
    st.subheader("Return / Risk Metrics")
    st.json(report["return_risk_metrics"])
    st.subheader("Diagnostic Metrics")
    st.json(report["diagnostic_metrics"])
    st.subheader("Point-In-Time Warnings")
    warnings = report["point_in_time_warnings"]
    if warnings:
        st.warning("\n".join(warnings))
    else:
        st.success("No point-in-time warnings.")


def render_dashboard(db_url: str, memo_dir: Path) -> None:
    import streamlit as st

    init_db(db_url)
    with session_scope(db_url) as session:
        snapshot = get_dashboard_snapshot(session, db_url, memo_dir)

    st.set_page_config(page_title="Project Stock Dashboard", layout="wide")
    st.title("Project Stock Dashboard")
    st.caption(NO_AUTO_TRADE_DISCLAIMER)
    counts = snapshot["overview"]["counts"]
    if isinstance(counts, dict) and not any(counts.values()):
        st.warning("The database is empty. Run `project-stock prepare-dashboard-demo` for demo data.")

    tabs = st.tabs(
        [
            "Overview",
            "Event Monitor",
            "Evidence Monitor",
            "Thesis State Monitor",
            "Portfolio Review",
            "Scenario / Emergency",
            "Backtest Validation",
        ]
    )
    with tabs[0]:
        _render_overview(st, db_url, memo_dir)
    with tabs[1]:
        _render_event_monitor(st, db_url)
    with tabs[2]:
        _render_evidence_monitor(st, db_url)
    with tabs[3]:
        _render_thesis_monitor(st, db_url)
    with tabs[4]:
        _render_portfolio_review(st, db_url)
    with tabs[5]:
        _render_scenario_emergency(st, db_url)
    with tabs[6]:
        _render_backtest_validation(st, memo_dir)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    render_dashboard(args.db_url, Path(args.memo_dir))


if __name__ == "__main__":
    main()
