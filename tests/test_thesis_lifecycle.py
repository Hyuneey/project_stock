from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.db.models import ThesisStateSnapshot
from project_stock.schemas.evidence import EvidenceCreate
from project_stock.storage.repository import Repository
from project_stock.thesis.lifecycle import (
    archive_thesis,
    evaluate_thesis_states,
    run_thesis_review_demo,
)


def _add_evidence(
    db_session,
    thesis_id: str,
    stance: str,
    strength: float,
    claim: str,
) -> None:
    Repository(db_session).append_evidence(
        EvidenceCreate(
            thesis_id=thesis_id,
            evidence_type="manual_test",
            claim=claim,
            supports_or_contradicts=stance,
            strength_score=strength,
            metadata_json={"source_event_type": "manual_test"},
        )
    )


def _remove_api_keys(monkeypatch) -> None:
    for env_var in ("DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY", "NEWS_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)


def _evaluation(result, thesis_id: str):
    return next(evaluation for evaluation in result.evaluations if evaluation.thesis_id == thesis_id)


def test_evidence_aggregation_by_thesis(db_session, repo_root):
    _add_evidence(db_session, "KOR_SEMI_MEMORY_UPCYCLE", "supports", 4.0, "Memory demand improves.")
    _add_evidence(db_session, "AI_INFRASTRUCTURE", "contradicts", 3.0, "Funding conditions tighten.")

    result = evaluate_thesis_states(
        session=db_session,
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        memo_dir=None,
    )

    kor = _evaluation(result, "KOR_SEMI_MEMORY_UPCYCLE")
    ai = _evaluation(result, "AI_INFRASTRUCTURE")
    assert kor.support_score > 0
    assert kor.contradiction_score == 0
    assert ai.contradiction_score > 0


def test_support_heavy_evidence_proposes_active(db_session, repo_root):
    _add_evidence(db_session, "AI_INFRASTRUCTURE", "supports", 5.0, "Cloud AI capex remains high.")
    _add_evidence(db_session, "AI_INFRASTRUCTURE", "supports", 4.5, "Memory suppliers retain pricing power.")

    result = evaluate_thesis_states(
        session=db_session,
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        memo_dir=None,
    )

    assert _evaluation(result, "AI_INFRASTRUCTURE").proposed_state.value == "active"


def test_contradiction_heavy_evidence_proposes_deteriorating(db_session, repo_root):
    _add_evidence(db_session, "KOR_SEMI_MEMORY_UPCYCLE", "contradicts", 4.0, "Margin pressure rises.")
    _add_evidence(db_session, "KOR_SEMI_MEMORY_UPCYCLE", "contradicts", 3.5, "Relative performance weakens.")

    result = evaluate_thesis_states(
        session=db_session,
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        memo_dir=None,
    )

    assert _evaluation(result, "KOR_SEMI_MEMORY_UPCYCLE").proposed_state.value == "deteriorating"


def test_strong_invalidation_evidence_proposes_invalidated(db_session, repo_root):
    _add_evidence(
        db_session,
        "KOR_SEMI_MEMORY_UPCYCLE",
        "contradicts",
        5.0,
        "EPS revisions turn negative.",
    )
    _add_evidence(
        db_session,
        "KOR_SEMI_MEMORY_UPCYCLE",
        "contradicts",
        5.0,
        "Relative strength breaks down for three months.",
    )

    result = evaluate_thesis_states(
        session=db_session,
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        memo_dir=None,
    )

    evaluation = _evaluation(result, "KOR_SEMI_MEMORY_UPCYCLE")
    assert evaluation.proposed_state.value == "invalidated"
    assert evaluation.invalidation_warnings


def test_no_evidence_does_not_crash(db_session, repo_root):
    result = evaluate_thesis_states(
        session=db_session,
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        memo_dir=None,
    )

    assert result.evaluation_count == 2
    assert {evaluation.proposed_state.value for evaluation in result.evaluations}.issubset(
        {"candidate", "watch"}
    )


def test_repeated_evaluation_skips_identical_snapshots(db_session, repo_root):
    first = evaluate_thesis_states(
        session=db_session,
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        memo_dir=None,
    )
    second = evaluate_thesis_states(
        session=db_session,
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        memo_dir=None,
    )
    snapshots = db_session.scalars(select(ThesisStateSnapshot)).all()

    assert first.snapshot_count == 2
    assert second.snapshot_count == 0
    assert second.skipped_duplicate_snapshot_count == 2
    assert len(snapshots) == 2


def test_thesis_state_snapshot_is_append_only(db_session):
    repo = Repository(db_session)
    snapshot = repo.append_thesis_snapshot(
        thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
        version="1.0",
        status="watch",
        as_of=datetime(2026, 6, 29, tzinfo=UTC),
        state_reason="Initial snapshot.",
    )
    db_session.commit()

    snapshot.status = "active"
    with pytest.raises(RuntimeError, match="ThesisStateSnapshot is append-only"):
        db_session.commit()
    db_session.rollback()

    db_session.delete(snapshot)
    with pytest.raises(RuntimeError, match="ThesisStateSnapshot is append-only"):
        db_session.commit()


def test_thesis_review_memo_is_created(db_session, repo_root, tmp_path):
    result = evaluate_thesis_states(
        session=db_session,
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        memo_dir=tmp_path,
    )

    memo = Path(result.memo_path or "")
    assert memo.exists()
    assert "No auto-trade" in memo.read_text(encoding="utf-8")


def test_cli_run_thesis_review_demo_works(tmp_path, repo_root, monkeypatch):
    _remove_api_keys(monkeypatch)
    runner = CliRunner()
    db_url = f"sqlite:///{tmp_path / 'thesis_demo.sqlite'}"

    result = runner.invoke(
        app,
        [
            "run-thesis-review-demo",
            "--db-url",
            db_url,
            "--thesis-dir",
            str(repo_root / "thesis"),
            "--scenario-dir",
            str(repo_root / "scenarios"),
            "--fixture-dir",
            str(repo_root / "tests" / "fixtures" / "official"),
            "--memo-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "snapshot_count" in result.output
    assert "memo_path" in result.output


def test_run_thesis_review_demo_skips_duplicate_snapshots(db_session, repo_root, tmp_path, monkeypatch):
    _remove_api_keys(monkeypatch)

    first = run_thesis_review_demo(
        session=db_session,
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        scenario_dir=repo_root / "scenarios",
        fixture_dir=repo_root / "tests" / "fixtures" / "official",
        memo_dir=tmp_path,
    )
    second = run_thesis_review_demo(
        session=db_session,
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        scenario_dir=repo_root / "scenarios",
        fixture_dir=repo_root / "tests" / "fixtures" / "official",
        memo_dir=tmp_path,
    )

    assert first.snapshot_count == 2
    assert second.snapshot_count == 0
    assert second.skipped_duplicate_snapshot_count == 2


def test_archive_thesis_behavior(db_session, repo_root):
    first = archive_thesis(
        session=db_session,
        thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        reason="Manual archive after review.",
    )
    second = archive_thesis(
        session=db_session,
        thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
        as_of=date(2026, 6, 29),
        thesis_dir=repo_root / "thesis",
        reason="Manual archive after review.",
    )

    snapshot = db_session.scalar(select(ThesisStateSnapshot))
    assert first.snapshot_count == 1
    assert second.snapshot_count == 0
    assert snapshot is not None
    assert snapshot.status == "archived"
