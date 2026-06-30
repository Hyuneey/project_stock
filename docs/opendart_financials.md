# OpenDART Financial Statements

The OpenDART financial adapter ingests single-company financial statement line
items for selected companies and periods. It is a controlled real-data
activation step after the offline MVP.

## Supported Scope

Supported inputs:

- `corp_code`
- `stock_code` when mapped to `corp_code`
- `bsns_year`
- `reprt_code`

Supported report codes:

- `11013`: 1Q
- `11012`: half-year
- `11014`: 3Q
- `11011`: annual

Unsupported in this scope:

- XBRL download
- Full report body parsing
- Consolidated footnote parsing
- Production multi-company batch jobs
- Investment decision logic

## Data Model

Rows are stored in `FinancialStatementLineItem`, not
`IndicatorObservation`, because the records are company-period-account data.

Fields include `statement_id`, `corp_code`, `stock_code`, `bsns_year`,
`reprt_code`, `fs_div`, `sj_div`, `account_name`, `current_amount`,
`previous_amount`, `currency`, `source_id`, `collected_at`, `available_from`,
and `metadata_json`.

Metadata stores source lineage such as `rcept_no`, raw OpenDART account fields,
report code, raw cache path, and mapped summary account when available.

## Amount Parsing

The parser accepts comma-separated amounts and parenthesized negatives:

- `"100,000"` becomes `100000`
- `"(5,000)"` becomes `-5000`
- `"-"` becomes missing and is skipped when it is the current amount

Malformed numeric strings raise an invalid-response error.

## Available From

The OpenDART financial response rows do not include an exact availability
timestamp. The MVP therefore uses `collected_at` as the conservative
`available_from`. If a future adapter links a disclosure timestamp with stronger
point-in-time evidence, that rule must remain documented and must never make
`available_from` earlier than a safe source availability time.

## Dedupe

Line items are deduped by:

- `corp_code`
- `bsns_year`
- `reprt_code`
- `fs_div`
- `sj_div`
- `account_name`

Repeated fixture or real ingestion of the same company-period-account skips
existing line items.

## Event Bridge

`normalize-financial-events` creates deterministic events only for MVP summary
accounts:

- revenue / `매출액`
- operating income / `영업이익`
- net income / `당기순이익`
- total assets / `자산총계`
- total liabilities / `부채총계`
- equity / `자본총계`

Possible event types include `financial_statement_received`,
`revenue_growth_candidate`, `operating_income_growth_candidate`,
`margin_pressure_candidate`, and `leverage_change_candidate`.

## Commands

Offline fixture ingest:

```bash
project-stock ingest-opendart-financials-fixture --fixture tests/fixtures/opendart_financial_statement_response.json --stock-code 005930 --bsns-year 2026 --reprt-code 11013
```

Opt-in real preview and ingest:

```bash
PROJECT_STOCK_ALLOW_NETWORK=true DART_API_KEY=... project-stock fetch-opendart-financials --stock-code 005930 --bsns-year 2026 --reprt-code 11013
PROJECT_STOCK_ALLOW_NETWORK=true DART_API_KEY=... project-stock ingest-opendart-financials --stock-code 005930 --bsns-year 2026 --reprt-code 11013
```

## Boundary

The adapter produces stored line items, normalized events, and evidence inputs
for human review. It does not implement broker execution, auto-trading, live
buy/sell orders, or LLM investment decision logic.
