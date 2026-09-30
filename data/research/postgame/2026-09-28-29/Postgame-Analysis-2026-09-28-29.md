# Postgame model analysis — September 28–29, 2026

Written 2026-09-30T09:54:01.858888+00:00. Dates use America/Los_Angeles. Frozen forecasts only; current finals are outcomes, never retroactive model inputs.

## September 28 — NFL

**Final: Chicago 27, Philadelphia 7.** The primary is the last eligible frozen Keenum-condition version (September 28, 4:56 p.m. Pacific), with end-of-Week-2 state. Earlier Monday versions and Williams/Bagent counterfactuals are not substituted or pooled. The already-recorded Monday research grade is referenced; no duplicate was appended.

| Product | Frozen model | Frozen simulation | Market no-vig | Actual / interpretation |
|---|---:|---:|---:|---|
| PHI outright | 59.18% | 59.33% | 63.69% | Lost; winner direction wrong |
| PHI −3.5 | 46.24% | 46.21% | 50.43% | Did not cover; model favored CHI +3.5 |
| Expected PHI margin | +2.37 | +2.36 | Market spread PHI −3.5 | Actual −20; absolute error 22.37 points |

The separate calibrated integer-margin arm is `nfl.qb_margin.integer_blend.v1.research`; the winner arm is `nfl.integrated_context.qb.v1.research`. Its margin distribution is not a joint-score model. No supported total/score forecast was graded.

Winner Brier: **0.3503 model vs 0.4056 market**, delta -0.0554. Spread Brier: **0.2138 vs 0.2543**, delta -0.0405. Lower is better; a losing favorite forecast can score better than a more confident losing market forecast. One event establishes no calibration advantage.

The actual margin was outside the central 80% interval (PHI −15 to +19). The frozen law assigned **5.85%** to Chicago winning by at least 20. This was a tail outcome, not a zero-probability event.

The official Bears recap reports Keenum 24/34 for 247 yards, two passing touchdowns and no interceptions, plus a rushing touchdown. Chicago forced three turnovers; Philadelphia was 2/9 on third down and gained 62 second-half yards. The model used the correct starting-QB condition. The miss concerns the resulting team performance and game distribution, not an accidental Williams assumption. These observations support the existing turnover and QB-uncertainty research queue; they do not identify a causal coefficient adjustment from one game.

Official recap: https://www.chicagobears.com/news/game-recap-case-keenum-defense-lead-bears-to-dominant-victory-over-eagles

Market benchmark was captured at 23:58:31Z, after the model freeze and before kickoff: PHI −198 / CHI +164, PHI −3.5 at −112 / CHI +3.5 at −108. The later total was 42.5; the earlier screenshot’s 41.5 is a different version. Market settlement terms remain unverified, so comparisons are diagnostic, with no ROI or payout grade. Official-gamebook clearance is still false. Weather was imputed and non-QB availability was not numerically consumed.

## September 29 — NHL

Winner probabilities below name the model’s favored team. Model / simulation percentages are from retained 100,000-draw runs, not postgame reruns. All five official NHL finals reconcile to ESPN.

| Game | Final | Original winner-only model / sim | Joint-score model / sim | Joint timing cohort |
|---|---|---|---|---|
| FLA @ CAR | FLA 1–CAR 0 OT | CAR 63.04% / 62.67% miss | Not issued: already started | Excluded |
| MTL @ TOR | MTL 3–TOR 2 | MTL 60.53% / 60.76% correct | TOR 53.67% / 53.51% miss | ARCHIVAL_LATE |
| NYR @ BOS | NYR 0–BOS 3 | BOS 55.91% / 55.77% correct | BOS 54.83% / 54.72% correct | Timing eligible |
| VAN @ EDM | VAN 6–EDM 5 OT | EDM 71.50% / 71.51% miss | EDM 61.46% / 61.27% miss | Timing eligible |
| CHI @ VGK | CHI 2–VGK 5 | VGK 72.85% / 72.68% correct | VGK 61.22% / 61.36% correct | Timing eligible |

| Game | Joint puck-line direction | Outcome | Joint total direction | Outcome |
|---|---:|---|---:|---|
| MTL @ TOR | TOR +1.5: 71.85% | Covered | under 6.5: 54.78% | Correct |
| NYR @ BOS | BOS +1.5: 75.74% | Covered | over 5.5: 61.29% | Miss |
| VAN @ EDM | VAN +1.5: 62.80% | Covered | under 6.5: 54.53% | Miss |
| CHI @ VGK | CHI +1.5: 61.62% | Failed | over 5.5: 58.89% | Correct |

These are probability directions above 50%, not authorized wagers or price-aware profit counts. Complementary sides are counted once per game. Original winner-only output has no puck-line probability.

### Paired scoring: same four games

Brier is binary squared probability error; log loss uses natural logarithms. All four include the Montreal archival diagnostic; they are not a strict prospective performance claim.

| Product / model | N | Direction correct | Brier | Log loss |
|---|---:|---:|---:|---:|
| Original winner-only | 4 | 3/4 | 0.2338 | 0.6639 |
| Joint winner | 4 | 2/4 | 0.2551 | 0.7036 |
| Market winner* | 4 | 3/4 | 0.2753 | 0.7500 |
| Joint quoted puck line | 4 | 3/4 | 0.1640 | 0.5078 |
| Market quoted puck line* | 4 | 2/4 | 0.1849 | 0.5548 |
| Joint quoted total | 4 | 2/4 | 0.2616 | 0.7171 |
| Market quoted total* | 4 | 3/4 | 0.2447 | 0.6824 |

On identical games the joint winner arm was **+0.0213 worse in Brier** than the original. The original’s full five-game diagnostic record was 3/5, Brier 0.2665; comparing that five-game score directly with the joint four-game score would confound coverage.

*Market grades are conditional references from the retained user screenshots. Exact book, jurisdiction, full capture timestamp and rule binding remain unresolved. They cannot enter the registered market-comparison cohort yet. Florida–Carolina’s live market is excluded. No odds were reconstructed from results or substituted with closing prices.

### Strict timing cohort and registered primary

Only NYR–BOS, VAN–EDM and CHI–VGK have both pre-start durable joint registration and reconciled finals. Montreal’s archive was published at 23:05:22Z, after its 23:00Z scheduled start; its numerical result is retained only as an archival diagnostic. The original winner-only card also explicitly lacks strict prospective grading eligibility. Paired comparisons to it remain diagnostic even on those three events.

For the three timing-eligible joint forecasts: winner **2/3, Brier 0.2440**; quoted puck-line direction **2/3, Brier 0.1923**; quoted totals **1/3, Brier 0.2807**.

The predeclared primary is **home −1.5**, not whichever quoted side happens to look best. Its Brier is **0.3020** versus **0.3374** for the frozen 7,428-game unconditional settled-margin pool; delta **-0.0354**. Baseline P(home wins by 2+)=32.73%. Log loss is 0.7993 versus 0.8768. This is three observations in one ISO week, far short of the registered 500-game / eight-week minimum. Week-bootstrap inference would be degenerate; no confidence or promotion conclusion is warranted.

### Error breakdown

- **Montreal–Toronto:** original MTL direction was correct; joint TOR direction was wrong. Toronto +1.5 nevertheless covered. Winner and cover are different events. The late-registered row is not allowed to improve or worsen the strict prospective record.
- **Vancouver–Edmonton:** both arms favored Edmonton; the joint arm reduced Edmonton from 71.50% to 61.46% but still missed the winner. Vancouver +1.5 covered. The 11-goal final exceeded the frozen central-80% total interval; only 6.963% of retained draws had at least 11 goals. This is a total-tail miss, not proof that the model forecast a Vancouver upset.
- **New York–Boston:** both winner directions and BOS +1.5 were correct; over 5.5 missed with only three goals. Official PBP records one Boston empty-net goal. Boston already led by two before it, so that goal did not flip ±1.5 settlement.
- **Chicago–Vegas:** both winner directions were correct, but CHI +1.5 failed. Vegas already led 4–2 before its empty-net goal made it 5–2; the empty-net goal did not cause the puck-line miss. Over 5.5 was correct.
- **Florida–Carolina:** the original CAR direction missed in a 1–0 overtime game. No joint forecast was issued after the event had started.

Descriptive slices are retained in analysis.json: one-goal versus multi-goal games, OT versus regulation, empty-net presence, market-favorite strength, and 5.5 versus 6.5 total environments. Every subgroup has only one to three joint observations. Observed goalie and player performance is postgame evidence; neither model consumed a registered player-availability/goalie-effect increment for these forecasts. Do not backfill those inputs into the frozen versions.

Official result sources: https://api-web.nhle.com/v1/schedule/2026-09-29 and the five linked gamecenter PBP/boxscore captures in source-receipts.json / detail-receipts.json. Empty-net flags require the opposing goalie-absence position of situationCode; a team scoring with its own goalie pulled is not an empty-net goal.

## Coverage and operational limits

- September 28: NFL PHI–CHI was the only event in the seven-league captured census.
- September 29: MLB playoff finals ATL 5–3 PHI, CWS 6–3 HOU, NYY 9–0 BOS, SD 8–0 CHC; WNBA playoff finals IND 99–89 LVA and NYL 87–71 MIN. No supported frozen forecasts were located for those postseason products, so model grades are N/A. Results are not predictions.
- CFB/NBA/MLS had no events in either date’s captured provider census; NFL had no September 29 event. September 30/October 1 NHL forecasts are outside this report and remain ungraded.
- This is an additive postgame audit, not a canonical universal grader or a weekly-state transition. NFL’s prior research grade remains single-counted. NHL research rows are durable audit evidence; the canonical grading ledger and old prospective-ledger bytes are untouched.
- 27 source captures succeeded. All 75 original NHL registry file hashes matched. Four retained joint draw arrays and the Monday margin draw hash were verified; no forecast rerun or coefficient update was performed.
- Local healthcheck exited 1 with 11 failures and six warnings, including snapshot/environment limitations and unresolved historical/recovery gates. This does not grant official release or gamebook clearance. See the retained health log; tests are not predictive validation.

## Findings and next evidence

| Issue | Fixed / established | Not established / remaining | Next evidence |
|---|---|---|---|
| POST-0928-QB-TAIL | Correct Keenum-conditioned primary and actual result bound | Why QB/team forecast underestimated Chicago; one result cannot identify coefficients | Official gamebook reconciliation; frozen contribution decomposition; turnover study on dev/held-out cohorts |
| POST-0929-ARM-DIVERGENCE | Paired original/joint scores calculated on identical IDs | Joint winner improvement is not established; four-game score is worse | Continue registered prospective cohort; keep arms separate |
| POST-0929-SETTLEMENT | Official full-game finals and OT/EN labels captured | Exact screenshot sportsbook/jurisdiction/time binding | Authenticated original market record and applicable rules before market eligibility |
| POST-0929-TOTAL-TAIL | VAN–EDM total-tail miss quantified from frozen draws | Calibration or personnel improvement | Accumulate prospective reliability/tail slices; separate goalie/availability challenger increment |
| POST-0929-LATE-ARCHIVE | Montreal excluded from strict timing cohort | No retroactive repair can make it timely | Complete future immutable publication before the declared cutoff |

These are linked audit findings, not claims that canonical standing-health cards were changed or their aging reset. Reproducibility: source-byte reconciliation plus frozen-artifact scoring; official-release eligibility remains false.

Keep the original winner-only arm and joint-score challenger separate. Continue prospective scoring under the existing protocol; no retraining, blending, state transition or wagering change follows from this small batch. **Action OFF; dose 0.0.**
