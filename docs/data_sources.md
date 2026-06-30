# Data Sources

## OpenDART

OpenDART is the official source for Korean corporate disclosure metadata. The
MVP fixture collector maps disclosure records to `RawDocument`; the real adapter
adds opt-in disclosure list ingestion through `fetch-opendart-disclosures` and
`ingest-opendart-disclosures`.

Real OpenDART fetches run only when `PROJECT_STOCK_ALLOW_NETWORK=true` and
either `DART_API_KEY` or `OPEN_DART_API_KEY` is set. The supported real-data
scope is disclosure list rows only. Full report body download, XBRL parsing, and
financial statement extraction are intentionally deferred.

Raw OpenDART list responses are cached under `data/raw/opendart/` by default and
remain ignored by Git. Disclosure rows dedupe by `rcept_no` through the document
checksum `opendart:<rcept_no>`.

financial statement adapter supports the single-company financial statement
endpoint in a controlled scope:

- Inputs: `corp_code` or mapped `stock_code`, `bsns_year`, and `reprt_code`.
- Supported report codes: `11013` 1Q, `11012` half-year, `11014` 3Q, and
  `11011` annual.
- Storage: `FinancialStatementLineItem`, deduped by company, year, report,
  financial-statement division, statement division, and account name.
- Raw cache: real responses are written under `data/raw/opendart/financial/`
  and are ignored by git.

Real OpenDART financial fetching is opt-in only. `PROJECT_STOCK_ALLOW_NETWORK`
defaults to `false`, and real fetches require `PROJECT_STOCK_ALLOW_NETWORK=true`
plus `DART_API_KEY` or `OPEN_DART_API_KEY`. Fixture ingestion requires no API key
and no network.

The financial adapter does not download XBRL, parse full report bodies, parse
consolidated footnotes, run multi-company production batch jobs, execute broker
orders, auto-trade, or let LLMs make investment decisions.

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

KRX is the source for Korean daily market price and trading data. The MVP keeps
real fetching opt-in and controlled by `PROJECT_STOCK_ALLOW_NETWORK=false` by
default.

The KRX daily adapter supports selected configured symbols for:

- daily stock OHLCV
- daily ETF OHLCV when represented through the same daily contract
- daily index level when represented as `MarketTimeSeries`

Symbol metadata lives in `configs/krx.symbols.example.yaml`. Fixture ingestion
requires no network and no credentials. Real fetches must be explicitly enabled
with `PROJECT_STOCK_ALLOW_NETWORK=true`; optional credentials, if required by a
deployment, are read only from `KRX_AUTH_TOKEN` or `KRX_API_KEY`.

For end-of-day data, the adapter treats the market observation timestamp as the
Korea market close time and sets `available_from` to the later of market close
plus 15 minutes or `collected_at`. This keeps daily bars point-in-time safe for
reviews and backtests.

The adapter does not implement tick data, order book data, intraday minute data,
broker order routing, live account or portfolio sync, short-selling/borrow data,
or derivatives data.

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

OpenDART financial statement summary accounts can be normalized from
`FinancialStatementLineItem` into events such as `financial_statement_received`,
`revenue_growth_candidate`, `operating_income_growth_candidate`,
`margin_pressure_candidate`, and `leverage_change_candidate`. The MVP maps only
summary accounts such as revenue, operating income, net income, assets,
liabilities, and equity.

## Guardrails

Collectors prepare data for decision support only. They do not execute broker
orders, do not auto-trade, and do not let LLMs make investment decisions. Tests
must remain deterministic, offline, and free of required API keys. Real fetches
must be explicitly enabled with `PROJECT_STOCK_ALLOW_NETWORK=true`.
