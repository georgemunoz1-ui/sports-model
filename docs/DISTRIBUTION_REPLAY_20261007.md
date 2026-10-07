# Distribution rollout evidence — October 7, 2026

The shared layer supports NFL, CFB, NBA, WNBA, MLB, NHL and MLS. This follow-up
executes authentic historical fitting and evaluation where the retained sources
support it. It does not activate a new accuracy default or claim improved ATS
performance. Source reconstruction, pregame capture, software acceptance, and
prospective performance remain distinct.

The owner requested completion of PR61. The experiment was committed to that
branch before execution in `docs/experiments/DISTRIBUTION_REPLAY_20261007.json`
and registered in `state.json`. Earlier queue entries and verdicts are unchanged.

## Executed study

Four sports, seven margin/total products, 3,661 distinct later-period games and
6,608 game-product evaluations were scored. Each parent model has its own frozen
identity. Conditional scaling changes only the residual scale; CDF calibration
is a separate experiment. No parent coefficients were retuned on the evaluation
period. Dates are chronological, but this history has been used in prior research;
these are retrospective diagnostic results, not untouched confirmatory evidence.

| Product | Residual / calibration / evaluation games | CRPS change from conditional scaling | 95% week-block interval |
|---|---:|---:|---:|
| CFB margin | 698 / 713 / 714 | +0.000481 | [-0.000123, +0.001090] |
| NBA margin | 1,230 / 1,230 / 1,230 | +0.004512 | [-0.010651, +0.018417] |
| NBA total | 1,230 / 1,230 / 1,230 | +0.000986 | [-0.003087, +0.005080] |
| NHL margin | 1,312 / 1,312 / 1,312 | +0.000486 | [-0.000802, +0.001799] |
| NHL total | 1,312 / 1,312 / 1,312 | -0.000175 | [-0.000400, +0.000042] |
| MLS margin | 493 / 510 / 405 | -0.000261 | [-0.001668, +0.001296] |
| MLS total | 493 / 510 / 405 | -0.000076 | [-0.001041, +0.000823] |

Lower CRPS is better. Every conditional-scale interval includes zero. Retain the
empirical reference for this comparison; the study does not establish a scaling
improvement in any sport.

The NHL margin CDF calibrator reduced CRPS by 0.004103, with a descriptive
week-block interval of [-0.007417, -0.000947]. Its hypothetical-contract log-loss
interval includes zero. One evaluated final margin still had zero exact-score
probability. This is a candidate for further testing, not an activation decision.
There is no multiplicity adjustment or verified market benchmark.

Six of seven CDF fits refused to run because calibration outcomes lay outside
the empirical support. No observations were removed, no probabilities silently
clipped, and no smoothing was selected after viewing outcomes. A separately
registered tail/support model is needed before calling these reliable discrete
score distributions. Six evaluated reference products also had zero-supported
scores. NHL margin calibration cannot repair that structural limitation.

All contract lines here are explicitly hypothetical: a fixed home-handicap grid
for margins and a half-point grid derived from the fixed parent mean for totals.
They are not observed betting lines. Cover-category Brier and log loss are useful
settlement diagnostics, but neither ATS hit rate nor executable profitability is
established by this study.

## Remaining work by sport

| Sport | Completed here | What prevents activation |
|---|---|---|
| NFL | Shared layer and canonical pregame integration; prior NFL work remains distinct | Original selected-parent OOF rows and source-bound fitting inputs must be recovered; authentic availability and prospective evaluation remain |
| CFB | Fitted and evaluated margin distributions on 714 later games | Selected parent has no total head; support/tail defects; availability inputs; prospective cohort |
| NBA | Fitted and evaluated margin and total on 1,230 later games | No demonstrated improvement; empirical support defects; availability inputs; prospective cohort |
| WNBA | Shared implementation and sport settlement | Official-plus-ESPN historical box archives and identified forecasts required; anonymous residual arrays are insufficient |
| MLB | Shared implementation and extra-inning settlement | Need source-bound point-run forecasts and actual final margins/totals; winner-only evaluations and the tie-proxy kernel do not validate this product |
| NHL | Fitted and evaluated margin and total on 1,312 later games; one fitted CDF calibrator | CDF signal is retrospective; zero exact-score support remains; goalie/availability inputs and prospective cohort required |
| MLS | Fitted and evaluated regulation margin and total on 405 later games | No demonstrated improvement; tail support, availability inputs and prospective cohort required |

The archive retrieval attempted for missing historical inputs returned HTTP 403
at the supplied download URL. Existing source gaps are retained as gaps. No
historical forecast registration was created after the fact. No availability
scenario weights, player effects, lineups or injury effects were invented.

## Reproduction and verification

`data/research/distribution_replay_20261007/` retains normalized identified
cohorts, frozen parent and distribution artifacts, all paired reports, forecast
hashes, 700,000 actual saved draws and a complete file-hash manifest. Source
receipts and source-manifest pins identify the prior retained provider captures.
Normalized-cohort replay verifies the computation; it is not independent
attestation of historical source availability.

```bash
python scripts/verify_distribution_study.py data/research/distribution_replay_20261007
python -m unittest discover -s tests -p test_distribution_history.py -v
```

The acquisition-dependent full study can be rerun with the pinned input archive:

```bash
python scripts/run_distribution_history.py \
  --design docs/experiments/DISTRIBUTION_REPLAY_20261007.json \
  --history PATH_TO_PINNED_HISTORY \
  --cfb-features data/cfb/model/cfb_v1_features.parquet \
  --output UNIQUE_DIRECTORY
```

For historical reconstruction, prediction time is simulated at start minus one
hour; result eligibility is conservatively assumed at start plus 48 hours. These
are disclosed assumptions, never source-capture timestamps. The runner rejects
overlapping seasonal boundaries. Actual artifact creation clocks remain current.
The initial runner attempt stopped at an incorrect positional simulation call;
the call was repaired without altering data, split, method or evaluation policy.
The completed run and replay use the repaired runner.

The earlier `docs/releases/2026-10-07-cross-sport-distributions/verification.json`
remains the original software-only checkpoint. This document and the new study
supersede its not-yet-run historical-fit status without rewriting that checkpoint.
Software merge does not clear standing repository health or close issue #59.
