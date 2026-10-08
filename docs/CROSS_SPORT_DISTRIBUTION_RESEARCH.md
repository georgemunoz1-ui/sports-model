# Cross-sport margin and total research

Implemented 2026-10-07 after the owner's request to apply the ATS research across
all models/sports. This is executable, opt-in research infrastructure, not seven
new fitted/validated production models. Existing selected models, specialized
challengers, frozen forecasts, canonical grading and wagering authority remain
unchanged. Main inspected: `43ad83382af067b019a086d45d23569497ca6e08`.

## What runs

- Discrete residual distributions for a named parent point model, separately for
  margin and total. Empirical and conditional-scale methods are distinct candidates.
- Conditional scale uses ridge regression of log(1 + squared residual) against
  declared pregame features; the standardized empirical residual pool supplies
  the predictive shape. This choice is an unvalidated research hypothesis.
- Monotone CDF recalibration fits on a separate chronological calibration cohort.
  It retains discrete mass and cannot repair an outcome absent from the support.
- Availability mixtures consume already modeled, source-bound joint scenarios,
  including their weights and retrieval times. They mix distributions, not means.
  This does not acquire injuries or estimate player/minutes effects by itself.
- Exact contract probabilities and actual reproducible PCG64 draws, with separate
  analytic and simulation outputs and retained arrays/hashes.
- Matched-event Brier, log loss, CRPS, descriptive reliability, paired time-block
  uncertainty, and optional same-time price comparisons. Integer pushes and
  quarter-line partial settlements remain explicit.
- Both the shared card command and canonical NFL pregame command accept
  `--distribution-research-config`. Parents are saved first. An optional child
  failure is recorded, returns nonzero and does not erase parent card outputs or
  prevent subsequent NFL events from running.

## Settlement profiles

| League | Supported profile | Margin ties | Products |
|---|---|---|---|
| NFL | `FULL_GAME_OT_REGULAR` / `FULL_GAME_OT_POSTSEASON` | Regular yes; postseason no | spread / total |
| CFB | `FULL_GAME_OT` | No | spread / total |
| NBA | `FULL_GAME_OT` | No | spread / total |
| WNBA | `FULL_GAME_OT` | No | spread / total |
| MLB | `COMPLETED_GAME_EXTRA_INNINGS` | No | run line / total |
| NHL | `FULL_GAME_OT_SO_PLUS_ONE` / `REGULATION` | Full game no; regulation yes | puck line / total |
| MLS | `REGULATION_90_STOPPAGE` | Yes | handicap / total |

These are declared modeling contracts, not inferred sportsbook house rules.
Use only matching, verified result and quote semantics. Postponement/void,
called-game exceptions, listed-pitcher conditions, first halves and live play
require separate adapters/contracts. MLS supports quarter lines as two equal
stakes on neighboring half lines. Other sports require half-point increments.
For margin contracts `line` is always the HOME handicap, including when the
selected side is AWAY. Totals use OVER/UNDER. Five states are always named:
`win`, `half_win`, `push`, `half_loss`, `loss`.

Illegal support is conditioned away and its removed probability is reported.
This is a modeling assumption to evaluate, not a validated overtime simulator.
Margin and total distributions are independent research products; no joint
scores, correlated parlay probability, team totals or winner/ATS coherence with
the incumbent winner head are claimed. Existing specialized joint-score models
remain independent comparisons.

## Fit input and chronology

Run `python scripts/cross_sport_distribution_research.py fit --input INPUT.json --output NEW_MODEL.json`.
The JSON contains:

```json
{
  "league": "nfl",
  "product": "margin",
  "settlement": "FULL_GAME_OT_REGULAR",
  "parent_model_id": "EXACT_PARENT_MODEL_ID",
  "information_set": "DECLARED_FORECAST_HORIZON",
  "fitted_at": "AS_OF_UTC_WITH_TIMEZONE",
  "method": "empirical",
  "market_input": false,
  "rows": []
}
```

`fitted_at` is the **historical fitting as-of boundary**, stored as
`fit_as_of_utc`; it is not an assertion that this artifact existed then. Actual
creation uses the writer clock. Predictions report whether the fitted artifact
existed at their cutoff. All outputs remain diagnostic and ineligible for
canonical prospective grading regardless of caller timestamps.

Each training row requires event_id, league, product, settlement, parent_model_id,
information_set, market_input, forecast_sha256, result_source_sha256,
prediction_kind=`CHRONOLOGICAL_OUT_OF_TIME`, parent_fit_cutoff, forecast_cutoff,
start_time_utc, result_available_at, predicted_mean, observed, and scale_features.
The forecast and result hashes must resolve to retained evidence during a real
experiment; this library checks format and chronology, not external attestation.

Required ordering is parent fit cutoff <= forecast cutoff < start <= result
availability < fitting boundary. Reused event IDs, mismatched scopes, naive
timestamps, booleans/nonfinite numbers, and in-sample forecasts are rejected.
No inherited winner-only probabilities are converted to margin distributions.

For conditional scale add `method: "conditional_scale"`, `scale_features` (an
ordered list of numeric pregame field names), and positive `ridge` (default 10).
Fit each candidate separately and predeclare hyperparameters before evaluation.
Thirty training/calibration rows is an engineering minimum, **not a validation
sample-size recommendation**. No automatic promotion threshold is supplied.

Market-informed parents are supported only with explicit `market_input: true`
and matching training/inference roles. They are separate candidate identities;
known market feature names are refused in a market-blind scale model. This
does not certify that arbitrarily renamed caller fields are market-free.

## Calibration, simulation and evaluation

`calibrate --input INPUT.json --output NEW_CALIBRATOR.json` accepts `rows` and
`fitted_at`. Rows contain a frozen distribution, observed outcome, kickoff,
result availability and result-source hash. One model/league/product/settlement
per fit; duplicate events, wrong scope, future labels, unsupported observed
values and absent outcome support are rejected. The fitted intercept/log-slope
transform is monotone; an untouched later cohort must assess any benefit.

`evaluate --input INPUT.json --output NEW_REPORT.json` accepts `rows`,
`baseline_id`, `challenger_id`, and optional `bootstrap`/`seed`. Rows contain:

- distribution, contract (`line`, `side`), observed, start_time_utc,
  result_available_at, result_source_sha256, block_id;
- optional contract.quote: event_id, same line/side/settlement, book,
  source_sha256, observed_at_utc, retrieved_at_utc, decimal_odds and
  opposing_decimal_odds for the exact opposing contract.

Reports show unmatched counts. They refuse duplicate event/cutoff/contract/model
rows or contradictory outcome/source bindings. Brier is the **category sum**,
not scalar binary Brier. Zero-probability log loss is null plus an explicit
zero-probability count, not a finite clipped score. Half-point/integer market
benchmarks use conditional non-push probabilities; quarter-line odds are not
misrepresented as binary implied probabilities. Flat-stake research returns
refer to the supplied contract list, not an optimized betting policy.

Paired score differences average contracts within each game before resampling
declared time blocks. Alternate lines are not extra independent games. Fewer
than five blocks produces no interval; five blocks does not guarantee useful
precision. Reliability bins are descriptive and have no inferential gate.
Repeated testing, subgroup claims and prospective sample design remain the
experiment owner's responsibility. This tool never closes issue #59.

## Card configuration

```json
{
  "schema": "sports.distribution_card_config.research.v1",
  "information_set": "DECLARED_FORECAST_HORIZON",
  "action_authority": false,
  "models": [{"path": "MODEL.json", "sha256": "EXACT_FILE_SHA256"}],
  "contracts": [{
    "event_id": "EXACT_EVENT_ID", "product": "margin",
    "settlement": "FULL_GAME_OT_REGULAR", "line": -3,
    "side": "HOME", "kind": "HYPOTHETICAL"
  }]
}
```

Each model entry can add `calibration: {path, sha256}`. Paths are relative to the
config. MARKET contracts require matching quote evidence; hypothetical lines
are labeled and have no quote/EV claim. `availability_scenarios` optionally maps
`EVENT_ID:PRODUCT` to joint scenarios. Each requires scenario_id, weight,
source_sha256, observed_at_utc, retrieved_at_utc, and a distribution bound to the
same event/cutoff/parent-row digest and fitted model. Unknown weights must not be
invented. Scenario mixtures receive a distinct model ID and need their own
calibrator; a calibrator fitted to the unmixtured model is intentionally refused.

Existing card replay:

```sh
python scripts/cross_sport_distribution_research.py card \
  --card FROZEN_CARD.json --config CONFIG.json --output NEW_DIRECTORY
```

New shared cards: append `--distribution-research-config CONFIG.json` to the
existing `scripts/generate_card_force.py` command. NFL: append it to
`scripts/run_nfl_integrated.py`; the QB arm's explicit margin/total heads can
feed separately fitted children without opting into the combined arm. Parent
scope restrictions still apply. A winner-only parent without a point head
returns POINT_HEAD_UNAVAILABLE; a missing fitted child returns FIT_REQUIRED.

## Adoption work still required

1. Assemble authentic chronological parent-forecast/result cohorts for each
   exact model, league, product, settlement and forecast horizon.
2. Pre-register empirical vs conditional-scale ablations, then the separate
   calibration and availability increments. Preserve a final untouched period.
3. Fit/hash each model and review residual tails, key-number mass, legal-support
   conditioning and full-game settlement. Do not transfer one league's residuals.
4. Acquire real availability and fit replacement/minutes effects in each sport.
   The mixture interface does not satisfy source acquisition or effect validation.
5. Evaluate later and prospectively with matched market snapshots and all failed
   or missing events visible. Register through the canonical writer separately.
6. Only then propose default changes through the existing selection process.

Current code status: implemented and exercised with synthetic fixtures for all
seven leagues. Current fitted sports deployment and measured accuracy improvement:
NOT ESTABLISHED. Existing NFL calibration, PR #50/#53/#58 and closure program #59
are not replaced or declared complete. Main's standing health failures remain.

## Executed historical follow-up

The October 7 follow-up fits and evaluates seven products across four sports,
with source-limited NFL/WNBA/MLB cases explicit. See
[DISTRIBUTION_REPLAY_20261007.md](DISTRIBUTION_REPLAY_20261007.md).
Conditional scaling showed no clear improvement; six CDF fits refused missing
support. No accuracy default was activated. The original verification checkpoint
remains unchanged as historical evidence.
