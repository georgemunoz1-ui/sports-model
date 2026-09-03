# Season-launch backfill — 2026-09-03

The CFB and NFL launch artifacts use immutable, versioned source snapshots and canonical ESPN game
identities. Their green state is strictly **schedule-backfill plus shadow-forecast readiness**.
It does not change action authority: all selections remain prohibited and no market prices are used
as model features.

| Sport | Backfill source | Current launch result | Action state |
|---|---|---|---|
| CFB | `sportsdataverse/cfbfastR-data` 2026 schedule snapshot | 8 completed Week 1 games backfilled; 43 future FBS-vs-FBS Week 1 shadow forecasts with canonical IDs | `NO_ACTION` |
| NFL | `nflverse/nfldata` immutable games snapshot | 272 regular-season schedule rows captured; 16 Week 1 shadow forecasts with canonical IDs | `NO_ACTION` |
| WNBA | Existing ESPN-family extension through the final pre-break games | Results/stat extension is complete through 2026-08-29; official availability history remains explicitly unresolved | `NO_ACTION` |

The prior EPA NFL artifact is not relabeled as restored. The new Elo/Platt model is a separately
named, shadow-only launch fallback, with a chronological calibration split and its own validation.
