# Real Data Activation

This layer activates opt-in real-data adapters after the v0.1.0 MVP baseline.
The default project mode remains offline, deterministic, and fixture-driven.

The system remains decision support only: no broker execution, no auto-trading,
no live buy/sell orders, and no LLM-directed investment decisions.

## Environment Variables

Copy `.env.example` to `.env` or set environment variables directly:

```bash
PROJECT_STOCK_ALLOW_NETWORK=false
FRED_API_KEY=
ECOS_API_KEY=
DART_API_KEY=
OPEN_DART_API_KEY=
```

`PROJECT_STOCK_ALLOW_NETWORK` defaults to `false`. Set it to `true` only for an
intentional real API fetch:

```bash
PROJECT_STOCK_ALLOW_NETWORK=true
FRED_API_KEY=your_fred_key
ECOS_API_KEY=your_ecos_key
DART_API_KEY=your_opendart_key
```

API keys are read only from the environment or `.env`. They must not be
hardcoded or committed.

## Doctor Commands

`real-data-doctor` performs no network calls:

```bash
project-stock real-data-doctor
```

It prints the DB URL, network flag, whether `FRED_API_KEY` and `ECOS_API_KEY`
are set, raw cache directories, supported FRED series, configured ECOS series,
a point-in-time caution, and the no-auto-trade warning.

`opendart-doctor` also performs no network calls:

```bash
project-stock opendart-doctor
```

It prints the network flag, whether `DART_API_KEY` or `OPEN_DART_API_KEY` is
set, corp-code config status, OpenDART raw cache location, and the no-auto-trade
warning.

## Supported FRED Series

The MVP allowlist is:

- `DGS10`: 10-Year Treasury Constant Maturity Rate
- `DGS2`: 2-Year Treasury Constant Maturity Rate
- `VIXCLS`: CBOE Volatility Index
- `FEDFUNDS`: Effective Federal Funds Rate

Fetch without inserting:

```bash
project-stock fetch-fred-series --series-id DGS10 --start-date 2026-06-01 --end-date 2026-06-30
```

Fetch and insert `IndicatorObservation` rows:

```bash
project-stock ingest-fred-series --series-id DGS10 --start-date 2026-06-01 --end-date 2026-06-30
```

Both commands fail clearly if network is disabled, the API key is missing, the
response is invalid, or the series is unsupported.

## ECOS Series Config

ECOS uses a configurable series map. See `configs/ecos.series.example.yaml`.

```yaml
series:
  - indicator_id: ECOS_BASE_RATE
    stat_code: "722Y001"
    item_code1: "0101000"
    item_code2:
    item_code3:
    frequency: D
    unit: percent
    description: Bank of Korea base rate
```

Fetch without inserting:

```bash
project-stock fetch-ecos-series --indicator-id ECOS_BASE_RATE --start-date 2026-06-01 --end-date 2026-06-30
```

Fetch and insert:

```bash
project-stock ingest-ecos-series --indicator-id ECOS_BASE_RATE --start-date 2026-06-01 --end-date 2026-06-30
```

Use `--series-config` to point to a private config file.

## OpenDART Disclosure List

OpenDART disclosure list ingestion uses `DART_API_KEY` or `OPEN_DART_API_KEY`.
The scope is disclosure list metadata only. Full report body download and XBRL
parsing are deferred.

Fixture ingestion remains offline:

```bash
project-stock ingest-opendart-disclosures-fixture --fixture tests/fixtures/opendart_disclosure_list_response.json
```

Real preview and ingestion are available only after explicit network opt-in:

```bash
project-stock fetch-opendart-disclosures --stock-code 005930 --bgn-de 20260601 --end-de 20260630
project-stock ingest-opendart-disclosures --stock-code 005930 --bgn-de 20260601 --end-de 20260630
```

## OpenDART Financial Statements

The financial adapter supports single-company financial statement rows for
selected companies and report periods.

Fixture ingestion remains offline:

```bash
project-stock ingest-opendart-financials-fixture --fixture tests/fixtures/opendart_financial_statement_response.json --stock-code 005930 --bsns-year 2026 --reprt-code 11013
```

Real preview and ingestion are available only after explicit network opt-in:

```bash
project-stock fetch-opendart-financials --stock-code 005930 --bsns-year 2026 --reprt-code 11013
project-stock ingest-opendart-financials --stock-code 005930 --bsns-year 2026 --reprt-code 11013
```

Supported report codes are `11013`, `11012`, `11014`, and `11011`. The adapter
does not download XBRL, parse full report bodies, parse consolidated footnotes,
or run production multi-company batch jobs.

See `docs/opendart_adapter.md` and `docs/opendart_financials.md` for scope,
corp-code config, cache behavior, available-from handling, and deferred work.

## Raw Response Cache

Real fetches save raw JSON by default:

- FRED: `data/raw/fred/`
- ECOS: `data/raw/ecos/`
- OpenDART disclosure list: `data/raw/opendart/`
- OpenDART financial statements: `data/raw/opendart/financial/`

Downloaded data remains ignored by Git through `data/raw/*`. Cache paths are
stored in `metadata_json["raw_cache_path"]` when available.

Use `--no-cache-raw` to skip writing raw response JSON where supported.

## Point-In-Time Limitations

The MVP records `available_from` no earlier than source release metadata and the
local collection time. This is conservative for downstream review and
backtesting, but it is not a full vintage database. Before using real data for
research, verify source-specific release calendars, publication lags, revisions,
and vintage behavior.

OpenDART financial statement rows do not include exact API release timestamps in
the MVP parser, so `available_from` is set no earlier than local collection time.

## Offline Tests

The test suite uses fixture parsers for FRED observation responses, ECOS
StatisticSearch responses, OpenDART disclosure list responses, and OpenDART
financial statement responses. It does not require network access or real API
keys.

The real adapter boundary is tested with:

- network disabled fetch rejection
- missing API key rejection
- fixture parser validation
- fixture-backed CLI ingestion
- raw cache path generation
- `available_from` safety

## Boundary

Real data activation only changes source collection. It must not create broker
orders, auto-trading actions, live buy/sell instructions, or LLM-directed
investment decisions.
