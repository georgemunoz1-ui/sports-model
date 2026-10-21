# PR 71 roster and disclosure reconciliation — October 21, 2026

This is branch integration and retained-source review, not a model change or
release approval. PR 71 remains draft. Wagering/action authority remains OFF.

## Reproduced merge

The inspected roster head was `e145d0b7cf90a3eb2553639a3d76bd49d13ab471`,
the common base was `7cf2aea0581b4048802c920c9670823fab21679e`, and current main
was `90daf8e0036c67a5304aa0747bf50b2266e0b364` (merged disclosure PR 72).
The comparison used GitHub blob-verified copies and `git merge-file --diff3`.

| File | Actual three-way outcome | Reconciliation |
| --- | --- | --- |
| `scripts/run_nfl_integrated.py` | Conflict at argument parsing | Keep roster options/loading and disclosure option/pregame single-event restriction; attach coverage before persistence and generate the disclosure from the enriched result. |
| `scripts/generate_card_force.py` | Textually clean | Keep both options, pre-simulation roster gate, coverage normalization and immutable disclosure sidecars. Test their combined behavior. |
| `docs/progress.md` | Conflict between independent appended entries | Preserve main's entire journal prefix, then append the roster entry and this integration entry without altering either historical record's text. |
| `state.json`, `sports/registry.py` | Clean | Preserve PR 71 metadata. All pre-existing main state values compare equal. |

The updated PR branch includes main as an additional parent. No main ref is
updated and PR 73 is not included. No fitted parameter, default-selection policy,
runtime configuration, model implementation, forecast, grade or ledger is changed.
The roster parser, raw-byte rebuilder, chronology checks and conflict rules are
unchanged from PR 71. The disclosure implementation is unchanged from main.

## Combined behavior and tests

Both APIs still distinguish missing membership (`ACQUIRE_REQUIRED`), invalid or
conflicting membership (`BLOCKED`), and usable membership without fitted effects
(`AVAILABLE_NOT_USED`). Ordinary diagnostic parent forecasts can carry a blocked
roster report; that does not qualify them as roster-aware. `--require-roster-aware`
refuses before simulation. Neither a disclosure packet nor an IN/OUT scenario
clears that gate or assigns availability weights.

The synthetic integration matrix exercises valid, conflicting and post-cutoff
sources plus wrong-parent and invented-weight disclosures across all seven
shared-card leagues and the separate NFL CLI. It checks selected NFL default and
capability trace, unchanged numerical fields/identity, both report hashes,
immutable sidecars, exit status, and no simulation/persistence on required-roster
refusal. NFL single-event/pregame restrictions remain covered.

Two existing fixtures were reconciled: the roster CLI's mock writer now supplies
the registration receipt consumed by the disclosure path, and the disclosure CLI
test compares all original parent fields while requiring the additive roster
report. These changes do not relax either production validator.

Executed focused command:

```sh
python3 -m pytest -q tests/test_rosters.py tests/test_roster_disclosure_integration.py \
  tests/test_card_disclosures.py tests/test_model_defaults.py \
  tests/test_cross_sport_distributions.py tests/test_current_runtime_contracts.py \
  tests/test_nfl_personnel_resolution.py tests/test_current_sports_data.py
```

Result: **224 tests and 56 subtests passed**. All four roster/shared/NFL CLI help
entry points passed. The focused CI workflow now runs both contracts, the combined
matrix, default-selection checks and distribution regressions without an artifact
upload dependency.

An additional local suite ran NFL context, week-two policy, weekly-state, spread,
MLB-current, default and distribution checks: 112 passed, 56 subtests passed and
three MLB tests could not load absent historical package files. An earlier broad
collection also lacked the locally restored `sportsim` package. Those are local
restoration limitations, not passing tests. Clean-checkout CI on the published
head is required; its results are recorded on PR 71. Local health remains RED
and is not a repository-wide health certification.

## Retained evidence investigation

Archive: `All-Sports-Roster-Evidence-2026-10-20.tar.xz`.
SHA-256: `7c53c458fcc841576cb5400deb0bdf0f7e19e3311fc7e4112726959f770d4d2b`.
Bundle identity: `4b140e98aa7116ea078973d3f72f8c5a90adc4b20f81427f5f81b86820570c58`.
The October 20 acceptance report and its test evidence remain unchanged.

Rechecked all 630 manifest files and rebuilt the normalized bundle from all
314 census/roster receipts. The result reproduces 307 parsed teams and 22,034
distinct sport-scoped IDs, including 138 CFB teams and 15,804 CFB players. The
retained requests use `limit=1000`. The prior 2,004-player recovery claim is
consistent with 15,804 minus 138 times 100; the original capped all-team capture
is not in this archive, so a fresh before/after acquisition was not performed.

`espn:nfl:4361437` is the same Emany Johnson ID, name, position and practice-squad
status in both retained responses:

| Team | Provider timestamp (UTC) | Retrieval (UTC) | Raw SHA-256 |
| --- | --- | --- | --- |
| Los Angeles Chargers (`espn:nfl:24`) | Oct 20 21:31:04 | Oct 20 22:18:04.483541 | `6f252579073593e0b7348bb13a854eeb88e82d9c5d730f2be831a992928f15cd` |
| Cincinnati Bengals (`espn:nfl:4`) | Oct 20 22:04:29 | Oct 20 22:18:04.743438 | `26d88d5cbd816ae80a80ab749aa4050cbadbf670be418fb819489c902aea8c16` |

The [Bengals transaction page](https://www.bengals.com/team/transactions/), viewed
October 21, lists the October 20 practice-squad signing. The
[Chargers 2026 transaction page](https://www.chargers.com/team/transactions/2026),
viewed October 21, lists Johnson among August 30 waivers. These official records
support Cincinnati membership and suggest the retained Chargers entry is stale.
That is an investigative inference, not an implemented provider reconciliation.
The web retrieval is not an original October 20 source receipt, does not establish
game-active status or a precise transaction effective time, and is not consumed
by inference. No raw row, snapshot, conflict ledger or forecast was overwritten.

Per-team TEST_ONLY event shells at the original review cutoff reproduced 305
available inventories and exactly two blocked inventories, CIN/LAC. All 307
inventories refuse at the actual October 21 review cutoff (staleness or the
membership conflict). These probes are roster contract tests, not forecasts or
validation of any real event schedule. Full details and receipts are in
`docs/releases/2026-10-21-roster-reconciliation/retained-source-review.json`.

To reproduce integrity and normalization, extract the hash-verified archive and run:

```python
from sports.rosters import load_bundle, league_counts
bundle = load_bundle('PATH/all-sports-20261020-v2/bundle.json')
print({sport: league_counts(league) for sport, league in bundle['sports'].items()})
print(bundle['sports']['nfl']['membership_conflicts'])
```

Future clearance requires a newly retained source package and an auditable,
event/cutoff-bound resolution under the source policy. Do not drop the Chargers
row, pick the newest timestamp, or treat an unweighted disclosure as resolution.
Full-roster numerical transforms remain unfitted for the selected parents.

## Independent status boundaries

- Software: focused local checks passed; updated-head remote CI is separately
  reported on PR 71. Historical CI on the old head does not certify this head.
- Storage: artifact-upload quota failures are independent of successful test,
  replay or history-verification steps; no quota workaround or cleanup is made.
- Sources: retained bytes and normalization verified; current live roster
  completeness/correctness is not certified. CIN/LAC ambiguity remains blocked.
- Prediction/release: no new predictive evaluation or promotion; full repository
  health remains uncertified, research-only status and action authority OFF.
