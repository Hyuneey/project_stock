from __future__ import annotations

from project_stock.schemas.scoring import BigFlowScoreInput, BigFlowScoreResult

WEIGHTS = {
    "secular": 0.20,
    "industry": 0.20,
    "earnings": 0.20,
    "valuation": 0.15,
    "market": 0.15,
    "macro": 0.10,
}


def _state_hint(score: float) -> str:
    if score >= 80:
        return "core_overweight_candidate"
    if score >= 65:
        return "active_overweight_candidate"
    if score >= 50:
        return "watch_or_hold"
    if score >= 35:
        return "deteriorating"
    return "invalidation_candidate"


def score_big_flow(score_input: BigFlowScoreInput) -> BigFlowScoreResult:
    components = {
        name: float(getattr(score_input, name)) * weight for name, weight in WEIGHTS.items()
    }
    score = round(sum(components.values()) - score_input.risk_penalty, 2)
    state_hint = _state_hint(score)
    return BigFlowScoreResult(
        thesis_id=score_input.thesis_id,
        score=score,
        state_hint=state_hint,
        components=components,
        risk_penalty=score_input.risk_penalty,
        rationale=(
            f"Weighted macro-thematic score is {score}; "
            f"risk penalty is {score_input.risk_penalty}."
        ),
    )
