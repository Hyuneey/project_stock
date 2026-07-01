from __future__ import annotations

from collections import Counter
from datetime import date
import json
from pathlib import Path

from sqlalchemy.orm import Session

from project_stock.operations.real_data_smoke import (
    DEFAULT_REAL_DATA_SMOKE_CONFIG,
    NO_AUTO_TRADE_DISCLAIMER,
    load_real_data_smoke_config,
    run_real_data_smoke,
)
from project_stock.playbooks.executor import execute_playbooks
from project_stock.playbooks.loader import load_playbook_dir
from project_stock.reports.render import render_report
from project_stock.scenarios.loader import load_scenario_dir
from project_stock.scenarios.matcher import match_scenarios
from project_stock.scoring.big_flow import score_big_flow
from project_stock.schemas.common import EmergencyLevel, SchemaBase
from project_stock.schemas.decisions import DecisionCreate
from project_stock.schemas.scoring import BigFlowScoreInput, BigFlowScoreResult
from project_stock.storage.repository import Repository
from project_stock.thesis.lifecycle import evaluate_thesis_states

KOR_SEMI_THESIS_ID = "KOR_SEMI_MEMORY_UPCYCLE"
DEFAULT_BIG_FLOW_FIXTURE = Path("tests/fixtures/big_flow_kor_semi_v2.json")


class KorSemiThesisPackResult(SchemaBase):
    thesis_id: str = KOR_SEMI_THESIS_ID
    as_of: date
    smoke_memo_path: str | None = None
    normalized_event_count: int = 0
    evidence_count: int = 0
    evidence_counts_by_stance: dict[str, int]
    scenario_match_count: int = 0
    matched_scenarios: list[str]
    activated_playbooks: list[str]
    allowed_actions: list[str]
    forbidden_actions: list[str]
    big_flow_score: float | None = None
    thesis_state: str | None = None
    thesis_snapshot_count: int = 0
    memo_path: str
    no_auto_trade: bool = True


def _fixture_metrics() -> dict[str, object]:
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
        "VIX_LEVEL": 22.0,
        "KRX_SEMI_ETF_CHANGE_5D_PCT": -4.5,
        "SOX_CHANGE_5D_PCT": -3.5,
        "SEMI_RELATIVE_STRENGTH_20D": -1.0,
        "AI_CAPEX_SLOWDOWN_HEADLINE": True,
        "SERVER_MEMORY_ORDER_CUT_FLAG": False,
        "AI_INFRA_REVISION_1M_PCT": -2.0,
    }


def _load_big_flow_result(fixture: Path | None) -> BigFlowScoreResult | None:
    if fixture is None:
        return None
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    score_input = BigFlowScoreInput.model_validate(payload)
    return score_big_flow(score_input)


def _evidence_counts(session: Session) -> tuple[dict[str, int], list[object], list[object]]:
    evidence_rows = [
        evidence
        for evidence in Repository(session).list_evidence()
        if evidence.thesis_id == KOR_SEMI_THESIS_ID
    ]
    counts = Counter(evidence.supports_or_contradicts for evidence in evidence_rows)
    supporting = sorted(
        [evidence for evidence in evidence_rows if evidence.supports_or_contradicts == "supports"],
        key=lambda item: (item.strength_score, item.created_at),
        reverse=True,
    )[:5]
    contradicting = sorted(
        [evidence for evidence in evidence_rows if evidence.supports_or_contradicts == "contradicts"],
        key=lambda item: (item.strength_score, item.created_at),
        reverse=True,
    )[:5]
    return dict(counts), supporting, contradicting


def _write_memo(
    *,
    memo_dir: Path,
    result: KorSemiThesisPackResult,
    top_supporting: list[object],
    top_contradicting: list[object],
    big_flow_result: BigFlowScoreResult | None,
    source_coverage: dict[str, list[str]],
) -> str:
    memo_dir.mkdir(parents=True, exist_ok=True)
    memo_path = memo_dir / f"kor_semi_thesis_pack_memo_{result.as_of.isoformat()}.md"
    memo = render_report(
        "kor_semi_thesis_pack_memo.md.j2",
        {
            "result": result,
            "top_supporting": top_supporting,
            "top_contradicting": top_contradicting,
            "big_flow": big_flow_result,
            "source_coverage": source_coverage,
            "disclaimer": NO_AUTO_TRADE_DISCLAIMER,
        },
    )
    memo_path.write_text(memo, encoding="utf-8")
    return str(memo_path)


def run_kor_semi_thesis_pack_demo(
    session: Session,
    *,
    config_path: Path | str = DEFAULT_REAL_DATA_SMOKE_CONFIG,
    thesis_dir: Path | str = "thesis",
    scenario_dir: Path | str = "scenarios/KOR_SEMI_MEMORY_UPCYCLE",
    playbook_dir: Path | str = "playbooks",
    memo_dir: Path | str = "data/processed",
    big_flow_fixture: Path | None = DEFAULT_BIG_FLOW_FIXTURE,
) -> KorSemiThesisPackResult:
    config = load_real_data_smoke_config(config_path)
    smoke_result = run_real_data_smoke(
        config_path,
        mode="fixture",
        session=session,
        thesis_dir=thesis_dir,
        scenario_dir=scenario_dir,
    )

    scenarios = [
        scenario
        for scenario in load_scenario_dir(scenario_dir)
        if scenario.thesis_id == KOR_SEMI_THESIS_ID and scenario.version == "2.0"
    ]
    scenario_matches = match_scenarios(scenarios, _fixture_metrics())
    matched = [match for match in scenario_matches if match.matched]
    repo = Repository(session)
    for match in matched:
        repo.append_scenario_trigger(
            scenario_id=match.scenario_id,
            thesis_id=match.thesis_id,
            event_id=None,
            match_score=match.match_score,
            result_state="matched",
            metadata_json={
                "source": "run_kor_semi_thesis_pack_demo",
                "no_auto_trade": True,
            },
        )

    playbooks = [
        playbook
        for playbook in load_playbook_dir(playbook_dir)
        if playbook.version == "2.0" and playbook.playbook_id.startswith("PB_KOR_SEMI_")
    ]
    playbook_results = execute_playbooks(
        playbooks,
        matched,
        EmergencyLevel.E3,
        confirmations=[
            "rates_move_confirmed",
            "fx_stress_confirmed",
            "revision_deterioration_confirmed",
            "market_breakdown_confirmed",
            "ai_capex_slowdown_confirmed",
        ],
    )
    activated = [result for result in playbook_results if result.activated]
    allowed_actions = sorted({action for result in activated for action in result.allowed_actions})
    forbidden_actions = sorted({action for result in playbook_results for action in result.forbidden_actions})

    big_flow_result = _load_big_flow_result(big_flow_fixture)
    thesis_result = evaluate_thesis_states(
        session=session,
        as_of=config.end_date,
        thesis_dir=thesis_dir,
        big_flow_scores={
            KOR_SEMI_THESIS_ID: big_flow_result.score,
        }
        if big_flow_result is not None
        else None,
        memo_dir=memo_dir,
    )
    latest = repo.latest_thesis_snapshot(KOR_SEMI_THESIS_ID)
    evidence_counts, top_supporting, top_contradicting = _evidence_counts(session)

    preliminary = KorSemiThesisPackResult(
        as_of=config.end_date,
        smoke_memo_path=smoke_result.memo_path,
        normalized_event_count=smoke_result.normalized_event_count,
        evidence_count=sum(evidence_counts.values()),
        evidence_counts_by_stance=evidence_counts,
        scenario_match_count=len(matched),
        matched_scenarios=[match.scenario_id for match in matched],
        activated_playbooks=[result.playbook_id for result in activated],
        allowed_actions=allowed_actions,
        forbidden_actions=forbidden_actions,
        big_flow_score=big_flow_result.score if big_flow_result else None,
        thesis_state=latest.status if latest else None,
        thesis_snapshot_count=thesis_result.snapshot_count,
        memo_path=str(Path(memo_dir) / f"kor_semi_thesis_pack_memo_{config.end_date.isoformat()}.md"),
    )
    source_coverage = {
        "FRED": config.fred_series,
        "ECOS": config.ecos_indicators,
        "OpenDART": [company.stock_code for company in config.opendart_companies],
        "KRX": config.krx_symbols,
    }
    memo_path = _write_memo(
        memo_dir=Path(memo_dir),
        result=preliminary,
        top_supporting=top_supporting,
        top_contradicting=top_contradicting,
        big_flow_result=big_flow_result,
        source_coverage=source_coverage,
    )
    repo.append_decision(
        DecisionCreate(
            decision_type="kor_semi_thesis_pack_review",
            thesis_id=KOR_SEMI_THESIS_ID,
            action="review_only",
            rationale=(
                f"{len(matched)} KOR_SEMI scenarios matched; "
                f"{len(activated)} review-only playbooks activated."
            ),
            portfolio_impact="human_review_required",
            metadata_json={
                "as_of": config.end_date.isoformat(),
                "matched_scenarios": [match.scenario_id for match in matched],
                "activated_playbooks": [result.playbook_id for result in activated],
                "allowed_actions": allowed_actions,
                "forbidden_actions": forbidden_actions,
                "big_flow_score": big_flow_result.score if big_flow_result else None,
                "evidence_counts_by_stance": evidence_counts,
                "memo_path": memo_path,
                "no_auto_trade": True,
            },
        )
    )
    return preliminary.model_copy(update={"memo_path": memo_path})
