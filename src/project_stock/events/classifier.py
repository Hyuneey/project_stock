from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from project_stock.schemas.events import EventCreate
from project_stock.utils.clock import utc_now

EVENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "macro_rate_shock": (
        "rate",
        "fed",
        "fomc",
        "yield",
        "inflation",
        "dollar",
        "us2y",
        "usdkrw",
    ),
    "geopolitical_energy_shock": ("war", "oil", "gas", "middle east", "sanction", "energy"),
    "earnings_shock": ("earnings", "guidance", "revenue", "operating profit", "consensus", "eps"),
    "policy_regulation": ("policy", "regulation", "export control", "subsidy", "tariff"),
    "industry_data": ("inventory", "shipment", "capex", "hbm", "dram", "nand", "semiconductor"),
    "liquidity_credit": ("credit", "spread", "liquidity", "funding", "default"),
    "company_specific": ("samsung", "sk hynix", "buyback", "management", "plant"),
}


def _field(document: Mapping[str, Any] | object, name: str, default: Any = None) -> Any:
    if isinstance(document, Mapping):
        return document.get(name, default)
    return getattr(document, name, default)


def classify_document(document: Mapping[str, Any] | object) -> str:
    text = f"{_field(document, 'title', '')} {_field(document, 'body_text', '')} {_field(document, 'summary', '')}"
    lowered = text.lower()
    scores = {
        event_type: sum(1 for keyword in keywords if keyword in lowered)
        for event_type, keywords in EVENT_KEYWORDS.items()
    }
    best_type, best_score = max(scores.items(), key=lambda item: item[1])
    return best_type if best_score else "unknown"


def event_from_document(document: Mapping[str, Any] | object) -> EventCreate:
    event_time = _field(document, "event_time") or _field(document, "published_at") or utc_now()
    if isinstance(event_time, str):
        event_time = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
    available_from = _field(document, "available_from") or event_time
    if isinstance(available_from, str):
        available_from = datetime.fromisoformat(available_from.replace("Z", "+00:00"))
    summary = _field(document, "summary") or _field(document, "title", "Untitled event")
    return EventCreate(
        event_type=classify_document(document),
        event_time=event_time,
        available_from=available_from,
        summary=summary,
        source_reliability=float(_field(document, "source_reliability", 3.0)),
        surprise_score=float(_field(document, "surprise_score", 3.0)),
        persistence_score=float(_field(document, "persistence_score", 3.0)),
        market_confirmation_score=float(_field(document, "market_confirmation_score", 3.0)),
        metadata_json={"classifier": "rule_based_v1"},
    )
