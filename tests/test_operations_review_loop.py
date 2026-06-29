from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.db.models import DecisionLog, Event, EvidenceLedger, IndicatorObservation, MarketTimeSeries, RawDocument
from project_stock.operations.review_loop import run_daily_review_loop, run_intraday_review_loop


def _fixture_dir(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures" / "official"


def _emergency_payload(repo_root: Path) -> dict[str, object]:
    return json.loads((repo_root / "tests" / "fixtures" / "emergency_rate_shock.json").read_text())


def _remove_api_keys(monkeypatch) -> None:
    for env_var in ("DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY", "NEWS_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)


def _source_record_counts(db_session) -> dict[str, int]:
    return {
        "raw_documents": len(db_session.scalars(select(RawDocument)).all()),
        "indicator_observations": len(db_session.scalars(select(IndicatorObservation)).all()),
        "market_time_series": len(db_session.scalars(select(MarketTimeSeries)).all()),
        "events": len(db_session.scalars(select(Event)).all()),
        "evidence": len(db_session.scalars(select(EvidenceLedger)).all()),
    }


def test_daily_review_loop_end_to_end(db_session, repo_root, tmp_path, monkeypatch):
    _remove_api_keys(monkeypatch)

    result = run_daily_review_loop(
        as_of=date(2026, 6, 29),
        db_session=db_session,
        thesis_dir=repo_root / "thesis",
        scenario_dir=repo_root / "scenarios",
        playbook_dir=repo_root / "playbooks",
        fixture_dir=_fixture_dir(repo_root),
        memo_dir=tmp_path,
        ingest_mock=True,
    )

    assert result.inserted_raw_counts["OPEN_DART"] == 1
    assert result.inserted_event_count > 0
    assert result.appended_evidence_count > 0
    assert result.scenario_match_count > 0
    assert result.decision_log_count == 1
    assert result.evidence_counts_by_thesis["KOR_SEMI_MEMORY_UPCYCLE"] > 0
    assert db_session.scalars(select(EvidenceLedger)).first() is not None
    assert db_session.scalars(select(DecisionLog)).first() is not None
    memo = Path(result.memo_path or "").read_text(encoding="utf-8")
    assert "No auto-trade" in memo
    assert "Matched Scenarios" in memo


def test_daily_review_loop_idempotency(db_session, repo_root, tmp_path, monkeypatch):
    _remove_api_keys(monkeypatch)

    first = run_daily_review_loop(
        as_of=date(2026, 6, 29),
        db_session=db_session,
        thesis_dir=repo_root / "thesis",
        scenario_dir=repo_root / "scenarios",
        playbook_dir=repo_root / "playbooks",
        fixture_dir=_fixture_dir(repo_root),
        memo_dir=tmp_path,
        ingest_mock=True,
    )
    first_counts = _source_record_counts(db_session)
    second = run_daily_review_loop(
        as_of=date(2026, 6, 29),
        db_session=db_session,
        thesis_dir=repo_root / "thesis",
        scenario_dir=repo_root / "scenarios",
        playbook_dir=repo_root / "playbooks",
        fixture_dir=_fixture_dir(repo_root),
        memo_dir=tmp_path,
        ingest_mock=True,
    )
    second_counts = _source_record_counts(db_session)
    decisions = db_session.scalars(select(DecisionLog).order_by(DecisionLog.created_at)).all()

    assert sum(second.inserted_raw_counts.values()) == 0
    assert second.inserted_event_count == 0
    assert second.appended_evidence_count == 0
    assert second.skipped_duplicate_evidence_count == first.evidence_candidate_count
    assert second_counts == {**first_counts, "evidence": first_counts["evidence"]}
    assert len(decisions) == 2
    assert decisions[-1].metadata_json["skipped_duplicate_evidence_count"] == second.skipped_duplicate_evidence_count


def test_intraday_review_loop_end_to_end(db_session, repo_root, tmp_path, monkeypatch):
    _remove_api_keys(monkeypatch)
    payload = _emergency_payload(repo_root)

    result = run_intraday_review_loop(
        event_input=payload["event_input"],
        metrics=payload["metrics"],
        exposure_context=payload["exposure_context"],
        db_session=db_session,
        thesis_dir=repo_root / "thesis",
        scenario_dir=repo_root / "scenarios",
        playbook_dir=repo_root / "playbooks",
        memo_dir=tmp_path,
    )

    assert result.emergency_level.value == "E3"
    assert any(match.scenario_id == "KOR_SEMI_RATE_SHOCK_BEAR" for match in result.matched_scenarios)
    assert "no_new_buy" in result.allowed_actions
    assert "llm_direct_trade_decision" in result.forbidden_actions
    assert result.appended_evidence_count > 0
    assert result.decision_log_count == 1
    memo = Path(result.memo_path or "").read_text(encoding="utf-8")
    assert "No auto-trade" in memo
    assert "Close-review requirement" in memo


def test_intraday_review_loop_idempotency(db_session, repo_root, tmp_path, monkeypatch):
    _remove_api_keys(monkeypatch)
    payload = _emergency_payload(repo_root)

    first = run_intraday_review_loop(
        event_input=payload["event_input"],
        metrics=payload["metrics"],
        exposure_context=payload["exposure_context"],
        db_session=db_session,
        thesis_dir=repo_root / "thesis",
        scenario_dir=repo_root / "scenarios",
        playbook_dir=repo_root / "playbooks",
        memo_dir=tmp_path,
    )
    first_counts = _source_record_counts(db_session)
    second = run_intraday_review_loop(
        event_input=payload["event_input"],
        metrics=payload["metrics"],
        exposure_context=payload["exposure_context"],
        db_session=db_session,
        thesis_dir=repo_root / "thesis",
        scenario_dir=repo_root / "scenarios",
        playbook_dir=repo_root / "playbooks",
        memo_dir=tmp_path,
    )
    second_counts = _source_record_counts(db_session)
    decisions = db_session.scalars(select(DecisionLog).order_by(DecisionLog.created_at)).all()

    assert first.appended_evidence_count > 0
    assert second.appended_evidence_count == 0
    assert second.skipped_duplicate_evidence_count == first.evidence_candidate_count
    assert second_counts["events"] == first_counts["events"]
    assert second_counts["evidence"] == first_counts["evidence"]
    assert len(decisions) == 2
    assert decisions[-1].metadata_json["skipped_duplicate_evidence_count"] == second.skipped_duplicate_evidence_count


def test_operational_review_loop_cli(tmp_path, repo_root, monkeypatch):
    _remove_api_keys(monkeypatch)
    runner = CliRunner()
    db_url = f"sqlite:///{tmp_path / 'operations.sqlite'}"

    daily = runner.invoke(
        app,
        [
            "run-daily-review-loop",
            "--as-of",
            "2026-06-29",
            "--db-url",
            db_url,
            "--ingest-mock-bundle",
            "--memo-dir",
            str(tmp_path),
            "--thesis-dir",
            str(repo_root / "thesis"),
            "--scenario-dir",
            str(repo_root / "scenarios"),
            "--playbook-dir",
            str(repo_root / "playbooks"),
            "--fixture-dir",
            str(_fixture_dir(repo_root)),
        ],
    )
    intraday = runner.invoke(
        app,
        [
            "run-intraday-review-loop",
            "--fixture",
            str(repo_root / "tests" / "fixtures" / "emergency_rate_shock.json"),
            "--db-url",
            db_url,
            "--memo-dir",
            str(tmp_path),
            "--thesis-dir",
            str(repo_root / "thesis"),
            "--scenario-dir",
            str(repo_root / "scenarios"),
            "--playbook-dir",
            str(repo_root / "playbooks"),
        ],
    )

    assert daily.exit_code == 0
    assert "memo_path" in daily.output
    assert intraday.exit_code == 0
    assert "emergency_level" in intraday.output
