# Fee-aware contract decision research

Implemented November 3, 2026 Pacific / November 4 UTC from owner-supplied
specifications. This is an isolated downstream research package. Existing model
code, selected defaults, forecasts, the shared card runner and accuracy-first
ranking are unchanged. Price/EV never increases a confidence ranking.

The two described implementation ZIPs were not available. This is **new code**,
not an import of the reported 51-test core or 28-test extension. Four attached
design/test documents were inspected. Exact reported test counts are not
reproduced or added to the counts below.

## Implemented and exercised

| Component | Scope and evidence |
|---|---|
| Decision core | Strict Decimal/string/integer inputs, real booleans, ordered gates, all findings retained, strict total-EV buffer comparison |
| Fees | Simple and marginal-tier maker/taker schedules; whole quantities; order-level minimum and upward rounding; separate alternative schedules |
| Deterministic spread comparisons | Half-point binary $1-payout contracts; selected-team/opponent-margin orientation; every payoff region including both tails; signed favorite lines |
| Joint-scenario parlay valuation | Supplied scenarios only, no marginal independence assumption; explicit reject/refund/remove-leg rules; surviving-index payouts; loss-dominant policy |
| SQLite | Actual file-backed transactions, concurrent writers, rollback, idempotency with evaluator identity, input hashes, append-only guards, audit chain and exported checkpoint |
| Evidence sidecar | Pins contract, quote, game state, model, rules, fee schedule and configuration bytes; checks declared identity/team/period/currency, pregame chronology and freshness; retains actual code/runtime receipt |

297 new focused engineering tests passed, independently reproduced. These include
55 independent adversarial checks, 34 real SQLite checks and 4 **static-only**
PostgreSQL migration checks. Counts overlap the module totals; do not add them.
These tests do not establish predictive validation, authentic venue data or
production database behavior.

Independent review caught and closed near-half-point decimal rounding,
post-cutoff state acceptance, a SQLite NULL authority constraint gap and a
decision/persistence serialization mismatch. Supplied earlier snippets also had
negative-line orientation, invalid-price and string-boolean defects; the new
implementation has explicit regressions.

## Decision and authority boundary

`models/common/decision_research/engine.py:decide_payload` is a **pure engineering
core**. Its supplied boolean assertions are not operational evidence. It applies:

1. Invalid input and identity/settlement/state/freshness/market-open gates.
2. Verified-executable-alternative dominance, then execution/size/fee gates.
3. Qualified valuation, strictly positive excess above the required EV buffer,
   risk constraints and authority gate.

It can return `QUALIFIED_CANDIDATE` for an all-true engineering fixture, while
still reporting `production_eligible:false`, `order_authorized:false` and
`qualification_source:CALLER_ASSERTIONS_UNVERIFIED`. Never call this an operational
candidate. The package exposes no order API.

The evidence-facing CLI does **not** accept those gate booleans. It derives
declared consistency from hash-pinned objects and always withholds venue-rule,
quote-execution, fee-authenticity and forecast-qualification approval because no
trusted authority adapters are configured. Thus its current output remains
`BLOCKED`, with exact findings. Hash-matching caller bytes cannot grant trust.
This validator is a partial compatibility layer, not completed provider
reconciliation or a production selection service.

All outputs keep Action OFF, dose 0 and ordering disabled. The package neither
changes the user's accuracy-first selector nor ranks events by EV. Historical
forecast labels and parameters remain untouched.

## Local use

Use the repository's configured test Python:

```bash
python -m pytest -q tests/test_decision_research_*.py
python scripts/run_contract_decision_research.py --help
python scripts/run_contract_decision_research.py \
  --request /absolute/request.json \
  --evidence-root /absolute/evidence \
  --output /absolute/new-output
```

The request contains only `comparison_id`, whole `quantity`, and `evidence`.
Evidence has exactly seven keys: `contract`, `quote`, `state`, `model`, `rules`,
`fee_schedule`, `configuration`; each references a relative path and SHA-256.
See `tests/test_decision_research_compatibility.py:make_fixture` for the complete
**synthetic** schema. It covers the seven league names without granting any
league/product support or inferring venue rules.

The CLI refuses an existing output directory. A successfully audited blocked
decision exits 2 and writes the reason, immutable source copies, request,
SQLite audit database, external-checkpoint candidate, observed checkout/dirty
status, exact source hashes, actual writer timestamps and a file manifest.
The checkpoint must be independently retained to detect later truncation; its
presence beside a database is not administrator-proof retention. Crashes or
persistence/copy failures leave an incomplete run, not a successful receipt.

## Money and settlement

For binary $1 gross-payout contracts, net expected return per contract is
`expected_payout - price - total_order_fee / quantity`. Fees are calculated for
the whole order before division. The buffer gate compares total amounts before
display division, avoiding repeating-decimal boundary drift. Equality passes on
the opportunity rather than qualifying it.

Fee rates, minima, tiers and venue identifiers in fixtures are illustrative.
Prior tier volume is supplied by the caller; there is no account-wide lock,
rebate support, reset scheduler or authenticated fee lookup. The evidence
validator checks a declared effective window but does not authenticate it.

Mathematical dominance is distinct from quote compatibility and absolute value.
It requires no worse net payoff in every outcome region and better payoff in at
least one. Unsupported integer or quarter-point binary spreads refuse; existing
sportsbook push/quarter-line adapters are not silently imported into binary
$1 contracts. A pregame model is never relabeled as live.

Parlays require a complete supplied joint law. Refunds do not refund entry fees.
REMOVE_LEG requires a payout for each encountered surviving-index set, including
an explicit empty set for all-push/void scenarios. Half-wins/losses, cash-out,
automatic correlated scenario generation and parlay eligibility selection are
not implemented. Input probabilities and venue rules remain unverified.

## Persistence and remaining work

SQLite owns each write transaction and refuses an active caller transaction.
Its append-only triggers reject UPDATE, DELETE and conflicting INSERT OR REPLACE.
Evaluations validate input hashes and the existing audit chain, bind an evaluator
identity, and atomically append or reuse the exact idempotent result. Failures
propagate. Logging emits `decision_recorded` and `decision_failed`; host logging
configuration is separate. An administrator can still remove triggers or rewrite
the complete store; external checkpoints and permissions are required.

`models/common/decision_research/sql/001_postgresql_candidate.sql` is a separate
undeployed candidate, **not a PostgreSQL adapter or a migration applied to an
established production schema**. PostgreSQL execution is NOT-RUN: server binaries,
driver and production schema/session conventions were unavailable. Static tests
are not substitutes for transaction, migration, concurrency or permissions tests.

Before shared-card integration, establish trusted exact-contract/source adapters,
verified venue rule/fee versions, production schema and transaction ownership,
PostgreSQL runtime tests, authenticated size/state inputs, and a bound predictive
qualification registry. Integrate partial settlements only under their existing
product-specific contracts. No authority or model promotion follows from this PR.

## Benchmark scope

`scripts/benchmark_contract_decision_research.py` runs synthetic local timing for
1,000/10,000 pure decisions and 100 SQLite WAL decisions with distinct comparison
IDs. It records median/p95 latency and audit count. Pure timing includes validation
and decision gates but uses a prepared fee; it excludes fee lookup/calculation,
quote acquisition and compatibility. SQLite rechecks the full chain before each
append. Results are single-environment observations, not production capacity.

Global repository health remains RED for pre-existing release/recovery/source
issues and the default Python's missing pytest; the separately configured test
runtime executes this suite. No health, release, grading or action gate is waived.
