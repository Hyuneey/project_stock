from __future__ import annotations

from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.db.models import Event, EvidenceLedger
from project_stock.evidence.generation import (
    append_evidence_candidates,
    classify_evidence_stance,
    generate_and_append_evidence,
    generate_evidence_candidates,
    match_thesis_relevance,
    score_evidence_strength,
)
from project_stock.events.normalization import normalize_events
from project_stock.ingest.dart import OpenDartCollector
from project_stock.ingest.ecos import EcosCollector
from project_stock.ingest.news import NewsRssCollector
from project_stock.scenarios.loader import load_scenario_dir
from project_stock.schemas.events import EventCreate
from project_stock.storage.repository import Repository
from project_stock.thesis.loader import load_thesis_dir


def _fixture(repo_root, name: str):
    return repo_root / "tests" / "fixtures" / "official" / name


def _add_event(
    db_session,
    event_type: str,
    summary: str,
    entities: list[dict[str, object]],
) -> Event:
    repo = Repository(db_session)
    event = repo.add_event(
        EventCreate(
            event_id=f"EVT_TEST_{event_type}",
            event_type=event_type,
            event_time=datetime(2026, 6, 29, tzinfo=UTC),
            first_seen_at=datetime(2026, 6, 29, tzinfo=UTC),
            available_from=datetime(2026, 6, 29, tzinfo=UTC),
            summary=summary,
            source_reliability=4.0,
            surprise_score=4.0,
            persistence_score=3.0,
            market_confirmation_score=3.0,
            metadata_json={"source_table": "test", "source_record_id": event_type},
        )
    )
    repo.add_event_entities(event.event_id, entities)
    return event


def test_event_to_thesis_relevance_matching(db_session, repo_root):
    event = _add_event(
        db_session,
        "sector_news_headline",
        "Semiconductor memory demand improves on AI infrastructure.",
        [
            {"entity_type": "theme", "entity_id": "KOR_SEMI_MEMORY_UPCYCLE", "relevance_score": 1.0},
            {"entity_type": "sector", "entity_id": "SEMICONDUCTOR", "relevance_score": 1.0},
        ],
    )
    theses = load_thesis_dir(repo_root / "thesis")

    results = match_thesis_relevance(event, theses)

    assert results
    assert results[0].thesis_id == "KOR_SEMI_MEMORY_UPCYCLE"
    assert "entity_overlap" in results[0].relevance_reasons


def test_event_to_thesis_relevance_uses_scenario_hints(db_session, repo_root):
    event = _add_event(
        db_session,
        "rate_policy_relevant",
        "US10Y rate policy pressure affects semiconductor duration risk.",
        [{"entity_type": "macro_factor", "entity_id": "US10Y", "relevance_score": 1.0}],
    )
    theses = load_thesis_dir(repo_root / "thesis")
    scenarios = load_scenario_dir(repo_root / "scenarios")

    results = match_thesis_relevance(event, theses, scenarios)

    assert results
    assert any("scenario_keyword_overlap" in result.relevance_reasons for result in results)


def test_event_to_scenario_linkage(db_session, repo_root):
    EcosCollector().ingest(db_session, fixture=_fixture(repo_root, "ecos_indicators.json"))
    normalize_events(db_session)

    result = generate_evidence_candidates(
        db_session,
        thesis_dir=repo_root / "thesis",
        scenario_dir=repo_root / "scenarios",
    )

    assert any(candidate.scenario_id == "KOR_SEMI_RATE_SHOCK_BEAR" for candidate in result.candidates)


def test_supports_stance(db_session):
    event = _add_event(
        db_session,
        "earnings_guidance",
        "Positive earnings guidance for Samsung Electronics.",
        [{"entity_type": "company", "entity_id": "005930", "relevance_score": 1.0}],
    )

    assert classify_evidence_stance(event, "KOR_SEMI_MEMORY_UPCYCLE") == "supports"


def test_contradicts_stance(db_session):
    event = _add_event(
        db_session,
        "rate_policy_relevant",
        "Rate policy pressure raises discount rate risk.",
        [{"entity_type": "macro_factor", "entity_id": "RATES", "relevance_score": 1.0}],
    )

    assert classify_evidence_stance(event, "AI_INFRASTRUCTURE") == "contradicts"


def test_neutral_stance(db_session):
    event = _add_event(
        db_session,
        "disclosure_received",
        "Routine disclosure received.",
        [{"entity_type": "company", "entity_id": "005930", "relevance_score": 1.0}],
    )

    assert classify_evidence_stance(event, "KOR_SEMI_MEMORY_UPCYCLE") == "neutral"


def test_strength_score_bounds(db_session):
    event = _add_event(
        db_session,
        "volatility_shock_move",
        "VIX shock.",
        [{"entity_type": "asset", "entity_id": "VIX", "relevance_score": 1.0}],
    )

    assert 0 <= score_evidence_strength(event, relevance_score=100) <= 5


def test_duplicate_evidence_prevention(db_session, repo_root):
    NewsRssCollector().ingest(db_session, fixture=_fixture(repo_root, "news_rss.json"))
    normalize_events(db_session)

    first = generate_and_append_evidence(db_session, repo_root / "thesis", repo_root / "scenarios")
    second = generate_and_append_evidence(db_session, repo_root / "thesis", repo_root / "scenarios")

    assert first.appended_count > 0
    assert second.appended_count == 0
    assert second.skipped_count == first.candidate_count


def test_no_match_event_safety(db_session, repo_root):
    _add_event(
        db_session,
        "unclassified_news",
        "Unrelated local sports update.",
        [{"entity_type": "asset", "entity_id": "UNRELATED", "relevance_score": 1.0}],
    )

    result = generate_evidence_candidates(db_session, repo_root / "thesis", repo_root / "scenarios")

    assert result.candidate_count == 0


def test_cli_run_evidence_demo(tmp_path, repo_root, monkeypatch):
    for env_var in ("DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY", "NEWS_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)
    runner = CliRunner()
    db_url = f"sqlite:///{tmp_path / 'evidence_demo.sqlite'}"

    result = runner.invoke(
        app,
        [
            "run-evidence-demo",
            "--fixture-dir",
            str(repo_root / "tests" / "fixtures" / "official"),
            "--db-url",
            db_url,
            "--thesis-dir",
            str(repo_root / "thesis"),
            "--scenario-dir",
            str(repo_root / "scenarios"),
        ],
    )

    assert result.exit_code == 0
    assert "counts_by_thesis_id" in result.output
    assert "counts_by_stance" in result.output


def test_evidence_ledger_append_only_still_enforced(db_session, repo_root):
    OpenDartCollector().ingest(db_session, fixture=_fixture(repo_root, "dart_disclosures.json"))
    normalize_events(db_session)
    generated = generate_evidence_candidates(db_session, repo_root / "thesis", repo_root / "scenarios")
    appended = append_evidence_candidates(db_session, generated.candidates)
    db_session.commit()
    evidence = db_session.get(EvidenceLedger, appended.evidence_ids[0])

    assert evidence is not None
    evidence.claim = "mutated"
    with pytest.raises(RuntimeError, match="EvidenceLedger is append-only"):
        db_session.commit()
