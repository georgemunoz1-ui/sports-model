# NBA efficiency direction shadow v1.1

This opt-in research copy corrects defensive-rating direction when ratings mean points allowed per 100 possessions. A larger opponent defensive rating increases expected scoring. The unchanged `models/nba/efficiency_monte_carlo_v1.py` and selected `pipelines/cards/adapters/nba.py` remain frozen; the selected card adapter uses the initial causal-score model, not either efficiency engine.

Run only with explicit supplied state and snapshot:

```
python scripts/run_nba_efficiency_shadow.py --allow-research \
  --snapshot snapshot.json --model-state fitted-state.json --output unique-shadow.json
```

Default count is 100,000; the inherited engine API supports a minimum 50,000. Snapshot must explicitly declare `defensive_rating_semantics: POINTS_ALLOWED_PER_100_POSSESSIONS` and both availability adjustments. State must contain all fitted parameters with `fit_required: false`. The repository supplies no fitted candidate state or inferred injury effect. Numeric synthetic test values are not fitted parameters.

Identity is `nba.efficiency_monte_carlo.v1_1.defense_direction_fix.shadow`, version `1.1.0`. Its versioned seed differs from the legacy engine; legacy seed/draw bytes are untouched. This engine retains its own inherited RNG and does not silently switch to the separate semantic-stream MC monitor. Inputs, state and result are hashed. CLI outputs are exclusive-create and labeled research-only, canonical-ineligible, action-authority false.

The inherited random one-point tie-break is a diagnostic settlement shortcut, not a fitted overtime model. Direction tests, API compatibility and replay checks do not establish predictive accuracy, calibration, point-in-time source validity, or promotion. The CLI does not acquire or certify current sports inputs; callers own authentic provenance and fitting evidence.
