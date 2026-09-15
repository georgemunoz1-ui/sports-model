# Week 2 repair and selected default

The Week 2 default is `nfl.integrated_context.qb.v1.research`. It leads the saved 2019–2025 out-of-fold comparison on Brier, log loss, winner hit rate, margin MAE and total MAE. This is an explicit, user-authorized provisional selection from previously inspected retrospective evidence, not a new prospective screen pass. It does not use Monday's outcome to select a winner.

| Arm | Brier | Hit rate | Role |
|---|---:|---:|---|
| QB | 0.222912 | 63.43% | Default research model |
| Travel | 0.229529 | 61.82% | Challenger |
| Base | 0.229609 | 60.54% | Reference comparison |
| Combined | 0.231032 | 62.09% | Failed-screen experimental comparison |
| Availability | 0.236335 | 60.32% | Challenger |

Population: 1,865 non-tied games; six ties excluded from binary scores. Early-season subgroup hit rates differ; the policy does not cherry-pick one subgroup to override the declared all-games probability objective. The exact evaluation file is SHA-pinned in `data/nfl/contextual_v1/week2_policy.json`. A changed evidence file or default inconsistent with the ranking rule fails closed. Selection for research leadership and official release eligibility are separate fields. Action remains OFF, dose 0.

## Implemented behavior

- Both the integrated CLI and shared card adapter resolve the Week 2 default to QB. Explicit challengers remain selectable and labeled. Unknown/failed models cannot acquire headline eligibility through the policy function.
- Week 2 inference requires a complete preceding-week assimilation audit, matching source and state hashes, cutoff-valid receipts, and recalculated state features that match the actual input row. Week 1 requires all 16 finals. A stale input row fails even if its manifest says assimilation succeeded.
- QB inference now applies Week 1 dropback EPA/count updates after the declared 0.55 offseason retention. It uses the same filter as the historical builder, updates completed-game starter identity, and checks parent-model/source/state binding. This first implementation deliberately supports the 2026 Week 1 to Week 2 transition; later weeks need a chained update packet, not repeated Week 1 addition.
- `scripts/run_nfl_assimilation.py` restores 2015–2025 states, applies complete Week 1 results, exports `week2_state_packet.json`, and traces next-week reference and default-QB probability changes. These state-sensitivity calculations are not a fresh pregame card: future starter identities from a schedule are not verified current starters; weather and health require fresh acquisition.
- The existing combined score sampler is represented by an exact weighted joint measure. Win/tie probabilities, expected scores, margin, total and contract settlement can derive from that measure. Separate Ridge head centers remain diagnostics. The QB arm has no fitted arm-specific joint residual distribution; its card cannot borrow combined-arm scores or claim a QB score simulation. Binary winner simulation remains available.
- Cards show selection role, screen status, independent-head directions and assimilation status. One distribution can legitimately have opposite mean-margin and majority-winner signs; this is not prohibited by fiat.

## Distribution trace

`python scripts/audit_nfl_frozen_distribution.py --forecast FROZEN_DIRECTORY --output NEW_AUDIT.json`

The read-only trace verifies saved file hashes, model coefficients, features, independently fitted heads, out-of-fold residual support, clipping/rounding, outcome-stratum weights, exact measure and seeded draw reproduction. Monday's 100,000 score draws reproduced byte-for-byte. No Normal sigma is used in this kernel. Back-solving different Normal sigmas from its outputs is not evidence of inconsistent implemented sigmas. Exact KC-by-21 probability is about 6.888%; the saved sample's 6.909% is Monte Carlo variation. This establishes construction provenance, not calibration or a promotion of the failed-screen arm. Frozen forecast bytes are unchanged.

## Remaining acceptance work

Official release remains blocked by the previously recorded health/recovery failures, canonical pre-execution registration and external verification requirements. Fresh Week 2 event binding, expected starters, weather, injury/inactive policy and source receipts are still required. The state packet is not installed as a completed current-event package.

The official game center and refreshed PBP reconcile DEN 176 and KC 392 net yards. Walker's 173 rushing plus 18 receiving equals 191 scrimmage yards. A complete official gamebook was not recovered; independent gamebook/PBP reconciliation remains an explicit release task. Diagnostic state assimilation is not gamebook clearance.

New roster-transfer, expected-workload, replacement-quality and reserve-status transforms remain unfitted. The existing QB/availability proxies do not become those capabilities by renaming them. A challenger must be designed and registered before fitting, use stable player identity and cutoff-valid historical roles, report turnover/early-season subgroups, and face future untouched evaluation. No guessed reserve weights or manual KC/DEN point shifts were introduced.

## Test scope

`python -m unittest discover -s tests -p 'test_nfl_*.py'`

The 100-test suite includes 15 new Week 2 tests for selection refusal/default distinction, event-week binding, required assimilation, stale feature rejection, incomplete weeks, future evidence, state tampering, exact-kernel settlement/sampling, legitimate skew, missing score strata and QB source/update arithmetic. Existing 85 tests cover assimilation, contextual features, modes, personnel, halftime and spread paths.

Not established by these tests: probability calibration, future performance, true source authorship, historical injury publication completeness, roster-transfer effects, official gamebook completeness, external registration or release-health clearance. Clean-run real-source reconstruction and frozen-draw reproduction are separate evidence from synthetic contract tests.
