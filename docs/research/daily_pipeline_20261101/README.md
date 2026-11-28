# Daily selected CFB operating pilot: actual execution evidence

Executed November 1, 2026 Pacific / November 2 UTC. This packet records genuine
pregame execution, the first two canonical-writer research registrations, remote
retention readback, and a separate postgame waiting-path execution. It does not
establish a completed forecast-to-final cycle or an active default-branch daily
service. Official release and wagering authority remain OFF.

## What is now exercised

The unchanged selected `cfb.fbs.elo_form_logit_ridge.v1_0.shadow` model runs on
fresh, source-bound current packages for FBS/FBS events in week 2 or later. Each
hosted execution retained 29 capture receipts, exact event/team/start/status
reconciliation, the full selected-model card, and 100,000 winner draws per event.
The workflow uploaded and downloaded its complete Actions artifact, verified
every manifest-bound byte, registered through the existing canonical writer,
and pushed the immutable execution and registry to a separate evidence branch.
A fresh remote checkout then verified the exact committed bytes.

| Hosted run | Source commit | Actual result |
| --- | --- | --- |
| [41401199915](https://github.com/georgemunoz1-ui/sports-model/actions/runs/41401199915) | `ff9cd745` | Two fresh executions succeeded; first registered two events, second retained the original receipts |
| [41401921392](https://github.com/georgemunoz1-ui/sports-model/actions/runs/41401921392) | `7fcf5138` | Both final-runtime executions succeeded; pinned dependency versions and full installed-distribution inventory verified; no new or replaced registrations |
| [41402593838](https://github.com/georgemunoz1-ui/sports-model/actions/runs/41402593838) | `2c8d4088` | Separate authenticated postgame restoration/readback succeeded; two registrations retained, zero due events, zero grades |
| [41401921500](https://github.com/georgemunoz1-ui/sports-model/actions/runs/41401921500) | `7fcf5138` | Injected failure produced [issue #104](https://github.com/georgemunoz1-ui/sports-model/issues/104), verified by issue readback and independent artifact download |

There are **two unique prospective research events**, not four independent event
samples. The repeated executions establish reproducibility, retention and
idempotence. They do not enlarge the predictive sample or replace the first
forecast probabilities.

## Original registered forecasts

Writer registration occurred at `2026-11-02T06:40:29.729255Z`, before both starts.
These are winner-only research forecasts from the unchanged selected parent.
Cover and total products are explicitly unavailable for this model in the full
card. No market inputs were used.

| Event | Start, Pacific | Model winner | Original analytic probability | Original 100,000-draw probability |
| --- | --- | --- | ---: | ---: |
| CFB:401866453, Ohio at Akron | November 3, 4 p.m. PST | Ohio | 89.8614732763% | 89.972% |
| CFB:401866454, Buffalo at Miami (OH) | November 3, 5 p.m. PST | Miami (OH) | 61.5188319697% | 61.435% |

Canonical receipt IDs:

- Ohio at Akron: `f864b52009a49aa3aa290db157a253b15e281f574cf1bd6a96877981691007a3`
- Buffalo at Miami (OH): `f1895940d7331e790ae14ed33e0689fcf293be0c8fbcf5aa75ac95adee81a3cd`

The original card SHA-256 is
`d75928df9b8cb9897170069a190ebb0ad61ece995855783aabbd2e3fb4880fe0`.
Registry SHA-256 remained
`12f0a6bb1e50d059e8864e3ecb2957a7d90cc62ff720e4bcefe75799b3fb3230`
through all four fresh executions and the postgame waiting attempt.

The evaluation cohort is `PROSPECTIVE_RESEARCH_SOURCE_UNVERIFIED`, and
`certified_calibration_eligible` remains false. Actual capture times, repository
identity, content hashes and pre-start writer receipts do not independently
authenticate provider observation history or qualify the parent model.

## Retention and independent verification

The full evidence and writer state live on
[`research/daily-cfb-archive-v1`](https://github.com/georgemunoz1-ui/sports-model/tree/research/daily-cfb-archive-v1).
The postgame-inclusive verified commit is
[`61251edf2ac6ac088be90e26042dddfb67386710`](https://github.com/georgemunoz1-ui/sports-model/tree/61251edf2ac6ac088be90e26042dddfb67386710).
Its 339 retained files include every original execution and the two immutable
forecast receipts. Each final-runtime run has a 77-file core and an 82-file
execution envelope. Independent review checked all manifest entries, raw-source
bindings, 15 source-code snapshots per run, both writer receipts, and the actual
dependency inventory.

Actions artifacts expire after 90 days. The separate versioned Git archive has
no automatic Actions expiry. It is not WORM storage, a protected external
archival service, or independently signed provider evidence. Failure notification
verification covers GitHub issue creation/readback; email, push and human receipt
were not verified.

Read `independent-forward-verification.json`,
`final-runtime-forward-verification.json`,
`independent-postgame-waiting-verification.json`, and
`independent-postgame-artifact-verification.json` for the exact comparisons.
`github-actions-artifact-metadata.json` retains actual artifact IDs, digests,
creation times and expiry dates. The original failure notification body is
retained byte-for-byte in `failure-drill-delivery.json`.

## Postgame behavior and repaired acquisition obstacle

The separate postgame workflow restored the authenticated archive and found no
registrations through its requested October 31 date. Its explicit state was
`NO_REGISTRATIONS_THROUGH_REQUESTED_DATE`, with two registered forecasts and zero
new grades. No settlement ledger was written. This is expected for November 3
events and is not a completed prospective cycle.

A separate real final-source probe found that the prior multi-day ESPN CFB URL
returned HTTP 400. The repaired acquisition uses exact daily endpoints and only
tries adjacent dates when the exact event is absent; transport denials, identity
conflicts and malformed finals remain failures. The probe retrieved and re-parsed
CFB:401856733, Missouri 34 at Arkansas 10. This was only acquisition and
normalization: it created no forecast, registration or settlement.

`live-final-source-probe/` preserves the exact successful probe bytes and original
manifest. The parent failed report and path mapping are separate files, so the
original sealed directory is unchanged. Original absolute receipt paths remain
historical evidence; the path map gives their retained repository locations.

An execution follow-up named **Grade first CFB registrations** was created for
November 4 at 8 a.m. Pacific, with at most three daily attempts. It must execute
and independently verify grading of the original two receipts after authentic
finals, and stop after success. No future execution or final result is claimed
here. It cannot substitute for deployment of the daily repository schedules.

## Software verification and source-bound CI evidence

- Each hosted pregame job passed 245 acquisition, forecast, registration,
  retention, notification and grading tests.
- The hosted postgame job passed its 59 focused tests before restoring the real
  registry. These overlap the pregame suite and are not an additional unique-test
  population.
- The current-source research-integrity job passed its 617-test step and actual
  retained-input NFL replay, then failed solely because the historical finding
  packet bound older `canonical_forecasts.py` bytes. Its failed overall status is
  preserved in `ci_reverification/`.
- A new `FINDING_EVIDENCE_daily_pipeline_v1.json` binds the verified current-source
  evidence and preserves the historical packet unchanged. All 19 successor
  findings validate locally. The CI pointer now checks this successor; current
  hosted status must be read from the PR checks rather than inferred from local
  validation.

Synthetic test fixtures are engineering evidence only. They are never personnel
observations, final results or prospective events. Full local logs and source
bindings are retained alongside `EXECUTION.json`.

## Remaining operating dependencies

PR #95 remains a separate open preflight. This pilot advances issue #96 without
closing it. Both implementation PRs remain drafts; no default branch, selected
model, historical forecast or authorization state was changed.

The pregame and postgame cron declarations require reviewed default-branch
deployment. The pilot restores `research/daily-cfb-archive-v1:registry/`; the
legacy main grading workflow still reads `main:data/grading/canonical/`. A unified
service needs an explicit single-state integration before competing writers are
enabled. Other leagues have not been claimed operational by this CFB pilot.

The complete live cycle still needs actual finals, append-only grades, and
verified retention of those grades and source bytes. Independent source
authenticity, historical parent-model provenance and predictive qualification
remain separate unresolved questions. Main's existing health check remains RED
with four failures and eight warnings; its full output is preserved here.

The separate personnel-source integration is PR #103 on PR #100. Its diagnostic
report found zero admissible personnel-v2 observations; these baseline CFB
forecasts do not use or validate that challenger.
