from __future__ import annotations

from project_stock.schemas.common import EmergencyLevel
from project_stock.schemas.scoring import EmergencyImpactInput, EmergencyImpactResult

BASE_FORBIDDEN_ACTIONS = [
    "headline_only_full_liquidation",
    "unverified_rumor_trade",
    "llm_direct_trade_decision",
]

RISK_ACTIONS_BY_LEVEL = {
    EmergencyLevel.E0: ["record_only"],
    EmergencyLevel.E1: ["watch"],
    EmergencyLevel.E2: ["review_no_new_buy"],
    EmergencyLevel.E3: ["no_new_buy", "review_partial_derisking"],
    EmergencyLevel.E4: ["reduce_risk_budget", "raise_cash_buffer"],
    EmergencyLevel.E5: ["halt_new_trades", "prioritize_defense"],
}


def emergency_level_from_score(eis: float) -> EmergencyLevel:
    if eis <= 100:
        return EmergencyLevel.E0
    if eis <= 300:
        return EmergencyLevel.E1
    if eis <= 700:
        return EmergencyLevel.E2
    if eis <= 1500:
        return EmergencyLevel.E3
    if eis <= 2500:
        return EmergencyLevel.E4
    return EmergencyLevel.E5


def score_emergency_impact(score_input: EmergencyImpactInput) -> EmergencyImpactResult:
    eis = round(
        score_input.source_reliability
        * score_input.relevance
        * score_input.surprise
        * score_input.transmission
        * score_input.market_confirmation
        * score_input.exposure,
        2,
    )
    level = emergency_level_from_score(eis)
    return EmergencyImpactResult(
        eis=eis,
        emergency_level=level,
        recommended_risk_actions=RISK_ACTIONS_BY_LEVEL[level],
        forbidden_actions=BASE_FORBIDDEN_ACTIONS,
        requires_close_review=level in {EmergencyLevel.E3, EmergencyLevel.E4, EmergencyLevel.E5},
    )
