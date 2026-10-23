# Research overhaul: implementation and remaining work

## Current continuation — integrated build v2

The continuation is governed by [INTEGRATION_CONTRACT.md](INTEGRATION_CONTRACT.md).
PR76 is merged; [POSTMERGE_DELIVERY.md](POSTMERGE_DELIVERY.md) and
[POSTMERGE_RECEIPTS.json](POSTMERGE_RECEIPTS.json) record actual main-branch
execution, the storage inventory and the separate first-registration blocker.
Read [DELIVERY_RECONCILIATION.md](DELIVERY_RECONCILIATION.md) for the delivery state,
[CAPABILITY_RECONCILIATION_v2.md](CAPABILITY_RECONCILIATION_v2.md) for remaining work,
and [BLIND_VERIFICATION.md](BLIND_VERIFICATION.md) for independent verification.
The final local suite passed **1,101 tests**. The actual NFL CLI ran both retained
100,000-draw paths; the October 22 replay retained 80 exact opportunities and emitted
NO_PICK for all of them. No predictive validation or wagering approval was created.

New command-line forecasts use `market_blind_numeric.v2`; explicit legacy replay
retains old identities. Selection sidecars are attached at the real entry points,
with signed lineage/lifecycle and frozen-policy walk-forward evaluation available.
The new numerical identity, automatic sidecars and ancestry logic supersede the
corresponding unchanged/pending statements in the initial-build record below.

## Initial-build record — retained historical scope

Based on main `90daf8e0036c67a5304aa0747bf50b2266e0b364`. The user authorized
parallel validation and building across sports on 2026-10-23 UTC. This change adds
executable research infrastructure and repairs; it is not a new fitted probability
model, a predictive-validation certificate or permission to wager.

## Implemented

| Area | Executable path | Behavior |
|---|---|---|
| Selection | `pipelines/cards/research_selection.py` | Sealed raw forecasts; exact event/side/line/period/settlement; frozen threshold; three decision classes; independently hashed price diagnostics. |
| Registry | `research/validation_registry.py` | Content-addressed artifacts; external Ed25519 trust; signed authorship/preregistration/review; exact procedure/config/target; expiry and signed revocation. Empty trust blocks qualification. |
| Trial accounting | `research/validation_registry.py:TrialLog` | Locked append, inspected configurations, duplicate refusal, external-tip verification and conservative global counts. |
| Selection runner | `scripts/run_research_selection.py` | Strict manifest; input/code receipts; actual execution time; explicit historical replay; immutable output directory. |
| Evaluation | `scripts/evaluate_research_selections.py`, `research/selection_evaluation.py` | External full population, exact same-event controls, frozen procedure/config/family, blocked coverage, paired block bootstrap, explicit-trial-count Holm and declared-assumption power curves. |
| Card face | `pipelines/cards/integrity_reporting.py`, `scripts/generate_card_force.py` | Consumed-state dates/ages, numerical traces, comparable home-oriented head/distribution signs and NHL review class. Unknown evidence stays UNKNOWN. |
| Rest candidate | `models/current/freshness.py`, `scripts/build_operational_rest_candidate.py` | Source-bound all-played-game rest candidate; no silent substitution under legacy coefficients. |
| NBA acquisition | `scripts/nba_history_scope.py`, capture/preparation scripts | Explicit source-derived provider season, current-event binding and exact team-season request census. |

The card runner attaches state traces after the existing forecast runs. Code-pinned
model files/adapters, coefficients, RNG identity, defaults and frozen forecasts are
unchanged. A trace does not itself measure a causal effect or certify calibration.

## Fixed semantics

- The implemented objective is unconditional winning-settlement accuracy. WIN,
  LOSS, PUSH and VOID are distinct states. PUSH/VOID are resolved non-wins under
  this objective; decisive-only accuracy and refunded stakes are separate. LIVE
  and MISSING are ungraded.
- Raw probabilities remain visible. Without matching qualification/quality,
  selectable probability is null and the decision is BLOCKED. Otherwise the
  frozen threshold yields ELIGIBLE_NOT_SELECTED or SHADOW_SELECTED. Zero selections
  is valid. Confidence bands remain null until qualified definitions exist.
- Payout odds do not affect selection. Missing/invalid quotes produce null price
  diagnostics. A different spread/total line is a new target. Ordinary refundable
  push value is `p_win * (decimal_odds - 1) - p_loss`; break-even is explicitly
  decisive-outcome based. Unsupported fees/settlement maps are not approximated.
- Control direction compares complete WIN and LOSS mass, retaining the target
  side on an exact tie. It never applies 0.5 to unconditional win mass with pushes.
  Controls must exist before the decision and event start.
- Late/future-at-decision probabilities remain in source artifacts but are excluded
  from pregame scoring with reasons; blocked opportunities remain in coverage.
- Changed inputs/configuration produce new identities. Children do not inherit
  qualification. Historical replay retains actual execution time and cannot be
  relabeled prospective. Oct 21–22 remains discovery.

## Running it

```bash
python -m pip install -r requirements-consolidated.txt
python scripts/run_research_selection.py --help
python scripts/evaluate_research_selections.py --help
python scripts/build_operational_rest_candidate.py --help
python scripts/capture_team_histories.py --help
python scripts/prepare_initial_baselines.py --help
```

Selection input example (paths point to separately sealed JSON files):

```json
{"schema":"research-selection-manifest-v1","entries":[
  {"entry_id":"example","forecast":"forecast.json","config":"config.json",
   "quality_receipt":"quality.json"}
]}
```

```bash
python scripts/run_research_selection.py --manifest packet/selection.json --output-dir runs/new-selection
```

No registry is needed to preserve raw diagnostic output. For qualification, supply
manifest registry IDs plus `--registry-store` and `--trust-file`. No production
keys/approvals are supplied here. Positive tests use ephemeral keys and synthetic
TEST_ONLY evidence. `--decision-at-utc` marks a historical diagnostic, retaining
actual replay time; it is not a trusted timestamp witness.

Evaluation input example (SHA placeholders must be replaced with exact digests):

```json
{"schema":"research-selection-evaluation-input-v1","evidence_scope":"DISCOVERY",
 "population":{"path":"population.json","sha256":"EXACT_FILE_SHA256"},
 "decisions":{"path":"decisions.json","sha256":"EXACT_FILE_SHA256"},
 "outcomes":{"path":"outcomes.json","sha256":"EXACT_FILE_SHA256"},
 "controls":{"path":"controls.json","sha256":"EXACT_FILE_SHA256"}}
```

Population lists `event_id,target_id,slate_id`, including blocked opportunities.
Outcomes declare every population event, including MISSING, with exact target,
observation time and status. Resolved rows also have settlement time, source digest
and reference. Optional controls are sealed forecasts on identical targets. Help
text and executable tests contain the complete schemas.

```bash
python scripts/evaluate_research_selections.py --manifest packet/evaluation.json --output-dir runs/new-evaluation
```

The evaluator authenticates retained bytes and record identities, not the sports
results' truth. It accepts DISCOVERY/SHADOW, refuses unsupported CONFIRMATION,
writes a new evaluation plus completion receipt and edits no canonical ledger.

## Repair boundaries and remaining work

NHL rest uses embargoed form state in both training and inference. Updating only
inference would change feature semantics under old coefficients. The new rest
input therefore requires separate refitting and chronological evaluation. Regular-
season-only captures cannot certify all-played-game rest across preseason/playoffs.

NBA acquisition previously stopped at provider year 2026 in October 2026. The new
explicit scope reads season 2027 from captured metadata and validates the request
census. It does not invent games, current player state, minutes or fitted models.

`CAPABILITY_GAPS.md` and JSON inventory all seven sports and 20 gaps against pinned
main. Those historical findings are not marked solved by the existence of this
branch. Outstanding work includes:

1. NBA player/minutes/churn, NHL goalie/rest refit and OT/empty-net layers, NFL
   availability and contract certification, CFB residual opponent adjustment/total
   head, and the WNBA/MLB/MLS target-specific challengers.
2. Integrating overlapping distribution, roster, winner-identity and market-
   independence PRs. The main-path MI-002 RNG metadata leak remains open; these
   tests do not certify upstream market independence.
3. Deploying trusted registration/timestamps and independent reviewers. Keys do
   not establish distinct humans; hashes do not establish truth. Signed scientific
   evidence is an external trust boundary, not automatically recomputed proof.
4. Enforcing inherited trial exposure across procedure ancestry, externally
   anchoring logs, and deploying calibrated drift monitors. Undeclared trials and
   caller-renamed families cannot be discovered by the journal. Global counts
   offer a conservative alternative. Expiry/revocation exists; automatic drift
   detection does not.
5. Frozen chronological predictive comparisons and separate publication-readiness
   verification. No procedure is promoted by this change.

The theory review corrects universal optimality claims: price exclusion is a
policy with unknown accuracy cost; aggregate calibration is insufficient for
Bayes-optimality. Proposed universal sample floors/attempt caps were not silently
encoded. Each research protocol must justify its own evidence requirements.

## Verification

See `VALIDATION.md` for executed commands/counts and scope. The independent
`ADVERSARIAL_REVIEW.md` records repaired attacks. The focused workflow is
`.github/workflows/research-overhaul.yml`; consolidation also runs the full test
directory. Software acceptance is separate from operational repository health and
predictive accuracy evidence.
