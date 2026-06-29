from __future__ import annotations

from project_stock.scoring.big_flow import score_big_flow
from project_stock.scoring.emergency import emergency_level_from_score, score_emergency_impact
from project_stock.scoring.thesis_impact import score_thesis_impact
from project_stock.schemas.common import EmergencyLevel
from project_stock.schemas.scoring import BigFlowScoreInput, EmergencyImpactInput, ThesisImpactInput


def test_big_flow_score_formula():
    result = score_big_flow(
        BigFlowScoreInput(
            thesis_id="KOR_SEMI_MEMORY_UPCYCLE",
            secular=80,
            industry=75,
            earnings=65,
            valuation=55,
            market=70,
            macro=60,
            risk_penalty=15,
        )
    )

    assert result.score == 53.75
    assert result.state_hint == "watch_or_hold"


def test_emergency_score_boundaries():
    assert emergency_level_from_score(100) == EmergencyLevel.E0
    assert emergency_level_from_score(101) == EmergencyLevel.E1
    assert emergency_level_from_score(701) == EmergencyLevel.E3
    result = score_emergency_impact(
        EmergencyImpactInput(
            source_reliability=4,
            relevance=4.5,
            surprise=4.5,
            transmission=4,
            market_confirmation=4,
            exposure=4,
        )
    )
    assert result.emergency_level == EmergencyLevel.E5
    e3_result = score_emergency_impact(
        EmergencyImpactInput(
            source_reliability=4,
            relevance=4,
            surprise=3.4,
            transmission=3,
            market_confirmation=3,
            exposure=3,
        )
    )
    assert e3_result.emergency_level == EmergencyLevel.E3
    assert "llm_direct_trade_decision" in result.forbidden_actions


def test_thesis_impact_boundaries():
    result = score_thesis_impact(
        ThesisImpactInput(
            relevance=4,
            surprise=4,
            transmission=4,
            persistence=4,
            market_confirmation=4,
            priced_in_penalty=0,
        )
    )

    assert result.impact_level == "red"
