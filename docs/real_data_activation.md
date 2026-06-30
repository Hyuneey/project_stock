# Real Data Activation

This layer activates real FRED and ECOS adapters after the v0.1.0 MVP baseline.
Real API calls are opt-in only. Tests and demo workflows remain offline and
deterministic.

The system remains decision support only: no broker execution, no auto-trading,
no live buy/sell orders, and no LLM-directed investment decisions.

## Environment Variables

Copy `.env.example` to `.env` or set environment variables directly:

```bash
PROJECT_STOCK_ALLOW_NETWORK=false
FRED_API_KEY=
ECOS_API_KEY=
```

`PROJECT_STOCK_ALLOW_NETWORK` defaults to `false`. Set it to `true` only for an
intentional real API fetch:

```bash
PROJECT_STOCK_ALLOW_NETWORK=true
FRED_API_KEY=your_fred_key
ECOS_API_KEY=your_ecos_key
```

API keys are read only from the environment or `.env`. They must not be
hardcoded or committed.

## Doctor Command

`real-data-doctor` performs no network calls:

```bash
project-stock real-data-doctor
```

It prints the DB URL, network flag, whether `FRED_API_KEY` and `ECOS_API_KEY`
are set, raw cache directories, supported FRED series, configured ECOS series,
a point-in-time caution, and the no-auto-trade warning.

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

## Raw Response Cache

Real fetches save raw JSON by default:

- FRED: `data/raw/fred/`
- ECOS: `data/raw/ecos/`

Downloaded data remains ignored by Git through `data/raw/*`. Cache paths are
stored in `metadata_json["raw_cache_path"]` on normalized indicator observations
when available.

Use `--no-cache-raw` to skip writing raw response JSON.

## Point-In-Time Limitations

The MVP records `available_from` no earlier than source release metadata and the
local collection time. This is conservative for downstream review and
backtesting, but it is not a full vintage database. Before using real data for
research, verify source-specific release calendars, publication lags, revisions,
and vintage behavior.

## Offline Tests

The test suite uses fixture parsers for FRED observation responses and ECOS
StatisticSearch responses. It does not require network access or real API keys.

The real adapter boundary is tested with:

- network disabled fetch rejection
- missing API key rejection
- fixture parser validation
- fixture-backed CLI ingestion
- raw cache path generation
- `available_from` safety
