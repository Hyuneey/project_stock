# Real-Run Operator Runbook

This runbook describes how to execute the official-data pipeline with real API
keys in a bounded, auditable way. It is for operator safety and repeatability;
it does not add investment logic.

## Purpose

Use this procedure when validating real FRED, ECOS, OpenDART, and KRX adapters
against the controlled KOR_SEMI smoke configuration. The intended output is a
local SQLite warehouse, raw response cache files, markdown memos, and dashboard
views for human review.

## Safety Boundary

The system is decision support only. It has no broker execution, no
auto-trading, no live buy/sell orders, and no LLM investment decision path.
Every real API call must be explicitly enabled with
`PROJECT_STOCK_ALLOW_NETWORK=true`.

## Required Environment Variables

Real mode requires:

- `PROJECT_STOCK_ALLOW_NETWORK=true`
- `FRED_API_KEY`
- `ECOS_API_KEY`
- `DART_API_KEY` or `OPEN_DART_API_KEY`

KRX does not require credentials in the MVP adapter. If a deployment needs KRX
credentials or tokens, read them only from `KRX_AUTH_TOKEN` or `KRX_API_KEY`.

## Confirm Default Safe Mode

With no environment changes, network access should be disabled:

```bash
project-stock real-run-preflight --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/real_run.sqlite --memo-dir data/processed/real_run
```

The output should show `network_enabled=false`, key presence only as booleans,
and `no_auto_trade=true`. This command never calls real APIs.

## Run Doctors

Run source readiness checks before any real execution:

```bash
project-stock real-run-preflight --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/real_run.sqlite --memo-dir data/processed/real_run
project-stock real-data-smoke-doctor --config configs/real_data_smoke.kor_semi.example.yaml
project-stock real-data-doctor --db-url sqlite:///./data/warehouse/real_run.sqlite
project-stock opendart-doctor --db-url sqlite:///./data/warehouse/real_run.sqlite
project-stock krx-doctor --db-url sqlite:///./data/warehouse/real_run.sqlite
```

Doctors inspect configuration, environment flags, key presence, and cache paths.
They must not make network calls.

## Run Dry-Run

Dry-run must pass before real mode:

```bash
project-stock run-real-data-smoke --config configs/real_data_smoke.kor_semi.example.yaml --dry-run
```

Dry-run validates source readiness and safety limits without network or DB
writes.

## Run Fixture Smoke

Run the deterministic fixture path against the intended DB:

```bash
project-stock run-real-data-smoke-fixture --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/real_run.sqlite
```

Review inserted counts, duplicate skips, normalized events, evidence rows,
thesis snapshots, and the generated smoke memo before continuing.

## Run Bounded Real Smoke

Only after preflight, doctors, dry-run, and fixture smoke pass, opt in to real
network access for the bounded smoke run:

```bash
PROJECT_STOCK_ALLOW_NETWORK=true project-stock run-real-data-smoke --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/real_run.sqlite
```

Keep the configured `max_days` and `max_records` small. Do not widen date
ranges or source lists during incident response.

## Inspect Raw Cache

Real fetches write raw responses under:

- `data/raw/fred/`
- `data/raw/ecos/`
- `data/raw/opendart/`
- `data/raw/opendart/financial/`
- `data/raw/krx/`

Do not commit downloaded raw data. Preserve cache files long enough to audit
what was ingested, then apply the local retention policy.

## Inspect DB Output

Use SQLite-compatible tooling or the dashboard to inspect:

- source records in `RawDocument`, `IndicatorObservation`,
  `FinancialStatementLineItem`, and `MarketTimeSeries`
- normalized `Event` and `EventEntity` rows
- `EvidenceLedger` rows
- `ThesisStateSnapshot` rows
- `ScenarioTriggerLog` and `DecisionLog` rows

Audit records are append-only at the application level.

## Launch Dashboard

Point the dashboard at the same DB and memo directory:

```bash
project-stock run-dashboard --db-url sqlite:///./data/warehouse/real_run.sqlite --memo-dir data/processed/real_run
```

Use `--launch` only when starting a local Streamlit process is intentional.

## Review KOR_SEMI Drilldown

In the KOR_SEMI drilldown, inspect:

- latest thesis state and score components
- supportive, contradicting, and neutral evidence counts
- top supporting and contradicting evidence
- triggered scenarios
- playbook review-only actions
- financial and market events
- latest KOR_SEMI and smoke memo links

Review actions are prompts for human analysis. They are not trade orders.

## Failure Handling

If preflight fails, fix environment variables, config paths, or DB/memo paths
before retrying. If dry-run fails, do not run real mode. If fixture smoke fails,
fix deterministic fixture behavior before using real keys. If real mode fails
after partial inserts, keep the DB and raw cache for audit, then rerun only
after reviewing duplicate counts and warnings.

## Rollback / Cleanup

For local runs, rollback means preserving the failed DB for audit, copying it
aside if needed, and starting a new DB URL for the next attempt. Do not delete
raw cache files until the run has been reviewed. Generated memo directories can
be archived or moved after review.

## DB Backup Recommendation

Before a real run, copy the target SQLite file or use a fresh run-specific DB
path such as `data/warehouse/real_run_YYYYMMDD.sqlite`. Keep the pre-run backup
until the post-run checklist is complete.

## Boundary Confirmation

Before and after every real run, confirm:

- no broker execution
- no auto-trading
- no live buy/sell orders
- no LLM investment decision
- `no_auto_trade=true` appears in command outputs and memos
