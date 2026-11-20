# CFB personnel v2 input controls — October 30, 2026

The optional `personnel_v2` experiment now has an executable input contract.
It does not modify the selected CFB arm, existing efficiency/joint stages, or
the original personnel-v1 procedure. Its identity is
`cfb.fbs.matchup_efficiency.personnel.v2.research`, with v1 recorded as parent.

## Actual integration

`models/experiments/cfb_efficiency.py:prepare_examples` transports a game's
`personnel_evidence` through the existing research preparation path. The normal
efficiency/control feature vectors are unchanged. `fit_personnel_v2` and
`predict` invoke `models/experiments/cfb_personnel.py:values`; the coefficients
are fitted using the existing earlier-training procedure, never hand-adjusted.

`scripts/run_efficiency_experiments.py --league cfb --stages personnel_v2`
selects the new stage. The default stage list is unchanged. The actual shared
runner's component receipts retain the evidence, consumed six-feature vector,
source hashes, coverage receipt, model identity, transform identity and code
hash. Shared-card integration can select a separately supplied fitted v2 state
through its existing efficiency sidecar configuration; no such state is
activated by this change.

## Input schema and boundaries

Each normalized game can contain `personnel_evidence` with schema
`cfb.personnel-input.v2`, its exact `event_id`, and `home`/`away` objects:

- Exact provider `team_id` and quarterback `player_id`.
- QB `status` is `CONFIRMED` or `PROJECTED`; unknown is refused.
- Explicit `expected_participation_probability`, `participation_method`,
  `workload_limitations`, and `prior_pass_attempt_share` evidence.
- `returning_snaps.offense` and `.defense`, each containing integer
  `numerator`, positive integer `denominator`, and `population_definition`.
- Sources with `source`, `path`, SHA-256, exact event/team identity,
  `observed_at_utc`, `retrieved_at_utc`, `available_at_utc`, and `field_bindings`.
  Each binding maps a required field to an RFC 6901 JSON pointer in the retained
  structured source bytes. Required fields are `event_id`, `team_id`,
  `quarterback.player_id`, `quarterback.status`,
  `quarterback.prior_pass_attempt_share`, `returning_snaps.offense`, and
  `returning_snaps.defense`. Source values must equal the declared values under
  canonical JSON serialization; matching the source file's hash alone is insufficient.
- A separate `participation_assumption` path/SHA-256 reference. Its retained
  `cfb.qb-participation-assumption.v1` record binds exact event/team/player,
  probability, method, workload assumptions, supporting source hashes and
  creation time. It must be created after source retrieval and before cutoff.

This stage validates exact field values against source bytes and timing but
does not authenticate the provider or certify the selected source-field meaning.
The explicit scenario assumption is retained as an assumption, not represented
as a provider observation. The stage does not convert
a status label into a numerical probability. The only feature arithmetic is
the explicitly supplied participation probability and two returning-snap
ratios per team. Prior pass-attempt share is required evidence, not an
additional fitted feature. Missing/invalid inputs remain errors, never zeros.

Source retrieval and availability must precede the forecast cutoff. No
retrospective original-time claim is inferred from later retrieval; an archive
with independent as-of evidence needs a separately specified acceptance policy.
The inherited cutoff is the CFB weekly feature freeze (earliest kickoff in that
season/week). A later-in-week personnel capture is refused even before its own
event; per-event personnel refresh requires a separately declared cutoff and
receipt policy, not retiming the weekly feature evidence.

The schedule census checks both team rows of every eligible completed FBS/FBS
game in the declared efficiency-history window, including missing nonlatest
rows. Its verdict is **complete within supplied schedule**, not external
schedule completeness. FCS history is listed separately; neither FCS coverage
nor a sufficient row count establishes FBS/FCS predictive comparability.
Metric season/week must match the schedule before a row counts as present.
Fresh future-event evidence is merged by an allowlisted, identity-checked
overlay; source and history evidence conflicts are refused rather than chosen.

## Executed validation and remaining blockers

Focused tests exercise real preparation, fit, prediction, and component-receipt
functions with synthetic evidence. They cover unknown QB status, nonfinite and
boolean probabilities, source identity/bytes/timing, incomplete field binding,
one-sided historical omissions, schedule-season conflicts, FCS separation,
source/assumption value mutation with unchanged bytes, actual future-event
evidence transport, incompatible fitting flags, legacy replay and CLI dispatch.
The fixture is 48 artificial games; it is not a predictive sample.

An independent execution of the original source from the parent commit and the
new source found exact equality of all 48 prepared examples and the efficiency
and personnel-v1 fitted states and final forecasts. State hashes:

- Efficiency: `9b00331d191bef109707b8c5a173420619de0db309537e77982d8af1c4835480`.
- Personnel v1: `fd941ee3603d6188da5883c4991da9b73b013c7e6ff6dd76936ac89eabf836c2`.

| Blocker / owner | Implemented closure evidence | Remaining dependency |
|---|---|---|
| CFB personnel transport and use / CFB research | `test_cfb_personnel_v2.py` exercises preparation → fitted v2 → prediction → actual runner receipt | Authentic current and historical QB/participation/minutes-equivalent snap evidence has not been acquired |
| One-sided or nonlatest FBS history omissions / CFB data | Negative fixture retains legacy eligibility while v2 refuses missing team row | Independent provider-schedule census and reconciliation of real affected events |
| FBS/FCS population scope / CFB evaluation | Explicit scope and unsupported-matchup reporting | Relevant cross-population model evaluation; no expansion of selected scope |
| Personnel predictive evidence / research evaluation | Versioned v2 identity, v1 retained; no promotion | Eligible chronological personnel corpus, registered matched baseline/challenger experiment, prospective shadow and untouched confirmation |

The retained `data/research/distribution_replay_20261007/cfb` cohort supports
replaying that existing margin-distribution study. It contains no substitute
for the personnel-v2 training evidence. The October slate is not a fitting or
confirmation population for these controls.

Implementation: exercised with synthetic inputs. Authentic production-runner
personnel replay: NOT_RUN. Predictive validation: NOT_ASSESSED. Provider
authenticity: NOT_ESTABLISHED. Selection and wagering authority unchanged/OFF.
