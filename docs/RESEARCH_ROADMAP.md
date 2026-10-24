# Cross-sport core-market research roadmap

Updated October 23, 2026 Pacific / October 24 UTC. **This is an experiment agenda, not a claim that the formulas below are newly fitted, backtested or promoted.** Current executed evidence is in [status](CURRENT_STATUS.md). Moneyline, spread/run line/puck line and totals are the core products; props, periods, alternate lines and parlays require additional qualified inputs/contracts.

## Common settlement layer, sport-specific probability models

A margin distribution alone cannot identify totals. Use a compatible joint score law `q(h,a)` or aligned score scenarios when all core markets are needed. With `M=H-A`, `T=H+A` and home handicap `s`:

```text
home win:       P(M > 0), with separate tie/draw/OT treatment
home cover:     P(M + s > 0)
push:           P(M + s = 0)
over total L:   P(T > L)
under total L:  P(T < L)
```

For decimal odds `d`, full-win/full-loss/push expected net return per unit is `p_win*(d-1)-p_loss`. Compare unconditional outcome masses to the actual payout; do not count half a push as a win. Quarter handicaps, voids, fees and partial payouts require explicit settlement. One joint scenario must settle every related same-game leg consistently.

A discretized Gaussian score grid can provide internally consistent arithmetic without establishing sport-specific support, key-number frequencies, tail accuracy or overtime realism. The separately described external `joint.py` is not certified integrated by the saved card refresh.

## Proposed increments by sport

| Sport | Opportunity / efficiency construction to investigate | Critical evaluation and settlement checks |
|---|---|---|
| NBA / WNBA | Estimate possessions separately from opponent-adjusted scoring efficiency. Box-score possession estimator: average both teams' `FGA-ORB+TOV+0.44*FTA`. Offensive rating: `100*points/possessions`; defensive rating: `100*points_allowed/possessions`. Project score from possessions × matchup points per possession. | Correct defensive direction; regulation-duration/OT normalization; shooting/turnover/rebound/free-throw components; shared pace uncertainty, endgame fouls, rotations and availability; winner/margin/total assessed separately |
| NFL / CFB | Model drives/plays and outcome rates using opponent-adjusted EPA/success, pass/rush mix, explosive plays, finishing drives, QB state and weather where authenticated. | EPA is not directly points per game; fit the mapping. Validate discrete scoring/key numbers and league-specific OT, not generic Gaussian boosts |
| MLB | Project run opportunities and plate-appearance outcomes from confirmed starter quality/workload, offense, bullpen, lineup and park/weather inputs; compare with existing frozen controls. | Base/out transitions, skipped home ninth, walkoffs and extra innings; both starter identities and contract-specific pitcher rules |
| NHL | Project shot/chance volume and scoring efficiency by strength state; goalie availability/quality and special teams as separate increments. | Rest feature semantics/refit, empty-net state, regulation versus OT/SO and shootout accounting; no silent no-tie conditioning |
| MLS | Dynamic attack/defense scoring rates with justified low-score dependence and source-bound personnel increments. | Regulation 1X2 draw mass, handicap half outcomes and totals; no automatic extra-time/penalty inclusion |

The basketball arithmetic is a feature/expectation template. The `0.44` coefficient is an estimator assumption, not a universal fitted truth. Joint uncertainty and opponent/pace effects must be estimated using permitted earlier data; no fixed league sigma or correlation is qualified by copying an illustrative value.

## Address the NBA regression without outcome tuning

Keep the original control and v2 candidates frozen. Separate tests for pace, opponent-adjusted efficiency, shot profile, personnel/minutes, score residuals and joint dependence so attribution is possible. Use matched training and evaluation populations, cutoff-consistent source eligibility and a fixed earlier residual/calibration window. Compare a distinct coherent joint candidate with the existing separate-head control rather than quietly replacing its winner probability.

Freeze each protocol before new confirmation results; report Brier/log loss, calibration diagnostics, margin/total errors, CRPS, interval coverage and exact offered-line settlement quality. Preserve negative results and inspected trials. Reusing the repaired October cohort is further diagnostic research, not prospective proof that the three discovery losses were preventable.

## Market and portfolio research are separate

Preserve market-independent baselines. Any candidate residual model such as `sigmoid(logit(p_market_at_decision)+f(x))`, fitted blending, uncertainty-based selection or portfolio allocation needs a distinct identity, earlier-only fitting and prospective qualification. Decision quotes and closing quotes must be stored separately; no closing-line leakage.

Do not pre-rank totals, underdogs, spreads or props by assumed profitability. Rank only comparable executed-price evidence by sport, market and horizon, including costs, limits, exclusions, dependence and uncertainty. Synthetic profit, a favorable CLV number, model agreement or 500 bets alone cannot establish an advantage. Same-game parlay pricing cannot be assumed independent.

A constrained joint-scenario portfolio and versioned pause/reactivation policy are candidate engineering work unless actual repository execution evidence establishes otherwise. This roadmap does not adopt external `/mnt/agents/output/` package claims, hard-coded blend weights, CLV kill switches or automatic staking. Unqualified output remains research-only with zero live allocation.
