# NFL spread calibration v1

Implemented and fitted a full-game spread calibration overlay for
`nfl.integrated_context.combined.v1.research`. This is a separate fitted research
output, not a replacement of the original forecast or an assertion of reliable
betting calibration. Original forecasts, final-score draws, SRS/EPA/B1/B2 arms,
and wagering authority remain unchanged.

## Design and chronology

Design SHA-256: `bd8cd3f7e5ba230adf56831aac941ba078adf6d6104a0e3e3473eb098e385a31`.
The design was written and saved persistently before fitting. It is a local
research design, not canonical prospective registration. Fit 2020–2022 (797
games); evaluate 2023–2025 (816 games, including 19 spread pushes). The historical
frame has already been used by this research program. No 2026 outcomes enter
fitting or evaluation, and the fit is not revised after evaluation.

The reference for each historical game is the exact weighted home-margin
marginal of `OUTCOME_ALIGNED_FINAL_SCORE_KERNEL_V2`. Each game's football
prediction is out of fold; its residual-score pool and final-tie rate use only
seasons earlier than the game. Two 2020 games lack conditional score support and
are explicitly excluded: `2020_01_GB_MIN`, `2020_06_KC_BUF`. All 816 test games
are supported. Final scores include overtime; no extra OT or coin flip is added.

## Transform

For the raw home-margin CDF F, fit:

`G(F) = sigmoid(a + b * logit(F))`, with exact `G(0)=0`, `G(1)=1`, and `b>0`.

Fixed penalized three-way negative log likelihood, not a test-selected grid:
`mean NLL + 0.01*(a^2 + log_b^2)`, L-BFGS-B, initial `(0,0)`, bounds ±2 for
both a and log_b. Fitted **a=0.0207865074**, **b=0.5277000176**.
No isotonic/alternative-family search or post-test threshold change occurred.

At home handicap h, with M=final home score minus final away score:

- Home cover: `1-G(P(M <= -h))`.
- Push: `G(P(M <= -h))-G(P(M < -h))`.
- Home fail: `G(P(M < -h))`.

Away contracts reverse cover/fail while preserving push. All alternate lines
come from one monotone CDF. Half-point contracts have zero ordinary-score push
mass. Integer contracts retain a third outcome. The transformed margin
expectation may differ from the original mean; that is not serialized as a
replacement football prediction. Original analytic win and total heads are
not claimed consistent with this separate margin distribution.

## Held-out retrospective results

Lower is better. Three-way Brier sums the three squared class errors;
binary Brier is a separate metric on the 797 nonpush games.

| Metric | Raw score kernel | Fitted calibration |
|---|---:|---:|
| Three-way Brier, 816 games | 0.546770 | 0.528574 |
| Three-way log loss | 0.798124 | 0.784503 |
| Conditional nonpush Brier, 797 games | 0.262645 | 0.253136 |
| Conditional nonpush log loss | 0.721486 | 0.699691 |

Paired three-way Brier delta **−0.018196**. Season-block 95% interval
**[−0.021632, −0.012849]**; secondary game-block interval
**[−0.025926, −0.010439]**. Each uses 10,000 resamples with frozen seed2026091412.
Only three test seasons exist; the narrow season interval is not a broad
uncertainty guarantee. All three individual seasons show score improvement.
The predeclared >=0.002 improvement / negative CI upper / no-worse log-loss
screen passes. This is a scoring improvement, not a calibration certificate.

The same-line proportionally de-vigged historical spread-price benchmark scores
**0.250220** conditional nonpush Brier—better than the calibrated arm. Historical
price observation timestamps are unavailable, so this is not a timestamp-matched
executable edge test. Odds were not predictors or fit targets; the observed
spread defines the settlement target.

## Material unresolved weakness: key-number mass

On 333 integer-line test games, predicted push probability averaged **3.24% raw**
and **1.79% calibrated**, versus **5.71% observed**. At absolute line3 specifically,
119games include13pushes (10.92%); calibrated mean push mass is only1.79%.
The calibration improves overall scoring while making push-frequency bias worse.
This is a concrete remaining model defect. Integer-line outputs explicitly carry
`PUSH_RELIABILITY_WORSENED_IN_HELDOUT_TEST`; no whole-number pricing validation
is claimed. A monotone CDF mapping cannot create score support absent from the
reference. A future key-number mass experiment must be separately specified and
must not be presented as independently confirmed on this same reused test set.

Fixed-width reliability bins, class counts, Wilson descriptive intervals,
per-season results, Week1/line-type/favorite subgroups and all per-game predictions
are saved. Lower Brier alone does not establish reliability, as explained in
[scikit-learn's calibration documentation](https://scikit-learn.org/stable/modules/calibration.html).

## DEN at KC: new overlay on the frozen forecast

Original forecast cutoff2026-09-14T09:25:55.427062Z. No source refresh or football
refit is implied. The calibration artifact was created later and is explicitly
marked unavailable at the original forecast cutoff.

| DEN +2.5 | Probability |
|---|---:|
| Original100,000final-score draws | 60.869% |
| Fitted CDF transform of those draws | 56.3143% |
| New100,000calibrated margin draws | 56.352% |

The new simulation is a **margin simulation**, not a drive or joint team-score
simulation. Seed16204868016266292140; arraySHA-256
`eea77bfc3bf9a29e3c78acd5a7a3bc75ba068a7ecec6c428f31cf8d7b1d275fe`.
The empirical input is the original preserved sample, so its sampling uncertainty
still exists. At the user's pictured52¢ purchase, the transformed model gap is
**+4.3143percentage points before fees**, assuming $1win/$0loss. No executable
current price or positive real-world EV is established.

## Commands and integration

Existing forecast: no regeneration required.

```bash
python scripts/run_nfl_spread_calibration.py \
  --forecast-directory data/nfl/contextual_v1/mnf_run_03/2026_01_DEN_KC \
  --home-spread -2.5 \
  --output NEW_OVERLAY_DIRECTORY
```

Future source-bound pregame runs can emit the overlay in the same command:

```bash
python scripts/run_nfl_integrated.py --date YYYY-MM-DD \
  --model-id nfl.integrated_context.combined.v1.research \
  --home-spread -2.5 --simulations 100000 --output NEW_RUN_DIRECTORY
```

Handicap is HOME-oriented; for DEN at KC, `-2.5` means KC−2.5 / DEN+2.5.
Use `--event-id` on multi-game dates when supplying a game's line; repeat
`--home-spread` for alternate lines for that event. The calibration model is
bound to the exact combined football coefficient artifact and score-kernel ID.
Market-aware/live/other football arms require their own calibration fits and
are explicitly rejected rather than silently reusing combined's transform.
The canonical adapter exports `calibrate_spreads`; output is separate from the
frozen forecast JSON, with its own timestamp, calibration hash, source hash,
margin draws and manifest. Writer never overwrites an existing overlay directory.

Refit from the frozen design and original datasets:

```bash
python scripts/fit_nfl_spread_calibration.py \
  --design data/nfl/spread_calibration_v1/design.json --output NEW_FIT_DIRECTORY
```

41 focused NFL tests pass, including hand-computed key-number settlement,
monotone alternate lines, opposing-side consistency, exact sampler matching,
seeded replay, source/arm mismatch rejection and nonmutation. Full repository
health is not established from this partial local checkout. New CI covers the
same NFL tests. This module does not calibrate totals, first halves or live bets.
