# Codex Implementation Plan

## Implemented in This MVP

- Python 3.11+ package scaffold with a `project-stock` Typer CLI.
- SQLite-compatible SQLAlchemy models for core source, event, evidence, decision,
  thesis, scenario, market, and indicator state.
- Pydantic schemas for thesis, scenario, playbook, event, evidence, decision, and
  scoring contracts.
- YAML thesis/scenario/playbook loaders with validation.
- Rule-based event classifier and entity mapper.
- Scenario matcher with six comparison operators.
- Playbook executor that returns risk actions and forbidden actions only.
- Big Flow Score, Emergency Impact Score, and Thesis Impact Score.
- Daily Sentinel and Intraday Emergency Sentinel flows.
- Jinja2 markdown memo templates.
- Offline mock fixtures and pytest coverage.

## Intentionally Not Implemented

- Broker order execution.
- Auto-trading, target prices, or direct buy/sell decisions.
- Paid or authenticated data API collection.
- LLM investment-decision logic.
- Production dashboard, API service, or scheduler.

## Next Phases

- Add real KRX/OpenDART/ECOS/FRED collectors behind optional adapters.
- Add ALFRED-style macro vintages and stronger look-ahead tests.
- Add FastAPI and a dashboard after the audit model stabilizes.
- Add model-assisted report summarization without decision authority.
- Add CI and deployment documentation.
