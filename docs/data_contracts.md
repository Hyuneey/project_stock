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

## YAML Contracts

Thesis, scenario, and playbook YAML files are validated with Pydantic schemas.
Scenario triggers currently support `>`, `>=`, `<`, `<=`, `==`, and `!=`.
