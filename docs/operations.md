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

## Backtest Validation Workflow

`run-backtest-demo` validates review signals against deterministic fixture
returns:

1. Load `configs/backtest.example.yaml`.
2. Load fixture market returns, thesis state signals, portfolio flags, and
   starting portfolio exposures.
3. Enforce point-in-time signal availability.
4. Run the configured review-only simulation policy.
5. Run the benchmark comparison policy.
6. Compute return/risk metrics, turnover, transaction cost impact, benchmark
   relative return, and diagnostic signal usefulness metrics.
7. Render `backtest_validation_report_<backtest_id>.md`.

`validate-signals` checks signal `available_from` dates before simulation.
`render-backtest-report` reruns the deterministic fixture validation and writes
the markdown report. These workflows do not write EvidenceLedger, DecisionLog,
or broker records; they are offline diagnostics only.

## OpenDART Financial Statement Workflow

Use the fixture-backed path for local validation:

1. Run `ingest-opendart-financials-fixture` with a fixture, stock or corp code,
   business year, and supported report code.
2. Run `normalize-financial-events` to convert supported summary accounts into
   normalized events and mapped entities.
3. Run `generate-evidence-candidates` or the broader review demos to connect
   those events to thesis evidence.

The real commands `fetch-opendart-financials` and `ingest-opendart-financials`
are disabled unless `PROJECT_STOCK_ALLOW_NETWORK=true` and `DART_API_KEY` or
`OPEN_DART_API_KEY` is set. They write raw JSON caches under
`data/raw/opendart/financial/` when caching is enabled. The adapter uses
`collected_at` as the conservative `available_from` when OpenDART response rows
do not contain an exact timestamp.

This workflow supports only single-company financial statement ingestion for
report codes `11013`, `11012`, `11014`, and `11011`. It does not download XBRL,
parse footnotes, produce orders, auto-trade, or delegate investment decisions to
an LLM.

## Dashboard Workflow

`prepare-dashboard-demo` prepares local demo data for inspection:

1. Initialize the SQLite database.
2. Run the offline daily review loop with official mock fixtures.
3. Run the thesis review demo.
4. Run the portfolio review demo.
5. Run the backtest validation demo.
6. Print the Streamlit launch command.

`run-dashboard` prints the command needed to launch the local Streamlit app. With
`--launch`, it starts Streamlit locally. Tests use the query helpers and command
printing only; they do not start a browser or server.

Dashboard sections are read-only views over existing operational outputs. They
must not mutate audit rows, fetch external data, or create live trading records.

## Real Data Activation Workflow

FRED and ECOS real adapters are opt-in. The normal test suite and local demos
remain offline.

1. Run `project-stock real-data-doctor` to inspect DB URL, network flag, API key
   presence, raw cache directories, supported FRED series, configured ECOS
   series, and point-in-time cautions. This command performs no network calls.
2. Set `PROJECT_STOCK_ALLOW_NETWORK=true` only for intentional real fetches.
3. Set `FRED_API_KEY` or `ECOS_API_KEY` in the environment or `.env`.
4. Use `fetch-fred-series` or `fetch-ecos-series` to preview normalized
   observations without DB insert.
5. Use `ingest-fred-series` or `ingest-ecos-series` to append
   `IndicatorObservation` rows.

Raw JSON responses are cached under `data/raw/fred/` and `data/raw/ecos/` by
default and remain ignored by Git. Real observations are marked `available_from`
no earlier than source release metadata and local collection time, but source
release calendars and vintage behavior still require additional review before
research use.

## OpenDART Real Data Workflow

OpenDART disclosure list ingestion is opt-in. The normal test suite and local
demo flows remain offline.

1. Run `project-stock opendart-doctor` to inspect DB URL, network flag, API key
   presence, corp-code config status, raw cache directory, and no-auto-trade
   boundary. This command performs no network calls.
2. Use `ingest-opendart-disclosures-fixture` for offline fixture ingestion.
3. Set `PROJECT_STOCK_ALLOW_NETWORK=true` only for an intentional real fetch.
4. Set `DART_API_KEY` or `OPEN_DART_API_KEY` in the environment or `.env`.
5. Use `fetch-opendart-disclosures` to preview normalized `RawDocument` rows.
6. Use `ingest-opendart-disclosures` to insert disclosure-list rows into the
   SQLite warehouse.

The adapter supports disclosure list metadata only. It does not download report
bodies, parse XBRL, extract financial statements, or create any trade action.

## Boundary

Allowed outputs are evidence rows, scenario trigger logs, decision-support logs,
thesis state snapshots, portfolio review flags, and markdown memos. Forbidden
outputs are broker orders, automatic trade execution, and LLM-directed
investment decisions.
