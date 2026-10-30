# NHL context and score-semantics controls — October 30, 2026

The new opt-in sidecar preserves the current forecast and exposes independently
checked goalie/rest input states. It does not replace the frozen NHL fit.

`research.nhl_context.shadow_from_card(card_path, config_path, output)` is the
shared-runner hook. `scripts/run_nhl_context.py` exposes the same API by CLI.
Configuration schema `sports.nhl_context_config.v1` requires `action_authority:
false` and `package: {path, sha256}`. Optional `rest_history` and `goalie_capture`
references use the same exact-file binding. The goalie observation freshness
policy is six hours by default; `max_goalie_age_hours` can make that policy
explicit. A new configuration gets a new identity. Output is create-only.

The existing operational-rest builder is reused without changing its feature
semantics or legacy coefficients. It retains the training/serving distinction
and independent golden-value checks. No operational-rest refit is invented.

Goalie source statuses are `CONFIRMED`, `PROJECTED`, or `UNKNOWN`. The loader
reads report fields from digest-verified raw normalized JSON, never from a
packet-level claim. Old observations remain stale after a later retrieval;
conflicting player IDs remain unknown. Provider authentication and parser
validation are separate from byte binding. The current adapter is explicitly
for upstream normalized sources; it is not an official NHL HTML scraper.
A reported starter does not create a fitted effect or mixture weight.

`models.nhl.context_controls.settlement_scores` checks regulation and final
scores under the existing named `FULL_GAME_OT_SO_PLUS_ONE` contract. OT/SO
requires tied regulation scores and exactly one added winning goal. It rejects
aggregate shootout attempts, tied finals, boolean/nonfinite/noninteger scores,
unknown finish types and other bookmaker contracts. This is an observed-score
semantic validator, not a mechanistic overtime distribution or a claim of
settlement-provider authentication. The validator is available to outcome
intake; it does not alter existing grading records.

## Exercised scope

- 44 tests pass: NHL context controls, independent rest golden vectors and the
  shared discrete-product regressions. Synthetic tests are software evidence.
- Actual retained October 30 NHL card: three events processed with exact parent
  package/state/event binding. All goalie/rest adjustment eligibility remains
  blocked. No new probabilities or forecasts were generated.
- Existing archived A5 source packet reexecuted: five events, four complete
  successor feature vectors and one unknown. Legacy rest was 14 days; ready
  successor features span approximately 8.04–10.08 start-to-start days. These are
  historical feature reconstructions at the recorded cutoff, not actual
  later-start physical rest measurements or predictive evidence.
- Default registry, frozen kernels, fitted states, original cards and allocation
  authority remain unchanged. Wagering remains OFF.

## Closure register

| Issue | Implemented control | Remaining evidence |
|---|---|---|
| NHL goalie ambiguity | Raw-record binding, explicit status/conflict/freshness checks | Authenticated pre-cutoff starter captures plus player history and a chronologically fitted/evaluated effect |
| Legacy rest construction | Reused existing separate successor feature builders and reexecuted retained sources | Complete all-played-game as-of history, successor refit, matched later-event evaluation |
| OT/SO contract ambiguity | Independent regulation/final score fixtures and strict semantic mapper | Source-bound final-score parser integration and separate full-score distribution evaluation |
| Research context hidden in notes | Immutable per-event sidecar with input eligibility and NOT_USED label | Optional shared-card invocation and real source configuration; no claim of scheduled deployment |

The retained-card run is diagnostic; it is not production-runner numerical
replay, PIT certification, predictive qualification or model activation.
