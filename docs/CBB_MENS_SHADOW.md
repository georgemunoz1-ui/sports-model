# Men's college basketball research baseline

The CBB sidecar uses its own score model, datasets, evaluation and grading population. The shared production selector and all existing league forecasts are separate. Use frozen dates and new directories; original cards never get retroactive forecasts.

## Daily operation

From the repository root with NumPy, pandas and pyarrow installed:

```sh
python scripts/cbb_shadow.py capture --date YYYY-MM-DD --inputs NEW_INPUT_DIR
python scripts/cbb_shadow.py card --date YYYY-MM-DD --inputs NEW_INPUT_DIR --output NEW_FORECAST_DIR
sha256sum NEW_FORECAST_DIR/card.json
python scripts/verify_cbb_shadow.py --inputs NEW_INPUT_DIR --run NEW_FORECAST_DIR --card-sha256 RAW_SHA_FROM_ABOVE --out NEW_RECEIPT.json
```

Keep the input directory, output directory, independently recorded forecast hash and verification receipt. Supply the official slate date in America/Los_Angeles. Acquire both-side lines/prices as a **separate** capture; attach only after freezing forecasts. A cover probability requires a defined side, line and full-game settlement. Missing prices cannot produce an executable evaluation. GitHub hosting or a production scheduler is not implicit in the CLI.

The source collector stores immutable season bytes under the hoopR commit recorded in each URL and retrieves ESPN group-50 schedule/scoreboard snapshots. A positive match to recognized ESPN D-I conference IDs on both sides is required. Independents, teams with missing affiliation, and teams moving divisions need explicit separate evidence; inspect exclusions and reconcile each day's coverage to the official NCAA schedule. Other opponents stay on the coverage ledger. The writer checks official status and actual time before issuing a diagnostic forecast, retains source and input hashes, and copies only allowlisted score, team, venue, date and status fields into the prediction path.

## Numeric procedure

* Estimate the venue scoring margin on nonneutral court games, and the overall points total, from 2021–22 through 2023–24 inclusive. Warm each team's ratings on those seasons. Hold the venue adjustment and total constant after that period.
* Project home margin from the venue adjustment and the difference in team strength ratings. Project total from the sum of the team scoring-environment ratings and the training-period mean. Derive two point-score means from projected margin and total.
* At the end of each earlier Pacific game day, apply opposite updates of 0.08 times the margin residual to the two team strengths. Apply 0.05 times the total residual to each team's scoring-environment rating. Retain 50% of both ratings when the season changes. Games never assimilate themselves or same-day targets. Newly admitted teams need five prior verified D-I games on both sides before forecasting.
* Collect paired out-of-sample home/away score residuals during 2024–25, center them by side and freeze the bank. For each matchup, add these paired residuals to its score means; round to nearest integers and condition on legal nonnegative, unequal final scores. This is a distribution of completed official final scores, including overtime. It is not a separate overtime possession simulation. The exact PMF means can differ slightly from the point-score heads after integer rounding and conditioning. Take home-win probability and both full-game spread and total marginals from that single empirical law, then draw 100,000 paired home/away scores with PCG64. The raw inputs contain no player/lineup model or pre-season transfer adjustments.
* Hold out 2025–26 for sequential retrospective evaluation (5,747 scored games among 5,752 eligible completed D-I pairs). Five failed the prior-history rule. The comparison is a venue-specific home-win rate, venue mean margin and unconditional mean total from the fitting window. The empirical bank has 5,754 earlier pairs. Historical data are archived final-status rows with prior-local-day chronology; original historical provider publication times are unverified. This is not a registered prospective validation or a market comparison.

For November 4, 2026, the historical reconstruction produced margin MAE 9.6022, total MAE 13.9254 and winner Brier 0.1847 on the 2025–26 holdout. The reference priors scored 11.6426, 16.1771 and 0.2307. The new prospective diagnostic slate consumed 140 current-season D-I finals, including 19 on November 3. All 26 scheduled rows were accounted for, including 10 in-scope pre-tip forecasts. Wagering authority is off.
