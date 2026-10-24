# Dormant binary isotonic replacement proposal

This directory proposes a replacement API for the dormant binary helper. It is not a drop-in patch to `harness/calibration.py`, and changes no active caller, forecast, model registry, default, or deployment. Draft review does not authorize adoption or promotion. The separate margin-support/CDF experiment must not be routed through this binary helper.

## Reproduced defects and reference comparison

`original_calibration.py` preserves the source at commit `7cf2aea0581b4048802c920c9670823fab21679e` solely for regression reproduction. For 125 copies each of scores `[0.1, 0.2, 0.8, 0.9]` paired with labels `[1, 0, 0, 1]`, its PAVA implementation predicts `1.0` at `0.2`; sklearn's reference fit gives `1/3`. The old fit also accepts this 500-event isotonic call although its method gate permits only Platt at that size.

The proposal uses `IsotonicRegression(increasing=True, y_min=0, y_max=1, out_of_bounds='clip')`. Tests compare weighted, tied-input predictions directly with sklearn. This is a binary probability mapping: clipping does not enforce CDF endpoints and cannot repair missing distribution support.

## API migration, only after separate integration approval

Old interface: `fit(method, scores, labels, fold_role=...)` returns a dictionary with a prediction callable.

Proposed interface:

```python
artifact = fit(
    scores, labels,
    base_model_id="cfb.binary.model_version.home_win.full_game_ot",
    calibration_rows=event_rows,
    fitted_at="2026-01-01T00:00:00Z",
    base_training_event_ids=training_ids,
    sample_weight=event_weights,  # optional, one positive weight per event
)
probabilities = predict(
    artifact, new_scores,
    expected_base_model_id="cfb.binary.model_version.home_win.full_game_ot",
)
```

Both identity arguments are required nonempty strings; prediction rejects a mismatch. The application must obtain the expected ID independently from the actual base-model configuration, not copy it from the calibration artifact. Use an immutable ID that distinguishes model version, league, binary outcome orientation, and settlement. This guard binds the declared identity; it cannot authenticate the provenance of arbitrary score arrays.

The artifact schema is `binary.isotonic.repair.proposal.v2`, with JSON-safe knots, base-model ID, fit-event IDs, training hash, source-code hash, dependency version, and artifact hash. Artifacts from the earlier isolated v1 proposal are incompatible and must not be relabelled or have their hashes manually repaired. Refit under approved chronological data boundaries if integration is later authorized.

Each event row requires `event_id`, `base_fit_cutoff`, `forecast_cutoff`, `start_time_utc`, `result_available_at`, and `prediction_kind='CHRONOLOGICAL_OUT_OF_TIME'`. Timestamp order, base-training/calibration disjointness, and event uniqueness are checked. Source availability remains explicitly unverified: supplied timestamps and role labels are not authenticated historical evidence. Applications must separately prevent application to fitting events and enforce fit-time versus forecast-cutoff chronology; this primitive prediction function receives no event metadata.

Eligibility requires more than 10,000 distinct events, ten fixed probability buckets each containing at least 500 events, and both labels in each bucket. Threshold copies and simulation draws must not be presented as independent events. Keep method selection and locked later evaluation separate from fitting. Never independently calibrate every spread or category with this API.

## Dependencies and focused tests

Verified here: Python 3.12.14, NumPy 2.3.5, scikit-learn 1.8.0, and pytest. No new dependency is installed automatically and no claim is made about other version combinations. NumPy and scikit-learn are runtime imports; pytest is test-only. Review integration dependency pins before adopting the proposal.

From this directory:

```sh
python3 -m pytest test_binary_isotonic_repair.py -q
```

The five tests cover the minimal old-code failure, weighted sklearn parity, eligibility and duplicate rejection, chronology/hash rejection, base-model mismatch/missing identity, and JSON serialization replay. These are focused tests, not a full repository test pass or predictive calibration validation.

## Rollback and adoption boundary

Because no active caller is modified, reverting the proposal directory has no forecast effect. If a later approved integration is attempted, keep old/new artifacts separate, add explicit caller compatibility tests and model/event/cutoff binding, and preserve the previous registered path for rollback. Do not replace frozen historical forecasts, enable this mapping by default, or treat a merged research proposal as predictive approval.
