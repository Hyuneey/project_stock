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
- `project-stock normalize-events`: normalizes all collected records into events.
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
- `src/project_stock/evidence/`: event-to-thesis evidence candidate generation.
- `src/project_stock/operations/`: daily and intraday operational review loops.
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
