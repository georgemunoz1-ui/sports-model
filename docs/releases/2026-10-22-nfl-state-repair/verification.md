# NFL current-state date binding repair — 2026-10-22

Research-only repair based on main `90daf8e0036c67a5304aa0747bf50b2266e0b364`.
No selected-model parameter, old state object, historical forecast, release gate,
canonical health card, or wagering authority is changed. No merge is implied.

## Cause and narrow correction

Current main already distinguishes a nominal first-snap starter from the active
passer. Source-bound adjudications preserve Case Keenum's Week 4 opening handoff
and identify Tyson Bagent as Chicago's active passer. Separate reviewed final
summary/PBP bindings resolve stale Seattle schedule entries to Sam Darnold.

With all seven reviewed adjudications supplied, unchanged main replays Weeks 1–5
but refuses Week 6 with `ADJUDICATION_DATE_BINDING`: SEA@DEN has kickoff
`2026-10-16T00:15:00Z`, matching nflverse `gameday=2026-10-15`, `gametime=20:15`
in America/New_York. Comparing the UTC calendar date to that local gameday is wrong.

The correction converts the source kickoff to America/New_York before checking
gameday. When gametime is supplied, it additionally requires exact kickoff-instant
agreement. Wrong date, wrong time, source identity, hash, final scores, passer
identity, chronology, and explicit alias-review checks continue to fail closed.

## Executed checks

- Existing starter-adjudication tests plus four timezone regressions: **15 passed**.
- Existing weekly-state regression tests: **15 passed**.
- Fresh source-bound chain: **six transitions replayed; 93 games consumed**.
- Real current packet: selected `nfl.integrated_context.qb.v1.research` executed
  for `2026_07_NE_CHI`; current state features and predictions replay exactly.
- Winner and separate explicitly selected QB-margin draws: 100,000 each,
  exact replay. Simulation count is not predictive validation.
- Partial-runtime healthcheck is not a full-repository health clearance.

Reproduce focused code tests from a complete checkout:

```sh
PYTHONPATH=.:tests python -m unittest test_nfl_starter_adjudication test_nfl_adjudication_timezone -v
PYTHONPATH=.:tests python -m unittest test_nfl_weekly_state -v
```

The complete raw-capture/state/draw/replay evidence is delivered separately as
`Sports-Model-NHL-NFL-Repair-2026-10-22-Evidence.zip`; its numerical-use proof is
`repair-20261022/nfl-source-state-feature-effect-proof.json`.

## Immutable identities

- Original starter module SHA256: `b78a8d5a68692341bf2a685069e1e8ff6f8873f21d472722151959514c2a04fa`
- Repaired starter module SHA256: `612100d1343e639547eeff1f1cf9a223b582757bc6aeeec23d178330063856b8`
- New seed: `6f406f70585cdea9780ff26e5ef48b05d7b53decdb70145b95b225cd73a9ee86`
- New Week 6 tip: `45abd0ea3971d79a84d4051679ad3aad973897257893f46b11014d4c6c513418`
- QB state SHA256: `bf1ecdbc5b45e9bba05df3361326625b7cb550653381f8e14604cc66eb331c71`
- Schedule SHA256: `bffcce70f89c952a6d4f2ff4656d4b3896ea47f2f7abfe95b9fe8f3ac60da95a`
- PBP SHA256: `1e1c16cb6463704c6c7c8dae476c320b25a81c32b287a744c383003501cb9933`

No official-gamebook clearance is claimed. Personnel/inactives and weather are
separate from the selected QB features; final event-specific confirmation is
still required for any stronger status. The optional QB-margin adapter/fit comes
from unmerged draft PR #69, explicitly selected and hash-verified; the legacy
combined-arm spread calibration is not substituted. Its prediction screen is HOLD.

Action OFF; dose 0.0; official_release_eligible:false.
