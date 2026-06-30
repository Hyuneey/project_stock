# Portfolio Review

The portfolio review layer maps thesis states and fixture holdings into
portfolio exposure review outputs. It does not fetch prices, execute broker
orders, route orders, auto-trade, or generate LLM-directed investment decisions.

## Portfolio Fixture Format

Portfolio fixtures are JSON files with:

- `portfolio_id`
- `as_of`
- `base_currency`
- `holdings`

Each holding includes:

- `symbol`
- `name`
- optional `quantity`
- `market_value`
- `currency`
- `asset_type`
- `theme_ids`
- `thesis_ids`
- `sector`
- optional `beta`
- optional `liquidity_bucket`

The MVP uses fixture `market_value` inputs directly. No external market data is
required.

## Exposure Calculations

The calculator derives:

- total market value
- cash value and cash ratio
- total equity exposure
- theme exposure
- thesis exposure
- sector exposure
- single asset exposure
- high beta exposure when beta is provided and `beta >= 1.2`
- foreign currency exposure when holding currency differs from base currency

All exposure ratios use total portfolio market value as denominator.

## Thesis-State-Aware Review Logic

Portfolio review reads the latest `ThesisStateSnapshot` by thesis ID:

- `active` or `core_overweight` with exposure below configured `review_min`
  produces `under_exposed_review`.
- `deteriorating`, `suspended`, or `invalidated` with exposure above the
  minimal threshold produces `reduce_risk_review`.
- `crowded` with exposure above configured `review_max` produces
  `crowding_review`.
- Missing thesis state produces `missing_thesis_state_warning`.
- Theme exposure above `max_theme_exposure` produces `over_exposed_review`.
- Single asset exposure above `max_single_asset_exposure` produces
  `concentration_warning`.

Risk-budget checks can also produce cash buffer, total equity exposure, and high
beta exposure review flags.

## Risk Flags

Risk flags include the flag type, severity, message, review action, optional
thesis/theme/symbol, exposure, and threshold. Review actions are prompts for
human review only. They are not instructions to buy, sell, rebalance, or execute
orders.

## DecisionLog Policy

Each portfolio review appends a `DecisionLog` row:

- `decision_type`: `portfolio_review`
- `action`: `review_only`
- `portfolio_impact`: `human_review_required`
- `metadata_json`: exposure breakdown, latest thesis states, risk flags, and
  `no_auto_trade`

DecisionLog rows remain append-only.

## No-Auto-Trade Boundary

Portfolio review outputs are exposure diagnostics, risk flags, DecisionLog rows,
and markdown memos. The system must not emit broker orders, order routing
payloads, auto-trading instructions, or LLM-directed buy/sell decisions.
