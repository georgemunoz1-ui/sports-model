# NFL integrated context pipeline — September 14, 2026

## What changed

The main research entry point is `python scripts/run_nfl_integrated.py --date 2026-09-14 --output UNIQUE_DIRECTORY`.
The common card command `python scripts/generate_card_force.py --date 2026-09-14 --league nfl --output-dir UNIQUE_DIRECTORY` resolves the same NFL adapter. It no longer needs a separate undocumented SRS runner. `data/nfl/contextual_v1/runtime.json` identifies the event package and combined research model. Models are bundled as portable coefficients, not unsafe pickle objects. No external network is needed to replay this event package.

The shared historical/live feature path has **100 features**: the recovered 18 EPA/weather/rest/venue features, five QB form/experience/change features, 72 availability/practice/prior-role features, and five airport-travel features. Position groups are QB, RB, WR/TE, OL, DL, LB and DB. Effects are fitted with regularized logistic and Ridge heads, never hand-set injury point deductions. Prior snap share is a workload proxy; it is not a prediction of tonight's usage. The QB, availability, travel, refit-base and combined arms are emitted together for comparison.

New data: **58,449 regular-season injury rows**, **264,774 snap rows**, **7,078 QB-game aggregates** from 2015–2025. Each game uses prior-week QB and snap history. Injury rows select the latest known report before kickoff. Known late updates are excluded; unresolved undated conflicts are quarantined. This historical source is not an archived pregame feed: 5,783 admitted/inspected report rows lack a publication timestamp, and historical starting-QB IDs are retrospectively recorded. All results below are reused retrospective screening evidence.

## Evaluation

Expanding training years, fixed hyperparameters selected before execution (logistic C=0.1; Ridge alpha=50). Held-out year folds 2019–2025: **1,871 final games**, including six ties; binary scoring uses **1,865 non-ties**. The refit base uses these same regularizers and population, so it is distinct from the older recovered model artifact.

| Arm | Brier, lower better | Margin MAE | Total MAE |
|---|---:|---:|---:|
| availability | 0.236335 | 10.605 | 11.131 |
| base | 0.229609 | 10.380 | 10.998 |
| combined | 0.231032 | 10.467 | 10.882 |
| qb | 0.222912 | 10.212 | 10.720 |
| travel | 0.229529 | 10.389 | 11.006 |

Combined-minus-base Brier **+0.001423**, season-block bootstrap95%CI **[-0.002535,+0.005453]**. The declared improvement screen **failed**. QB-only evidence is promising; broad availability features worsen this first test. Travel alone changes little. More inputs did not automatically improve probability accuracy. Week1 Brier is0.238322 base and0.244594 combined. These results do not promote any model or retrospectively change Sunday forecasts. B2 was not run.

## Current MNF test

Forecast cutoff **2026-09-14T09:25:55.427062+00:00**; DEN at KC, kickoff2026-09-15T00:15Z. Model: **Denver by0.805791**, total **47.119722**, Denver conditional non-tie win **54.521660%**. Binary Monte Carlo: Denver **54.275%** in100,000draws.

Joint score simulation100,000draws: Denver **54.330%**, KC **45.292%**, tie **0.378%**. Sample mean scores: DEN **24.102**, KC **23.042**. These mean scores belong to the joint distribution; they need not equal the independently fitted Ridge centers. The sampler's winner masses are tied to the logistic head, so their agreement is by construction, not independent validation.

Inputs now applied: expected Mahomes/Nix IDs and prior passing state; official injury/practice status; ConnerDB and SimmonsOL absences; Cooper's verified commissioner-exempt state mapped explicitly to an OUT proxy. Prior role estimates are Conner1.000, Simmons0.925, Cooper0.6175 from up to four prior appearances. Applying an injury-report transform to commissioner exemption is a flagged support extrapolation. The DEN→KC travel feature is an854.86km home-airport proxy, east one time zone; actual routing/arrival time is unknown.

NWS hourly grid for Arrowhead coordinates: kickoff-containing hour **88°F**, sustained wind **13mph**; source updated2026-09-14T06:26:43Z, retrieved09:14:23Z. This replaces the earlier city-point proxy. Historical weather is game-observed weather while current input is a forecast, which limits the validation claim. Final inactives and expected workloads remain pending; no invented snap limits or injury-recovery values are applied.

## Simulation and settlement

The new joint kernel learns score shapes from paired out-of-fold final-score residuals. It estimates final tie probability from2015–2025finals with a predeclared Jeffreys rate (10ties/2,895games; fitted rate0.00362569). It draws a supported integer score pair conditional on the fitted outcome mass. Overtime already belongs to the target, so there is no additional approximate OT or winner-only coin flip.

A first unconditioned residual sampler manufactured excessive tie mass and is preserved as superseded. The separately recorded v2 specification fixes this mechanical issue; it does not claim calibrated key-number probabilities. Product functions calculate explicit win/push/loss for a specified full-game spread/total; moneyline requires an explicit tie-refund/loss contract. First-half products are rejected.

Secondary later-year residual checks (2020–2025, prior years only) support **1613games**, with **2unsupported conditional-support cases** retained. Nominal80% coverage: margin **81.96%**, total **82.95%**. This is diagnostic and does not establish ATS, total, key-number or conditional tie calibration.

## Verification and operating status

Fifteen targeted tests pass: weekly leakage exclusion; duplicate/status/source handling; real fitted feature perturbations; market/schema separation; role unknowns; relocation/time-zone handling; exact seeded replay; explicit push/tie/period settlement; canonical routing; zero-dose rendering. Actual run arrays are preserved with source/config/code hashes and exclusive output directories. The full repository checkout could not be obtained, so repository-wide health is not claimed. New CI runs these focused checks on the actual PR checkout.

The research functionality is integrated; statistical promotion is separate and remains false. Market input false; action authority false; Sunday/SNF/SRS/B1/EPA artifacts unchanged. New event dates require new source-bound packets; an unacquired date is never a verified zero-game slate. The included package is a frozen MNF example and must not masquerade as fresh data on later dates.

## Reproduce and extend

Install `requirements-nfl-context.txt`, then run the main command above. Tests: `python -m unittest discover -s tests -p test_nfl_context.py -v`.

Training: `python scripts/build_nfl_context.py --recovered-root PATH_TO_RECOVERED_BUNDLE_CHECKOUT --output NEW_FIT_DIR`. Source filenames and SHA-256 receipts are in `data/nfl/contextual_v1/sources/manifest.json`; the recovered original schedule/PBP bundle supplies the original base feature table. Pack with `scripts/pack_nfl_context_model.py`, then create a new event package with `scripts/prepare_nfl_event.py` using explicit event, base-feature and current-context files. Set `NFL_CONTEXT_PACKAGE` to that new package. Do not alter old bundles or treat replays as new pregame registration.


## Explicit selection and information regimes

The integrated command accepts `--model-id` and `--mode`. The compatibility
mode is `research_pregame`, and its default model remains the combined research
arm, not an accuracy-preferred or validated production model. Exact fitted IDs
in the coefficient artifact select base, QB, availability, travel, or combined.
An unknown model ID fails without substituting another model. All five analytic
comparison outputs remain included. Binary simulations use the selected arm.
The joint score residual pool belongs to combined only; other arms explicitly
report joint-score simulation unavailable and do not reuse that pool.

The requested four future operating modes are listed with capability status in
`models/nfl/contextual/operating.py`. There is currently no registered validated
official model, fitted market-aware ensemble, or fitted live model in this runner.
Those names cannot relabel a research pregame output. Postgame evaluation uses
the existing dedicated historical scripts, not this pregame inference command.
This interface does not claim to implement those additional model families.
A future market-aware model needs its own fitted/versioned input and target
contract. Current football-only generation still rejects a market context field.

Outputs distinguish fitted matrix-column counts, finite values before imputation,
head-specific nonzero coefficient counts, imputed feature names, missingness
indicators, and source limitations. A 100-column matrix is not evidence of 100
fully observed current facts. Personnel/travel coefficients in this integrated
arm were newly fitted; they were not recovered historical coefficients of the
old 18-feature EPA arm. Changing output metadata changes new-run identities and
seeds; previously frozen arrays and artifacts are untouched.
