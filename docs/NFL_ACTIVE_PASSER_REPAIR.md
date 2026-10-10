# Explicit nominal-starter versus active-passer binding

The weekly QB state previously required every schedule starter to appear in the
qualifying passing sample. In 2026 Week 4, Chicago's Case Keenum took the opening
handoff while Tyson Bagent handled the passing. Keenum's nominal starter record
was not a stale or false assignment. Seattle separately had a stale Drew Lock
assignment where the retained summary and first passing play identify Sam Darnold.

## Repair contract

`starter_adjudication.apply` returns an additional `home_active_qb_id` and
`away_active_qb_id`, defaulting to the original schedule QB. The weekly reducer
uses this active ID for its existing required qualifying-dropback binding.

A reviewed `resolution_kind: NOMINAL_STARTER_NO_DROPBACKS` keeps the schedule
`*_qb_id` unchanged and sets only the active ID. It requires the original schedule
ID, full schedule name, and an exact retained article excerpt containing that
name, in addition to all existing source/hash/event/team/final/first-QB-play
checks. An original nominal starter appearing as a passer or scramble rusher
rejects this narrowly defined no-dropback resolution.

`STALE_SCHEDULE_STARTER` remains a separate correction type. Omitted type retains
that historical behavior. Unknown kinds refuse. No maximum-dropbacks heuristic
or unchecked automatic player substitution is introduced.

The exact reviewed WSH/WAS alias requires ESPN team ID 28, full display name
Washington Commanders, and the explicit per-resolution provider binding. No
other alias is silently canonicalized.

## Immutable state and migration

Source bytes and existing objects remain immutable. Changed transform hashes
require a new reviewed seed and complete replay. No default state pointer, fitted
coefficient, selected model, live CLI or official-release gate is changed by this
patch. Deploying code alone does not certify or activate a new weekly state.

## Historical diagnostic API

`models.nfl.contextual.reconstruction.run_qb` is a separate, post-start-only
archived-input diagnostic. It uses the unchanged fitted base/QB feature, head and
Bernoulli simulation primitives. State/review validation uses the actual writer
clock; dynamic source bytes are independently checked against an explicit
prestart information cutoff. It checks raw personnel evidence, preview player
crosswalks, exact schedule/rest/base binding, and target exclusion. It rejects
unsupported context additions and requires exactly 100,000 draws.

Its schema is `nfl.qb_reconstruction.v1`, disposition is
`POST_START_RESEARCH_RECONSTRUCTION`, and prospective eligibility and action
authority are unconditionally false. It does not call the prospective writer or
register a forecast. The ordinary live runner retains `NOT_PREGAME` refusal.
Historical training-seed source acquisition clocks remain an explicit limitation.

## October 8 TB at Dallas acceptance

A separate post-start rebuild from retained prestart sources replayed 64 completed
Week 1-4 games through four verified transitions. Source information cutoff was
2026-10-08T02:30:00Z; kickoff was 2026-10-09T00:15:00Z. Reviews and new execution
occurred October 9 after kickoff. The expected QBs were source-bound Jalon Daniels
(TB; GSIS 00-0041251, ESPN 4596472) and Dak Prescott (DAL; GSIS 00-0033077,
ESPN 2577417), with Baker Mayfield OUT in the retained source. Final inactives and
weather were unavailable. The original pregame attempt produced no forecast.

The unchanged selected model `nfl.integrated_context.qb.v1.research` gave Dallas
0.763300602143854 conditional non-tie probability. First 100,000 draws yielded
0.7613; the code-hardened, separately preserved rerun yielded 0.76197. The code
identity changes the deterministic seed; both samples remain preserved. This is
not prospective evidence, an accuracy claim, or an ATS/total/score simulation.

## Tests

`python -m unittest discover -s tests -p 'test_nfl*.py' -v`

The new reconstruction tests compare exact feature/head results to the unchanged
registered runner on synthetic prestart inputs, check deterministic 100,000-draw
replay, and reject source/clock/rest/base/QB/outcome/context mutations. Real retained
TB/DAL acceptance additionally verifies exact draw bytes and unchanged live refusal.
Current missing test fixtures were recovered unchanged from Git commit
b5ab679c73dae0e698b835c03aa091d2b279dba6, with exact Git blob hashes verified.
