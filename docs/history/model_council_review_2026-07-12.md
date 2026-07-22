# MODEL COUNCIL REVIEW PACKAGE — 2026-07-12
Purpose: adversarial verification, NOT sign-off. Attack surfaces listed explicitly in §9.
Scope: V11 (production, locked) | V12-MC-P (parametric shadow, canary-only) |
V12-MC v2 (blocked, pending data) | falsification protocol | 6-day evidence base.

════════════════════════════════════════════════════════════════════
## 1. V11 PRODUCTION ENGINE (locked)
════════════════════════════════════════════════════════════════════
### 1.1 Signal inventory & locked weights
| Signal  | W    | Input definition                                   | Normalization (clip [-1,1]) |
|---------|------|----------------------------------------------------|------------------------------|
| g3      | 0.22 | Gate 3 BBE-adj SP score diff (our SP − opp SP)     | /15, center 0                |
| massey  | 0.18 | Massey win% − market implied%                      | /0.15                        |
| sharp   | 0.18 | money% − bets% (pp)                                | /40                          |
| sp_rel  | 0.14 | Alpha SP-Rel DIFFERENTIAL (our − opp), slate-ranked| ×2, clip                     |
| k_rate  | 0.10 | (k_stack − 45)/10; 0 for sides, live for totals    | /1                           |
| sp_reg  | 0.08 | −z(last start) — OUR SP ONLY                       | /2                           |
| career  | 0.06 | career xwOBA vs current opp roster, normalized     | clip                         |
| sp_cons | 0.04 | −std(window)/25 — one-sided [−1,0]                 | clip [−1,0]                  |
unified = Σ wᵢsᵢ ∈ [−1,1]. Tiers: FIRE >0.35 (2.0u) | MONITOR >0.12 (1.0u) | BLOCK (0u).
Kelly: adj_units = base × max(0.5, 1 − std/30). Known double-count: sp_cons in score AND sizing (flagged §13 of spec, frozen).

### 1.2 Gate 3 score (per start)
raw = 100 − xwOBA×200 − HH%×0.3 − BB%×0.5 + K%×0.5   (whole-number pcts; ~30 avg, ~50 elite)
BBE-adjusted: w = BBE/(BBE+150); each input shrunk to league (xwOBA .320, HH 35.0, K 22.0, BB 8.5), then raw formula.
HARD CAP: missing/void SP data → game capped out of FIRE (enforced upstream in main V11, not in module).

### 1.3 SP-form alphas (window N=10 qualifying starts, BBE≥5 filter)
SP-Rel = slate-percentile(ts_rank of last start) − 0.5 (cross-sectional; NOT comparable across dates)
SP-Reg = −z(last vs window; window INCLUDES last → mild attenuation)
SP-Cons = −std/25 | SP-Mom = decay-linear, computed, ZERO weight (dead signal)
Validity: <2 starts → soft-degrade to 0s, kelly_mod=1.0 (via dict-default in matchup combiner).

### 1.4 Fallback in current sessions (Statcast blocked)
gate3_proxy = 50 + (K%−22)×1.2 − (BB%−8.5)×1.5 − (ERA−4.20)×6, season aggregates.
Proxy ≠ Gate 3. All 7/8 card output was proxy-class; ceiling MONITOR by construction
when 5/8 signals dark (sharp/massey/sp_rel/sp_reg/sp_cons all zeroed+flagged that day).

### 1.5 Lock status
Zero weight/cutoff/formula changes across 6 graded days. Spec doc verified 16/16
vs source 7/12. Known-issue list (13 items) frozen, not patched.

════════════════════════════════════════════════════════════════════
## 2. V12-MC-P — PARAMETRIC SHADOW (canary-only)
════════════════════════════════════════════════════════════════════
Contract: season aggregates only. SP ERA shrunk w=GS/(GS+8) to 4.20. Team RF/RA (as-of 7/8).
Per game: IP ~ N(5.5,1.2) clip[2.5,8]; runs ~ Poisson(Gamma(k=3.5, mean/3.5)) where
mean = oppSP_ERA/9×IP×offense + oppTeamRA/9×(9−IP)×offense×0.95; ties → coinflip
weighted ±0.05 to better pen. NO walk-off truncation (margins invalid — ML only).
Known biases: team RA double-counts staff quality; totals ~0.6 low (empirically
confirmed miscalibration 7/8: actuals 8.71 vs sim 8.31); NO PARK ADJUSTMENT (COL
Coors-inflated RF → COL-away edges fired 4 days, went 1-3).
Status: canary/committee-disagreement use only. Team-only variant RETIRED
(Brier 0.2569 < coin 0.25, n=45 — SP layer is the entire source of value).

════════════════════════════════════════════════════════════════════
## 3. V12-MC v2 (blocked)
════════════════════════════════════════════════════════════════════
Input contract: reconciled per-start logs (reconcile_gamelog() gate). Blocked on
pybaseball 2026 availability. Fork test: statcast_pitcher('2026-06-01','2026-07-08',
player_id=669373) after Drive cache clear. Savant web confirmed serving 2026 (7/8+).
Forbidden from feeding V11 tiers (integration boundary, spec §14).

════════════════════════════════════════════════════════════════════
## 4. FALSIFICATION PROTOCOL
════════════════════════════════════════════════════════════════════
Gate: n=100 PINNACLE CLV closes before ANY weight/cutoff/formula change. Counter 0/100.
Dual track: DK-close-equivalent diagnostic live (7 entries). Re-anchor gate to DK
requires explicit dated amendment by Taco — NOT made; advisor recommendation logged
and rejected as insufficient authority.
Canary system: pre-registered skips graded post-game (C18–C23 complete).
Fade-shadow ledger: blind-fade ≤−150 tracked separately (0-2).
Real-money exposure to date: $0.

════════════════════════════════════════════════════════════════════
## 5. EVIDENCE BASE (all prediction-class, no look-ahead survived)
════════════════════════════════════════════════════════════════════
n=83 (7/7–7/12; 6 VSiN blocks unmatched, logged gap):
  V12-MC-P Brier 0.2405 | market devig closes 0.2378 | coin 0.25
  → beats coin; DOES NOT beat close. No edge claim made.
>5pp edges: 21-19. ≥10pp class: 2-2 (4 of 10 counter instances).
V11 MONITOR (7/8 only carded day): 4-3 paper, 0u.
CLV diagnostic n=7: all 7 MONITOR sides beat close (+0.8→+2.7pp prob). Anecdote-class.
Provenance chain: VSiN probables verified PREGAME (Misiorowski 1.47 pre vs 1.62 post);
7/10-12 box-score SP stats identified as contaminated and EXCLUDED.

════════════════════════════════════════════════════════════════════
## 6. DATA SOURCES & STATUS
════════════════════════════════════════════════════════════════════
LIVE: VSiN exports (probables+closes), DK boards (user paste), Savant web (2026 confirmed),
plaintextsports, multi-book Vegas boards.
BLOCKED: statsapi.mlb.com (2026→2021 rewrite), pybaseball (untested fork).
MISSING: money% (sharp signal dead), Massey ratings, Pinnacle closes.

════════════════════════════════════════════════════════════════════
## 7. CORRECTIONS LOG (3 entries, causes attached)
════════════════════════════════════════════════════════════════════
#1 Asserted-but-unapplied edit (docstring walk-off claim) — caught on re-read, verified fix.
#2 Declared real VSiN data nonexistent from incomplete parse — caught by disk verification.
#3 "Thursday resumption" stated without schedule source (actual Fri 7/17).
Pattern across all three: assertion outran verification. Mitigation in force: verify-
before-claim on file writes, exhaustive-parse checks, source-required for schedule facts.

════════════════════════════════════════════════════════════════════
## 8. OPEN FLAGS
════════════════════════════════════════════════════════════════════
Park adjustment absent (backlogged post-N100) | sp_cons double-count (frozen) |
intent_walk counted vs SP | cache never invalidated | z-window attenuation |
SP-Mom dead weight | 7/17 opener prices garbled (matchups firm) | ROI calc on
21-19 record queued | 6 unmatched VSiN blocks | GS ±1 ambiguity (negligible).

════════════════════════════════════════════════════════════════════
## 9. ATTACK SURFACES — COUNCIL: BREAK THESE
════════════════════════════════════════════════════════════════════
A1. CLV n=7 is one correlated slate. Alternative hypothesis: broad favorite steam
    day, not signal. Test: does CLV persist on days our sides are dogs?
A2. G3 proxy coefficients (1.2/1.5/6) were never IC-fit — inherited by analogy.
    A council member should demand their provenance or replace-at-N100.
A3. Devig method (proportional) understates favorite prob vs power devig — market
    Brier 0.2378 could shift ±.001; engine-vs-market conclusion robust? Verify.
A4. Edge record 21-19 uses devig probs but graded vs listed prices — ROI unknown;
    52.5% on dogs could be profitable OR deeply negative. Compute before any claim.
A5. Team RF/RA frozen as-of 7/8 for 7/9-12 sims — 4-day staleness. Material?
A6. Shrinkage prior GS/(GS+8)≈8-start halflife chosen by convention, not fit.
A7. VSiN "closes" assumed close-equivalent because captured at FINAL — could be
    last-refresh-before-capture. Cross-book spot-check passed once (MIL@PIT); thin.
A8. Doubleheader handling in eval (MIL@PIT 7/11 ×2) — verify block-to-final pairing.
A9. Corrections pattern (3× assertion-outran-verification) — process risk if cadence
    increases under live-capture time pressure Friday.
════════════════════════════════════════════════════════════════════
Package status: COMPLETE. Requesting adversarial review, not approval.
