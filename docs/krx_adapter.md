# KRX Adapter

The KRX adapter ingests selected Korean daily market data into
`MarketTimeSeries`. It is a controlled, offline-first activation step for market
data review and event detection.

## Supported MVP Scope

Supported data types:

- daily stock OHLCV
- daily ETF OHLCV when available through the same daily contract
- daily index level when represented as `MarketTimeSeries`

Not supported:

- tick data
- order book data
- intraday minute data
- broker order routing
- account or portfolio live sync
- short selling or borrow data
- derivatives data

## Symbol Config

Allowed symbols are configured in `configs/krx.symbols.example.yaml`.

```yaml
symbols:
  - symbol: "005930"
    name: Samsung Electronics
    market: KOSPI
    asset_type: stock
    currency: KRW
    theme_ids:
      - KOR_SEMI_MEMORY_UPCYCLE
    thesis_ids:
      - KOR_SEMI_MEMORY_UPCYCLE
    sector: SEMICONDUCTOR
    aliases:
      - Samsung
    krx_isu_cd: KR7005930003
```

Required fields are `symbol`, `name`, `market`, `asset_type`, and `currency`.
Optional fields include theme IDs, thesis IDs, sector, aliases, and KRX query
codes such as `krx_isu_cd` or `krx_index_code`.

Unsupported symbols and unsupported `asset_type` values raise explicit
configuration errors.

## Availability Assumption

Daily rows represent end-of-day market data. The default assumption is:

- market close is 15:30 Asia/Seoul
- daily data is safely usable from market close plus 15 minutes
- if `collected_at` is later, use `collected_at`

Therefore `available_from` is never earlier than the daily observation timestamp
or collection time.

## Dedupe

Application-level dedupe skips existing rows with the same:

- `source_id`
- `symbol`
- `timestamp`
- `frequency`

Repeated fixture or real ingestion of the same daily bars reports skipped rows
instead of inserting duplicates.

## Cache Behavior

Real responses are cached under:

```text
data/raw/krx/
```

The raw cache path is stored in `metadata_json.raw_cache_path` when available.
Downloaded raw data is not committed.

## Commands

Offline fixture ingest:

```bash
project-stock krx-doctor
project-stock ingest-krx-daily-fixture --fixture tests/fixtures/krx_daily_market_response.json --symbol 005930 --start-date 2026-06-26 --end-date 2026-06-29
```

Opt-in real preview and ingest:

```bash
PROJECT_STOCK_ALLOW_NETWORK=true project-stock fetch-krx-daily --symbol 005930 --start-date 2026-06-26 --end-date 2026-06-29
PROJECT_STOCK_ALLOW_NETWORK=true project-stock ingest-krx-daily --symbol 005930 --start-date 2026-06-26 --end-date 2026-06-29
```

## Deferred Work

Tick data, minute bars, order book data, borrow/short-selling data, derivatives,
and live broker/account integration are intentionally deferred because they have
different latency, licensing, and operational risk controls.

## Boundary

KRX market data is used for market event detection, evidence generation, and
human review. It must not create broker orders, auto-trading actions, live
buy/sell instructions, or LLM-directed investment decisions.
