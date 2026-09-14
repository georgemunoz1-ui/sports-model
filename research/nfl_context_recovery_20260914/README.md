# NFL pipeline recovery — 2026-09-14

The earlier MNF runner used the small SRS/Elo-margin baseline, not the most capable
preserved fitted NFL model. The personnel repository bundle at commit
`a411de6dc86666e4103b7037ee9dd8f5601eec53` contains the fitted
`nfl.rs.epa_logit_ridge.v0_2.shadow` model, causal feature builder, source PBP,
personnel capture/registration code, and original model pins.

Recovered bundle SHA-256:
`97a9889fe2be3b5c4cd5c1c53e972f499e2426cb924da1146ddf768408d67997`.

## What is restored

- Exact fitted 18-feature inference, exported from the pinned joblib artifact.
- EPA, success, explosiveness, protection, pace, prior score differential, rest,
  neutral venue, roof, temperature, wind, state experience, and missing flags.
- A market-free event context adapter, input-source timing checks, numerical
  contribution traces, portable reproduction, and explicit capability reporting.
- Separate 100,000-draw binary winner diagnostic and 100,000-draw legacy NFL
  drive-simulator bridge, preserving real ties as a third outcome.

The portable export matches the recovered model on all 3,167 feature rows with
maximum absolute differences below 1e-10. Eight targeted tests pass. The old
bundle healthcheck reports zero failures and two warnings, including stale MLB
data. This does not establish current repository-wide operational health.

## MNF result

Source model before weather refresh: Denver win 59.3039%, Denver by 1.8317,
total 44.4500. Current bound weather proxy: Denver win 58.9475%, Denver by
2.4284, total 45.3675. Weather changes the fitted Kansas City margin by -0.5967
points and total by +0.9176. Different fitted heads need not move together.

Weather is the NWS Kansas City city-point hourly bucket at 19:00 CDT, not an
Arrowhead station: 86 F, sustained wind 11 mph, gust 22 mph. The gust is retained
but is not substituted for sustained wind. Publication 2026-09-13 18:51 CDT.
This is a spatial proxy and the product is older than the later city day/night
forecast. An overnight low is never substituted for kickoff temperature.

Rest 7/7 is the inherited nflverse Week 1 schedule convention, not a verified
measurement of days since preseason activity. Its fitted difference is zero.

Final binary diagnostic: Denver 58.992%, KC 41.008%. This samples the fitted
binary probability and is not independent evidence of prediction quality.
Separate drive bridge: Denver 56.378%, KC 42.760%, tie 0.862%; mean scores
Denver 24.0631, KC 21.6222. Conditional Denver win excluding ties is 56.8682%.
Do not pool these probabilities: they use different distributions/targets.

## Remaining restoration gaps

The recovered personnel implementation explicitly binds context without changing
the registered probability. A later Sept 9 shadow registration has one-event
personnel point contributions, but no recoverable fitted general-purpose
personnel coefficient set. These one-event values were not transferred to KC.
No fitted travel-distance/time-zone effect appears in the recovered 18 features.
Those current facts are bound with numeric adjustment null. This recovery is
partial for the user's complete personnel/weather/travel integration request.

No player-value adjustment or validated full-current model is claimed. Inactives
and snap restrictions are not invented. Cooper is now confirmed on the official
Commissioner Exempt roster, while Simmons and Conner are officially out.

The drive code is recovered unchanged from
`19391558f866ae580defd7940794ce5914c04d91`. Its default drive parameters were not
fitted here. The new bridge matches its expected regulation scores to fitted
score centers; those source centers target final scores, so adding approximate
overtime is an acknowledged target mismatch. Its two-drives-per-team overtime
implementation is not a rule-exact clock simulation. Distribution, ATS, totals,
and tie-settlement calibration remain unestablished. It is an explicitly
separate research experiment, not a promoted forecast engine.

Original SRS/B1 outputs and model coefficients remain unchanged. Reused-history
performance claims do not establish prospective validation. The initial local
trial was superseded because publication timestamps were not established for
non-weather inputs; its invalidation is preserved. The final run uses null
publication timestamps where unknown and known available-by times.

## Execution

`python run_recovered.py` creates `results_final/` exclusively and refuses to
overwrite it. `python -m unittest discover -s . -p test_recovery.py -v` verifies
saved arrays and integration checks after the result arrays are restored from
the output package. Dependencies: Python, NumPy, SciPy. The fitted inference
export does not require unpickling an artifact or refitting scikit-learn.

The exact fitted joblib artifact hash is
`1d72eb8f27d5edfda781373455167ea921ef01a0b736e1096f337bf2a81cf18b`.
The full original bundle remains the recovery source for rebuilding causal
weekly features; this event runner is not a replacement for that history build.
