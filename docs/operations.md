# Operations

The operations layer runs deterministic review loops over the MVP components.
It is decision support only. It does not execute broker orders, auto-trade, or
delegate buy/sell decisions to an LLM.

## Daily Review Flow

`run_daily_review_loop` performs a close-of-day review:

1. Register official source metadata.
2. Optionally ingest the offline official mock bundle with source-record dedupe.
3. Normalize source records into events and mapped entities.
4. Generate thesis-linked evidence candidates and append non-duplicates.
5. Build deterministic review metrics from explicit metrics, event metadata,
   event types, mapped entities, and evidence metadata.
6. Match YAML scenarios and evaluate playbooks in review-only mode.
7. Append a `daily_review` DecisionLog row.
8. Render `daily_review_memo_<date>.md`.

The daily decision action is `review_only`, and portfolio impact is recorded as
`no_auto_trade / human_review_required`.

## Intraday Emergency Flow

`run_intraday_review_loop` performs an urgent review:

1. Create or reuse a stable emergency event from the fixture input.
2. Map event entities.
3. Generate evidence candidates for the emergency event and append
   non-duplicates.
4. Merge explicit fixture metrics with deterministic event and evidence hints.
5. Match scenarios.
6. Compute the Emergency Impact Score.
7. Execute linked playbooks when scenario, emergency level, and confirmations
   match.
8. Append an `emergency_risk_review` DecisionLog row.
9. Render `emergency_review_memo_<event_id>.md`.

The intraday decision action is `no_new_buy` at E3 or above and
`risk_review_only` below E3. These are risk-review labels, not broker orders.

## Idempotency Rules

Daily review dedupes mock source records before insert:

- News/RSS by checksum.
- OpenDART by `rcept_no` or source/title/publication time.
- ECOS/FRED by source, indicator, period, and release time.
- KRX by source, symbol, frequency, and timestamp.

Event normalization dedupes by source lineage and close event/entity windows.
Evidence generation skips existing ledger rows with the same `event_id`,
`thesis_id`, `scenario_id`, and `evidence_type`.

DecisionLog remains append-only. Repeated operational reviews may append new
DecisionLog rows, and metadata records how many duplicate evidence candidates
were skipped.

## Memo Outputs

Daily memos include new events by type, evidence counts by thesis and stance,
matched scenarios, playbook status, human review items, and a no-auto-trade
disclaimer.

Emergency memos include the event summary, EIS score and level, matched
scenarios, affected theses, evidence counts, allowed and forbidden risk actions,
close-review requirement, and a no-auto-trade disclaimer.

Thesis review memos include the evaluation date, thesis state table,
support/contradiction/neutral scores, proposed transitions, top supporting and
contradicting evidence, invalidation warnings, recommended human review actions,
and a no-auto-trade disclaimer.

## Thesis Review Process

`run-thesis-review-demo` runs the offline source-to-thesis-review chain:

1. Register sources.
2. Ingest the official mock bundle with idempotent source-record checks.
3. Normalize events.
4. Generate and append deduplicated evidence.
5. Evaluate thesis states from accumulated EvidenceLedger rows.
6. Append deduplicated ThesisStateSnapshot rows.
7. Render `thesis_review_memo_<date>.md`.

`evaluate-thesis-states` can be run against an existing DB to append snapshots
from already accumulated evidence. `archive-thesis` is the only path that
creates an `archived` snapshot.

## Portfolio Review Process

`run-portfolio-review-demo` runs the thesis review demo first, then reviews a
local portfolio fixture:

1. Ensure thesis state snapshots exist.
2. Load `configs/portfolio.example.yaml`.
3. Load `tests/fixtures/portfolio_holdings_core_satellite.json`.
4. Calculate exposure by cash, theme, thesis, sector, asset, beta, and currency.
5. Compare exposure with latest thesis states and configured review limits.
6. Append a `portfolio_review` DecisionLog row.
7. Render `portfolio_review_memo_<portfolio_id>_<date>.md`.

`review-portfolio` can be run against an existing DB when thesis snapshots
already exist. Portfolio flags are review prompts only and never broker orders.

## Boundary

Allowed outputs are evidence rows, scenario trigger logs, decision-support logs,
thesis state snapshots, portfolio review flags, and markdown memos. Forbidden
outputs are broker orders, automatic trade execution, and LLM-directed
investment decisions.
