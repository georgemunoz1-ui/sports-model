# All-sports operational research recovery

Registered before acquisition or fitting of new NBA/NHL/MLS baselines. The owner
explicitly requests all models operational with full autonomy. This is research
engineering, not wagering authority or a change to historical verdicts.

Existing selected MLB, WNBA and CFB algorithms remain frozen. Recover their data,
fit/runtime artifacts and adapters; retain source grades and chronological cutoffs.
No failed NFL ensemble is selected. New NBA/NHL/MLS baselines get distinct research
identities, not a false recovered-model label.

Population: ESPN completed regular-season games, 2021 onward. NBA/NHL winner
includes overtime; MLS is regulation 1X2. Exclude canceled/nonfinal/preseason and
postseason games. Preserve raw responses, actual retrieval times and complete
provider IDs. Retrospective source revisions do not prove historical availability.

Fixed split: train 2021–2024, validation 2025, untouched 2026 later-period audit.
No hyperparameter search or holdout-selected architecture. Binary models use
regularized logistic regression C=1 on causal team scoring/form/rest features;
margin/total Ridge alpha=1 are independent diagnostics, not a joint score model.
MLS uses two regularized Poisson score heads alpha=1 and an independent count
joint distribution with explicit limitations. Baseline is training-only empirical
home-win rate (NBA/NHL) or training-only home/draw/away rates (MLS).

State updates occur after a conservative one-day embargo, with same-day games
sharing the same pre-day state. Exponentially weighted scoring form alpha=0.1,
shrinkage 10 observed games toward training league scoring, rest capped at 14 days;
new teams use the declared training prior and explicit cold-start indicators.
Scalers/imputers fit on training only. Report scalar binary Brier or category-sum
1X2 Brier, log loss, reliability counts, season coverage and paired UTC-week block
bootstrap intervals (1000 draws, seed 7). Record margin/total MAE separately.

No claim of superiority unless the paired later-period interval excludes zero
and reliability/coverage checks pass. Prospective validation remains a separate
requirement for promotion. Engineering operation requires source completeness,
finite bound outputs, genuine retained simulation draws, deterministic replay,
cutoff/duplicate/final-only guards, and actual adapter consumption. A model that
fails a predictive screen may remain an explicit research candidate; it cannot
silently become the accuracy-preferred default.


Acquisition amendment before any score/model inspection: ESPN historical date-range
requests returned HTTP 400 for all 207 requested league-months. Use retained
SportsDataverse schedule mirrors for NBA/NHL and football-data.co.uk USA results
for MLS, with current ESPN event identity reconciliation. Raw MLS source may carry
market columns: the parser admits only date, teams, final goals and result; no
market field may enter features, training or model selection. Keep the same fixed
split, parameters, evaluation and no-promotion rules.

Acquisition resolution before fitting: ESPN team-season endpoints successfully
returned all 555 directory/schedule requests for NBA/NHL/MLS, 2021–2026. Use that
original ESPN population with exact provider-ID overlap reconciliation. Discard
the stale NBA/NHL master mirrors and the alternate MLS CSV from this experiment.
The parameters and split above remain fixed. Current research availability is an
explicit opt-in; it does not change the accuracy-preferred default registry.

Population correction after the first audit: ESPN labels three NBA Cup championship
games regular season but separately tags competition type 39. Exclude that type
consistently in training, validation, later audit and current schedules to honor
the preregistered regular-season population. This removes one game in each of
2024–2026; it is a source-classification correction, not a tuned exclusion. Keep
the first NBA evaluation in the release evidence under preliminary/. No parameter,
feature, split or promotion rule changes; the corrected audit is a restatement,
not a newly untouched holdout.
