# Replay comparison and evidence controls

This change repairs the repository distribution verifier and candidate-method
replay. It does not modify the separately supplied `SnapshotStore`, whose source
was outside this checkout. Prior local persistence tests retain their original
scope; neither those tests nor this change establishes an integrated live
production-runner replay.

`research.replay_controls.equivalent` rejects nonfinite operands before equality,
keeps boolean metadata distinct from numbers, and requires finite nonnegative
real, non-boolean absolute and relative tolerances. A malformed tolerance fails
with `INVALID_COMPARISON_CONFIGURATION`, including comparisons with no numeric
leaves. Integer support and identity fields remain exact. The default absolute
tolerance is the original `1e-11`, with zero relative tolerance.

`scripts/verify_distribution_study.py` now reconstructs each fitted model in a
fresh subprocess through `research.distribution_replay_adapter`. The subprocess
receives fitted model state and allowlisted inference rows; outcomes and expected
checkpoints are excluded. The parent loads frozen numerical checkpoints after
reconstruction. The worker accepts no arbitrary adapter path or additional input
keys. This is a trusted-code input boundary, **not an OS security sandbox**:
hostile code on the same filesystem could still read other files. Do not claim
that this closes adversarial filesystem isolation.

The retained-study command can write new local, content-addressed evidence:

```bash
python scripts/verify_distribution_study.py data/research/distribution_replay_20261007 \
  --evidence-dir /absolute/path/new-evidence-directory
```

Each snapshot references complete hashed reports for numerical replay, PIT,
semantic verification, source authenticity and predictive validation. Bare PASS
strings or reports bound to another execution are rejected. Reads rehash both
the snapshot and every report. Existing bytes cannot be replaced through this
API; identical writes are idempotent. Local hashes do not prove remote retention,
historical existence, or independent timestamp anchoring.

A numerical replay may pass while PIT is unresolved and provider authenticity or
predictive validation remains unassessed. The command marks semantic verification
`NOT_RUN` because the replay command itself does not execute the independent test
suite. `tests/test_replay_controls.py` contains a hand-calculated six-point
residual-law fixture, attempted checkpoint-copy fixtures, tolerance/type/nonfinite
refusals, and evidence-tamper tests. A separate test-execution report can be bound
to a successor snapshot; a matching checkpoint alone never sets semantic PASS.

No selected defaults, fitted kernels, retained forecasts, original evaluation
results, registration clocks or wagering authority are changed.
