# First Bounded Real Smoke Acceptance Record

SANITIZED RECORD. This document contains only operator-level status and
aggregate fixture-smoke counts. It does not contain API keys, secrets, raw API
responses, raw market data rows, database dumps, generated local reports, buy
or sell recommendations, portfolio orders, or broker payloads.

## Run Metadata

- run_id: `FIRST_BOUNDED_REAL_SMOKE`
- git SHA at procedure start: `645eeef5c5bf51534827ac6d3c167d6675e9918a`
- config path: `configs/real_data_smoke.kor_semi.example.yaml`
- intended real DB URL: `sqlite:///./data/warehouse/first_real_smoke.sqlite`
- fixture DB URL: `sqlite:///./data/warehouse/first_real_smoke_fixture.sqlite`
- intended memo dir: `data/processed/first_real_smoke`
- generated local acceptance report path:
  `data/processed/real_run_acceptance/FIRST_BOUNDED_REAL_SMOKE.md`
- no_auto_trade: `true`

## Command Sequence

1. `project-stock real-run-preflight --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/first_real_smoke.sqlite --memo-dir data/processed/first_real_smoke`
2. `project-stock real-data-smoke-doctor --config configs/real_data_smoke.kor_semi.example.yaml`
3. `project-stock run-real-data-smoke --config configs/real_data_smoke.kor_semi.example.yaml --dry-run`
4. `project-stock run-real-data-smoke-fixture --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/first_real_smoke_fixture.sqlite`
5. Bounded real smoke: not run.
6. `project-stock render-real-run-acceptance-template --run-id FIRST_BOUNDED_REAL_SMOKE --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/first_real_smoke.sqlite --memo-dir data/processed/first_real_smoke --output-path data/processed/real_run_acceptance/FIRST_BOUNDED_REAL_SMOKE.md`

## Procedure Results

- preflight passed: `yes`
- doctor passed: `yes`
- dry-run passed: `yes`
- fixture smoke passed: `yes`
- real smoke status: `skipped_missing_keys`
- dashboard review status: `not_performed_real_smoke_skipped`

## Real Smoke Decision

The bounded real smoke was not executed because real network opt-in was disabled
and required API keys were not present in the local environment:

- `PROJECT_STOCK_ALLOW_NETWORK=false`
- `FRED_API_KEY` present: `no`
- `ECOS_API_KEY` present: `no`
- `DART_API_KEY` or `OPEN_DART_API_KEY` present: `no`
- KRX credential present: `no / not required for MVP adapter`

This is an accepted safe stop condition for the first bounded real-run attempt.

## Fixture Smoke Aggregate Summary

Fixture mode was executed offline to confirm the pipeline shape before any real
API call.

Inserted counts:

- `FRED.indicator_observations`: 4
- `BOK_ECOS.indicator_observations`: 2
- `OPEN_DART.raw_documents`: 2
- `OPEN_DART.financial_statement_line_items`: 6
- `KRX.market_time_series`: 2

Skipped duplicate counts:

- source-record duplicate skips: 0 for all fixture sources in this run
- `EvidenceLedger`: 0
- `ThesisStateSnapshot`: 0

Aggregate review outputs:

- normalized event count: 13
- evidence count: 26
- thesis snapshot count: 2
- evidence by thesis:
  - `KOR_SEMI_MEMORY_UPCYCLE`: 13
  - `AI_INFRASTRUCTURE`: 13
- thesis states:
  - `KOR_SEMI_MEMORY_UPCYCLE`: `deteriorating`
  - `AI_INFRASTRUCTURE`: `deteriorating`

These are deterministic fixture outputs only. They are not real market-data
results and are not investment recommendations.

## Warnings / Errors

- preflight warning: missing real API keys for FRED, ECOS, and OpenDART real
  sources.
- dry-run warning: completed without network or database writes.
- fixture smoke warnings: none reported.
- real smoke: skipped, so no real source errors or provider payloads exist.

## Dashboard Review Status

Dashboard review was not performed for a real smoke DB because the bounded real
smoke was skipped. Generated local fixture memo/report artifacts remain under
ignored `data/` paths and are not committed.

## Git Hygiene

Before commit, validate:

- `git ls-files data` lists only `.gitkeep` files.
- no `.sqlite` or `.db` files are tracked.
- no raw cache files are tracked.
- no generated local report under `data/` is tracked.
- no `.env`, API keys, secrets, or tokens are tracked.

## No-Auto-Trade Confirmation

- no broker execution occurred
- no auto-trading occurred
- no live buy/sell orders were generated
- no LLM investment decision occurred
- no portfolio orders were created
- no_auto_trade: `true`

## Final Acceptance Decision

`skipped_missing_keys`

The first bounded real-run attempt is accepted as a safe stopped run. The next
bounded real smoke should only be attempted when the operator explicitly sets
`PROJECT_STOCK_ALLOW_NETWORK=true` and provides the required API keys.
