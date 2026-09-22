# NFL weekly state repair

This is a new repair from main `4b39c651c88eefc66dfa6f6aaac3183dc5b48839`.
No implementation from PR38 or ensemble implementation from PR39 is inherited.
PR38/37 archives are read as pinned input evidence only; archived code is never executed.
The selected QB model, coefficients, EWMA, QB filters, offseason retention,
market firewall and action authority are unchanged.

## Safety contract

- Filter PBP by schedule game IDs before team league means or QB aggregation.
- Pin a full 272-game season schedule with 32 teams, 17 games/team, canonical IDs,
  18 weeks and no duplicate team/week. Bind each update against that independent
  seed schedule. Do not infer completeness from the supplied subset or PBP IDs.
- Release only after all games in the anchored week reconcile, including final
  scores, terminal game boundary and completed starter IDs. Overtime may end
  with time remaining only with an explicit END GAME marker.
- Advance exactly one week. Maintain consumed IDs, model/transform hashes,
  parent identity, source bytes/receipts, before ancestry and after state.
  QB offseason retention occurs once at seed creation, never once per week.
- Lock writers; compare the requested parent with HEAD. Identical retries return
  the original ID. Changed retries, skipped/repeated weeks and corrections to
  consumed finals require explicit investigation/rebuild; no overwrite occurs.
- Write/fsync content-addressed immutable objects before atomically replacing
  HEAD. An interrupted write may leave an orphan; the reader refuses it unless
  it is in the published chain. Rejection preserves HEAD and existing objects.
- Replay every transition from retained raw bytes on read. Week3+ runtime and
  canonical CLI require the previous week's state and recompute the nine
  consumed team features. Both team and QB state hashes appear in the trace.
- The legacy assimilation command is now audit-only and cannot publish an
  untracked TeamState dictionary. Frozen Week2 evidence remains readable.

The schedule structural contract is deliberately for the present 32-team,
17-game regular season. Postponements that change the anchor, canceled games,
season rollovers and corrected consumed results stop for a reviewed rebuild.
A source URL/hash proves retained byte identity, not independent authenticity or
historical publication. Review the seed provenance and retain its ID outside
forecast packets. `NFL_WEEKLY_STATE_SEED_SHA256` is the operator trust pin.
No new source-observed timestamp is invented; eligibility is retrieval-bound.

## Commands

Use a separately reviewed `historical_state.json` reconstructed by the frozen
historical team transform, not neutral invented team priors. Receipts must bind
raw `games.csv` and `play_by_play_2026.csv` bytes to their exact nflverse URLs
and actual retrieval times. The pinned PR37 seed is suitable for a retrospective
repair replay; it is not new prospective evidence.

```bash
python scripts/advance_nfl_weekly_state.py \
  --store /absolute/path/research-state \
  --seed /absolute/path/historical_state.json \
  --schedule /absolute/path/games.csv \
  --schedule-receipt /absolute/path/games.receipt.json

python scripts/advance_nfl_weekly_state.py \
  --store /absolute/path/research-state --seed-id SEED_ID \
  --parent-id SEED_ID --week 1 \
  --schedule /absolute/path/games.csv \
  --schedule-receipt /absolute/path/games.receipt.json \
  --pbp /absolute/path/play_by_play_2026.csv \
  --pbp-receipt /absolute/path/pbp.receipt.json
```

Advance Week2 using the returned Week1 ID as parent and fresh complete sources.
Week3+ follows the same interface, without a Week1-only scope exception. Updates
and forecasts are separate operations. For a source-bound future event package:

```bash
export NFL_WEEKLY_STATE_SEED_SHA256=SEED_ID
export NFL_CONTEXT_PACKAGE=/absolute/path/acquired-event-package.json
python scripts/run_nfl_integrated.py --date 2026-09-27 \
  --weekly-state-store /absolute/path/research-state \
  --weekly-state-id COMPLETED_WEEK2_ID \
  --output /absolute/path/new-forecast-directory
```

The CLI binds only the state-derived base fields; current schedule/event identity,
QB availability, weather and other event context still need their normal source
capture and gates. An absent date package remains an acquisition dependency.
No default event package or state pointer is changed by this repair.

## Acceptance evidence and limits

See `docs/releases/2026-09-22-weekly-state/` for exact local test logs and code hashes.
The synthetic suite exercises Week1→2→3→4, bye teams, concurrent retries,
interrupted publication, stale parents, corrected finals, duplicate/missing PBP,
late sources, unknown seed/model, altered state and stale base feature refusal.
It runs the actual canonical adapter with 100,000 draws and checks identical
replay; it also runs `run_nfl_integrated.py` as a subprocess. These fabricated
observations are TEST_ONLY, not a real Week3 forecast.

Pinned real-source replay verifies 51 frozen and 10 capture manifest entries.
With 17 games of PBP, the Week1 update exactly reproduces both frozen team state
and frozen QB state, including floating-point aggregation conventions. Repeating
it is a no-op. A truncated schedule and repeated week are rejected. Full Week2
has only one final in this captured vintage, so no Week3 state is created.

Fresh acquisition of the 2026 PBP release through the available GitHub fetch
connector returned 404; this is an acquisition failure, not proof of no games.
Real current Week3 acceptance therefore remains BLOCKED until a fresh complete
Week2 schedule/PBP capture is reconciled and a fresh Week3 event package consumes
that state. Global health remains RED. No predictive improvement, official
release, prospective eligibility, or ensemble promotion is claimed.

The CI workflow repeats the same synthetic and pinned real-source checks. It
fails on test errors and uploads logs even on failure. Source artifacts expire
in December 2026; preserve the downloaded original archives for long-term replay.

## Subsequent real-source acceptance

The source-acquisition limitation above records the original PR42 acceptance.
The September 22 operational follow-up acquired complete Week 2 PBP, isolated a
starter conflict, and rebuilt a separately pinned chain with source-bound
adjudication. See `docs/NFL_REAL_WEEK3_ACCEPTANCE.md` and its retained evidence.
