# Evidence Generation

The evidence generation layer turns normalized `Event` records and their
`EventEntity` mappings into thesis-linked `EvidenceCandidate` records, then
appends deduplicated candidates to `EvidenceLedger`.

This layer is deterministic. It does not use LLMs, broker integrations, order
execution, live APIs, or paid services.

## Event to Evidence Flow

1. Load thesis YAML definitions and scenario YAML definitions.
2. Read normalized events and their mapped entities from SQLite.
3. Score each event against each thesis using entity and keyword overlap.
4. Classify the candidate stance as `supports`, `contradicts`, or `neutral`.
5. Compute bounded strength and confidence scores.
6. Attach `scenario_id` when an event type or trigger-related hint matches a
   scenario belonging to the same thesis.
7. Append candidates to `EvidenceLedger` when they are not duplicates.

## Thesis Relevance Rules

Relevance is based on deterministic overlap:

- Theme/entity overlap, such as `KOR_SEMI_MEMORY_UPCYCLE`.
- Sector overlap, such as `SEMICONDUCTOR`.
- Company or asset overlap, such as `005930`, `000660`, `SOX`, or `USDKRW`.
- Macro factor overlap, such as `US10Y`, `VIX`, inflation, rates, or growth.
- Scenario keywords and trigger-related metrics when available.

Events with no thesis match return no candidates and do not raise errors.

## Stance Rules

The MVP stance rules are transparent and event-type driven:

- `supports`: positive earnings guidance, semiconductor/AI demand headlines, or
  constructive sector relative strength for a matching thesis.
- `contradicts`: earnings deterioration, risk disclosures, rate shocks, FX
  stress, volatility shocks, or risk-negative macro pressure for matching
  growth or foreign-flow-sensitive theses.
- `neutral`: generic disclosures, neutral macro releases, or unclassified news
  without a directional signal.

## Strength Formula

`strength_score` uses a 0 to 5 scale:

```text
0.20 * source_reliability
+ 0.20 * surprise_score
+ 0.15 * persistence_score
+ 0.15 * market_confirmation_score
+ 0.20 * (relevance_score / 20)
+ 0.10 * event_type_severity
```

The result is rounded and clamped to the 0 to 5 range. `relevance_score` and
`confidence_score` use a 0 to 100 scale.

## Duplicate Rules

`EvidenceLedger` remains append-only. The generation service skips duplicate
evidence when an existing ledger row has the same:

- `event_id`
- `thesis_id`
- `scenario_id`
- `evidence_type`

Corrections should be represented by newly appended evidence with new metadata,
not by editing existing ledger rows.

## Scenario Linkage

An evidence candidate can be thesis-level only or scenario-linked. Scenario
linkage is attached when:

- the scenario belongs to the matched `thesis_id`, and
- the event type or trigger-related metadata maps to that scenario's risk or
  opportunity pattern.

Examples:

- `rate_policy_relevant` and `rates_shock_move` can link to
  `KOR_SEMI_RATE_SHOCK_BEAR`.
- `earnings_revision_candidate` can link to `KOR_SEMI_EARNINGS_BEAR`.
- `sector_news_headline` can link to `KOR_SEMI_AI_DEMAND_BULL`.

## Limitations

The MVP uses fixture-backed events and deterministic dictionaries. It is meant
to produce auditable decision-support evidence, not final investment decisions.
Future real collectors can add richer metadata, but they must preserve the same
append-only audit path and must not introduce broker execution or LLM-directed
buy/sell decisions.
