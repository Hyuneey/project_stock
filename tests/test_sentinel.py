from __future__ import annotations

import json

from sqlalchemy import select

from project_stock.db.models import DecisionLog, EvidenceLedger
from project_stock.sentinel.intraday import run_intraday_emergency_check


def test_emergency_rate_shock_matches_scenario_and_writes_logs(db_session, repo_root):
    payload = json.loads((repo_root / "tests/fixtures/emergency_rate_shock.json").read_text())
    result = run_intraday_emergency_check(
        event_input=payload["event_input"],
        metrics=payload["metrics"],
        exposure_context=payload["exposure_context"],
        db_session=db_session,
        scenario_dir=repo_root / "scenarios",
        playbook_dir=repo_root / "playbooks",
    )
    db_session.commit()

    assert result.emergency_score.emergency_level.value == "E3"
    assert any(match.scenario_id == "KOR_SEMI_RATE_SHOCK_BEAR" for match in result.matched_scenarios)
    assert any(playbook.activated for playbook in result.playbook_results)
    assert "no_new_buy" in result.allowed_actions
    assert "llm_direct_trade_decision" in result.forbidden_actions
    assert result.thesis_action == "defer_to_close_review"
    assert result.evidence_ids
    assert result.decision_ids
    assert db_session.scalars(select(EvidenceLedger)).first() is not None
    assert db_session.scalars(select(DecisionLog)).first() is not None
