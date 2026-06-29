from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from project_stock.config import DEFAULT_DB_URL
from project_stock.db.migrations import init_db as init_database
from project_stock.db.models import RawDocument
from project_stock.db.session import session_scope
from project_stock.events.classifier import event_from_document
from project_stock.events.mapper import map_entities
from project_stock.events.normalization import (
    detect_market_events as detect_market_events_flow,
    normalize_events as normalize_events_flow,
    normalize_events_from_documents as normalize_documents_flow,
    normalize_events_from_indicators as normalize_indicators_flow,
    run_event_normalization_demo as run_event_normalization_demo_flow,
)
from project_stock.ingest.dart import OpenDartCollector
from project_stock.ingest.ecos import EcosCollector
from project_stock.ingest.fred import FredCollector
from project_stock.ingest.krx import KrxCollector
from project_stock.ingest.mock import ingest_mock_data
from project_stock.ingest.news import NewsRssCollector
from project_stock.ingest.official_bundle import ingest_official_mock_bundle as ingest_bundle
from project_stock.ingest.sources import register_official_sources
from project_stock.scoring.big_flow import score_big_flow as compute_big_flow_score
from project_stock.schemas.scoring import BigFlowScoreInput
from project_stock.sentinel.daily import run_daily_sentinel
from project_stock.sentinel.intraday import run_intraday_emergency_check
from project_stock.storage.repository import Repository
from project_stock.thesis.loader import load_thesis_dir
from project_stock.scenarios.loader import load_scenario_dir
from project_stock.playbooks.loader import load_playbook_dir

app = typer.Typer(no_args_is_help=True)
console = Console()
DEFAULT_OFFICIAL_FIXTURE_DIR = Path("tests/fixtures/official")


def _echo_json(payload: Any) -> None:
    console.print(json.dumps(payload, indent=2, sort_keys=True, default=str))


@app.command()
def init_db(db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url")) -> None:
    init_database(db_url)
    _echo_json({"status": "ok", "db_url": db_url})


@app.command()
def register_sources(db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url")) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        sources = register_official_sources(session)
        source_ids = [source.source_id for source in sources]
    _echo_json({"registered_sources": len(source_ids), "source_ids": source_ids})


@app.command()
def load_yaml(
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
    playbook_dir: Path = typer.Option(Path("playbooks"), "--playbook-dir"),
) -> None:
    theses = load_thesis_dir(thesis_dir)
    scenarios = load_scenario_dir(scenario_dir)
    playbooks = load_playbook_dir(playbook_dir)
    _echo_json(
        {
            "thesis_count": len(theses),
            "scenario_count": len(scenarios),
            "playbook_count": len(playbooks),
            "status": "validated",
        }
    )


@app.command()
def ingest_mock(db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url")) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        event_ids = ingest_mock_data(session)
    _echo_json({"inserted_events": len(event_ids), "event_ids": event_ids})


@app.command()
def ingest_dart_mock(
    fixture: Path = typer.Option(..., "--fixture"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = OpenDartCollector().ingest(session, fixture=fixture, mock=True)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def ingest_ecos_mock(
    fixture: Path = typer.Option(..., "--fixture"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = EcosCollector().ingest(session, fixture=fixture, mock=True)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def ingest_fred_mock(
    fixture: Path = typer.Option(..., "--fixture"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = FredCollector().ingest(session, fixture=fixture, mock=True)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def ingest_krx_mock(
    fixture: Path = typer.Option(..., "--fixture"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = KrxCollector().ingest(session, fixture=fixture, mock=True)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def ingest_news_mock(
    fixture: Path = typer.Option(..., "--fixture"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = NewsRssCollector().ingest(session, fixture=fixture, mock=True)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def ingest_official_mock_bundle(
    fixture_dir: Path = typer.Option(DEFAULT_OFFICIAL_FIXTURE_DIR, "--fixture-dir"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        results = ingest_bundle(session, fixture_dir)
    _echo_json(
        {
            "total_inserted": sum(result.inserted_count for result in results),
            "total_skipped": sum(result.skipped_count for result in results),
            "collectors": [result.model_dump(mode="json") for result in results],
        }
    )


@app.command()
def classify_events(db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url")) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        repo = Repository(session)
        events = []
        for raw in session.query(RawDocument).all():
            event = repo.add_event(event_from_document(raw))
            repo.add_event_entities(event.event_id, map_entities(f"{raw.title} {raw.body_text}"))
            events.append(event.event_id)
    _echo_json({"classified_events": len(events), "event_ids": events})


@app.command()
def normalize_events(db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url")) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = normalize_events_flow(session)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def normalize_events_from_documents(
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = normalize_documents_flow(session)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def normalize_events_from_indicators(
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = normalize_indicators_flow(session)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def detect_market_events(
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    thresholds: Path = typer.Option(Path("configs/market_event_thresholds.yaml"), "--thresholds"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = detect_market_events_flow(session, thresholds_path=thresholds)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def run_event_normalization_demo(
    fixture_dir: Path = typer.Option(DEFAULT_OFFICIAL_FIXTURE_DIR, "--fixture-dir"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = run_event_normalization_demo_flow(session, fixture_dir)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def run_daily(
    as_of: str = typer.Option(..., "--as-of"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = run_daily_sentinel(as_of=date.fromisoformat(as_of), db_session=session)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def run_emergency(
    fixture: Path = typer.Option(..., "--fixture"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
    playbook_dir: Path = typer.Option(Path("playbooks"), "--playbook-dir"),
) -> None:
    init_database(db_url)
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    with session_scope(db_url) as session:
        result = run_intraday_emergency_check(
            event_input=payload["event_input"],
            metrics=payload["metrics"],
            exposure_context=payload["exposure_context"],
            db_session=session,
            scenario_dir=scenario_dir,
            playbook_dir=playbook_dir,
        )
    _echo_json(result.model_dump(mode="json"))


@app.command()
def score_big_flow(fixture: Path = typer.Option(..., "--fixture")) -> None:
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    result = compute_big_flow_score(BigFlowScoreInput.model_validate(payload))
    _echo_json(result.model_dump(mode="json"))
