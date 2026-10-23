# MI-002: versioned numerical stochastic identity

The market/display metadata leak is repaired for the supported v2 fixed-state execution paths. The repair creates a separately identified research child. It does not fit new weights, certify probabilities, change the frozen model registry, or grant action authority. Full legacy replay remains available and retains the original leak by design.

## Evidence and scope

The starting counterexample and synthetic fixture construction were inspected from PR74, commit `d5ab18213253fb2c903a943f06d499fe547afc7d`, file `tests/test_selected_market_independence.py`, Git blob `7accd370573e441d60685ea55fb5da5d60209715`. Local fixtures retain real code-pin checks and run the actual loaders, transforms, samplers and selected-model handling. Six current-package fixtures are synthetic software evidence; NFL uses the retained fitted historical artifact. The calibrated-spread check uses the authentic saved fitted calibrator. No predictor is mocked.

Final execution receipt: `MI002_REPRODUCTION_r5.json`, report SHA-256 `43d8839c813a613947c67ab2111b246eca164bb9aec0b9b5341086c12f00c7ee`. It records source bytes, input/package hashes, legacy and child identities, retained-array hashes and numerical probabilities. Earlier receipts remain unchanged; they describe earlier helper bytes and are superseded for this final implementation. Temporary reproduction arrays are removed unless `--retain-runs` is supplied; hashes in a receipt alone do not constitute durable raw-array storage.

At 100,000 draws, the synthetic MLB metadata twins changed the legacy selected probability from **0.57832 to 0.57888**. Under the final v2 code both produce **0.57923**, with identical numerical identities and retained draw bytes. This is an identity repair example, not an accuracy comparison.

| Executed path | Versioned repair and tested boundary |
|---|---|
| NFL selected QB and independent pregame arms | Exact consumed selected features, numerical head parameters and sampler bytes define the child. Historical fitted QB quote twins pass; consumed-feature changes change identity. Combined arm also preserves exact head predictions and resamples its existing joint kernel; original score-array receipts are checked. Market-informed enhanced/live modes are explicitly rejected by this independent wrapper. |
| CFB regular and Week 1 selected arms | Exact fitted feature order, consumed values, numeric parameters and code define identity. Both selected branches tested. |
| WNBA | Consumed home/away feature fields and exactly three numeric league-state values are allowlisted. Nested unused team metadata is excluded. Actual logistic helper code and retained rounding are bound. |
| NBA / NHL initial research baselines | Actual nine consumed features, fitted heads and transform/sampler code are bound. This does not reclassify these baselines as validated defaults. |
| Current MLB package | The actual frozen V13 formula, HFA code and consumed pitcher/team/park inputs define identity. Full package/model-state metadata hashes remain archival. The stale legacy MLB package is not repaired through a code-pin bypass. |
| MLS initial regulation baseline | Fitted goal heads and consumed features define the independent-Poisson child. Regulation draw semantics are preserved. |
| Generic margin/total research distributions | `distribution_research.build` inherits explicit v2 row semantics only. After existing fitted-model, chronology, scenario/calibration and PMF validation, canonical support/masses, target, bound numeric parent, sampler code and draw count seed the child. Seven parent→margin-PMF→draw quote twins pass. The generic total mechanism uses the same sampler; this does not manufacture a missing CFB total head or establish total calibration. |
| Optional NFL calibrated-spread overlay | Existing `spread_runtime.build_overlay` admission executes first. The v2 wrapper binds numeric calibrated support/masses, intercept/slope, target, score-array hash, numeric parent, code and draw count. Calibrator metadata twins preserve v2 draws and contract probabilities; a coefficient change changes the numerical identity and exact calibrated probabilities. Requested lines remain downstream diagnostics. |

## Identity and replay behavior

`pipelines/cards/semantic_identity.py` is outside frozen model code. The original inference, package code-pin admission, generic distribution core and NFL calibration core are unchanged. Low-level wrapper APIs default to `legacy.v1`. New CLI runs use explicit/default `market_blind_numeric.v2`; an explicit `legacy.v1` request remains the replay path. Neither path implies predictive approval.

Full event, package, parent forecast, fitted artifact and distribution hashes remain in archival provenance. They do not seed v2 numerical sampling. The v2 identity includes actual consumed feature values, fitted numerical state, event target, cutoff/start, draw count, sampler identity, NumPy version and helper source bytes. Changing a consumed feature, coefficient, PMF mass/support, target or draw count changes the numerical identity. Market and display metadata perturbations preserve it.

V2 also emits source-addressed `feature_procedure_id` and `calibration_procedure_id`, with the full observed component artifacts in `identity_provenance`. Base selected paths explicitly identify **no separate fitted post-hoc calibrator**, tied to their actual prediction code; WNBA rounding is disclosed. This is evidence of the executed stage, not evidence of calibration. The optional NFL spread child identifies its actual fitted CDF recalibration separately. `numerical_identity.fitted_state_sha256` is the semantic model binding; the original `model_state_config_hash` remains the potentially metadata-bearing archive binding.

Shared runs save the separately named `event_id.semantic-v2` draw directory, numeric input identity, complete legacy parent forecast, provenance and a manifest. Direct NFL persistence uses its existing writer for the separately identified bundle. The optional spread child embeds its full legacy overlay receipt and preserves the original calibrator hash. No frozen artifact is overwritten or silently relabelled.

Unknown semantics, mismatched numeric-parent hashes/targets, invalid PMFs, code-pin drift, mismatched NFL parent predictions, and corrupted original score arrays refuse. There is no automatic compatibility fallback or inferred certification. Generic historical rows without a v2 marker still use the exact original distribution sampler.

## Verification and limits

Focused verification: **83 passed** across `test_semantic_identity.py`, `test_semantic_distribution_identity.py`, `test_semantic_spread_identity.py`, `test_cross_sport_distributions.py` and `test_nfl_spread_calibration.py`. The reproduction command is:

```sh
python scripts/verify_semantic_identity.py --output NEW_RECEIPT.json --retain-runs NEW_RUN_DIRECTORY
```

This closes the demonstrated inference seed leak on the named v2 paths for fixed fitted state. It does not certify a market-free acquisition/training history, full reacquisition/refitting invariance, predictive accuracy, present-day data freshness, or prospective selection eligibility. Explicit legacy runs still have MI-002; intentionally market-aware NFL modes remain a separate information regime. All fitted procedures keep their previous research/validation status, and action authority remains false.
