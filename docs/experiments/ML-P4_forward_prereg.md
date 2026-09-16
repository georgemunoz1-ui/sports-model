# ML-P4 FORWARD VALIDATION · PRE-REGISTRATION

**Status: PRE-REGISTERED, committed BEFORE the first eligible forecast.** Owner override
2026-07-28 authorizes Phase 4 immediately. This authorization is prospective only: it does not
retroactively validate the Phase 2/3 holdout interpretation, which stays preserved with its
disclosed limitations.

## Candidate — FROZEN

`d_logistic_2f`, exactly as frozen at the P3 candidate freeze:

- coefficients β = [0.09724894149789932, 0.049056529386263814, 0.2106568691062031]
  (owner spec [0.0972, 0.0491, 0.2107] at 4dp — verified)
- config sha256 `132523ac86695b851fd8e4c88815da0416a79421e76ba0cce1c9bce24dfe096b`
  (`data/mlb/ml_asof/p3_candidate_config.json`). Hash definition, stated exactly: this is the
  freeze-time **canonical hash** — sha256 of the parsed config re-serialized as
  `json.dumps(cfg, sort_keys=True)`. The artifact's **file-byte** sha256 is
  `eede422d0659e485ecdfefb40938aaab5d705bd1aa873720460977cd7a573f47` (unchanged since freeze
  commit `6895208`). The generator verifies BOTH before every run and refuses if either differs.
- features: x1 = (h_rf − h_ra) − (a_rf − a_ra) as-of strict-before; x2 = shrunk(a_era, a_gs) −
  shrunk(h_era, h_gs), shrunk w = g/(g+8) toward 4.20
- **No refitting. No coefficient, feature, scaling or eligibility changes during Phase 4.**
  The generator refuses to run if the recomputed config hash differs.

Incumbent reference: V13 arithmetic, HFA 1.005, n=4000, forward RNG
`default_rng(int(gamePk))` — deterministic per game, slate-order independent, registered as
`ml.v13_1.p4fwd.hfa1005.n4000.rng_gamePk`.

## Statuses (ACTIVE, effective now)

ML `FORWARD_VALIDATION_ACTIVE` · K `MAINTENANCE_ONLY_ACTIVE` · RL `DATA_CAPTURE_ACTIVE /
MODEL_NOT_READY` · TOTAL `DATA_CAPTURE_ACTIVE / MODEL_NOT_READY`. The `verdicts.mlb_sides`
NO_PROMOTE *verdict* (no plays) is unchanged — FORWARD_VALIDATION_ACTIVE is a process state, not a
promotion.

## Cohort — every eligible game, no selection

Challenger, incumbent and market benchmark run on **every** game with the required inputs. No
picking disagreements or attractive prices. A failed row is quarantined **individually** with its
reason; a slate never stops for one unresolved row.

Row fields (all required): gamePk (or explicit `UNRESOLVED:` id) · teams · starters + confirmation
status · `generated_at_utc` · scheduled first pitch (UTC, per the approved conservative clock
policy) · dataset + model hashes · candidate p(home) · V13 p(home) + exact model identity ·
complete two-sided ML quote (single book) · sportsbook + `observed_at_utc` · de-vig method +
market p(home) · data-quality flags · eligibility disposition · outcome later via the grade
registry only.

**De-vig method: proportional** (`p = imp_h / (imp_h + imp_a)`), fixed now. Power de-vig may be
reported alongside as sensitivity, never substituted.

## Disposition rules (fixed now)

**PROMOTION cohort** (`PROMOTION_PROSPECTIVE`) requires ALL: generated strictly before scheduled
first pitch · both starters confirmed (not TBA/odds-named-only, no conflict) · neither starter
placeholder-contaminated or NO_LOG · team results complete through D−1 (approved staleness policy,
reconciliation not max-date) · no STALE_BLOCK starter without authoritative no-missed-start
verification · complete same-book two-sided quote with `observed_at_utc` before first pitch.

**DIAGNOSTIC cohort** (`DIAGNOSTIC_PROSPECTIVE`): any failed condition above, flagged with reasons;
still forecast, still graded, never counted toward the n=300.

**QUARANTINE**: missing inputs that make a probability impossible (no price at all, no starters) —
recorded with reason, no forecast fabricated.

**7/28 ruling (final): NOT ELIGIBLE.** The 18:07:46Z chat forecast was V13-only; the challenger's
coefficients did not exist frozen until commit `6895208`. No challenger prediction is reconstructed
from the known card. **Phase 4 begins with the 2026-07-29 slate.**

## Checkpoints and stopping rule

Primary checkpoint: **n=300 clean priced graded games**. Descriptive checkpoints at **n=100** and
**n=200**: report only — no refitting, no early promotion, no reset. Each checkpoint reports:
candidate/V13/market Brier and log loss · paired candidate−V13 and candidate−market differences
(mean ± SE) · calibration intercept + slope · reliability bins · directional accuracy (secondary) ·
excluded/diagnostic row counts with reasons · performance by probability band, descriptive.

**Pre-registered probability bands (candidate p(home)), fixed before any result:**
`[0, .40) · [.40, .45) · [.45, .50) · [.50, .55) · [.55, .60) · [.60, 1]`. No band search after
results; only these six are ever reported.

**At n=300, one decision:** `PROMOTE_TO_SHADOW_SELECTOR` / `REVISE` / `REJECT`. Promotion requires
all of: (1) candidate beats V13 on Brier AND log loss; (2) candidate calibration not materially
degraded (slope within [0.8, 1.25] and |intercept| ≤ 0.15 as the pre-set reading of "materially");
(3) the candidate−market gap measured and reported honestly — beating the market is NOT assumed;
if the candidate loses to the market, the gap is quantified and the six pre-registered bands are
examined for incremental information, nothing else; (4) no unresolved lineage, leakage or
systematic-missingness defect invalidating the cohort.

## Boundaries

Paper only; $0; no real-money wagers. Gate stays 0/100 until a separate shadow-selector protocol.
No formula changes during Phase 4. Passive capture continues all markets; priority ML → K → RL →
TOTAL. Push authorization remains separate and must not delay collection.

## Operative dependencies for CLEAN rows, stated plainly

1. `results.csv` finals through D−1 (currently ends 7/25 → until backfilled, every row lands in
   DIAGNOSTIC on team-staleness alone).
2. Pre-pitch confirmed starters (not aggregator-named-only).
3. A same-book two-sided quote with `observed_at_utc` before first pitch.
4. First-pitch UTC per the approved conservative clock policy.
