# Backtesting Validation

The validation layer tests whether thesis states, evidence-like signals,
scenario triggers, and portfolio review flags would have been useful in
deterministic fixture histories. It is a diagnostic harness for review logic,
not a trading system.

## Review Simulation Versus Live Trading

Backtest policies can create `BacktestTradeSimulationRecord` rows that describe
hypothetical target exposure changes. They are used only to calculate simulated
returns, turnover, and cost impact. They are not broker orders, live trading
instructions, order-routing payloads, or LLM-directed buy/sell decisions.

## Fixtures

The MVP demo uses:

- `configs/backtest.example.yaml`: policy, cost, benchmark, and mapping config.
- `tests/fixtures/backtest_market_returns.csv`: dated symbol returns and
  benchmark returns.
- `tests/fixtures/backtest_thesis_states.json`: point-in-time thesis state
  signals.
- `tests/fixtures/backtest_portfolio_flags.json`: point-in-time portfolio review
  flags.
- `tests/fixtures/backtest_portfolio_snapshots.json`: starting exposure weights.

All fixture records carry `available_from`. Tests require no network access and
no API keys.

## Point-In-Time Rule

A signal can affect simulated exposure only when:

```text
signal.available_from <= decision_date
```

If a signal has `available_from` after its decision date, strict validation
raises before the backtest. Warning mode records the issue and ignores that
signal until it becomes available.

Market returns are evaluation outcomes. Future returns are used only after the
decision date being evaluated and never to decide an earlier exposure.

## Policies

Supported MVP policies are:

- `buy_and_hold_benchmark`: benchmark-only comparison.
- `static_portfolio`: keep the starting exposure snapshot.
- `thesis_state_risk_overlay`: reduce simulated thesis exposure when the latest
  available thesis state is `deteriorating`, `suspended`, or `invalidated`.
- `portfolio_review_flag_overlay`: reduce simulated exposure when latest
  available review flags include `over_exposed_review`, `reduce_risk_review`,
  `crowding_review`, or `concentration_warning`.

`active` and `core_overweight` states maintain exposure by default. Simulated
overweighting is disabled unless explicitly enabled in config, and even then it
remains an offline simulation.

## Cost Assumptions

The engine applies transaction costs and slippage in basis points:

```text
cost = turnover * (transaction_cost_bps + slippage_bps) / 10000
```

Turnover is one-way turnover, computed as half the absolute sum of exposure
changes. `max_turnover_per_period` caps simulated rebalancing.

## Performance Metrics

The report includes:

- cumulative return
- annualized return
- volatility
- max drawdown
- Calmar ratio
- review-flag hit ratio
- average turnover
- transaction cost impact
- benchmark cumulative return
- benchmark relative return
- downside capture when benchmark-down periods exist

These metrics are deterministic calculations over fixture returns.

## Diagnostic Metrics

The validation layer also computes non-trading usefulness diagnostics:

- `deterioration_precision`: deteriorating, suspended, or invalidated thesis
  states followed by negative forward returns.
- `active_followthrough`: active or core-overweight states followed by positive
  relative returns.
- `scenario_trigger_followthrough`: triggered scenarios followed by their
  expected fixture direction.
- `evidence_stance_alignment`: supports or contradicts evidence followed by
  matching later returns.
- `portfolio_flag_usefulness`: risk flags followed by negative forward returns
  or drawdown-like fixture behavior.

These metrics are diagnostics only. They are not proof of profitability.

## Report

Run:

```bash
project-stock run-backtest-demo --memo-dir data/processed
```

The command writes `backtest_validation_report_<backtest_id>.md` with metrics,
cost assumptions, turnover, point-in-time warnings, limitations, and the
no-auto-trade disclaimer.

## Limitations

The MVP uses a small deterministic fixture. It does not fetch prices, run live
market data, estimate capacity, optimize portfolios, or place trades. Broader
validation should add larger point-in-time datasets before any operational use.
