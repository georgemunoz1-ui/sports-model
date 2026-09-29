# NHL joint-score recovery and validation — September 29, 2026

Report written 2026-09-29T23:24:09.620248+00:00. Research only; action OFF, dose 0.0.

## Completed and remaining

| Request | Executed result | Remaining |
|---|---|---|
| Persistent evidence and registry | 15 immutable research entries; full original archive committed, 45/45 Git blob hashes verified | Library file service still returns transfer_failed; canonical main registry not changed |
| Exact settlement binding | Official DraftKings rule text reviewed: full-game OT included, one shootout goal added | Screenshot book/jurisdiction and applicable version not proven; book_rules_bound remains false |
| Bootstrap | 10,000 paired ISO-week resamples, 26 blocks; monthly sensitivity also executed | Retrospective, not prospective or market superiority |
| Log loss/reliability | Both home and away −1.5 metrics and fixed-decile reliability; diagnostic calibration fit | No calibration coefficients applied |
| Error slices | One-goal, REG/OT/SO, frozen-model favorite strength, predicted scoring environment; PBP marker audit below | No-marker is not certified absence; sparse slices cannot support decisions |
| Goalie/player increment | Separate acquisition contract, source paths, actual capture receipts, 10 input-gate tests | Official roster requests failed HTTP 403; no confirmed goalies, no fitted personnel effects |
| Prospective evaluation | Immutable evaluation protocol and 15-entry ledger; 14 entries timing eligible, zero grades | Collect finals and bound market snapshots; Montreal–Toronto excluded from strict prospective cohort |
| Arm separation | Initial winner-only model and joint-score challenger remain distinct | No promotion, blend or action authority |

## Evidence identities

- Registry commit: [1263fe95](https://github.com/georgemunoz1-ui/sports-model/commit/1263fe95d3fe766364aee295f66adf2dddab0e78).
- Frozen archive: [73288361](https://github.com/georgemunoz1-ui/sports-model/tree/732883617df2dea08d76ba627b6cea2510472732/data/research/nhl/joint-score-20260929/archive).
- Original archive SHA256: `f8978a1772d8a8030b3a27ce3f5b5ecbdd63c5081010a12156e78257ad5d978c`.
- Publication clock: September 29 23:05:22 UTC / 4:05:22 p.m. Pacific. Montreal–Toronto retained schedule start is 23:00 UTC; screenshot says 23:10. Conservative earlier schedule controls registration eligibility. Original local forecasts were frozen at 22:46 UTC; late persistence is not backdated.
- Research branch registration does not rewrite `canonical_registration:false` in old artifacts, change defaults or confer official clearance.
- Verified 95 original manifest files unchanged and 15/15 seed/draw replays exact. These are reproducibility checks, not predictive validation.

## Same-population historical evaluation

Training: 4,804 games, seasons 2021–2024. Bandwidth chosen on 1,312 season-2025 games. Audit: 1,312 season-2026 games. The 2026 cohort had previously been viewed in aggregate and is not untouched prospective evidence. Historical point-in-time source availability is unproven. Unconditional comparator uses training outcomes only; it is neither the old winner-only model nor the market.

| Home −1.5 metric | Challenger | Unconditional training baseline | Difference |
|---|---:|---:|---:|
| Brier | 0.20947077 | 0.21111005 | -0.00163928 |
| Log loss | 0.60949945 | 0.61334259 | -0.00384315 |

home_minus1_5_brier_bootstrap: 95% percentile interval [-0.002720180866421118, -0.00039231515903954576]; 26 week blocks, 10,000 resamples, PCG64 seed 20260929. Negative challenger-minus-baseline is better.

home_minus1_5_log_loss_bootstrap: 95% percentile interval [-0.006199452002434872, -0.001122586900931952]; 26 week blocks, 10,000 resamples, PCG64 seed 20260929. Negative challenger-minus-baseline is better.

home_minus1_5_brier_month_sensitivity: 95% percentile interval [-0.002813490639661486, -0.0003046388849270401]; 7 month blocks, 10,000 resamples, PCG64 seed 20260929. Negative challenger-minus-baseline is better.

The original broader four-margin-category delta remains {'ci95': [-0.004461808178311523, 0.0005555300634960066], 'mean_delta': -0.002171806467329466}; its interval crosses zero. The winner improvement interval also crosses zero. Secondary puck-line gains do not establish overall superiority.

Average home −1.5 prediction: 32.71%; observed: 30.11%. Fixed-decile ECE: 2.66 percentage points. Diagnostic calibration fit: intercept 0.415, slope 1.747; NOT applied.

| Probability bin | Games | Mean forecast | Observed cover |
|---|---:|---:|---:|
| 20%–30% | 140 | 29.15% | 19.29% |
| 30%–40% | 1150 | 32.91% | 31.39% |
| 40%–50% | 19 | 42.89% | 31.58% |
| 50%–60% | 2 | 54.66% | 0.00% |
| 60%–70% | 1 | 64.99% | 100.00% |

## Error slices

Home −1.5; descriptive slices. Outcome-conditioned slices cannot be interpreted as unconditional calibration. No retuning based on these post-screen results.

| Slice | N | Brier | ΔBrier | Log loss |
|---|---:|---:|---:|---:|
| OT | 207 | 0.106651 | -0.000427 | 0.394839 |
| REG | 986 | 0.243270 | -0.002236 | 0.680083 |
| SO | 119 | 0.108278 | +0.001200 | 0.398068 |
| empty_net_explicit | 406 | 0.275377 | -0.002772 | 0.747169 |
| empty_net_no_explicit_marker | 770 | 0.170646 | -0.000605 | 0.528471 |
| empty_net_unknown | 136 | 0.232541 | -0.004116 | 0.657279 |
| model_favorite_50_60 | 1272 | 0.208760 | -0.002090 | 0.608004 |
| model_favorite_60_70 | 36 | 0.229486 | +0.016825 | 0.652025 |
| model_favorite_70_plus | 4 | 0.255348 | -0.024502 | 0.702236 |
| one_goal | 567 | 0.107296 | +0.000218 | 0.396138 |
| predicted_total_6to7 | 1308 | 0.209481 | -0.001683 | 0.609526 |
| predicted_total_7plus | 4 | 0.206067 | +0.012603 | 0.600653 |
| predicted_total_below6 | 0 | NOT ESTABLISHED | — | — |
| two_plus | 745 | 0.287234 | -0.003053 | 0.771883 |

PBP acquisition: 1176/1312 captured, 1176 final-score and goal-census reconciled. Explicit Empty Net markers are from provider play fields. No explicit marker remains a proxy-negative group, not official absence certification. All raw source bytes are preserved; no forecast input changed.

## Personnel and settlement boundaries

Actual personnel acquisition: 16/40 sources captured (15 event summaries plus one injury feed); 24 official roster requests returned HTTP 403. All confirmed-goalie fields remain null. Data captured after original cutoff cannot be retroactively consumed. The acquisition-only contract requires source/effective/retrieval/review timestamps before cutoff, official source, player/team IDs, bytes hash and manual review. No effect estimated or forecast adjusted.

[DraftKings official hockey rules](https://sportsbook.draftkings.com/es/help/sport-rules/hockey), document dated August 26, 2025, retrieved September 29, 2026: ordinary full-game markets include OT; NHL shootout settlement adds one goal to the winning side and total. Regulation/60-minute/period and Winning Margin props have different treatment. Interruption/void clauses need separate handling. This verifies conditional compatibility only; screenshots do not establish the exact operator/jurisdiction/rule version.

## Prospective discipline

14 frozen entries have durable publication before their retained scheduled start. Montreal–Toronto is archival-late. Zero entries are graded in this follow-up. Missing market quotes remain null. The protocol requires same-game paired comparisons, frozen versions, independently reconciled finals, idempotent grades and append-only corrections. No promotion conclusion before 500 timing-eligible grades over at least eight weeks and independent review; this minimum is not a pass. Personnel remains its own acquisition increment. Original winner-only and joint-score models remain separate.

Next evidence: exact sportsbook/jurisdiction binding; official pre-cutoff goalie/player source confirmations; prospective final-source grades. Neither the Vancouver discrepancy nor this retrospective result changes model selection or action authority.

`accepted_risk_release_override:false` · `official_release_eligible:false` · **Action OFF; dose 0.0.**
