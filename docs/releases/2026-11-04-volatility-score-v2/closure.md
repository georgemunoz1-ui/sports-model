# PR105/PR106 energy-scoring incident: local repair evidence

**Status: LOCAL_VERIFIED_HOSTED_PENDING.** Base commit:
`629ed150612a56f2dabaecdecaab7019af3e7630`. Repair commit is not assigned;
the coordinator must review and commit the final local patch separately.
No remote repository, workflow, settings, PR status or merge was changed here.

The old metric gave a lower expected score to an incorrect wider synthetic
forecast (0.70710678) than to the true distribution (0.75). The additive v2
metric uses unscaled Euclidean distance with fixed coordinate order
`[home_score, away_score]` and unit scales. It correctly ranks truth at
0.53033009 ahead of the wider alternative at 1.41421356. The regression retains
both old and corrected values; it does not rewrite the historical record.

New score records carry metric/scale-source/code identities. The v2 evaluator
rejects old or mixed metric records; `rescore-v2` makes a separate derived record
bound to the exact frozen grade and distribution. The CLI defaults `grade` and
`evaluate` to v2, while explicitly named legacy-v1 commands retain reproduction.

The retained command in `closure.json` completed with **51 passed, zero
failures/errors/skips**: 15 new scoring tests plus 36 existing matrix/replay
tests. `targeted-tests.log` and `targeted-tests.xml` are bound by SHA-256 in the
closure record. Fifteen protected source/state/default/replay files match their
base hashes, including the original numerical module and all six fitted models.

The startup health command separately exited 1 for existing source archive,
overdue recovery, historical BLOCKED release and standing-health evidence debt.
Its three generated audit-file changes were restored and excluded from this
repair. Global health is not cleared by the scoring tests.

Independent verification remains pending. After final local review, owner
confirmation is still required before remote publication/workflows/merging;
hosted checks and independently retrieved evidence must bind the actual repair
commit. PR106's parent-orientation and closure-evidence failures are separate
incidents. Predictive qualification, model/default promotion, forecast/grading
authority, production enablement and wagering remain unchanged and ungranted.

Independent verification: PASS (19 tests, 1,643 protected original files unchanged). Evidence retained under `independent/`. Local implementation commit: `5e7f13552190a5f78181afa864ed69d4c1fd96ba`. Required-check configuration remains unverified (HTTP 403). Hosted pinned-environment verification remains pending.
