# Freshness and rest repair — source trace and executable candidate paths

Audit basis: canonical source pinned to `90daf8e0036c67a5304aa0747bf50b2266e0b364`, plus the user's frozen October 22 card. This work changes acquisition/candidate construction and adds receipts. It does not alter an existing forecast, selected model, fitted package, grading ledger, wagering authority, or default.

## Findings established from source

| Finding | Exact source path | Consequence |
|---|---|---|
| Rest and form share `team_state[team]['last']`. Rest is elapsed **start-to-start hours divided by 24**, clipped to 0–14; unknown state is imputed to 14. | `models/current/baseline.py::feature`, `::update` | A current fetch timestamp does not establish current rest. Calendar-day rest and hours since game end are different variables. |
| Training rows and deployment state both defer games on the same and previous UTC date. | `scripts/prepare_initial_baselines.py::causal_rows` | The coefficients were trained on the embargoed rest proxy. Replacing only inference rest is a feature-definition change, so it requires a separately identified refit and chronological evaluation. |
| Legacy team-history capture stops at the wall-clock calendar year. Legacy preparation accepts only provider seasons 2021–2026. | `scripts/capture_team_histories.py::main`; `scripts/prepare_initial_baselines.py::histories` | NBA's October 2026 provider season 2027 is omitted even when acquisition succeeds. Merely re-fetching season 2026 leaves April-ending state. |
| Runtime currentness checks source acquisition age and fit cutoff, not the age of each consumed team state. | `models/current/common.py::current` | Fresh capture can pass while underlying team state is stale. |

The rest issue is therefore traced to **shared embargoed feature construction**, not merely an assertion that a UTC timestamp is wrong. The form embargo remains unchanged. Its statistical merits were not evaluated here.

## Frozen evidence

Retained excerpt: `tests/fixtures/frozen_20261022_freshness_excerpt.json`. Parent `October-22-2026-Pregame-Card.json` SHA256 is `06af78e016a4eb152d259a53efbcf9192ca1d5bf60c8eac15fa0f912e0d4754e`; creation time is `2026-10-22T06:31:02.839044+00:00`. The excerpt is independently hash-pinned in a regression test.

- `NHL:401892556`, Florida at Pittsburgh, starts `2026-10-22T23:00:00+00:00`; frozen `away_rest = 5.041666666666667`. Under the documented feature equation this corresponds to a consumed last-start time of October 17 at 22:00 UTC. This last timestamp is **reconstructed from the feature**, not independently recovered from a state file. The NHL source summary ends at October 20 23:00 UTC.
- Both frozen NBA rows have both rest fields clipped to 14. The source summary has 7,230 consumed games and a latest consumed game start of `2026-04-13T00:30:00+00:00`, despite October 22 capture times. NBA's recorded season counts stop at provider season 2026.
- The recovered result-verification receipt identifies the official [October 21 Florida–Ottawa recap](https://www.nhl.com/news/florida-panthers-ottawa-senators-game-recap-october-21-2026) as the source for Florida's previous-night loss. That postgame retrieval is not a preforecast availability receipt. No retained raw preforecast October 21 team-schedule capture was recovered in this work, so a corrected **actual-game** rest value or probability is not asserted.

The regression using a previous game at October 21 23:00 UTC is explicitly **synthetic**. It reproduces the old 5.0416667-day proxy and a 1-day operational candidate while changing no non-rest feature. It proves semantics and guards, not the missing real-world capture or predictive improvement.

## Built: source-bound NBA acquisition

`scripts/nba_history_scope.py` derives the required final provider season from retained, hash-verified current NBA scoreboard bytes. It does not guess the season using a month boundary. Current-season witnesses must be captured by the cutoff and within a bounded current schedule window. Historical cutoffs use their own source season, never today's calendar. No suitable current witness means an explicit error.

The captured team directory must contain the expected 30 distinct NBA team IDs. The resulting acquisition scope contains its source hash, current-season witnesses, exact provider-year range, IDs and its own digest. Preparation checks every team/year request exactly once, raw hashes, requested-season response identity, team participation, timestamps, final status, and source-bound current event packets. An empty but valid schedule response remains no observed games; it is not an assertion that the model state is current.

Opt-in acquisition and preparation:

```bash
python scripts/capture_team_histories.py --league nba \
  --nba-current-bundle PATH_TO_CURRENT_CAPTURE \
  --output NEW_NBA_HISTORY_DIRECTORY

python scripts/prepare_initial_baselines.py --league nba \
  --history NEW_NBA_HISTORY_DIRECTORY --current PATH_TO_CURRENT_CAPTURE \
  --nba-acquisition-scope NEW_NBA_HISTORY_DIRECTORY/nba_acquisition_scope.json \
  --as-of-utc ACTUAL_PREPARATION_CUTOFF --output NEW_RESEARCH_PACKAGE_DIRECTORY
```

This follows the existing fixed-method research refit behavior and records the repaired acquisition lineage. It does not change selected defaults or certify player/roster freshness. Captures cannot be backdated: using newly fetched data under a historical cutoff fails. A network acquisition and full actual NBA refit were **not performed** in this task; a complete source corpus remains required.

Legacy no-scope behavior remains available to reproduce historical controls. The corrected path is explicit so an existing trained control is not silently reinterpreted. A later default acquisition switch must use a new operational run identity and the reviewed source scope.

## Built: operational-rest candidate and state receipts

`models/current/freshness.py` exposes:

- `normalize_captured_schedule(raw, league=..., captured_at_utc=..., source_sha256=...)`: verifies retained raw bytes, normalizes IDs/times and played-final status, discards scores. Completed cancellations and forfeits are not accepted as played games. Capture time is evidence that a final was observed, not proof it was available earlier.
- `operational_rest(event, records, cutoff_utc=..., coverage=...)`: selects the latest eligible observed final before cutoff, excludes the target event, future observations, future completions and nonfinals. Conflicting IDs, missing coverage, bad timestamps and invalid sources return unknown. Rest units are fixed as start-to-start 24-hour days. A six-hour source-age policy mirrors the existing runtime TTL and is explicitly recorded, not presented as a calibrated quality threshold.
- `rebuild_candidate_features(...)`: rebuilds **only** the two rest features on the existing feature vector, returns new semantic identity `initial_causal_score.operational_rest.start_to_start.v1` and `REFIT_AND_CHRONOLOGICAL_EVALUATION_REQUIRED`. Missing either side's eligible history returns `candidate_features: null`. This function does not apply old fitted coefficients to new semantics.
- `state_freshness_receipt(package, event, features, cutoff_utc=..., max_state_age_hours=None)`: binds the original consumed state and feature snapshot hashes, reports per-team timestamps and state ages, reconstructs the actual rest feature and marks imputation. It flags post-cutoff fits and states. State-age blocking requires an explicitly chosen policy; otherwise actual ages remain disclosed.

Coverage inputs are upstream acquisition assertions, not inferred completeness from a nonempty array. Each contains `team_id`, `from_utc`, `through_utc`, `observed_at_utc`, `source_sha256`, `complete: true`, and `population: "ALL_PLAYED_GAMES"`. They must cover the predecessor and a timely observed capture with a bound source hash and matching retained observation timestamp. The helper checks those assertions; an upstream collector must establish complete schedule coverage from retained responses. A source hash alone does not prove a provider omitted no game.

This population requirement matters: the existing NBA/NHL model histories request `seasontype=2` only. They cannot certify physical rest around preseason or postseason boundaries. Such history may repair regular-season model state while remaining insufficient for the all-played-games rest candidate. This is an explicit acquisition gap, not a silently substituted rest definition.

The executable candidate CLI verifies an original initial-baseline package's identity, fitted/state digest and runtime code pins; loads hash-bound raw schedule captures; binds coverage to those captures; and writes an immutable candidate plus manifest:

```bash
python scripts/build_operational_rest_candidate.py \
  --package PATH_TO_ORIGINAL_PACKAGE_JSON \
  --history-packet PATH_TO_RETAINED_REST_HISTORY_PACKET_JSON \
  --event-id NHL:PROVIDER_ID --as-of-utc ORIGINAL_FORECAST_CUTOFF \
  --output NEW_CANDIDATE_DIRECTORY
```

The history packet has schema `sports.operational_rest_history.v1`, a `league`, `sources` containing `raw_path`, `source_sha256`, `captured_at_utc`, and the explicit `coverage` rows above. Source paths must stay within the packet directory. The collector's all-game completeness assertion remains separately reviewable; the CLI does not invent it. `forecast_generated` is always false. A candidate with missing qualifying coverage is retained with null features instead of applying an old fit to a guessed value.

Integration point is the **unpinned card orchestration layer**, after forecasting:

```python
raw.setdefault('diagnostics', {})['state_freshness_receipt'] = state_freshness_receipt(
    ctx['package'], event, raw['model_input_snapshot'], cutoff_utc=ctx['cutoff'])
```

`baseline.py`, `common.py` and league adapters are package-code-pinned and remain unmodified. Altering one solely to add disclosure would prevent executable replay of frozen packages. Receipt attachment belongs outside that pinned forecast procedure.

“Feature matches consumed state” proves numerical **input use**, not that a personnel change or goalie identity altered a prediction. No feature delta or prediction-effect claim is manufactured. Missing player/goalie inputs remain missing.

## Validation and remaining work

`python -m unittest tests.test_current_freshness tests.test_nba_history_scope tests.test_nhl_season_rollover_unittest tests.test_nhl_atomic_capture -q`: **66 tests passed**, comprising 28 new tests and 38 existing NHL acquisition/replay regressions. Tests cover original embargo preservation, corrected candidate locality, chronology across UTC offsets, source hashes, post-cutoff availability, current-event exclusion, cancellations/forfeits, identity conflicts, missing/all-game history coverage, nonfinite/bool values, stale state with fresh captures, October/January rollover and historical April acquisition, exact request census and source-event tampering. The CLI is tested end-to-end on explicitly synthetic raw captures, including immutable output, path escape and hash tampering.

`python -m pytest tests/test_current_runtime_contracts.py -q`: 15 existing runtime tests passed, including the original embargo and immutable replay contracts.

The two existing NHL suites initially required restoration of `research/nhl-season-scope-2026-27-v2.json`; after the pinned fixture was hydrated they passed. The original v1 feature code, runtime code pins and frozen controls remain unchanged.

Still required before any claim of improved forecasting accuracy:

1. Acquire complete current NBA provider-season histories and actual preforecast previous-game captures, retain raw receipt bytes, and build a new package in a new directory.
2. Build chronological operational-rest training features with historical availability evidence. Modern captures of old finals do not establish historical availability; preserve the existing retrospective limitation.
3. Fit/evaluate the changed rest semantics under a separate procedure identity with preregistered paired endpoints. No promotion is implied by a repaired input.
4. Acquire and model NBA player availability/minutes, NHL starting goalies and other missing identity features. An acquisition rollover does not solve those model deficiencies.
5. Use the selection registry and validated state population to decide eligibility. A current control or a freshly fetched source is not automatically publication-ready.

No production freshness guarantee, calibration claim, historical result revision, or wagering permission is created by these changes.
