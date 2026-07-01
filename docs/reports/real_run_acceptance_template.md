# Real-Run Acceptance Report

This report documents a bounded official-data smoke run for manual audit. Do
not paste secrets, raw API payloads, raw cache contents, SQLite database
contents, or generated trading instructions into this report. Generated real-run
acceptance reports should be written under
`data/processed/real_run_acceptance/` and should not be committed unless they
are sanitized examples.

## Run Metadata

- run_id: `{{ run_id }}`
- operator: `{{ operator }}`
- run_date: `{{ run_date }}`
- git SHA: `{{ git_sha }}`
- config path: `{{ config_path }}`
- DB path / URL: `{{ db_url }}`
- memo dir: `{{ memo_dir }}`
- raw cache dir: `{{ raw_cache_dir }}`
- acceptance report path: `{{ output_path }}`

## Environment Checks

- PROJECT_STOCK_ALLOW_NETWORK: `{{ project_stock_allow_network }}`
- FRED_API_KEY present: `{{ fred_api_key_present }}`
- ECOS_API_KEY present: `{{ ecos_api_key_present }}`
- DART_API_KEY or OPEN_DART_API_KEY present: `{{ opendart_api_key_present }}`
- KRX credential status: `{{ krx_credential_status }}`
- no_auto_trade: `{{ no_auto_trade }}`

## Preflight Result

TODO: paste summary from `project-stock real-run-preflight`, excluding secrets.

## Doctor Result

TODO: paste summary from `real-data-smoke-doctor`, `real-data-doctor`,
`opendart-doctor`, and `krx-doctor`, excluding secrets and raw payloads.

## Dry-Run Result

TODO: paste `project-stock run-real-data-smoke --dry-run` status and warnings.

## Fixture Smoke Result

TODO: paste fixture smoke status, memo path, inserted counts, duplicate counts,
and warnings from the deterministic offline run.

## Bounded Real Smoke Result

TODO: paste bounded real smoke status, memo path, inserted counts, duplicate
counts, and warnings. Do not paste raw API responses or database contents.

## Inserted Counts By Source

- FRED: TODO
- ECOS: TODO
- OpenDART disclosures: TODO
- OpenDART financials: TODO
- KRX: TODO

## Skipped Duplicate Counts

- FRED: TODO
- ECOS: TODO
- OpenDART disclosures: TODO
- OpenDART financials: TODO
- KRX: TODO
- EvidenceLedger: TODO
- ThesisStateSnapshot: TODO

## Normalized Event Counts

TODO: summarize normalized event counts by event type.

## Evidence Counts

TODO: summarize EvidenceLedger rows by thesis and stance.

## ThesisStateSnapshot Counts

TODO: summarize created and skipped duplicate thesis state snapshots.

## Scenario Triggers

TODO: list triggered scenarios and trigger reasons.

## Playbook Actions

TODO: list review-only playbook actions and forbidden actions.

## Smoke Report Path

`{{ smoke_report_path }}`

Manual copy/paste is preferred for high-level smoke counts. This template does
not parse smoke reports automatically.

## Dashboard Review Notes

TODO: record dashboard overview, event monitor, evidence monitor, thesis state
monitor, portfolio review, scenario/emergency monitor, backtest validation, and
KOR_SEMI drilldown observations.

## Data Quality Notes

TODO: record missing observations, unexpected values, publication-time
assumptions, point-in-time limitations, and provider warnings.

## Warnings / Errors

TODO: record command warnings, source errors, retry notes, and unresolved
questions.

## Manual Investment Review Notes

TODO: record human review notes only. Do not include automated trade
instructions, broker orders, live order payloads, or LLM investment decisions.

## No-Auto-Trade Confirmation

- [ ] Confirm no broker execution occurred.
- [ ] Confirm no auto-trading occurred.
- [ ] Confirm no live order or live buy/sell order was generated.
- [ ] Confirm no LLM investment decision occurred.
- [ ] Confirm `no_auto_trade=true` was present in relevant outputs.

## Final Acceptance Decision

Select exactly one:

- [ ] accepted
- [ ] accepted_with_notes
- [ ] rejected
- [ ] rerun_required

Decision rationale:

TODO
