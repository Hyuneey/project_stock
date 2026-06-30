# Data Sources

## OpenDART

OpenDART is the planned official source for Korean corporate disclosure text.
The MVP implements a fixture-based collector interface that maps disclosure
records to `RawDocument`. Real API fetching is intentionally not implemented in
this PR; future work must read `DART_API_KEY` from the environment and keep tests
offline.

## ECOS

Bank of Korea ECOS is the source for Korean macro indicators. The offline mock
collector maps fixture records to `IndicatorObservation`; the real adapter can
fetch ECOS StatisticSearch data only when `PROJECT_STOCK_ALLOW_NETWORK=true` and
`ECOS_API_KEY` is set. Supported indicators are configured in
`configs/ecos.series.example.yaml` or a private file passed with
`--series-config`.

## FRED and Future ALFRED

FRED is the source for US and global macro indicators. The offline mock
collector supports an optional `vintage_date` field and stores ALFRED-readiness
metadata. The real adapter supports an MVP allowlist: `DGS10`, `DGS2`,
`VIXCLS`, and `FEDFUNDS`. Real fetches run only when
`PROJECT_STOCK_ALLOW_NETWORK=true` and `FRED_API_KEY` is set.

Real FRED and ECOS fetches cache raw JSON under `data/raw/fred/` and
`data/raw/ecos/` by default. Cache paths are stored in indicator metadata when
available. Downloaded data is ignored by Git.

## KRX

KRX is the planned source for Korean market price and trading data. The MVP mock
collector maps fixture rows to `MarketTimeSeries` with OHLCV, traded value,
frequency, adjustment flag, `collected_at`, and `available_from`.

## News/RSS

News/RSS is mock-only in the MVP. It maps fixture items to `RawDocument` and
dedupes by checksum. News reliability is lower by default because source quality,
publisher identity, and syndication duplication require additional controls
before real ingestion.

## Event Normalization

Collected records are normalized into `Event` and `EventEntity` rows after
ingestion. OpenDART and News/RSS records normalize from `RawDocument`; ECOS and
FRED records normalize from `IndicatorObservation`; KRX records normalize from
`MarketTimeSeries` when a previous observation exists for move detection. The
normalization layer preserves source lineage in event metadata and carries
forward safe `available_from` timestamps.

## Guardrails

Collectors prepare data for decision support only. They do not execute broker
orders, do not auto-trade, and do not let LLMs make investment decisions. Tests
must remain deterministic, offline, and free of required API keys. Real fetches
must be explicitly enabled with `PROJECT_STOCK_ALLOW_NETWORK=true`.
