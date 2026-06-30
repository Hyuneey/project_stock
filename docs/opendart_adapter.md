# OpenDART Disclosure Adapter

The OpenDART adapter activates real disclosure-list ingestion in a small,
controlled scope. It converts OpenDART disclosure list rows into `RawDocument`
records for downstream event normalization and evidence generation.

This adapter is decision support only. It does not execute broker orders,
auto-trade, generate live buy/sell orders, or delegate investment decisions to
an LLM.

## API Key Setup

Set one of these environment variables directly or in `.env`:

```bash
DART_API_KEY=your_key
# or
OPEN_DART_API_KEY=your_key
```

Secrets must not be hardcoded or committed.

## Network Opt-In

Network access is disabled by default:

```bash
PROJECT_STOCK_ALLOW_NETWORK=false
```

Real OpenDART fetches run only when explicitly enabled:

```bash
PROJECT_STOCK_ALLOW_NETWORK=true
```

Fixture ingestion does not require network access or an API key.

## Doctor Command

`opendart-doctor` performs no network calls:

```bash
project-stock opendart-doctor
```

It prints the DB URL, network flag, whether `DART_API_KEY` or
`OPEN_DART_API_KEY` is set, corp-code config status, raw cache directory, and
the no-auto-trade warning.

## Supported Scope

This PR supports OpenDART disclosure list fetch only:

- `corp_code`
- `stock_code` when mapped through corp-code config
- `bgn_de`
- `end_de`
- `page_no`
- `page_count`
- `pblntf_ty`
- `last_reprt_at`

It intentionally does not implement full report body download, XBRL parsing, or
financial statement extraction. Those require separate source-specific parsing,
availability, and revision controls.

## Corp-Code Config

Use `configs/opendart.corp_codes.example.yaml` as the format:

```yaml
companies:
  - corp_code: "00126380"
    stock_code: "005930"
    corp_name: Samsung Electronics
    market: KOSPI
    aliases:
      - Samsung
      - Samsung Electronics Co., Ltd.
```

Pass a private mapping with `--corp-code-config`.

## Commands

Preview normalized `RawDocument` records without inserting:

```bash
project-stock fetch-opendart-disclosures --stock-code 005930 --bgn-de 20260601 --end-de 20260630
```

Fetch and insert rows:

```bash
project-stock ingest-opendart-disclosures --stock-code 005930 --bgn-de 20260601 --end-de 20260630
```

Run fixture-backed ingestion without network/API keys:

```bash
project-stock ingest-opendart-disclosures-fixture --fixture tests/fixtures/opendart_disclosure_list_response.json
```

## RawDocument Mapping

Each disclosure list row maps to `RawDocument`:

- `source_id`: `OPEN_DART`
- `title`: `report_nm`
- `body_text`: deterministic summary from company, stock code, report name,
  receipt number, receipt date, filer, corp class, and remarks
- `published_at`: parsed from `rcept_dt` with a conservative default market
  close time when only a date is available
- `collected_at`: adapter fetch or fixture parse time
- `available_from`: no earlier than both `published_at` and `collected_at`
- `metadata_json`: `rcept_no`, `corp_cls`, `corp_code`, `corp_name`,
  `stock_code`, `report_nm`, `rcept_dt`, `flr_nm`, `rm`, source, and raw cache
  path when available

## Dedupe

Real and fixture-ingested disclosures set `checksum` to
`opendart:<rcept_no>`. Ingestion skips rows with an existing checksum for
`OPEN_DART`.

## Cache Behavior

Real fetches save raw JSON under:

```text
data/raw/opendart/
```

The filename includes the query prefix and a UTC timestamp. Downloaded data is
ignored by Git. The raw cache path is stored on `RawDocument.raw_path` and in
`metadata_json["raw_cache_path"]`.

Use `--no-cache-raw` to skip writing raw response JSON.

## Point-In-Time Handling

OpenDART list rows provide `rcept_dt` as a date. The adapter uses a conservative
default market-close timestamp for `published_at` and applies
`safe_available_from` so downstream logic never sees an event before the parsed
receipt time or the collection time.
