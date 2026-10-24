# CFB capability repair — October 3, 2026

Implemented an isolated empirical joint final-score challenger, selected-state
consumption verifier, and event-bound context acquisition path. Incumbent code,
model defaults, state.json, and frozen morning forecasts remain byte-identical.

## Executed evidence

- FBS-only score population enforced; 11,835 training games through 2023;
  1,427 matched 2024-25 evaluation games.
- Joint winner Brier 0.192807 vs same-feature logistic control 0.187823.
  Paired season-week bootstrap delta interval [0.001643, 0.008517].
  Screen FAILED; no replacement, blend, or promotion.
- Joint margin MAE 13.1875; total MAE 12.7916. Central-80% interval coverage
  83.11% margin, 83.81% total. Cover/total quote-based calibration unestablished.
- 13 fresh pre-start diagnostic forecasts, 100,000 paired score draws each,
  all arrays replayed exactly. Score, winner, margin, total, handicap and push
  arithmetic share one discrete empirical distribution. Hypothetical half-point
  and integer curves are retained; they are not sportsbook quotes or approved
  pricing. A quote-binding adapter remains absent and rejects supplied quotes.
- 331 eligible 2026 finals reproduce the selected team state exactly. All 62
  upcoming event feature rows have current-season effects. This proves selected
  state/input binding only, not full CFB assimilation acceptance or official
  source coverage. Mean absolute fixed-head probability effect versus
  historical-only team state is 0.101188.
- Weather provider fields captured for 13/13; availability 0/13. Weather units
  remain unverified; current personnel and weather remain numerically unconsumed.
- 16 regression tests cover score coherence, deterministic draws, integer pushes,
  half-point pushes, wrong subdivisions, duplicate/future results, corrupt state,
  invalid lines, timezone refusal, and unknown/late/wrong-event context.

## Unresolved requirements

The broad current-season assimilation gate remains HOLD: provider-bound complete
schedule lineage, roster/transfer/depth-chart identity and source bindings are
still missing. Current context needs historical PIT observations, validated
units/player mapping, chronological fitting and actual runner consumption.
No injury records is UNKNOWN, not healthy. Full official clearance cannot be
created by replacing these gaps with zero adjustments.

Legacy margin artifact declares FBS-only n=36,901, but its fit script does not
filter subdivision. The underlying table has only 17,472 FBS/FBS rows. Preserve
that artifact; it is not accepted as a shortcut to current cover validation.

## Commands

python scripts/run_cfb_joint_empirical.py --features data/cfb/model/cfb_v1_features.parquet --history SOURCE/binary/schedules/parquet --output NEW_DIRECTORY
python scripts/verify_cfb_consumption.py --source SOURCE --package PACKAGE --output NEW_RECEIPT.json
python scripts/capture_cfb_context_review.py --package PACKAGE --date 2026-10-03 --output NEW_CONTEXT_DIRECTORY
python -m pytest tests/test_cfb_joint_empirical_v1.py -q

Artifacts are isolated and append-only. Historical availability/PIT remains
unproven. Existing repository release-health failures remain separate. Local
syntax/replay checks passed; whole-repository CI was not claimed green.
ACTION OFF; official release remains RED.
