from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Iterable

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from project_stock.db.models import IndicatorObservation, RawDocument
from project_stock.events.financials import normalize_financial_events
from project_stock.events.normalization import normalize_events
from project_stock.evidence.generation import generate_and_append_evidence
from project_stock.ingest.base import CollectorConfigError, CollectorIngestResult
from project_stock.ingest.dart import OpenDartCollector
from project_stock.ingest.ecos import EcosCollector
from project_stock.ingest.fred import FredCollector
from project_stock.ingest.krx import KrxCollector
from project_stock.ingest.opendart_financials import OpenDartFinancialCollector
from project_stock.ingest.real_data import (
    NETWORK_ENV_VAR,
    NetworkDisabledError,
    network_enabled,
)
from project_stock.ingest.sources import register_official_sources
from project_stock.portfolio.review import review_portfolio
from project_stock.reports.render import render_report
from project_stock.schemas.common import SchemaBase
from project_stock.schemas.indicators import IndicatorObservationCreate
from project_stock.schemas.real_data_smoke import (
    RealDataSmokeConfig,
    RealDataSmokeResult,
    RealDataSmokeSourceStatus,
    SmokeMode,
)
from project_stock.storage.repository import Repository
from project_stock.thesis.lifecycle import evaluate_thesis_states

DEFAULT_REAL_DATA_SMOKE_CONFIG = Path("configs/real_data_smoke.kor_semi.example.yaml")
NO_AUTO_TRADE_DISCLAIMER = (
    "No auto-trade: real-data smoke output is decision support only and does not "
    "authorize broker execution, auto-trading, live buy/sell orders, or "
    "LLM-directed investment decisions."
)


class SmokeIngestSummary(SchemaBase):
    inserted_counts: dict[str, int]
    skipped_duplicate_counts: dict[str, int]


def load_real_data_smoke_config(path: Path | str = DEFAULT_REAL_DATA_SMOKE_CONFIG) -> RealDataSmokeConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return RealDataSmokeConfig.model_validate(payload)


def _date_count(config: RealDataSmokeConfig) -> int:
    return (config.end_date - config.start_date).days + 1


def _estimated_real_records(config: RealDataSmokeConfig) -> int:
    days = max(0, _date_count(config))
    return (
        len(config.fred_series) * days
        + len(config.ecos_indicators) * days
        + len(config.opendart_companies) * config.opendart_disclosure.page_count
        + len(config.opendart_companies)
        * len(config.opendart_financials.years)
        * len(config.opendart_financials.report_codes)
        * 8
        + len(config.krx_symbols) * days
    )


def validate_smoke_limits(config: RealDataSmokeConfig) -> None:
    if config.end_date < config.start_date:
        raise ValueError("real-data smoke end_date must be on or after start_date.")
    if _date_count(config) > config.max_days:
        raise ValueError(
            f"real-data smoke date range spans {_date_count(config)} days; "
            f"max_days is {config.max_days}."
        )
    estimate = _estimated_real_records(config)
    if estimate > config.max_records:
        raise ValueError(
            f"real-data smoke request estimates {estimate} records; "
            f"max_records is {config.max_records}."
        )


def _any_env_set(names: Iterable[str]) -> bool:
    return any(bool(os.getenv(name, "").strip()) for name in names)


def _source_status(
    *,
    source_id: str,
    adapter: str,
    required_api_keys: list[str],
    would_run: bool,
    mode: SmokeMode,
) -> RealDataSmokeSourceStatus:
    enabled = network_enabled()
    key_set = True if not required_api_keys else _any_env_set(required_api_keys)
    if not would_run:
        return RealDataSmokeSourceStatus(
            source_id=source_id,
            adapter=adapter,
            would_run=False,
            network_enabled=enabled,
            required_api_keys=required_api_keys,
            api_key_set=key_set,
            available=True,
            reason="not configured for this smoke run",
        )
    if mode in {"dry_run", "fixture"}:
        reason = "dry-run only; no network calls" if mode == "dry_run" else "fixture mode; no network calls"
        if required_api_keys and not key_set:
            reason = f"{reason}; real mode would require {' or '.join(required_api_keys)}"
        return RealDataSmokeSourceStatus(
            source_id=source_id,
            adapter=adapter,
            would_run=True,
            network_enabled=enabled,
            required_api_keys=required_api_keys,
            api_key_set=key_set,
            available=True,
            reason=reason,
        )
    if not enabled:
        return RealDataSmokeSourceStatus(
            source_id=source_id,
            adapter=adapter,
            would_run=True,
            network_enabled=False,
            required_api_keys=required_api_keys,
            api_key_set=key_set,
            available=False,
            reason=f"network disabled; set {NETWORK_ENV_VAR}=true",
        )
    if required_api_keys and not key_set:
        return RealDataSmokeSourceStatus(
            source_id=source_id,
            adapter=adapter,
            would_run=True,
            network_enabled=True,
            required_api_keys=required_api_keys,
            api_key_set=False,
            available=False,
            reason=f"missing API key: {' or '.join(required_api_keys)}",
        )
    return RealDataSmokeSourceStatus(
        source_id=source_id,
        adapter=adapter,
        would_run=True,
        network_enabled=True,
        required_api_keys=required_api_keys,
        api_key_set=key_set,
        available=True,
        reason="ready for bounded real fetch",
    )


def build_source_statuses(
    config: RealDataSmokeConfig,
    mode: SmokeMode,
) -> list[RealDataSmokeSourceStatus]:
    return [
        _source_status(
            source_id="FRED",
            adapter="fred_series",
            required_api_keys=["FRED_API_KEY"],
            would_run=bool(config.fred_series),
            mode=mode,
        ),
        _source_status(
            source_id="BOK_ECOS",
            adapter="ecos_series",
            required_api_keys=["ECOS_API_KEY"],
            would_run=bool(config.ecos_indicators),
            mode=mode,
        ),
        _source_status(
            source_id="OPEN_DART",
            adapter="opendart_disclosures",
            required_api_keys=["DART_API_KEY", "OPEN_DART_API_KEY"],
            would_run=bool(config.opendart_companies),
            mode=mode,
        ),
        _source_status(
            source_id="OPEN_DART",
            adapter="opendart_financials",
            required_api_keys=["DART_API_KEY", "OPEN_DART_API_KEY"],
            would_run=bool(config.opendart_financials.years)
            and bool(config.opendart_financials.report_codes)
            and bool(config.opendart_companies),
            mode=mode,
        ),
        _source_status(
            source_id="KRX",
            adapter="krx_daily",
            required_api_keys=[],
            would_run=bool(config.krx_symbols),
            mode=mode,
        ),
    ]


def _raise_if_real_unavailable(statuses: list[RealDataSmokeSourceStatus]) -> None:
    if not network_enabled():
        raise NetworkDisabledError(
            f"Network access is disabled. Set {NETWORK_ENV_VAR}=true to run real-data smoke."
        )
    missing = [status for status in statuses if not status.available and "missing API key" in status.reason]
    if missing:
        details = "; ".join(
            f"{status.adapter}: {' or '.join(status.required_api_keys)}" for status in missing
        )
        raise CollectorConfigError(f"Unavailable smoke sources due to missing API keys: {details}.")


def real_data_smoke_doctor_payload(
    config_path: Path | str = DEFAULT_REAL_DATA_SMOKE_CONFIG,
) -> dict[str, object]:
    config = load_real_data_smoke_config(config_path)
    validate_smoke_limits(config)
    statuses = build_source_statuses(config, "dry_run")
    return {
        "status": "ok",
        "smoke_id": config.smoke_id,
        NETWORK_ENV_VAR: os.getenv(NETWORK_ENV_VAR, "false"),
        "network_enabled": network_enabled(),
        "source_statuses": [status.model_dump(mode="json") for status in statuses],
        "required_api_keys": {
            "FRED": ["FRED_API_KEY"],
            "BOK_ECOS": ["ECOS_API_KEY"],
            "OPEN_DART": ["DART_API_KEY", "OPEN_DART_API_KEY"],
            "KRX": [],
        },
        "date_range": {
            "start_date": config.start_date.isoformat(),
            "end_date": config.end_date.isoformat(),
            "days": _date_count(config),
        },
        "fred_series": config.fred_series,
        "ecos_indicators": config.ecos_indicators,
        "opendart_companies": [company.model_dump(mode="json") for company in config.opendart_companies],
        "opendart_disclosure": config.opendart_disclosure.model_dump(mode="json"),
        "opendart_financials": config.opendart_financials.model_dump(mode="json"),
        "krx_symbols": config.krx_symbols,
        "safety_limits": {
            "max_records": config.max_records,
            "max_days": config.max_days,
            "estimated_records": _estimated_real_records(config),
        },
        "no_auto_trade": True,
        "warning": NO_AUTO_TRADE_DISCLAIMER,
    }


def _same_time(left: object | None, right: object | None) -> bool:
    if isinstance(left, datetime) and isinstance(right, datetime):
        left_value = left.astimezone(UTC) if left.tzinfo else left.replace(tzinfo=UTC)
        right_value = right.astimezone(UTC) if right.tzinfo else right.replace(tzinfo=UTC)
        return left_value == right_value
    return left == right


def _indicator_exists(session: Session, record: IndicatorObservationCreate) -> bool:
    rows = session.scalars(
        select(IndicatorObservation).where(IndicatorObservation.source_id == record.source_id)
    ).all()
    for row in rows:
        if (
            row.indicator_id == record.indicator_id
            and row.observation_period == record.observation_period
            and _same_time(row.release_at, record.release_at)
        ):
            return True
    return False


def _append_indicator_observations(
    session: Session,
    records: list[IndicatorObservationCreate],
    *,
    collector_id: str,
    source_id: str,
) -> CollectorIngestResult:
    repo = Repository(session)
    inserted_ids: list[str] = []
    skipped_count = 0
    for record in records:
        if _indicator_exists(session, record):
            skipped_count += 1
            continue
        inserted_ids.append(repo.add_indicator_observation(record).observation_id)
    return CollectorIngestResult(
        collector_id=collector_id,
        source_id=source_id,
        inserted_count=len(inserted_ids),
        skipped_count=skipped_count,
        record_ids=inserted_ids,
    )


def _add_result_counts(
    result: CollectorIngestResult,
    table_name: str,
    inserted: Counter[str],
    skipped: Counter[str],
) -> None:
    key = f"{result.source_id}.{table_name}"
    inserted[key] += result.inserted_count
    skipped[key] += result.skipped_count


def _ingest_fred(
    session: Session,
    config: RealDataSmokeConfig,
    mode: SmokeMode,
) -> list[CollectorIngestResult]:
    collector = FredCollector()
    results: list[CollectorIngestResult] = []
    for series_id in config.fred_series:
        raw_records = collector.fetch_series(
            series_id=series_id,
            start_date=config.start_date.isoformat(),
            end_date=config.end_date.isoformat(),
            fixture=config.fixture_paths.fred_observations if mode == "fixture" else None,
            cache_raw=mode == "real",
        )
        records = collector.normalize(raw_records)
        results.append(
            _append_indicator_observations(
                session,
                records,
                collector_id=collector.collector_id,
                source_id=collector.source_id,
            )
        )
    return results


def _ingest_ecos(
    session: Session,
    config: RealDataSmokeConfig,
    mode: SmokeMode,
) -> list[CollectorIngestResult]:
    collector = EcosCollector()
    results: list[CollectorIngestResult] = []
    for indicator_id in config.ecos_indicators:
        raw_records = collector.fetch_series(
            indicator_id=indicator_id,
            start_date=config.start_date.isoformat(),
            end_date=config.end_date.isoformat(),
            series_config=config.config_paths.ecos_series,
            fixture=config.fixture_paths.ecos_statistic_search if mode == "fixture" else None,
            cache_raw=mode == "real",
        )
        records = collector.normalize(raw_records)
        results.append(
            _append_indicator_observations(
                session,
                records,
                collector_id=collector.collector_id,
                source_id=collector.source_id,
            )
        )
    return results


def _ingest_opendart_disclosures(
    session: Session,
    config: RealDataSmokeConfig,
    mode: SmokeMode,
) -> list[CollectorIngestResult]:
    collector = OpenDartCollector()
    if mode == "fixture":
        return [
            collector.ingest_disclosures(
                session=session,
                corp_code=None,
                stock_code=None,
                bgn_de="19700101",
                end_de="29991231",
                fixture=config.fixture_paths.opendart_disclosures,
                cache_raw=False,
            )
        ]
    results: list[CollectorIngestResult] = []
    for company in config.opendart_companies:
        results.append(
            collector.ingest_disclosures(
                session=session,
                corp_code=company.corp_code,
                stock_code=company.stock_code,
                bgn_de=config.opendart_disclosure.bgn_de,
                end_de=config.opendart_disclosure.end_de,
                page_count=config.opendart_disclosure.page_count,
                corp_code_config=config.config_paths.opendart_corp_codes,
                cache_raw=True,
            )
        )
    return results


def _ingest_opendart_financials(
    session: Session,
    config: RealDataSmokeConfig,
    mode: SmokeMode,
) -> list[CollectorIngestResult]:
    collector = OpenDartFinancialCollector()
    if (
        not config.opendart_companies
        or not config.opendart_financials.years
        or not config.opendart_financials.report_codes
    ):
        return []
    if mode == "fixture":
        company = config.opendart_companies[0]
        return [
            collector.ingest_financials(
                session,
                corp_code=company.corp_code,
                stock_code=company.stock_code,
                bsns_year=config.opendart_financials.years[0],
                reprt_code=config.opendart_financials.report_codes[0],
                corp_code_config=config.config_paths.opendart_corp_codes,
                fixture=config.fixture_paths.opendart_financials,
                cache_raw=False,
            )
        ]
    results: list[CollectorIngestResult] = []
    for company in config.opendart_companies:
        for year in config.opendart_financials.years:
            for report_code in config.opendart_financials.report_codes:
                results.append(
                    collector.ingest_financials(
                        session,
                        corp_code=company.corp_code,
                        stock_code=company.stock_code,
                        bsns_year=year,
                        reprt_code=report_code,
                        corp_code_config=config.config_paths.opendart_corp_codes,
                        cache_raw=True,
                    )
                )
    return results


def _ingest_krx(
    session: Session,
    config: RealDataSmokeConfig,
    mode: SmokeMode,
) -> list[CollectorIngestResult]:
    collector = KrxCollector()
    results: list[CollectorIngestResult] = []
    for symbol in config.krx_symbols:
        results.append(
            collector.ingest_daily(
                session,
                symbol=symbol,
                start_date=config.start_date.isoformat(),
                end_date=config.end_date.isoformat(),
                symbol_config=config.config_paths.krx_symbols,
                fixture=config.fixture_paths.krx_daily if mode == "fixture" else None,
                cache_raw=mode == "real",
            )
        )
    return results


def _run_ingestion(
    session: Session,
    config: RealDataSmokeConfig,
    mode: SmokeMode,
) -> SmokeIngestSummary:
    inserted: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    for result in _ingest_fred(session, config, mode):
        _add_result_counts(result, "indicator_observations", inserted, skipped)
    for result in _ingest_ecos(session, config, mode):
        _add_result_counts(result, "indicator_observations", inserted, skipped)
    for result in _ingest_opendart_disclosures(session, config, mode):
        _add_result_counts(result, "raw_documents", inserted, skipped)
    for result in _ingest_opendart_financials(session, config, mode):
        _add_result_counts(result, "financial_statement_line_items", inserted, skipped)
    for result in _ingest_krx(session, config, mode):
        _add_result_counts(result, "market_time_series", inserted, skipped)
    return SmokeIngestSummary(
        inserted_counts=dict(inserted),
        skipped_duplicate_counts=dict(skipped),
    )


def _raw_document_count(session: Session) -> int:
    return len(session.scalars(select(RawDocument)).all())


def _write_smoke_memo(
    config: RealDataSmokeConfig,
    result: RealDataSmokeResult,
) -> str:
    config.memo_dir.mkdir(parents=True, exist_ok=True)
    memo_path = config.memo_dir / f"real_data_smoke_report_{config.smoke_id}_{result.mode}.md"
    memo = render_report(
        "real_data_smoke_report.md.j2",
        {
            "config": config,
            "result": result,
            "source_statuses": result.source_statuses,
            "inserted_counts": result.inserted_counts,
            "skipped_duplicate_counts": result.skipped_duplicate_counts,
            "events_by_type": result.events_by_type,
            "evidence_by_thesis": result.evidence_by_thesis,
            "thesis_states": result.thesis_states,
            "warnings": result.warnings,
            "no_auto_trade_disclaimer": NO_AUTO_TRADE_DISCLAIMER,
        },
    )
    memo_path.write_text(memo, encoding="utf-8")
    return str(memo_path)


def _thesis_states(thesis_result: object) -> dict[str, str]:
    evaluations = getattr(thesis_result, "evaluations", [])
    states: dict[str, str] = {}
    for evaluation in evaluations:
        if not hasattr(evaluation, "thesis_id"):
            continue
        state = evaluation.proposed_state
        states[evaluation.thesis_id] = state.value if hasattr(state, "value") else str(state)
    return states


def run_real_data_smoke(
    config_path: Path | str = DEFAULT_REAL_DATA_SMOKE_CONFIG,
    *,
    mode: SmokeMode,
    session: Session | None = None,
    thesis_dir: Path | str = "thesis",
    scenario_dir: Path | str = "scenarios",
) -> RealDataSmokeResult:
    config = load_real_data_smoke_config(config_path)
    validate_smoke_limits(config)
    statuses = build_source_statuses(config, mode)
    warnings: list[str] = []

    if mode == "dry_run":
        warnings.append("dry_run_completed_without_network_or_database_writes")
        return RealDataSmokeResult(
            smoke_id=config.smoke_id,
            mode=mode,
            source_statuses=statuses,
            warnings=warnings,
        )

    if session is None:
        raise ValueError("A database session is required for fixture and real smoke modes.")
    if mode == "real":
        _raise_if_real_unavailable(statuses)

    register_official_sources(session)
    before_raw_documents = _raw_document_count(session)
    ingest_summary = _run_ingestion(session, config, mode)
    after_raw_documents = _raw_document_count(session)
    if after_raw_documents < before_raw_documents:
        warnings.append("raw_document_count_decreased_unexpectedly")

    normalization = normalize_events(session)
    financial_normalization = normalize_financial_events(session)
    evidence = generate_and_append_evidence(session, thesis_dir, scenario_dir)
    thesis_result = evaluate_thesis_states(
        session=session,
        as_of=config.end_date,
        thesis_dir=thesis_dir,
        memo_dir=config.memo_dir,
    )
    portfolio_memo_path = None
    if config.fixture_paths.portfolio is not None and config.config_paths.portfolio is not None:
        portfolio = review_portfolio(
            session=session,
            portfolio_fixture=config.fixture_paths.portfolio,
            portfolio_config=config.config_paths.portfolio,
            as_of=config.end_date,
            memo_dir=config.memo_dir,
        )
        portfolio_memo_path = portfolio.memo_path

    events_by_type = Counter(normalization.counts_by_event_type)
    events_by_type.update(financial_normalization.counts_by_event_type)
    result = RealDataSmokeResult(
        smoke_id=config.smoke_id,
        mode=mode,
        source_statuses=statuses,
        inserted_counts=ingest_summary.inserted_counts,
        skipped_duplicate_counts={
            **ingest_summary.skipped_duplicate_counts,
            "EvidenceLedger": evidence.skipped_count,
            "ThesisStateSnapshot": thesis_result.skipped_duplicate_snapshot_count,
        },
        normalized_event_count=len(normalization.inserted_event_ids)
        + len(financial_normalization.inserted_event_ids),
        events_by_type=dict(events_by_type),
        evidence_count=evidence.appended_count,
        evidence_by_thesis=evidence.counts_by_thesis_id,
        thesis_snapshot_count=thesis_result.snapshot_count,
        thesis_states=_thesis_states(thesis_result),
        warnings=warnings,
        portfolio_memo_path=portfolio_memo_path,
    )
    memo_path = _write_smoke_memo(config, result)
    return result.model_copy(update={"memo_path": memo_path})
