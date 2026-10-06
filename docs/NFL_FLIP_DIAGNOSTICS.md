# NFL base versus QB diagnostics

Implements the inference and reporting portion of [#55-A](https://github.com/georgemunoz1-ui/sports-model/issues/55). These observations do not select or suppress an arm, change a fitted probability, validate a forecast, or authorize action. The grading-time flip ledger and fixed-base challenger remain separate work.

`build_flip_diagnostics(bundle, arm_model_ids=None, gap_threshold_pp=10.0)` compares the already-computed `arms.base.prediction.home_win` and `arms.qb.prediction.home_win`. Each arm is independently fitted. Every strict, unrounded crossing of 0.5 emits `PICK_FLIP`, regardless of its size. Exactly 0.5 has no pick. `LARGE_PROBABILITY_GAP` is an independent magnitude flag; it never gates a flip.

Missing or invalid probabilities, missing source/model identities, contradictory arm metadata, and unsupported information regimes emit `NOT_COMPARABLE` with a null flip. The current scope is football-only `research_pregame`, with explicit `market_input=false`. Endpoint probabilities remain valid for pick comparison but have null logit differences. Cards display missing diagnostics explicitly.

The report includes home-oriented probabilities/picks, signed probability and logit differences, source identity/cutoff/artifact/code hashes, reporter hash, and original tags/warnings. A canonical-JSON source projection hash is explicitly distinguished from a raw-file hash. Contribution reporting separates signed QB terms from shared-feature coefficient redistribution and intercept changes. Absolute QB contribution share excludes the intercept from its denominator; incomplete, inconsistent or nonfinite traces are flagged without inventing contributions. These are fitted-term descriptions, not causal QB effects.

## Outputs

- `runtime.run` attaches `flip_diagnostics` after inference and simulation. Integrated CLI output includes the diagnostic.
- `persist_run` writes a separate `flip_diagnostics.json` covered by the run manifest and appends to the sibling `flip_diagnostics.jsonl` stream.
- Shared NFL cards retain the full report in JSON, add exact numeric CSV columns, render a base/QB comparison table, and write a separate diagnostic stream in the card output directory.
- Enhanced pregame forecasts retain the football diagnostic only under `football_reference`, with its original identity. It is not a diagnostic of the market-blended probability. Live mode is unsupported.

`append_flip_diagnostic(path, report)` locks and validates the complete hash chain before writing. An identical replay is a no-op; a conflicting identity, modified record or truncated chain is rejected. Write timestamps are actual observation times, never backdated forecast registration. This local chain supports integrity checks, not an external immutable anchor. It is separate from canonical grading/production ledgers.

Old forecast files are never migrated or rewritten. New code provenance legitimately changes future forecast identities and therefore identity-derived simulation seeds; this change does not claim bitwise draw equality across code versions. Within a saved forecast, diagnostics leave the prediction, draw arrays and simulation metadata intact. Reporter changes have their own source hash and diagnostic identity.

## Verification

`python -m unittest discover -s tests -p 'test_nfl*.py' -q` in the focused snapshot covers the new module/integration tests plus the existing context and week-2 suites. Regression cases include the small ATL-shaped flip, large same-side gaps, near-50% rounding, neutral/endpoints, orientation symmetry, missing/invalid arms and identities, unsupported scopes, warning/tag retention, contribution decomposition, no input mutation, actual writer time, idempotence, and corrupt/conflicting stream refusal. Integration tests exercise a pinned historical fixture, card JSON/CSV/Markdown, run sidecar/manifest/draw persistence, and enhanced-mode reference placement. These tests validate plumbing, not predictive performance.

Full repository CI and standing health are separate gates. This change does not clear existing RED release conditions or modify model defaults, evaluation results, frozen bytes or canonical ledgers.

**Research only; RELEASE RED; ACTION OFF; DOSE 0.0.**
