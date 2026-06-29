# Event Taxonomy

Events are deterministic decision-support records. They are not broker orders,
auto-trading instructions, or LLM investment decisions.

| event_type | Description | Source table | Expected fields | Entity mapping | Example scenario usage |
| --- | --- | --- | --- | --- | --- |
| `disclosure_received` | OpenDART disclosure received without a stronger subtype. | `raw_documents` | `doc_id`, `published_at`, `available_from`, `report_name` | company, country | Evidence that a company filing exists for review. |
| `earnings_guidance` | Disclosure text references guidance, forecast, or outlook. | `raw_documents` | disclosure metadata, summary text | company, sector, theme | Triggers closer earnings thesis review. |
| `earnings_revision_candidate` | Disclosure suggests EPS or profit revision risk. | `raw_documents` | disclosure metadata, summary text | company, sector, theme | Feeds earnings shock scenario checks. |
| `corporate_action_candidate` | Disclosure references dividend, buyback, split, or merger. | `raw_documents` | disclosure metadata, summary text | company | Supports corporate action watch items. |
| `risk_disclosure_candidate` | Disclosure references litigation, risk, uncertainty, or going-concern language. | `raw_documents` | disclosure metadata, summary text | company, sector | Raises qualitative risk review. |
| `macro_policy_headline` | News/RSS headline references policy, Fed, rates, or inflation. | `raw_documents` | checksum, published_at, available_from | macro_factor, country | Supports macro rate shock monitoring. |
| `geopolitical_risk_headline` | News/RSS headline references war, sanctions, oil, or geopolitical risk. | `raw_documents` | checksum, published_at, available_from | macro_factor, country | Supports geopolitical or energy shock scenarios. |
| `sector_news_headline` | News/RSS headline references semiconductors, memory, HBM, or sector news. | `raw_documents` | checksum, published_at, available_from | sector, theme | Feeds semiconductor theme evidence. |
| `company_news_headline` | News/RSS headline references Samsung Electronics, SK Hynix, or stock codes. | `raw_documents` | checksum, published_at, available_from | company | Supports company-specific event review. |
| `unclassified_news` | News/RSS item did not match MVP rules. | `raw_documents` | checksum, published_at, available_from | best-effort mappings | Stored for review without scenario activation by default. |
| `macro_indicator_release` | Macro indicator released without surprise data. | `indicator_observations` | indicator_id, period, value, release_at, available_from | macro_factor, country | Neutral macro evidence. |
| `macro_surprise_positive` | Indicator surprise z-score is positive and material. | `indicator_observations` | surprise_z, consensus, previous | macro_factor, country | Positive or tightening-growth evidence depending indicator. |
| `macro_surprise_negative` | Indicator surprise z-score is negative and material. | `indicator_observations` | surprise_z, consensus, previous | macro_factor, country | Negative growth or easing-risk evidence depending indicator. |
| `inflation_surprise` | Inflation-linked indicator released with surprise context. | `indicator_observations` | surprise_z, consensus, previous | macro_factor, country | Feeds rate-policy risk scenarios. |
| `growth_surprise` | Growth-linked indicator released with surprise context. | `indicator_observations` | surprise_z, consensus, previous | macro_factor, country | Feeds cycle and earnings scenarios. |
| `rate_policy_relevant` | Rate/yield indicator release relevant to policy and discount rates. | `indicator_observations` | release_at, value, available_from | macro_factor, country | Supports rate shock and valuation pressure scenarios. |
| `market_large_move` | Asset moved beyond generic configured threshold versus previous observation. | `market_time_series` | symbol, timestamp, previous value, current value, pct_move | asset or company | Confirms market stress or momentum. |
| `fx_stress_move` | USDKRW moved beyond configured FX threshold. | `market_time_series` | symbol, timestamp, pct_move | asset, macro_factor | Feeds Korea FX and foreign-flow risk scenarios. |
| `rates_shock_move` | US10Y moved beyond configured absolute threshold. | `market_time_series` | symbol, timestamp, absolute_move | macro_factor | Confirms rate shock scenarios. |
| `sector_relative_strength_move` | SOX moved beyond configured semiconductor threshold. | `market_time_series` | symbol, timestamp, pct_move | asset, sector, theme | Confirms semiconductor relative strength deterioration or recovery. |
| `volatility_shock_move` | VIX moved beyond configured volatility threshold. | `market_time_series` | symbol, timestamp, pct_move | asset, macro_factor | Confirms market stress scenarios. |

## Entity Mapping Rules

The MVP uses deterministic dictionaries. Supported entity types are `theme`,
`sector`, `asset`, `company`, `macro_factor`, and `country`.

- `KOR_SEMI_MEMORY_UPCYCLE`: semiconductor memory upcycle theme.
- `AI_INFRASTRUCTURE`: AI infrastructure theme.
- `SEMICONDUCTOR`: semiconductor sector.
- `USDKRW`, `US10Y`, `SOX`, `VIX`: market assets or macro factors.
- `005930`: Samsung Electronics.
- `000660`: SK Hynix.

## Evidence Mapping Examples

Evidence generation uses the taxonomy and mapped entities to produce
thesis-linked candidates:

- `earnings_guidance` with positive guidance language for
  `KOR_SEMI_MEMORY_UPCYCLE` is supportive evidence.
- `earnings_revision_candidate` with EPS, profit, or guidance deterioration for
  `KOR_SEMI_MEMORY_UPCYCLE` is contradicting evidence and can link to
  `KOR_SEMI_EARNINGS_BEAR`.
- `disclosure_received` without directional language is neutral thesis evidence.
- `rate_policy_relevant` or `rates_shock_move` is risk-negative for high-duration
  AI or growth-sensitive theses and can link to `KOR_SEMI_RATE_SHOCK_BEAR`.
- `fx_stress_move` from a USDKRW spike is contradicting evidence for
  Korea foreign-flow-sensitive theses.
- `sector_news_headline` or `sector_relative_strength_move` tied to SOX,
  semiconductors, HBM, or AI infrastructure can support
  `KOR_SEMI_AI_DEMAND_BULL` when direction is positive.

Duplicate prevention uses source lineage first, then News/RSS checksum, then a
close timestamp/entity window for same `event_type` and mapped entity.
