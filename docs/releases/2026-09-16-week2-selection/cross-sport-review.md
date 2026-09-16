# Cross-sport review protocol — 2026-09-16

Status: review protocol, not forecast registration or release clearance.
Action authority OFF; dose 0.0.
Evidence baseline: main 547053102f25952323d123b019df07aed9661fc9.
Prior amendment: audit/week2-selection-20260916 at b28da9ea1b434101ea7556f6fef48dbc17a78c73.
Historical forecasts, manifests, selection records, and model parameters remain unchanged.

## Cadence and scope

Use one morning review in America/Los_Angeles. MLB gets a short daily review and
a full Tuesday review. NFL gets its full Tuesday review and a separate event-specific
go/no-go before the declared cutoff. CFB gets a review the morning after each game day,
including midweek games; Tuesday provides a weekly rollup. The morning automation
checks readiness as of its actual retrieval time; it is not a guaranteed final
pre-cutoff check and cannot certify later lineup or inactive releases.
If an early event has already started, mark it POST_START and do not construct a
pregame claim. A postponed or missing slate is not silently treated as zero games.

Determine season phase from each league's current official schedule on every review.
Do not group NBA/WNBA/MLS as preseason: on this review date WNBA and MLS are in season.
NBA preparation status and model readiness are separate facts. Unsupported current-form
claims get BLOCKED-UNVALIDATED; this label does not erase valid historical model evidence.

## Task 3 — verify operational gates

| League | Required checks and failure labels |
|---|---|
| NFL | Official gamebook/PBP reconciliation; P3 games → state → actual Week 2 runner features → forecast contribution; fresh event/personnel/weather context; selection and forecast registration timing; accessible verification manifest. Sixteen reproducible state checks alone do not close P3. |
| MLB | Execute packet validation: package/input/code hashes, slate identity, capture/cutoff ordering, TTL, prior-day state, duplicate/date-hole checks. Record command, exit status, commit and evidence hashes. Separately reconcile expected games to the official schedule; day coverage does not prove game coverage. Record PBP digest and actual lineup confirmation time; probable lineups are not confirmed lineups. New evidence requires a new packet, never revised September 14 pins. |
| CFB | Report CONTROL-MISSING for the selected winner model's current-season assimilation/freshness claim until an executable gate and effect demonstration exist. Source availability and a roster capture do not prove state assimilation. |
| NBA | Confirm automatic selection still refuses to choose an unsupported default. Check schedule and roster finalization for preparation; a runnable adapter is not validated selection. |
| WNBA | Keep FF7's target-specific historical evidence distinct from fresh fitted-state/feature-frame availability, lineup/minute-limit checks, assimilation evidence and runnable current-card integration. Missing current inputs block a current forecast, not the historical evidence label. |
| MLS | No verified default forecast engine; retain selector refusal. In-season source/recovery work does not establish current-form forecasting capability. |

Statuses: PASS, FAIL, CONTROL-MISSING, UNKNOWN/NOT-RUN. Uninspected controls cannot pass.
Gate existence, fixture execution, current-packet execution and official eligibility
must be separate reported fields. Evidence available only to authorized repository readers
is not a public verification manifest.

## Task 4 — cohort and arm evidence

NFL QB arm: provisional research default; OOF 2019–2025 in reused history, 1,865 non-ties.
Combined NFL remains experimental. Week 1 stays graded under the arm that actually headlined.
B2: trace complete, registration/specification still separate; earliest prospective evaluation
Week 3 against the QB baseline, no Week 2 B2 execution. A QB-specific distribution must exist
before a variance experiment can claim that baseline.

MLB: name V13's own historical screen, population, evaluation dates, target and NO_PROMOTE
restriction. Do not import NFL selection logic as evidence of MLB predictive superiority.

CFB: selected FBS form arm, appropriate week/subdivision cohort, with
RESEARCH, NO-CURRENT-SEASON-ASSIMILATION-GATE.
NBA/MLS: no verified default. WNBA: FF7 target-specific evidence, conditional current readiness.

Preserve these distinctions verbatim:
- out-of-fold within reused history ≠ untouched program-level holdout
- research default ≠ permanent default
- selected arm ≠ official forecast eligibility

Do not select champions by unit-test count, simulation count, feature count, or a small
recent hit-rate sample. Compare declared metrics and eligible cohorts under registered rules.

## Task 5 — lessons and evidence inputs

NFL: input-field lineage, uncertainty/cushion, failed-screen headline prohibition,
win/margin/score reconciliation, gross/net/sack-yard accounting, honest labels.
Require ledgers, gamebooks/PBP manifests, team-state deltas, feature deltas, model contribution,
registration record, event cutoff and verification-manifest location.
A feature can change with zero numerical effect; record why rather than force a nonzero delta.

MLB: September 14 immutable-package lesson and injury-report lag.
Require daily PBP/results digest, expected-game reconciliation, pitcher/lineup confirmation
timestamps, injury effective/retrieval times, bullpen availability, park/weather and packet hashes.

CFB: demonstrate current-season state changes reaching selected-model inputs before any
freshness claim. Require rosters, transfer-portal changes, depth charts, schedule,
results/source manifests and player/team identity mapping.

NBA/WNBA/MLS: verify season schedule and roster finalization dates independently;
register evaluation before the applicable future cohort begins. Do not retroactively
register an already-started season as untouched prospective evidence.

## Review output and execution boundary

Report league/date/timezone, actual cutoff checked, season phase/source, exact selected model,
target/cohort, evidence tier, Task 3 gate results, Task 4 status, Task 5 incident/delta,
artifact references, unresolved blockers and next concrete action.
Short daily MLB output may use one row per blocker; Tuesday expands the evidence review.
CFB post-game review is conditional on newly completed games, with a weekly rollup.

Scheduled work is an evidence/readiness review only. It does not enable unattended numerical
forecasts, mutate historical packets, promote models, register an incomplete experiment,
issue official forecasts, execute bets or send messages to third parties. Preserve the
existing requirement for manual validation/artifact review before scheduled forecast production.

## Verification performed for this amendment

Executed on the baseline checkout:
`python3 -m pytest tests/test_mlb_current_path.py tests/test_model_defaults.py -q`
Result: 29 passed.

Coverage includes packet/input hash rejection, wrong-slate/expiry rejection, staged-result
chronology/duplicates/date holes, deterministic draw capture and default-selection refusal.
MLB composition fixtures explicitly mock the loader to retain a historical package;
those tests do not establish a fresh packet's validity. The package-integrity test
separately exercises the real loader against isolated fixture files.
No fresh forecast, current MLB packet, CFB assimilation gate or official release is established.

Season references checked 2026-09-16:
- WNBA schedule: https://www.wnba.com/
- MLS official 2026 schedule: https://www.mlssoccer.com/news/mls-announces-2026-regular-season-schedule
