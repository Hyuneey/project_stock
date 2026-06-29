from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from project_stock.db.models import Event, EvidenceLedger, IndicatorObservation, MarketTimeSeries, RawDocument
from project_stock.events.classifier import event_from_document
from project_stock.events.mapper import map_entities
from project_stock.events.normalization import EventNormalizationResult, normalize_events
from project_stock.evidence.generation import append_evidence_candidates, generate_evidence_candidates
from project_stock.ingest.base import CollectorIngestResult
from project_stock.ingest.dart import OpenDartCollector
from project_stock.ingest.ecos import EcosCollector
from project_stock.ingest.fred import FredCollector
from project_stock.ingest.krx import KrxCollector
from project_stock.ingest.news import NewsRssCollector
from project_stock.ingest.sources import register_official_sources
from project_stock.playbooks.executor import execute_playbooks
from project_stock.playbooks.loader import load_playbook_dir
from project_stock.reports.render import render_report
from project_stock.scenarios.loader import load_scenario_dir
from project_stock.scenarios.matcher import match_scenarios
from project_stock.schemas.common import EMERGENCY_LEVEL_ORDER, EmergencyLevel
from project_stock.schemas.decisions import DecisionCreate
from project_stock.schemas.documents import RawDocumentCreate
from project_stock.schemas.indicators import IndicatorObservationCreate
from project_stock.schemas.market import MarketTimeSeriesCreate
from project_stock.schemas.operations import DailyReviewResult, IntradayReviewResult
from project_stock.schemas.scenarios import ScenarioMatchResult
from project_stock.schemas.scoring import EmergencyImpactInput
from project_stock.scoring.emergency import score_emergency_impact
from project_stock.storage.repository import Repository

DEFAULT_OFFICIAL_FIXTURE_DIR = Path("tests/fixtures/official")
DEFAULT_MEMO_DIR = Path("data/processed")
NO_AUTO_TRADE_DISCLAIMER = (
    "No auto-trade: this memo is decision support only and does not authorize "
    "broker order execution or LLM-directed buy/sell decisions."
)


def _datetime_key(value: object | None) -> object | None:
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _same_time(left: object | None, right: object | None) -> bool:
    return _datetime_key(left) == _datetime_key(right)


def _raw_document_exists(session: Session, record: RawDocumentCreate) -> bool:
    repo = Repository(session)
    if record.checksum and repo.find_raw_document_by_checksum(record.checksum, record.source_id):
        return True
    metadata = record.metadata_json or {}
    rcept_no = metadata.get("rcept_no")
    documents = session.scalars(
        select(RawDocument).where(RawDocument.source_id == record.source_id)
    ).all()
    for document in documents:
        document_metadata = document.metadata_json or {}
        if rcept_no and document_metadata.get("rcept_no") == rcept_no:
            return True
        if (
            document.title == record.title
            and document.url == record.url
            and _same_time(document.published_at, record.published_at)
        ):
            return True
    return False


def _indicator_observation_exists(
    session: Session,
    record: IndicatorObservationCreate,
) -> bool:
    observations = session.scalars(
        select(IndicatorObservation).where(IndicatorObservation.source_id == record.source_id)
    ).all()
    for observation in observations:
        if (
            observation.indicator_id == record.indicator_id
            and observation.observation_period == record.observation_period
            and _same_time(observation.release_at, record.release_at)
        ):
            return True
    return False


def _market_time_series_exists(session: Session, record: MarketTimeSeriesCreate) -> bool:
    rows = session.scalars(
        select(MarketTimeSeries).where(MarketTimeSeries.source_id == record.source_id)
    ).all()
    for row in rows:
        if (
            row.symbol == record.symbol
            and row.frequency == record.frequency
            and _same_time(row.timestamp, record.timestamp)
        ):
            return True
    return False


def _ingest_collector_idempotent(
    session: Session,
    collector: object,
    fixture: Path,
) -> CollectorIngestResult:
    repo = Repository(session)
    records = collector.normalize(collector.fetch_raw(fixture=fixture, mock=True))
    inserted_ids: list[str] = []
    skipped_count = 0
    for record in records:
        if isinstance(record, RawDocumentCreate):
            if _raw_document_exists(session, record):
                skipped_count += 1
                continue
            inserted_ids.append(repo.add_raw_document_create(record).doc_id)
            continue
        if isinstance(record, IndicatorObservationCreate):
            if _indicator_observation_exists(session, record):
                skipped_count += 1
                continue
            inserted_ids.append(repo.add_indicator_observation(record).observation_id)
            continue
        if isinstance(record, MarketTimeSeriesCreate):
            if _market_time_series_exists(session, record):
                skipped_count += 1
                continue
            inserted_ids.append(repo.add_market_time_series(record).series_id)
            continue
        skipped_count += 1
    return CollectorIngestResult(
        collector_id=collector.collector_id,
        source_id=collector.source_id,
        inserted_count=len(inserted_ids),
        skipped_count=skipped_count,
        record_ids=inserted_ids,
    )


def ingest_official_mock_bundle_idempotent(
    session: Session,
    fixture_dir: Path,
) -> list[CollectorIngestResult]:
    register_official_sources(session)
    collectors = [
        (OpenDartCollector(), fixture_dir / "dart_disclosures.json"),
        (EcosCollector(), fixture_dir / "ecos_indicators.json"),
        (FredCollector(), fixture_dir / "fred_indicators.json"),
        (KrxCollector(), fixture_dir / "krx_market.json"),
        (NewsRssCollector(), fixture_dir / "news_rss.json"),
    ]
    return [
        _ingest_collector_idempotent(session, collector, fixture)
        for collector, fixture in collectors
    ]


def _setdefault_metric(metrics: dict[str, object], key: str, value: object) -> None:
    if key not in metrics:
        metrics[key] = value


def _apply_event_metric_hints(metrics: dict[str, object], event: Event) -> None:
    metadata = event.metadata_json or {}
    summary = event.summary.lower()
    symbol = str(metadata.get("symbol", "")).upper()
    pct_move = metadata.get("pct_move")
    absolute_move = metadata.get("absolute_move")
    entity_ids = {entity.entity_id for entity in event.entities}

    if event.event_type == "sector_news_headline" and any(
        word in summary for word in ("ai", "hbm", "demand", "improve")
    ):
        _setdefault_metric(metrics, "HBM_PRICE_CHANGE_1M_PCT", 5.0)
        _setdefault_metric(metrics, "KOR_SEMI_REL_STRENGTH_1M_PCT", 3.5)
    if event.event_type == "earnings_guidance":
        _setdefault_metric(metrics, "EPS_REVISION_1M_PCT", 2.5)
    if event.event_type in {"earnings_revision_candidate", "risk_disclosure_candidate"}:
        _setdefault_metric(metrics, "EPS_REVISION_1M_PCT", -4.0)
    if event.event_type == "sector_relative_strength_move" and isinstance(pct_move, (int, float)):
        _setdefault_metric(metrics, "KOR_SEMI_REL_STRENGTH_1M_PCT", float(pct_move))
    if event.event_type == "market_large_move" and isinstance(pct_move, (int, float)):
        if symbol in {"005930", "000660", "SOX"} or entity_ids.intersection({"005930", "000660", "SOX"}):
            _setdefault_metric(metrics, "KOR_SEMI_REL_STRENGTH_1M_PCT", float(pct_move))
    if event.event_type == "fx_stress_move" and isinstance(pct_move, (int, float)):
        _setdefault_metric(metrics, "USDKRW_CHANGE_1D_PCT", abs(float(pct_move)))
    if event.event_type == "rates_shock_move":
        if isinstance(absolute_move, (int, float)):
            _setdefault_metric(metrics, "US2Y_YIELD_CHANGE_1D_BP", abs(float(absolute_move)) * 100)
        else:
            _setdefault_metric(metrics, "US2Y_YIELD_CHANGE_1D_BP", 20)
    if event.event_type == "volatility_shock_move" and isinstance(pct_move, (int, float)):
        _setdefault_metric(metrics, "VIX_CHANGE_1D_PCT", abs(float(pct_move)))
    if event.event_type == "macro_rate_shock":
        text = f"{event.summary} {metadata}".lower()
        if "us2y" in text or "yield" in text or "rate" in text:
            _setdefault_metric(metrics, "US2Y_YIELD_CHANGE_1D_BP", 20)
        if "usdkrw" in text:
            _setdefault_metric(metrics, "USDKRW_CHANGE_1D_PCT", 1.2)
        if "sox" in text:
            _setdefault_metric(metrics, "SOX_CHANGE_1D_PCT", -3.1)


def _apply_evidence_metric_hints(metrics: dict[str, object], evidence: EvidenceLedger) -> None:
    metadata = evidence.metadata_json or {}
    source_event_type = str(metadata.get("source_event_type", ""))
    if evidence.supports_or_contradicts == "supports" and source_event_type == "sector_news_headline":
        _setdefault_metric(metrics, "HBM_PRICE_CHANGE_1M_PCT", 5.0)
    if (
        evidence.supports_or_contradicts == "contradicts"
        and source_event_type == "earnings_revision_candidate"
    ):
        _setdefault_metric(metrics, "EPS_REVISION_1M_PCT", -4.0)


def build_review_metrics(
    events: list[Event],
    evidence_rows: list[EvidenceLedger],
    explicit_metrics: dict[str, object] | None = None,
) -> dict[str, object]:
    metrics = dict(explicit_metrics or {})
    for event in events:
        _apply_event_metric_hints(metrics, event)
    for evidence in evidence_rows:
        _apply_evidence_metric_hints(metrics, evidence)
    return metrics


def _matched_scenarios(
    scenarios: list[object],
    metrics: dict[str, object],
) -> list[ScenarioMatchResult]:
    return [match for match in match_scenarios(scenarios, metrics) if match.matched]


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _write_memo(
    memo_dir: Path,
    filename: str,
    template_name: str,
    context: dict[str, object],
) -> str:
    memo_dir.mkdir(parents=True, exist_ok=True)
    memo_path = memo_dir / filename
    memo_path.write_text(render_report(template_name, context), encoding="utf-8")
    return str(memo_path)


def _event_id_for_scenario(
    scenario_id: str,
    evidence_rows: list[EvidenceLedger],
    events: list[Event],
) -> str | None:
    for evidence in evidence_rows:
        if evidence.scenario_id == scenario_id and evidence.event_id:
            return evidence.event_id
    return events[0].event_id if events else None


def _append_scenario_trigger_logs(
    repo: Repository,
    matched: list[ScenarioMatchResult],
    evidence_rows: list[EvidenceLedger],
    events: list[Event],
) -> int:
    for match in matched:
        repo.append_scenario_trigger(
            scenario_id=match.scenario_id,
            thesis_id=match.thesis_id,
            event_id=_event_id_for_scenario(match.scenario_id, evidence_rows, events),
            match_score=match.match_score,
            result_state="triggered",
            metadata_json=match.model_dump(mode="json"),
        )
    return len(matched)


def run_daily_review_loop(
    as_of: date,
    db_session: Session,
    thesis_dir: Path | str = "thesis",
    scenario_dir: Path | str = "scenarios",
    playbook_dir: Path | str = "playbooks",
    fixture_dir: Path | str = DEFAULT_OFFICIAL_FIXTURE_DIR,
    memo_dir: Path | str = DEFAULT_MEMO_DIR,
    ingest_mock: bool = False,
    normalize: bool = True,
    generate_evidence: bool = True,
    metrics: dict[str, object] | None = None,
) -> DailyReviewResult:
    repo = Repository(db_session)
    warnings: list[str] = []
    register_official_sources(db_session)

    inserted_raw_counts: dict[str, int] = {}
    if ingest_mock:
        ingest_results = ingest_official_mock_bundle_idempotent(db_session, Path(fixture_dir))
        inserted_raw_counts = {
            result.source_id: result.inserted_count for result in ingest_results
        }

    normalization = EventNormalizationResult()
    if normalize:
        normalization = normalize_events(db_session)

    evidence_result = None
    if generate_evidence:
        generated = generate_evidence_candidates(db_session, thesis_dir, scenario_dir)
        evidence_result = append_evidence_candidates(db_session, generated.candidates)

    events = repo.list_events_with_entities()
    evidence_rows = repo.list_evidence()
    review_metrics = build_review_metrics(events, evidence_rows, metrics)
    scenarios = load_scenario_dir(scenario_dir)
    playbooks = load_playbook_dir(playbook_dir)
    matched = _matched_scenarios(scenarios, review_metrics)
    _append_scenario_trigger_logs(repo, matched, evidence_rows, events)
    playbook_results = execute_playbooks(playbooks, matched, EmergencyLevel.E0, confirmations=[])

    appended_evidence_count = evidence_result.appended_count if evidence_result else 0
    skipped_duplicate_evidence_count = evidence_result.skipped_count if evidence_result else 0
    evidence_candidate_count = evidence_result.candidate_count if evidence_result else 0
    evidence_counts_by_thesis = evidence_result.counts_by_thesis_id if evidence_result else {}
    evidence_counts_by_stance = evidence_result.counts_by_stance if evidence_result else {}

    first_match = matched[0] if matched else None
    decision = repo.append_decision(
        DecisionCreate(
            decision_type="daily_review",
            thesis_id=first_match.thesis_id if first_match else None,
            scenario_id=first_match.scenario_id if first_match else None,
            action="review_only",
            rationale=(
                f"Daily review processed {len(events)} events, "
                f"{appended_evidence_count} new evidence rows, and {len(matched)} scenario matches."
            ),
            portfolio_impact="no_auto_trade / human_review_required",
            review_after="next daily review",
            metadata_json={
                "as_of": as_of.isoformat(),
                "review_metrics": review_metrics,
                "matched_scenarios": [match.scenario_id for match in matched],
                "appended_evidence_count": appended_evidence_count,
                "skipped_duplicate_evidence_count": skipped_duplicate_evidence_count,
                "no_auto_trade": True,
            },
        )
    )

    event_type_counts = Counter(event.event_type for event in events)
    memo_path = _write_memo(
        Path(memo_dir),
        f"daily_review_memo_{as_of.isoformat()}.md",
        "daily_review_memo.md.j2",
        {
            "as_of": as_of.isoformat(),
            "new_events_by_type": normalization.counts_by_event_type,
            "all_events_by_type": dict(event_type_counts),
            "evidence_counts_by_thesis": evidence_counts_by_thesis,
            "evidence_counts_by_stance": evidence_counts_by_stance,
            "matched_scenarios": matched,
            "playbook_results": playbook_results,
            "recommended_review_items": _recommended_daily_review_items(matched, evidence_counts_by_stance),
            "decision_id": decision.decision_id,
            "disclaimer": NO_AUTO_TRADE_DISCLAIMER,
        },
    )

    return DailyReviewResult(
        as_of=as_of,
        inserted_raw_counts=inserted_raw_counts,
        inserted_event_count=len(normalization.inserted_event_ids),
        mapped_entity_count=normalization.entity_count,
        evidence_candidate_count=evidence_candidate_count,
        appended_evidence_count=appended_evidence_count,
        skipped_duplicate_evidence_count=skipped_duplicate_evidence_count,
        scenario_match_count=len(matched),
        decision_log_count=1,
        memo_path=memo_path,
        warnings=warnings,
        new_events_by_type=normalization.counts_by_event_type,
        evidence_counts_by_thesis=evidence_counts_by_thesis,
        evidence_counts_by_stance=evidence_counts_by_stance,
        matched_scenarios=matched,
        playbook_results=playbook_results,
    )


def _recommended_daily_review_items(
    matched: list[ScenarioMatchResult],
    evidence_counts_by_stance: dict[str, int],
) -> list[str]:
    items = ["Review appended evidence before any portfolio action."]
    if matched:
        items.append("Review matched scenario diagnostics and required confirmations.")
    if evidence_counts_by_stance.get("contradicts", 0) > 0:
        items.append("Review contradicting evidence for thesis deterioration risk.")
    return items


def _emergency_source_record_id(event_input: dict[str, Any]) -> str:
    stable = {
        "title": event_input.get("title"),
        "body_text": event_input.get("body_text"),
        "event_time": event_input.get("event_time"),
    }
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"emergency:{digest[:24]}"


def _get_or_create_emergency_event(
    repo: Repository,
    event_input: dict[str, Any],
) -> Event:
    event_create = event_from_document(event_input)
    source_record_id = _emergency_source_record_id(event_input)
    metadata = {
        **(event_create.metadata_json or {}),
        "source_table": "emergency_events",
        "source_record_id": source_record_id,
        "event_input_title": event_input.get("title"),
        "event_input_body_text": event_input.get("body_text"),
    }
    event_create = event_create.model_copy(update={"metadata_json": metadata})
    existing = repo.find_event_by_source_record(
        "emergency_events",
        source_record_id,
        event_create.event_type,
    )
    if existing is not None:
        if not existing.entities:
            repo.add_event_entities(existing.event_id, _emergency_entities(event_input, existing))
        return existing
    event = repo.add_event(event_create)
    repo.add_event_entities(event.event_id, _emergency_entities(event_input, event))
    return event


def _emergency_entities(event_input: dict[str, Any], event: Event) -> list[dict[str, object]]:
    return map_entities(
        f"{event_input.get('title', '')} {event_input.get('body_text', '')} "
        f"{event.summary} {event.event_type}"
    )


def _emergency_input_from_context(
    event: Event,
    exposure_context: dict[str, object],
) -> EmergencyImpactInput:
    return EmergencyImpactInput(
        source_reliability=float(exposure_context.get("source_reliability", event.source_reliability)),
        relevance=float(exposure_context.get("relevance", 4.0)),
        surprise=float(exposure_context.get("surprise", event.surprise_score)),
        transmission=float(exposure_context.get("transmission", 4.0)),
        market_confirmation=float(
            exposure_context.get("market_confirmation", event.market_confirmation_score)
        ),
        exposure=float(exposure_context.get("exposure", 4.0)),
    )


def _action_for_emergency_level(level: EmergencyLevel) -> str:
    if EMERGENCY_LEVEL_ORDER[level] >= EMERGENCY_LEVEL_ORDER[EmergencyLevel.E3]:
        return "no_new_buy"
    return "risk_review_only"


def run_intraday_review_loop(
    event_input: dict[str, Any],
    metrics: dict[str, object],
    exposure_context: dict[str, object],
    db_session: Session,
    thesis_dir: Path | str = "thesis",
    scenario_dir: Path | str = "scenarios",
    playbook_dir: Path | str = "playbooks",
    memo_dir: Path | str = DEFAULT_MEMO_DIR,
) -> IntradayReviewResult:
    repo = Repository(db_session)
    event = _get_or_create_emergency_event(repo, event_input)

    generated = generate_evidence_candidates(db_session, thesis_dir, scenario_dir)
    event_candidates = [
        candidate for candidate in generated.candidates if candidate.event_id == event.event_id
    ]
    evidence_result = append_evidence_candidates(db_session, event_candidates)
    event_evidence = [
        evidence for evidence in repo.list_evidence() if evidence.event_id == event.event_id
    ]

    scenarios = load_scenario_dir(scenario_dir)
    review_metrics = build_review_metrics([event], event_evidence, metrics)
    matched = _matched_scenarios(scenarios, review_metrics)
    _append_scenario_trigger_logs(repo, matched, event_evidence, [event])

    emergency_score = score_emergency_impact(_emergency_input_from_context(event, exposure_context))
    playbooks = load_playbook_dir(playbook_dir)
    playbook_results = execute_playbooks(
        playbooks,
        matched,
        emergency_score.emergency_level,
        confirmations=list(exposure_context.get("confirmations", [])),
    )
    allowed_actions = _unique(
        emergency_score.recommended_risk_actions
        + [
            action
            for result in playbook_results
            if result.activated
            for action in result.allowed_actions
        ]
    )
    forbidden_actions = _unique(
        emergency_score.forbidden_actions
        + [action for result in playbook_results for action in result.forbidden_actions]
    )

    first_match = matched[0] if matched else None
    decision = repo.append_decision(
        DecisionCreate(
            decision_type="emergency_risk_review",
            thesis_id=first_match.thesis_id if first_match else None,
            scenario_id=first_match.scenario_id if first_match else None,
            event_id=event.event_id,
            action=_action_for_emergency_level(emergency_score.emergency_level),
            rationale=(
                f"Emergency review EIS={emergency_score.eis} "
                f"level={emergency_score.emergency_level.value}; "
                f"{len(matched)} scenarios matched."
            ),
            portfolio_impact=", ".join(allowed_actions) or "no_auto_trade / human_review_required",
            review_after="next close review",
            metadata_json={
                "allowed_actions": allowed_actions,
                "forbidden_actions": forbidden_actions,
                "matched_scenarios": [match.scenario_id for match in matched],
                "appended_evidence_count": evidence_result.appended_count,
                "skipped_duplicate_evidence_count": evidence_result.skipped_count,
                "review_metrics": review_metrics,
                "no_auto_trade": True,
            },
        )
    )

    affected_theses = sorted({match.thesis_id for match in matched})
    memo_path = _write_memo(
        Path(memo_dir),
        f"emergency_review_memo_{event.event_id}.md",
        "emergency_review_memo.md.j2",
        {
            "event": event,
            "emergency_score": emergency_score,
            "matched_scenarios": matched,
            "affected_theses": affected_theses,
            "appended_evidence_count": evidence_result.appended_count,
            "skipped_duplicate_evidence_count": evidence_result.skipped_count,
            "allowed_actions": allowed_actions,
            "forbidden_actions": forbidden_actions,
            "decision_id": decision.decision_id,
            "requires_close_review": emergency_score.requires_close_review,
            "disclaimer": NO_AUTO_TRADE_DISCLAIMER,
        },
    )

    return IntradayReviewResult(
        event_id=event.event_id,
        emergency_level=emergency_score.emergency_level,
        emergency_score=emergency_score.eis,
        matched_scenarios=matched,
        allowed_actions=allowed_actions,
        forbidden_actions=forbidden_actions,
        appended_evidence_count=evidence_result.appended_count,
        decision_log_count=1,
        memo_path=memo_path,
        thesis_action="defer_to_close_review",
        evidence_candidate_count=len(event_candidates),
        skipped_duplicate_evidence_count=evidence_result.skipped_count,
        playbook_results=playbook_results,
    )
