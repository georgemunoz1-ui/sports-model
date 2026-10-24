# NFL pregame — September 28, 2026

PHI at CHI, 5:15 PM Pacific (00:15 UTC September 29). Selected registered model:
`nfl.integrated_context.qb.v1.research`. Fresh execution through
`scripts/run_nfl_integrated.py`; 100,000 binary non-tie winner simulations per
explicit Chicago QB condition. No mixture weights or official starter assertion.

| Chicago QB condition | PHI model | PHI simulation | CHI model | CHI simulation |
|---|---:|---:|---:|---:|
| Keenum | 59.18% | 59.03% | 40.82% | 40.97% |
| Bagent | 58.73% | 58.75% | 41.27% | 41.25% |

Execution COMPLETED; predictive validation HOLD; publication INELIGIBLE;
wagering authority OFF; dose 0.0. These are registered-model research outputs.
The existing writer records actual pre-start times but explicitly sets
`canonical_prospective_eligible:false`; canonical forecast registration and
prospective grading eligibility have **not** been granted.

The official Bears and Eagles injury reports still leave Chicago's starter
unresolved. Keenum is the reported-starter condition; Bagent remains a separate
sensitivity. Final inactives are pending. The QB arm uses fitted weather
imputation; non-QB injury effects are not numerically used. Scores, spread,
total, tie/push pricing and a score distribution are unavailable for this arm.

## Package and state

Main was inspected at `43ad83382af067b019a086d45d23569497ca6e08`.
The existing September 28 source capture was reused after byte/hash checks and
full-season schedule validation: schedule retrieved at
2026-09-28T05:52:34.690993+00:00, 4.60 hours before preparation, within the
existing six-hour schedule budget. Original source timestamps were preserved.
This is a newly built event package using current retained sources, not a new
network capture and not a reused September 14 event package.

The selected state is `e962a66b806e2371f7890ec6bc91c57726282ea2b2467a05761c603f00d406cf`,
completed_week=2, 32 games. Its full seed/Week1/Week2 chain replayed successfully.
Week3 Sunday results remain excluded from Monday's parent; the week cannot be
sealed before Monday finishes. Both forecasts prove consumption of this state,
including team/QB state hashes and all nine state-derived feature values.

`prepare_nfl_event.py` now excludes verified `weekly_state`/`assimilation`
bindings from the source-receipt list, matching the inference binding contract.
It still validates them through `live_features` before writing the package.
Missing real source-receipt fields continue to fail. No inference, fitting,
default, global runtime pointer, frozen forecast or grading state was changed.

## Verification and retained evidence

Both complete forecast payloads and 100,000 draw arrays replay exactly. Package,
model, feature, context, raw-source, state, forecast and draw hashes are retained
in `run_receipt.json`, `preparation_receipt.json` and per-run manifests.
NumPy PCG64; arrays are uint8, shape (100000,), C order. The seed is derived
from the complete forecast identity and the registered binary simulation kind.

403 local tests and 45 subtests passed before the dependency-free retention
test adjustment; the revised retention/grading tests passed 24 tests and 30
subtests. The existing MLB acceptance fixture matches exactly. 2,370 base-tree
files were checked: the only modified existing files are the MLB workflow and
NFL package builder. All other tracked bytes, including defaults and durable
grading state, match main. Repository health/release restrictions remain RED;
software tests do not clear them.

The first replay check omitted the integrated CLI's absolute-path state binding
and therefore correctly failed the identity comparison. Repeating the exact CLI
binding produced identical payloads and draws. Both verification logs are retained;
no frozen output was changed to pass the check.

## Reproduction

Extract the evidence archive into a checkout of the pinned repository revision
with the package-builder patch. It adds `research/nfl/2026-09-28-current/` with
source bytes, immutable state objects, prepared inputs/packages and frozen runs.
Inspect the saved receipts first. Do not rerun into an existing frozen directory.
Before kickoff, for each condition use a new output directory:

```bash
NFL_WEEKLY_STATE_SEED_SHA256=85a125580dbe1be76cac0d0edbb889d9ec22040ae078263c49460721484718d6 \
NFL_CONTEXT_PACKAGE=research/nfl/2026-09-28-current/keenum/event_package.json \
python scripts/run_nfl_integrated.py --date 2026-09-28 --simulations 100000 \
  --weekly-state-store research/nfl/2026-09-28-current/state \
  --weekly-state-id e962a66b806e2371f7890ec6bc91c57726282ea2b2467a05761c603f00d406cf \
  --output NEW_UNIQUE_OUTPUT_DIRECTORY
```

Substitute `bagent` for the other condition. The environment explicitly selects
the dated package; the September 14 global pointer is preserved. A new run must
recheck freshness and start time. A relocated state path changes the forecast
identity and seed; exact archived draw replay uses the saved identity/seed.
Original writer timestamps cannot be regenerated or backdated.

Sources: [Bears official report](https://www.chicagobears.com/news/injury-update-bears-rule-out-caleb-williams-will-start-tyson-bagent-or-case-keenum-vs-eagles),
[Eagles official report](https://www.philadelphiaeagles.com/news/eagles-at-bears-injury-report-2026-nfl-week-3-monday-night-football-caleb-williams-saquon-barkley),
[nflverse schedule](https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv).
Market features OFF; action authority OFF; all existing release restrictions remain.

Durable evidence: `NFL-Pregame-2026-09-28-Registered-Model.zip`, libfile_429776e038c08191a697c9868cc6a92d.
Archive SHA-256: `c26961d424c7d2145dc433850ac7ca14be32dc2f1788ab96b079596be8b53bf2`.
