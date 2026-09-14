# Current-date sports refresh

The current slate defaults to the actual clock in America/Los_Angeles. It does
not inherit an old board date. All seven league entries have independent season,
phase, schedule coverage and feature readiness. NFL September 14, 2026 is Week 1,
as confirmed by the NFL schedule. League weeks are explicit source metadata,
never ISO calendar weeks. A later slate outside the acquired calendar window
requires fresh acquisition; yesterday's calendar cannot silently become today's.

## Command

```
python scripts/refresh_all_sports.py --bundle /path/to/acquired-bundle --output /new/unique/output
```

Optional `--date YYYY-MM-DD`, `--timezone America/Los_Angeles`, and `--as-of`
are explicit. A past slate requires `--historical`; this labels reconstruction,
not a forecast issued in the past. For exact replay, supply the original aware
as-of timestamp and the preserved acquisition bundle. The input bundle includes
`acquisition.json` and every source file it names. Acquire sources through the
approved environment tools; the refresh command performs no network requests.

## What changed

- Timezone-aware local-day windows, including DST; UTC kickoff dates do not
  move Monday Night Football into a Tuesday local slate.
- Source receipts distinguish capture time, source availability, event time,
  materialized-file hash and representation. Web excerpts are labeled excerpts.
- Explicit unknown/partial coverage; empty or blocked source responses cannot
  prove a league has no games. A scheduled break does not mean model inputs are current.
- Strict score orientation, future-final checks, and doubleheader preservation.
- Current-snapshot pointer and hash verification; snapshot freshness expires
  after six hours or a local-date change. Calendar coverage receipts expire too.
- Immutable outputs, explicit replay manifests, MLB reconciliation candidates,
  and a separate WNBA regular-season extension with exhibition rows quarantined.
- The legacy health check now labels integrity checks and current-data readiness
  separately. Its exit code still covers its existing integrity tests; the new
  readiness result must be inspected before claiming current forecast readiness.

## September 14 acquisition result

The run at 2026-09-14T16:04:55.381103Z records the September 14 Pacific slate.

| League | Acquired update | Remaining work |
|---|---|---|
| MLB | 469 final observations Aug10–Sep13; 94 scheduled games Sep14–20, including 10 Sep14 | Exact provider-ID binding, starter/pitcher logs, personnel, feature recomputation |
| NFL | 15 Week1 finals and 17 future games, including DEN@KC Sep14 | Current PBP/EPA backfill and final inactive/workload updates |
| WNBA | Four Aug30 full box scores; updated extension 98 regular-season games after Jul22; one All-Star record quarantined | Updated-model refit and current personnel before Sep17 restart |
| CFB | Partial FBS Week2 scoreboard capture with 40 complete team-quarter observations | Complete schedule/results/PBP capture; later scoreboard requests hit bot verification |
| MLS | Three Sep13 finals and 14 upcoming matches from schedule table | Source timezone, provider-ID binding, complete recent history and model inputs |
| NBA | Official 2026–27 calendar acquired; offseason, no Sep14 first-team games | Roster and model inputs for preseason |
| NHL | Team preseason calendar and a no-games feed response acquired | League-wide/preseason/prospect coverage remains unverified |

MLB comparison to operational results through Aug23: 296 previously absent
observations (281 after Aug23 and 15 earlier), 165 matching existing scores,
six prior blank-score rows, and two ambiguous doubleheader rows. No conflicting
nonblank single-game scores were found. These are acquisition/reconciliation
records, not permission to grade a different event ID. Canonical results and
historical forecast outputs are not overwritten.

The WNBA new games are MIN81–ATL89, LAS90–SEA74, GSV86–PDX69, CON71–DAL97.
The old extension included COOP/SPO All-Star teams. The new extension removes
that row from regular-season inputs but keeps it in `quarantined`. Historical
model files are unchanged; the revised extension is not a refitted model.

## Reproduction and limits

Fourteen focused contract tests passed. Re-running the acquired bundle with
the identical cutoff reproduced all six manifest hashes. New WNBA field-goal,
three-point and free-throw counts reproduce each team's final points.

This refresh does **not** establish repository-wide health or make every model
current. The canonical full checkout was unavailable locally. The older recovery
health check can pass while its MLB data end Aug9; operational main results end
Aug23. Neither copy's file modification times establish feed freshness.

Raw acquisitions and the prior snapshots are retained in the separately saved
refresh evidence package. The runtime pointer identifies the exact versioned
status file. A current-data snapshot is not a replacement for the NFL integrated
model, its market/live arms, or its calibration artifact. Existing experiments,
frozen forecasts and action authority remain unchanged.
