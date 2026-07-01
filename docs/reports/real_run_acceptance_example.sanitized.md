# Real-Run Acceptance Report

SANITIZED EXAMPLE. All values below are placeholders or fake values. This file
does not contain real API output, raw data, database contents, secrets, or
investment recommendations.

## Run Metadata

- run_id: `SANITIZED_RUN_YYYYMMDD_001`
- operator: `example_operator`
- run_date: `YYYY-MM-DD`
- git SHA: `0000000000000000000000000000000000000000`
- config path: `configs/real_data_smoke.kor_semi.example.yaml`
- DB path / URL: `sqlite:///./data/warehouse/example_real_run.sqlite`
- memo dir: `data/processed/example_real_run`
- raw cache dir: `data/raw`
- acceptance report path:
  `data/processed/real_run_acceptance/SANITIZED_RUN_YYYYMMDD_001.md`

## Environment Checks

- PROJECT_STOCK_ALLOW_NETWORK: `true`
- FRED_API_KEY present: `yes`
- ECOS_API_KEY present: `yes`
- DART_API_KEY or OPEN_DART_API_KEY present: `yes`
- KRX credential status: `not required / not set`
- no_auto_trade: `true`

## Preflight Result

Example status: passed. Key presence was verified as booleans only. No secrets
were copied into this report.

## Doctor Result

Example status: passed. Source config files were present. No network calls were
made by doctor commands.

## Dry-Run Result

Example status: passed. Dry-run completed without network or database writes.

## Fixture Smoke Result

Example status: passed. Fixture counts were reviewed manually.

## Bounded Real Smoke Result

Example status: passed. Real run was bounded by the configured date range and
record limits. Raw API responses were not pasted into this report.

## Inserted Counts By Source

- FRED: `<manual_count>`
- ECOS: `<manual_count>`
- OpenDART disclosures: `<manual_count>`
- OpenDART financials: `<manual_count>`
- KRX: `<manual_count>`

## Skipped Duplicate Counts

- FRED: `<manual_count>`
- ECOS: `<manual_count>`
- OpenDART disclosures: `<manual_count>`
- OpenDART financials: `<manual_count>`
- KRX: `<manual_count>`
- EvidenceLedger: `<manual_count>`
- ThesisStateSnapshot: `<manual_count>`

## Normalized Event Counts

Placeholder summary only. No real event rows are included.

## Evidence Counts

Placeholder summary only. No real EvidenceLedger contents are included.

## ThesisStateSnapshot Counts

Placeholder summary only.

## Scenario Triggers

Placeholder scenario list only.

## Playbook Actions

Review-only placeholder actions. No broker orders, no auto-trading, no live
orders, and no LLM investment decisions are included.

## Smoke Report Path

`data/processed/example_real_run/real_data_smoke_report_PLACEHOLDER_real.md`

## Dashboard Review Notes

Example note: dashboard sections loaded and were manually reviewed. No
investment recommendation is recorded here.

## Data Quality Notes

Example note: provider publication-time assumptions require continued review.

## Warnings / Errors

Example note: no unresolved warnings in this sanitized example.

## Manual Investment Review Notes

Human review notes would be recorded here. They must not be automated trade
instructions, broker order payloads, live order payloads, or LLM investment
decisions.

## No-Auto-Trade Confirmation

- [x] Confirm no broker execution occurred.
- [x] Confirm no auto-trading occurred.
- [x] Confirm no live order or live buy/sell order was generated.
- [x] Confirm no LLM investment decision occurred.
- [x] Confirm `no_auto_trade=true` was present in relevant outputs.

## Final Acceptance Decision

Select exactly one:

- [ ] accepted
- [x] accepted_with_notes
- [ ] rejected
- [ ] rerun_required

Decision rationale:

Sanitized placeholder only. This example is not an investment recommendation.
