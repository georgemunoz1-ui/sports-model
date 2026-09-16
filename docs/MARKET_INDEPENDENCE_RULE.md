# Market-Independent Prediction Rule

**Standing governance rule. Same force as R1 (never invent numbers), R3 (frozen stays frozen)
and R6 (append-only).** Adopted as a written artifact 2026-08-29. Enforced by
`harness/market_independence.py`, which is wired into `harness/healthcheck.py`.

## THIS RULE IS NOT NEW, AND THE RECORD SHOULD SAY SO

The constraint predates this file. "Prices are never predictive features and enter only the
action/EV overlay" was already asserted in five places in the board builders before this document
existed (`build_board_0828.py`, `build_card_0828.py`, `build_full_card_0828.py` ×2,
`build_board_nfl_0828.py`), and the 2026-08-28 MLB board carries **zero** market-derived fields in
its rows — verified by schema scan, not by assertion.

That matters for how the 2026-08-28 non-compliance is recorded. A market-weighted predictive
ensemble (CFB w=0.3 market, MLB/WNBA w=0.6 market) did not violate a rule adopted afterwards. It
violated a constraint that was already in force. Writing it down changes the enforceability, not
the obligation. See `data/audit/2026-08-29_market_independence_disclosure.json`.

## THE RULE

Build all game, team, and player projections from **independent statistical and data-driven
analysis**. Do **not** use sportsbook odds, implied probabilities, betting percentages,
public-money splits, line movement, consensus picks, or bookmaker pricing as predictive features
for determining which team/player is more likely to win or outperform.

The objective is to identify the underlying competitive advantage directly from the data rather
than allowing the betting market to anchor the model's conclusion.

Predictions should instead be driven by measurable factors such as: team and player efficiency
metrics; opponent-adjusted performance; offensive and defensive matchup advantages; expected
lineups, starters, rotations, and availability; injuries, suspensions, and role changes; recent
performance with appropriate regression toward larger-sample baselines; strength of schedule;
pace, possession, opportunity, and usage; home/away and travel effects; rest and scheduling
effects; coaching/scheme tendencies; offensive/defensive line advantages where applicable;
advanced metrics such as EPA, success rate, explosive-play rate, pressure rate, xERA/xwOBA,
Statcast data, depending on sport; historical matchup characteristics when statistically
meaningful; weather and environmental effects when relevant; and uncertainty, variance, and
distributional outcomes.

**Sportsbook information must remain firewalled from the predictive model.**

The model must first independently generate:

1. projected winner
2. win probability
3. projected score/margin
4. projected total
5. player/statistical projections where applicable
6. uncertainty/confidence intervals

Only **after those projections are frozen** may sportsbook prices be introduced as an
**action/valuation layer** to determine whether the independently generated projection provides
sufficient value relative to the available price.

> **Data determines who should win.
> The market only determines whether the resulting wager is worth making.**

Do not reverse-engineer a projection to agree with a betting line. Do not move a projected
probability simply because the market disagrees. A major disagreement with the market should
trigger an **audit of the underlying data, inputs, injuries, lineups, and model assumptions**, not
an automatic correction toward the sportsbook number.

If the independent model produces an apparent large edge, verify: data freshness; roster/lineup
accuracy; starter status; injuries/suspensions; schedule and venue; model-input integrity;
sample-size reliability; and whether an important matchup variable is missing.

If those checks pass, **preserve the independent projection even when it materially disagrees with
the market.**

**No implied probability, vig, line movement, reverse-line movement, public betting percentage,
sharp-money narrative, or "book trap" theory may determine the predicted winner.** These may
optionally be recorded as **post-model contextual information**, but they must never contaminate
or influence the underlying forecast.

## THE ANTI-CONTRARIAN CLAUSE

**Market independence does not mean automatically fading favorites or siding against sportsbook
consensus. If the independent data supports the favorite, select the favorite; if it supports the
underdog, select the underdog. Direction must come exclusively from the model evidence.**

Otherwise "ignore the books" mutates into "always distrust the favorite," which is just market
anchoring with the sign flipped. The goal is price-blind forecasting first, price-aware wagering
second.

## REQUIRED OUTPUT SEPARATION

    MODEL FORECAST   — purely statistical/data driven
    UNCERTAINTY/RISK — variance, missing information, injury uncertainty
    MARKET COMPARISON— model projection versus available line/price
    BET DECISION     — whether the edge is large and reliable enough to act on

## WHAT IS MACHINE-CHECKED

`harness/market_independence.py` enforces four things and refuses rather than warns:

1. **FEATURE FIREWALL** — no market-derived key may appear in a forecast row's feature position.
   The token list is precise on purpose. A previous crude firewall in this repo matched the
   substring `"point"` and rejected `home_ewma_points_for`, a *preregistered* feature; that is a
   false positive breaking a legitimate model, and this checker carries an allow-list and a
   regression test pinning that exact case so it cannot recur.
2. **ORDERING** — any market artifact attached to a board must be captured at or after the
   board's `forecast_anchor_utc`. A price observed before the freeze cannot have failed to
   influence it; the ordering is the only evidence of the firewall holding in time.
3. **LAYER SEPARATION** — a published decision artifact must carry the four layers above as
   distinct fields, so a reader can see which claims are price-blind.
4. **CONTRARIAN DRIFT** — a slate on which the model takes the non-favorite in *every* game is
   flagged. This is a DIAGNOSTIC, not a refusal: an all-fade slate can happen honestly, and
   treating it as proof of anchoring would itself be a form of anchoring. It is surfaced so a
   human can look.
