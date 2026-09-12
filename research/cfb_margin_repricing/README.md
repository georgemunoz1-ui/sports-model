# CFB frozen margin repricing

Append-only research utility. No refit, new predictive inputs, forecast overwrite, production integration, or action authority.

Run from repository root:
```sh
python -m unittest discover -s research/cfb_margin_repricing -v
python research/cfb_margin_repricing/reprice.py --bundle research/cfb_context_fix/results_02/bundle.json --event-id 401856810 --home-line -6.5 --total-line 49.5 --output /tmp/byu_repricing_new.json
```
Output must not exist. Source model is cfb.team_context_heads.v0_1.research. Uses original full-margin histogram; integer inverse-CDF quantiles. Half-point home spreads only. Model probability uses frozen normal parameters; simulation probability uses original counts. No key-number calibration. First-half inputs cannot become full-game totals. Whole-number/quarter lines and period mismatches reject. Full-game total returns UNSUPPORTED with null probabilities.

## BYU vs Arizona, September 12
Frozen forecast cutoff 19:09:15Z (12:09 PM PDT). Child generated after scheduled kickoff; NOT a live update or a new prospective forecast. User-supplied BYU -6.5 and total49.5 have no independently verified book, price or observation timestamp.

BYU expected margin +17.93147; model cover71.72648%; preserved100K simulation cover71.949% (71,949 covers /28,051 noncovers). MC standard error0.1421 percentage points describes sampling only, not model uncertainty. Margin P10/P25/P50/P75/P90: -7/+5/+18/+31/+43, BYU-oriented. Arizona +6.5 probabilities28.27352%/28.051%. Total49.5 UNSUPPORTED.

Nine targeted tests pass. Original ordered draws reproduced to full SHA and match every frozen histogram count. Parent unchanged. Whole-repository health not verified: canonical checkout unavailable locally. Source head0588f590043a2e6e1c9ecfbca64a7d270a41fd92. Research uncertainty remains uncalibrated, starting QBs unconfirmed, player impact absent. This patch does not establish model accuracy or betting value.
