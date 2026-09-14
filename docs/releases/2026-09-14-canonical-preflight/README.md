# DEN at KC: canonical-release preflight

Requested operational source: sportsmodel/main at 34a7ec7e74db64d04197b4188771f2a9868cd045.
Event: 2026_01_DEN_KC, Denver away, Kansas City home, Arrowhead, kickoff 2026-09-15T00:15:00Z.
This is a preflight investigation, not a forecast or registration.

## Verified ARM_A identity

The original 2025 SRS reference bundle SHA-256 is
8a1bad4c3326c5ceb5089d9cae6d76662bd2a76a0afd76ffd1fbda3c5de7c659.
The recovered original bundle matches that digest. Its engine is
nfl.elo_margin_monte_carlo.v1, version 1.0.0. Engine, runner, configuration and
historical population byte hashes are retained in canonical-release-request.json.
The engine also exists unchanged at research/audits/2026-09-10/nfl_engine.py.
This is distinct from nfl.integrated_context.combined.v1.research used in the
September 14 17:19 UTC test. No substitution between those identities is allowed.

The frozen runner applies zero QB/injury adjustment points and no current weather,
travel or final-inactive effects. Its final-inactives scope is therefore excluded,
not complete. Generic configuration text mentions injury adjustments, but the
actual frozen runner and bundle explicitly show they were not applied.
No new inactive-aware profile is adopted here.

The original engine calls its outputs emergency diagnostic/unvalidated. It uses
logistic analytic probabilities and Normal score-proxy simulation probabilities,
which are different distributions. Score-proxy ties are resolved by a coin flip
for a binary winner; this is not an NFL final-score/overtime settlement model.
Full-game spread and total products remain unsupported for frozen ARM_A.
Operational registration alone cannot validate that product contract.

## Timing contract

Separate three instants:
1. Input freeze/cutoff: latest allowed predictive information.
2. Externally acknowledged pre-execution registration: hashes, exact arm and cutoff.
3. Output-publication deadline: after computation and before kickoff.

A manifest containing newly computed output hashes cannot be required before the
input cutoff while execution is required after that cutoff. The publication
requirement is before kickoff, with a separately declared earlier deadline.
No future cutoff or execution appointment is assigned while preflight is blocked.
No registration is fabricated from this request record.

## Existing evidence corrected

The 17:19 UTC test has local post-execution registration, not pre-execution
canonical registration. Its full ZIP was saved persistently. The earlier 17:11
verification archive and manifest are also committed to the private GitHub
repository. They are not sandbox-only; access is authenticated, not public.
Neither fact changes their research/non-canonical standing.
Simmons and Conner OUT were already encoded in the combined test inputs.
Pending final inactives does not mean those public absences were absent.

## Checkout audit

Draft PR #26 adds a read-only GitHub Actions audit pinned to operational 34a7ec7.
The first job verified exact checkout, a clean pre-execution tree and git fsck,
recorded dependency/runner fingerprints, and produced a full Git bundle.
It executes the existing healthcheck unchanged and stores its exit separately.
A successful audit workflow means evidence collection succeeded, not health GREEN.
Direct artifact download returned HTTP 403. The authorized file-materialization
route then succeeded. The archive digest and all 14 per-file hashes verified.
The Git bundle restored a complete local checkout at 34a7ec7 with clean status
and passing git fsck. The second audit also exposes nonsecret receipts in job logs.
Environment fingerprints are measured evidence, not a pre-approved container lock.

Prior forecasts, labels, registries, grade ledgers, coefficients and authority are
unchanged. Canonical eligibility stays false pending a passing release attempt.

## Release decision

NO_CANONICAL_RUN: the full, unchanged remote healthcheck exited 1 with five
failures and six warnings. This is actual repository evidence, not an inference
from the earlier incomplete local checkout. No fresh release input capture,
pre-execution registration or forecast execution proceeds past that failed gate.

- [FAIL] relay_parser selftest (relay_parser selftest: FAIL (fixture absent — nothing was checked))
- [FAIL] ingest_lancebroz selftest (  - dry run found nothing to append and nothing already present - window)
- [FAIL] module manifest (MANIFEST_REFUSED; 183 registered, 1 problems)
- [FAIL] recovery jobs (7 registered, 5 overdue, 7 defect(s) still owned)
- [FAIL] PregameDecisionReadiness v1.0 acceptance (standard acceptance: 15/16 passed  — STANDARD NOT IMPLEMENTED)

Environment fingerprints were captured, but no approved fully resolved/container
lock is established. The local Git checkout is now complete; a later release
attempt must fix real failures without deleting recovery obligations or waiving
tests. canonical-no-run.json is the machine-readable decision.
