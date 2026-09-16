# Tested defaults across sports — 2026-09-16

The shared policy is `data/model_selection/defaults_v1.json`. Inspect it with `python scripts/model_defaults.py`. Query an exact product with `--league wnba --target total`, or an exact football cohort with `--league cfb --week 2 --division FBS_VS_FBS`.

Selection considers evidence quality, chronological evaluation, comparable populations, calibration, stability and performance. It does not count unit tests or Monte Carlo draws as predictive evidence. A new feature-rich model is not automatically an upgrade. Retain a tested incumbent when an apparent improvement is too weak to establish superiority. Every selection pins its source evidence. Changed evidence requires a versioned review; defaults do not silently drift.

| Sport/product | Selected research default | Evidence and limitation |
|---|---|---|
| NFL winner | QB integrated-context arm | 1,865 non-tied OOF games; 0.222912 Brier, 63.43% hit rate. User-authorized provisional selection; current-state gates from PR #29 remain. |
| MLB winner | Frozen V13 estimator, current-input research profile | Broader OOF testing: 1,054 games. Paired 234-game holdout: 64.53% hit rate, Brier 0.2447. d_logistic_2f has slightly lower holdout Brier 0.2438 but 58.97% hit rate; no established superiority. V13 retains NO_PROMOTE/no-action status. |
| WNBA winner/margin/total | FF7 logistic/ridge v1 shadow | 1,633 walk-forward games; winner Brier 0.211232 and hit rate 66.69%. Target-specific tests passed versus baseline with multiplicity adjustment. |
| CFB FBS/FBS, Week 2 onward | Elo/form logistic/ridge v1 shadow | 10,818 pooled OOF games, Brier 0.182233; paired improvement versus causal Elo. The pooled sample is not misrepresented as a separately measured Week-2-only sample. |
| CFB FBS/FBS, Week 1 | Elo/context opener-specific arm | 758 opener games, Brier 0.18327; subgroup calibration gates pass. Full-form arm's Week 1 failure is not concealed by pooled results. |
| NBA, NHL, MLS | No verified tested default recovered | This checkout lacks recoverable fitted forecast/evaluation evidence sufficient for selection. MLS has a read-only evaluation adapter; that does not establish a current forecasting model. |

## Runtime behavior

- `scripts/generate_card_force.py` applies the shared selection policy to every newly generated card row. Unsupported leagues/products fail explicitly. CFB requires week and subdivision scope; FCS/FBS is not silently substituted.
- NFL's Week 2 selector checks its selected QB identity against the shared policy. Explicit NFL experiment commands remain available, labeled experimental; the default shared card cannot headline them.
- MLB's unchanged, pinned producer still computes and retains both arms. The card selects the V13 winner probability and direction, preserving the deterministic candidate in a labeled challenger block. The new `mlb.v13.current_input.research.v1` identity names this selection of the existing estimator under the current input policy; it is not a refit or the historical replay's seed/input identity. Lineage retains the producer bundle ID, source hashes, inputs and draw directory.
- MLB V13 is Monte Carlo-only: analytic probability and analytic–simulation gap are null, displayed as unavailable. Matching two copies of the same Monte Carlo estimate is never called convergence. Totals/run lines remain settlement-blocked.
- WNBA's selected wrapper is `pipelines.cards.selected.wnba_predict`, delegating to the pinned tested model without changing its arithmetic or data gates. Existing dated fallback builders remain historical commands; they are not selected defaults.
- CFB's selected model is the existing tested v1 family, with the recorded opener-specific profile. V2 acquisition alone cannot replace it. The common current-card CFB/WNBA adapters are absent in this checkout; policy selection does not claim those adapters have been restored or current inputs acquired. Existing model-specific runners still need valid current input packages.

## Product and release separation

Winner selection does not transfer to totals, spreads, props, regulation/OT variants, postseason or another league. WNBA's three targets have separate evidence. No other target inherits a default automatically. NFL QB scores cannot borrow the failed-screen combined arm's residual pool. NBA/NHL/MLS are explicitly blocked rather than filled by an unsupported fallback.

All choices remain research-only where release gates have not cleared. No historical artifact, frozen estimator, ledger, action gate or stake was changed. Selecting V13 as a research presentation default does not overturn its frozen no-promotion verdict or establish an edge over market/base rate.

## Verification and remaining scope

15 selection contract tests cover evidence drift/missingness, failed and challenger refusal, product/cohort separation, all seven league statuses, correct MLB direction selection, no fabricated analytic probability/convergence, and action-off preservation. The existing 100 NFL and 13 MLB tests also pass locally. These 128 tests are software checks, not 128 pieces of predictive evidence.

Remaining operational blockers include current source acquisition, missing WNBA/CFB common-card adapters, missing NBA/NHL/MLS forecasting evidence, the unavailable production ingestion archive, and overdue recovery jobs. The local health report also found missing pytest for two legacy self-tests. None is papered over by this selection policy.

## Governance amendment: Week 2 stability and Week 3+ B2 sequencing

The following distinctions apply verbatim:

- out-of-fold within reused history ≠ untouched program-level holdout
- research default ≠ permanent default
- selected arm ≠ official forecast eligibility

The NFL QB winner arm remains a provisional research default selected from reused 2019–2025 out-of-fold evidence. Week 1 stays graded as combined-headlined research; QB results remain parallel-arm results.

**B2:** construction trace complete. Schedule any prospective B2 comparison against the QB-default arm's frozen prospective baseline starting **2026 Week 3 or later**, never Week 2. Keep the baseline/mean policy fixed across paired arms; isolate the variance change. A new mean policy requires a new experiment version. The historical combined-model trace does not supply a fitted QB-specific score distribution. The experiment still needs its exact output target, variance transform, parameter/source hashes, evaluation cohort, metrics and decision rule registered before execution or exposure to evaluation outcomes. This sequencing amendment does not claim those missing specifications or execute B2.

**P3 — assimilation effect in a fresh event forecast: OPEN.** Sixteen state checks and the QB update prove reproducible state application. Saved state-sensitivity calculations also show probability changes under held context; they do not complete the fresh-event demonstration.

The first two release-path items are:
1. Bind all eligible Week 1 games to reconciled sources, preserve before/after team and QB states, and verify state-update provenance.
2. In a fresh, event-specific Week 2 QB output, expose before/after feature values, their source/game/state hashes, numerical feature contributions where supported, and the resulting forecast delta. Hold model parameters and newly acquired event/personnel/weather context fixed for this attribution comparison. Retain a hash linking the actual emitted forecast to the post-update feature vector. Label the prior-state comparison diagnostic only; it is not another historical pregame forecast.

Zero effect is an admissible finding: disclose it and its cause rather than force a nonzero delta. State checks, archived sensitivity results, or a manifest flag alone do not close P3.

Next deliverable: fresh event-specific Week 2 selected-default research package, including P3 evidence. Official release gates remain unresolved; action authority OFF; dose 0.0.

Publication is operator-verified in a private repository. Independent verification requires authorized access to the remote manifest and underlying artifacts; a sandbox link alone does not establish that access.
