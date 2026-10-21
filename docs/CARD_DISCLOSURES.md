# Card input, scenario and dependence disclosures

These presentation features explain research forecasts without changing model
means, probabilities, selected defaults, prices, registration eligibility or action
authority. They apply to all seven shared-card leagues and the separate NFL
pregame runner. Live NFL is outside this disclosure interface.

## Operating paths

New `scripts/generate_card_force.py` runs automatically write
`disclosures/disclosures.json` and `disclosures/disclosures.md`; the Markdown card
includes the same disclosures. New `scripts/run_nfl_integrated.py` pregame runs
write those files beneath each event directory and print their contents. Both
accept an optional `--disclosures packet.json`. The NFL packet path requires a
single `--event-id` so no event's evidence can be silently dropped.

For an existing frozen shared card, create a separate immutable directory:

```sh
python scripts/render_card_disclosures.py --card frozen/diagnostic_card.json \
  --disclosures packet.json --output new-disclosure-report
```

The original JSON card and draw files are never rewritten. Each sidecar binds the
canonical parent JSON hash and packet hash, and has its own content hash. Output
directories must be new. A malformed top-level packet fails; invalid per-event or
parlay evidence is recorded with a reason, independent events continue, and the
CLI returns exit 2. Never describe PARTIAL as complete acceptance.

## Unknowns, assumptions and conditional availability

Minimal packet (replace illustrative identities and hashes with actual evidence):

```json
{
  "schema": "sports.card_disclosures.input.v1",
  "action_authority": false,
  "events": [{
    "event_id": "EVENT_ID",
    "parent_model_id": "EXACT_PARENT_MODEL_ID",
    "parent_input_sha256": "64_HEX_CHARACTERS_FROM_PARENT_INPUT_SNAPSHOT_HASH",
    "known_inputs": [],
    "unknown_inputs": [{"name": "final_availability", "reason": "Final report not captured."}],
    "assumptions": [{"name": "rotation", "value": "starter plays", "rationale": "Conditional case only."}],
    "availability_scenarios": [{
      "scenario_id": "starter_out",
      "conditions": [{"entity_id": "SPORT_SCOPED_PLAYER_ID", "availability": "OUT"}],
      "rationale": "Availability unresolved."
    }],
    "pass_reasons": [{"code": "METHOD_INSTABILITY", "detail": "Named methods disagree.", "evidence_ref": "frozen-study-reference"}]
  }],
  "parlays": []
}
```

Known inputs require `name`, non-null `value`, source SHA-256, `observed_at_utc`
and `retrieved_at_utc`, ordered before the parent cutoff. Optional `input_path`
is a list of mapping keys into `model_input_snapshot`; an exact value match proves
input binding, not numerical consumption. Hash and timestamp checks are not
provider authentication. Assumptions require a value and rationale; unknowns
require a reason. One name cannot occupy conflicting knowledge states.

Scenarios have unique IDs and unique entity conditions (`IN` or `OUT`). Missing
forecasts stay `NOT_RUN`; no probability or impact is invented. This layer rejects
weights and probabilities of playing. It neither averages scenario outputs nor
modifies the existing separately fitted availability-mixture path.

An optional `distribution_artifact: {"path": "relative.json", "sha256": "..."}`
can reference an existing `sports.discrete_distribution.research.v1` artifact.
Its hash and full distribution contract are checked. Provenance must bind
`event_id`, `cutoff`, `parent_model_id`, `base_input_sha256`, `scenario_id`, and
`scenario_conditions_sha256` (the canonical digest of the conditions list).
The resulting conditional mean remains research, not validated injury impact.
This interface packages existing scenario forecasts; it does not fit a new
availability model or infer effects from a roster listing.

PASS is the wagering disposition. Automatic reasons disclose authority OFF,
market value not evaluated by this layer, predictive qualification not assessed
by this layer, parent warnings and unweighted scenarios. Supplied additional
reasons require an evidence reference and remain explicitly supplied/unverified.
There is no new edge threshold, confidence cap, wager selector or go-live gate.

## Dependence and redundant parlay legs

Each parlay has `parlay_id` and `legs`. Each leg declares `leg_id`, `event_id`,
`model_id`, `league`, `product` (`margin` or `total`), `settlement`, `side` and
`line`. Margin orientation is home minus away; its line is the home handicap.
An AWAY selection uses that same home-oriented line, not the away team's displayed
handicap. League settlement and side/line checks reuse the existing contract.

Full-win threshold nesting identifies redundant legs within the exact same
event/model/product/settlement. Example: Over 27.5, Under 75.5, Over 30.5,
home +20.5, Under 72.5 have five nominal legs and three retained constraints;
Over 27.5 and Under 75.5 are implied. Duplicates have deterministic representatives.
Contradictory integer thresholds are detected. The count is explicitly scoped to
this reduction; no general proof of cross-variable logical independence is made.
Player props and sportsbook-specific void/payout rules are not implemented.

`reported_joint_probability` requires `report_source_sha256` and remains
`REPORTED_NOT_REPLAYED`. It is never used as a verified recommendation. Optional
`joint_draw_artifact: {"path": "joint.json", "sha256": "..."}` permits arithmetic
recomputation, with this artifact schema:

- `schema: sports.joint_draw_disclosure.research.v1`
- `joint_model_id`, `joint_model_sha256`, `dependence_assumption`, `draw_count`
- `cutoff`, identical to the card's as-of cutoff
- `parent_bindings`: event ID to `{model_id, input_snapshot_hash}`, exact coverage
- `variables`: each contains `binding` with the leg's event/model/league/product/
  settlement, `variable_id` equal to its canonical digest, and integer `values`
  of exactly `draw_count` elements. One row across variables declares one joint
  sample; independently generated arrays must not be zipped together.

Every variable, hash, parent binding, count and settlement is checked. Paired
margin/total rows must map to nonnegative integer scores; two variables naming
the same physical outcome must agree even when model IDs differ. Probability
is the fraction of joint rows where all legs fully win. MLS quarter-line half wins
and ordinary pushes do not count as full wins. This is an unconditional intersection,
not a payout distribution or a push-adjusted parlay price. The marginal product is
shown only as an independence diagnostic alongside the actual sample intersection.
A reported probability must match the retained intersection within 0.0000005.

Arithmetic recomputation is labeled `RECOMPUTED_FROM_SUPPLIED_JOINT_DRAWS`.
Sampler replay stays `NOT_PERFORMED`; predictive validation stays
`NOT_ESTABLISHED`. A hash or caller flag cannot upgrade either status. A declaration
of dependence is not proof of a fitted joint law. Actual odds, sportsbook acceptance
and expected value remain unavailable. Wagering authority stays OFF.

## Acceptance scope

Regression tests cover all-seven shared runner integration, the separate NFL
runner, unchanged parent probabilities, identity/timing/hash failures, invalid
knowledge states, fabricated weights, conditional artifacts, nested/duplicate/
contradictory legs, MLS quarter-line full wins, joint support/count mismatch,
reported-versus-recomputed mismatch, and immutable output. These are software and
reporting checks; no predictive or market-superiority claim follows.
