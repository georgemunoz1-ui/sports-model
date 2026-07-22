# AUTHORIZATIONS LOG — standing decisions by Taco

## 2026-07-18T04:14Z (2026-07-17 ~21:14 PT) — four decisions via structured question, this session

**AUTH-1 (Priorities).** All three tracks authorized for this session: (a) MLB pipeline + 7/18 card,
(b) multi-sport foundation (WNBA/NFL/CFB/NBA), (c) 2026 backfill & calibration.

**AUTH-2 (Governance — engine tracks).** DUAL TRACK:
- V11 remains FROZEN, runs proxy-class on newly available inputs that match its locked signal
  definitions. Paper only. No weight/cutoff/formula changes. The 0/100 Pinnacle gate remains
  attached to V11. D1/D2 (V11.1 fork) NOT authorized tonight — V11.1 does not exist yet.
- V13 CLOUD-NATIVE track authorized: new engine built on newly unblocked data (per-start logs,
  statcast gamefeed, auto-captured DK closes). Own spec, own hash, own independent forward paper
  ledger. Never feeds V11 tiers. Park adjustment and fitted HFA are allowed AT BIRTH in V13 (new
  track ≠ mid-protocol patch of V11/V12). No pooling of records across tracks, per council rule.

**AUTH-3 (CLV close-capture).** Auto-capture in-session: DK-close-equivalent snapshots taken
pre-first-pitch via scheduled in-session reminders (~11:00 PT and ~15:45 PT waves on game days,
per-day adjustment allowed). Entries keyed (date, gamePk, side), idempotent. DIAGNOSTIC track
only. Pinnacle n=100 gate untouched at 0/100. This formalizes the dual-track initiated 2026-07-12.

**AUTH-4 (D5 falsification decision rules).** OPERATIVE DEFAULT ADOPTED FORMALLY, pre-registered
with this timestamp, before any 7/18 prediction:
- DK-close diagnostic logging only; idempotent keyed entries.
- NO weight/cutoff/formula change to V11 until the n=100 gate (Pinnacle, or explicit dated
  re-anchor amendment by Taco — none made).
- Canary system continues (pre-registered before first pitch, graded post-game).
- No falsification decision thresholds (CLV mean/median, calibration slope, ROI, subgroup) are in
  force yet; a full D5 draft may be produced for review but binds nothing until Taco approves.

## 2026-07-18T20:1x Z (13:1x PT) — TIMING CORRECTION
The `<env>` "today = July 18" stamp was static; real wall-clock advanced during the session. At
card-build time it is ~1:10 PM PT on GAME DAY 7/18, slate LIVE. Consequences: (a) 7/17 fully graded
below; (b) 7/18 early games (1:10–3:10 ET) were already live/final at compute → V11/V13 outputs on
them are GRADE-ONLY, not actionable; (c) pregame-actionable set = 4:10 ET wave and later; (d) DK
closing board re-captured 20:09Z (data/mlb/odds/2026-07-18_close.json). The user's uploaded 7/18
matchups feed supplied all SP proxy inputs (ERA/K%/BB%/GS), current team RF/RA, market lines, and
the EST competing-model line — dissolving the FanGraphs rate-limit block.

## 2026-07-18 (later) — DOCTRINE LOCKED by Taco (supersedes CLV-primary framing)
**AUTH-5 (Evaluation doctrine).** PRIMARY scoreboard for all engines = **win% + Brier vs
coin AND vs a data baseline** (pure DATA > Implied). NOT CLV/beating-the-close. Goal: winning
picks on ML, Run Line, Totals, and sport-specific markets — "beat the house at a high clip."
CLV/Pinnacle-close is DEMOTED to a secondary diagnostic; the n=100 gate is retained only as a
sample-size discipline, not as the definition of success. Implied odds are used ONLY as the price
paid at bet time, never as the prediction target.

**AUTH-6 (Loss-quality — not all losses are equal).** Taco: "I can live with losses like SF-SEA
[led into the 7th, lost late — variance]; blowouts which data would've avoided I cannot."
Formalized into a tracked metric:
  - LIVE loss (acceptable): final margin <=2, or our side led/was tied into the 7th+. Variance.
  - BLOWOUT loss (indictable): margin >=5 and never competitive. Data should have smelled it.
  - **BLOWOUT-LOSS RATE = (blowouts)/(total bets)** — a primary KPI to MINIMIZE, alongside win%/Brier.
  7/18 baseline: 6-7, blowout-loss rate 2/13 = 15% (WSH/Littell, NYM/Manaea). 4 of 7 losses were
  1-2 run games. Worked example of an indictable loss: Littell (14.8% K, contact profile) 8ER/9 hard-
  hit in a hitter park, model still had WSH 54% — it ignored the starter's left tail.

**V13.1 build targets (structural, principled — NOT slate-overfit):**
  1. Extract P(lose by >=5) per pick from the MC run-margin distribution = explicit BLOWOUT RISK;
     add downside-aware selection (suppress a side with high blowout risk even if mean win%>50%).
  2. Park x contact-profile interaction on run-suppression: low-K/high-contact starters get a LARGER
     park penalty in hitter parks (more balls in play exposed to the park). Directly addresses the
     Littell/Sutter-Health failure. Mechanism-based, not curve-fit.
  3. DEFER temperature-scaling (V13-CAL-1 under-dispersion fix) until >=1 more graded slate — fitting
     a calibration temperature on n=1 is the one-slate-overfit the council warned against.

## 2026-07-18 — V13.1 POOLED VALIDATION (7/17+7/18, n=28, two opposite slate types)
Directional ML: 18-10 (64.3%). Brier: V13.1 0.2403 vs Market 0.2377 vs coin 0.25 → V13.1 now
~LEVEL with market on calibration (was 0.02 behind on 7/18 alone; the gap washed out pooled).
READ: V13.1 is market-COMPETITIVE (price of entry), NOT yet market-BEATING (would need Brier
below market / profitable results). 18-10 SU is partly trivial favorites — not proof of edge.

**BLOWOUT-RISK GUARDRAIL — VALIDATED, operating point ADOPTED at 18%:**
  High-risk picks (modeled P(pick blown out by >=5) >= 18%): 6 picks, 33% got blown out.
  Low-risk (<18%): 22 picks, 5% got blown out. 6.6x separation across BOTH slate types.
  The 18% cutoff is supported by 28 games over two opposite slates (NOT fit to WSH alone) → adopted
  as the live no-play trigger. At 18% it now correctly flags WSH/Littell 7/18 AND COL 7/17.
  Missed one: SF@SEA 7/17 (SEA shut out 0-7 behind an elite arm) — an unpredictable upset, the
  "acceptable variance" class Taco said he can live with. Signal works; it won't catch everything.

**TOTALS: NOT READY.** Pooled totals directional 12-15 (44%) — below coin. Do NOT bet totals on
V13.1 yet; the totals model needs work before it earns a rec. Run-line pending grading.

STANDING after validation: V13.1 = new base engine. Blowout guardrail LIVE at 18%. ML picks =
market-competitive (paper until edge proven). Totals/props = paper, not-ready. Temperature
calibration still deferred (n=28 too small to fit). Gate 0/100. $0 risked.

## 2026-07-19 — PITCHER-INDEX EXPERIMENT: NEGATIVE RESULT (do not adopt)
Tested on 7/18 (n=13, the slate with career-vs-roster xwOBA + finals). Three run-suppression variants:
  BASE (V13.1):        Brier 0.2490 | directional 9-4
  SKILL (kwERA blend): Brier 0.2502 | directional 10-3
  SKILL+MATCHUP tilt:  Brier 0.2503 | directional 10-3
VERDICT: no improvement. Brier flat-to-slightly-WORSE; +1 directional game is noise at n=13.
ROOT CAUSE (structural, not sample-luck): career-vs-roster xwOBA samples are TOO SMALL. Littell's
.478 vs ATH was 13 PA; Holmes's .426 vs TEX was 22 PA. Shrunk responsibly (PA/(PA+150)), a 13-PA
matchup earns ~8% weight -> moves win% by <1pt (WSH 44%->44%, unchanged; the exact game we hoped to
catch). Un-shrunk, it overfits noise (Bieber .433 vs CWS -> Bieber then threw 6 shutout IP). Either
way it can't help at this data granularity. kwERA base is theoretically sound but showed no edge here.
DECISION: pitcher-index NOT adopted. V13.1 run-suppression unchanged. This is the anti-overfit
discipline working — plausible idea, tested cheaply, rejected on evidence.
IMPLICATION for the broader "player index" question: the PITCHER piece is a dead end (small matchup
samples). IF we invest in player-level at all, go to LINEUP-AWARE OFFENSE — a full lineup's aggregate
wOBA is a large-sample, high-information quantity, unlike a pitcher's 20-PA history vs one roster.
Separately, the reference model's Dixon-Coles low-score correlation correction is a better lead for
the weak TOTALS model than anything pitcher-index. Both HELD pending more graded slates.

## 2026-07-19 — OBJECTIVE-FUNCTION CORRECTION (logic flaw fix, per Taco)
FLAW (we committed it): AUTH-5 framed the goal as "win% + beat the house at a HIGH CLIP / win more
often than not." That treats raw win% as the betting objective — it smuggles in risk-neutrality and
a false >50% bar. PROFITABILITY REQUIRES BEATING THE PRICE'S BREAK-EVEN, NOT 50%. A 45% pick at +150
(break-even 40.0%) is +EV and a strategy WIN while losing 55% of the time. "Highest win%" was wearing
the mask of "highest EV" — the exact substitution the whole approach was meant to prevent.

CORRECTED SPINE — the 5-step hierarchy, two layers NEVER conflated:
  1. ACCURATE CALIBRATED PROBABILITIES — DATA > Implied. Measured vs OUTCOMES (Brier, calibration,
     win% vs coin AND data baseline). This is the MODEL-QUALITY scoreboard. Win% lives HERE as a
     diagnostic — it is NOT the betting objective.
  2. CORRECT OBJECTIVE FUNCTION — the BET objective is positive EV vs the offered price's break-even
     (p_model > p_breakeven). NOT win% > 50%.
  3. DECISION vs PRICE/CONTEXT — edge = p_model − p_breakeven; act only when edge exceeds a
     model-uncertainty BUFFER (V13.1's p has error bars → require edge ≳ 4pp as a safety margin, not
     because 50% is the bar).
  4. RISK & OPPORTUNITY COST — fractional-Kelly sizing; the blowout guardrail is a step-4 control;
     bankroll/variance; don't over-bet a thin edge.
  5. OUTCOME TRACKING — grade vs outcomes; track ROI vs BREAK-EVEN (not just W-L); calibration over
     time; confidence intervals before ANY edge claim.

RECONCILES the earlier DATA>Implied vs "value" tension: accuracy (step 1) uses NO market input; the
price enters ONLY at the decision (steps 2-3). Different layers, not opposites. The 7/18 split we
saw — "win predictor 10-5 vs value bettor 5-10" — was exactly step 1 (fine) vs step 2 (the real
objective) pulling apart; now named explicitly so raw win% can't impersonate EV again.

LANGUAGE RETIRED: "beat the house at a high clip", "win more often than not". USE: "positive EV vs
the price's break-even."

EVIDENCE CONSISTENCY (all confirm no demonstrated edge yet → $0 is correct): a 21-19 record at −110
is ≈ breakeven ROI (+0.23%, actual 52.5% vs 52.38% break-even), NOT an edge; V13.1 Brier ≈ market
with no CI separation → step-1-competitive, step-2-UNPROVEN. Correct amount at risk stays $0.

CARD DECISION-RULE FIX (applies to all future cards): replace the "edge ≥ +3%" filter with explicit
EV. Per $1: EV = p_model·(decimal_odds−1) − (1−p_model). Flag a play when EV > 0 AND edge ≥ ~4pp
buffer. Report EV%, not just "edge". Win% stays on the card as a calibration diagnostic only.

## 2026-07-20 — CARD NOT ACTIONABLE; EV RULE EXPOSED CAL-1 AS THE BLOCKER
Applying the corrected EV objective (AUTH-7) to V13.1's 7/20 probabilities produced 5 "plays" — ALL
underdogs (PIT, TB, CHW, CIN, STL), incl. the absurd CHW +143 over TEX/deGrom. Measured: V13 mean
|p-0.5| = 0.051 vs market 0.059 → V13 is 13% UNDER-DISPERSED. The EV math is correct; the INPUT
probabilities are not — under-dispersion makes every favorite look beatable and every dog look +EV.
The flaw fix did its job: "win%" HID this; "EV vs break-even" made it impossible to ignore.
DECISION: 0 plays on 7/20. $0. The dog-value is an artifact, not an edge.
UNBLOCK: CAL-1 (dispersion calibration) is now THE priority — and the 1,475-game backfill finally
makes it fittable (couldn't on n=28). PREREQUISITE: enrich the backfill's features_json with each
game's pre-game V13 inputs (SP rates as-of-date, team form) so V13 can be scored on all 1,475 finals
and its probabilities recalibrated against real outcomes (temperature/isotonic). THEN the EV rule
produces trustworthy, favorite-and-dog-balanced plays. Order: enrich features -> fit calibration ->
re-run cards. No live stakes until calibration passes.

## 2026-07-20 — VERDICT FROM THE FULL BACKFILL: V13 HAS NO DEMONSTRATED EDGE (the honest capstone)
Enrichment complete: 1,461 games scored with as-of-date inputs (NO look-ahead), calibration fit with
a 70/30 train/test split. Results:
  - Fitted temperature T = 1.50 (UPPER boundary) — the fit wants to SHRINK V13's probs toward the
    52% base rate. (The n=26 July fit said T=0.55/widen — the exact OPPOSITE. Small sample lied.)
  - Held-out Brier: raw 0.2521 -> calibrated 0.2500 = COIN FLIP. Market reference ~0.238.
  - Directional accuracy 53.0% vs home base rate 52.0% and vs market's ~57%.
  - Maturity split: blind(0-2GS) 51% (WORSE than base), thin(3-7GS) 56% (only real signal, ~2SE),
    mature(8+GS) 52% (~base). No clean "improves with data" pattern; below market at every level.
RECONCILIATION: the 7/17-7/18 "18-10 / Brier≈market" was a 27-game small-sample MIRAGE. Tested on
1,461 games with honest as-of inputs, V13 is ~a coin flip and clearly worse than the market.
VERDICT: V13 is NOT bettable. $0 is not caution now — it is the correct, evidence-based conclusion
from 1,461 games. No amount of park/HFA/guardrail tuning fixes a coin-flip core.
WHY: the MC's inputs (season rate stats + team RF/RA) are too weak; the market prices lineups,
platoon, bullpen state, injuries, and far sharper pitcher models. Free-data + simple MC ≈ market's floor.
PATH FORWARD (realistic): (1) the 1,461-game dataset now enables the SUPERVISED approach (gradient
boosting/ensemble per the reference repos) — the honest next experiment, with the SAME train/test
discipline that just exposed V13; (2) richer features (lineup wOBA, bullpen rest) may add signal;
(3) accept that beating the MLB market on free data is genuinely hard and may not be achievable.
The backfill did its job: it told us the truth BEFORE any money was risked. That is the win.

Constraint notes recorded at adoption time:
- ESPN core-API odds EMPTY OUT after game completion (verified on 7/17 LAD@NYY, count:0).
  Closes are therefore captured live pre-pitch; post-hoc recovery from ESPN is not possible.
  7/17 closes: NOT CAPTURED (session began ~21:08 PT, after all first pitches). CLV diagnostic
  for 7/17: no entries. Counter: Pinnacle 0/100 unchanged; DK diagnostic remains at 7 entries.
- All web data in this environment flows through the sanctioned fetch tool (summarizing fetcher).
  Bulk-CSV endpoints unusable; JSON APIs usable with verbatim-extraction prompts. Numeric
  cross-checks between independent sources are mandatory before a number enters a ledger
  (provenance discipline per corrections log #1–#5).
