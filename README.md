# Sports Model Research System

Governed, pregame sports forecasting research for MLB, WNBA, NFL, and college football.

> **Current operating posture — August 30, 2026**
> **Paper research only · execution unauthorized · 0 bets · 0.00u · $0**
> Forecast probabilities and market prices are kept in separate layers. A model opinion is not a wager.

## Repository status

| Item | Current state |
|---|---|
| Operational branch | [`sportsmodel/main`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main) |
| Current audited head | `01a0fafb` — FU-1 feed adapter + market capture/evaluation layer merged (PR #7) |
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

## Recent updates — August 29–30, 2026

| Change | Record |
|---|---|
| **PR #4 merged** (`34babc4`) | P0 freshness fixes: `POST_HOC_NOT_PREGAME` guard, exact-name identity matching, stale-starter CAP routing, forecastable-vs-actionable separation with `REGISTERED_FALLBACK_ONLY` fail-closed. Owner's full 5-point merge gate passed, including WNBA reproduction (not environmental skips). |
| **PR #5 merged** (`ceefb72`) | Monte Carlo convergence gate ported: `MC_CONVERGENCE_TOL_PP = 2.7386pp` (worst-case p=0.5, 3×√(0.25/3000)×100) against frozen TRIALS=30000 / BLOCKS=10 / CONVERGENCE_SIGMAS=3.0. |
| **PR #6 merged** (`9613559`) | `CARD_UPDATE_PROTOCOL` — the end-of-night all-sports graded sweep standard (byte-identical port). |
| **Postgame audit** (`5772da2`) | `POSTGAME-AUDIT-2026-08-30`: Tier-1 bound inferential grading (4 WNBA games) vs Tier-2 descriptive-only; five structural corrections — σ provenance pinned (CFB Week-1 18.385 n=758; WNBA margin SD 13.97 coherence-only; the "12.53 vs covers" claim withdrawn), single-defect hypothesis REJECTED, CFB ids "unbindable under current schema" (not forever), 8/29 posture two-layer reconciliation (RESULT_DISPLAY vs CANONICAL_EVIDENCE_ADMISSION). FU-1 identified as highest-leverage follow-up. |
| **PR #7 merged** (`01a0fafb`) | **FU-1 feed adapter + market layer.** Programmatic schedule/starter/results feeds (ESPN scoreboard, MLB StatsAPI — no keys), result binding (2026-08-28 MLB cohort **15/15**: RESULT_BINDING_PASS, DATE_COHERENCE_PASS, CANONICAL_ID_MATCH), probable-vs-confirmed starter gating (boxscore `gamesStarted` only — probables are always IDENTIFIED_UNCONFIRMED), multi-source market capture (SportsGameOdds, The Odds API, MoneyLine; scraped sources stay IDENTIFIED_UNCONFIRMED), historical odds/line-movement capture, causal backtest harness (walk-forward, purge/embargo, temporal firewall on closing lines), dormant calibration layer (Platt→beta→isotonic; refuses fits under n=500), and the P0 data-quality battery (canonical event identity, quote age/staleness, versioned snapshots, dq_gate). pytest 26/26; market layer firewalled from forecast paths (`assert_no_market_imports` tested). P1/P2 items deferred to issue #8. |
| **8/29 card graded** | Final all-sports sweep per CARD_UPDATE_PROTOCOL: CFB 2–2, WNBA 0–1, MLB 2–3; leans 2–1. Grading descriptive only; ledger $0. |
| **8/30 pregame board V1→V3** | Registered model-first board: 1 lean (ATL +2.5, C-tier, usable edge +6.9pp after data-quality × uncertainty factors), WNBA decision-state records with no-vig market separation, scenario engine (GSV@POR raw +11.0pp edge rejected on confirmed post-cutoff roster news), movement classification (CON@DAL steam = new_information 0.85; unexplained steam never faded), MLB slate-wide actionable block (0/14 SP_CONFIRMED + pitcher corpus cutoff 7/19), NFL NO_FORECAST, CFB early board separated. V2/V3 are append-only deltas; V1 untouched. |
| **WNBA shadow model reproduced** | `wnba.rs.ff7_logit_ridge.v1_0.shadow` mirrored and reproduced on the verified parity mirror: walk-forward 2,287 games, Brier 0.2112 vs base 0.2472, AUC 0.722. Feature cutoff 2026-08-27 declared DATA_STALE on the 8/30 board. |

Follow-up queue: issue #8 (FU-1 P1/P2 — market features as-of decision_time, movement classification, additional scrapers, MC wiring), SIM-1 simulation-methodology spec (docs-only, in draft), FU-2 CFB id migration, FU-3 board_shape wiring, FU-4 preregistered CFB margin evaluation, FU-5 per-game WNBA residual retention, FU-6 owner decision on 47 pseudo-pk MLB games (recommended: accept-descriptive).

## Model status at a glance

| Sport | Implementation | Current output status | Validation / evidence status | Action status |
|---|---|---|---|---|
| **MLB** | Champion V13, widened and adaptive challengers, expanding home prior, total outputs, anchored replacement workflow | **Forecast generation active**; actionable layer requires SP_CONFIRMED under post-PR-#4 freshness rules (probables never confirm) | Models remain research-grade. Winner-arm ordering has been unstable; the champion has underperformed the prior across multiple recent comparisons. The widened challenger has prospective evidence worth accumulating, not promotion authority. | `SYSTEM_NOT_DECISION_READY`; no model-authorized bets |
| **WNBA** | Current four-factors feature-refresh arm, standings Log5 fallback, expanding home prior; `wnba.rs.ff7_logit_ridge.v1_0.shadow` reproduced (walk-forward Brier 0.2112 / AUC 0.722) | **Forecast generation active when the daily archive rebuild binds** | Winner arm has useful early diagnostic results, but the fallback has beaten it on some probability comparisons. Margin compression persists and totals remain unvalidated. | Personnel/market gates still apply; no model-authorized bets |
| **NFL** | `sportsim` NFL drive model exists in PR #1; historical NFL records and benchmarks also exist | **No current admitted forecast path** | The prior statement "no NFL model has ever been built" is withdrawn. The implementation exists but is unmerged, not restored into the governed registry, and not validated as current for the competition phase. | `SYSTEM_FAILURE_NFL_MODEL_NOT_REGISTERED`; benchmark display only |
| **CFB** | High-level CFB v2 challenger preregistered in draft PR #2 | **No forecasts yet** (early board rows are EARLY_FORECAST context, never final) | Lifecycle is `PREREGISTERED_DATA_ACQUISITION_PENDING`. Historical acquisition, feature materialization, OOF training, calibration, and prospective validation remain pending. Week-1 σ = 18.385 (n=758). | Forecast- and wager-blocked |

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

### Freshness and starter gating (PR #4)

A probable pitcher listing is never a confirmation. Under the merged P0 rules a starter slot is
CONFIRMED only from an in-game boxscore line; anything else routes to the registered CAP, and the
actionable layer fails closed (`REGISTERED_FALLBACK_ONLY`) when no legitimate actionable forecast
exists. The FU-1 feed layer (PR #7) now automates this distinction: StatsAPI `probablePitcher`
hydrates are IDENTIFIED_UNCONFIRMED by construction; confirmation comes from boxscore
`gamesStarted ≥ 1` once the game is underway.

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
- **August 28–29:** graded per CARD_UPDATE_PROTOCOL; Tier-1/Tier-2 separation per the 8/30 postgame
  audit (descriptive-only where binding evidence tiers are not met).

### Data and readiness

- MLB provenance recovery bound 1,948 of 1,957 historical rows in the latest reconciliation;
  remaining refusals are named rather than silently filled.
- The FU-1 feed layer binds programmatic finals with real game ids (ESPN_GAMEID / MLB_GAMEPK);
  the 2026-08-28 cohort binds 15/15 through the result-binding gate. 47 pseudo-pk games from
  8/24–27 remain unrecoverable without re-capture (FU-6 owner decision pending).
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
- `wnba.winner.EXPANDING_HOME_PRIOR` — baseline prior, graded separately;
- `wnba.rs.ff7_logit_ridge.v1_0.shadow` — reproduced shadow arm: walk-forward 2,287 games,
  Brier 0.2112 vs base 0.2472, AUC 0.722; margin SD 13.97 is frozen and coherence-only.

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
- The calibration layer (PR #7) ships DORMANT: it refuses any fit under 500 bound events; the
  current Tier-1 bound base is n=4, so p_calibrated = p_raw on all current cards.

## NFL

The correct status is not "no model has ever existed."

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

## Feed and market layers (FU-1, PR #7)

The system no longer depends on manual schedule/result/starter capture:

- **Feeds:** ESPN scoreboard and MLB StatsAPI clients (no API keys) with ET-date derivation from
  the UTC instant (never a UTC slice), cross-feed reconciliation that surfaces CONFLICTs (missing
  game, score disagreement, start-time disagreement) with both claims retained, and cached
  fixtures as the reproducible offline path.
- **Result binding:** programmatic finals flow through the same fail-closed result-binding gate
  (sport + canonical game ID + scheduled date + away + home).
- **Market capture:** multi-source structured odds (SportsGameOdds primary, The Odds API
  secondary, MoneyLine historical movement), entry/closing separation, versioned snapshots with
  schema_version + ingestion_run_id, quote-age/staleness/missingness quality fields. Browser-only
  sources (Covers, VegasInsider, OddsTrader) are registered as IDENTIFIED_UNCONFIRMED /
  trend-validation-only. Circa is a labelled sharp-reference book, never in consensus.
- **Firewall:** the market layer is valuation/audit only — separate `market_*` namespace with a
  tested import firewall against forecast paths; a pregame forecast path can never read a closing
  line or a post-cutoff snapshot (fail-loud, refusal recorded).
- **Evaluation:** causal backtest harness (walk-forward folds with purge/embargo, event-level
  splits, news trichotomy where publication_time governs) and a dormant calibration layer.

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
pre-start finals, partial-cohort aggregation, and evidence-score disagreement. Commit `8e24d17`
discloses two inferred fixture IDs as `SYNTHETIC_UNVERIFIED`; fixture metadata is never allowed to
masquerade as captured canonical evidence. PR #7 extends the same gate to feed-produced result rows
(2026-08-28 MLB cohort: 15/15 binding proof).

No arm record, Brier/log loss, MAE/RMSE/bias, counterfactual P&L, promotion count, estimator input, or
results thesis may publish from a refused cohort.

## Decision architecture

```text
frozen model outputs
        ↓
replacement workflow for material pregame information changes
        ↓
separate same-book market overlay (no-vig separation; entry vs closing tracked for CLV)
        ↓
raw EV screen
        ↓
uncertainty, data-quality, freshness, personnel, and action-authority gates
        ↓
PLAY / LEAN / WAIT / PASS / BLOCKED / SYSTEM_FAILURE
```

Standing rules:

1. Prices never enter predictive model features.
2. Opening, current, and closing prices are separate observations.
3. A reconstructed price is not a captured market artifact.
4. Positive raw EV is not authorization; usable edge = raw edge × data-quality × uncertainty factors.
5. Totals are displayed and graded separately but are not decision-bearing unless independently
   validated.
6. Result display and canonical evidence admission are separate: an available score may be shown
   without being allowed to settle or promote a model.
7. Missing data produces an explicit refusal or system failure, never a guessed value.
8. Unexplained line movement is classified `unknown` and never faded; `new_information` moves are
   accepted, not fought.
9. Every real-money field remains `NO` / `0` / `$0` until the complete registered action path passes.

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
- first-party public endpoints (ESPN scoreboard API, MLB StatsAPI) consumed by the FU-1 feed layer;
- open-source Python scientific-computing libraries used by the model and test harnesses.

Every admitted external artifact is expected to retain repository, commit, path, byte count,
SHA-256, and retrieval time. Observing a repository `HEAD` is discovery—not a reproducible pin.

### What is reproducible for authorized repository users

- frozen board probabilities and model identities;
- source and artifact hashes;
- append-only forecast and grading records;
- replacement and side-reselection logic;
- result-binding and evidence-tier controls;
- feed fixtures and the offline reproducible binding path (FU-1);
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
| [`data/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/data) | Bound inputs, evidence, registries, overlays, feed fixtures, and audit records |
| [`engine/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/engine) | Forecast and simulation implementations |
| [`harness/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/harness) | Gates, builders, feed/market layers, mutation tests, graders, and healthcheck |
| [`reports/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/reports) | Analysis and evaluation outputs |
| [`docs/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/docs) | Standards, experiments, incident records, specs, and append-only progress journal |
| [`sports/`](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main/sports) | Sport-specific integrations |

## Reading a board

Every reader-facing card should answer, in order:

1. What did the model predict?
2. How strong was the signal (raw edge, and usable edge after data-quality × uncertainty factors)?
3. What market price was actually retained (entry, captured ≤ decision_time; closing recorded later for CLV)?
4. Was the row a play, lean, wait, pass, block, or system failure?
5. What happened, and how did the model compare with its baselines?
6. What evidence grade supports the result?

Technical hashes, route exhaustion, mutation counts, and incident details remain available in the
audit appendix; they should not hide model output or results from the first screen.

---

This project produces research forecasts, not financial advice or guaranteed outcomes. Model status
is intentionally conservative: an implementation may exist while current forecast permission,
promotion authority, or wagering authority remains disabled.
