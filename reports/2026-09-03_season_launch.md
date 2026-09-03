# Season-launch backfill — 2026-09-03

This artifact establishes a deliberately narrow **green** state for CFB and NFL: current,
immutable schedule backfill plus a reproducible, point-in-time paper-forecast path. It never
authorizes a recommendation, price comparison, or wager.

| Sport | Backfill evidence | Shadow-forecast result | Action state |
|---|---|---|---|
| CFB | 888 2026 schedule rows; 8 completed Week 1 rows retained and 43 future FBS-vs-FBS Week 1 events canonically bound | 43/43 paper forecasts. Causal Elo state ends 2025, applies one 2026 regression, and consumes no 2026 results. Historical 2011–2025 FBS/FBS validation: n=10818, Brier=0.1841871687099094. | `NO_ACTION` |
| NFL | 7,239 retained regular-season rows; 272 2026 schedule rows and 16 Week 1 events canonically bound | 16/16 paper forecasts. Elo/Platt calibration is 2002–2018 and validation is 2019–2025 (n=1871, Brier=0.22842, log loss=0.649141). | `NO_ACTION` |
| WNBA | Existing ESPN-family extension: 95 result/stat games through 2026-08-29, missing=[] | Historical results/stat backfill is complete through the final pre-break game; 6 official availability units remain unresolved. | `NO_ACTION` |

The old NFL EPA artifact remains an open recovery task (RJ-006); this update registers a separate
fallback shadow model rather than claiming that lineage was restored. CFB v2 personnel/continuity
inputs, NFL QB/OL/injury inputs, market mapping, and all execution authority remain out of scope.

The global multi-sport release is still not green: this scoped launch status does not override
unresolved WNBA or MLB release gates.
