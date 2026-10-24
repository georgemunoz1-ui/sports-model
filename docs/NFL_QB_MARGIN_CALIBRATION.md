# QB integer-margin calibration, research grading and market display

The new registered research model is `nfl.qb_margin.integer_blend.v1.research`.
It adds a separately identified calibrated margin distribution to the unchanged
selected QB winner model. The previous margin model, combined quarantine, frozen
forecasts, canonical grading and weekly assimilation are preserved. Market prices
remain excluded from predictive inputs; the comparison panel is always displayed.
Action authority remains OFF.

## Improvement screen and full-data fit

Preregistration commit `dbe169b45eb7a99583d66cc566c8f608a43a0f29` precedes the fit.
The exact design is `data/nfl/qb_margin_calibration_v1/design.json`. One scalar
weight blends the unchanged residual-margin distribution with an integer-margin
component. The latter preserves actual NFL winning magnitudes, including 3 and 7,
conditioned on the QB Ridge prediction with a fixed four-point bandwidth. The
unchanged QB logistic head and prior-only tie estimate determine winner/tie mass.
No market data, additional model arm or 2026 outcome enters this fit.

For each outer year 2022–2025, the scalar is fitted only from earlier inner-year
predictions/outcomes. Each inner distribution also uses strictly earlier history.
The exact bounded quadratic CRPS minimum uses no arbitrary iteration cap. Final
alpha is **0.5289571149**, using all **1,615** eligible 2020–2025 calibration games.
The final distribution uses all **1,871** QB OOF games from 2019–2025. No rows are
removed because of an unfavorable outcome. All current simulations use **100,000**
actual draws per scenario, with retained PCG64 seeds and raw-array hashes.

All seven preregistered checks passed on 1,087 paired 2022–2025 games (7,609 fixed
contract probes):

| Metric | Previous QB margin | Calibrated successor |
|---|---:|---:|
| Mean margin CRPS | 7.124773 | 7.112266 |
| Three-way cover/push/loss Brier | 0.435680 | 0.433998 |
| Clipped contract log loss | 0.697699 | 0.690247 |
| Mean push mass at +/-3 (observed 7.406%) | 2.905% | 4.738% |
| Mean push mass at +/-7 (observed 4.002%) | 2.546% | 3.324% |

The paired CRPS difference is -0.012507, with season-bootstrap 95% interval
[-0.019593, -0.004182]. Rounded-normal CRPS is 7.125179. The 90% margin interval
covers 92.09%; zero-mass observed contracts are zero. Key-number underprediction
is reduced, not eliminated. This reused retrospective history is not an untouched
holdout. Four outer seasons provide limited uncertainty resolution. No automatic
production promotion, predictive-validation clearance or market-superiority claim
follows from PASS. Cohort metrics, reliability bins, effective sample sizes and
fold alpha values remain in the retained evaluation.

## Execute the integrated process

Use the existing source-bound acquisition path and a date-covered event package.
Do not reuse September 14 for an uncovered date. The current event uses the sealed
Week 2 state (32 games); Week 3 Sunday results cannot advance the Monday parent.
The September 28 reruns occurred before the six-hour schedule-source budget expired.
Keenum/Bagent remain separate conditions until a starter is verified.

```bash
NFL_CONTEXT_PACKAGE=/absolute/path/to/event_package.json \
NFL_WEEKLY_STATE_SEED_SHA256=85a125580dbe1be76cac0d0edbb889d9ec22040ae078263c49460721484718d6 \
python scripts/run_nfl_integrated.py \
  --date 2026-09-28 --event-id 2026_03_PHI_CHI --simulations 100000 \
  --weekly-state-store /absolute/path/to/state \
  --weekly-state-id e962a66b806e2371f7890ec6bc91c57726282ea2b2467a05761c603f00d406cf \
  --qb-margin-calibrated --home-spread 3.5 \
  --comparison-market-packet /absolute/path/to/market_snapshot.json \
  --output NEW_UNIQUE_DIRECTORY
```

`--qb-margin` retains its original model identity. `--qb-margin-calibrated` selects
this successor. The ordinary winner-model default is unchanged. Both explicit QB
margin paths now register in the separate research ledger. Use
`--research-grading-store` only to select another durable research store.
Existing forecast folders reject overwrites. No final grading or state update
is needed to run a pregame forecast.

Every research-pregame command writes `board.json` and `board.md`. Missing quotes
produce a visible unavailable panel. Supplied snapshots with no capture time show
`SNAPSHOT_TIME_UNKNOWN`. Prices load after forecast, simulations and registration
are frozen. Model win, simulated win, model cover, simulated cover, line, odds,
break-even and proportional no-vig benchmarks are separate fields. The display
packet never passes to predictive `run()`. `--market-packet` remains a different,
explicit predictive-mode argument with its existing safeguards.

Current screenshot extraction is source-hashed. The book name is not visible;
no brand or capture time is invented. Novig chart probabilities and buy prices
are retained separately. Ticket percentages are not described as money wagered.
Totals, team totals and first-half probabilities are unsupported by this margin
model even when a market quote exists.

## Enabled grading state

`data/grading/nfl_qb_margin/HEAD` points to an append-only chain of immutable
hash-addressed records. Two current scenario registrations exist; both are
pending. Actual-clock registration occurs before kickoff. Forecast bytes, source
and draw hashes, simulation counts, QB conditions and selected contracts are bound
in each record. This is research grading, not a retroactive canonical registration.

```bash
python scripts/grade_nfl_qb_margin.py
python scripts/grade_nfl_qb_margin.py --event-id 2026_03_PHI_CHI \
  --schedule /path/to/captured-games.csv --schedule-receipt /path/to/schedule-receipt.json \
  --official-final /path/to/captured-espn-summary.json --official-receipt /path/to/official-receipt.json
```

Receipts contain `source_url`, `retrieved_at_utc` and SHA-256 of exact raw bytes.
The schedule URL is the existing nflverse games.csv authority. The official
summary URL is `https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=EVENT_ID`.
Do not synthesize a final packet: acquire and retain both raw final feeds. ESPN
must explicitly be completed/post and match teams, kickoff and both final scores.
The schedule must agree and identify both QBs. Sources must be captured after
start and no later than the actual grading clock. The CLI requires supplied,
verified captures; it does not imply an unattended source-fetching service.

A matching QB scenario enters the matched research cohort. Other scenarios are
retained as counterfactual grades excluded from that cohort. Model versions and
scenarios never double-count in primary winner grading. Exact retries are
idempotent; tampering, nonfinals and conflicts fail without changing state. A batch
publishes only after all records are durable under one lock. Corrections require
an explicit separately reviewed append-only correction process; conflicting final
results are never silently overwritten. Grading never advances weekly state.

## Verification and retained evidence

`verify_nfl_qb_margin_calibration.py` independently reconstructs integer atoms,
replays all 1,615 calibration objectives/fold optima, and replays the current saved
arrays with independent inverse-CDF sampling. It verifies source/model/draw hashes,
registration chronology, exact cover settlement and Monte Carlo agreement.
The targeted tests cover optimizer boundaries, future-fold/duplicate rejection,
integer push and side-swap symmetry, missing/unknown market quotes, display
invariance, matched/counterfactual grading, duplicate retries, conflicting finals
and tampered state. Original tracked bytes outside the disclosed workflow, CLI,
source-packaging and append-only documentation/state changes remain identical.
Global recovery health and prospective promotion gates remain unchanged.
