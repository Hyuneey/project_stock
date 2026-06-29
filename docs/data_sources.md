# Data Sources

## OpenDART

OpenDART is the planned official source for Korean corporate disclosure text.
The MVP implements a fixture-based collector interface that maps disclosure
records to `RawDocument`. Real API fetching is intentionally not implemented in
this PR; future work must read `DART_API_KEY` from the environment and keep tests
offline.

## ECOS

Bank of Korea ECOS is the planned source for Korean macro indicators. The MVP
mock collector maps fixture records to `IndicatorObservation` with `release_at`,
`collected_at`, and `available_from`.

## FRED and Future ALFRED

FRED is the planned source for US and global macro indicators. The mock collector
supports an optional `vintage_date` field and stores ALFRED-readiness metadata so
future vintage-aware ingestion can be added without changing the downstream
indicator table contract.

## KRX

KRX is the planned source for Korean market price and trading data. The MVP mock
collector maps fixture rows to `MarketTimeSeries` with OHLCV, traded value,
frequency, adjustment flag, `collected_at`, and `available_from`.

## News/RSS

News/RSS is mock-only in the MVP. It maps fixture items to `RawDocument` and
dedupes by checksum. News reliability is lower by default because source quality,
publisher identity, and syndication duplication require additional controls
before real ingestion.

## Guardrails

Collectors prepare data for decision support only. They do not execute broker
orders, do not auto-trade, and do not let LLMs make investment decisions. Tests
must remain deterministic, offline, and free of required API keys.
