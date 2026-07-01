# project-stock

`project-stock` is an MVP scaffold for a macro-thematic flow investment
decision-support system. It tracks thesis definitions, scenarios, evidence, and
risk-review decisions. It is not an auto-trading system: there is no broker
integration, no order execution, and no LLM-directed buy/sell decision path.

## Architecture Overview

The MVP uses local SQLite for relational state and includes a Parquet-ready
storage adapter for later market and indicator datasets. The core flow is:

1. Raw source material or mock fixtures are collected.
2. Rule-based normalizers turn raw inputs into events.
3. Entity mapping links events to companies, assets, sectors, themes, countries,
   and macro factors.
4. Evidence generation links normalized events to theses and scenarios.
5. Scenario triggers compare current metrics with YAML-defined conditions.
6. Playbooks return allowed and forbidden risk-management actions only.
7. EvidenceLedger and DecisionLog rows are appended for auditability.
8. Sentinels render markdown memos for human review.
9. Offline validation replays fixture returns to diagnose thesis states,
   scenario signals, and portfolio review flags.

## Install

```bash
python -m pip install -e ".[dev]"
```

API keys are optional and are not required for tests or the local demo.

## 5-Minute Local Demo

```bash
project-stock init-db --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock load-yaml --thesis-dir thesis --scenario-dir scenarios --playbook-dir playbooks
project-stock ingest-mock --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock run-daily --as-of 2026-06-29 --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock run-emergency --fixture tests/fixtures/emergency_rate_shock.json --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock score-big-flow --fixture tests/fixtures/big_flow_kor_semi.json
```

The emergency fixture returns a rate-shock scenario match, risk actions,
forbidden actions, and appends EvidenceLedger and DecisionLog records. The daily
run writes a markdown memo under `data/processed/`.

## Operational Review Loop Demo

The operational loop connects mock ingestion, event normalization, evidence
generation, scenario matching, playbook checks, decision logging, and memo
rendering. It remains review-only: no broker execution, no auto-trading, and no
LLM-directed buy/sell decisions.

```bash
project-stock run-daily-review-loop --as-of 2026-06-29 --ingest-mock-bundle --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock run-intraday-review-loop --fixture tests/fixtures/emergency_rate_shock.json --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Both commands write markdown memos under `data/processed/` unless `--memo-dir`
is provided. Repeated runs skip duplicate source records, events, and evidence,
while appending a fresh DecisionLog row for the operational review.

## Thesis Lifecycle Demo

The thesis lifecycle demo converts accumulated EvidenceLedger rows into
append-only ThesisStateSnapshot recommendations and a thesis review memo.

```bash
project-stock run-thesis-review-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock evaluate-thesis-states --as-of 2026-06-29 --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock archive-thesis --thesis-id KOR_SEMI_MEMORY_UPCYCLE --as-of 2026-06-29 --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Lifecycle states are review recommendations only. They do not authorize broker
orders, auto-trading, or LLM-directed buy/sell decisions.

## Portfolio Review Demo

The portfolio review demo runs thesis review first, loads a deterministic
holdings fixture, calculates exposure, evaluates review flags, appends a
`portfolio_review` DecisionLog row, and renders a portfolio memo.

```bash
project-stock run-portfolio-review-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock review-portfolio --portfolio-fixture tests/fixtures/portfolio_holdings_core_satellite.json --portfolio-config configs/portfolio.example.yaml --as-of 2026-06-29 --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Portfolio outputs are review flags only. They are not broker orders or trade
instructions.

## Backtest Validation Demo

The backtest demo loads deterministic fixture returns, point-in-time thesis
state signals, portfolio review flags, and a starting exposure snapshot. It
runs a review-only simulation policy, compares it with the benchmark, computes
diagnostic validation metrics, and renders a markdown report.

```bash
project-stock run-backtest-demo --memo-dir data/processed
project-stock validate-signals --thesis-states tests/fixtures/backtest_thesis_states.json --portfolio-flags tests/fixtures/backtest_portfolio_flags.json
project-stock render-backtest-report --memo-dir data/processed
```

Backtest policies produce hypothetical exposure-change records for validation
only. They do not create broker orders, live trading instructions, or
LLM-directed buy/sell decisions.

## Dashboard Demo

The dashboard MVP is a local Streamlit app for inspecting operational outputs:
events, evidence, thesis states, portfolio reviews, scenario triggers,
emergency reviews, memo artifacts, and backtest validation reports.

```bash
python -m pip install -e ".[dev,dashboard]"
project-stock prepare-dashboard-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
project-stock run-dashboard --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
```

`run-dashboard` prints the Streamlit launch command by default. Add `--launch`
to start the local Streamlit process. The dashboard is read-only review support
and does not create broker orders, live trading instructions, or LLM-directed
buy/sell decisions.

## KOR_SEMI Thesis Pack Demo

The first real thesis pack upgrades `KOR_SEMI_MEMORY_UPCYCLE` to version `2.0`
and connects the official adapter fixtures, scenario bank, review-only
playbooks, Big Flow Score fixture, evidence generation, thesis lifecycle, and a
dedicated memo.

```bash
project-stock run-kor-semi-thesis-pack-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
project-stock score-big-flow --fixture tests/fixtures/big_flow_kor_semi_v2.json
```

The demo remains fully offline and deterministic. It writes
`kor_semi_thesis_pack_memo_<date>.md`, triggers at least one KOR_SEMI scenario
from fixture metrics, returns review-only risk actions, and creates supporting
and contradicting EvidenceLedger rows. It does not execute broker orders,
auto-trade, create live buy/sell orders, or let an LLM make investment
decisions.

## Official Data Mock Demo

These commands register official source metadata and ingest one deterministic
offline fixture from each collector. No API keys or network calls are required.

```bash
project-stock register-sources --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock ingest-official-mock-bundle --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Individual mock collectors are also available:

```bash
project-stock ingest-dart-mock --fixture tests/fixtures/official/dart_disclosures.json
project-stock ingest-ecos-mock --fixture tests/fixtures/official/ecos_indicators.json
project-stock ingest-fred-mock --fixture tests/fixtures/official/fred_indicators.json
project-stock ingest-krx-mock --fixture tests/fixtures/official/krx_market.json
project-stock ingest-news-mock --fixture tests/fixtures/official/news_rss.json
```

## Real FRED and ECOS Adapters

Real FRED and ECOS fetches are opt-in only. Network access is disabled unless
`PROJECT_STOCK_ALLOW_NETWORK=true`, and tests do not require network or real API
keys.

```bash
project-stock real-data-doctor
PROJECT_STOCK_ALLOW_NETWORK=true FRED_API_KEY=... project-stock fetch-fred-series --series-id DGS10 --start-date 2026-06-01 --end-date 2026-06-30
PROJECT_STOCK_ALLOW_NETWORK=true ECOS_API_KEY=... project-stock fetch-ecos-series --indicator-id ECOS_BASE_RATE --start-date 2026-06-01 --end-date 2026-06-30
```

Use `ingest-fred-series` and `ingest-ecos-series` to insert normalized
`IndicatorObservation` rows. Raw JSON responses are cached under `data/raw/fred/`
or `data/raw/ecos/` by default and remain ignored by Git. See
`docs/real_data_activation.md`.

## OpenDART Disclosure Adapter

OpenDART disclosure-list ingestion is opt-in for real network calls. Tests and
fixture commands do not require API keys or network access.

```bash
project-stock opendart-doctor
project-stock ingest-opendart-disclosures-fixture --fixture tests/fixtures/opendart_disclosure_list_response.json
```

For real fetches, explicitly set `PROJECT_STOCK_ALLOW_NETWORK=true` and either
`DART_API_KEY` or `OPEN_DART_API_KEY`:

```bash
project-stock fetch-opendart-disclosures --stock-code 005930 --bgn-de 20260601 --end-de 20260630
project-stock ingest-opendart-disclosures --stock-code 005930 --bgn-de 20260601 --end-de 20260630
```

This adapter only handles disclosure list rows. It does not download full report
bodies, parse XBRL, extract financial statements, execute broker orders,
auto-trade, or make LLM-directed investment decisions.

## OpenDART Financial Statement Demo

OpenDART single-company financial statements can be ingested from an offline
fixture into `FinancialStatementLineItem` rows, then summarized into normalized
events. The fixture path requires no network and no API key.

```bash
project-stock ingest-opendart-financials-fixture --fixture tests/fixtures/opendart_financial_statement_response.json --stock-code 005930 --bsns-year 2026 --reprt-code 11013 --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock normalize-financial-events --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock generate-evidence-candidates --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Real OpenDART financial fetches are opt-in only. Set
`PROJECT_STOCK_ALLOW_NETWORK=true` and `DART_API_KEY` or `OPEN_DART_API_KEY`
before using `fetch-opendart-financials` or `ingest-opendart-financials`.
Supported report codes are `11013`, `11012`, `11014`, and `11011`. The adapter
does not download XBRL, parse footnotes, execute broker orders, auto-trade, or
delegate investment decisions to an LLM.

## KRX Daily Market Data Demo

The KRX daily adapter can ingest selected daily market data from an offline
fixture into `MarketTimeSeries`, then the existing market event detector can
process those rows. No API key or network call is required for the fixture path.

```bash
project-stock krx-doctor
project-stock ingest-krx-daily-fixture --fixture tests/fixtures/krx_daily_market_response.json --symbol 005930 --start-date 2026-06-26 --end-date 2026-06-29 --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock detect-market-events --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock generate-evidence-candidates --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Real KRX fetches are opt-in only. Set `PROJECT_STOCK_ALLOW_NETWORK=true` before
using `fetch-krx-daily` or `ingest-krx-daily`. Optional credentials, if needed
by a deployment, must come from `KRX_AUTH_TOKEN` or `KRX_API_KEY`. The adapter is
daily-data only and does not implement tick data, order books, intraday minute
data, broker order routing, live account sync, derivatives data, auto-trading,
or LLM-directed investment decisions.

## Real-Data Smoke Pipeline

The real-data smoke pipeline validates that FRED, ECOS, OpenDART disclosure,
OpenDART financial, and KRX adapters can run together for a bounded KOR_SEMI
demo. Dry-run and fixture modes are fully offline.

```bash
project-stock real-data-smoke-doctor --config configs/real_data_smoke.kor_semi.example.yaml
project-stock run-real-data-smoke --config configs/real_data_smoke.kor_semi.example.yaml --dry-run
project-stock run-real-data-smoke-fixture --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Real mode requires `PROJECT_STOCK_ALLOW_NETWORK=true` plus the configured FRED,
ECOS, and OpenDART API keys. Smoke runs are capped by `max_days` and
`max_records`, write a markdown report under the configured memo directory, and
remain decision support only.

## Event Normalization Demo

The normalization demo initializes the DB, registers sources, ingests the
official mock bundle, converts source records into normalized events, and prints
event counts plus mapped entity counts.

```bash
project-stock run-event-normalization-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Individual normalization commands are available for focused checks:

```bash
project-stock normalize-events-from-documents --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock normalize-events-from-indicators --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock detect-market-events --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock normalize-events --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

## Evidence Generation Demo

The evidence demo initializes the DB, registers sources, ingests the official
mock bundle, normalizes events, generates deterministic thesis-linked evidence
candidates, appends deduplicated EvidenceLedger rows, and prints counts by
thesis and stance.

```bash
project-stock run-evidence-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Focused evidence commands are also available:

```bash
project-stock generate-evidence-candidates --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock append-evidence-candidates --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

## CLI Commands

- `project-stock init-db`: creates the SQLite schema.
- `project-stock register-sources`: inserts official source metadata.
- `project-stock load-yaml`: validates thesis, scenario, and playbook YAML.
- `project-stock ingest-mock`: inserts deterministic mock raw documents and events.
- `project-stock ingest-dart-mock`: ingests mock OpenDART disclosures.
- `project-stock ingest-ecos-mock`: ingests mock ECOS macro indicators.
- `project-stock ingest-fred-mock`: ingests mock FRED macro indicators.
- `project-stock ingest-krx-mock`: ingests mock KRX market series.
- `project-stock ingest-news-mock`: ingests mock RSS/news items with checksum dedupe.
- `project-stock ingest-official-mock-bundle`: runs one mock fixture per official collector.
- `project-stock fetch-opendart-financials`: fetches opt-in OpenDART financial preview rows.
- `project-stock ingest-opendart-financials`: ingests opt-in OpenDART financial rows.
- `project-stock ingest-opendart-financials-fixture`: ingests OpenDART financial fixture rows offline.
- `project-stock krx-doctor`: prints KRX real-data readiness without network calls.
- `project-stock fetch-krx-daily`: fetches opt-in KRX daily market data preview rows.
- `project-stock ingest-krx-daily`: ingests opt-in KRX daily market data rows.
- `project-stock ingest-krx-daily-fixture`: ingests KRX daily market fixture rows offline.
- `project-stock real-data-smoke-doctor`: validates real-data smoke config and readiness offline.
- `project-stock run-real-data-smoke`: runs dry-run or opt-in real real-data smoke flow.
- `project-stock run-real-data-smoke-fixture`: runs the offline fixture-backed real-data smoke flow.
- `project-stock normalize-events`: normalizes all collected records into events.
- `project-stock normalize-financial-events`: normalizes summary financial rows into events.
- `project-stock normalize-events-from-documents`: normalizes RawDocument records.
- `project-stock normalize-events-from-indicators`: normalizes IndicatorObservation records.
- `project-stock detect-market-events`: detects market events from MarketTimeSeries records.
- `project-stock run-event-normalization-demo`: runs the offline ingestion-to-event demo.
- `project-stock generate-evidence-candidates`: ranks event-to-thesis evidence candidates without appending.
- `project-stock append-evidence-candidates`: appends deduplicated generated candidates to EvidenceLedger.
- `project-stock run-evidence-demo`: runs the offline ingestion-to-evidence demo.
- `project-stock run-daily-review-loop`: runs the full offline daily operational review loop.
- `project-stock run-intraday-review-loop`: runs the full emergency operational review loop.
- `project-stock evaluate-thesis-states`: appends deduplicated thesis state snapshots from evidence.
- `project-stock run-thesis-review-demo`: runs the offline ingestion-to-thesis-review demo.
- `project-stock archive-thesis`: appends an explicit archived thesis snapshot.
- `project-stock review-portfolio`: reviews a portfolio fixture against config and thesis states.
- `project-stock run-portfolio-review-demo`: runs thesis review and portfolio review end to end.
- `project-stock run-backtest-demo`: runs the offline fixture-based validation demo.
- `project-stock validate-signals`: checks signal `available_from` point-in-time safety.
- `project-stock render-backtest-report`: renders the backtest validation report.
- `project-stock prepare-dashboard-demo`: prepares offline demo DB rows and memo/report artifacts.
- `project-stock run-dashboard`: prints or launches the local Streamlit dashboard command.
- `project-stock classify-events`: classifies raw documents into events.
- `project-stock run-daily`: runs the Daily Sentinel and writes a risk memo.
- `project-stock run-emergency`: runs the Intraday Emergency Sentinel fixture flow.
- `project-stock score-big-flow`: scores a thesis from a JSON fixture.

## Directory Structure

- `thesis/`: versioned thesis definitions.
- `scenarios/`: triggerable scenario definitions.
- `playbooks/`: risk-action playbooks; never broker orders.
- `src/project_stock/db/`: SQLAlchemy models and DB initialization.
- `src/project_stock/ingest/`: official collector interfaces and mock collectors.
- `src/project_stock/events/financials.py`: financial statement event normalization.
- `src/project_stock/ingest/krx.py`: KRX mock plus opt-in daily market data adapter.
- `src/project_stock/evidence/`: event-to-thesis evidence candidate generation.
- `src/project_stock/operations/`: daily and intraday operational review loops.
- `src/project_stock/portfolio/`: portfolio exposure and thesis-state-aware review.
- `src/project_stock/backtest/`: offline deterministic review-simulation validation.
- `src/project_stock/dashboard/`: local dashboard query helpers and Streamlit entrypoint.
- `src/project_stock/thesis/`: thesis loading and lifecycle state evaluation.
- `src/project_stock/sentinel/`: daily and intraday sentinel flows.
- `src/project_stock/reports/templates/`: Jinja2 markdown memo templates.
- `tests/fixtures/`: deterministic local fixtures.

## Development Principles

- Keep `available_from`, `published_at`, `release_at`, and `event_time` explicit.
- Treat EvidenceLedger and DecisionLog as append-only audit records.
- Do not add broker execution, order routing, or LLM-based trade decisions.
- Keep tests deterministic and offline.

## Validation

```bash
pytest
```
