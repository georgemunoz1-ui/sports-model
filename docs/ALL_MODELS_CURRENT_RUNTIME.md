# Current research runtimes

Updated October 23, 2026 Pacific / October 24 UTC. This guide describes available source paths, not a claim that every league has fresh inputs or a currently qualified forecast. [Current status](CURRENT_STATUS.md) separates code, execution, health and promotion. The older runtime snapshot is [preserved](history/2026-10-23-status-refresh/ALL_MODELS_CURRENT_RUNTIME.md).

| League | Package / runtime path | Required distinction |
|---|---|---|
| NFL | `prepare_nfl_weekly_events.py`, `run_fresh_nfl_research.py`, `run_nfl_integrated.py` | Independently pinned weekly seed/state; complete prior week; current QB evidence; no partial-week advancement |
| CFB | `prepare_cfb_current.py`, shared `cfb` adapter | FBS/FBS, selected week scope, previous-week state and exact feature replay; efficiency experiment is separate |
| NBA | `prepare_initial_baselines.py`, shared `nba` adapter; optional efficiency runner | Current provider season and cutoff-aligned history; explicit initial-baseline opt-in; no qualified default |
| WNBA | `prepare_wnba_current.py`, shared `wnba` adapter | Official regular-season census/box reconciliation; do not infer postseason coverage |
| MLB | `prepare_mlb_official_current.py` or the explicit legacy current-packet path | D-1 form, starter identity/quality and original pinned engine; unknown-starter treatment is not confirmed-starter eligibility |
| NHL | Explicit scoped `capture_team_histories.py` and `prepare_initial_baselines.py` | Source-year repair does not resolve fitted rest, goalie or OT/SO qualification |
| MLS | Explicit initial Poisson package and shared `mls` adapter | Regulation home/draw/away; no automatic default or extra-time substitution |

These preparation commands live in `scripts/`. Existing six-hour source/package checks, event identity, code pins, source receipts and post-start refusals remain unchanged. Rebuilding a package from old source bytes does not refresh its source clock. An empty or missing acquisition is not proof of zero scheduled games. The old statement that NBA had no games referred only to an old acquired window and is not a current slate claim.

## Actual integration, not just feature availability

The shared CLI `generate_card_force.py --efficiency-research-config` was exercised for CFB/NBA in PR #78. Historical runs and separate selector evaluation also completed. Personnel stages remain explicitly blocked without authenticated inputs; joint stages have their own identities and evidence limits. [Run IDs and counts](research/efficiency_2026_10_23/INTEGRATION_STATUS.md).

`verify_all_current_runtimes.py` is an acceptance entry point requiring complete recovery/current/history bundles. Its historical acceptance results are not proof of today's input state. Use the current model-specific source scopes and inspect `--help` rather than reusing an expired package or old hard-coded date.

## Workflow deployment versus scheduling

| Path | Inspected trigger / result | Not established |
|---|---|---|
| [Canonical grading](../.github/workflows/canonical-research-grading.yml) | Daily cron `45 13 * * *` UTC, manual dispatch and relevant main pushes | Nonempty settlement: latest receipt has zero registrations |
| [Diagnostic shadow card](../.github/workflows/diagnostic-shadow-card.yml) | Manual/repository dispatch; a legacy branch request trigger | An autonomous daily seven-league or efficiency-challenger cron |
| [All-model operations](../.github/workflows/all-model-operations.yml) | Historical branch-specific push workflow | An always-on source refresh service on main |
| PR #78 efficiency logging | Actual local pregame paths exercised | A deployed recurring efficiency service with verified remote archive |
| CI archive / monitor | Archive hooks and persistent-monitor implementation merged | Configured authenticated uploader, successful durable receipt, notification schedule |

No workflow is enabled, dispatched or rescheduled by this documentation update. To finish recurring research execution, separately configure authorized archive transport, acquire fresh complete packages, freeze the candidate/protocol and schedule, exercise a genuine pre-start run through readback/registration, then grade authentic finals. Preserve failed attempts; do not backdate registration or count superseded candidate records as additional games.

## Output semantics

Independent winner, margin and total heads are not automatically a single coherent score distribution. The CFB selected parent lacks a total head. MLB full-game run/total settlement remains outside winner qualification. NFL selected-QB probabilities cannot borrow a combined-arm score pool. MLS's Poisson dependence assumption and NHL's OT/SO treatment must be explicit. Current injuries, lineups or goalies are not numerically used merely because they appear in disclosures.
