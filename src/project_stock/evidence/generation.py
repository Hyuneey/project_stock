from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

from sqlalchemy.orm import Session

from project_stock.db.models import Event, EvidenceLedger
from project_stock.ingest.official_bundle import ingest_official_mock_bundle
from project_stock.ingest.sources import register_official_sources
from project_stock.events.normalization import normalize_events
from project_stock.scenarios.loader import load_scenario_dir
from project_stock.schemas.evidence import (
    EvidenceCandidate,
    EvidenceCreate,
    EvidenceGenerationResult,
    EvidenceStance,
    ThesisRelevanceResult,
)
from project_stock.schemas.scenarios import ScenarioDefinition
from project_stock.schemas.thesis import ThesisDefinition
from project_stock.storage.repository import Repository
from project_stock.thesis.loader import load_thesis_dir
from project_stock.utils.clock import utc_now
from project_stock.utils.ids import make_id

ENTITY_THESIS_HINTS: dict[str, set[str]] = {
    "KOR_SEMI_MEMORY_UPCYCLE": {
        "KOR_SEMI_MEMORY_UPCYCLE",
        "SEMICONDUCTOR",
        "005930",
        "000660",
        "SOX",
        "USDKRW",
        "US10Y",
        "RATES",
    },
    "AI_INFRASTRUCTURE": {
        "AI_INFRASTRUCTURE",
        "SEMICONDUCTOR",
        "005930",
        "000660",
        "SOX",
        "US10Y",
        "RATES",
    },
}

SUPPORTIVE_EVENT_TYPES = {
    "earnings_guidance",
    "macro_surprise_positive",
    "sector_news_headline",
}

CONTRADICTING_EVENT_TYPES = {
    "earnings_revision_candidate",
    "risk_disclosure_candidate",
    "macro_policy_headline",
    "macro_surprise_negative",
    "rate_policy_relevant",
    "fx_stress_move",
    "rates_shock_move",
    "volatility_shock_move",
}

SEVERITY_BY_EVENT_TYPE: dict[str, float] = {
    "disclosure_received": 1.0,
    "earnings_guidance": 3.0,
    "earnings_revision_candidate": 4.0,
    "risk_disclosure_candidate": 4.0,
    "macro_policy_headline": 3.0,
    "geopolitical_risk_headline": 4.0,
    "sector_news_headline": 2.5,
    "company_news_headline": 2.5,
    "macro_indicator_release": 2.0,
    "macro_surprise_positive": 3.5,
    "macro_surprise_negative": 3.5,
    "inflation_surprise": 4.0,
    "growth_surprise": 3.0,
    "rate_policy_relevant": 3.5,
    "market_large_move": 3.0,
    "fx_stress_move": 4.0,
    "rates_shock_move": 4.0,
    "sector_relative_strength_move": 3.5,
    "volatility_shock_move": 4.0,
}

SCENARIO_EVENT_HINTS: dict[str, set[str]] = {
    "KOR_SEMI_RATE_SHOCK_BEAR": {
        "macro_policy_headline",
        "rate_policy_relevant",
        "fx_stress_move",
        "rates_shock_move",
        "sector_relative_strength_move",
        "volatility_shock_move",
    },
    "KOR_SEMI_EARNINGS_BEAR": {
        "earnings_revision_candidate",
        "risk_disclosure_candidate",
        "macro_surprise_negative",
    },
    "KOR_SEMI_AI_DEMAND_BULL": {
        "earnings_guidance",
        "sector_news_headline",
        "macro_surprise_positive",
        "market_large_move",
    },
    "KOR_SEMI_GRINDING_BASE": {
        "disclosure_received",
        "macro_indicator_release",
    },
}


def _tokens(text: str) -> set[str]:
    return {token for token in re.split(r"[^a-zA-Z0-9_]+", text.lower()) if len(token) >= 3}


def _entity_ids(event: Event) -> list[str]:
    return [entity.entity_id for entity in event.entities]


def _event_text(event: Event) -> str:
    metadata = event.metadata_json or {}
    return " ".join(
        [
            event.event_type,
            event.summary,
            str(metadata.get("indicator_id", "")),
            str(metadata.get("symbol", "")),
            str(metadata.get("source_id", "")),
        ]
    )


def _thesis_keywords(thesis: ThesisDefinition) -> set[str]:
    beneficiaries = " ".join(
        item
        for values in thesis.beneficiaries.values()
        for item in values
    )
    assumptions = " ".join(assumption.statement for assumption in thesis.core_assumptions)
    invalidations = " ".join(thesis.invalidation_conditions)
    return _tokens(f"{thesis.thesis_id} {thesis.title} {thesis.core_claim} {beneficiaries} {assumptions} {invalidations}")


def match_thesis_relevance(
    event: Event,
    theses: list[ThesisDefinition],
    scenarios: list[ScenarioDefinition] | None = None,
) -> list[ThesisRelevanceResult]:
    scenarios = scenarios or []
    event_entities = set(_entity_ids(event))
    event_tokens = _tokens(_event_text(event))
    event_text = _event_text(event).lower()
    results: list[ThesisRelevanceResult] = []
    for thesis in theses:
        score = 0.0
        reasons: list[str] = []
        matched_keywords_set: set[str] = set()
        matched_entities = sorted(event_entities.intersection(ENTITY_THESIS_HINTS.get(thesis.thesis_id, set())))
        if matched_entities:
            score += min(60.0, 20.0 * len(matched_entities))
            reasons.append("entity_overlap")
        matched_keywords_set.update(event_tokens.intersection(_thesis_keywords(thesis)))
        matched_keywords = sorted(matched_keywords_set)
        if matched_keywords:
            score += min(25.0, 5.0 * len(matched_keywords))
            reasons.append("keyword_overlap")
        if any(entity in event_entities for entity in {"RATES", "US10Y"}) and "rate" in _thesis_keywords(thesis):
            score += 15.0
            reasons.append("macro_factor_overlap")
        if any(entity in event_entities for entity in {"005930", "000660", "SOX"}):
            if thesis.thesis_id in {"KOR_SEMI_MEMORY_UPCYCLE", "AI_INFRASTRUCTURE"}:
                score += 10.0
                reasons.append("company_asset_overlap")
        scenario_keywords: set[str] = set()
        trigger_metrics: set[str] = set()
        for scenario in scenarios:
            if scenario.thesis_id != thesis.thesis_id:
                continue
            scenario_tokens = _tokens(
                f"{scenario.scenario_id} {scenario.description} {' '.join(scenario.risk_action)}"
            )
            scenario_keywords.update(event_tokens.intersection(scenario_tokens))
            if event.event_type in SCENARIO_EVENT_HINTS.get(scenario.scenario_id, set()):
                scenario_keywords.add(scenario.scenario_id.lower())
            for condition in scenario.trigger.all_conditions:
                metric = condition.metric.lower()
                metric_tokens = _tokens(metric)
                if metric in event_text or event_tokens.intersection(metric_tokens):
                    trigger_metrics.add(metric)
        if scenario_keywords:
            score += min(10.0, 3.0 * len(scenario_keywords))
            reasons.append("scenario_keyword_overlap")
            matched_keywords_set.update(scenario_keywords)
        if trigger_metrics:
            score += min(10.0, 5.0 * len(trigger_metrics))
            reasons.append("trigger_metric_overlap")
            matched_keywords_set.update(trigger_metrics)
        score = min(100.0, score)
        if score > 0:
            results.append(
                ThesisRelevanceResult(
                    event_id=event.event_id,
                    thesis_id=thesis.thesis_id,
                    relevance_score=score,
                    relevance_reasons=reasons,
                    matched_entity_ids=matched_entities,
                    matched_keywords=sorted(matched_keywords_set),
                )
            )
    return sorted(results, key=lambda result: result.relevance_score, reverse=True)


def classify_evidence_stance(event: Event, thesis_id: str) -> EvidenceStance:
    metadata = event.metadata_json or {}
    pct_move = metadata.get("pct_move")
    if event.event_type in SUPPORTIVE_EVENT_TYPES:
        return "supports"
    if event.event_type in CONTRADICTING_EVENT_TYPES:
        return "contradicts"
    if event.event_type in {"market_large_move", "sector_relative_strength_move"}:
        if isinstance(pct_move, (int, float)):
            return "supports" if pct_move > 0 else "contradicts"
    if event.event_type == "inflation_surprise":
        return "contradicts" if thesis_id == "AI_INFRASTRUCTURE" else "neutral"
    if event.event_type == "growth_surprise":
        return "supports"
    return "neutral"


def score_evidence_strength(event: Event, relevance_score: float) -> float:
    severity = SEVERITY_BY_EVENT_TYPE.get(event.event_type, 2.0)
    relevance_0_5 = relevance_score / 20.0
    score = (
        0.20 * event.source_reliability
        + 0.20 * event.surprise_score
        + 0.15 * event.persistence_score
        + 0.15 * event.market_confirmation_score
        + 0.20 * relevance_0_5
        + 0.10 * severity
    )
    return round(max(0.0, min(5.0, score)), 2)


def _confidence_score(event: Event, relevance_score: float) -> float:
    raw = (
        relevance_score * 0.55
        + event.source_reliability * 10.0 * 0.20
        + event.market_confirmation_score * 10.0 * 0.15
        + event.persistence_score * 10.0 * 0.10
    )
    return round(max(0.0, min(100.0, raw)), 2)


def _scenario_link(
    event: Event,
    thesis_id: str,
    scenarios: list[ScenarioDefinition],
) -> str | None:
    metadata_text = _event_text(event).lower()
    for scenario in scenarios:
        if scenario.thesis_id != thesis_id:
            continue
        hints = SCENARIO_EVENT_HINTS.get(scenario.scenario_id, set())
        trigger_metrics = {condition.metric.lower() for condition in scenario.trigger.all_conditions}
        scenario_words = _tokens(f"{scenario.scenario_id} {scenario.description} {' '.join(scenario.risk_action)}")
        if event.event_type in hints:
            return scenario.scenario_id
        if trigger_metrics and any(metric.lower() in metadata_text for metric in trigger_metrics):
            return scenario.scenario_id
        if scenario_words.intersection(_tokens(metadata_text)):
            return scenario.scenario_id
    return None


def generate_evidence_candidates(
    session: Session,
    thesis_dir: Path | str = "thesis",
    scenario_dir: Path | str = "scenarios",
) -> EvidenceGenerationResult:
    theses = load_thesis_dir(thesis_dir)
    scenarios = load_scenario_dir(scenario_dir)
    repo = Repository(session)
    candidates: list[EvidenceCandidate] = []
    for event in repo.list_events_with_entities():
        relevance_results = match_thesis_relevance(event, theses, scenarios)
        for relevance in relevance_results:
            stance = classify_evidence_stance(event, relevance.thesis_id)
            scenario_id = _scenario_link(event, relevance.thesis_id, scenarios)
            source_entity_ids = _entity_ids(event)
            source_entity_mappings = [
                {
                    "entity_type": entity.entity_type,
                    "entity_id": entity.entity_id,
                    "relevance_score": entity.relevance_score,
                }
                for entity in event.entities
            ]
            strength_score = score_evidence_strength(event, relevance.relevance_score)
            candidate = EvidenceCandidate(
                candidate_id=make_id("EVC", event.event_time),
                event_id=event.event_id,
                thesis_id=relevance.thesis_id,
                scenario_id=scenario_id,
                evidence_type=f"event:{event.event_type}",
                claim=f"{event.summary} [{event.event_type}]",
                supports_or_contradicts=stance,
                strength_score=strength_score,
                relevance_score=relevance.relevance_score,
                confidence_score=_confidence_score(event, relevance.relevance_score),
                source_event_type=event.event_type,
                source_entity_ids=source_entity_ids,
                created_at=utc_now(),
                metadata_json={
                    "relevance_reasons": relevance.relevance_reasons,
                    "matched_entity_ids": relevance.matched_entity_ids,
                    "matched_keywords": relevance.matched_keywords,
                    "source_entity_mappings": source_entity_mappings,
                    "source_event_metadata": event.metadata_json or {},
                },
            )
            candidates.append(candidate)
    return _summarize_candidates(candidates, [], 0)


def _evidence_exists(session: Session, candidate: EvidenceCandidate) -> bool:
    for evidence in Repository(session).list_evidence():
        if (
            evidence.event_id == candidate.event_id
            and evidence.thesis_id == candidate.thesis_id
            and evidence.scenario_id == candidate.scenario_id
            and evidence.evidence_type == candidate.evidence_type
        ):
            return True
    return False


def append_evidence_candidates(
    session: Session,
    candidates: list[EvidenceCandidate],
) -> EvidenceGenerationResult:
    repo = Repository(session)
    appended: list[EvidenceLedger] = []
    skipped_count = 0
    for candidate in candidates:
        if _evidence_exists(session, candidate):
            skipped_count += 1
            continue
        evidence = repo.append_evidence(
            EvidenceCreate(
                event_id=candidate.event_id,
                thesis_id=candidate.thesis_id,
                scenario_id=candidate.scenario_id,
                evidence_type=candidate.evidence_type,
                claim=candidate.claim,
                supports_or_contradicts=candidate.supports_or_contradicts,
                strength_score=candidate.strength_score,
                source_ids_json=candidate.source_entity_ids,
                metadata_json={
                    "candidate_id": candidate.candidate_id,
                    "relevance_score": candidate.relevance_score,
                    "confidence_score": candidate.confidence_score,
                    "source_event_type": candidate.source_event_type,
                    **(candidate.metadata_json or {}),
                },
            )
        )
        appended.append(evidence)
    return _summarize_candidates(candidates, appended, skipped_count)


def generate_and_append_evidence(
    session: Session,
    thesis_dir: Path | str = "thesis",
    scenario_dir: Path | str = "scenarios",
) -> EvidenceGenerationResult:
    generated = generate_evidence_candidates(session, thesis_dir, scenario_dir)
    return append_evidence_candidates(session, generated.candidates)


def run_evidence_demo(
    session: Session,
    fixture_dir: Path,
    thesis_dir: Path | str = "thesis",
    scenario_dir: Path | str = "scenarios",
) -> EvidenceGenerationResult:
    register_official_sources(session)
    ingest_official_mock_bundle(session, fixture_dir)
    normalize_events(session)
    return generate_and_append_evidence(session, thesis_dir, scenario_dir)


def _summarize_candidates(
    candidates: list[EvidenceCandidate],
    appended: list[EvidenceLedger],
    skipped_count: int,
) -> EvidenceGenerationResult:
    thesis_counts = Counter(candidate.thesis_id for candidate in candidates)
    stance_counts = Counter(candidate.supports_or_contradicts for candidate in candidates)
    return EvidenceGenerationResult(
        candidate_count=len(candidates),
        appended_count=len(appended),
        skipped_count=skipped_count,
        candidates=candidates,
        evidence_ids=[evidence.evidence_id for evidence in appended],
        counts_by_thesis_id=dict(thesis_counts),
        counts_by_stance=dict(stance_counts),
    )
