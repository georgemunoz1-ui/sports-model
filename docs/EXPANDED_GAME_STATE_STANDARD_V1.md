# Expanded Game-State Forecast Standard v1

Status: repository-wide research forecast contract

Standard ID: `expanded_game_state.v1`

Version: `1.0.0`

## Operating rule

For every authoritative, valid scheduled event, the forecasting process must:

1. Generate a reproducible market-independent league baseline.
2. Attempt to bind the league's required point-in-time game-state dimensions.
3. Apply only verified inputs whose impact is defined by a separately versioned transform.
4. Emit an event-level contribution log for every non-zero adjustment.
5. Preserve the baseline forecast as a benchmark arm.
6. Emit an explicit coverage label for missing, partial, conflicting, or complete information.
7. Freeze the independent forecast before any market/valuation comparison.

A missing information adapter or unresolved enrichment does **not** suppress a valid-event forecast.
It suppresses only the unavailable enrichment.

```text
NO_INFORMATION_ADAPTER
!= NO_FORECAST

NO_INFORMATION_ADAPTER
= BASELINE_FORECAST
+ EXPLICIT_UNKNOWN_STATE
+ ZERO_UNVERIFIED_ADJUSTMENT
```

## Primary versus baseline

`BASELINE_ONLY` is the safe fallback and benchmark. The primary current **research** opinion should
use expanded game state whenever verified context and a versioned impact transform are available.
An SRS-only, Elo-only, Poisson-only, or other team-strength-only card may not be presented as the
current expanded model opinion when the required current-state inputs have been validly bound.

This standard does not promote an unvalidated impact transform. An expanded forecast can therefore
be the default research card while still carrying `SHADOW_UNVALIDATED` and `action_authority=false`.

## Required dimensions

| League | Expanded game-state dimensions |
|---|---|
| MLB | team strength; starter; lineup; bullpen; schedule/rest/workload; park/weather/roof |
| NFL | team strength; QB; availability/practice/inactives; position-group health; workload; schedule/rest/travel; weather/venue |
| CFB | team strength; QB; availability/suspension; depth chart; position-group health; schedule/rest/travel; weather/venue/neutral site |
| NBA | team strength; availability; starting lineup; minutes/workload; rest/back-to-back; travel; venue |
| WNBA | team strength; availability; starting lineup; minutes/workload; rest/back-to-back; travel; venue |
| NHL | team strength; starting goalie; scratches/availability; line combinations; rest/back-to-back; travel; venue |
| MLS | team strength; starting XI; goalkeeper; injury/suspension/international duty; fixture congestion; travel; weather/venue |

The executable dimension registry is `models/common/expanded_game_state_standard_v1.py`.

## Information states

Each dimension must be one of:

- `RESOLVED`
- `PARTIAL`
- `UNKNOWN`
- `UNAVAILABLE`
- `NOT_APPLICABLE`

Unknown or unavailable information contributes **zero** adjustment. It must never be replaced by a
hand-written estimate simply to complete a card.

## Coverage labels

| Label | Meaning |
|---|---|
| `FULL_INFORMATION_SHADOW` | Baseline plus all required expanded dimensions resolved for the current research contract |
| `BASELINE_WITH_UNRESOLVED_INPUTS` | Some enrichment is usable, some remains partial/unknown/unavailable |
| `BASELINE_ONLY` | Valid baseline; no usable enrichment |
| `SOURCE_CONFLICT_BASELINE` | Event is valid but disputed enrichment is retained as conflict and not applied |
| `INVALID_EVENT` | Authoritative identity/reconciliation failed; no forecast for the phantom/ambiguous event |

## Impact-transform rule

A non-zero contextual adjustment is invalid unless the artifact records:

```text
impact_transform.id
impact_transform.version
impact_transform.status
feature_contributions
```

Permitted research status values are:

```text
SHADOW_UNVALIDATED
SHADOW_VALIDATED
PRODUCTION_VALIDATED
```

The label describes evidence state; it does not grant betting authority. Existing promotion and
prospective-validation gates remain controlling.

## Hard predictive exclusions

The expanded game-state context may not contain predictive sportsbook or market information:

- sportsbook odds
- implied probabilities
- line movement
- betting/public-money percentages
- consensus picks
- bookmaker-derived team strength

These may only enter the separate market/valuation layer after forecast freeze.

Subjective morale/effort/sentiment language is also excluded from direct forecast adjustment under
v1. Observable facts such as availability, workload, travel, lineup, role, weather, or verified
restrictions may be modeled through league-specific transforms.

## Relationship to the information-state platform

The sports-information platform extracts and verifies factual state. This forecast standard governs
how a forecast consumes that state.

```text
source material
-> PIT verified information event
-> league information state
-> expanded-game-state envelope
-> separately versioned impact transform
-> research shadow forecast
-> immutable prospective registration
-> outcome grading
```

Extraction confidence is not itself a point/probability adjustment. The impact transform remains a
separate, testable model object.

## Baseline preservation

Every expanded card should retain or reference its baseline arm so postgame evaluation can answer:

- Did expanded state improve Brier/log loss?
- Did margin or total error improve?
- Which feature classes helped or hurt?
- Was added complexity worth the uncertainty?

That comparison must be prospective; never reconstruct a pregame expanded forecast after results are
known.

## Current migration semantics

Adopting this standard changes the repository default contract immediately. It does **not** imply
that every league already has complete live source binding or a validated impact transform.

Until each league is migrated and validated, the truthful states are:

```text
STANDARD = ADOPTED
BASELINE_FALLBACK = REQUIRED
GAME_STATE_BINDING = ATTEMPTED_PER_LEAGUE
MISSING_STATE = EXPLICIT
UNVALIDATED_IMPACT = SHADOW_ONLY
MARKET_INPUT = FORBIDDEN
ACTION_AUTHORITY = OFF
```
