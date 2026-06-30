# MVP Milestone v0.1.0

This checkpoint marks the first integrated MVP of `project-stock`, a local
macro-thematic flow investment decision-support system. The MVP is designed for
human review, auditability, deterministic offline demos, and validation of
signals against fixtures.

It is not an auto-trading system. It does not execute broker orders, does not
auto-trade, and does not delegate investment buy/sell decisions to an LLM.

## Release Scope

- Tag: `v0.1.0-mvp`
- Base branch: `main`
- Local warehouse: SQLite under `data/warehouse/`
- Processed artifacts: markdown reports under `data/processed/`
- Test mode: offline and deterministic, with no required API keys
- Dashboard: local Streamlit app behind the optional `dashboard` extra

## PR Summary

| PR | Title | Squash commit | Summary |
| --- | --- | --- | --- |
| #1 | Build MVP scaffold for macro-thematic flow system | `9a3c4a2` | Added the Python package scaffold, SQLite SQLAlchemy models, Pydantic schemas, YAML thesis/scenario/playbook loaders, rule-based scenario and scoring MVPs, sentinel flows, CLI commands, markdown reports, fixtures, tests, docs, and CI. |
| #2 | Harden scenario triggers and audit model | `e505e6a` | Extended scenario trigger modes, hardened condition coercion and null handling, strengthened scenario tests, and documented append-only audit semantics. |
| #3 | Add official data collector interfaces | `be460fc` | Added collector interfaces and deterministic mock ingestion for official data-source classes without requiring live API keys. |
| #4 | Add event normalization pipeline | `0753318` | Added deterministic normalization from raw documents, indicators, and market time series into normalized events and mapped entities with dedupe rules. |
| #5 | Add evidence candidate generation | `8a4ba12` | Added thesis relevance matching, stance classification, strength scoring, duplicate-safe EvidenceLedger append flow, and evidence demos. |
| #6 | Integrate operational review loops | `19b6e9d` | Connected ingestion, event normalization, evidence generation, scenario matching, playbooks, decision logging, and memo rendering for daily and intraday reviews. |
| #7 | Add thesis lifecycle management | `a5ad174` | Added evidence aggregation, rule-based thesis state transitions, append-only ThesisStateSnapshot persistence, archive behavior, and thesis review memos. |
| #8 | Add portfolio review layer | `c17d70b` | Added YAML portfolio config, holding and exposure schemas, deterministic exposure calculations, thesis-state-aware review flags, DecisionLog integration, and portfolio memos. |
| #9 | Add backtest validation layer | `b8a2016` | Added offline fixture-based backtesting, point-in-time signal guards, review-only simulation policies, performance metrics, diagnostic validation metrics, and reports. |
| #10 | Add dashboard MVP | `19fd902` | Added local Streamlit dashboard queries and app sections for events, evidence, thesis states, portfolio review, emergency scenarios, backtest artifacts, and demo preparation. |

## Current Architecture

The MVP is organized as a deterministic review pipeline:

1. Source registration and mock ingestion create `RawDocument`,
   `IndicatorObservation`, and `MarketTimeSeries` records.
2. Event normalization converts source records into `Event` rows and
   deterministic `EventEntity` mappings.
3. Evidence generation maps events and entities to thesis-linked
   `EvidenceLedger` candidates with support, contradiction, or neutral stance.
4. Scenario matching evaluates YAML trigger conditions against explicit
   metrics, event metadata, entity mappings, and evidence metadata.
5. Playbook execution returns allowed and forbidden risk-review actions only.
6. Operational loops append `DecisionLog` records and render daily or emergency
   markdown memos.
7. Thesis lifecycle evaluation converts accumulated evidence into append-only
   `ThesisStateSnapshot` records and thesis review memos.
8. Portfolio review maps thesis states and evidence context to exposure review
   flags and portfolio review memos.
9. Backtest validation evaluates fixture-based thesis states, scenario signals,
   and portfolio flags with point-in-time guardrails.
10. The local dashboard reads the SQLite warehouse and memo artifacts for
    inspection.

Core persistence is SQLite-compatible through SQLAlchemy. The project also
includes Parquet-ready storage helpers for later offline datasets. Tests and
demos run without network calls or paid APIs.

## Key CLI Commands

Setup and source ingestion:

```bash
project-stock init-db --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock load-yaml --thesis-dir thesis --scenario-dir scenarios --playbook-dir playbooks
project-stock register-sources --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock ingest-official-mock-bundle --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Event and evidence pipeline:

```bash
project-stock normalize-events --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock run-event-normalization-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock generate-evidence-candidates --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock run-evidence-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Operational review:

```bash
project-stock run-daily-review-loop --as-of 2026-06-29 --ingest-mock-bundle --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock run-intraday-review-loop --fixture tests/fixtures/emergency_rate_shock.json --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

Thesis, portfolio, and validation:

```bash
project-stock run-thesis-review-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock run-portfolio-review-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite
project-stock run-backtest-demo --memo-dir data/processed
```

Dashboard:

```bash
python -m pip install -e ".[dev,dashboard]"
project-stock prepare-dashboard-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
project-stock run-dashboard --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
```

`run-dashboard` prints a Streamlit launch command by default. It does not need
to start a browser during tests.

## Validation Result

Validation was performed on `main` after PR #1 through PR #10 were squash
merged.

- `git pull origin main`: passed, already up to date.
- Python interpreter: `Python 3.12.13`.
- `python -m pip install -e ".[dev,dashboard]"`: passed. The active local
  interpreter initially lacked `pip`, so `python -m ensurepip --upgrade` was run
  once before reinstalling the project successfully.
- `ruff check .`: passed with `All checks passed!`.
- `pytest`: direct local execution first hit a Windows ACL issue while removing
  the repo-local `.pytest_tmp` directory. Re-running the same suite with a clean
  temp base and cache disabled passed: `99 passed in 7.53s`.
- `project-stock prepare-dashboard-demo --db-url sqlite:///./data/warehouse/final_acceptance.sqlite --memo-dir data/processed/final_acceptance`: passed and wrote daily, thesis, portfolio, and backtest artifacts.
- `project-stock run-backtest-demo --memo-dir data/processed/final_acceptance_backtest`: passed and wrote `backtest_validation_report_MVP_FIXTURE_BACKTEST.md`.
- `project-stock run-dashboard --db-url sqlite:///./data/warehouse/final_acceptance.sqlite --memo-dir data/processed/final_acceptance`: passed and printed the Streamlit launch command.

Generated acceptance artifacts:

- `data/warehouse/final_acceptance.sqlite`
- `data/processed/final_acceptance/daily_review_memo_2026-06-29.md`
- `data/processed/final_acceptance/thesis_review_memo_2026-06-29.md`
- `data/processed/final_acceptance/portfolio_review_memo_PERSONAL_CORE_SATELLITE_2026-06-29.md`
- `data/processed/final_acceptance/backtest_validation_report_MVP_FIXTURE_BACKTEST.md`
- `data/processed/final_acceptance_backtest/backtest_validation_report_MVP_FIXTURE_BACKTEST.md`

## No-Trade Boundary

The MVP intentionally enforces a decision-support boundary:

- No broker execution.
- No order routing.
- No generated buy/sell orders.
- No auto-trading.
- No live trading instructions.
- No LLM-directed investment decisions.

Allowed outputs are review records, risk-review labels, forbidden-action lists,
scenario matches, thesis state recommendations, exposure review flags, markdown
memos, fixture-based validation reports, and dashboard summaries.

## Next Steps

1. Add migration management before expanding schemas beyond MVP SQLite tables.
2. Add authenticated real collectors behind explicit opt-in configuration while
   preserving offline fixture tests.
3. Add richer source reliability and point-in-time availability checks for real
   data feeds.
4. Expand event taxonomy coverage and entity dictionaries for more sectors,
   assets, countries, and macro factors.
5. Add report persistence metadata for dashboard backtest and memo discovery.
6. Add benchmarked validation fixtures with broader historical regimes.
7. Add deployment documentation for local-only dashboard usage and optional
   private environment setup.
8. Keep all future layers inside the no-broker, no-auto-trading, no-LLM-trade
   decision boundary unless the project scope is explicitly changed.
