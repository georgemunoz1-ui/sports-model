# All-sports margin system: independent design review

Review date: 2026-10-19. Scope: recovered local repository, existing discrete research layer, and retained October 19 outputs. This is a design/source audit, not model promotion, prospective validation, or a sportsbook contract certification.

## Findings that should determine the implementation

1. **Standardize orientation explicitly.** The shared `discrete_research.outcome` interprets its `line` as the home handicap even for an AWAY selection: home wins when `M + h > 0`, where `M = home - away`. The NFL contextual `settlement_values` instead takes the selected team's handicap: away wins when `-M + away_handicap > 0`. Both work in isolation; passing an unnamed line between them can reverse a contract. A new interface should require `home_handicap` or an explicit orientation enum and translate once. Home -3 and away +3 must be complements with identical push mass.
2. **A point forecast or Bernoulli simulation does not identify a margin distribution.** `models/current/common.emit` has independent winner, margin, and total heads; it only simulates the winner. The selected NFL QB artifact also has a mean margin but no eligible score residual pool. Do not infer scale from its win probability, borrow another arm's residual pool, or describe independent margin/total distributions as a joint score simulator.
3. **Finite empirical support is the main existing statistical defect.** `discrete_research.predict` splits shifted residual centers across adjacent integers, then conditions on legal support. Legal but unobserved integer outcomes can receive zero mass. `discrete_calibration.fit` correctly refuses calibration outcomes with zero support; CDF recalibration cannot create missing support. The October 7 study reports six refused fits and zero-supported evaluated scores. A separately identified, preregistered support/tail model is necessary; never clip evaluation losses or add a floor after seeing the test outcome.
4. **Conditioning is not overtime modeling.** The retained October 19 NHL marginal distributions remove 10.27–13.42% zero-margin mass and renormalize. That changes the mean and cover curve. Keep `removed_illegal_support_mass` visible. A future regulation-plus-OT/SO model must allocate tied regulation states to final outcomes under a fitted mechanism, not silently discard them.
5. **Keep fitting, calibration, and later evaluation separate.** Use event-identified parent out-of-time predictions and source-bound final scores; preserve parent/model/product/settlement/season identities. Freeze support policy, hyperparameters, feature set and splits before the later evaluation. Source-observed, retrieval, cutoff, creation, registration and event-start timestamps are distinct. A hash or caller timestamp alone does not prove a historical pregame forecast existed.
6. **Current line/quote validation is not full authentication.** Existing quote checks match event, side, numeric line and settlement and reject post-cutoff times. They do not independently authenticate a book or prove that the two odds are contemporaneous opposing contracts. Require observed <= retrieved <= cutoff for live capture, exact opposing-line identity, period, house-rules receipt and void policy before market scoring. Until then, show hypothetical ladders and no market edge claim.

## Reusable October 19 evidence

| Product | Genuine retained capability | Limit |
|---|---|---|
| NFL WAS at SF, selected QB | Mean home margin **+11.01444**, point total **48.11641**, winner probability **81.64101%** in `afternoon-refresh/nfl/2026_06_WAS_SF/forecast.json` | `joint_distribution=null`; score simulation refuses the combined-specific residual pool. Cover probabilities need the selected-parent historical cohort and a fitted distribution. |
| NHL four events | Four fitted empirical margin distributions, retained 100,000 draws each, in `recovered/evidence/run-2026-10-19/nhl/margin/distribution_report.json` | Parent is `nhl.fixed_parent.03ce6285cdbfaa24.research`, distinct from the initial winner model. Contracts are empty; line ladders are hypothetical. Mean margins: **+0.76273, -0.70111, -0.07875, +0.83012** in report event order. |
| CFB/NBA/NHL/MLS historical | October 7 normalized cohorts and frozen residual/calibration/evaluation artifacts | Existing diagnostic history; not new prospective evidence. Replay recreates calculations, not original source availability. |
| WNBA/MLB | Shared software interface and settlement labels | Existing design report identifies missing source-bound historical forecasts. MLB tie-proxy output is not a completed-game runline simulator. WNBA regular-season eligibility does not cover Finals automatically. |

Historical report: `docs/DISTRIBUTION_REPLAY_20261007.md`. It reports 3,661 distinct later-period games, seven margin/total products, and 6,608 game-product evaluations. Every conditional-scale CRPS interval includes zero. Those results do not establish ATS improvement. Current local `python3 harness/healthcheck.py` exits 1 with many missing-file/module failures in this partial checkout; do not label repository health green from focused tests.

## Required league contracts

| League | Margin target and rule distinction | Model requirements |
|---|---|---|
| NFL | Regular-season final margin can be zero; postseason final margin cannot. Regulation/first half are separate products. | Preserve point masses at key margins, use same-parent OOF residuals, report tie separately. 2026 Rule 16 distinguishes regular-season 10-minute OT and postseason continuation [1]. |
| CFB | Completed full-game OT margin is nonzero; overtime differs from NFL. | Preserve integer tails and small-margin structure, eligibility by competition, and season-specific overtime rules. NCAA documents alternating two-point attempts beginning in third OT [2]. |
| NBA | Completed final score includes all required OT; regulation is separate. | Integer support, pace/dispersion effects fitted only when inputs exist; test late fouling and OT slices. NBA Rule 5 provides repeated five-minute OT [3]. |
| WNBA | Same full-game/regulation distinction; separately fitted league and competition scope. | Do not transplant NBA variance or assume regular-season validation covers playoffs. The 2026 rulebook has five-minute OT and continuation of tied games [4]. |
| MLB | Completed-game margin excludes ties; regulation-inning and completed-game products differ. | Separate regular/postseason extra-inning process; score dependence, walk-off censoring, starters and bullpen state require fitted evidence. Automatic runner applies only to regular season [5]. |
| NHL | Regulation permits ties; final official-score product includes OT/SO; postseason mechanism differs. | Exact rule version and book scoring convention, goalie/player state, one-goal/empty-net slices. Official shootout score adds one goal to the winner [6]; current 2026–27 rulebook page exists, but its linked PDF retrieval failed in this audit [7]. |
| MLS | Regulation 90 minutes plus stoppage permits a draw. Advancement markets are different products. | Preserve draw mass; support whole, half, and quarter Asian handicaps with half-win/half-loss states. The 2026 playoff procedures differ by round, so qualification and regulation cannot share one unqualified outcome [8]. |

League rules describe the game. They do not establish a particular sportsbook's period, push, listed-player, abandonment, postponement, or void terms.

## Acceptance requirements for the new layer

- Return mean, median, modes, standard deviation, central predictive intervals, full integer PMF/CDF, same-distribution home/tie/away probabilities, and a hypothetical handicap ladder. Label model spread as a selected summary convention; a mean is not automatically the even-price line of a skewed discrete distribution.
- Preserve full win/half-win/push/half-loss/loss mass. Report unconditional cover and conditional-on-nonpush probability separately. For a chosen decimal price `d`, diagnostic net payoff is `p_win*(d-1) + p_half_win*(d-1)/2 - p_loss - p_half_loss/2`; price arithmetic grants no authority.
- Use exact PMF settlement as the analytic reference; actual retained 100,000 draws supply Monte Carlo estimates and replay receipts. At 100,000 draws the worst-case Monte Carlo standard error is about **0.158 percentage points**, not predictive uncertainty.
- Test probability sums, monotonic cover curves, home/away symmetry, whole-number pushes, MLS quarter-line payoffs, invalid/future/tampered inputs, model and event mismatch, support extremes and deterministic replay. No automatic calibration/promotion from passing software tests.
- Evaluate chronological same-event comparisons using CRPS/RPS, exact-outcome log loss with zero support explicitly counted, category Brier/log loss, interval coverage/sharpness, discrete PIT and calibration by margin/tie/OT/availability slices. Cluster alternate lines within games and bootstrap appropriate time blocks; report sample sizes and unmatched coverage.
- Keep direct-score, residual-distribution, availability-mixture and market-informed arms separate. A joint score product must satisfy `M=H-A`, `T=H+A`, `T>=abs(M)` and parity constraints; two independent marginals do not provide that coherence.

These recommendations follow the proper-scoring and calibration frameworks in [9–10]. Dixon–Coles motivates a separately tested score-model family for soccer [11]; its older empirical result does not prove current MLS betting profitability. No method is an all-sports accuracy guarantee.

## Independent implementation review checkpoint

Reviewed the new `models/common/margin_system.py`, `margin_challenger.py`, `research/evaluate_margin_system.py`, `pipelines/cards/margin_system.py`, and `scripts/run_margin_system_study.py` during this implementation. This checkpoint is source/numerical review, not the final frozen-code acceptance receipt.

- Independently checked home/away complement identities, full/half/push mass for NFL integer and MLS quarter handicaps, and refusal of contradictory contract metadata.
- Independently fitted the synthetic test cohort and checked challenger predictions at mean margins -100, -7, 0, 7 and 100: legal masses were positive and normalized; excluded zero-margin states and finite-tail limits were explicit. A separate wide-grid summation agreed with the analytic lattice/legal-support normalizer within 1e-7 (observed difference zero).
- Review found a contract-summary output-key mismatch, accepted contradictory diagnostic contract fields, missing challenger conditioning warnings in the summary, and card start-time/completion-clock binding gaps. Owning agents repaired these; the metadata refusal was independently rerun successfully. Their broader unit-test results are separately reported by those agents.
- The study runner fits on the retained residual split, leaves calibration unused, evaluates later rows, saves its design before fitting/evaluation, and labels the historical cohort reused. No untouched-holdout or prospective claim is justified. Its diagnostic line-zero contract is a threshold comparison, not a market spread benchmark.
- The challenger remains a fitted residual/Student-t mixture with explicit no-tie conditioning and a finite represented range. It is neither a possession-level score simulator nor a mechanistic overtime model. Final acceptance must bind the final code hashes, fitted artifacts, evaluation outputs and actual draw bytes.

## Primary sources

1. NFL 2026 rules, Rule 16: https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf
2. NCAA approved overtime change: https://www.ncaa.org/news/media-center-changes-to-injury-timeouts-approved-in-football/ ; current rules hub: https://www.ncaa.org/championships/playing-rules/football-playing-rules/
3. NBA Rule 5: https://official.nba.com/rule-no-5-scoring-and-timing/
4. WNBA 2026 rules, Rule 5: https://cdn.wnba.com/sites/4/2026/05/2026-WNBA-Official-Rule-Book.pdf
5. MLB automatic runner: https://www.mlb.com/glossary/rules/designated-runner
6. NHL official rules, Rule 84 (2022–23 retained source): https://media.nhl.com/site/asset/public/ext/2022-23/2022-23Rulebook.pdf
7. NHL current rulebook gateway: https://www.nhl.com/info/video-rulebook
8. MLS 2026 competition guidelines: https://www.mlssoccer.com/news/2026-mls-competition-guidelines
9. Gneiting and Raftery (2007), proper scoring rules: https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf
10. Czado, Gneiting and Held (2009), ordered discrete predictive assessment: https://doi.org/10.1111/j.1541-0420.2009.01191.x
11. Dixon and Coles (1997), score model: https://doi.org/10.1111/1467-9876.00065
