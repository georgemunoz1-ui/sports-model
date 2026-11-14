# November 12, 2026 — cross-model postgame learning controls

**Scope:** eight-league opt-in evaluation layer; **not** eight fitted-model updates. New code is additive, research-only and non-authorizing. Frozen forecasts, prices, fitted weights, model default registry, release history and canonical grading are unchanged. This document records a **post-outcome** design: November 11 is development evidence, not its prospective confirmation.

## Source findings that motivated the implementation

The user-supplied November 11 bounded readback, *not* a canonical settlement-package replay, reported **19 preferred ML contracts at 14–5, 19 preferred spread/puck contracts at 12–7, 26–12 across 38 correlated contracts on 19 games**, and +5.62901 hypothetical units at frozen prices. Binary Brier was ML **0.178785 vs simulation 0.179004**, spread/puck **0.240359 vs simulation 0.240788**, combined **0.209572 vs simulation 0.209896**. A full-precision pregame readback gave mean absolute Sim–Model deviation **0.125916 percentage points**; replication accuracy is not independent predictive evidence.

The nine preferred MLs with positive model EV went **5–4, −0.93558 units**; the seven also restricted to model win probability ≥60% went **5–2, +1.06442 units**. These are *retrospective* screens. A two-flip substitution (Sacramento State +675, Toronto +200) finished 12–7, −0.76401u versus 14–5, +1.74275u for all preferred MLs, but this was **not** a complete EV-first strategy test. A named 8-contract balance cohort went 6–2 across six games; its 60/40 score had **no independently verified pregame procedure receipt**. Do not use it as a validated selector.

The four unpriced CBB ≥90% underdog threshold cases went **2–2 versus 3.6986 expected covers**, full-precision Brier **0.443454** (small sample). Retain this extreme-tail population and all lower-confidence counterparts rather than tuning a cap or fading it after seeing outcomes. In the New Orleans–Brooklyn case, the retained bulletin had **Trey Murphy III PROBABLE**, while he subsequently did not play; the forecast did not numerically consume that injury source. The transition time relative to the original arm cutoffs is **unresolved**. A first-quarter Curry exit is not a pregame input.

## Eight-sport evaluation applicability

| League | Product- and feature-specific review; no automatic numerical update |
|---|---|
| NFL | Starter identity, final actives vs point-in-time roster status, report missingness support, selected QB vs independent margin arm, push and OT conventions |
| CFB | FBS population/season chronology, winner vs spread-PMF calibration, whole-number push mass; selected total head absent unless an independently fitted arm is actually supplied |
| NBA | Player-status publication vs ingestion vs **numerical use**, fitted-state history policy, winner vs point-margin/total arm separation, same-event matched Brier against prices |
| WNBA | Winner/cover/total scope and regular season vs postseason, verified rotation states before start |
| MLB | Starter/bullpen/lineup source chronology, extra-innings settlement, winner-only support vs run-line/total/props, preserving all V11/V13 historic verdicts |
| NHL | Confirmed goalie as of cutoff, puck-line vs win probability mismatch, OT/shootout plus-one score rules, separate joint-volatility shadow arm |
| MLS | Regulation 1X2 HOME/DRAW/AWAY law and **three-class Brier**, not an NBA/NHL-style binary moneyline; regulation versus extra time and quarter-lines |
| CBB | Verified D1 pair identity, opponent-adjusted point centers, residual-scale challenger, high-confidence underdog tails and calibration by market handicap |

The software cannot decide an arm supports a product merely because a league traditionally has a market. Each row must explicitly declare its own `model_id`, `arm_id`, `product_supported` status, temporal identity and native settlement.

## Implemented in the opt-in auditor

- `research/nov11_cross_model/cross_model_learning_review.py`: validated odds and outcome masses; group-separated Brier scores; signed Sim–Model replication gap and optional Monte Carlo SE; two-sided same-event/period/provider/line matching for no-vig comparisons; push-aware three-class scoring and decisive conditional comparisons; MLA binary and MLS regulation 1X2 properly separated; no-action output; prospective source timestamps left **unverified** unless a separate trusted attestor exists; source-state monitoring without fabricated fitted effects.
- `scripts/review_cross_model_findings.py`: explicit input JSON to read-only research JSON. Does not import or mutate league model weights, write the canonical registry, create forecasts or authorize stakes. It may write to an explicitly requested **research** file only.
- `tests/test_cross_model_learning_review.py`: standard-library tests spanning eight-league review contracts, source clocks, exact quote joins, integer pushes, MLS draws, refusal of an incomplete two-price MLS 1X2 market, CBB tails, missing personnel, side preference and zero authorization.

**Interface:**

```bash
python -m unittest discover -s tests -p test_cross_model_learning_review.py -v
python scripts/review_cross_model_findings.py --input examples/cross_model_learning_synthetic.json
```

Example payloads are deliberately **synthetic and outcome-free** and do not demonstrate real coverage. The runner is not wired into production card generation or canonical grading. The evaluation layer cannot independently authenticate a supplied hash/timestamp or infer a fitted personnel adjustment.

## Forward experimental design (not yet registered)

The model-optimal side, EV-optimal side, price-qualified abstention and 60/40 blend are *different procedures*. If desired, pre-register separately on a future untouched slate before event start, including exact event and quote IDs, candidate population, normalization, tie handling, odds/settlement, gate behavior and event dependence. Test the preferred-side/price rule against a fully specified two-sided shadow EV selector on matched quote vintages. Use appropriate multi-game/temporal uncertainty, not simulated-draw counts or duplicated game contracts as independent samples.

**Cross-league predictive promotion is not permitted by this patch.** Do not merge a challenger, change fitted parameters, apply a universal probability threshold, or change wagering settings because of one positive slate. Compare each league/model/product to the matched market and an earlier-only reference with Brier/log loss and recorded missingness. If a personnel transition or authenticated quote vintage cannot be established, retain an unavailable result.

## Integration dependencies

`main` remains older than research draft PRs #95, #98, #102, #105, #108 and #111–#118. In particular, #117 (cross-model missingness), #118 (registered research) and #102 (daily pipeline) are not equivalent to a production release. This additive research adapter should be reviewed for integration with their *actual* APIs only after the branches converge, with a verified complete checkout and CI. Avoid claiming a locally isolated test run is the repository-wide healthcheck. All original model defaults and wagering authority remain unchanged.

## Coordinated eight-league disposition and exposure follow-up

The follow-up deliberately does **not** claim fitted or deployed changes in all
league models. The machine-readable file
`data/research/nov11_cross_model_dispositions_v1.json` names one unchanged
baseline and one blocked/proposed shadow workstream per league. Each entry has a
pinned source-branch code commit, missing fitted-state/input identities recorded
as null, unverified eligible training data, unresolved release dependencies and a
separate product-specific action queue. `research/nov11_cross_model/model_disposition_review.py`
refuses a false training, registration, release or authority claim.

`research/nov11_cross_model/event_exposure_shadow.py` implements source-law-gated, **same-event**
reference exposure. Its classification distinguishes nested moneyline/spread
stacks from opposing middle-window contracts by common winning settlement
scenarios. It refuses incomplete/unsupported settlement tables, contradictory
event identities, invalid probability masses and live authority. If a coherent
joint score/scenario law is absent, event EV, volatility and pair structure are
**NULL/UNASSESSED** rather than manufactured from independent marginal legs.
The multi-event book does not compute an SD or optimize an allocation unless
an independently supported *cross-event* joint law exists (not provided here).

New read-only commands:

```bash
python scripts/validate_model_dispositions.py
python scripts/review_event_exposure_shadow.py --input examples/event_exposure_shadow_synthetic.json
python -m unittest discover -s tests -p 'test_*.py' -q
```

Synthetic scenario probabilities are for verifying correlation accounting, not
sports prediction. These modules are **not** wired to the old or new daily
card generators. Each prospective numerical challenger still needs its exact
fitted parent and input hash, chronology-consistent labels and independent
forward evaluation. Existing draft PRs and protected integrations remain separate.

## Protected module manifest reconciliation

The initial draft added a module under `harness/`, which failed its module
registry health test. A subsequent attempt to register it changed
`data/registry/module_manifest.json`, a protected file that cannot be modified
by this research PR. The resolved approach is an **isolated**
`research/nov11_cross_model/` package. It is not imported by any production
runner or protected harness module. The old module manifest is preserved
**byte-for-byte**, so neither module registration rules nor protected-file
checks are weakened.
