# Real-Run Postrun Checklist

Complete this checklist after any bounded real official-data smoke run.

## Inserted Counts By Source

- [ ] FRED inserted count reviewed.
- [ ] ECOS inserted count reviewed.
- [ ] OpenDART disclosure inserted count reviewed.
- [ ] OpenDART financial inserted count reviewed.
- [ ] KRX inserted count reviewed.
- [ ] Unexpected zero-count sources are explained.

## Skipped Duplicate Counts

- [ ] Duplicate source-record counts reviewed.
- [ ] Duplicate evidence skips reviewed.
- [ ] Duplicate thesis snapshot skips reviewed.
- [ ] Repeated run behavior is documented if this was a rerun.

## Normalized Events

- [ ] Event count by event type reviewed.
- [ ] `available_from` values are spot-checked.
- [ ] Financial events reviewed for expected summary accounts.
- [ ] Market events reviewed for expected threshold behavior.

## Evidence Rows

- [ ] Evidence counts by thesis reviewed.
- [ ] Supports/contradicts/neutral balance reviewed.
- [ ] Top supporting evidence reviewed.
- [ ] Top contradicting evidence reviewed.
- [ ] Duplicate prevention behavior documented.

## Thesis Snapshots

- [ ] ThesisStateSnapshot rows reviewed.
- [ ] Proposed state and transition reasons reviewed.
- [ ] Snapshot metadata includes relevant evidence IDs or scoring components.
- [ ] No duplicate identical snapshot was appended unexpectedly.

## Scenario Triggers

- [ ] ScenarioTriggerLog rows reviewed.
- [ ] Trigger reasons and metrics reviewed.
- [ ] No scenario is treated as an automated trade instruction.

## Playbook Actions

- [ ] Allowed risk-review actions reviewed.
- [ ] Forbidden actions reviewed.
- [ ] Actions remain review-only labels such as `reduce_risk_review` or
      `close_review_required`.

## Smoke Report Path

- [ ] `real_data_smoke_report_<smoke_id>_<mode>.md` exists.
- [ ] Report warnings and limitations reviewed.
- [ ] Report includes `no_auto_trade=true` or the no-auto-trade disclaimer.

## Dashboard Review

- [ ] Dashboard launched or launch command recorded.
- [ ] Overview counts inspected.
- [ ] Event monitor inspected.
- [ ] Evidence monitor inspected.
- [ ] Thesis state monitor inspected.
- [ ] KOR_SEMI drilldown inspected when relevant.

## Acceptance Report

- [ ] `project-stock render-real-run-acceptance-template --run-id ...` was run.
- [ ] Generated report path is under `data/processed/real_run_acceptance/`.
- [ ] Generated report is not committed unless it is a sanitized example.
- [ ] Manual final acceptance decision selected: `accepted`,
      `accepted_with_notes`, `rejected`, or `rerun_required`.
- [ ] Raw data, raw cache files, database files, generated outputs, and real API
      outputs were not committed.

## Error/Warning Review

- [ ] CLI warnings reviewed.
- [ ] Memo warnings reviewed.
- [ ] Any failed source fetch is linked to raw cache or provider error details.
- [ ] Follow-up action is documented before rerun.

## Raw Cache Retention

- [ ] Raw cache paths are recorded.
- [ ] Raw cache files are kept until audit review is complete.
- [ ] Raw data is not committed to Git.
- [ ] Cleanup timing is documented.

## Data Quality Notes

- [ ] Missing observations noted.
- [ ] Unexpected values noted.
- [ ] Source publication-time assumptions noted.
- [ ] Point-in-time limitations noted.

## Manual Investment Review Notes

- [ ] Human reviewer records interpretation outside the automated pipeline.
- [ ] Any thesis or portfolio action remains a manual review decision.
- [ ] No LLM investment decision is used.

## No Automated Trading Confirmation

- [ ] Confirm no broker execution occurred.
- [ ] Confirm no auto-trading occurred.
- [ ] Confirm no live buy/sell orders were generated.
- [ ] Confirm no LLM investment decision occurred.
- [ ] Confirm system output remained decision support only.
