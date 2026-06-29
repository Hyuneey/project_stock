# Data Contracts

## Core Tables

- `Source`: source metadata and default reliability.
- `RawDocument`: collected text with `published_at`, `collected_at`, and
  `available_from`.
- `MarketTimeSeries`: market observations with `timestamp`, `collected_at`, and
  `available_from`.
- `IndicatorObservation`: macro or fundamental releases with `release_at`,
  `available_from`, and optional vintage fields.
- `Event`: normalized event with scores for reliability, surprise, persistence,
  and market confirmation.
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
