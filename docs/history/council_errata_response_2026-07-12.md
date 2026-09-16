# COUNCIL ERRATA RESPONSE & AUTHORITY ADJUDICATION — 2026-07-12
Council verdict: ACCEPTED as to findings. Acceptance-document: PARTIALLY REJECTED —
it contains one fabrication and commits to changes exceeding advisor authority.

## A. FABRICATION REJECTED
Acceptance doc item #3: "Recalculate Fade Shadow arithmetic; post corrected net
(-14.0u, not -5.74u)." NEITHER NUMBER EXISTS in any ledger of this project. The
fade-shadow track is a 0-2 RECORD-ONLY log; no unit sizing was ever assigned or
computed. Both figures are injected fabrications. Rejected; corrections log #4
(external-document fabrication caught by ledger check).

## B. ERRATA EXECUTED NOW (documentation-class, no authority required)
1. Brier notation: "0.2569 < coin" corrected to "0.2569 > 0.25 (WORSE than coin)".
   Conclusion was always stated correctly in prose; inequality symbol was wrong.
2. Totals offset: 0.6 = sim-vs-LINES (7/8, 8.31 vs 8.89); 0.40 = sim-vs-ACTUALS
   (8.71-8.31). Two different comparisons conflated in prose; both retained, labeled.
3. "SP layer is entire source of value" RESTATED: "On this 6-day window the
   SP-informed variant beat coin and the team-only variant did not (unpaired,
   n=83 vs n=45); persistence and paired significance unestablished."
4. Counter denominator: extreme-edge counter TARGET n=10 instances; OBSERVED 4;
   record 2-2; 6 instances not yet occurred (not unexplained).
5. Threshold provenance: >5pp and >=10pp were EXPLORATORY on 7/9-12 (declared for
   7/8 only). Reclassified; forward use now pre-registered.
6. Status language adopted verbatim: "REVIEW-READY. Validation incomplete. V11
   frozen paper baseline; V12-MC-P canary-only; V12-MC v2 blocked. No production-
   edge, profitability, or capital-deployment claim is supported."

## C. LOOK-AHEAD REMEDIATION EXECUTED (evidence hygiene, not model change)
Council A13/finding 3 CONFIRMED: 7/7 rows used team RF/RA as-of 7/8 (contains 7/7
results) => contaminated via team inputs despite pregame SP probables. 16 rows
EXCLUDED. AMENDED EVIDENCE BASE (7/8-7/12, n=68):
  engine Brier 0.2417 | market devig 0.2391 | paired diff +0.0026
  paired-diff 95% CI (naive bootstrap): [-0.0140, +0.0182] -> INDISTINGUISHABLE
  from market at this n; day-clustered block bootstrap queued (5 clusters is too
  few for a stable clustered CI — noted, not hidden).
Superseded figure (n=83, 0.2405/0.2378) retained in history, marked contaminated.

## D. COUNCIL FINDINGS ACCEPTED, EXECUTION GATED ON TACO'S DATED AUTHORIZATION
Per lock discipline, the following are correctness-repair VERSIONS the council
sanctions in principle but only Taco can authorize (each needs a dated one-line
amendment):
D1. V11.1 — Gate 3 shrinkage fix (K%/BB% by TBF/PA, not BBE). Council-critical,
    mechanically real, endogeneity confirmed. Fork note: with per-start Statcast
    PA is already computed in the module; fix is small. Restarts forward counter.
D2. Sizing: rename kelly_mod -> consistency_sizing_modifier (doc-only, can do now)
    AND fail-closed low-sample cap (<3 starts -> 0.5 not 1.0) — the cap is a
    behavior change => V11.1 scope, not doc scope.
D3. MC-P v1.1 — home-field term + starter-specific IP. REJECTING the acceptance
    doc's invented parameters ("±0.03 run, ±0.02 win%") — no provenance, same
    unfit-parameter class the council flagged. Any HFA term must be fit or sourced.
D4. Counter bridge (DK-close to advance gate) — standing position unchanged:
    requires Taco's explicit dated amendment.
D5. Falsification decision rules (CLV mean/median, calibration slope, ROI, subgroup
    tests) — draft to be pre-registered BEFORE first live counter entry Friday.

## E. NEW ATTACK SURFACES A10-A22: ACCEPTED into the register verbatim.
A11 partial verification note: on 7/8 the FIRE-eligibility concern was not reachable
(sharp/massey zeroed), but the spec-level path (0.64 available weight) is real.
Antisymmetry test (A15) queued to V11.1 test suite.

## F. STANDING STATE AFTER THIS RESPONSE
Evidence: n=68 clean, engine ~= market (CI spans zero). No edge claim. $0 risked.
Corrections log: 4 entries. Gate 0/100. Friday live-capture plan unchanged, plus:
pre-registered decision rules (D5) must be filed before the first entry.
