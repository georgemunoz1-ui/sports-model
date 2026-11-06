# NBA forecast combination: first research implementation

This opt-in, mean-only challenger preserves the frozen point-margin baseline and
tests whether Dunks & Threes disagreement, followed by three Databallr factors,
can improve it. The first acquired dataset contains three October 29 events and
**zero eligible fitting events**. No real-data combination was fitted, no
incremental improvement is established, and no card/default was changed.

## Procedure and scope

The local frozen specification is
`data/research/nba_forecast_combination_v1/protocol.json`, experiment
`nba.forecast_combination.v1.EXP.001`. A protocol file and candidate-catalog entry
are research bookkeeping, not signed validation or canonical prospective
registration. New settings require a successor identity. This file does not
change `state.json`, the selected defaults or existing model verdicts.

| ID | Definition |
| --- | --- |
| B0 | Exact preserved home-minus-away point-margin forecast |
| B1 | External Dunks & Threes point-margin forecast |
| C1 | B0 + alpha + w * (B1 - B0), with 0 <= w <= 1 |
| C2 | C1 on the same complete-source population + a fitted Databallr increment |

C1 minimizes mean squared residual error plus fixed quadratic penalties on
alpha and w. Both penalties are 1. C2 standardizes three features using only
training events, then ridge-fits C1 residuals with penalty 1. Constant columns
have scale 1 and contribute zero. No imputation or outcome-driven tuning is
performed. The operational fit floor is 100 eligible distinct events; this is
neither a power calculation nor a qualification gate.

Databallr features are home minus away differences in (oTS+dTS), (oTOV+dTOV)
and (ORB+DRB), using the displayed positive-good factors in points per 100
possessions. Their coefficients convert incremental associations to game-margin
points. No predetermined point adjustment or independent-source-confidence
bonus is applied. These are **NBA six-factor team** fields, not the eight-factor
WNBA VPM visualization or its 3D coordinates.

Circadian effects, WNBA coefficients, market inputs, totals and selectors are
outside this experiment. Published score predictions do not identify a joint
score law. Challenger winner/cover/push probabilities and intervals remain null
until a separately evaluated uncertainty model is fitted from chronological
out-of-sample challenger residuals. The baseline SD is not copied.

## Source and dataset contract

Each opportunity retains event ID, league, canonical team orientation, timezone
aware start/cutoff, evidence population, normalized B0/B1/factor source payloads,
raw receipts, model generation, historical record type, as-of and capture times,
forecast identity, artifact paths/hashes, and an independently bound outcome.
The dataset JSON contains a `rows` array; paths are relative to its directory.
Every normalized source is also stored as its own JSON, with its exact-byte
SHA-256 in the row. Raw bytes are separately hashed. Paths outside the dataset
root are refused. Parsing/identity review is required and recorded; hashes do
not prove semantic truth or historical availability.

The pilot fits only `point_in_time_live` populations, sources explicitly backed
by capture-before-cutoff evidence, and one model-version/history stratum. Source
as-of <= capture <= common forecast cutoff < start; final outcome availability
must be after start and strictly before the fit cutoff. Unknown times stay null.
Current source tables are not eligible for earlier games. Reconstructed
backtests remain diagnostic records and cannot silently enter the live-history
fit. Provider model-generation labels are distinguished from unavailable exact
build/checkpoint identifiers.

Duplicate event IDs or duplicate league/home/away/start identities are excluded.
Missing-source events remain in the audit. A rejected challenger may emit a
separately labeled B0 fallback only if B0's own source checks pass. No fallback
is scored as C1/C2. Fit state hashes bind protocol, code, source versions,
training rows and train-only preprocessing; prediction refuses training-event
reuse and a fit cutoff later than the target cutoff. Computations performed
after a historical forecast cutoff are explicitly reconstruction diagnostics.
There is no canonical registration or background collection service here.

## Executed first capture

The preserved October 29 08:40 PDT card contains three NBA events. Its margin
parent is `nba.fixed_parent.8b20d506d255dd14.research`, distinct from the
`nba.initial_causal_score.research.v1` winner head. Only the point-margin parent
is B0. Its previous qualification/input limitations remain attached.

The current Dunks & Threes page was captured on October 30 after these games.
It displays NOP 62%, ATL 52% and POR 68%, compared with 65%, 54% and 72% in the
user's earlier screenshot. Both vintages are preserved separately. The earlier
screenshot's capture clock is unverified; the later page's displayed update
clock lacks a timezone and does not prove original pregame availability.

Current Databallr team factors are retained as another postgame diagnostic
capture. Direct HTML retrieval returned an application shell; factor values
instead trace to the retained web retrieval text. No missing HTML values were
filled by pretending the shell contained them.

All three rows are excluded from fitting. Both C1 and C2 CLI fit attempts
returned `BLOCKED_INSUFFICIENT_ELIGIBLE_EVENTS` with exit code 2. Actual outputs,
raw captures, normalized rows, hashes and the older screenshot transcription
are delivered in the separate comparison evidence bundle. It is not an
untouched validation cohort, a retrospective promotion screen or a betting card.

## Running the explicit research interface

```bash
python3 -m unittest tests.test_nba_forecast_combination -v
python3 scripts/run_nba_forecast_combination.py audit \
  --dataset /path/to/NBA-Comparison-Dataset-20261030.json \
  --protocol data/research/nba_forecast_combination_v1/protocol.json \
  --stage C1 --output /new/path/audit.json
python3 scripts/run_nba_forecast_combination.py fit \
  --dataset /path/to/comparison.json \
  --protocol data/research/nba_forecast_combination_v1/protocol.json \
  --stage C1 --train-before <timezone-aware-cutoff> --output /new/path/fit.json
```

`predict` additionally requires `--state` and the matching `--stage`/protocol.
All CLI outputs use exclusive creation; existing evidence cannot be overwritten.
Normalized-source construction is explicit ingestion work; this runner does
not scrape a private API, infer unavailable snapshots or autonomously collect
future events.

## Verification and remaining gates

30 synthetic engineering tests pass: known blend recovery, both weight bounds,
regularization, training-only scaling, zero-variance factors, sign/orientation,
missing sources, live/backtest and version separation, timestamps, identity and
raw/payload/outcome hashes, duplicates, future labels, state/protocol tampering,
market independence and immutable blocked CLI output. Synthetic fixtures are
not empirical forecasting evidence.

Session-start full-checkout health was RED: 9 failures, 7 warnings. The log is
retained with the evidence. Failures include frozen lineage/equivalence, missing
test-runtime dependencies, unavailable production pitcher archive, overdue
recovery/release and standing-health obligations. No repository health
certification follows from these focused tests.

Next evidence: genuine paired pre-cutoff source snapshots and baseline receipt
lineage, then chronological OOS mean forecasts on matched populations, paired
error uncertainty with date blocks, missing-source/fallback reporting, and a
separate challenger uncertainty fit. A frozen future confirmation cohort and
writer-owned archival/registration are separate subsequent steps. Wagering OFF;
allocation ZERO; research publication qualification remains INELIGIBLE.

Sources: [Dunks & Threes methodology](https://dunksandthrees.com/about/epm),
[game predictions](https://dunksandthrees.com/games), and
[Databallr NBA team factors](https://databallr.com/teams), retrieved October 30,
2026. Dunks & Threes distinguishes the current 2026–27 generation, earlier live
models and reconstructed backtests; these are not interchangeable live records.

## Subsequent pregame-capture increment

The first implementation record above is preserved. The later October 30
[pregame source-capture report](NBA_PREGAME_CAPTURE_20261030.md) documents the
opt-in collector, raw-extraction replay gates, two genuine captures of the same
10 upcoming events, 71 focused tests and remaining source-access/timestamp
limitations. It does not revise the original zero-eligible October 29 finding.
