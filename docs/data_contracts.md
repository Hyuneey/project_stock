# Data Contracts

## Core Tables

- `Source`: source metadata and default reliability.
- `RawDocument`: collected text with `published_at`, `collected_at`, and
  `available_from`.
- `MarketTimeSeries`: market observations with `timestamp`, `collected_at`, and
  `available_from`.
- `IndicatorObservation`: macro or fundamental releases with `release_at`,
  `collected_at`, `available_from`, and optional vintage fields.
- `Event`: normalized event with scores for reliability, surprise, persistence,
  market confirmation, and `available_from`.
- `EventEntity`: event-to-company, theme, or macro-factor mapping.
- `EvidenceLedger`: append-only thesis/scenario evidence.
- `DecisionLog`: append-only decision-support actions and rationale.
- `ThesisStateSnapshot`: point-in-time thesis state.
- `ScenarioTriggerLog`: scenario trigger audit rows.

## Time Fields

- `event_time`: when the event occurred.
- `published_at`: when a source published a raw document.
- `release_at`: when an indicator was officially released.
- `collected_at`: when this system collected the record.
- `available_from`: earliest timestamp when the record may be used.

## Look-Ahead Rule

Backtests and reviews must not use records before `available_from`. When a source
has `published_at` and `collected_at`, the conservative default is to use the
later timestamp as the earliest safe availability time.

Collector writes apply the same rule for each destination:

- Raw documents: `available_from >= max(published_at, collected_at)` when present.
- Indicator observations: `available_from >= max(release_at, collected_at)` when present.
- Market series: `available_from >= max(timestamp, collected_at)` when present.

## Event Normalization Contract

Every normalized event must include:

- `event_id`: stable event identifier assigned before insert.
- `event_type`: deterministic taxonomy value.
- `event_time`: source event/release/market observation time.
- `first_seen_at`: first time the system can reasonably observe the event.
- `available_from`: earliest timestamp when downstream logic may use the event.
- `summary`: human-readable event statement.
- `source_reliability`, `surprise_score`, `persistence_score`,
  `market_confirmation_score`: bounded MVP scores from 0 to 5.
- `metadata_json`: source lineage, source record ID, source ID, and source
  fields used for normalization.

`available_from` must not be earlier than the underlying source record's
`available_from`. Normalizers also retain `source_table` and `source_record_id`
inside `metadata_json` so duplicate prevention and audit review can trace the
event back to the collected record.

`event_time` is when the source phenomenon occurred or was published. For
OpenDART and News/RSS this is usually `published_at`; for ECOS/FRED this is
`release_at`; for market data this is the market observation `timestamp`.

## Evidence Candidate Contract

`EvidenceCandidate` is an intermediate, deterministic candidate generated from a
normalized `Event` and its `EventEntity` rows before append-only persistence.
Each candidate must include:

- `candidate_id`: stable candidate identifier.
- `event_id`: source normalized event.
- `thesis_id`: thesis receiving the evidence.
- `scenario_id`: optional scenario linkage when event type or trigger-related
  context matches a scenario for the same thesis.
- `evidence_type`: MVP evidence category, currently `event:<event_type>`.
- `claim`: human-readable evidence statement.
- `supports_or_contradicts`: one of `supports`, `contradicts`, or `neutral`.
- `strength_score`: 0 to 5 score combining source reliability, surprise,
  persistence, market confirmation, thesis relevance, and event-type severity.
- `relevance_score`: 0 to 100 thesis relevance score.
- `confidence_score`: 0 to 100 confidence score for the deterministic mapping.
- `source_event_type`: event taxonomy value used to generate the candidate.
- `source_entity_ids`: mapped entity IDs used for relevance and audit review.
- `created_at`: candidate generation timestamp.
- `metadata_json`: mapped entity types, relevance reasons, matched keywords, and
  source event lineage.

Appending evidence converts a candidate into an `EvidenceLedger` row. The append
path stores the canonical source event in `event_id`, mapped entity IDs in
`source_ids_json`, and preserves candidate metadata. Duplicate appends for the
same `event_id`, `thesis_id`, `scenario_id`, and `evidence_type` are skipped at
the service layer.

## Collector Contract

Official collectors expose `collector_id`, `source_id`, `fetch_raw`, `normalize`,
and `ingest`. `fetch_raw` returns typed Pydantic raw-record schemas, not arbitrary
dicts. `normalize` returns internal create schemas for `RawDocument`,
`IndicatorObservation`, or `MarketTimeSeries`. `ingest` registers source metadata
and writes through repository methods.

API keys are read from environment variables only and are required only when a
future real fetch is requested. Mock fixture ingestion must work without API keys
and without network access.

Registered official source IDs:

- `OPEN_DART`
- `BOK_ECOS`
- `FRED`
- `KRX`
- `NEWS_RSS`

## Operational Review Result Contracts

`DailyReviewResult` summarizes one close-of-day review pass:

- `as_of`: review date.
- `inserted_raw_counts`: inserted mock source records by source ID.
- `inserted_event_count`: normalized events inserted during this run.
- `mapped_entity_count`: EventEntity rows inserted during normalization.
- `evidence_candidate_count`: generated evidence candidates.
- `appended_evidence_count`: newly appended EvidenceLedger rows.
- `skipped_duplicate_evidence_count`: evidence candidates skipped by dedupe.
- `scenario_match_count`: matched scenario count after metric integration.
- `decision_log_count`: DecisionLog rows appended by the loop.
- `memo_path`: rendered markdown memo path.
- `warnings`: non-fatal operational warnings.

The schema also carries memo-supporting details: new events by type, evidence
counts by thesis and stance, matched scenario diagnostics, and playbook results.

`IntradayReviewResult` summarizes one emergency review pass:

- `event_id`: normalized or reused emergency event.
- `emergency_level`: EIS level from `E0` to `E5`.
- `emergency_score`: numeric Emergency Impact Score.
- `matched_scenarios`: deterministic scenario match diagnostics.
- `allowed_actions`: risk-review actions only, never broker orders.
- `forbidden_actions`: prohibited actions such as LLM-directed trade decisions.
- `appended_evidence_count`: newly appended EvidenceLedger rows.
- `decision_log_count`: DecisionLog rows appended by the loop.
- `memo_path`: rendered markdown memo path.
- `thesis_action`: defaults to `defer_to_close_review`.

Repeated reviews may append new DecisionLog rows. Duplicate evidence for the
same event/thesis/scenario/evidence type must be skipped and recorded in
DecisionLog metadata.

## Thesis Lifecycle Contracts

Supported `ThesisState` values are:

- `candidate`
- `watch`
- `active`
- `core_overweight`
- `crowded`
- `deteriorating`
- `suspended`
- `invalidated`
- `archived`

`ThesisStateEvaluationInput` includes `thesis_id`, `as_of`, optional
`previous_state`, optional `lookback_days`, `minimum_evidence_count`, optional
`big_flow_score`, and optional `crowding_flag`.

`ThesisStateEvaluationResult` includes:

- `thesis_id`
- `previous_state`
- `proposed_state`
- `confidence_score`
- `support_score`
- `contradiction_score`
- `neutral_score`
- `net_evidence_score`
- `risk_score`
- `big_flow_score`
- `evidence_count`
- `top_supporting_evidence`
- `top_contradicting_evidence`
- `transition_reasons`
- `recommended_review_action`
- `no_auto_trade`
- `invalidation_warnings`
- `evidence_ids`

`ThesisLifecycleTransition` records previous and proposed states, whether the
recommendation changed, transition reason, and snapshot ID when available.

`ThesisReviewResult` records evaluation count, appended snapshot count, skipped
duplicate snapshot count, memo path, evaluations, transitions, warnings, and
`no_auto_trade`.

`ThesisStateSnapshot` persistence is append-only. A run may append one snapshot
per thesis. Repeated evaluation for the same `as_of` and same evidence/scoring
fingerprint skips duplicate snapshots unless a force flag is used. Snapshot
metadata stores evidence IDs, scoring components, transition reasons,
invalidation warnings, recommended review action, and `no_auto_trade`.

## Portfolio Review Contracts

`PortfolioConfig` is loaded from YAML and includes:

- `portfolio_id`
- `base_currency`
- `review_frequency`
- `max_total_equity_exposure`
- `max_theme_exposure`
- `max_single_asset_exposure`
- `cash_buffer_min`
- `risk_budget`
- `thesis_exposure_map`
- `asset_theme_map`
- `benchmark_symbols`

`PortfolioHolding` includes `symbol`, `name`, optional `quantity`,
`market_value`, `currency`, `asset_type`, `theme_ids`, `thesis_ids`, `sector`,
optional `beta`, and optional `liquidity_bucket`.

`PortfolioSnapshot` groups holdings by `portfolio_id`, `as_of`, and
`base_currency`.

`PortfolioExposure` records total market value, cash value and ratio, total
equity exposure, theme exposure, thesis exposure, sector exposure, single asset
exposure, high beta exposure, and foreign currency exposure.

`PortfolioRiskFlag` records a review-only flag type, severity, message, review
action, optional thesis/theme/symbol, exposure, and threshold.

`PortfolioReviewResult` includes portfolio ID, date, exposure breakdown, latest
thesis states, risk flags, DecisionLog ID, memo path, and `no_auto_trade`.
Portfolio reviews append `DecisionLog` rows with `decision_type:
portfolio_review`, `action: review_only`, and `portfolio_impact:
human_review_required`.

## Scenario Trigger Contract

Thesis, scenario, and playbook YAML files are validated with Pydantic schemas.
Scenario trigger conditions support `>`, `>=`, `<`, `<=`, `==`, and `!=`.

The legacy form remains valid:

```yaml
trigger:
  any_of:
    - metric: US2Y_YIELD_CHANGE_1D_BP
      operator: ">"
      value: 15
```

New scenarios can be explicit:

```yaml
trigger:
  mode: min_score
  min_match_score: 67
  required:
    - metric: RATES_MOVE_CONFIRMED
      operator: "=="
      value: true
  optional:
    - metric: US2Y_YIELD_CHANGE_1D_BP
      operator: ">"
      value: 15
    - metric: USDKRW_CHANGE_1D_PCT
      operator: ">"
      value: 1.0
```

Supported modes:

- `any_of`: at least one optional condition must match, after required gates pass.
- `all_of`: all required conditions must match; optional conditions only affect
  score and diagnostics.
- `min_score`: required gates must pass and the total match score must meet a
  positive `min_match_score`.

Missing metrics, `null` metric values, malformed values, and failed type
coercions return unmatched condition evaluations with explicit reasons instead
of raising runtime exceptions. Boolean metric strings are parsed only from
`true`, `false`, `1`, and `0`.

## Append-Only Audit Contract

`EvidenceLedger`, `DecisionLog`, and `ThesisStateSnapshot` are append-only at the
application level. Repository methods provide append and list paths only. Update
and delete paths are forbidden, and ORM flush guards raise if application code
attempts to update or delete these rows directly. Corrections must be
represented by new appended records that explain the superseding evidence,
decision rationale, or thesis-state review.
