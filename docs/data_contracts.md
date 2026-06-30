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

`EvidenceLedger` and `DecisionLog` are append-only at the application level.
Repository methods provide append and list paths only. Update and delete paths
are forbidden, and ORM flush guards raise if application code attempts to update
or delete these rows directly. Corrections must be represented by new appended
records that explain the superseding evidence or decision rationale.
