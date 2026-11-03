# Cross-Sport Volatility Matrix Research

**Status:** opt-in research software; no predictive qualification, selected-model change, or wagering authority.

**Scope:** NFL, CFB, NBA, WNBA, MLB, NHL and MLS; paired home/away score errors, derived margins and totals, frozen-outcome residual diagnostics, and exact contract settlement only inside existing product boundaries.

## 1. Decision

The repository now has a separate `sports.volatility_matrix.research.v1` fit artifact and `sports.joint_score_distribution.research.v1` predictive artifact. The implementation does not edit `discrete_research.py`, calibration code, current models, selected defaults, historical forecasts, or prior distribution identities. That separation matters because existing fitted artifacts pin their source-code hashes.

This is an implementation of a challenger, not evidence that it beats a baseline. The repository's earlier retrospective result—that conditional residual scaling did not improve CRPS in the seven evaluated products—remains unchanged. NBA joint-score challenger regressions also remain negative evidence, not something this new layer can erase.

## 2. What the matrix represents

For game \(g\), let home-minus-away orientation be fixed before fitting:

\[
M_g=H_g-A_g,\qquad T_g=H_g+A_g.
\]

The inputs are paired errors from forecasts that were actually produced before each game using only then-available information:

\[
e_{H,g}=H_g-\hat H_g,\qquad e_{A,g}=A_g-\hat A_g.
\]

The fitted artifact retains two different objects:

1. **Bias:** \(\bar e_H,\bar e_A\), the mean signed errors.
2. **Dispersion:** the centered covariance matrix

\[
\Sigma=\begin{bmatrix}
\operatorname{Var}(e_H)&\operatorname{Cov}(e_H,e_A)\\
\operatorname{Cov}(e_H,e_A)&\operatorname{Var}(e_A)
\end{bmatrix}.
\]

The derived quantities are not independently fitted:

\[
\sigma_M^2=\sigma_H^2+\sigma_A^2-2\operatorname{Cov}(e_H,e_A),
\]
\[
\sigma_T^2=\sigma_H^2+\sigma_A^2+2\operatorname{Cov}(e_H,e_A).
\]

Consequently, positive shared score error increases total variance and reduces margin variance relative to independence. Also,

\[
\operatorname{Cov}(M,T)=\operatorname{Var}(e_H)-\operatorname{Var}(e_A).
\]

A margin/total covariance parameter therefore cannot be chosen independently of the two team-score variances. This is why separate margin and total standard deviations plus an arbitrary correlation are not a sufficient joint-score model.

### Worked illustrative example only

For the uploaded example \(\Sigma=[[100,30],[30,81]]\), home SD is 10, away SD is 9, correlation is \(30/(10\times9)=1/3\), margin SD is \(\sqrt{121}=11\), and total SD is \(\sqrt{241}\approx15.524\). These are algebra results, not fitted league constants.

### Bias is not volatility

Centering removes the mean before covariance estimation. A model can be biased and have a narrow distribution, unbiased and too wide, or calibrated on average and wrong within segments. The initial implementation deliberately retains the parent point mean and reports bias separately; it does not silently turn mean error into a point-forecast correction. Legal-support conditioning, such as removing final ties, can change the final discrete mean, so predicted support moments are reported separately from the analytic matrix.

## 3. Five kinds of uncertainty must not be collapsed

| Component | Meaning | Treatment |
|---|---|---|
| Aleatoric outcome variance | Randomness remaining with fixed inputs and model | Paired residual distribution and its covariance |
| Parameter/model-fit uncertainty | Limited or unstable estimation of the forecasting model | Requires separate bootstrap/Bayesian or candidate-model evaluation; not identified by residual covariance alone |
| Input/availability uncertainty | Unknown lineup, goalie, pitcher, weather or other pregame state | Existing source-bound scenario mixtures; no invented player values |
| Model-form uncertainty | Wrong functional family or omitted structure | Compare registered challengers out of time; do not hide it by widening SD |
| Monte Carlo numerical error | Error from using finite draws to evaluate a fixed distribution | Report MC standard error separately from predictive SD |

For an estimated probability \(\hat p\) from \(n\) independent simulation draws, the binomial Monte Carlo standard error is \(\sqrt{\hat p(1-\hat p)/n}\). The retained metadata also reports the conservative bound \(100\sqrt{0.25/n}\) in percentage points. Neither value measures game-outcome uncertainty. More draws improve numerical precision, not forecast quality.

## 4. Estimation choices

### Empirical paired residual challenger

The initial `empirical` method retains centered paired errors and maps them around the frozen parent home/away means. Fractional centers are divided between adjacent integer score cells using all four home/away combinations. This preserves each cell's pre-conditioning home and away means while retaining the residual pairing. Illegal negative scores and disallowed ties are removed explicitly, with removed mass and the conditioning policy recorded.

This is a discrete empirical joint law, not a bivariate normal approximation. The fitted matrix is sample covariance with denominator `n-1`; the equally weighted empirical prediction pool has population second moments with denominator `n`, and the artifact reports that scale explicitly. Bilinear allocation then preserves pre-conditioning means and home/away covariance but adds rounding variance to each score marginal; margin and total variance each receive the sum of those two rounding increments. The artifact therefore labels the analytic matrix as excluding discretization/legal conditioning and treats emitted-support moments as authoritative for the actual discrete distribution. This distinction is material in low-score sports. It can preserve key-number, low-score and tail behavior only to the extent those patterns exist in eligible training residuals. Thirty rows is only a software floor, not a validation threshold or a claim of stable covariance estimation.

### Ledoit–Wolf challenger

The `ledoit_wolf` method shrinks the covariance toward a spherical target and applies a symmetric linear transform so the retained empirical residuals have the shrunk sample covariance. The shrinkage intensity, target and estimator convention are stored. The implementation was checked numerically against the reference `sklearn.covariance.ledoit_wolf` calculation on synthetic matrices; that is a correctness check, not sports evidence.

Shrinkage can stabilize a small-sample covariance estimate. It does not prove better calibration or contract probabilities. The empirical and shrunk challengers must be compared in a pre-registered chronological evaluation.

### Optional conditional scale

When registered pregame features are supplied, a ridge model fits log transformed mean squared **centered** paired score error, keeping global training bias out of the scale target. The convention is `sqrt(1 + estimated centered MSE)`, so scale is floored at one and ridge regularization can strongly attenuate heteroscedastic response. The scale regression and residual pool are estimated on the same training rows; this is an in-sample challenger construction, not evidence of out-of-time calibration. A single predicted scale multiplies both error components, so correlation is retained while variances and covariance scale coherently. Market-like feature names are refused in a market-blind arm. A different scale is a hypothesis about heteroscedasticity, not an assumed improvement. Team-, pace-, availability- and segment-specific matrices remain unsupported unless the corresponding earlier-only fit and validation are actually performed.

## 5. Sport-by-sport volatility matrix

The shared implementation supplies the same artifact and chronology contract, not the same sigma or the same parametric law.

| League | Required joint considerations | Initial shared challenger | Explicit remaining structure / limitation |
|---|---|---|---|
| NFL | Integer scores, key numbers, regular-season ties versus postseason no-tie settlement, overtime and selected-arm identity | Paired empirical score cells with exact integer settlement | No drive-level overtime branch; key numbers only if present in eligible residuals; no residual borrowing between QB and combined arms |
| CFB | Wider opponent-quality heterogeneity, integer/key-number margins, no final ties, overtime rules, tempo differences | Same paired empirical or shrunk-residual family, fitted only to the exact parent | No drive-level overtime branch; selected current parent has no total head, so a joint card must remain unavailable until a real total head exists |
| NBA | Shared pace, no ties, overtime, late fouling and garbage-time state dependence | Discrete paired score residuals; conditional pace scale only as a challenger | No explicit overtime or endgame-fouling branch; earlier joint-score regressions are preserved |
| WNBA | Shared pace, no ties, overtime, player availability and shorter-season estimation uncertainty | Separate WNBA-only fit; no NBA parameter transfer | No automatic availability mixture or postseason transfer; missing eligible archive data remain a blocker |
| MLB | Overdispersed runs, home bottom-ninth/walk-off censoring, extra innings, one-run game mass | Paired final-score residuals only where exact parent and settlement are eligible | No inning, home-score-censoring or extra-inning branch; current margin product does not gain totals authority |
| NHL | Low integer scores, regulation versus OT/SO settlement, one-goal OT/SO finals, empty-net mass, goalie identity | Separate full-game or regulation paired fit with legal tie handling | No explicit empty-net, OT/SO or goalie branch; prior separate-margin calibration warning remains |
| MLS | Regulation-only scores, draws, low-score dependence and quarter-handicap settlement | Regulation paired residual cells; exact total quarter-line handling | No Dixon–Coles correction or playoff extra-time mixing; no spread product is activated for the 1X2-only selected path |

Published models motivate later challengers rather than license hard-coded constants: Stern's NFL normal-margin approximation is market-anchored and era-specific; Dixon–Coles is a low-score soccer correction; NHL scoring-rate work supports state-dependent goal models; and baseball run models require overdispersion and game-structure treatment. None of those sources supplies this repository's model-specific OOF covariance.

## 6. Luck accounting without hindsight revision

“Luck” is not directly observed from a close loss, a bad beat, a blowout, or a winner that disagreed with the market. The implemented `sports.luck_accounting.research.v1` record uses an operational definition:

> the realized outcome residual under a frozen pregame joint predictive distribution.

For each settled game it preserves the parent forecast and distribution hashes and reports:

- actual minus predictive mean for home, away, margin and total;
- standardized margin and total residuals when predictive SD is positive;
- mid-PIT values for discrete margin and total distributions, explicitly not a substitute for randomized-PIT calibration;
- central 50%, 80% and 95% interval coverage;
- CRPS, log loss, zero-probability-outcome indicators and a predictive-SD-standardized multivariate energy score;
- explicit `causal_luck_identified=False` and `single_game_model_bias_estimated=False`.

A tail outcome can be compatible with a calibrated forecast. Repeated signed errors can indicate bias; repeated standardized spread or coverage failure can indicate dispersion error. One game identifies neither. Postgame process statistics may be used in a separately labeled explanatory analysis, but cannot alter the original pregame forecast or become pregame features retroactively.

The aggregate evaluation artifact reports mean signed errors, mean standardized residuals, CRPS, coverage and zero-support counts. It is explicitly `DIAGNOSTIC_NOT_WALK_FORWARD_VALIDATION`; aggregation code is not a substitute for a pre-registered design.

## 7. Data and identity gates

Every training row must bind:

- unique event identity;
- league, exact settlement, parent model/arm and information set;
- market-input role;
- paired predicted home/away means and observed final scores;
- forecast and result-source SHA-256 identities;
- parent-fit cutoff, forecast cutoff, start time and result availability;
- `prediction_kind=CHRONOLOGICAL_OUT_OF_TIME`.

The required order is parent fit cutoff ≤ forecast cutoff < start ≤ result availability < matrix fit time. Duplicate events, future fitted artifacts, training-event reuse, parent/information-set mismatch, code drift, nonfinite values, negative scores and illegal ties fail closed. Prediction requires explicit paired score heads or explicit margin and total heads; winner probabilities are never converted into score means.

Known baseline gaps are not filled with guesses. In particular, existing NFL packed paired residuals do not by themselves provide this fitter's complete row-level provenance; selected CFB lacks a total head; WNBA residual arrays lack the required game-level chronology; and several replay cohorts lack eligible paired score forecasts. These are acquisition/provenance tasks, not permission to relabel retrospective residuals as prospective forecasts.

### Retrospective replay fits created November 3, 2026 UTC

The converter joined each retained margin row to its total row by unique event, checked all parent/settlement/timing identities, derived home and away scores, and minted a disclosed composite forecast hash. It refused to treat simulated timestamps as real captures. Both matrix methods were fitted on the same diagnostic cohorts; no held-out improvement evaluation was performed.

| League | Unique games | Empirical home/away error covariance | Error correlation | Analytic margin SD | Analytic total SD | Mean bias (home, away) | Ledoit–Wolf shrinkage |
|---|---:|---:|---:|---:|---:|---|---:|
| NBA | 1,230 | 33.2595 | 0.2448 | 14.3258 | 18.3920 | (-0.7513, -1.1129) | 0.04277 |
| NHL | 1,312 | -0.3641 | -0.1191 | 2.6160 | 2.3210 | (0.0100, -0.0055) | 0.14896 |
| MLS | 493 | 0.0852 | 0.0584 | 1.6624 | 1.7619 | (-0.0010, 0.2522) | 0.39503 |

These are sample-covariance diagnostics before empirical-pool denominator conversion, discretization and legal-support conditioning. They are not confirmed predictive parameters. Full fitted artifacts, source provenance, bias vectors, shrinkage metadata and summary hashes live under `data/research/volatility_matrix_replay_20261103/`.

| League | Current data verdict | Named next acquisition requirement |
|---|---|---|
| CFB | `BLOCKED: NO_PAIRED_SCORE_HEAD` | Fit and retain a real earlier-only total head and paired OOF score forecasts |
| NFL | `BLOCKED: NO_ROW_PROVENANCE` | Re-run the exact parent/arm walk-forward with event IDs, hashes and real availability timestamps |
| WNBA | `BLOCKED: ANONYMOUS_RESIDUAL_ARRAYS` | Persist paired walk-forward rows bound to official-plus-ESPN sources and chronology |
| MLB | `BLOCKED: RETROSPECTIVE_BATCH_CHRONOLOGY` | Produce a new as-of paired-run forecast replay with pregame cutoffs and result receipts |

The detailed machine-readable record is `data/research/volatility_matrix_replay_20261103/readiness.json`.

## 8. Predictive acceptance protocol

Implementation acceptance and predictive acceptance are separate.

### Software acceptance

- Matrix symmetry, finite values and positive semidefiniteness.
- Exact margin/total variance identities and separate bias retention.
- Reference-checked shrinkage and reproducible paired simulations.
- Legal support, exact push/half-win/half-loss handling and MLS quarter lines.
- Chronology, duplicate, parent-scope, market-role, training-reuse, hash and code-drift refusals.
- Parent-card immutability, visible per-event failures and unchanged model defaults.

### Pre-registered predictive evaluation

1. Freeze the parent model/arm, information set, settlement, eligible league/season population, training windows, matrix method, scale features, and evaluation code before seeing confirmation outcomes.
2. Build rolling-origin fits using only results available before each forecast. Preserve untouched confirmation periods.
3. Compare against the exact existing independent margin/total research parent on the same events. Opposite sides and alternate-line ladders do not add independent games.
4. Evaluate unique games jointly, with paired uncertainty intervals by event. Keep league and settlement cohorts separate unless pooling itself is a registered challenger.
5. Primary distribution metrics: margin and total CRPS. Secondary diagnostics: log loss with zero-support counts, central interval coverage, randomized-PIT behavior for discrete outcomes, multivariate energy score and joint tail behavior, signed bias, standardized-residual dispersion, and segment stability. Marginal calibration alone does not establish calibrated score dependence.
6. Evaluate contract probabilities separately with timestamped quotes and exact settlement. Market comparison occurs only after the independent forecast is frozen. Closing prices are not decision-time prices.
7. Tune family, shrinkage, window length and context slices only in inner chronological windows. Use one untouched confirmation period. Predeclare a small primary hypothesis family and control best-of-many model/metric/slice multiplicity with an appropriate confirmatory procedure; report effect sizes and dependent, event-clustered intervals rather than isolated p-values.
8. Require improvement on confirmation data, not only fit-window or synthetic checks. Preserve null and negative results. Do not promote from a few favorable games, repeated simulations, or software test counts.
9. Keep selected defaults, qualification, economics and wagering authority unchanged unless the repository's separate applicable gates pass. Current wagering remains OFF, dose 0 and allocation ZERO.

## 9. Use in sports-betting research

A joint distribution makes margin and total quotes coherent because both come from the same score cells. It also supports exact pushes and paired simulation counts. Derived PMFs and grade/evaluate commands remain mathematical diagnostics; the card pipeline separately enforces supported contract products and does not activate MLB totals or MLS spreads. It does not create an edge. Forecast probability, market price, qualification, expected value, return variance and wagering authority remain separate decisions.

Lower predictive SD is not automatically a better bet, and higher SD is not automatically “more value.” A candidate's settlement probability, price-sensitive EV, return SD and model risk can rank differently. Alternative lines are correlated views of one event, not independent diversification. Until out-of-time evidence establishes calibration and economic value, the matrix is diagnostic only.

## 10. Files and execution

- `models/common/volatility_matrix_v1.py`: fit, analytic volatility, joint prediction, exact marginals, paired simulation, luck records and aggregate diagnostics.
- `pipelines/cards/volatility_research.py`: optional seven-league child-card adapter and product-boundary enforcement.
- `scripts/cross_sport_volatility_research.py`: `fit`, `card`, `grade` and `evaluate` commands; outputs are create-only.
- `scripts/build_volatility_replay_inputs.py`: disclosed NBA/NHL/MLS replay-row converter and diagnostic fit runner.
- `data/research/volatility_matrix_replay_20261103/`: six fitted artifacts, reproducible paired-input generation, summary hashes and seven-league readiness record.
- `tests/test_volatility_matrix_v1.py`: synthetic correctness and refusal checks, explicitly not predictive validation.
- `tests/test_volatility_replay_inputs.py`: source-row, persisted-hash, provenance and prediction reconciliation for the six replay artifacts.

Example fit invocation:

```bash
python3 scripts/cross_sport_volatility_research.py fit \
  --input research/volatility/fit_request.json \
  --output research/volatility/nfl_matrix.json
```

Example child-card invocation:

```bash
python3 scripts/cross_sport_volatility_research.py card \
  --card path/to/frozen_parent_card.json \
  --config research/volatility/card_config.json \
  --output research/volatility/card_output \
  --simulations 100000
```

The configuration schema is `sports.volatility_card_config.research.v1`; each fitted model file is SHA-256 pinned. Existing parent cards and default selection files are not modified.

## 11. External methodological references

- Ledoit, O. and Wolf, M. (2004), “A well-conditioned estimator for large-dimensional covariance matrices,” *Journal of Multivariate Analysis* 88(2), 365–411. [DOI](https://doi.org/10.1016/j.jmva.2004.02.002).
- Gneiting, T. and Raftery, A.E. (2007), “Strictly Proper Scoring Rules, Prediction, and Estimation,” *JASA* 102(477), 359–378. [DOI](https://doi.org/10.1198/016214506000001437).
- Stern, H.S. (1991), “On the Probability of Winning a Football Game,” *The American Statistician* 45(3), 179–183. [DOI](https://doi.org/10.1080/00031305.1991.10475797).
- Dixon, M.J. and Coles, S.G. (1997), “Modelling Association Football Scores and Inefficiencies in the Football Betting Market,” *JRSS-C* 46(2), 265–280. [DOI](https://doi.org/10.1111/1467-9876.00065).
- Buttrey, S.E., Washburn, A.R. and Price, W.L. (2011), “Estimating NHL Scoring Rates.” [Paper](https://faculty.nps.edu/awashburn/docs/EstimatingNHLScoringRates.pdf).
- Mauboussin, M.J., *Untangling Skill and Luck*. Skill/luck variance decomposition is useful for ex-ante rating research, not retrospective excuse-making. [Paper](https://www.trendfollowing.com/pdfs/UntanglingSkillandLuck.pdf).

## 12. Current verdict

**Shared software capability implemented across seven leagues; retrospective diagnostic matrices fitted for NBA, NHL and MLS; CFB, NFL, WNBA and MLB remain explicitly data-blocked. Cross-sport predictive improvement is not established.** No fitted league matrix is qualified merely because the shared code and artifacts exist. Historical records remain unchanged, and no selection or wagering setting is activated by this work.
