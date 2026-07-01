# Thesis Lifecycle

The thesis lifecycle layer converts accumulated `EvidenceLedger` rows into
append-only `ThesisStateSnapshot` recommendations. It is deterministic decision
support only and never creates broker orders, auto-trades, or LLM-directed
buy/sell decisions.

## Supported States

- `candidate`
- `watch`
- `active`
- `core_overweight`
- `crowded`
- `deteriorating`
- `suspended`
- `invalidated`
- `archived`

`invalidated` is not automatically archived. `archived` is created only by the
explicit `archive-thesis` command.

## Evidence Aggregation Formula

Evidence is grouped by `thesis_id`. Each row contributes by stance:

- `supports`: adds `strength_score * recency_weight` to `support_score`.
- `contradicts`: adds `strength_score * recency_weight` to
  `contradiction_score`.
- `neutral`: adds `strength_score * recency_weight * 0.35` to `neutral_score`.

Recency weights are deterministic:

- 0 to 7 days: `1.15`
- 8 to 30 days: `1.00`
- 31 to 90 days: `0.85`
- Older than 90 days: `0.70`

`net_evidence_score = support_score - contradiction_score`.
`risk_score = contradiction_score + invalidation warning penalty`.

## Transition Rules

Default MVP rules are:

- `candidate -> watch` when minimum evidence is present and net evidence is
  mildly positive.
- `watch -> active` when support is strong and contradiction is low.
- `active -> core_overweight` when support is very strong, risk is low, and an
  optional Big Flow score is high.
- `active -> crowded` when support is strong but risk or crowding is high.
- `active/watch -> deteriorating` when contradiction score rises above the
  deterioration threshold.
- `deteriorating -> suspended` when contradiction persists.
- `deteriorating/suspended -> invalidated` when contradiction is very high or
  multiple invalidation conditions are matched.
- `invalidated -> archived` only through explicit archive command.

All state changes are recommendations for human review.

## Invalidation Handling

The evaluator reads `invalidation_conditions` from thesis YAML. It matches
condition keywords against evidence claims, evidence type, source event type,
and source event metadata. Matching invalidation evidence raises risk and can
propose `deteriorating`, `suspended`, or `invalidated` depending on severity and
contradiction score.

No LLM is used for invalidation checks.

## Snapshot and Idempotency Policy

`ThesisStateSnapshot` is append-only. A lifecycle run can append one snapshot
per thesis. Snapshot metadata includes:

- evidence IDs
- support, contradiction, neutral, net, risk, and confidence scores
- transition reasons
- recommended review action
- invalidation warnings
- `no_auto_trade`
- deterministic evaluation fingerprint

Repeated evaluation with the same `as_of` and identical evidence/scoring
fingerprint skips duplicate snapshots unless `--force` is used.

## Archive Policy

Archiving is explicit. `archive-thesis` appends an `archived` snapshot with the
provided reason. It does not mutate prior snapshots. Repeating the same archive
command for the same `as_of` skips the duplicate unless `--force` is used.

## KOR_SEMI v2 Pack

`KOR_SEMI_MEMORY_UPCYCLE_v2.0.yaml` adds explicit source mappings, supporting
and contradicting evidence types, and review cadence. The
`run-kor-semi-thesis-pack-demo` command runs the fixture-backed real-data smoke
chain, matches KOR_SEMI v2 scenarios, executes review-only playbooks, scores the
KOR_SEMI Big Flow fixture, and evaluates a ThesisStateSnapshot.

The Big Flow fixture uses descriptive components:

- `secular_tailwind`
- `industry_cycle`
- `earnings_revision`
- `valuation_sanity`
- `price_confirmation`
- `macro_fit`
- `risk_penalty`

The scorer maps these to the existing deterministic Big Flow components before
snapshot evaluation. No thesis state is a trade instruction.

## Boundary

Lifecycle outputs are thesis state recommendations, snapshot audit rows, and
markdown memos. Portfolio actions remain human-reviewed and outside the system.
