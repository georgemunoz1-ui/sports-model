# MLB remaining-issue repair and postseason challenger review — October 6, 2026

**Engineering paths implemented; predictive adoption rejected.** The new challenger uses information the older kernel only displayed, but the held-out screen got worse. The unchanged selected model, original postseason arm, old forecast bytes, NO_PROMOTE verdict, and action authority remain intact. PR #58 remains draft and unmerged, stacked on draft PR #51; this is not an automatic change to the recurring workflow.

## Predictive screen — 2025 later-period holdout

Lower Brier and log loss are better. All rows below use the same 44 eligible games and 11 series. Each raw arm used 100,000 simulations per event; the calibration row is a deterministic transform of the raw full-context probability, not another simulation run. Historical inputs were rebuilt from sources captured now; they are **retrospective, date-filtered reconstructions**, not certified historical pregame packets. Actual original lineup/starter identities are recovered from final boxscores. All historical arms use neutral park factor 1.0, so this does not validate the full current park-adjusted pipeline.

| Arm | Binary Brier | Log loss | Brier minus baseline |
|---|---:|---:|---:|
| Unchanged postseason baseline | 0.25004 | 0.69339 | +0.00000 |
| + Starter workload | 0.25151 | 0.69645 | +0.00147 |
| + Posted lineup composition | 0.25416 | 0.70179 | +0.00411 |
| + Roster bullpen / recent usage | 0.25589 | 0.70517 | +0.00585 |
| + 2024-fitted calibration | 0.26430 | 0.72358 | +0.01426 |

The full-context Brier delta is +0.00585, with paired series-bootstrap 95% interval **[+0.00014, +0.01229]**. The calibrated delta versus baseline is +0.01426, interval **[+0.00133, +0.02961]**. These are small-cohort exploratory intervals over 11 blocks; no multiplicity or historical point-in-time certification is claimed. Workload and lineup intervals cross zero. None supports promotion. Raw win rate is secondary and cannot reverse this probability-quality result.

Calibration was fitted only to 41 eligible 2024 postseason games, with a positive logit slope of **1.853767**. It worsened 2025 performance and is retained as a failed candidate, **not applied to the selected card**. The 2025 set is now opened: later redesigns need a new untouched or prospective evaluation population.

The predeclared design was committed at `974d6a8a560b91c063062a3434dcd72ecb9a5766` before scoring. Coverage: 2023 development 37/41; 2024 calibration 41/43; 2025 holdout 44/47. All nine exclusions remain named: five dated-roster/starter conflicts and four missing qualifying starter histories. They were not patched with later outcomes or neutral values. Captured evidence includes 811 official API responses, 131 postseason game boxscores, 262 dated roster snapshots, and full-season schedules/player logs. Exact source hashes, coverage, fitted state, per-game inputs, probabilities, seeds, and packed winner draws are retained.

## Current diagnostic execution

Latest freeze: **2026-10-06T21:51:00.015763+00:00**, 2:51 p.m. Pacific; all four successful runs preceded their scheduled starts. These are explicit research diagnostics, not a replacement betting card.

| Event | Separate arm | Away win | Home win | Disposition |
|---|---|---:|---:|---|
| LAD @ ATL | workload.v2 | 50.541% | 49.459% | PRE_START diagnostic |
| LAD @ ATL | lineup.v3 | 50.886% | 49.114% | PRE_START diagnostic |
| LAD @ ATL | bullpen.v4 | 48.503% | 51.497% | PRE_START diagnostic |
| MIL @ SD | workload.v2 | 51.948% | 48.052% | PRE_START diagnostic |

The MIL lineup was absent in the 2:36 p.m. source capture. Its lineup and bullpen arms correctly blocked; workload continued. Calibration was deliberately not bound for current use after its failed screen. Monte Carlo uncertainty is about ±0.31 percentage points, not a model-confidence interval. No score, total, run-line or wager output is supported. No later confirmation is implied.

Numerical consumption is now explicit: Yamamoto/Sale starter means 6.192/6.275 innings; May/Pivetta 4.150/4.775, each shrunk under the registered workload policy. LAD/ATL lineup offense multipliers 0.991/0.979 and bullpen run-rate proxies 3.495/3.170 are consumed by their respective arms. These are model estimates, not announced workload limits or proof of superior baseball forecasting.

## What changed

- Distinct arms for empirical starter workload, lineup offense, current roster reliever quality/usage, and calibration. No blending into the original engine.
- Explicit opener/bulk and pitch-cap input contract, with reviewed source receipts and innings/pitch unit checks. Current games have no captured announced cap/bulk plan, so none is asserted. This branch has regression tests, not current announced-opener validation.
- Availability acts through eligible personnel and the actual lineup; missing lineup blocks the affected arms. No double injury penalty or invented injury-severity coefficient.
- Official dated roster, transaction and R/F/D/L/W player-history acquisition; strict prior-date feature construction; required source and player census, receipt hashes, review chronology, starter/event identity, and actual writer clock.
- Append-only diagnostic artifacts, same-request idempotency, retained 100,000-draw arrays and exact replay. First-freeze hashes were committed at `ffa3caf580cb55b2606a0d64f0c1e0b851c9486c` before first pitch. Canonical prospective grading remains false.
- Atomic no-clobber raw capture prevents concurrent identical-response partial-file races. A real failed historical attempt is retained. Historical parsing now distinguishes postponed rows even when the provider's abstract state says Final. Optimizer NumPy scalar conversion is explicit; these repair attempts and logs are preserved.

## Verification

**40 targeted tests passed.** Four additional current-source negative checks rejected a missing game-phase source, review before source capture, wrong phase URL, and missing transaction source. The latest four forecasts replay exactly and identical retries return the same run IDs. All 122 historical packed-draw files match retained hashes; representative games from all three seasons reproduce baseline plus three challenger winner draws exactly. Historical evaluation executed 48.8 million paths across the 122 matched games and four arms; that is computation count, not predictive validation. Reliability/bin counts, series-bootstrap intervals, incremental ablations and extra-inning/workload/favorite/realized-total slices are in the evidence.

The nine original postseason model pins remain unchanged. Full repository health was attempted from a partial source snapshot and cannot be certified; missing local modules/data are not newly established repository defects. Existing RED obligations remain binding.

## Issue cards

| Issue | FIXED | NOT ESTABLISHED | REMAINING | NEXT EVIDENCE | Reproducibility tier |
|---|---|---|---|---|---|
| Workload / opener-bulk | Empirical workload consumed; source-bound cap/bulk contract; unit checks | Accuracy improvement; current announced opener case | Workload interval crosses zero; current announced roles absent | Capture a real pre-cutoff opener/bulk plan and grade a newly frozen diagnostic cohort | Executed source-bound workload; opener path test-only |
| Lineup / injury lag | Player IDs, shrunk lineup offense, roster eligibility and transaction capture | Injury severity, full postseason series-roster certification, platoon effects | MIL lineup missing; historical roster conflicts excluded | Final source-bound lineup and series roster, complete dated availability, prospective replacement-impact evidence | Current execution; historical retrospective reconstruction |
| Bullpen | Individual relief histories and 3-day pitch-load weights consumed | True manager usage/availability; predictive gain | Full-context held-out screen worsened | Redesign on development data under new identity; new untouched or prospective test | Executed, screen failed |
| Calibration / postseason accuracy | Fitted state, held-out Brier/log loss/reliability/bootstrap and slices created | Better predictive accuracy or market superiority | Calibration worsened; small holdout, no matched authentic market cohort | Preserve failed fit; prospective same-event market-blind model/market grading and existing promotion gates | Retrospective evaluated; no adoption |
| Integrity / storage | Atomic capture, source census, review binding, immutable receipts and exact replay | Canonical prospective registry / complete repository health | Full canonical ledger/artifact verification, merge and deployment acceptance | Complete-checkout registry validation and a new pre-start writer-registered cohort; never upgrade old flags | Local execution plus committed hash anchor |
| Operational integration | Explicit audited/context commands implemented and executed | Automatic use by old entry points | PR #51/#58 unmerged; selected/default flow unchanged | Review/merge through repository gates, then execute deployment acceptance | Branch implementation, not deployed |

Historical exclusions, active-player injury severity, manager intent, future prospective outcomes and authentic contemporaneous market data cannot be manufactured to turn these cards green. Weather, defense, platoon and score settlement are explicitly outside this winner-only increment. No standing-health triage session was appended or aging reset in this development task.

`EXECUTION_STATUS: COMPLETED` for the reported diagnostic/evaluation runs; `PREDICTIVE_VALIDATION: HOLD` overall, full-context/calibration baseline screen failed; `PUBLICATION_ELIGIBILITY: INELIGIBLE`; `official_release_eligible:false`; `canonical_registration:false`; `prospective_grade_eligible:false`; `WAGERING_AUTHORITY:OFF`; dose `0.0`.

## Commands

```bash
python3 scripts/mlb_context_history.py --root NEW_HISTORY_DIR --years 2023 2024 2025
python3 scripts/evaluate_mlb_postseason_context.py --root HISTORY_DIR --design research/registrations/mlb_postseason_context_design.json --output NEW_EVALUATION_DIR
python3 scripts/mlb_context_current.py --root NEW_CAPTURE_DIR --date YYYY-MM-DD
# Inspect sources and supply a hash-bound event-specific review.
python3 scripts/run_mlb_postseason_context.py run --root CAPTURE_DIR --review REVIEW.json --contract research/registrations/mlb_postseason_context_v2.json --output NEW_RUN_DIR
python3 scripts/run_mlb_postseason_context.py verify --run NEW_RUN_DIR/runs/RUN_ID
python3 -m unittest research.test_mlb_postseason_context research.test_mlb_postseason_audited research.test_mlb_postseason_v1 research.test_mlb_postseason_workflow -v
```

Frozen first-run contract v1 remains in history; its original source snapshot is commit `ffa3caf`. Contract v2 records only evaluator/interop implementation fixes, with the numerical kernel unchanged. Replay old runs using their bound source revision.
