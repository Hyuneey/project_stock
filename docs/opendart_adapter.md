# OpenDART Adapter

OpenDART support is intentionally scoped for offline-first decision support. It
currently covers disclosure-list ingestion and selected single-company financial
statement ingestion.

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

## Disclosure List Scope

The disclosure adapter supports OpenDART disclosure list fetch only:

- `corp_code`
- `stock_code` when mapped through corp-code config
- `bgn_de`
- `end_de`
- `page_no`
- `page_count`
- `pblntf_ty`
- `last_reprt_at`

It intentionally does not implement full report body download or XBRL parsing.

## Financial Statement Scope

The financial adapter uses the OpenDART single-company financial statement
endpoint. Required query inputs are:

- `corp_code` or a `stock_code` that resolves through
  `configs/opendart.corp_codes.example.yaml`
- `bsns_year`
- `reprt_code`

Supported `reprt_code` values:

- `11013`: 1Q
- `11012`: half-year
- `11014`: 3Q
- `11011`: annual

Financial statement rows map to `FinancialStatementLineItem`. Selected summary
accounts can be normalized into `Event` and `EventEntity` rows for evidence
generation.

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

Pass a private mapping with `--corp-code-config`. The adapter can resolve by
`corp_code` or by configured `stock_code`. Missing stock-code mappings raise a
clear configuration error.

## Commands

Preview normalized disclosure `RawDocument` records without inserting:

```bash
project-stock fetch-opendart-disclosures --stock-code 005930 --bgn-de 20260601 --end-de 20260630
```

Fetch and insert disclosure rows:

```bash
project-stock ingest-opendart-disclosures --stock-code 005930 --bgn-de 20260601 --end-de 20260630
```

Run disclosure fixture-backed ingestion without network/API keys:

```bash
project-stock ingest-opendart-disclosures-fixture --fixture tests/fixtures/opendart_disclosure_list_response.json
```

Run financial fixture-backed ingestion without network/API keys:

```bash
project-stock ingest-opendart-financials-fixture --fixture tests/fixtures/opendart_financial_statement_response.json --stock-code 005930 --bsns-year 2026 --reprt-code 11013
```

Normalize financial summary account events:

```bash
project-stock normalize-financial-events
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

Financial line items dedupe by company, year, report code, financial statement
division, statement division, and account name.

## Cache And Availability

Disclosure list fetches save raw JSON under:

```text
data/raw/opendart/
```

Financial statement fetches save raw JSON under:

```text
data/raw/opendart/financial/
```

Downloaded data is ignored by Git. Raw cache paths are stored in metadata when
available. Use `--no-cache-raw` to skip writing raw response JSON where
supported.

OpenDART list rows provide `rcept_dt` as a date. The adapter uses a conservative
default market-close timestamp for `published_at` and applies
`safe_available_from` so downstream logic never sees an event before the parsed
receipt time or the collection time.

Financial API rows do not include an exact release timestamp, so
`available_from` is set no earlier than `collected_at`.

## Deferred Work

This adapter does not implement XBRL download, full report body parsing,
consolidated footnote parsing, or production multi-company batch jobs. Those
require separate point-in-time controls and parser validation.

## Boundary

OpenDART data is used for human review, evidence generation, and memo context.
It must not create broker orders, auto-trading actions, live buy/sell
instructions, or LLM-directed investment decisions.
