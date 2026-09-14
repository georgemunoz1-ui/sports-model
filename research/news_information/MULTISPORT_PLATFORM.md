# Shared multi-sport information-state platform

PR #18 keeps one common evidence pipeline and adds league-specific contracts for MLB, NFL, NBA,
WNBA, NHL, CFB and MLS.

## Boundary

The shared layer performs immutable capture, PIT chronology, extraction, claim verification, entity
resolution and conflict preservation. It does **not** decide how many runs, points, goals or win
probability a claim is worth.

League transforms emit only structured shadow state:

```text
fact -> league-specific information state -> research feature store
```

They do not emit coefficients, probability deltas, expected-run deltas, expected-goal deltas, market
fields or action signals.

## Versioned taxonomies

- `sports_event_taxonomy.v1`
- `mlb_event_taxonomy.v1`
- `football_event_taxonomy.v1`
- `basketball_event_taxonomy.v1`
- `hockey_event_taxonomy.v1`
- `soccer_event_taxonomy.v1`

`validate_information_event()` now validates an event type against both the common vocabulary and the
league family. For example, `STARTER_PITCH_LIMIT` is valid for MLB but not NFL; `QB_OUT` is valid for
NFL/CFB but not MLB.

## Official-source coverage contracts

Each league has a source profile with required and optional official anchor kinds. Captures are
separate from claims: a successfully archived official injury report may contain no injury claim and
still counts as source coverage.

Tier behavior remains:

```text
Tier 1 official        -> candidate structured evidence after parsing/identity/PIT checks
Tier 2 beat reporter   -> research; corroboration required initially
Tier 3 news outlet     -> research corroboration
Tier 4-5               -> discovery/archive only
Tier 6                 -> excluded
market-facing source   -> excluded from information-state evidence
```

The adapters operate over already captured immutable bytes. Concrete remote endpoint retrieval and
provider-specific parsing must be separately bound and tested; no unofficial endpoint is invented by
this layer.

## First shadow targets

| League | First research target |
|---|---|
| MLB | expected team runs and pitcher/bullpen run-prevention state |
| NFL | QB and position-group availability state |
| NBA | player-minute availability and lineup net-rating state |
| WNBA | player-minute and lineup-strength state, separately calibrated |
| NHL | goaltender availability and expected-goals state |
| CFB | team-strength uncertainty and QB/position-group state |
| MLS | attack/defense lineup state and uncertainty |

These names describe the future research target. Current transforms are
`UNVALIDATED_SHADOW_STATE_ONLY`.

## Full-slate diagnostics

`build_full_slate_diagnostics()` emits one row for every supplied scheduled game. News/source coverage
never silently filters a game. Missing official anchors appear as `LOW`/`MEDIUM` completeness. An
explicit event-identity failure is `BLOCKED`/`INVALID`.

## Benchmarking

`score_multisport_extraction()` reports global metrics only for context and always includes
league-stratified and event-type metrics plus destructive false positives per league. Global F1 alone
cannot authorize promotion.

## Governance

```text
RAW_SOCIAL_SENTIMENT           = NOT_DIRECT_FORECAST_INPUT
UNVERIFIED_BEAT_REPORT_CLAIM   = RESEARCH_ONLY
TIER_1_OFFICIAL_FACT           = CANDIDATE_STRUCTURED_INPUT
TIER_2_CLAIM                   = REQUIRE_CORROBORATION_INITIALLY
MARKET_INPUT                   = FORBIDDEN
MARKET_OVERLAY                 = OFF
ACTION_AUTHORITY               = OFF
```
