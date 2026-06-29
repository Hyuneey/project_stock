from __future__ import annotations

from collections import defaultdict
from datetime import date
import json
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from project_stock.reports.render import render_report
from project_stock.schemas.common import ThesisStatus
from project_stock.schemas.decisions import DecisionCreate
from project_stock.schemas.portfolio import (
    PortfolioConfig,
    PortfolioExposure,
    PortfolioHolding,
    PortfolioReviewResult,
    PortfolioRiskFlag,
    PortfolioSnapshot,
)
from project_stock.storage.repository import Repository
from project_stock.thesis.lifecycle import run_thesis_review_demo

DEFAULT_MEMO_DIR = Path("data/processed")
DEFAULT_PORTFOLIO_CONFIG = Path("configs/portfolio.example.yaml")
DEFAULT_PORTFOLIO_FIXTURE = Path("tests/fixtures/portfolio_holdings_core_satellite.json")
NO_AUTO_TRADE_DISCLAIMER = (
    "No auto-trade: portfolio review flags are human review prompts only and do "
    "not authorize broker orders, order routing, or LLM-directed buy/sell decisions."
)


def load_portfolio_config(path: Path | str) -> PortfolioConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return PortfolioConfig.model_validate(payload)


def load_portfolio_snapshot(path: Path | str, config: PortfolioConfig, as_of: date) -> PortfolioSnapshot:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "holdings" in payload:
        snapshot_payload = {
            "portfolio_id": payload.get("portfolio_id", config.portfolio_id),
            "as_of": payload.get("as_of", as_of.isoformat()),
            "base_currency": payload.get("base_currency", config.base_currency),
            "holdings": payload["holdings"],
        }
    else:
        snapshot_payload = {
            "portfolio_id": config.portfolio_id,
            "as_of": as_of.isoformat(),
            "base_currency": config.base_currency,
            "holdings": payload,
        }
    return PortfolioSnapshot.model_validate(snapshot_payload)


def _ratio(value: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return round(value / total, 6)


def _is_cash(holding: PortfolioHolding) -> bool:
    return holding.asset_type.lower() in {"cash", "cash_like", "money_market"}


def calculate_portfolio_exposure(snapshot: PortfolioSnapshot) -> PortfolioExposure:
    total = round(sum(holding.market_value for holding in snapshot.holdings), 2)
    cash_value = round(sum(holding.market_value for holding in snapshot.holdings if _is_cash(holding)), 2)
    equity_value = round(
        sum(holding.market_value for holding in snapshot.holdings if holding.asset_type.lower() == "equity"),
        2,
    )
    theme_values: dict[str, float] = defaultdict(float)
    thesis_values: dict[str, float] = defaultdict(float)
    sector_values: dict[str, float] = defaultdict(float)
    asset_values: dict[str, float] = defaultdict(float)
    foreign_values: dict[str, float] = defaultdict(float)
    high_beta_value = 0.0

    for holding in snapshot.holdings:
        asset_values[holding.symbol] += holding.market_value
        for theme_id in holding.theme_ids:
            theme_values[theme_id] += holding.market_value
        for thesis_id in holding.thesis_ids:
            thesis_values[thesis_id] += holding.market_value
        if holding.sector:
            sector_values[holding.sector] += holding.market_value
        if holding.currency != snapshot.base_currency:
            foreign_values[holding.currency] += holding.market_value
        if holding.beta is not None and holding.beta >= 1.2:
            high_beta_value += holding.market_value

    return PortfolioExposure(
        total_market_value=total,
        cash_value=cash_value,
        cash_ratio=_ratio(cash_value, total),
        total_equity_exposure=_ratio(equity_value, total),
        theme_exposure={key: _ratio(value, total) for key, value in sorted(theme_values.items())},
        thesis_exposure={key: _ratio(value, total) for key, value in sorted(thesis_values.items())},
        sector_exposure={key: _ratio(value, total) for key, value in sorted(sector_values.items())},
        single_asset_exposure={key: _ratio(value, total) for key, value in sorted(asset_values.items())},
        high_beta_exposure=round(high_beta_value, 2),
        high_beta_ratio=_ratio(high_beta_value, total),
        foreign_currency_exposure={
            key: _ratio(value, total) for key, value in sorted(foreign_values.items())
        },
    )


def _latest_thesis_states(
    session: Session,
    thesis_ids: set[str],
) -> dict[str, str | None]:
    repo = Repository(session)
    states: dict[str, str | None] = {}
    for thesis_id in sorted(thesis_ids):
        snapshot = repo.latest_thesis_snapshot(thesis_id)
        states[thesis_id] = snapshot.status if snapshot is not None else None
    return states


def _flag(
    flag_type: str,
    message: str,
    review_action: str,
    severity: str = "review",
    thesis_id: str | None = None,
    theme_id: str | None = None,
    symbol: str | None = None,
    exposure: float | None = None,
    threshold: float | None = None,
) -> PortfolioRiskFlag:
    return PortfolioRiskFlag(
        flag_type=flag_type,
        severity=severity,
        message=message,
        review_action=review_action,
        thesis_id=thesis_id,
        theme_id=theme_id,
        symbol=symbol,
        exposure=exposure,
        threshold=threshold,
    )


def evaluate_portfolio_flags(
    exposure: PortfolioExposure,
    config: PortfolioConfig,
    latest_thesis_states: dict[str, str | None],
) -> list[PortfolioRiskFlag]:
    flags: list[PortfolioRiskFlag] = []
    if exposure.total_equity_exposure > config.max_total_equity_exposure:
        flags.append(
            _flag(
                "total_equity_exposure_review",
                "Total equity exposure exceeds configured maximum.",
                "review_total_equity_exposure",
                exposure=exposure.total_equity_exposure,
                threshold=config.max_total_equity_exposure,
            )
        )
    if exposure.cash_ratio < config.cash_buffer_min:
        flags.append(
            _flag(
                "cash_buffer_review",
                "Cash ratio is below configured minimum.",
                "review_cash_buffer",
                exposure=exposure.cash_ratio,
                threshold=config.cash_buffer_min,
            )
        )

    high_beta_threshold = config.risk_budget.get("high_beta_exposure_threshold")
    if high_beta_threshold is not None and exposure.high_beta_ratio > high_beta_threshold:
        flags.append(
            _flag(
                "high_beta_exposure_review",
                "High beta exposure exceeds configured threshold.",
                "review_high_beta_exposure",
                exposure=exposure.high_beta_ratio,
                threshold=high_beta_threshold,
            )
        )

    for theme_id, actual in exposure.theme_exposure.items():
        threshold = config.max_theme_exposure.get(theme_id)
        if threshold is not None and actual > threshold:
            flags.append(
                _flag(
                    "over_exposed_review",
                    f"Theme exposure exceeds configured maximum for {theme_id}.",
                    "review_theme_exposure",
                    theme_id=theme_id,
                    exposure=actual,
                    threshold=threshold,
                )
            )

    for symbol, actual in exposure.single_asset_exposure.items():
        if actual > config.max_single_asset_exposure:
            flags.append(
                _flag(
                    "concentration_warning",
                    f"Single asset concentration exceeds threshold for {symbol}.",
                    "review_position_concentration",
                    symbol=symbol,
                    exposure=actual,
                    threshold=config.max_single_asset_exposure,
                )
            )

    minimal_threshold = config.risk_budget.get("minimal_thesis_exposure_threshold", 0.02)
    for thesis_id, actual in exposure.thesis_exposure.items():
        state = latest_thesis_states.get(thesis_id)
        band = config.thesis_exposure_map.get(thesis_id)
        if state is None:
            flags.append(
                _flag(
                    "missing_thesis_state_warning",
                    f"No latest thesis state snapshot exists for {thesis_id}.",
                    "review_missing_thesis_state",
                    thesis_id=thesis_id,
                    exposure=actual,
                )
            )
            continue
        if state in {ThesisStatus.active.value, ThesisStatus.core_overweight.value}:
            review_min = band.review_min if band else 0.0
            if actual < review_min:
                flags.append(
                    _flag(
                        "under_exposed_review",
                        f"Thesis is {state} but exposure is below review band.",
                        "review_under_exposure",
                        thesis_id=thesis_id,
                        exposure=actual,
                        threshold=review_min,
                    )
                )
        if state in {
            ThesisStatus.deteriorating.value,
            ThesisStatus.suspended.value,
            ThesisStatus.invalidated.value,
        } and actual > minimal_threshold:
            flags.append(
                _flag(
                    "reduce_risk_review",
                    f"Thesis is {state} while exposure remains above minimal threshold.",
                    "review_risk_reduction",
                    thesis_id=thesis_id,
                    exposure=actual,
                    threshold=minimal_threshold,
                )
            )
        if state == ThesisStatus.crowded.value:
            review_max = band.review_max if band and band.review_max is not None else None
            if review_max is not None and actual > review_max:
                flags.append(
                    _flag(
                        "crowding_review",
                        "Thesis is crowded and exposure is above review band.",
                        "review_crowding_exposure",
                        thesis_id=thesis_id,
                        exposure=actual,
                        threshold=review_max,
                    )
                )
    return flags


def _all_thesis_ids(snapshot: PortfolioSnapshot, config: PortfolioConfig) -> set[str]:
    ids = set(config.thesis_exposure_map)
    for holding in snapshot.holdings:
        ids.update(holding.thesis_ids)
    return ids


def _append_decision(
    session: Session,
    result: PortfolioReviewResult,
) -> str:
    repo = Repository(session)
    decision = repo.append_decision(
        DecisionCreate(
            decision_type="portfolio_review",
            thesis_id=None,
            action="review_only",
            rationale=(
                f"Portfolio {result.portfolio_id} reviewed with "
                f"{len(result.risk_flags)} risk flags."
            ),
            portfolio_impact="human_review_required",
            review_after="next portfolio review",
            metadata_json={
                "portfolio_id": result.portfolio_id,
                "as_of": result.as_of.isoformat(),
                "exposure": result.exposure.model_dump(mode="json"),
                "risk_flags": [flag.model_dump(mode="json") for flag in result.risk_flags],
                "latest_thesis_states": result.latest_thesis_states,
                "no_auto_trade": True,
            },
        )
    )
    return decision.decision_id


def render_portfolio_review_memo(
    memo_dir: Path,
    result: PortfolioReviewResult,
    config: PortfolioConfig,
) -> str:
    memo_dir.mkdir(parents=True, exist_ok=True)
    memo_path = memo_dir / f"portfolio_review_memo_{result.portfolio_id}_{result.as_of.isoformat()}.md"
    memo = render_report(
        "portfolio_review_memo.md.j2",
        {
            "result": result,
            "config": config,
            "disclaimer": NO_AUTO_TRADE_DISCLAIMER,
        },
    )
    memo_path.write_text(memo, encoding="utf-8")
    return str(memo_path)


def review_portfolio_snapshot(
    session: Session,
    snapshot: PortfolioSnapshot,
    config: PortfolioConfig,
    memo_dir: Path | str = DEFAULT_MEMO_DIR,
    append_decision: bool = True,
) -> PortfolioReviewResult:
    exposure = calculate_portfolio_exposure(snapshot)
    thesis_states = _latest_thesis_states(session, _all_thesis_ids(snapshot, config))
    flags = evaluate_portfolio_flags(exposure, config, thesis_states)
    result = PortfolioReviewResult(
        portfolio_id=snapshot.portfolio_id,
        as_of=snapshot.as_of,
        exposure=exposure,
        latest_thesis_states=thesis_states,
        risk_flags=flags,
    )
    decision_id = _append_decision(session, result) if append_decision else None
    result = result.model_copy(update={"decision_id": decision_id})
    memo_path = render_portfolio_review_memo(Path(memo_dir), result, config)
    return result.model_copy(update={"memo_path": memo_path})


def review_portfolio(
    session: Session,
    portfolio_fixture: Path | str,
    portfolio_config: Path | str,
    as_of: date,
    memo_dir: Path | str = DEFAULT_MEMO_DIR,
) -> PortfolioReviewResult:
    config = load_portfolio_config(portfolio_config)
    snapshot = load_portfolio_snapshot(portfolio_fixture, config, as_of)
    return review_portfolio_snapshot(session, snapshot, config, memo_dir=memo_dir)


def run_portfolio_review_demo(
    session: Session,
    as_of: date,
    portfolio_fixture: Path | str = DEFAULT_PORTFOLIO_FIXTURE,
    portfolio_config: Path | str = DEFAULT_PORTFOLIO_CONFIG,
    memo_dir: Path | str = DEFAULT_MEMO_DIR,
    thesis_dir: Path | str = "thesis",
    scenario_dir: Path | str = "scenarios",
) -> PortfolioReviewResult:
    run_thesis_review_demo(
        session=session,
        as_of=as_of,
        thesis_dir=thesis_dir,
        scenario_dir=scenario_dir,
        memo_dir=memo_dir,
    )
    return review_portfolio(
        session=session,
        portfolio_fixture=portfolio_fixture,
        portfolio_config=portfolio_config,
        as_of=as_of,
        memo_dir=memo_dir,
    )
