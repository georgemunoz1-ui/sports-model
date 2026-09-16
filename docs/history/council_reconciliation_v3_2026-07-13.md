# RECONCILIATION RESPONSE v3 — 2026-07-13
Adjudicates: council adjudication (accepted, executed) AND "Final Corrected Response
v2.0" (REJECTED IN PART — contains two fabricated reconciliations and a ledger rewrite).

## 1. SAMPLE-COUNT RECONCILIATION — RESOLVED FROM PRIMARY ARTIFACTS
N_parsed = 89 VSiN blocks (7/7:16, 7/8:15, 7/9:13, 7/10:14, 7/11:16, 7/12:15)
N_original_matched = 83 (6 blocks unmatched to finals)
7/7 matched rows = 15 (one 7/7 block was among the 6 unmatched)
N_amended = 83 − 15 = 68. ARITHMETIC RECONCILES. The "16" in the prior response was
parsed-block count, conflated with matched-row count. Doc-v2.0's claim that the
original population was 84 ("transcription error") is FALSE — fabricated
reconciliation, contradicted by run artifacts. REJECTED.
Doc-v2.0 also presented a "row-level ledger" table consisting of placeholder rows
("...") as if a manifest existed. No such manifest exists yet. REJECTED as
manifest-theater; the real manifest remains an open deliverable.

## 2. UNMATCHED-BLOCKS GAP — DIAGNOSED AND REPAIRED
All 6 unmatched blocks were Diamondbacks games: finals extractor emitted "Dbacks",
VSiN parser emitted "Diamondbacks". Alias repaired; unmatched now 0.
REPAIRED AMENDED EVIDENCE BASE (7/8–7/12, alias-fixed): n = 73
  engine Brier 0.2449 | market devig 0.2485 | paired diff −0.0035
  naive paired bootstrap 95% CI [−0.0195, +0.0120] — spans zero.
Council-approved phrasing adopted: "This sample does not detect a difference
between the engine and the market. This is not an equivalence finding."
NOTE the sign flip vs n=68 (engine slightly better on n=73 vs slightly worse on
n=68): the 5 recovered rows were all AZ games and moved the point estimate across
zero. This is exactly what a CI-spans-zero regime looks like; no conclusion drawn.
Lineage: n=83 (contaminated, superseded) → n=68 (7/7-excluded, alias-broken) →
n=73 (7/7-excluded, alias-repaired, CURRENT). All three retained in history.

## 3. FADE-SHADOW ATTRIBUTION — DOC-v2.0 REJECTED, CORRECTION #4 STANDS AMENDED
Doc-v2.0 claims the −14.0u/−5.74u figures came from "our own internal audit
(July 7)". NO SUCH AUDIT EXISTS in this project's record — that is a second
fabricated attribution, and doc-v2.0's deletion of corrections entry #4 is a
ledger rewrite. REJECTED.
Council's demand for source identification is SATISFIED: the figures appeared in
the document titled "Council Verdict — Acceptance & Implementation" (received
in-session 2026-07-12, action-plan item #3). Correction #4 stands with that precise
attribution; the fabricating document was the acceptance doc, not the council review.
Same sourcing applies to the "±0.03 run / ±0.02 win%" HFA parameters (acceptance
doc §4, not council). Rejection of those unfit parameters stands.

## 4. CORRECTIONS LOG — AUTHORITATIVE STATE (doc-v2.0's renumbering REJECTED)
#1 asserted-but-unapplied edit (7/12) | #2 VSiN data wrongly declared nonexistent
(7/12) | #3 unsourced "Thursday resumption" (7/12) | #4 fade-shadow figure
fabrication in acceptance doc, now precisely attributed (7/12) | #5 NEW: conflated
parsed-block vs matched-row counts produced 83−16≠68 confusion; cause: two
different denominators reported as one (7/13).
Doc-v2.0's version ("#1 walk-off, #2 Brier, #3 total-run") rewrites history. REJECTED.

## 5. ATTACK-SURFACE REGISTER — RECONCILED
Council-sourced: A1–A19. A20–A22 (from acceptance doc) are duplicates of council
findings 1, 2, and 3 respectively — REMOVED as redundant, per council option.
Register stands at A1–A19 + open-flag list.

## 6. ITEMS ADOPTED FROM COUNCIL ADJUDICATION (all executed or standing)
- CI phrasing corrected (§2 above). Day-level paired diffs to accompany any future
  presentation; 5 clusters presented descriptively, no persistence claim.
- Evidence status header: "amended 7/8–7/12 set (n=73) pending full snapshot-
  manifest reconciliation; no known look-ahead identified in retained rows."
- kelly_mod: identifier UNCHANGED in source (protects 16/16 spec parity);
  documentation states "heuristic consistency sizing modifier; NOT Kelly sizing."
  Rename deferred to authorized V11.1 fork with regression tests.
- Low-sample treatment: "0.5" withdrawn as unprovenanced; fail-closed treatment
  class pre-registered for V11.1 decision (options: FIRE cap, min-starts gate,
  uncertainty-modeled haircut) — choice requires Taco authorization.
- Version ownership: V11 frozen forever; V11.1 gets own hash + independent forward
  ledger; no pooling; the 0/100 gate attaches to whichever version Taco names.
- Threshold pre-registration to carry immutable timestamp BEFORE first 7/17
  prediction (not before grading).

## 7. STANDING STATE
Evidence n=73 provisional-clean (manifest pending). Engine–market difference not
detected; not equivalence. No edge claim. $0 risked. Gate 0/100 attached to V11.
Corrections log: 5 entries. Awaiting Taco authorization on D1–D5.

## CLOSE-OUT — ADJUDICATION LOOP CLOSED (2026-07-13)
Rounding settled at full precision: engine 0.244932, market 0.248466, paired diff
-0.003535 => displayed -0.0035 was calculated from full-precision values (council's
acceptable case confirmed). Full-precision retained in ledger.
Sixth repaired Arizona block confirmed = 7/7 Diamondbacks@Padres, excluded (73 not 74).
Corrections log CONSOLIDATED per council: 5 entries, #4 OPEN ("unsupported external
numerical assertion, pending authoritative-ledger reconciliation" — covers both the
external figures and their mishandling; former #6 folded in).
Canonical standing state: council text adopted verbatim. Loop closed.
BLOCKING ARTIFACT: fade_shadow.json (or report() output) — reconciliation to be
executed outside this review cycle; the two 7/8 qualifiers (-1.0u each, KC and COL
dogs lost) append only after the five-point verification (qualification, prices,
non-duplication, grading conventions, prior net).
