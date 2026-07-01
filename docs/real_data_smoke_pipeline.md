# Real-Data Smoke Pipeline

The real-data smoke pipeline verifies that the official FRED, ECOS, OpenDART,
and KRX adapters can work together in one bounded operational flow for the
KOR_SEMI thesis demo.

It remains decision support only. It does not execute broker orders, auto-trade,
generate live buy/sell orders, or let an LLM make investment decisions.

## Modes

Start with operator preflight and the smoke doctor. Both commands are offline:

```bash
project-stock real-run-preflight --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
project-stock real-data-smoke-doctor --config configs/real_data_smoke.kor_semi.example.yaml
```

Dry-run validates config and readiness only:

```bash
project-stock run-real-data-smoke --config configs/real_data_smoke.kor_semi.example.yaml --dry-run
```

Fixture mode is offline and deterministic:

```bash
project-stock run-real-data-smoke-fixture --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Real mode requires explicit network opt-in:

```bash
PROJECT_STOCK_ALLOW_NETWORK=true project-stock run-real-data-smoke --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock run-dashboard --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
```

For real API-key execution, follow `docs/real_run_operator_runbook.md`,
`docs/checklists/real_run_preflight_checklist.md`, and
`docs/checklists/real_run_postrun_checklist.md`.

## Required API Keys

- FRED: `FRED_API_KEY`
- ECOS: `ECOS_API_KEY`
- OpenDART: `DART_API_KEY` or `OPEN_DART_API_KEY`
- KRX: no required key in the MVP adapter unless a deployment config requires
  `KRX_AUTH_TOKEN` or `KRX_API_KEY`

`real-data-smoke-doctor` prints configured sources, required keys, network
status, date ranges, symbols, companies, and safety limits without making
network calls.

## Safety Limits

The config includes `max_days` and `max_records`. Real mode validates these
before any network request. This keeps the smoke run small and prevents broad
historical downloads by default.

## Expected Outputs

Fixture and real modes:

- ingest source rows into `RawDocument`, `IndicatorObservation`,
  `FinancialStatementLineItem`, and `MarketTimeSeries`
- normalize events and mapped entities
- generate and append deduplicated evidence
- evaluate thesis state snapshots
- optionally run portfolio review if a portfolio fixture is configured
- write `real_data_smoke_report_<smoke_id>_<mode>.md`

Repeated fixture runs skip duplicate source rows, evidence, and identical thesis
snapshots where the underlying layer supports idempotency.

## Dashboard Inspection

Use the same DB URL for the smoke run and dashboard:

```bash
project-stock run-real-data-smoke-fixture --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock run-dashboard --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
```

Smoke outputs appear in the existing dashboard sections for events, evidence,
thesis states, portfolio review, and memo artifacts.

## KOR_SEMI Thesis Pack Fixture Extension

The KOR_SEMI v2 thesis pack uses the same smoke config and fixtures, then adds
deterministic KOR_SEMI scenario metrics, v2 playbook execution, and Big Flow
scoring:

```bash
project-stock run-kor-semi-thesis-pack-demo --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Fixture mode is expected to produce both supportive and contradicting KOR_SEMI
evidence. Examples include revenue growth support from OpenDART financial line
items and margin/rate/FX/market stress contradiction from financial, FRED/ECOS,
and KRX-derived events. At least one v2 KOR_SEMI scenario is triggered from the
deterministic metrics, and linked playbooks return risk-review actions only.

## Limitations

The smoke pipeline is not a full historical ingestion job or vintage database.
It uses conservative `available_from` handling but source-specific calendars,
publication lags, market holidays, revisions, and provider availability require
additional validation before research use.
