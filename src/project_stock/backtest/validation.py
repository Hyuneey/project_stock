from __future__ import annotations

from collections import defaultdict
import csv
from datetime import date
import json
import math
from pathlib import Path
from statistics import pstdev

import yaml

from project_stock.reports.render import render_report
from project_stock.schemas.backtest import (
    BacktestConfig,
    BacktestMarketReturn,
    BacktestPerformanceMetrics,
    BacktestPeriod,
    BacktestPortfolioSnapshot,
    BacktestReportResult,
    BacktestSignalSnapshot,
    BacktestTradeSimulationRecord,
    BacktestValidationResult,
)

DEFAULT_BACKTEST_CONFIG = Path("configs/backtest.example.yaml")
DEFAULT_MARKET_RETURNS = Path("tests/fixtures/backtest_market_returns.csv")
DEFAULT_THESIS_STATES = Path("tests/fixtures/backtest_thesis_states.json")
DEFAULT_PORTFOLIO_FLAGS = Path("tests/fixtures/backtest_portfolio_flags.json")
DEFAULT_PORTFOLIO_SNAPSHOTS = Path("tests/fixtures/backtest_portfolio_snapshots.json")
DEFAULT_MEMO_DIR = Path("data/processed")
NO_AUTO_TRADE_DISCLAIMER = (
    "No auto-trade: this backtest is an offline review simulation only. It does "
    "not create live orders, broker instructions, or LLM-directed buy/sell decisions."
)
RISK_NEGATIVE_STATES = {"deteriorating", "suspended", "invalidated"}
POSITIVE_STATES = {"active", "core_overweight"}


def load_backtest_config(path: Path | str) -> BacktestConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return BacktestConfig.model_validate(payload)


def load_market_returns(path: Path | str) -> list[BacktestMarketReturn]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [BacktestMarketReturn.model_validate(row) for row in reader]


def load_signal_snapshots(path: Path | str) -> list[BacktestSignalSnapshot]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [BacktestSignalSnapshot.model_validate(row) for row in payload]


def load_portfolio_snapshots(path: Path | str) -> list[BacktestPortfolioSnapshot]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [BacktestPortfolioSnapshot.model_validate(row) for row in payload]


def validate_point_in_time_signals(
    signals: list[BacktestSignalSnapshot],
    strict: bool = True,
) -> list[str]:
    warnings: list[str] = []
    for signal in signals:
        if signal.available_from > signal.signal_date:
            warnings.append(
                f"{signal.signal_id} is available from {signal.available_from.isoformat()} "
                f"after decision date {signal.signal_date.isoformat()} and cannot be used early."
            )
    if strict and warnings:
        raise ValueError("; ".join(warnings))
    return warnings


def _dates_in_period(
    config: BacktestConfig,
    market_returns: list[BacktestMarketReturn],
) -> list[date]:
    dates = {
        record.date
        for record in market_returns
        if config.start_date <= record.date <= config.end_date
        and record.available_from <= record.date
    }
    return sorted(dates)


def _returns_by_date(
    market_returns: list[BacktestMarketReturn],
) -> dict[date, dict[str, float]]:
    grouped: dict[date, dict[str, float]] = defaultdict(dict)
    for record in market_returns:
        if record.available_from <= record.date:
            grouped[record.date][record.symbol] = record.return_value
    return grouped


def _benchmark_by_date(
    config: BacktestConfig,
    market_returns: list[BacktestMarketReturn],
) -> dict[date, float]:
    benchmark: dict[date, float] = {}
    for record in market_returns:
        if record.available_from > record.date:
            continue
        if record.benchmark_return is not None:
            benchmark.setdefault(record.date, record.benchmark_return)
        if record.symbol == config.benchmark_symbol:
            benchmark[record.date] = record.return_value
    return benchmark


def _initial_exposures(
    config: BacktestConfig,
    snapshots: list[BacktestPortfolioSnapshot],
) -> dict[str, float]:
    eligible = [
        snapshot
        for snapshot in snapshots
        if snapshot.date <= config.start_date and snapshot.available_from <= config.start_date
    ]
    if not eligible:
        raise ValueError("no point-in-time portfolio snapshot is available at start_date")
    return dict(sorted(eligible[-1].exposures.items()))


def _latest_signals_by_key(
    signals: list[BacktestSignalSnapshot],
    decision_date: date,
    signal_type: str,
) -> dict[str, BacktestSignalSnapshot]:
    latest: dict[str, BacktestSignalSnapshot] = {}
    for signal in signals:
        if signal.signal_type != signal_type:
            continue
        if signal.signal_date > decision_date or signal.available_from > decision_date:
            continue
        key = signal.thesis_id or signal.symbol or signal.scenario_id or signal.signal_id
        current = latest.get(key)
        if current is None or (signal.signal_date, signal.signal_id) > (
            current.signal_date,
            current.signal_id,
        ):
            latest[key] = signal
    return latest


def _normalize_exposures(exposures: dict[str, float], cash_symbol: str) -> dict[str, float]:
    sanitized = {symbol: max(0.0, round(value, 8)) for symbol, value in exposures.items()}
    non_cash_total = sum(value for symbol, value in sanitized.items() if symbol != cash_symbol)
    sanitized[cash_symbol] = max(0.0, round(1.0 - non_cash_total, 8))
    total = sum(sanitized.values())
    if total <= 0:
        return {cash_symbol: 1.0}
    return {symbol: round(value / total, 8) for symbol, value in sorted(sanitized.items())}


def _symbols_for_thesis(config: BacktestConfig, thesis_id: str | None) -> list[str]:
    if thesis_id is None:
        return []
    return config.policy.thesis_symbol_map.get(thesis_id, [])


def _target_for_thesis_state_policy(
    config: BacktestConfig,
    baseline: dict[str, float],
    previous: dict[str, float],
    decision_date: date,
    signals: list[BacktestSignalSnapshot],
) -> tuple[dict[str, float], list[str]]:
    target = dict(previous)
    reasons: list[str] = []
    latest_states = _latest_signals_by_key(signals, decision_date, "thesis_state")
    if not latest_states:
        return target, reasons

    for thesis_id, signal in sorted(latest_states.items()):
        symbols = _symbols_for_thesis(config, thesis_id)
        if not symbols:
            continue
        if signal.state in RISK_NEGATIVE_STATES:
            for symbol in symbols:
                target[symbol] = baseline.get(symbol, previous.get(symbol, 0.0)) * (
                    1.0 - config.policy.risk_reduction_fraction
                )
            reasons.append(f"{thesis_id}:{signal.state}")
        elif (
            signal.state in POSITIVE_STATES
            and config.policy.allow_simulated_overweight
            and config.policy.simulated_overweight_fraction > 0
        ):
            for symbol in symbols:
                target[symbol] = baseline.get(symbol, previous.get(symbol, 0.0)) * (
                    1.0 + config.policy.simulated_overweight_fraction
                )
            reasons.append(f"{thesis_id}:simulated_overweight")
    return target, reasons


def _target_for_portfolio_flag_policy(
    config: BacktestConfig,
    baseline: dict[str, float],
    previous: dict[str, float],
    decision_date: date,
    signals: list[BacktestSignalSnapshot],
) -> tuple[dict[str, float], list[str]]:
    target = dict(previous)
    reasons: list[str] = []
    latest_flags = _latest_signals_by_key(signals, decision_date, "portfolio_flag")
    for key, signal in sorted(latest_flags.items()):
        if signal.flag_type not in config.policy.review_flag_types:
            continue
        symbols = [signal.symbol] if signal.symbol else _symbols_for_thesis(config, signal.thesis_id)
        if not symbols:
            continue
        for symbol in symbols:
            target[symbol] = baseline.get(symbol, previous.get(symbol, 0.0)) * (
                1.0 - config.policy.portfolio_flag_reduction_fraction
            )
        reasons.append(f"{key}:{signal.flag_type}")
    return target, reasons


def _policy_target(
    config: BacktestConfig,
    baseline: dict[str, float],
    previous: dict[str, float],
    decision_date: date,
    signals: list[BacktestSignalSnapshot],
) -> tuple[dict[str, float], list[str]]:
    if config.policy_name == "buy_and_hold_benchmark":
        return {config.benchmark_symbol: 1.0}, ["benchmark_only"]
    if config.policy_name == "static_portfolio":
        return dict(previous), []
    if config.policy_name == "thesis_state_risk_overlay":
        target, reasons = _target_for_thesis_state_policy(
            config,
            baseline,
            previous,
            decision_date,
            signals,
        )
        return _normalize_exposures(target, config.policy.cash_symbol), reasons
    if config.policy_name == "portfolio_review_flag_overlay":
        target, reasons = _target_for_portfolio_flag_policy(
            config,
            baseline,
            previous,
            decision_date,
            signals,
        )
        return _normalize_exposures(target, config.policy.cash_symbol), reasons
    raise ValueError(f"unsupported backtest policy: {config.policy_name}")


def _apply_turnover_cap_and_cost(
    config: BacktestConfig,
    previous: dict[str, float],
    target: dict[str, float],
) -> tuple[dict[str, float], float, float]:
    symbols = sorted(set(previous) | set(target))
    deltas = {symbol: target.get(symbol, 0.0) - previous.get(symbol, 0.0) for symbol in symbols}
    raw_turnover = 0.5 * sum(abs(delta) for delta in deltas.values())
    if raw_turnover > config.max_turnover_per_period and raw_turnover > 0:
        scale = config.max_turnover_per_period / raw_turnover
        target = {
            symbol: previous.get(symbol, 0.0) + (target.get(symbol, 0.0) - previous.get(symbol, 0.0)) * scale
            for symbol in symbols
        }
        target = _normalize_exposures(target, config.policy.cash_symbol)
        deltas = {symbol: target.get(symbol, 0.0) - previous.get(symbol, 0.0) for symbol in symbols}
        raw_turnover = 0.5 * sum(abs(delta) for delta in deltas.values())
    cost_rate = (config.transaction_cost_bps + config.slippage_bps) / 10_000.0
    return target, round(raw_turnover, 8), round(raw_turnover * cost_rate, 8)


def _trade_records(
    decision_date: date,
    previous: dict[str, float],
    target: dict[str, float],
    turnover: float,
    transaction_cost: float,
    reasons: list[str],
) -> list[BacktestTradeSimulationRecord]:
    records: list[BacktestTradeSimulationRecord] = []
    symbols = sorted(set(previous) | set(target))
    policy_reason = ", ".join(reasons) if reasons else "maintain_previous_exposure"
    for symbol in symbols:
        change = round(target.get(symbol, 0.0) - previous.get(symbol, 0.0), 8)
        if abs(change) < 0.00000001:
            continue
        records.append(
            BacktestTradeSimulationRecord(
                date=decision_date,
                symbol=symbol,
                previous_exposure=round(previous.get(symbol, 0.0), 8),
                target_exposure=round(target.get(symbol, 0.0), 8),
                exposure_change=change,
                turnover=turnover,
                transaction_cost=transaction_cost,
                policy_reason=policy_reason,
            )
        )
    return records


def _portfolio_return(
    exposures: dict[str, float],
    returns: dict[str, float],
    transaction_cost: float,
) -> float:
    gross = sum(weight * returns.get(symbol, 0.0) for symbol, weight in exposures.items())
    return round(gross - transaction_cost, 8)


def _compound(returns: list[float]) -> float:
    value = 1.0
    for period_return in returns:
        value *= 1.0 + period_return
    return round(value - 1.0, 8)


def _periods_per_year(frequency: str) -> int:
    return {
        "daily": 252,
        "weekly": 52,
        "monthly": 12,
        "quarterly": 4,
        "annual": 1,
    }.get(frequency, 12)


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for period_return in returns:
        equity *= 1.0 + period_return
        peak = max(peak, equity)
        drawdown = equity / peak - 1.0
        worst = min(worst, drawdown)
    return round(worst, 8)


def _performance_metrics(
    config: BacktestConfig,
    portfolio_returns: list[float],
    benchmark_returns: list[float],
    turnovers: list[float],
    transaction_costs: list[float],
    review_flag_hit_ratio: float,
) -> BacktestPerformanceMetrics:
    periods = len(portfolio_returns)
    cumulative = _compound(portfolio_returns)
    benchmark_cumulative = _compound(benchmark_returns)
    periods_per_year = _periods_per_year(config.rebalance_frequency)
    annualized = round((1.0 + cumulative) ** (periods_per_year / periods) - 1.0, 8) if periods else 0.0
    volatility = (
        round(pstdev(portfolio_returns) * math.sqrt(periods_per_year), 8)
        if len(portfolio_returns) > 1
        else 0.0
    )
    max_drawdown = _max_drawdown(portfolio_returns)
    calmar = round(annualized / abs(max_drawdown), 8) if max_drawdown < 0 else None
    negative_pairs = [
        (portfolio_return, benchmark_return)
        for portfolio_return, benchmark_return in zip(portfolio_returns, benchmark_returns, strict=False)
        if benchmark_return < 0
    ]
    downside_capture = None
    if negative_pairs:
        portfolio_down = sum(pair[0] for pair in negative_pairs)
        benchmark_down = sum(pair[1] for pair in negative_pairs)
        if benchmark_down != 0:
            downside_capture = round(portfolio_down / benchmark_down, 8)
    return BacktestPerformanceMetrics(
        cumulative_return=cumulative,
        annualized_return=annualized,
        volatility=volatility,
        max_drawdown=max_drawdown,
        calmar_ratio=calmar,
        hit_ratio_review_flags=review_flag_hit_ratio,
        average_turnover=round(sum(turnovers) / len(turnovers), 8) if turnovers else 0.0,
        transaction_cost_impact=round(sum(transaction_costs), 8),
        benchmark_cumulative_return=benchmark_cumulative,
        benchmark_relative_return=round(cumulative - benchmark_cumulative, 8),
        downside_capture=downside_capture,
    )


def _next_market_date(signal_date: date, dates: list[date]) -> date | None:
    for market_date in dates:
        if market_date > signal_date:
            return market_date
    return None


def _thesis_forward_return(
    config: BacktestConfig,
    thesis_id: str | None,
    market_date: date,
    returns_by_date: dict[date, dict[str, float]],
) -> float | None:
    symbols = _symbols_for_thesis(config, thesis_id)
    values = [returns_by_date[market_date].get(symbol) for symbol in symbols]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _validation_ratio(hits: int, count: int) -> float:
    return round(hits / count, 8) if count else 0.0


def compute_validation_metrics(
    config: BacktestConfig,
    signals: list[BacktestSignalSnapshot],
    market_returns: list[BacktestMarketReturn],
) -> tuple[dict[str, float], dict[str, int]]:
    dates = _dates_in_period(config, market_returns)
    returns_by_date = _returns_by_date(market_returns)
    benchmark_by_date = _benchmark_by_date(config, market_returns)
    counts = {
        "deterioration_signals": 0,
        "active_signals": 0,
        "scenario_trigger_signals": 0,
        "evidence_stance_signals": 0,
        "portfolio_review_flags": 0,
    }
    hits = {
        "deterioration_precision": 0,
        "active_followthrough": 0,
        "scenario_trigger_followthrough": 0,
        "evidence_stance_alignment": 0,
        "portfolio_flag_usefulness": 0,
    }
    for signal in signals:
        if signal.available_from > signal.signal_date:
            continue
        next_date = _next_market_date(signal.signal_date, dates)
        if next_date is None:
            continue
        forward_return = _thesis_forward_return(config, signal.thesis_id, next_date, returns_by_date)
        if forward_return is None and signal.symbol:
            forward_return = returns_by_date[next_date].get(signal.symbol)
        if forward_return is None:
            continue
        benchmark_return = benchmark_by_date.get(next_date, 0.0)

        if signal.signal_type == "thesis_state" and signal.state in RISK_NEGATIVE_STATES:
            counts["deterioration_signals"] += 1
            if forward_return < 0:
                hits["deterioration_precision"] += 1
        if signal.signal_type == "thesis_state" and signal.state in POSITIVE_STATES:
            counts["active_signals"] += 1
            if forward_return - benchmark_return > 0:
                hits["active_followthrough"] += 1
        if signal.signal_type == "scenario_trigger":
            counts["scenario_trigger_signals"] += 1
            if (
                signal.expected_direction == "negative"
                and forward_return < 0
                or signal.expected_direction == "positive"
                and forward_return > 0
            ):
                hits["scenario_trigger_followthrough"] += 1
        if signal.signal_type == "evidence_stance":
            counts["evidence_stance_signals"] += 1
            if (
                signal.stance == "contradicts"
                and forward_return < 0
                or signal.stance == "supports"
                and forward_return > 0
            ):
                hits["evidence_stance_alignment"] += 1
        if signal.signal_type == "portfolio_flag" and signal.flag_type in config.policy.review_flag_types:
            counts["portfolio_review_flags"] += 1
            if forward_return < 0:
                hits["portfolio_flag_usefulness"] += 1
    return (
        {
            "deterioration_precision": _validation_ratio(
                hits["deterioration_precision"],
                counts["deterioration_signals"],
            ),
            "active_followthrough": _validation_ratio(
                hits["active_followthrough"],
                counts["active_signals"],
            ),
            "scenario_trigger_followthrough": _validation_ratio(
                hits["scenario_trigger_followthrough"],
                counts["scenario_trigger_signals"],
            ),
            "evidence_stance_alignment": _validation_ratio(
                hits["evidence_stance_alignment"],
                counts["evidence_stance_signals"],
            ),
            "portfolio_flag_usefulness": _validation_ratio(
                hits["portfolio_flag_usefulness"],
                counts["portfolio_review_flags"],
            ),
        },
        counts,
    )


def run_backtest(
    config: BacktestConfig,
    market_returns: list[BacktestMarketReturn],
    portfolio_snapshots: list[BacktestPortfolioSnapshot],
    signals: list[BacktestSignalSnapshot],
    strict_point_in_time: bool = True,
) -> BacktestValidationResult:
    warnings = validate_point_in_time_signals(signals, strict=strict_point_in_time)
    dates = _dates_in_period(config, market_returns)
    returns_by_date = _returns_by_date(market_returns)
    benchmark_by_date = _benchmark_by_date(config, market_returns)
    baseline = _initial_exposures(config, portfolio_snapshots)
    previous = (
        {config.benchmark_symbol: 1.0}
        if config.policy_name == "buy_and_hold_benchmark"
        else _normalize_exposures(baseline, config.policy.cash_symbol)
    )
    portfolio_returns: list[float] = []
    benchmark_returns: list[float] = []
    turnovers: list[float] = []
    transaction_costs: list[float] = []
    trade_records: list[BacktestTradeSimulationRecord] = []
    period_returns: dict[str, float] = {}
    benchmark_period_returns: dict[str, float] = {}

    for decision_date in dates:
        target, reasons = _policy_target(config, baseline, previous, decision_date, signals)
        target = _normalize_exposures(target, config.policy.cash_symbol)
        target, turnover, transaction_cost = _apply_turnover_cap_and_cost(config, previous, target)
        trade_records.extend(
            _trade_records(decision_date, previous, target, turnover, transaction_cost, reasons)
        )
        period_return = _portfolio_return(target, returns_by_date[decision_date], transaction_cost)
        benchmark_return = benchmark_by_date.get(decision_date, 0.0)
        portfolio_returns.append(period_return)
        benchmark_returns.append(benchmark_return)
        turnovers.append(turnover)
        transaction_costs.append(transaction_cost)
        period_returns[decision_date.isoformat()] = period_return
        benchmark_period_returns[decision_date.isoformat()] = benchmark_return
        previous = target

    validation_metrics, validation_counts = compute_validation_metrics(
        config,
        signals,
        market_returns,
    )
    metrics = _performance_metrics(
        config,
        portfolio_returns,
        benchmark_returns,
        turnovers,
        transaction_costs,
        validation_metrics["portfolio_flag_usefulness"],
    )
    return BacktestValidationResult(
        backtest_id=config.backtest_id,
        period=BacktestPeriod(start_date=config.start_date, end_date=config.end_date),
        policy_name=config.policy_name,
        benchmark_symbol=config.benchmark_symbol,
        metrics=metrics,
        validation_metrics=validation_metrics,
        validation_counts=validation_counts,
        trade_records=trade_records,
        period_returns=period_returns,
        benchmark_returns=benchmark_period_returns,
        point_in_time_warnings=warnings,
    )


def _with_policy(config: BacktestConfig, policy_name: str) -> BacktestConfig:
    return config.model_copy(update={"policy_name": policy_name, "policy": config.policy.model_copy(update={"policy_name": policy_name})})


def render_backtest_report(
    result: BacktestValidationResult,
    memo_dir: Path | str = DEFAULT_MEMO_DIR,
) -> BacktestReportResult:
    memo_dir = Path(memo_dir)
    memo_dir.mkdir(parents=True, exist_ok=True)
    report_path = memo_dir / f"backtest_validation_report_{result.backtest_id}.md"
    report = render_report(
        "backtest_validation_report.md.j2",
        {
            "result": result,
            "disclaimer": NO_AUTO_TRADE_DISCLAIMER,
        },
    )
    report_path.write_text(report, encoding="utf-8")
    return BacktestReportResult(
        backtest_id=result.backtest_id,
        policy_name=result.policy_name,
        report_path=str(report_path),
        metrics=result.metrics,
        benchmark_metrics=result.benchmark_metrics,
        validation_metrics=result.validation_metrics,
        point_in_time_warnings=result.point_in_time_warnings,
    )


def run_backtest_demo(
    config_path: Path | str = DEFAULT_BACKTEST_CONFIG,
    market_returns_path: Path | str = DEFAULT_MARKET_RETURNS,
    thesis_states_path: Path | str = DEFAULT_THESIS_STATES,
    portfolio_flags_path: Path | str = DEFAULT_PORTFOLIO_FLAGS,
    portfolio_snapshots_path: Path | str = DEFAULT_PORTFOLIO_SNAPSHOTS,
    memo_dir: Path | str = DEFAULT_MEMO_DIR,
) -> tuple[BacktestValidationResult, BacktestReportResult]:
    config = load_backtest_config(config_path)
    market_returns = load_market_returns(market_returns_path)
    signals = load_signal_snapshots(thesis_states_path) + load_signal_snapshots(portfolio_flags_path)
    portfolio_snapshots = load_portfolio_snapshots(portfolio_snapshots_path)
    overlay_result = run_backtest(config, market_returns, portfolio_snapshots, signals)
    benchmark_config = _with_policy(config, "buy_and_hold_benchmark")
    benchmark_result = run_backtest(benchmark_config, market_returns, portfolio_snapshots, signals)
    overlay_result = overlay_result.model_copy(
        update={"benchmark_metrics": benchmark_result.metrics}
    )
    report_result = render_backtest_report(overlay_result, memo_dir=memo_dir)
    return overlay_result, report_result
