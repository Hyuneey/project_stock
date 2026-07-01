from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from project_stock.cli import app
from project_stock.db.migrations import init_db
from project_stock.db.session import make_session_factory
from project_stock.evidence.generation import classify_evidence_stance
from project_stock.operations.kor_semi_thesis_pack import KOR_SEMI_THESIS_ID
from project_stock.playbooks.executor import execute_playbook
from project_stock.playbooks.loader import load_playbook_file, load_playbook_dir
from project_stock.scenarios.loader import load_scenario_dir
from project_stock.scenarios.matcher import match_scenario
from project_stock.scoring.big_flow import score_big_flow
from project_stock.schemas.common import EmergencyLevel
from project_stock.schemas.scoring import BigFlowScoreInput
from project_stock.storage.repository import Repository
from project_stock.thesis.loader import load_thesis_dir, load_thesis_file

runner = CliRunner()


def _scenario_metrics() -> dict[str, object]:
    return {
        "THESIS_ID": KOR_SEMI_THESIS_ID,
        "MEMORY_PRICE_CHANGE_1M_PCT": 4.5,
        "OPERATING_INCOME_CHANGE_YOY_PCT": -50.0,
        "EPS_REVISION_1M_PCT": -4.0,
        "MARGIN_PRESSURE_FLAG": True,
        "GUIDANCE_DETERIORATION_FLAG": True,
        "US10Y_CHANGE_5D_BP": 25.0,
        "USDKRW_CHANGE_5D_PCT": 1.8,
        "VIX_CHANGE_5D_PCT": 18.0,
        "KRX_SEMI_ETF_CHANGE_5D_PCT": -4.5,
        "SOX_CHANGE_5D_PCT": -3.5,
        "SEMI_RELATIVE_STRENGTH_20D": -1.0,
        "AI_CAPEX_SLOWDOWN_HEADLINE": True,
    }


def test_kor_semi_v2_thesis_yaml_validation(repo_root: Path):
    thesis = load_thesis_file(repo_root / "thesis/KOR_SEMI_MEMORY_UPCYCLE_v2.0.yaml")
    loaded = {item.thesis_id: item for item in load_thesis_dir(repo_root / "thesis")}

    assert thesis.thesis_id == KOR_SEMI_THESIS_ID
    assert thesis.version == "2.0"
    assert thesis.no_auto_trade is True
    assert "DGS10" in thesis.source_mappings["FRED"]
    assert loaded[KOR_SEMI_THESIS_ID].version == "2.0"


def test_kor_semi_v2_scenarios_validate_and_trigger(repo_root: Path):
    scenarios = [
        scenario
        for scenario in load_scenario_dir(repo_root / "scenarios/KOR_SEMI_MEMORY_UPCYCLE")
        if scenario.version == "2.0"
    ]

    assert len(scenarios) == 6
    assert {scenario.scenario_type for scenario in scenarios} == {"bull", "base", "bear", "shock"}
    matches = [match_scenario(scenario, _scenario_metrics()) for scenario in scenarios]
    matched_ids = {match.scenario_id for match in matches if match.matched}
    assert "KOR_SEMI_SHOCK_RATE_FX_STRESS_V2" in matched_ids
    assert "KOR_SEMI_BEAR_REVISION_DETERIORATION_V2" in matched_ids
    assert "KOR_SEMI_SHOCK_SEMICONDUCTOR_PRICE_BREAKDOWN_V2" in matched_ids


def test_kor_semi_v2_playbooks_validate_and_execute(repo_root: Path):
    playbook = load_playbook_file(repo_root / "playbooks/kor_semi_rate_fx_stress_v2.0.yaml")
    scenario = next(
        scenario
        for scenario in load_scenario_dir(repo_root / "scenarios/KOR_SEMI_MEMORY_UPCYCLE")
        if scenario.scenario_id == "KOR_SEMI_SHOCK_RATE_FX_STRESS_V2"
    )
    match = match_scenario(scenario, _scenario_metrics())

    result = execute_playbook(
        playbook,
        [match],
        EmergencyLevel.E3,
        confirmations=["rates_move_confirmed", "fx_stress_confirmed"],
    )

    assert result.activated is True
    assert "reduce_risk_review" in result.allowed_actions
    assert {"broker_order", "auto_trade", "live_buy_sell_order", "llm_direct_trade_decision"}.issubset(
        set(result.forbidden_actions)
    )


def test_kor_semi_playbook_bank_has_required_review_only_actions(repo_root: Path):
    playbooks = [
        playbook
        for playbook in load_playbook_dir(repo_root / "playbooks")
        if playbook.version == "2.0" and playbook.playbook_id.startswith("PB_KOR_SEMI_")
    ]

    assert len(playbooks) >= 4
    for playbook in playbooks:
        assert "do_not_auto_trade" in playbook.allowed_actions
        assert "broker_order" in playbook.forbidden_actions
        assert playbook.no_auto_trade is True


def test_kor_semi_evidence_mapping_supports_and_contradicts():
    supportive = SimpleNamespace(
        event_type="revenue_growth_candidate",
        metadata_json={"pct_change": 25.0},
    )
    margin = SimpleNamespace(
        event_type="margin_pressure_candidate",
        metadata_json={"pct_change": -150.0},
    )
    negative_market = SimpleNamespace(
        event_type="market_large_move",
        metadata_json={"pct_move": -4.5},
    )

    assert classify_evidence_stance(supportive, KOR_SEMI_THESIS_ID) == "supports"
    assert classify_evidence_stance(margin, KOR_SEMI_THESIS_ID) == "contradicts"
    assert classify_evidence_stance(negative_market, KOR_SEMI_THESIS_ID) == "contradicts"


def test_big_flow_kor_semi_v2_fixture(repo_root: Path):
    payload = json.loads((repo_root / "tests/fixtures/big_flow_kor_semi_v2.json").read_text())
    score_input = BigFlowScoreInput.model_validate(payload)
    result = score_big_flow(score_input)

    assert score_input.secular == payload["secular_tailwind"]
    assert result.thesis_id == KOR_SEMI_THESIS_ID
    assert 0 <= result.score <= 100


def test_run_kor_semi_thesis_pack_demo_cli(tmp_path: Path, repo_root: Path, db_url: str, monkeypatch):
    monkeypatch.delenv("PROJECT_STOCK_ALLOW_NETWORK", raising=False)
    memo_dir = tmp_path / "memos"

    result = runner.invoke(
        app,
        [
            "run-kor-semi-thesis-pack-demo",
            "--db-url",
            db_url,
            "--memo-dir",
            str(memo_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.replace("\n", ""))
    assert payload["scenario_match_count"] >= 1
    assert payload["matched_scenarios"]
    assert payload["allowed_actions"]
    assert payload["big_flow_score"] is not None
    assert Path(payload["memo_path"]).exists()
    memo = Path(payload["memo_path"]).read_text(encoding="utf-8")
    assert "No auto-trade" in memo
    assert "KOR_SEMI" in memo

    init_db(db_url)
    factory = make_session_factory(db_url)
    with factory() as session:
        evidence = [row for row in Repository(session).list_evidence() if row.thesis_id == KOR_SEMI_THESIS_ID]
        snapshots = Repository(session).list_thesis_snapshots(KOR_SEMI_THESIS_ID)

    assert any(row.supports_or_contradicts == "supports" for row in evidence)
    assert any(row.supports_or_contradicts == "contradicts" for row in evidence)
    assert snapshots


def test_no_broker_order_or_live_trading_implementation_for_kor_semi(repo_root: Path):
    forbidden = {
        "place_order(",
        "submit_order(",
        "broker_execute(",
        "live_buy(",
        "live_sell(",
        "auto_trade=True",
        "llm_direct_trade_decision(",
    }
    python_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (repo_root / "src" / "project_stock").rglob("*.py")
    )

    assert [item for item in forbidden if item in python_text] == []
