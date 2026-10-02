# October 2, 2026 — completed limited-feature research run

Eight actual pregame winner forecasts, 100,000 retained Bernoulli draws each; total 800,000. Original seeds replayed exactly in the runner and independently after artifact retrieval. All 290 files covered by the original CFB/NHL manifests passed local SHA-256 verification. CFB cutoff 2026-10-02T21:13:23.417942+00:00; NHL cutoff 2026-10-02T21:12:32.975492+00:00. All starts later than generation. Run 37065316362; execution commit 9930483918b33120524cbd0403213096f407e4c2; baseline 43ad83382af067b019a086d45d23569497ca6e08.

| League / matchup | Start PT | Named winner | Model win | Sim win | Home margin | Total point estimate | Winner ML | Market no-vig | Price break-even |
|---|---|---|---|---|---|---|---|---|---|
| CFB Pitt @ Virginia Tech | 4:00 PM | Pitt | 60.18% | 60.12% | -4.346697 | unsupported | +105 | 46.75% | 48.78% |
| CFB Liberty @ Delaware | 4:00 PM | Liberty | 56.39% | 56.66% | -2.885225 | unsupported | -270 | 70.02% | 72.97% |
| CFB Penn State @ Northwestern | 5:00 PM | Penn State | 59.16% | 58.98% | -3.727662 | unsupported | -142 | 56.35% | 58.68% |
| NHL NY Rangers @ Detroit | 3:30 PM | NY Rangers | 57.96% | 57.87% | -0.650228 | 6.448897 | +110 | 45.73% | 47.62% |
| NHL Washington @ Carolina | 4:00 PM | Carolina | 59.17% | 59.04% | 0.401243 | 6.362135 | -148 | 57.21% | 59.68% |
| NHL Boston @ Winnipeg | 5:00 PM | Boston | 57.64% | 57.37% | -0.611730 | 6.309908 | +102 | 47.39% | 49.50% |
| NHL St. Louis @ Dallas | 6:00 PM | Dallas | 51.99% | 51.77% | -0.010712 | 6.389029 | -185 | 62.25% | 64.91% |
| NHL Anaheim @ Vegas | 7:00 PM | Vegas | 66.15% | 65.98% | 0.850791 | 6.414850 | -205 | 64.47% | 67.21% |

Market snapshot: DraftKings via ESPN, NHL 2:12:07 p.m. PT and CFB 2:12:24 p.m. PT. Provider `close` field is not independently verified final closing price. Market comparison only, not model input. Price executability not verified. Spread snapshots: PITT +2.5 (-115) / VT -2.5 (-105), total54.5; LIB -7 (-108) / DEL +7 (-112), total51.5; PSU -2.5 (-118) / NU +2.5 (-102), total46.5. NHL totals: NYR-DET5.5, WSH-CAR6.5, BOS-WPG5.5, STL-DAL5.5, ANA-VGK6.5.

CFB selected model `cfb.fbs.elo_form_logit_ridge.v1_0.shadow`: 36,901 historical feature rows replayed, 17,687 training rows, 331 current finals assimilated under the week-freeze policy, 61 upcoming feature checks. Current-week Thursday results excluded by the freeze, not manually added. Formal current-season assimilation control remains unclosed. No current QB/personnel/weather fitted adjustments. Model predicts Pitt by4.3467, Liberty by2.8852, Penn State by3.7277. No CFB total head or supported cover probability.

NHL model `nhl.initial_causal_score.research.v1` is explicit initial research, not a promoted default. All five official NHL games are regular-season gameType2, team/time matched to the provider. Fresh historical collection is seasons2021–2026 through2025–26; **2026–27 outcomes, current goalies, roster changes and player availability were not incorporated**. Later-audit Brier0.248950 vs baseline0.249646; paired interval[-0.004522,+0.003113] crosses zero. Historical point-in-time availability unproven. Dallas winner51.99% conflicts with an effectively zero/slightly STL margin; separate heads were not forced coherent.

Independent NHL margin/total estimates are not joint-score distributions. Joint-score attempt failed: scripts/run_nhl_joint_score_research.py missing in merged checkout; failure retained in nhl/joint-runner.log. Original full challenger design contract not recovered; no replacement contract was invented. Model cover, sim cover and over/under probabilities unavailable for all eight events. Close model/sim winner agreement is Monte Carlo execution consistency, not independent predictive validation.

Coverage: NFL0, CFB3FBS, MLB0, NBA0, WNBA1, MLS0, NHL5 in fresh seven-league provider census. Montana State @ Idaho7:30PM PT is a separately discovered FCS game, outside selected FBS scope. WNBA Dallas @ Golden State6PM PT is playoff Game3, not run because selected FF7 path is regular-season-only. MLB official date page confirms no games. NBA preseason beginsOct3. Official NFL/MLS complete date census not independently extracted: retain provider-zero wording. Eight forecasts out of ten discovered events; not a complete all-division CFB census.

Protected state.json/default selection/official release blocker register unchanged; main untouched. Three workflow jobs and uploads succeeded, but the joint-score subprocess failed and repository health remains red:6 failures,8 warnings. Every original card retains eligible_for_prospective_grading:false with PIT_STATUS_PIT_ORDERED. This separate research publication does not update the canonical grading ledger or hash chain. ActionOFF;dose0;official_release_eligible:false. No default, coefficient, market-input or action-policy promotion.

Master index SHA-256: `86352c47c6cdd50ac3d8e790e4d4f4e1fe6ed1b289bbcfa252e18290edd24cd7`.

| Archive | ID | SHA-256 |
|---|---|---|
| census | 11252500970 | 99518ba2a556dcf5e5853fd78d671bfb9195b67908093119c95c96151b5f226a |
| cfb | 11252058159 | 575b207516da55d63bb73d1e2e662a0cccea2cd700ec5c2850139898d0ebb2d4 |
| nhl | 11251753364 | 32b069ee0cfec473030c0cf4fd6fa086c83557009f04f7735298e10a76708133 |

Archive retention expires 2026-12-31T21:11:18Z. Research omission register includes NHL joint-runner/design recovery, NHL current-season state, CFB ATS/push and formal assimilation, WNBA postseason scope, FCS scope and canonical grading/publication controls.

Official supplemental sources checked October2: https://www.wnba.com/game/1042600113 ; https://www.mlb.com/schedule/2026-10-02 ; https://www.nba.com/news/key-dates ; https://govandals.com/sports/football/schedule/2026 . Original captured APIs and hashes remain in the three named workflow artifacts. This publication record was generated at 2026-10-02T21:20:07.794138+00:00 and is not backdated to a forecast cutoff.
