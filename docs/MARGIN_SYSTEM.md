# Shared margin and cover research system

This is an additive research interface for NFL, CFB, NBA, WNBA, MLB, NHL and MLS.
It describes full margin distributions, then computes winner and spread outcomes
from exactly the same probability mass function (PMF). It does not change any
selected default, existing forecast, ledger, model verdict, or action authority.
Software execution is not evidence of predictive skill or profitable trading.

## Components

| Component | Purpose |
|---|---|
| `models/common/margin_system.py` | Hash-checked PMF adapters, integer quantiles, predictive intervals, five-state cover pricing, coherent winner probabilities, Monte Carlo receipts |
| `models/common/margin_challenger.py` | Separate fitted residual + Student-t tail + integer-frequency challenger; conditional scale and chronological internal tuning |
| `research/evaluate_margin_system.py` | Later-cohort research evaluation, calibration and paired uncertainty where supported |
| `pipelines/cards/margin_system.py` | Immutable all-sport card, source receipts, missing-product coverage and actual completion-time labeling |
| `scripts/run_margin_system.py` | Explicit opt-in CLI; no incumbent runner or scheduled default is changed |

## Orientation and settlement

The sole internal orientation is `M = home score - away score`. A home handicap
`h` settles on `M + h`. The matching away handicap is `-h`. For example, home -3
and away +3 share one market: an exact home margin of +3 pushes both.

The legacy discrete API always receives the **home handicap**, even when its
`side` argument is `AWAY`. Card rows therefore retain `home_handicap`,
`away_handicap`, `home_spread`, `away_spread`, and `line_basis` explicitly. A
selected-side handicap must be translated exactly once before using that API.

| League | Accepted settlement profiles |
|---|---|
| NFL | `FULL_GAME_OT_REGULAR` (ties possible), `FULL_GAME_OT_POSTSEASON` |
| CFB | `FULL_GAME_OT` |
| NBA / WNBA | `FULL_GAME_OT` |
| MLB | `COMPLETED_GAME_EXTRA_INNINGS` |
| NHL | `FULL_GAME_OT_SO_PLUS_ONE`, or a separate `REGULATION` distribution |
| MLS | `REGULATION_90_STOPPAGE` (draws retained) |

Rules are model contracts, not independent confirmation of a sportsbook's terms.
No regulation/full-game conversion is inferred. MLB shortened-game and specific
book void rules require their own source contract. NHL shootout bookkeeping must
already be reflected in supplied score states. MLS quarter handicaps split into
adjacent half-step legs; half-win and half-loss remain separate outcomes.

## Existing retained distribution reports

From the repository root:

```bash
python scripts/run_margin_system.py \
  --input /absolute/path/distribution_report.json \
  --events /absolute/path/diagnostic_card.json \
  --output /absolute/path/new-margin-card \
  --draws 100000
```

`--input` can be repeated. Existing `sports.distribution_card.research.v1` reports
must have a valid `artifact_sha256`; every margin distribution must also have its
own valid hash. The original PMFs and source files are preserved. An old finite
support defect or no-tie conditioning assumption remains visible; the adapter
does not silently repair the incumbent artifact.

`--events` is optional metadata with an `events` or `forecasts` array. Only event
ID, home team, away team, and start time are read. It cannot replace a model,
point projection, probability, or cutoff. Conflicting start times are refused;
equivalent UTC instants using different offsets are accepted. A bound
`distribution.provenance.start_time_utc` is used when no other start is supplied.

## Explicit PMF input

The other accepted JSON schema is:

```json
{
  "schema": "sports.margin_system_input.research.v1",
  "action_authority": false,
  "distributions": [
    {
      "event_id": "source-event-id",
      "home_team": "Home",
      "away_team": "Away",
      "start_time_utc": "2026-10-19T23:00:00Z",
      "distribution": "REPLACE_WITH_A_COMPLETE_HASHED_DISCRETE_DISTRIBUTION_OBJECT"
    }
  ],
  "coverage": []
}
```

The string above is a documentation placeholder, not a runnable distribution.
Build the object with `margin_system.from_discrete(existing_distribution)`,
`from_joint_scores(home_scores, away_scores, ...)`, or
`from_margin_draws(margins, ..., orientation="HOME_MINUS_AWAY")`. Each adapter
requires a source/event/cutoff binding. A winner-only probability does not identify
a margin distribution and is rejected; there is no assumed Gaussian spread scale.

Paired score inputs preserve empirical states and reject tied finals under
no-tie contracts. They do not invent overtime. Empirical draw resampling estimates
numerical simulation noise conditional on the supplied empirical PMF; it does
not estimate uncertainty in the original score model.

## Fitted challenger from explicit point heads

The CLI can also bind separately fitted challengers to existing point forecasts:

```bash
python scripts/run_margin_system.py \
  --parent-card /absolute/path/source-bound-point-card.json \
  --challenger-config /absolute/path/challenger-config.json \
  --output /absolute/path/new-challenger-card \
  --draws 100000
```

`--parent-card` may be repeated and can be combined with retained `--input` PMFs.
Each parent card has `league`, `as_of_utc`, `generated_at_utc`, `forecasts`, and
explicit `information_set` and `settlement` (card-level or per row). A row needs:

- `event_id`, `model_id`, `home_team`, `away_team`, `start_time_utc`;
- `forecast_status: "FORECAST_GENERATED"`;
- valid `input_snapshot_hash` and `model_state_config_hash`;
- an explicit home-oriented margin point supported by the existing
  `distribution_research.point` reader; no probability inversion;
- any required fitted scale inputs in `model_input_snapshot`.

The exact parent ID, league, information set and settlement must match the fit.
The parent must have been generated before event start, and input cutoff cannot
postdate parent generation. These are checked declarations, not independent
historical attestation. A fit created after the parent cutoff is labeled a
reconstruction, never prospective. The CLI refuses explicit market-informed
parents; it does not inspect raw data deeply enough to certify market blindness.

Configuration example:

```json
{
  "schema": "sports.margin_system_challenger_config.research.v1",
  "action_authority": false,
  "information_set": "RECONSTRUCTED_PROVIDER_FINALS_FIXED_PARENT",
  "derived_scale_features": ["absolute_parent_margin"],
  "models": [
    {"path": "nhl-fitted-challenger.json", "sha256": "EXACT_64_CHARACTER_FILE_SHA256"}
  ]
}
```

Paths resolve relative to the config. The file hash, artifact hash and fitted-code
identity are validated. The optional `derived_scale_features` list explicitly
allows `absolute_parent_margin = abs(the_actual_parent_point)`. Other missing
scale features block that row; they are never filled with zero. Missing fits,
missing point heads and rejected parent inputs are reported as coverage failures,
while independently valid rows continue. A malformed config or tampered artifact
fails the whole invocation before output creation.

## Output and interpretation

The output directory must not already exist, even if empty. Outputs are:

- `margin_report.json`: retained PMFs, source/parent hashes, mean/median/mode,
  predictive intervals, same-PMF winner probabilities, cover ladders, simulation
  counts/receipts, coverage and status axes;
- `margin_card.html`: readable summary and hypothetical handicap tables;
- `draws/*.npy`: actual integer margin draws with raw-byte and file hashes.

There is no command-line clock override. `execution_started_at_utc` and actual
completion `created_at_utc` are separate. Time-status labels are calculated at
completion, after draws are written, so crossing kickoff during execution cannot
be mislabeled as pregame. Missing start times remain unavailable. New child
reports never self-certify prospective eligibility.

Default handicap ladders depend on sport. A custom ladder is explicit:

```bash
python scripts/run_margin_system.py --input source.json --output new-output \
  --home-spreads=-7,-6.5,-3.5,-3,0,3,3.5,6.5,7
```

Every ladder is **HYPOTHETICAL**, with no acquired market quote, sportsbook price,
vig, expected return or bet recommendation implied. A mean-implied home spread
is `-E[M]`; a median-implied spread is `-median(M)`. Neither is a fitted market
price. The analytic cover output keeps win, half-win, push, half-loss and loss.
Model fair decimal prices use winning and losing stake probabilities, including
half outcomes; they exclude vig and costs.

The 50%, 80% and 95% intervals describe predictive game-margin variability.
Integer endpoints can cause the attained probability to exceed the nominal
level. Wilson intervals in simulation diagnostics describe **Monte Carlo error
conditional on a fixed PMF**, not model accuracy, training uncertainty, or
simultaneous confidence over a complete ladder. Increasing draws does not add
observed games or validate the forecast.

All seven leagues appear in coverage. `NO_MARGIN_INPUT` does not mean no games
were scheduled. Totals and joint scores are not fabricated from marginal PMFs.
The recovered repository is partial, so global health remains
`INCOMPLETE_PARTIAL_SNAPSHOT`, action authority remains false, and predictive and
prospective acceptance remain separate work.

Controlled report status axes are `execution_status: COMPLETED` or `PARTIAL`
(partial when a supplied product was refused), `predictive_validation:
UNVALIDATED`, `publication_eligibility: INELIGIBLE`, and `wagering_authority: OFF`.
Completion describes executed computation only. These artifacts are research
reports, not eligible production forecast publications or prospective registrations.

## Checks

```bash
python -m unittest discover -s tests -p 'test_margin_system*.py' -v
```

Card checks cover exact source hashes, source immutability, no overwrite,
simulation-byte verification, event/settlement/information-set identity,
handicap orientation, missing points, explicit market-input refusal, metadata
conflicts, post-start completion, escaping and CLI execution. Synthetic fixtures
validate implementation behavior only. Retrospective validation, current input
assimilation and prospective performance must be reported separately.
