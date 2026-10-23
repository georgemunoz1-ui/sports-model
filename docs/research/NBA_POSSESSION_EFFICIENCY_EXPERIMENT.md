# NBA possession-efficiency experiment

This independent experiment does not replace the existing NBA baseline, its
fitted packages, or any original forecast. The source baseline remains
`models.current.baseline`, with fitting and causal state construction from
`scripts.prepare_initial_baselines`. A new fit using that exact procedure is
identified as `nba.initial_causal_score.exact_procedure_refit.control.v1`; it is
not described as the original frozen coefficients. Retained original packages
can additionally be evaluated only where their actual information set permits.

## Frozen first experiment

- Model: `nba.possession_efficiency.research.v1`.
- Provider seasons ending 2021–2024 fit the means and winner head. Seasons 2025
  and 2026 are later-period retrospective evaluation. Season 2027 is prospective
  SHADOW only for forecasts actually written before the event.
- No test-period tuning. Box-stat source archives were retrieved now, so the
  historical exercise is a reconstruction, not proven original point-in-time
  evidence. Source revisions remain a limitation.
- Both teams need five eligible earlier games. Missing sources and warmup
  exclusions remain in population coverage rather than becoming neutral inputs.
- Team rates use a fixed old/new weight of 0.9/0.1. As with the preserved baseline,
  previous UTC day games are excluded. The explicit rest value still comes from
  that embargoed history and is not a new operational-rest model.
- Full-game possessions are the average of each team's
  `FGA - ORB + TOV + 0.44 * FTA`. This is a declared box-score estimator, including
  any overtime in the recorded game. It is not provider-counted possessions or
  possessions normalized to 48 minutes.
- Past offense and opponent defense provide points per 100 estimated possessions,
  effective field-goal percentage, turnovers per estimated possession, offensive
  rebound share, and free-throw attempts per field-goal attempt.
- Standardized Ridge heads, alpha 1, fit possession count and shared
  own-offense/opponent-defense efficiency. Home court is a fitted indicator in
  the efficiency head, disabled at neutral sites; no hand-added home points.
- Team point forecasts multiply the two component point estimates. A separate
  standardized logistic winner head, C 1, uses the same historical feature set.
  It is not claimed to arise from a joint score law. A Bernoulli winner simulation
  is numerical integration of this probability, not a possession simulator.

## Separately identified increments

`nba.possession_efficiency.personnel.research.v1` requires source-bound personnel
impact inputs available before every training and prediction cutoff. It adds
explicit home and away impact features to the efficiency and winner heads.
Missing historical availability/impact evidence blocks this increment only.
Player box scores alone do not establish expected pregame minutes or availability.

`nba.possession_efficiency.joint.research.v1` retains the first experiment's mean
heads and adds a two-dimensional residual law. Its covariance is estimated from
2024 predictions made by a fit restricted to 2021–2023, never from the 2025–2026
evaluation outcomes. The final mean fit remains 2021–2024. Residual mean is
reported diagnostically and is not added as a hindsight bias correction.

The joint law is explicitly a **continuous bivariate final-score surrogate**.
It permits negative continuous score tails; simulations record their count. It
does not provide an NBA overtime process, integer score support, or exact push
settlement. Those are further experiments, not silently supplied by rounding or
a coin-flip tie breaker. Mean and covariance receipts plus retained actual draws
make its limitations auditable.

## Source and chronology checks

Normalization matches sport-scoped event IDs, schedule team IDs, opponent IDs,
final scores, season and regular-season eligibility. Cup championship events are
excluded. Shooting makes cannot exceed attempts, and team points must equal
`2*FGM + 3PM + FTM`. Player turnovers plus team turnovers must reconcile to total
turnovers. Each raw source digest is rechecked before reading.

Player point/DNP discrepancies are separately enumerated and never repaired by
guessing. The first experiment does not consume player data. A missing or invalid
team box excludes that challenger row while the valid score-only schedule remains
available to the actual baseline procedure.

Targets do not enter their own feature construction. Duplicate event IDs,
nonmonotone forecast cutoffs, future label availability, targets inside the fit,
changed feature conventions, undeclared features, and modified fitted-state bytes
are refused. Receipts bind the numerical components, input state, code, sources,
configuration, and output. Historical replays cannot become prospective records
by changing their declared cutoff.

## Integration contract

`normalize_sportsdataverse(source_root)` returns `history`, `score_history`,
`future_events`, `excluded`, `player_reconciliation_issues`, and `sources`.
`prepare_examples(history, config)` retains the full input population, with
eligibility, targets, historical event IDs, source bindings and feature values.
Future events use `final=false` and an actual `forecast_cutoff_utc`.
`fit(train_examples, config)` and `predict(state, example, simulations=0)` supply
the research runner. Config `stage` selects an independent identity.

The root runner owns real run IDs, paired evaluation, prospective storage,
component receipts and numerical draw files. Software tests use explicitly
synthetic fixtures and are not empirical sports results. No code completion,
small cohort, or positive comparison grants promotion or action authority.
