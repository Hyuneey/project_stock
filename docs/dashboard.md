# Dashboard MVP

The dashboard MVP is a local Streamlit app for inspecting outputs from the
macro-thematic flow system. It reads SQLite rows and markdown artifacts already
created by offline demos or operational review loops.

## Install

Streamlit is optional:

```bash
python -m pip install -e ".[dev,dashboard]"
```

The normal test suite does not require launching Streamlit.

## Prepare Demo Data

Run:

```bash
project-stock prepare-dashboard-demo --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
```

This command is offline and deterministic. It initializes the DB, runs the daily
review loop over mock fixtures, runs thesis review, runs portfolio review, runs
backtest validation, writes memo/report artifacts, and prints a dashboard launch
command.

To inspect smoke pipeline outputs, run the fixture smoke against the same DB:

```bash
project-stock run-real-data-smoke-fixture --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/project_stock.sqlite
```

For real API-key runs, prepare and review the same DB with the operator-safe
sequence:

```bash
project-stock real-run-preflight --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/real_run.sqlite --memo-dir data/processed/real_run
project-stock real-data-smoke-doctor --config configs/real_data_smoke.kor_semi.example.yaml
project-stock run-real-data-smoke --config configs/real_data_smoke.kor_semi.example.yaml --dry-run
project-stock run-real-data-smoke-fixture --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/real_run.sqlite
PROJECT_STOCK_ALLOW_NETWORK=true project-stock run-real-data-smoke --config configs/real_data_smoke.kor_semi.example.yaml --db-url sqlite:///./data/warehouse/real_run.sqlite
project-stock run-dashboard --db-url sqlite:///./data/warehouse/real_run.sqlite --memo-dir data/processed/real_run
```

Use `docs/real_run_operator_runbook.md` and the checklists under
`docs/checklists/` before relying on dashboard views from real API data.

For the KOR_SEMI drilldown, prepare a focused demo DB:

```bash
project-stock prepare-kor-semi-dashboard-demo --db-url sqlite:///./data/warehouse/kor_semi_dashboard.sqlite --memo-dir data/processed/kor_semi_dashboard
```

## Launch

Print the launch command:

```bash
project-stock run-dashboard --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
```

Start Streamlit directly:

```bash
project-stock run-dashboard --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed --launch
```

The printed command is equivalent to:

```bash
python -m streamlit run src/project_stock/dashboard/app.py -- --db-url sqlite:///./data/warehouse/project_stock.sqlite --memo-dir data/processed
```

## Sections

### Overview

Shows the DB URL, latest available dates, table counts for core records, and
latest memo/report artifacts under the memo directory.

### Event Monitor

Shows recent normalized events with event type, source, available time, summary,
scores, and mapped entity counts. Event type and source filters are local only.

### Evidence Monitor

Shows evidence counts by thesis and stance, top evidence by strength score, and
duplicate evidence skip counts when DecisionLog metadata contains them.

### Thesis State Monitor

Shows the latest ThesisStateSnapshot per thesis with support, contradiction,
net evidence, risk score, transition reasons, and top supporting or
contradicting evidence when the snapshot metadata links evidence IDs.

### KOR_SEMI Drilldown

Shows a focused view for `KOR_SEMI_MEMORY_UPCYCLE`:

- latest thesis state and snapshot metrics
- Big Flow Score when available from the thesis pack demo
- evidence balance across supports, contradicts, and neutral
- top supporting and contradicting evidence
- triggered KOR_SEMI scenarios
- review-only playbook actions from related DecisionLog rows
- related financial and market events
- KOR_SEMI memo links

Evidence balance is a review signal, not a trade signal. A high contradiction
count should direct the user to inspect the top contradicting evidence, scenario
triggers, and close-review actions. It does not authorize automated selling or
broker execution.

### Portfolio Review

Shows the latest `portfolio_review` DecisionLog, exposure breakdown, latest
thesis states used by the review, and portfolio risk flags from metadata.

### Scenario / Emergency Monitor

Shows ScenarioTriggerLog rows and the latest `emergency_risk_review` DecisionLog
when present, including allowed risk-review actions, forbidden actions, and
emergency level if available.

### Backtest Validation

Shows the latest `backtest_validation_report_*.md` artifact from the memo
directory, parsed return/risk metrics, diagnostic metrics, and point-in-time
warnings.

### Real-Data Smoke Outputs

Smoke pipeline rows appear in the existing event, evidence, thesis state, and
portfolio sections when the dashboard points at the same SQLite DB. The smoke
report itself appears in memo artifacts under the configured memo directory.

## Limitations

- The dashboard is a local MVP and reads only the configured SQLite DB and memo
  directory.
- It does not fetch external data or require API keys.
- Empty tables render empty sections instead of raising.
- Backtest metrics are parsed from local report artifacts unless future
  persistence is added.
- It is not an operations console for live execution.

## No-Auto-Trade Boundary

Dashboard output is human review support only. It must not create broker orders,
order-routing payloads, live trading instructions, auto-trading actions, or
LLM-directed buy/sell decisions.
