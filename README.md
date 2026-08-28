# Sports Model Research System

Governed, pregame sports forecasting research for MLB, WNBA, NFL, and college football.

> **Current operating posture — August 28, 2026**  
> **Paper research only · execution unauthorized · 0 bets · 0.00u · $0**  
> Forecast probabilities and market prices are kept in separate layers. A model opinion is not a wager.

## Repository status

| Item | Current state |
|---|---|
| Operational branch | [`sportsmodel/main`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main) |
| Operational history | 417 commits at the time of this status update |
| Current audited head | `8e24d17` — result-binding fixture provenance disclosed and fail-closed |
| GitHub default branch | `main` — legacy one-commit landing branch, not the operational model branch |
| Repository visibility | **Private** |
| License | **No license currently present** |
| Open-source status | **Not open source today**; see [Open-source and reproducibility status](#open-source-and-reproducibility-status) |
| Decision readiness | `SYSTEM_NOT_DECISION_READY` / `ACTION_BLOCKED` |
| Wager authority | `NO` |
| Actual wagering ledger | **0 bets · 0.00u · $0** |

The default `main` branch contains the original placeholder repository. All governed model code,
cards, audit records, tests, and research history live on `sportsmodel/main`. This README is intended
to be mirrored on both branches until the repository default branch is deliberately changed.

## Model status at a glance

| Sport | Implementation | Current output status | Validation / evidence status | Action status |
|---|---|---|---|---|
| **MLB** | Champion V13, widened and adaptive challengers, expanding home prior, total outputs, anchored replacement workflow | **Forecast generation active** | Models remain research-grade. Winner-arm ordering has been unstable; the champion has underperformed the prior across multiple recent comparisons. The widened challenger has prospective evidence worth accumulating, not promotion authority. | `SYSTEM_NOT_DECISION_READY`; no model-authorized bets |
| **WNBA** | Current four-factors feature-refresh arm, standings Log5 fallback, expanding home prior | **Forecast generation active when the daily archive rebuild binds** | Winner arm has useful early diagnostic results, but the fallback has beaten it on some probability comparisons. Margin compression persists and totals remain unvalidated. | Personnel/market gates still apply; no model-authorized bets |
| **NFL** | `sportsim` NFL drive model exists in PR #1; historical NFL records and benchmarks also exist | **No current admitted forecast path** | The prior statement “no NFL model has ever been built” is withdrawn. The implementation exists but is unmerged, not restored into the governed registry, and not validated as current for the competition phase. | `SYSTEM_FAILURE_NFL_MODEL_NOT_REGISTERED`; benchmark display only |
| **CFB** | High-level CFB v2 challenger preregistered in draft PR #2 | **No forecasts yet** | Lifecycle is `PREREGISTERED_DATA_ACQUISITION_PENDING`. Historical acquisition, feature materialization, OOF training, calibration, and prospective validation remain pending. | Forecast- and wager-blocked |

## MLB

### Registered forecast family

The daily MLB board keeps separately identified outputs rather than blending them:

- `mlb.winner.CHAMPION_V13` — deployed frozen champion;
- `mlb.winner.CHALLENGER_WIDENED` — wider probability challenger;
- `mlb.winner.CHALLENGER_ADAPTIVE` — adaptive challenger;
- `mlb.winner.EXPANDING_HOME_PRIOR` — constant expanding home-win baseline;
- champion and expanding-prior total outputs — reported for evaluation, never decision-bearing;
- `mlb.replacement.CONFIRMED_LINEUP` — separately anchored replacements when starter or lineup
  information changes materially after the original freeze.

The original frozen board is never rewritten. A replacement may change the probability, selected
side, attached price, EV, and disposition only as one coherent transaction. If a replacement crosses
50%, the side-reselection gate refuses retention of the abandoned side.

### Current evidence

- **August 25:** active path 6–9, Brier 0.2568 versus expanding prior 0.2491. The nine
  explicitly priced candidates finished 6–3, but that is a one-slate screening hypothesis—not a
  validated betting edge.
- **August 26:** widened challenger 12–3, Brier 0.2332; expanding prior 8–7, Brier 0.2491.
  Across August 25–26, widened reached 18–12 / 0.2436 versus the prior's 0.2491. This is registered
  prospective evidence worth accumulating; it does not satisfy the promotion horizon.
- **August 27 corrected close-out:** active replacement path 2–5, champion 4–3, adaptive 5–2,
  widened 3–4, prior 4–3. The initial 5–1 headline was invalid because five August 26 results were
  joined to the repeated August 27 series.

### Data and readiness

- MLB provenance recovery bound 1,948 of 1,957 historical rows in the latest reconciliation;
  remaining refusals are named rather than silently filled.
- The date-blocked OOF uncertainty replay has run, but per-game conservative-EV consumption and
  execution authority are not approved merely because the statistic can be computed.
- Prices are inputs to the **market overlay**, never predictive model features.
- Negative raw EV may produce an economic pass. Positive raw EV remains only a candidate until all
  uncertainty, freshness, personnel, and execution gates pass.

## WNBA

### Current model family

- `wnba.replacement.FEATURE_REFRESH` — frozen four-factors machinery rerun on the current daily
  feature pool;
- `wnba.fallback.STANDINGS_LOG5_v1` — standings-based fallback, graded separately;
- `wnba.winner.EXPANDING_HOME_PRIOR` — baseline prior, graded separately.

The daily feature rebuild consumes the committed ESPN/wehoop archive through the previous day's
completed games, checks that target games are absent, checks zero game-ID overlap on the append, and
then freezes forecasts. If the archive is late, the system records staleness and retries; it does not
silently call an old feature state current.

### Current evidence

- The August 26 current-feature arm went 2–0 descriptively and correctly resolved the Seattle/Toronto
  disagreement against the standings fallback.
- On August 27, the refresh arm again selected both winners, but the standings fallback produced the
  better Brier score: approximately 0.1323 versus 0.2027 for the refresh arm.
- Winner-direction evidence is still small. It does not establish promotion or betting authority.
- Margin forecasts continue to compress large outcomes.
- Totals remain **unvalidated**. The August 27 total MAE was approximately 22.2 points, and the
  recent current-feature total projections have shown a material over-projection pattern.
- Official injury/personnel acquisition remains a separate gate. Archived game payloads may identify
  prior availability but do not authorize a claim that a player is currently in or out.

## NFL

The correct status is not “no model has ever existed.”

[`PR #1 — Add sportsim`](https://github.com/georgemunoz1-ui/sports-model/pull/1) contains an NFL
drive-by-drive simulation engine plus NBA, MLB, and NHL engines. The NFL implementation models drive
outcomes so key margins such as 3 and 7 emerge from the score distribution. The PR also includes
ratings, season simulation, market tools, walk-forward evaluation, CLI tooling, synthetic data, and
168 tests.

However, that code is:

- open in a separate branch and not merged into `sportsmodel/main`;
- not admitted as the current governed NFL model identity;
- not fitted and validated on a retained current-season feature state inside the operational system;
- not authorized to emit live model probabilities or selections.

Therefore the present operational status is:

```text
MODEL_IMPLEMENTATION_EXISTS_UNMERGED
CURRENT_REGISTERED_FORECAST_PATH_UNAVAILABLE
NO_CURRENT_FORECAST
NO_SELECTION
WAGER_AUTHORITY = NO
```

NFL preseason market rows are benchmark/context records only. They do not become model forecasts,
and no EV can be computed from a market price without an admitted independent model probability.

## College football

[`Draft PR #2 — CFB v2 challenger`](https://github.com/georgemunoz1-ui/sports-model/pull/2) is a
preregistration, not a completed model release.

Registered design:

- primary cohort: FBS vs FBS;
- FBS vs FCS fit, calibration, reporting, and promotion kept separate;
- 36 frozen predictive columns, including explicit missingness indicators;
- market-free causal EPA/form, opponent adjustment, returning production, quarterback/talent,
  transfer/coaching, travel, and rest features;
- walk-forward season-week evaluation with nested calibration;
- block-bootstrap inference and a 1,000-game / 60-block promotion horizon;
- totals disabled until independently validated;
- market, result, chronology, provenance, identity, lifecycle, and stake firewalls.

Current lifecycle:

```text
PREREGISTERED_DATA_ACQUISITION_PENDING
FORECAST_PERMISSION = NO
ACTION_PERMISSION = NO
STAKE = 0
```

The historical CFB v1 is identified but is absent from the operational branch pending a clean,
isolated port. If v2 inputs are unavailable and v1 is absent or unhealthy, the required output is
`SYSTEM_FAILURE_CFB_BASELINE_UNAVAILABLE`—not an invented forecast.

## P0 result-integrity incident

The August 27 end-of-night grading initially joined five prior-day MLB finals to the next day's
repeated series. This contaminated result record `caf9a897` and commit `a287dbb`, producing an invalid
5–1 active-path headline and invalid Brier, totals, P&L, and narrative claims.

The contaminated artifacts remain append-only but accrue nothing. Commit `9a55809` superseded the
grading and introduced a fail-closed result-binding gate. A result can grade a forecast only when all
of the following match:

```text
sport + canonical game ID + scheduled date + away team + home team
```

The gate refuses prior-date series joins, date mismatch, unmatched or ambiguous IDs, team reversal,
pre-start finals, partial-cohort aggregation, and evidence-score disagreement. Latest commit
`8e24d17` also discloses two inferred fixture IDs as `SYNTHETIC_UNVERIFIED`; fixture metadata is never
allowed to masquerade as captured canonical evidence.

No arm record, Brier/log loss, MAE/RMSE/bias, counterfactual P&L, promotion count, estimator input, or
results thesis may publish from a refused cohort.

## Decision architecture

```text
frozen model outputs
        ↓
replacement workflow for material pregame information changes
        ↓
separate same-book market overlay
        ↓
raw EV screen
        ↓
uncertainty, freshness, personnel, and action-authority gates
        ↓
BET / PASS / BLOCKED / SYSTEM_FAILURE
```

Standing rules:

1. Prices never enter predictive model features.
2. Opening, current, and closing prices are separate observations.
3. A reconstructed price is not a captured market artifact.
4. Positive raw EV is not authorization.
5. Totals are displayed and graded separately but are not decision-bearing unless independently
   validated.
6. Result display and canonical evidence admission are separate: an available score may be shown
   without being allowed to settle or promote a model.
7. Missing data produces an explicit refusal or system failure, never a guessed value.
8. Every real-money field remains `NO` / `0` / `$0` until the complete registered action path passes.

## Open-source and reproducibility status

### What is open or publicly inspectable upstream

The system uses public repositories and open-source tooling where their licenses and retained
artifacts permit it. Current examples include:

- [`sportsdataverse/wehoop-wnba-raw`](https://github.com/sportsdataverse/wehoop-wnba-raw) for
  committed ESPN-derived WNBA schedules and box-score payloads;
- [`lancebroz/mlb-pitcher-data`](https://github.com/lancebroz/mlb-pitcher-data) for committed,
  StatsAPI-derived MLB pitch data and game identifiers;
- nflverse schedule/data artifacts for regular-season NFL research;
- SportsDataverse CFB repositories proposed in the CFB v2 source plan;
- open-source Python scientific-computing libraries used by the model and test harnesses.

Every admitted external artifact is expected to retain repository, commit, path, byte count,
SHA-256, and retrieval time. Observing a repository `HEAD` is discovery—not a reproducible pin.

### What is reproducible for authorized repository users

- frozen board probabilities and model identities;
- source and artifact hashes;
- append-only forecast and grading records;
- replacement and side-reselection logic;
- result-binding and evidence-tier controls;
- mutation tests and the full healthcheck;
- paper-ledger accounting with zero automatic wager authority.

Run the active branch:

```bash
git clone --branch sportsmodel/main https://github.com/georgemunoz1-ui/sports-model.git
cd sports-model
python3 harness/healthcheck.py
```

Because the repository is private, cloning requires access to the GitHub account or repository.

### Why this repository is not open source yet

Public upstream data does not automatically make downstream private code open source. This
repository currently lacks a license, and some records depend on owner-relayed market observations,
private screenshots, or sources whose redistribution terms must be reviewed.

Before changing repository visibility, the minimum release checklist is:

1. choose and add an explicit software license;
2. perform a secret, credential, personal-data, and private-link audit;
3. separate redistributable code from non-redistributable raw data and screenshots;
4. document every upstream license and attribution requirement;
5. add a reproducible dependency lock/bootstrap path;
6. make the healthcheck pass on a clean anonymous clone using only documented inputs;
7. replace owner-relay dependencies with public fixtures or clearly optional private overlays;
8. publish a data-availability statement explaining what can and cannot be redistributed;
9. protect the operational branch and require the core healthcheck before merge;
10. change visibility only after the release artifact reproduces without private state.

Until those steps are complete, the accurate label is:

```text
PRIVATE GOVERNED RESEARCH REPOSITORY
OPEN-SOURCE UPSTREAMS USED WHERE PERMITTED
MODEL CODE NOT YET OPEN-SOURCE LICENSED
```

## Repository map

| Path | Purpose |
|---|---|
| [`cards/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/cards) | Frozen pregame boards and rendered cards |
| [`data/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/data) | Bound inputs, evidence, registries, overlays, and audit records |
| [`engine/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/engine) | Forecast and simulation implementations |
| [`harness/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/harness) | Gates, builders, mutation tests, graders, and healthcheck |
| [`reports/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/reports) | Analysis and evaluation outputs |
| [`docs/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/docs) | Standards, experiments, incident records, and append-only progress journal |
| [`sports/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/sports) | Sport-specific integrations |

## Reading a board

Every reader-facing card should answer, in order:

1. What did the model predict?
2. How strong was the signal?
3. What market price was actually retained?
4. Was the row a candidate, pass, block, or system failure?
5. What happened, and how did the model compare with its baselines?
6. What evidence grade supports the result?

Technical hashes, route exhaustion, mutation counts, and incident details remain available in the
audit appendix; they should not hide model output or results from the first screen.

---

This project produces research forecasts, not financial advice or guaranteed outcomes. Model status
is intentionally conservative: an implementation may exist while current forecast permission,
promotion authority, or wagering authority remains disabled.
