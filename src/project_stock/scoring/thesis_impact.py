from __future__ import annotations

from project_stock.schemas.scoring import ThesisImpactInput, ThesisImpactResult


def _impact_level(tis: float) -> str:
    if tis >= 85:
        return "red"
    if tis >= 70:
        return "orange"
    if tis >= 50:
        return "yellow"
    if tis >= 30:
        return "watch"
    return "noise"


def score_thesis_impact(score_input: ThesisImpactInput) -> ThesisImpactResult:
    raw = (
        score_input.relevance
        * score_input.surprise
        * score_input.transmission
        * score_input.persistence
        * score_input.market_confirmation
    )
    tis = round(raw - score_input.priced_in_penalty, 2)
    level = _impact_level(tis)
    return ThesisImpactResult(
        tis=tis,
        impact_level=level,
        rationale=f"Thesis impact score is {tis} after priced-in penalty.",
    )
