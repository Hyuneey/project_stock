# KOR_SEMI Thesis Pack

`KOR_SEMI_MEMORY_UPCYCLE` v2.0 is the first real thesis pack built on the
official adapter interfaces and the real-data smoke pipeline. It remains a
review-support workflow only.

## Purpose

The thesis tracks whether Korean memory leaders can benefit from memory price
recovery, resilient AI/server demand, improving operating-income revisions, and
confirmed semiconductor relative strength while rates, FX, volatility, and
crowding risks remain contained.

## Data Source Mapping

- FRED: `DGS10`, `DGS2`, `VIXCLS`, `FEDFUNDS`
- ECOS: `ECOS_BASE_RATE`, `ECOS_CPI_KR`
- OpenDART: disclosure list and selected financial line items for `005930` and
  `000660`
- KRX: `005930`, `000660`, `KOSPI200`, `SEMI_ETF_PROXY`

Real network fetches remain opt-in through `PROJECT_STOCK_ALLOW_NETWORK=true`.
The thesis pack demo uses fixture mode and requires no API keys.

## Scenario Bank

The v2 scenario bank lives under `scenarios/KOR_SEMI_MEMORY_UPCYCLE/`:

- `bull_memory_upcycle_v2.0.yaml`
- `base_gradual_recovery_v2.0.yaml`
- `bear_revision_deterioration_v2.0.yaml`
- `shock_rate_fx_stress_v2.0.yaml`
- `shock_ai_capex_slowdown_v2.0.yaml`
- `shock_semiconductor_price_breakdown_v2.0.yaml`

Triggers use deterministic `any_of`, `all_of`, and `min_score` conditions.
Fixture metrics are intentionally mixed so the demo creates both supportive and
contradicting review evidence.

## Playbooks

KOR_SEMI v2 playbooks return review-only actions:

- `no_new_buy_review`
- `reduce_risk_review`
- `close_review_required`
- `update_thesis_watchlist`
- `request_human_review`
- `do_not_auto_trade`

Forbidden actions include `broker_order`, `auto_trade`,
`live_buy_sell_order`, and `llm_direct_trade_decision`.

## Evidence Mapping

Supportive examples:

- `revenue_growth_candidate`
- `operating_income_growth_candidate`
- positive `market_large_move` or `sector_relative_strength_move`
- improved guidance or sector news

Contradicting examples:

- `margin_pressure_candidate`
- `leverage_change_candidate`
- `rate_policy_relevant`
- `fx_stress_move`
- `rates_shock_move`
- `volatility_shock_move`
- negative semiconductor market moves

Rules are deterministic and transparent. No LLM is used.

## Demo Command

```bash
project-stock run-kor-semi-thesis-pack-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
project-stock score-big-flow --fixture tests/fixtures/big_flow_kor_semi_v2.json
```

The demo initializes the DB if needed, runs fixture-backed smoke ingestion,
normalizes events, appends KOR_SEMI evidence, matches v2 scenarios, executes
review-only playbooks, evaluates thesis state, and writes
`kor_semi_thesis_pack_memo_<date>.md`.

## Dashboard Inspection

Prepare drilldown demo data and launch the dashboard:

```bash
project-stock prepare-kor-semi-dashboard-demo --db-url sqlite:///./data/warehouse/kor_semi_dashboard.sqlite --memo-dir data/processed/kor_semi_dashboard
project-stock run-dashboard --db-url sqlite:///./data/warehouse/kor_semi_dashboard.sqlite --memo-dir data/processed/kor_semi_dashboard
```

Inspect the KOR_SEMI Drilldown tab for:

- latest thesis state and Big Flow Score
- evidence balance by stance
- top supporting and contradicting evidence
- triggered scenarios
- review-only playbook actions
- financial and market signals
- memo links

Evidence balance should be interpreted as a review queue. Supportive evidence
identifies what strengthens the thesis, while contradicting evidence identifies
risks that may require close review. It is not a buy/sell instruction.

## Limitations

- Fixture evidence is deterministic and diagnostic, not proof of profitability.
- OpenDART financial mapping only covers selected summary accounts.
- Scenario triggers are rule-based and intentionally conservative.
- Real data calls are disabled unless explicitly opted in.
- No broker execution, no auto-trading, no live buy/sell orders, and no LLM
  investment decision logic are implemented or authorized.
