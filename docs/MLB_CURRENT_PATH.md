# Current MLB research path

The common command now resolves a real MLB adapter:

```
python scripts/generate_card_force.py --date 2026-09-14 --league mlb --simulations 100000 --output-dir UNIQUE_DIRECTORY
```

The active pointer is `data/mlb/current_v1/runtime.json`. Its package and all declared input/model pins are verified before running. An absent date, expired packet, future capture, conflicting schedule, or changed source hash is refused. Output directories must be new; exact V13 run arrays, seeds, inputs and per-game hashes are retained.

This explicitly operates the existing pinned V13 simulation and the independently frozen `d_logistic_2f` analytic candidate. It does NOT recover the missing Phase 1.1 fixed-Poisson/Gamma-Poisson generator. These are different model arms; their probability difference is not a Monte Carlo convergence test. No coefficients, frozen model source, historical forecasts, grades or canonical finals were changed. V13 return-frame capture retains the original arrays without changing RNG calls, and a regression proves identical outputs to the uninstrumented pinned function.

## Assimilation

The September 14 packet combines 1,684 Tier-1 canonical finals through August 21 with 311 staged research observations from August 22 through September 13. It rebuilds per-team runs for/against and exposes before/after form plus the deterministic forecast effect in every game. The original CSV remains unchanged. Staged observations retain their source hash, retrieval time and derived IDs; they are not elevated to Tier 1 or retroactively made pregame evidence.

D-1 and every date in the trailing 14-day window are checked. Duplicate IDs, same matchup/start duplicated under another ID, invalid finals and post-cutoff retrievals are refused. Distinct doubleheader starts remain distinct. Date continuity does not prove a complete authoritative daily census; that limitation remains in the artifact.

Refresh from a retained, reconciled source package:

```
python scripts/prepare_mlb_current.py --target-date YYYY-MM-DD --staged-directory STAGED_DIRECTORY --events-file ACQUIRED_EVENT_EVIDENCE --output data/mlb/current_v1/UNIQUE_SNAPSHOT --activate
```

Activation replaces the pointer only after packet preparation succeeds. The existing canonical-only `harness/mlb_form_state.py` path retains its stronger canonical requirement and still reports its own missing D-1; the research adapter reads the explicitly identified assimilated research snapshot instead. No canonical health gate was weakened.

## Current limits

All 20 September 14 pitcher slots fail the original freshness/availability contract. Current official probable names are bound to official game IDs, but the registered league-default treatment is applied to their numerical profiles. Information dose/action authority is zero. Current lineup, injury, relief availability and starter workload are not verified. Prior role or season ERA alone cannot fill the missing as-of pitcher history.

V13 uses a winner tie proxy, not full extra-inning settlement. Run-line and total products are suppressed. Probability values are research diagnostics, not approved bets. Repository health remains RED due to the missing production archive and overdue recovery jobs. Timestamp alignment does not enable canonical grading for this adapter.
