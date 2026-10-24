# MLB playoff research model — September 30, 2026

**Created and executed at 2:54 p.m. Pacific. Separate challenger; not promoted. Action OFF; dose 0.0.**

Model: `mlb.postseason.v13_empty_base_extras.research.v1`. 100,000 paths per event, NumPy PCG64. Winner estimate is Monte Carlo only; there is no independent analytic probability.

| Event | Start PT | Favored team | Win estimate | Status |
|---|---|---|---:|---|
| PHI @ ATL | 11 a.m. | PHI | 51.20% | POST_START_DIAGNOSTIC |
| CWS @ HOU | 2 p.m. | CWS | 53.30% | POST_START_DIAGNOSTIC |
| BOS @ NYY | 5 p.m. | NYY | 51.87% | PRE_START_PROVISIONAL |
| CHC @ SD | 7 p.m. | CHC | 51.05% | PRE_START_PROVISIONAL |

The first two events were already started at acquisition. Their scores were available in raw schedule/feed evidence but were not extracted into predictive inputs. They are not live probabilities, backdated forecasts or grading evidence. No evaluation of those observed outcomes was used to choose coefficients.

## What was built

Frozen V13 nine-inning Gamma–Poisson paths are retained unchanged. Only tied-nine-inning winner resolution changes: independent empty-base Poisson extra innings use inherited team run-prevention, offense, park and HFA rates until a winner is resolved. No automatic runner and no playoff boost. The inherited starter-length prior remains 5.4 innings with SD 1.3; no postseason hook or reliever-deployment adjustment was fitted. This remains a coarse probability model, not a play-by-play simulator.

MLB official rule source: https://www.mlb.com/news/mlb-playoff-format-faq (September 1, 2026; postseason uses no automatic runner). Only winner output is exposed. Run-line, score and total settlement are not established, including walk-off scoring details.

## Actual inputs and omissions

- 2,433 completed prior-date games: 2,429 regular-season and four September 29 postseason finals; full 30-team census. All current-day results excluded.
- Eight observed starter profiles from official regular-season game logs, filtered strictly before September 30. Their ERA/K/BB, sample sizes, team runs for/against and park factors entered the calculation.
- Official schedule/feed identities and probable starters reconcile: Sánchez/Mahle; Burke/Brown; Gray/Fried; Gausman/Pivetta. Probable identification is not a promise they will start.
- Source capture approximately 2:48 p.m. Pacific; each raw response/hash and actual retrieval timestamp retained. Provider-original lineup confirmation timestamps unavailable.
- Boston/New York batting orders were posted; Cubs order absent, Padres order posted. Those lineups and captured weather were reviewed but not numerically consumed.
- Current injuries, bullpen fatigue/availability, postseason starter hooks and tactical reliever selection are unconsumed. No market inputs or overlays.

## Comparison to the unchanged V13 tie proxy

| Event | Original V13 home win | New home win | Difference, pp | Nine-inning tie frequency |
|---|---:|---:|---:|---:|
| PHI @ ATL | 48.811% | 48.796% | -0.015 | 11.05% |
| CWS @ HOU | 46.683% | 46.696% | +0.013 | 10.75% |
| BOS @ NYY | 51.909% | 51.871% | -0.038 | 10.96% |
| CHC @ SD | 49.673% | 48.946% | -0.727 | 10.73% |

Both columns share exactly the same underlying nine-inning draws. Differences concern extra-inning handling only. This sensitivity is not evidence of improved accuracy. Monte Carlo 95% intervals are approximately ±0.31 percentage points; they exclude model and input uncertainty.

## Verification and registration

- Nine targeted unittest checks passed: replay, full probability mass, unchanged non-tied paths, input rejection, effect direction, unsupported-product suppression, review binding and post-start refusal. Four actual event replays matched every retained array exactly.
- Model/code contract committed before numerical event execution at code commit `0fbfdfb79e1af16a258946eaa8d641a63ef13823`. Each run binds package, model, code, agent review, input and draw hashes with actual writer time.
- Local immutable research receipts are retained. Canonical forecast registration and prospective-grade eligibility remain FALSE. No official clearance or automatic-default change.
- Existing healthcheck exited 1: 11 failures, six warnings including longstanding recovery and local environment limitations. This research build does not close those obligations.
- Regular-season defaults, September 14 packet pins, the old forecasts, original model source and the active Phase-4 experiment remain unchanged. State gains one separate shadow-candidate reference on the draft branch only.

## Validation plan and issue card

**PREDICTIVE_VALIDATION: UNVALIDATED.** Zero completed held-out postseason games evaluated for this candidate. It inherits regular-season coefficients; regular-season evidence cannot establish postseason performance. First collect source-bound historical postseason inputs, predeclare chronological development/holdout splits, then compare matched-event Brier/log loss and calibration with the frozen baseline. Retain prospective postseason results and use season/series blocks for uncertainty. No coefficients change from this slate.

**MLB-PS-001:** FIXED — executable explicit postseason winner challenger, input checks and retained replayable paths. NOT ESTABLISHED — postseason calibration, market superiority, canonical registration, full score settlement. REMAINING — lineup/availability/deployment increments and chronological postseason evaluation. NEXT EVIDENCE — matched baseline/challenger postseason grading from frozen eligible cards; acquire current reliever and starter-workload data for a separately registered increment. Reproducibility tier: exact local code/input/draw replay, not predictive validation.

`EXECUTION_STATUS: COMPLETED`  
`PREDICTIVE_VALIDATION: UNVALIDATED`  
`PUBLICATION_ELIGIBILITY: INELIGIBLE` (official release)  
`WAGERING_AUTHORITY: OFF`  
**Action OFF; dose 0.0.**
