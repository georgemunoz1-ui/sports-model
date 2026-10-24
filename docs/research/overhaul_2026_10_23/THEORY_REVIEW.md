# Independent theory and specification review

Review date: 2026-10-23 UTC (2026-10-22 America/Los_Angeles). Scope: the attached route assessment and three pasted analytical briefs. This review does not attest that the four earlier claimed agent reports were executed or that the repository implements the proposals. No forecast, validation status, publication status, or wagering authority is changed by this review.

## Disposition

Retain separate forecasting, validation, selection, and price diagnostics as a defensible research architecture. Replace universal optimality claims with testable scope statements. Implement evidence integrity and evaluation infrastructure now; treat statistical floors, drift policies, calibration methods, and selector designs as explicit protocol choices. Research output must continue when publication or selection is blocked, provided the forecast's own mandatory input and chronology contract is satisfied.

## Findings and corrected requirements

| ID | Finding | Corrected requirement |
|---|---|---|
| T01 | The claim that excluding price costs exactly zero accuracy conflates decision costs with predictive information. | A price-independent selector is the chosen policy. Its accuracy cost is unknown. Price invariance applies with the forecast, target line, settlement, and other selection inputs fixed. A separately identified market-informed research arm can test informational value without changing the independent arm. |
| T02 | A calibrated score is not necessarily the true conditional probability needed for a Bayes-optimal decision. | Validate discrimination, calibration, and risk at coverage separately. Do not certify optimality from reliability bins or a calibration map alone. |
| T03 | Estimate-then-optimize superiority is overstated. | The cited result is asymptotic under model-class and regularity assumptions. It supports a baseline architecture, not a ban on end-to-end or learned selective challengers. |
| T04 | Chow/reject-option theory does not uniquely mandate a rejection-cost interpretation for this project. | Choose an explicit cost, bounded-risk, or bounded-coverage objective. For accuracy at coverage, a development-selected threshold and fixed confirmation protocol suffice; a fictitious monetary rejection cost is unnecessary. |
| T05 | A closing-market score gap is not an identified firewall cost. | Publish same-cutoff market baselines and separately label closing-market context. A causal/incremental information claim needs paired arms on identical events, cutoff, fitting/tuning budgets, and evaluation windows. |
| T06 | Walsh/Joshi and Hubacek do not prove the independent pipeline is universally optimal or profitable. | Treat reported results as specific experiments. Walsh/Joshi's quoted ROI comparison used one betting test season. Training a model to decorrelate from market predictions uses market information in its objective and is not evidence of market-blind fitting. |
| T07 | The proposed 200 events / 20 slates / 8 weeks / rho>=0.3 / three attempts / 12-month expiry bundle has no universal statistical justification in the cited sources. | Require per-target declared sample/coverage minima, practical effect size, uncertainty method, multiplicity family, and a power design. Policy defaults must be labeled as policy. A numerical minimum does not replace the calculated evidence requirement. |
| T08 | Permanently inheriting a parent's track record risks invalid score pooling or approval transfer. | Inherit immutable provenance, trial-family membership, inspected-data exposure, and failure history. Keep predictive scores attached to exact versions. Reuse evidence only under a declared applicability rule; changed children do not automatically inherit validation. |
| T09 | A permanent ban on an entire manual-override class is broader than required. | An ad hoc historical override cannot be retroactively prospective. A repeatable rule can become a future versioned candidate with independent evaluation. Never silently rewrite the original event decision. |
| T10 | A blanket ban on early stopping is not mathematically necessary; symmetric demotion and promotion tests are not generally optimal. | Permit a preregistered fixed endpoint or a valid sequential design with stated assumptions. Keep immediate integrity invalidation distinct from statistical performance degradation. Calibrate monitor thresholds and false-alarm handling; an alarm must not suppress diagnostic logging. |
| T11 | Half-credit for pushes changes the objective and conflicts with the proposed winning-settlement objective. | Freeze win/loss/push/void treatment. For an unconditional winning-settlement objective, a push is not a win; report decisive win rate and push rate separately. A half-credit utility requires a separately identified policy. |
| T12 | Market-independent margin generation is compatible with evaluation at a market-defined line, but the language is ambiguous. | Declare the line as target metadata for computing P(margin + handicap > 0), not as a fitted predictive feature. A changed line requires a new target evaluation. Missing payout odds and missing target lines have different consequences. |
| T13 | A child hash or caller-provided signer name cannot establish preregistration or independent certification. | Verify content hashes against retrievable artifacts and bind registration to a trusted timestamp/append-only writer. Any author/signature separation must be an access-control property, not a string inequality. |
| T14 | A full risk-coverage curve is descriptive if thresholds are selected after outcomes. | Freeze the operational threshold separately. Evaluate selectors on the same frozen forecast stream at matched coverage and evaluate forecasters on identical events. Preserve full-slate scores and eligibility coverage. |

## Mathematical counterexample to the zero-accuracy claim

Consider equally frequent subgroups with outcome-A probabilities 0.9 and 0.3. A forecaster that reports 0.6 for every case is perfectly calibrated in aggregate and predicts A with 60% accuracy. Information identifying the subgroups permits predictions A in the first group and B in the second, for 80% accuracy. If market information supplies that distinction, its role is predictive information even with symmetric classification costs. This is a synthetic counterexample, not a sports result. It does not authorize market input to the independent model.

## Minimal executable acceptance matrix

1. **Exact target:** each decision binds event, period, side, line, forecast cutoff, and settlement version. Winner and cover probabilities cannot substitute for one another.
2. **Price invariance:** vary only payout odds among low/high/missing; selection probability, acceptance, and confidence band remain identical. Price diagnostics change or become null.
3. **Line sensitivity:** changing a spread/total line creates a new target evaluation and recomputed probability; never attach an old cover probability to a new line.
4. **Push semantics:** ordinary settlement diagnostics use p_win*(decimal_odds-1)-p_loss. Conditional break-even basis is labeled. Other payoff maps require their full settlement states.
5. **Eligibility isolation:** missing target-specific validation yields raw evidence plus null selectable probability and a reason. This cannot erase raw forecasts or disable unrelated research products.
6. **Shadow isolation:** internal SHADOW acceptance remains distinguishable from ACTIVE publication. Tests passing do not establish predictive promotion.
7. **No abstention wins:** blocked and eligible-abstained cases remain in coverage denominators. A rejected candidate's later loss never becomes a correct prediction.
8. **Unsettled outcomes:** live, postponed, void, and unavailable results cannot enter win/loss grading as finals. Zero selected events produce undefined selective accuracy.
9. **Independent identity:** changed feature, calibration, threshold, tie policy, target objective, or code build cannot masquerade as the old approved combination.
10. **Lineage:** child trials retain family's searched configurations and used data windows while keeping scores/version approval separate.
11. **Confirmation discipline:** protocol registration precedes the evaluation window. Development/discovery data remain excluded; retuning invalidates confirmation, not the original records.
12. **Evidence resolution:** unavailable, mismatched, future-dated, or unhashed required evidence fails eligibility with a precise reason. A caller flag cannot grant approval.
13. **Research throughput:** each blocking dependency identifies its affected product and next evidence requirement. A failure in another sport does not block independent work.
14. **Power and coverage:** distinguish all opportunities, integrity-eligible opportunities, selected opportunities, and settled selections. A power assertion records the chosen effect, paired variance or simulation design, dependence assumptions, multiplicity, and required number of usable selected events/blocks.
15. **Uncertainty distinction:** distinguish predictive intervals, parameter/probability confidence intervals, Monte Carlo error, and empirical confidence-band bins. Conformal coverage does not certify event probabilities.

## Sources checked

- Elmachtoub, Lam, Zhang, Zhao, *Estimate-Then-Optimize versus Integrated-Estimation-Optimization versus Sample Average Approximation: A Stochastic Dominance Perspective*, arXiv:2304.06833, version 4. https://arxiv.org/abs/2304.06833 — supports asymptotic ETO result under well specification; does not prove this sports implementation is optimal.
- Franc and Prusa, *On discriminative learning of prediction uncertainty*, ICML 2019. https://proceedings.mlr.press/v97/franc19a.html — optimal rejection is based on conditional risk and the work learns an uncertainty ordering when posterior probabilities are unavailable.
- Franc, Prusa, Voracek, *Optimal Strategies for Reject Option Classifiers*, JMLR 24(11), 2023. https://jmlr.org/papers/v24/21-0048.html — unifies cost-based, bounded-improvement, and bounded-abstention formulations; a cost model is not the only supported formulation.
- Geifman and El-Yaniv, *SelectiveNet*, ICML 2019. https://proceedings.mlr.press/v97/geifman19a.html — demonstrates an integrated selective model improving risk-coverage on its studied datasets, supporting research rather than categorical exclusion of this design.
- Walsh and Joshi, *Machine learning for sports betting: should model selection be based on accuracy or calibration?*, arXiv:2303.06021, version 4. https://arxiv.org/abs/2303.06021 — one betting test season, with average ROI +34.69% versus -35.17% for the compared systems; no general zero-cost market-exclusion theorem.
- Cawley and Talbot, *On Over-fitting in Model Selection and Subsequent Selection Bias in Performance Evaluation*, JMLR 11, 2010. https://jmlr.org/papers/v11/cawley10a.html — optimizing finite-sample evaluation criteria can overfit and bias reported performance.
- Howard, Ramdas, McAuliffe, Sekhon, *Time-uniform, nonparametric, nonasymptotic confidence sequences*, Annals of Statistics 49(2), 2021. https://arxiv.org/abs/1810.08240 — supports valid sequential alternatives under their assumptions, not unrestricted repeated peeking.
- Barber, Candes, Ramdas, Tibshirani, *Conformal prediction beyond exchangeability*, Annals of Statistics 51(2), 2023. https://arxiv.org/abs/2202.13415 — drift-aware coverage robustness has conditions and does not establish calibrated winner/cover probabilities.

## Scope limitation

This review found no supplied empirical basis for the proposed universal floors and no proof that any newly proposed component improves the sports system. The four referenced prior reports were not present at their stated local paths in the parent's inspection. The current report is an actual independent review in this agent session; its recommendations require implementation verification and target-specific prospective evidence before promotion.
