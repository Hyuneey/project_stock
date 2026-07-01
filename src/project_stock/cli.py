from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import typer
from jinja2 import Environment
from rich.console import Console

from project_stock.backtest.validation import (
    DEFAULT_BACKTEST_CONFIG,
    DEFAULT_MARKET_RETURNS,
    DEFAULT_MEMO_DIR as DEFAULT_BACKTEST_MEMO_DIR,
    DEFAULT_PORTFOLIO_FLAGS,
    DEFAULT_PORTFOLIO_SNAPSHOTS,
    DEFAULT_THESIS_STATES,
    load_signal_snapshots,
    run_backtest_demo as run_backtest_demo_flow,
    validate_point_in_time_signals,
)
from project_stock.config import DEFAULT_DB_URL
from project_stock.db.migrations import init_db as init_database
from project_stock.db.models import RawDocument
from project_stock.db.session import session_scope
from project_stock.events.classifier import event_from_document
from project_stock.events.mapper import map_entities
from project_stock.events.financials import normalize_financial_events as normalize_financial_events_flow
from project_stock.events.normalization import (
    detect_market_events as detect_market_events_flow,
    normalize_events as normalize_events_flow,
    normalize_events_from_documents as normalize_documents_flow,
    normalize_events_from_indicators as normalize_indicators_flow,
    run_event_normalization_demo as run_event_normalization_demo_flow,
)
from project_stock.evidence.generation import (
    append_evidence_candidates as append_evidence_candidates_flow,
    generate_evidence_candidates as generate_evidence_candidates_flow,
    run_evidence_demo as run_evidence_demo_flow,
)
from project_stock.ingest.base import CollectorConfigError
from project_stock.ingest.dart import (
    DART_API_KEY_ENV_VARS,
    OpenDartCollector,
    load_opendart_corp_codes,
)
from project_stock.ingest.ecos import EcosCollector, load_ecos_series_config
from project_stock.ingest.fred import FredCollector, SUPPORTED_FRED_SERIES
from project_stock.ingest.krx import KrxCollector, krx_doctor_payload
from project_stock.ingest.mock import ingest_mock_data
from project_stock.ingest.news import NewsRssCollector
from project_stock.ingest.opendart_financials import OpenDartFinancialCollector
from project_stock.ingest.official_bundle import ingest_official_mock_bundle as ingest_bundle
from project_stock.ingest.real_data import (
    NETWORK_ENV_VAR,
    build_raw_cache_path,
    network_enabled,
)
from project_stock.ingest.sources import register_official_sources
from project_stock.operations.review_loop import (
    run_daily_review_loop as run_daily_review_loop_flow,
    run_intraday_review_loop as run_intraday_review_loop_flow,
)
from project_stock.operations.real_data_smoke import (
    DEFAULT_REAL_DATA_SMOKE_CONFIG,
    build_source_statuses,
    load_real_data_smoke_config,
    real_data_smoke_doctor_payload,
    run_real_data_smoke as run_real_data_smoke_flow,
    validate_smoke_limits,
)
from project_stock.operations.kor_semi_thesis_pack import (
    DEFAULT_BIG_FLOW_FIXTURE,
    run_kor_semi_thesis_pack_demo as run_kor_semi_thesis_pack_demo_flow,
)
from project_stock.portfolio.review import (
    review_portfolio as review_portfolio_flow,
    run_portfolio_review_demo as run_portfolio_review_demo_flow,
)
from project_stock.scoring.big_flow import score_big_flow as compute_big_flow_score
from project_stock.schemas.scoring import BigFlowScoreInput
from project_stock.sentinel.daily import run_daily_sentinel
from project_stock.sentinel.intraday import run_intraday_emergency_check
from project_stock.storage.repository import Repository
from project_stock.thesis.lifecycle import (
    archive_thesis as archive_thesis_flow,
    evaluate_thesis_states as evaluate_thesis_states_flow,
    run_thesis_review_demo as run_thesis_review_demo_flow,
)
from project_stock.thesis.loader import load_thesis_dir
from project_stock.scenarios.loader import load_scenario_dir
from project_stock.playbooks.loader import load_playbook_dir

app = typer.Typer(no_args_is_help=True)
console = Console()
DEFAULT_OFFICIAL_FIXTURE_DIR = Path("tests/fixtures/official")
DEFAULT_DASHBOARD_APP = Path(__file__).resolve().parent / "dashboard" / "app.py"
DEFAULT_REAL_RUN_ACCEPTANCE_TEMPLATE = Path("docs/reports/real_run_acceptance_template.md")
DEFAULT_REAL_RUN_ACCEPTANCE_DIR = Path("data/processed/real_run_acceptance")


def _echo_json(payload: Any) -> None:
    console.print(json.dumps(payload, indent=2, sort_keys=True, default=str), markup=False)


def _exit_with_error(error: Exception) -> None:
    _echo_json({"status": "error", "error": str(error), "no_auto_trade": True})
    raise typer.Exit(1)


def _dashboard_command(db_url: str, memo_dir: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(DEFAULT_DASHBOARD_APP),
        "--",
        "--db-url",
        db_url,
        "--memo-dir",
        str(memo_dir),
    ]


def _env_key_status(names: list[str]) -> dict[str, bool]:
    return {name: bool(os.getenv(name, "").strip()) for name in names}


def _path_status(paths: dict[str, Path | None]) -> dict[str, dict[str, object]]:
    return {
        name: {
            "path": str(path) if path is not None else None,
            "exists": path.exists() if path is not None else False,
        }
        for name, path in paths.items()
    }


def _raw_cache_directory_status() -> dict[str, dict[str, object]]:
    paths = {
        "fred": build_raw_cache_path("fred", "DGS10", "YYYY-MM-DD", "YYYY-MM-DD").parent,
        "ecos": build_raw_cache_path("ecos", "ECOS_BASE_RATE", "YYYY-MM-DD", "YYYY-MM-DD").parent,
        "opendart": Path("data/raw/opendart"),
        "opendart_financial": Path("data/raw/opendart/financial"),
        "krx": Path("data/raw/krx"),
    }
    return _path_status(paths)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _current_git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _safe_report_name(run_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in run_id).strip("_")
    return safe or "real_run"


def _render_markdown_template(template_path: Path, context: dict[str, object]) -> str:
    template = Environment(
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    ).from_string(template_path.read_text(encoding="utf-8"))
    return template.render(**context)


def _missing_real_run_key_groups(source_statuses: list[object]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for status in source_statuses:
        required_keys = getattr(status, "required_api_keys", [])
        if not getattr(status, "would_run", False) or not required_keys:
            continue
        if not getattr(status, "api_key_set", False):
            missing[getattr(status, "adapter", "unknown")] = list(required_keys)
    return missing


def _real_run_preflight_payload(config_path: Path, db_url: str, memo_dir: Path) -> dict[str, object]:
    config = load_real_data_smoke_config(config_path)
    validate_smoke_limits(config)
    statuses = build_source_statuses(config, "dry_run")
    source_config_paths = {
        "ecos_series": config.config_paths.ecos_series,
        "opendart_corp_codes": config.config_paths.opendart_corp_codes,
        "krx_symbols": config.config_paths.krx_symbols,
        "portfolio": config.config_paths.portfolio,
    }
    safe_sequence = [
        f"project-stock real-run-preflight --config {config_path} --db-url {db_url} --memo-dir {memo_dir}",
        f"project-stock real-data-smoke-doctor --config {config_path}",
        f"project-stock run-real-data-smoke --config {config_path} --dry-run",
        f"project-stock run-real-data-smoke-fixture --config {config_path} --db-url {db_url}",
        f"{NETWORK_ENV_VAR}=true project-stock run-real-data-smoke --config {config_path} --db-url {db_url}",
        f"project-stock run-dashboard --db-url {db_url} --memo-dir {memo_dir}",
    ]
    return {
        "status": "ok",
        "config": str(config_path),
        "config_exists": config_path.exists(),
        "db_url": db_url,
        "memo_dir": str(memo_dir),
        NETWORK_ENV_VAR: os.getenv(NETWORK_ENV_VAR, "false"),
        "network_enabled": network_enabled(),
        "api_keys": _env_key_status(
            [
                "FRED_API_KEY",
                "ECOS_API_KEY",
                "DART_API_KEY",
                "OPEN_DART_API_KEY",
                "KRX_AUTH_TOKEN",
                "KRX_API_KEY",
            ]
        ),
        "source_statuses": [status.model_dump(mode="json") for status in statuses],
        "missing_required_key_groups": _missing_real_run_key_groups(statuses),
        "source_config_files": _path_status(source_config_paths),
        "raw_cache_directories": _raw_cache_directory_status(),
        "smoke_limits": {
            "start_date": config.start_date.isoformat(),
            "end_date": config.end_date.isoformat(),
            "max_days": config.max_days,
            "max_records": config.max_records,
        },
        "configured_sources": {
            "fred_series": config.fred_series,
            "ecos_indicators": config.ecos_indicators,
            "opendart_companies": [company.model_dump(mode="json") for company in config.opendart_companies],
            "krx_symbols": config.krx_symbols,
        },
        "recommended_next_command": safe_sequence[1],
        "safe_execution_sequence": safe_sequence,
        "manual_review_required": True,
        "no_auto_trade": True,
        "warning": "Decision support only: no broker execution, no auto-trading, no LLM investment decisions.",
    }


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
def real_data_doctor(db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url")) -> None:
    _echo_json(
        {
            "status": "ok",
            "db_url": db_url,
            NETWORK_ENV_VAR: os.getenv(NETWORK_ENV_VAR, "false"),
            "network_enabled": network_enabled(),
            "fred_api_key_set": bool(os.getenv("FRED_API_KEY")),
            "ecos_api_key_set": bool(os.getenv("ECOS_API_KEY")),
            "raw_cache_directories": {
                "fred": str(build_raw_cache_path("fred", "DGS10", "YYYY-MM-DD", "YYYY-MM-DD").parent),
                "ecos": str(
                    build_raw_cache_path("ecos", "ECOS_BASE_RATE", "YYYY-MM-DD", "YYYY-MM-DD").parent
                ),
            },
            "supported_fred_series": sorted(SUPPORTED_FRED_SERIES),
            "configured_ecos_series_example": sorted(
                load_ecos_series_config(Path("configs/ecos.series.example.yaml"))
            )
            if Path("configs/ecos.series.example.yaml").exists()
            else [],
            "point_in_time_caution": (
                "Real observations are marked available no earlier than their source release "
                "or local collection time; verify source-specific release lags before research use."
            ),
            "no_auto_trade": True,
            "warning": "Decision support only: no broker execution, no auto-trading, no LLM trade decisions.",
        }
    )


@app.command()
def opendart_doctor(
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    corp_code_config: Path = typer.Option(
        Path("configs/opendart.corp_codes.example.yaml"),
        "--corp-code-config",
    ),
) -> None:
    configured_companies: list[str] = []
    config_error = None
    if corp_code_config.exists():
        try:
            configured_companies = sorted(load_opendart_corp_codes(corp_code_config))
        except ValueError as exc:
            config_error = str(exc)
    _echo_json(
        {
            "status": "ok",
            "db_url": db_url,
            NETWORK_ENV_VAR: os.getenv(NETWORK_ENV_VAR, "false"),
            "network_enabled": network_enabled(),
            "dart_api_key_set": bool(os.getenv("DART_API_KEY")),
            "open_dart_api_key_set": bool(os.getenv("OPEN_DART_API_KEY")),
            "accepted_api_key_env_vars": list(DART_API_KEY_ENV_VARS),
            "corp_code_config": str(corp_code_config),
            "corp_code_config_exists": corp_code_config.exists(),
            "corp_code_config_error": config_error,
            "configured_stock_codes": configured_companies,
            "raw_cache_directory": "data/raw/opendart",
            "supported_scope": "disclosure list only; no report body, XBRL, or financial extraction",
            "no_auto_trade": True,
            "warning": "Decision support only: no broker execution, no auto-trading, no LLM trade decisions.",
        }
    )


@app.command()
def real_data_smoke_doctor(
    config: Path = typer.Option(DEFAULT_REAL_DATA_SMOKE_CONFIG, "--config"),
) -> None:
    try:
        payload = real_data_smoke_doctor_payload(config)
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
    _echo_json(payload)


@app.command()
def real_run_preflight(
    config: Path = typer.Option(DEFAULT_REAL_DATA_SMOKE_CONFIG, "--config"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
    require_network_enabled: bool = typer.Option(False, "--require-network-enabled"),
    require_keys: bool = typer.Option(False, "--require-keys"),
) -> None:
    try:
        payload = _real_run_preflight_payload(config, db_url, memo_dir)
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)

    errors: list[str] = []
    if require_network_enabled and not payload["network_enabled"]:
        errors.append(f"Network disabled; set {NETWORK_ENV_VAR}=true before bounded real runs.")
    missing_keys = payload["missing_required_key_groups"]
    if require_keys and isinstance(missing_keys, dict) and missing_keys:
        details = "; ".join(
            f"{adapter}: {' or '.join(keys)}" for adapter, keys in sorted(missing_keys.items())
        )
        errors.append(f"Missing required API keys for configured sources: {details}.")
    if errors:
        payload["status"] = "error"
        payload["errors"] = errors
        _echo_json(payload)
        raise typer.Exit(1)
    _echo_json(payload)


@app.command()
def render_real_run_acceptance_template(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(DEFAULT_REAL_DATA_SMOKE_CONFIG, "--config"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
    output_path: Path | None = typer.Option(None, "--output-path"),
    git_sha: str | None = typer.Option(None, "--git-sha"),
    operator: str | None = typer.Option(None, "--operator"),
    smoke_report_path: Path | None = typer.Option(None, "--smoke-report-path"),
) -> None:
    if not DEFAULT_REAL_RUN_ACCEPTANCE_TEMPLATE.exists():
        _exit_with_error(
            FileNotFoundError(f"Missing template: {DEFAULT_REAL_RUN_ACCEPTANCE_TEMPLATE}")
        )
    resolved_output = output_path or (
        DEFAULT_REAL_RUN_ACCEPTANCE_DIR / f"real_run_acceptance_{_safe_report_name(run_id)}.md"
    )
    context = {
        "run_id": run_id,
        "operator": operator or "TODO: operator name",
        "run_date": date.today().isoformat(),
        "git_sha": git_sha or _current_git_sha() or "TODO: git SHA",
        "config_path": str(config),
        "db_url": db_url,
        "memo_dir": str(memo_dir),
        "raw_cache_dir": "data/raw",
        "output_path": str(resolved_output),
        "project_stock_allow_network": os.getenv(NETWORK_ENV_VAR, "false"),
        "fred_api_key_present": _yes_no(bool(os.getenv("FRED_API_KEY", "").strip())),
        "ecos_api_key_present": _yes_no(bool(os.getenv("ECOS_API_KEY", "").strip())),
        "opendart_api_key_present": _yes_no(
            bool(os.getenv("DART_API_KEY", "").strip())
            or bool(os.getenv("OPEN_DART_API_KEY", "").strip())
        ),
        "krx_credential_status": (
            "present"
            if bool(os.getenv("KRX_AUTH_TOKEN", "").strip())
            or bool(os.getenv("KRX_API_KEY", "").strip())
            else "not required / not set"
        ),
        "smoke_report_path": str(smoke_report_path)
        if smoke_report_path is not None
        else "TODO: paste smoke report path after bounded real smoke.",
        "no_auto_trade": "true",
    }
    rendered = _render_markdown_template(DEFAULT_REAL_RUN_ACCEPTANCE_TEMPLATE, context)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(rendered, encoding="utf-8")
    _echo_json(
        {
            "status": "ok",
            "output_path": str(resolved_output),
            "template_path": str(DEFAULT_REAL_RUN_ACCEPTANCE_TEMPLATE),
            "no_auto_trade": True,
        }
    )


@app.command()
def run_real_data_smoke(
    config: Path = typer.Option(DEFAULT_REAL_DATA_SMOKE_CONFIG, "--config"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
) -> None:
    try:
        if dry_run:
            result = run_real_data_smoke_flow(
                config,
                mode="dry_run",
                thesis_dir=thesis_dir,
                scenario_dir=scenario_dir,
            )
        else:
            init_database(db_url)
            with session_scope(db_url) as session:
                result = run_real_data_smoke_flow(
                    config,
                    mode="real",
                    session=session,
                    thesis_dir=thesis_dir,
                    scenario_dir=scenario_dir,
                )
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def run_real_data_smoke_fixture(
    config: Path = typer.Option(DEFAULT_REAL_DATA_SMOKE_CONFIG, "--config"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
) -> None:
    init_database(db_url)
    try:
        with session_scope(db_url) as session:
            result = run_real_data_smoke_flow(
                config,
                mode="fixture",
                session=session,
                thesis_dir=thesis_dir,
                scenario_dir=scenario_dir,
            )
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def run_kor_semi_thesis_pack_demo(
    config: Path = typer.Option(DEFAULT_REAL_DATA_SMOKE_CONFIG, "--config"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(
        Path("scenarios/KOR_SEMI_MEMORY_UPCYCLE"),
        "--scenario-dir",
    ),
    playbook_dir: Path = typer.Option(Path("playbooks"), "--playbook-dir"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
    big_flow_fixture: Path = typer.Option(DEFAULT_BIG_FLOW_FIXTURE, "--big-flow-fixture"),
) -> None:
    init_database(db_url)
    try:
        with session_scope(db_url) as session:
            result = run_kor_semi_thesis_pack_demo_flow(
                session,
                config_path=config,
                thesis_dir=thesis_dir,
                scenario_dir=scenario_dir,
                playbook_dir=playbook_dir,
                memo_dir=memo_dir,
                big_flow_fixture=big_flow_fixture,
            )
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
    _echo_json(result.model_dump(mode="json"))


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
def fetch_opendart_disclosures(
    corp_code: str | None = typer.Option(None, "--corp-code"),
    stock_code: str | None = typer.Option(None, "--stock-code"),
    bgn_de: str = typer.Option(..., "--bgn-de"),
    end_de: str = typer.Option(..., "--end-de"),
    page_no: int = typer.Option(1, "--page-no"),
    page_count: int = typer.Option(10, "--page-count"),
    pblntf_ty: str | None = typer.Option(None, "--pblntf-ty"),
    last_reprt_at: str | None = typer.Option(None, "--last-reprt-at"),
    corp_code_config: Path = typer.Option(
        Path("configs/opendart.corp_codes.example.yaml"),
        "--corp-code-config",
    ),
    cache_raw: bool = typer.Option(True, "--cache-raw/--no-cache-raw"),
) -> None:
    try:
        collector = OpenDartCollector()
        raw_records = collector.fetch_disclosures(
            corp_code=corp_code,
            stock_code=stock_code,
            bgn_de=bgn_de,
            end_de=end_de,
            page_no=page_no,
            page_count=page_count,
            pblntf_ty=pblntf_ty,
            last_reprt_at=last_reprt_at,
            corp_code_config=corp_code_config,
            cache_raw=cache_raw,
        )
        documents = collector.normalize(raw_records)
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
    _echo_json(
        {
            "status": "ok",
            "source_id": "OPEN_DART",
            "record_count": len(documents),
            "documents": [document.model_dump(mode="json") for document in documents],
            "no_auto_trade": True,
        }
    )


@app.command()
def ingest_opendart_disclosures(
    corp_code: str | None = typer.Option(None, "--corp-code"),
    stock_code: str | None = typer.Option(None, "--stock-code"),
    bgn_de: str = typer.Option(..., "--bgn-de"),
    end_de: str = typer.Option(..., "--end-de"),
    page_no: int = typer.Option(1, "--page-no"),
    page_count: int = typer.Option(10, "--page-count"),
    pblntf_ty: str | None = typer.Option(None, "--pblntf-ty"),
    last_reprt_at: str | None = typer.Option(None, "--last-reprt-at"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    corp_code_config: Path = typer.Option(
        Path("configs/opendart.corp_codes.example.yaml"),
        "--corp-code-config",
    ),
    cache_raw: bool = typer.Option(True, "--cache-raw/--no-cache-raw"),
) -> None:
    init_database(db_url)
    try:
        with session_scope(db_url) as session:
            result = OpenDartCollector().ingest_disclosures(
                session=session,
                corp_code=corp_code,
                stock_code=stock_code,
                bgn_de=bgn_de,
                end_de=end_de,
                page_no=page_no,
                page_count=page_count,
                pblntf_ty=pblntf_ty,
                last_reprt_at=last_reprt_at,
                corp_code_config=corp_code_config,
                cache_raw=cache_raw,
            )
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def ingest_opendart_disclosures_fixture(
    fixture: Path = typer.Option(..., "--fixture"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = OpenDartCollector().ingest_disclosures(
            session=session,
            corp_code=None,
            stock_code=None,
            bgn_de="19700101",
            end_de="29991231",
            fixture=fixture,
            cache_raw=False,
        )
    _echo_json(result.model_dump(mode="json"))


@app.command()
def fetch_opendart_financials(
    corp_code: str | None = typer.Option(None, "--corp-code"),
    stock_code: str | None = typer.Option(None, "--stock-code"),
    bsns_year: str = typer.Option(..., "--bsns-year"),
    reprt_code: str = typer.Option(..., "--reprt-code"),
    corp_code_config: Path = typer.Option(
        Path("configs/opendart.corp_codes.example.yaml"),
        "--corp-code-config",
    ),
    cache_raw: bool = typer.Option(True, "--cache-raw/--no-cache-raw"),
) -> None:
    try:
        records = OpenDartFinancialCollector().fetch_financials(
            corp_code=corp_code,
            stock_code=stock_code,
            bsns_year=bsns_year,
            reprt_code=reprt_code,
            corp_code_config=corp_code_config,
            cache_raw=cache_raw,
        )
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
    _echo_json(
        {
            "status": "ok",
            "source_id": "OPEN_DART",
            "record_count": len(records),
            "line_items": [record.model_dump(mode="json") for record in records],
            "no_auto_trade": True,
        }
    )


@app.command()
def ingest_opendart_financials(
    corp_code: str | None = typer.Option(None, "--corp-code"),
    stock_code: str | None = typer.Option(None, "--stock-code"),
    bsns_year: str = typer.Option(..., "--bsns-year"),
    reprt_code: str = typer.Option(..., "--reprt-code"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    corp_code_config: Path = typer.Option(
        Path("configs/opendart.corp_codes.example.yaml"),
        "--corp-code-config",
    ),
    cache_raw: bool = typer.Option(True, "--cache-raw/--no-cache-raw"),
) -> None:
    init_database(db_url)
    try:
        with session_scope(db_url) as session:
            result = OpenDartFinancialCollector().ingest_financials(
                session,
                corp_code=corp_code,
                stock_code=stock_code,
                bsns_year=bsns_year,
                reprt_code=reprt_code,
                corp_code_config=corp_code_config,
                cache_raw=cache_raw,
            )
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def ingest_opendart_financials_fixture(
    fixture: Path = typer.Option(..., "--fixture"),
    corp_code: str | None = typer.Option(None, "--corp-code"),
    stock_code: str | None = typer.Option(None, "--stock-code"),
    bsns_year: str = typer.Option(..., "--bsns-year"),
    reprt_code: str = typer.Option(..., "--reprt-code"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    corp_code_config: Path = typer.Option(
        Path("configs/opendart.corp_codes.example.yaml"),
        "--corp-code-config",
    ),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = OpenDartFinancialCollector().ingest_financials(
            session,
            corp_code=corp_code,
            stock_code=stock_code,
            bsns_year=bsns_year,
            reprt_code=reprt_code,
            corp_code_config=corp_code_config,
            fixture=fixture,
            cache_raw=False,
        )
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
def fetch_ecos_series(
    indicator_id: str = typer.Option(..., "--indicator-id"),
    start_date: str = typer.Option(..., "--start-date"),
    end_date: str = typer.Option(..., "--end-date"),
    series_config: Path = typer.Option(Path("configs/ecos.series.example.yaml"), "--series-config"),
    fixture: Path | None = typer.Option(None, "--fixture"),
    cache_raw: bool = typer.Option(True, "--cache-raw/--no-cache-raw"),
) -> None:
    try:
        collector = EcosCollector()
        raw_records = collector.fetch_series(
            indicator_id=indicator_id,
            start_date=start_date,
            end_date=end_date,
            series_config=series_config,
            fixture=fixture,
            cache_raw=cache_raw,
        )
        observations = collector.normalize(raw_records)
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
    _echo_json(
        {
            "status": "ok",
            "source_id": "BOK_ECOS",
            "indicator_id": indicator_id,
            "record_count": len(observations),
            "observations": [record.model_dump(mode="json") for record in observations],
            "no_auto_trade": True,
        }
    )


@app.command()
def ingest_ecos_series(
    indicator_id: str = typer.Option(..., "--indicator-id"),
    start_date: str = typer.Option(..., "--start-date"),
    end_date: str = typer.Option(..., "--end-date"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    series_config: Path = typer.Option(Path("configs/ecos.series.example.yaml"), "--series-config"),
    fixture: Path | None = typer.Option(None, "--fixture"),
    cache_raw: bool = typer.Option(True, "--cache-raw/--no-cache-raw"),
) -> None:
    init_database(db_url)
    try:
        with session_scope(db_url) as session:
            result = EcosCollector().ingest_series(
                session=session,
                indicator_id=indicator_id,
                start_date=start_date,
                end_date=end_date,
                series_config=series_config,
                fixture=fixture,
                cache_raw=cache_raw,
            )
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
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
def fetch_fred_series(
    series_id: str = typer.Option(..., "--series-id"),
    start_date: str = typer.Option(..., "--start-date"),
    end_date: str = typer.Option(..., "--end-date"),
    fixture: Path | None = typer.Option(None, "--fixture"),
    cache_raw: bool = typer.Option(True, "--cache-raw/--no-cache-raw"),
) -> None:
    try:
        collector = FredCollector()
        raw_records = collector.fetch_series(
            series_id=series_id,
            start_date=start_date,
            end_date=end_date,
            fixture=fixture,
            cache_raw=cache_raw,
        )
        observations = collector.normalize(raw_records)
    except CollectorConfigError as exc:
        _exit_with_error(exc)
    _echo_json(
        {
            "status": "ok",
            "source_id": "FRED",
            "series_id": series_id.upper(),
            "record_count": len(observations),
            "observations": [record.model_dump(mode="json") for record in observations],
            "no_auto_trade": True,
        }
    )


@app.command()
def ingest_fred_series(
    series_id: str = typer.Option(..., "--series-id"),
    start_date: str = typer.Option(..., "--start-date"),
    end_date: str = typer.Option(..., "--end-date"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    fixture: Path | None = typer.Option(None, "--fixture"),
    cache_raw: bool = typer.Option(True, "--cache-raw/--no-cache-raw"),
) -> None:
    init_database(db_url)
    try:
        with session_scope(db_url) as session:
            result = FredCollector().ingest_series(
                session=session,
                series_id=series_id,
                start_date=start_date,
                end_date=end_date,
                fixture=fixture,
                cache_raw=cache_raw,
            )
    except CollectorConfigError as exc:
        _exit_with_error(exc)
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
def krx_doctor(
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    symbol_config: Path = typer.Option(Path("configs/krx.symbols.example.yaml"), "--symbol-config"),
) -> None:
    _echo_json(krx_doctor_payload(db_url, symbol_config))


@app.command()
def fetch_krx_daily(
    symbol: str = typer.Option(..., "--symbol"),
    start_date: str = typer.Option(..., "--start-date"),
    end_date: str = typer.Option(..., "--end-date"),
    symbol_config: Path = typer.Option(Path("configs/krx.symbols.example.yaml"), "--symbol-config"),
    cache_raw: bool = typer.Option(True, "--cache-raw/--no-cache-raw"),
) -> None:
    try:
        records = KrxCollector().fetch_daily(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            symbol_config=symbol_config,
            cache_raw=cache_raw,
        )
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
    _echo_json(
        {
            "status": "ok",
            "source_id": "KRX",
            "record_count": len(records),
            "market_time_series": [record.model_dump(mode="json") for record in records],
            "no_auto_trade": True,
        }
    )


@app.command()
def ingest_krx_daily(
    symbol: str = typer.Option(..., "--symbol"),
    start_date: str = typer.Option(..., "--start-date"),
    end_date: str = typer.Option(..., "--end-date"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    symbol_config: Path = typer.Option(Path("configs/krx.symbols.example.yaml"), "--symbol-config"),
    cache_raw: bool = typer.Option(True, "--cache-raw/--no-cache-raw"),
) -> None:
    init_database(db_url)
    try:
        with session_scope(db_url) as session:
            result = KrxCollector().ingest_daily(
                session,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                symbol_config=symbol_config,
                cache_raw=cache_raw,
            )
    except (CollectorConfigError, ValueError) as exc:
        _exit_with_error(exc)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def ingest_krx_daily_fixture(
    fixture: Path = typer.Option(..., "--fixture"),
    symbol: str = typer.Option(..., "--symbol"),
    start_date: str = typer.Option(..., "--start-date"),
    end_date: str = typer.Option(..., "--end-date"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    symbol_config: Path = typer.Option(Path("configs/krx.symbols.example.yaml"), "--symbol-config"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = KrxCollector().ingest_daily(
            session,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            symbol_config=symbol_config,
            fixture=fixture,
            cache_raw=False,
        )
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
def normalize_financial_events(db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url")) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = normalize_financial_events_flow(session)
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
def generate_evidence_candidates(
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = generate_evidence_candidates_flow(session, thesis_dir, scenario_dir)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def append_evidence_candidates(
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        generated = generate_evidence_candidates_flow(session, thesis_dir, scenario_dir)
        result = append_evidence_candidates_flow(session, generated.candidates)
    _echo_json(result.model_dump(mode="json"))


@app.command()
def run_evidence_demo(
    fixture_dir: Path = typer.Option(DEFAULT_OFFICIAL_FIXTURE_DIR, "--fixture-dir"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = run_evidence_demo_flow(session, fixture_dir, thesis_dir, scenario_dir)
    _echo_json(
        {
            "candidate_count": result.candidate_count,
            "appended_count": result.appended_count,
            "skipped_count": result.skipped_count,
            "counts_by_thesis_id": result.counts_by_thesis_id,
            "counts_by_stance": result.counts_by_stance,
            "evidence_ids": result.evidence_ids,
        }
    )


@app.command()
def run_daily_review_loop(
    as_of: str = typer.Option(..., "--as-of"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    ingest_mock_bundle: bool = typer.Option(False, "--ingest-mock-bundle"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
    playbook_dir: Path = typer.Option(Path("playbooks"), "--playbook-dir"),
    fixture_dir: Path = typer.Option(DEFAULT_OFFICIAL_FIXTURE_DIR, "--fixture-dir"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = run_daily_review_loop_flow(
            as_of=date.fromisoformat(as_of),
            db_session=session,
            thesis_dir=thesis_dir,
            scenario_dir=scenario_dir,
            playbook_dir=playbook_dir,
            fixture_dir=fixture_dir,
            memo_dir=memo_dir,
            ingest_mock=ingest_mock_bundle,
        )
    _echo_json(result.model_dump(mode="json"))


@app.command()
def run_intraday_review_loop(
    fixture: Path = typer.Option(..., "--fixture"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
    playbook_dir: Path = typer.Option(Path("playbooks"), "--playbook-dir"),
) -> None:
    init_database(db_url)
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    with session_scope(db_url) as session:
        result = run_intraday_review_loop_flow(
            event_input=payload["event_input"],
            metrics=payload["metrics"],
            exposure_context=payload["exposure_context"],
            db_session=session,
            thesis_dir=thesis_dir,
            scenario_dir=scenario_dir,
            playbook_dir=playbook_dir,
            memo_dir=memo_dir,
        )
    _echo_json(result.model_dump(mode="json"))


@app.command()
def evaluate_thesis_states(
    as_of: str = typer.Option(..., "--as-of"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
    lookback_days: int | None = typer.Option(None, "--lookback-days"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = evaluate_thesis_states_flow(
            session=session,
            as_of=date.fromisoformat(as_of),
            thesis_dir=thesis_dir,
            lookback_days=lookback_days,
            memo_dir=memo_dir,
            force=force,
        )
    _echo_json(result.model_dump(mode="json"))


@app.command()
def run_thesis_review_demo(
    as_of: str = typer.Option("2026-06-29", "--as-of"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
    fixture_dir: Path = typer.Option(DEFAULT_OFFICIAL_FIXTURE_DIR, "--fixture-dir"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = run_thesis_review_demo_flow(
            session=session,
            as_of=date.fromisoformat(as_of),
            thesis_dir=thesis_dir,
            scenario_dir=scenario_dir,
            fixture_dir=fixture_dir,
            memo_dir=memo_dir,
        )
    _echo_json(result.model_dump(mode="json"))


@app.command()
def archive_thesis(
    thesis_id: str = typer.Option(..., "--thesis-id"),
    as_of: str = typer.Option(..., "--as-of"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    reason: str = typer.Option("Explicit archive command.", "--reason"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = archive_thesis_flow(
            session=session,
            thesis_id=thesis_id,
            as_of=date.fromisoformat(as_of),
            thesis_dir=thesis_dir,
            reason=reason,
            force=force,
        )
    _echo_json(result.model_dump(mode="json"))


@app.command()
def review_portfolio(
    portfolio_fixture: Path = typer.Option(..., "--portfolio-fixture"),
    portfolio_config: Path = typer.Option(Path("configs/portfolio.example.yaml"), "--portfolio-config"),
    as_of: str = typer.Option(..., "--as-of"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = review_portfolio_flow(
            session=session,
            portfolio_fixture=portfolio_fixture,
            portfolio_config=portfolio_config,
            as_of=date.fromisoformat(as_of),
            memo_dir=memo_dir,
        )
    _echo_json(result.model_dump(mode="json"))


@app.command()
def run_portfolio_review_demo(
    as_of: str = typer.Option("2026-06-29", "--as-of"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    portfolio_fixture: Path = typer.Option(
        Path("tests/fixtures/portfolio_holdings_core_satellite.json"),
        "--portfolio-fixture",
    ),
    portfolio_config: Path = typer.Option(Path("configs/portfolio.example.yaml"), "--portfolio-config"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        result = run_portfolio_review_demo_flow(
            session=session,
            as_of=date.fromisoformat(as_of),
            portfolio_fixture=portfolio_fixture,
            portfolio_config=portfolio_config,
            memo_dir=memo_dir,
            thesis_dir=thesis_dir,
            scenario_dir=scenario_dir,
        )
    _echo_json(result.model_dump(mode="json"))


@app.command()
def run_backtest_demo(
    config: Path = typer.Option(DEFAULT_BACKTEST_CONFIG, "--config"),
    market_returns: Path = typer.Option(DEFAULT_MARKET_RETURNS, "--market-returns"),
    thesis_states: Path = typer.Option(DEFAULT_THESIS_STATES, "--thesis-states"),
    portfolio_flags: Path = typer.Option(DEFAULT_PORTFOLIO_FLAGS, "--portfolio-flags"),
    portfolio_snapshots: Path = typer.Option(DEFAULT_PORTFOLIO_SNAPSHOTS, "--portfolio-snapshots"),
    memo_dir: Path = typer.Option(DEFAULT_BACKTEST_MEMO_DIR, "--memo-dir"),
) -> None:
    result, report = run_backtest_demo_flow(
        config_path=config,
        market_returns_path=market_returns,
        thesis_states_path=thesis_states,
        portfolio_flags_path=portfolio_flags,
        portfolio_snapshots_path=portfolio_snapshots,
        memo_dir=memo_dir,
    )
    _echo_json(
        {
            "backtest_id": result.backtest_id,
            "policy_name": result.policy_name,
            "benchmark_symbol": result.benchmark_symbol,
            "cumulative_return": result.metrics.cumulative_return,
            "benchmark_cumulative_return": result.metrics.benchmark_cumulative_return,
            "benchmark_relative_return": result.metrics.benchmark_relative_return,
            "average_turnover": result.metrics.average_turnover,
            "transaction_cost_impact": result.metrics.transaction_cost_impact,
            "validation_metrics": result.validation_metrics,
            "trade_simulation_record_count": len(result.trade_records),
            "point_in_time_warnings": result.point_in_time_warnings,
            "report_path": report.report_path,
            "no_auto_trade": result.no_auto_trade,
        }
    )


@app.command()
def validate_signals(
    thesis_states: Path = typer.Option(DEFAULT_THESIS_STATES, "--thesis-states"),
    portfolio_flags: Path = typer.Option(DEFAULT_PORTFOLIO_FLAGS, "--portfolio-flags"),
    strict: bool = typer.Option(True, "--strict/--warn-only"),
) -> None:
    signals = load_signal_snapshots(thesis_states) + load_signal_snapshots(portfolio_flags)
    warnings = validate_point_in_time_signals(signals, strict=strict)
    _echo_json(
        {
            "signal_count": len(signals),
            "warning_count": len(warnings),
            "warnings": warnings,
            "status": "valid" if not warnings else "warnings",
            "no_auto_trade": True,
        }
    )


@app.command()
def render_backtest_report(
    config: Path = typer.Option(DEFAULT_BACKTEST_CONFIG, "--config"),
    market_returns: Path = typer.Option(DEFAULT_MARKET_RETURNS, "--market-returns"),
    thesis_states: Path = typer.Option(DEFAULT_THESIS_STATES, "--thesis-states"),
    portfolio_flags: Path = typer.Option(DEFAULT_PORTFOLIO_FLAGS, "--portfolio-flags"),
    portfolio_snapshots: Path = typer.Option(DEFAULT_PORTFOLIO_SNAPSHOTS, "--portfolio-snapshots"),
    memo_dir: Path = typer.Option(DEFAULT_BACKTEST_MEMO_DIR, "--memo-dir"),
) -> None:
    result, report = run_backtest_demo_flow(
        config_path=config,
        market_returns_path=market_returns,
        thesis_states_path=thesis_states,
        portfolio_flags_path=portfolio_flags,
        portfolio_snapshots_path=portfolio_snapshots,
        memo_dir=memo_dir,
    )
    _echo_json(
        {
            "backtest_id": report.backtest_id,
            "policy_name": report.policy_name,
            "report_path": report.report_path,
            "cumulative_return": result.metrics.cumulative_return,
            "benchmark_relative_return": result.metrics.benchmark_relative_return,
            "point_in_time_warnings": report.point_in_time_warnings,
            "no_auto_trade": report.no_auto_trade,
        }
    )


@app.command()
def run_dashboard(
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
    launch: bool = typer.Option(False, "--launch"),
) -> None:
    command = _dashboard_command(db_url, memo_dir)
    if launch:
        subprocess.run(command, check=False)
        return
    _echo_json(
        {
            "status": "launch_command",
            "command": " ".join(command),
            "db_url": db_url,
            "memo_dir": str(memo_dir),
            "install": "python -m pip install -e \".[dev,dashboard]\"",
            "no_auto_trade": True,
        }
    )


@app.command()
def prepare_dashboard_demo(
    as_of: str = typer.Option("2026-06-29", "--as-of"),
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(Path("scenarios"), "--scenario-dir"),
    playbook_dir: Path = typer.Option(Path("playbooks"), "--playbook-dir"),
    fixture_dir: Path = typer.Option(DEFAULT_OFFICIAL_FIXTURE_DIR, "--fixture-dir"),
    portfolio_fixture: Path = typer.Option(
        Path("tests/fixtures/portfolio_holdings_core_satellite.json"),
        "--portfolio-fixture",
    ),
    portfolio_config: Path = typer.Option(Path("configs/portfolio.example.yaml"), "--portfolio-config"),
) -> None:
    init_database(db_url)
    review_date = date.fromisoformat(as_of)
    with session_scope(db_url) as session:
        daily_result = run_daily_review_loop_flow(
            as_of=review_date,
            db_session=session,
            thesis_dir=thesis_dir,
            scenario_dir=scenario_dir,
            playbook_dir=playbook_dir,
            fixture_dir=fixture_dir,
            memo_dir=memo_dir,
            ingest_mock=True,
        )
        thesis_result = run_thesis_review_demo_flow(
            session=session,
            as_of=review_date,
            thesis_dir=thesis_dir,
            scenario_dir=scenario_dir,
            fixture_dir=fixture_dir,
            memo_dir=memo_dir,
        )
        portfolio_result = run_portfolio_review_demo_flow(
            session=session,
            as_of=review_date,
            portfolio_fixture=portfolio_fixture,
            portfolio_config=portfolio_config,
            memo_dir=memo_dir,
            thesis_dir=thesis_dir,
            scenario_dir=scenario_dir,
        )
    backtest_result, backtest_report = run_backtest_demo_flow(memo_dir=memo_dir)
    launch_command = _dashboard_command(db_url, memo_dir)
    _echo_json(
        {
            "status": "ready",
            "db_url": db_url,
            "memo_dir": str(memo_dir),
            "daily_memo_path": daily_result.memo_path,
            "thesis_memo_path": thesis_result.memo_path,
            "portfolio_memo_path": portfolio_result.memo_path,
            "backtest_report_path": backtest_report.report_path,
            "backtest_id": backtest_result.backtest_id,
            "dashboard_command": " ".join(launch_command),
            "no_auto_trade": True,
        }
    )


@app.command()
def prepare_kor_semi_dashboard_demo(
    db_url: str = typer.Option(DEFAULT_DB_URL, "--db-url"),
    memo_dir: Path = typer.Option(Path("data/processed"), "--memo-dir"),
    config: Path = typer.Option(DEFAULT_REAL_DATA_SMOKE_CONFIG, "--config"),
    thesis_dir: Path = typer.Option(Path("thesis"), "--thesis-dir"),
    scenario_dir: Path = typer.Option(
        Path("scenarios/KOR_SEMI_MEMORY_UPCYCLE"),
        "--scenario-dir",
    ),
    playbook_dir: Path = typer.Option(Path("playbooks"), "--playbook-dir"),
    big_flow_fixture: Path = typer.Option(DEFAULT_BIG_FLOW_FIXTURE, "--big-flow-fixture"),
    portfolio_fixture: Path = typer.Option(
        Path("tests/fixtures/portfolio_holdings_core_satellite.json"),
        "--portfolio-fixture",
    ),
    portfolio_config: Path = typer.Option(Path("configs/portfolio.example.yaml"), "--portfolio-config"),
) -> None:
    init_database(db_url)
    with session_scope(db_url) as session:
        thesis_pack_result = run_kor_semi_thesis_pack_demo_flow(
            session,
            config_path=config,
            thesis_dir=thesis_dir,
            scenario_dir=scenario_dir,
            playbook_dir=playbook_dir,
            memo_dir=memo_dir,
            big_flow_fixture=big_flow_fixture,
        )
        portfolio_result = run_portfolio_review_demo_flow(
            session=session,
            as_of=thesis_pack_result.as_of,
            portfolio_fixture=portfolio_fixture,
            portfolio_config=portfolio_config,
            memo_dir=memo_dir,
            thesis_dir=thesis_dir,
            scenario_dir=scenario_dir,
        )
    launch_command = _dashboard_command(db_url, memo_dir)
    _echo_json(
        {
            "status": "ready",
            "db_url": db_url,
            "memo_dir": str(memo_dir),
            "kor_semi_memo_path": thesis_pack_result.memo_path,
            "portfolio_memo_path": portfolio_result.memo_path,
            "matched_scenarios": thesis_pack_result.matched_scenarios,
            "allowed_actions": thesis_pack_result.allowed_actions,
            "dashboard_command": " ".join(launch_command),
            "no_auto_trade": True,
        }
    )


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
