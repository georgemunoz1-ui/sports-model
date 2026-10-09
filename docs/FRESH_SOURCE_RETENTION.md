# Fresh source retention and NFL inference bridge

This change adds byte-retention checks and a narrow NFL frozen-coefficient runner.
It does not promote models, grant betting authority, repair historical PIT, refit
coefficients, or certify calibration eligibility. Historical packages are unchanged.

## Scoped schedule discovery

`python scripts/capture_priority_schedules.py --date YYYY-MM-DD --scopes regular postseason --output UNIQUE_DIR`

The capture uses the existing evidence collector and preserves actual response
bytes, SHA-256, URL and wall-clock retrieval time. It queries adjacent provider
calendar dates and filters by the explicit slate timezone. Every league is handled
independently; failures remain `SCHEDULE_UNKNOWN` and `ACQUIRE_REQUIRED`. Preseason
must be explicitly selected. CFB scope is the ESPN FBS group. ESPN identifiers stay
namespaced as ESPN identifiers: they are not official/model IDs, and empty provider
responses are not asserted as authoritative zero-game slates. Raw responses may
contain provider odds fields, but these are not transformed or used as model inputs.

No forecast package is automatically made from this evidence. NBA/NHL current
baselines, WNBA selected model and the NFL weekly path retain their existing
regular-season restrictions. Capturing postseason evidence does not make those
models postseason-eligible.

## Retention checks on cards

Set `SPORTS_SOURCE_BUNDLES` to a JSON list of retained capture directories. The
shared writer matches every source URL/hash/capture-time tuple to retained raw
bytes and includes `source_attestation`. Missing bytes, changed bytes, path escape,
changed timestamp, malformed evidence or sources after cutoff cannot pass.
`PIT_ORDERED` remains `PIT_ORDERED`, even with `RAW_BYTES_AND_RECEIPTS_VERIFIED`.
These local receipts are not signed provider provenance, historical availability,
or proof of numerical use. Invalid/missing retention is recorded, not hidden.

## Narrow frozen NFL runner

`python scripts/run_fresh_nfl_research.py --store VERIFIED_STORE --state-id STATE_ID --seed-id INDEPENDENT_SEED_ID --source-bundles CAPTURE_DIR --date YYYY-MM-DD --output UNIQUE_DIR`

The operator must already have independently set `NFL_WEEKLY_STATE_SEED_SHA256`.
The command calls the existing `prepare_nfl_weekly_events.build`, preserving its
verified state, six-hour schedule freshness, team mapping, event IDs and model
selection. It binds a new immutable package explicitly into the shared runner;
the archived/default package is never overwritten. It verifies requested-date
coverage, selected model digest, weekly-state assimilation identity, feature
snapshot digest, retained forecast/draw hashes, and equality of retained forecast
trace to card diagnostics. It emits the card plus a fresh-run receipt and manifest.
Failure is explicit and partial evidence is preserved. It does not register the
card itself; existing canonical registration can consume a successful card.

## Exact prerequisites and remaining blockers

For NFL, obtain current `games.csv` and season PBP plus real retrieval receipts
through the existing approved capture path. Replay them using:

`python scripts/validate_current_nfl_weekly_state.py --frozen FROZEN_BUNDLE --capture CAPTURE_DIR --output UNIQUE_STATE_DIR --through-week COMPLETED_WEEK`

The frozen bundle must include `completed_manifest.json` and `historical_state.json`.
The repository must include `data/nfl/contextual_v1/model_packed.json`,
`recovered_parameters.json`, model source modules, selection artifacts and their
pinned dependencies. The isolated partial test checkout does not include those
frozen datasets. The operator must determine the completed week from verified
schedule/results and resolve any explicit QB/starter conflicts; the bridge does
not guess a week, manufacture a seed, or adjudicate personnel conflicts.

Other existing builders are not refresh-only:

- `prepare_cfb_current.py --source RECOVERY --output PACKAGES` calls LogisticRegression.fit and Ridge.fit.
- `prepare_wnba_current.py --source RECOVERY --current CURRENT --output PACKAGES` calls the incumbent fitter's fit_full.
- `prepare_initial_baselines.py --history HISTORY --current CURRENT --output PACKAGES` fits deployment heads for NBA/NHL/MLS.

They were deliberately not orchestrated under this repair's no-retrain constraint.
An authorized, separately reviewed fixed-coefficient state-refresh implementation
is still needed for those paths, or explicit authorization for their existing
refit workflow. No fresh full-slate acceptance is claimed by unit tests.

## Verification

`python -m unittest discover -s tests -p 'test_source_attestation.py' -v`

`python -m unittest discover -s tests -p 'test_fresh_nfl_research.py' -v`

The NFL test fixture substitutes builder/runner modules and is explicitly synthetic:
it tests orchestration and refusal conditions, not model accuracy or live inference.
