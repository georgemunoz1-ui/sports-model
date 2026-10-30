# Exact-contract candidate board and payout arithmetic

The October 30 research board was calculated in a session-specific script. The
repository now has an opt-in downstream command that consumes frozen PMFs and
explicit quotes, preserves their identities, and reports one probability-ranked
research candidate per event. It does not modify a forecasting model or activate
an existing candidate.

```bash
python3 scripts/build_research_candidate_board.py \
  --input retained_input.json --output new-candidate-board-directory
python3 -m pytest -q tests/test_settlement_risk.py tests/test_research_candidate_board.py
```

`pipelines/cards/candidate_board.py` documents the strict input schema. Supply an
event inventory, original discrete distributions with separate bindings, and
exact contract records. Each distribution binding includes event, league,
product, settlement, cutoff, parent-forecast hash, explicit orientation, and the
hash of the evidence used to establish that orientation. A supplied hash proves
consistency, not authenticity. Legacy artifacts are never edited or resealed to
insert missing provenance. Opposite-side prices must be supplied explicitly.
Multiple distributions for the same event/product/settlement are refused: an
upstream frozen procedure must choose the model, rather than this board choosing
whichever challenger reports the highest probability. Raw quote-term binding and
house-rule verification remain explicitly unverified even with complete book and
timestamp metadata.

The output retains all supplied contracts, selects one per event, and ranks
within each league by **unconditional full-win probability**. Pushes and voids
are not wins. Quarter-line half wins and half losses remain separate; positive
return probability is also displayed and is not silently substituted for the
ranking objective. Ties use the canonical contract identity, which excludes
price. Negative-EV candidates remain visible with a price warning. Missing
events receive `NO_SUPPORTED_CANDIDATE` instead of disappearing.

`models/common/settlement_risk.py` rejects boolean or nonfinite probabilities,
out-of-range mass, missing win/push/loss states, invalid American or decimal
odds, nonunit probability sums, and nonfinite payoff arithmetic. Its fixed mass
tolerance is `1e-12`, absolute only; accepted mass is not renormalized. It uses
the complete net-return map `(b, b/2, 0, -1/2, -1, 0)` for full win, half win,
push, half loss, loss and void. Variance uses the centered weighted second
moment; no negative or nonfinite variance is clamped to zero. Zero SD yields a
null standardized expected return with an explicit reason. Return SD describes
payout variability only, not model uncertainty.

The command was exercised on 16 original October 30 margin PMFs, 22 explicit
contracts, and a 17-event inventory. It reproduced the 16 displayed candidate
probabilities, EV, SD and league ranks, with maximum absolute numeric difference
`4.27e-14`; Harvard–Dartmouth remained unsupported. NBA supplied terms contain
only the ten reported candidate sides, so this is not a complete all-market
optimization. CFB uses the original 11:58Z quote snapshot and NHL uses the
retained 15:32Z snapshot. In particular, UCF's original `-112` price is different
from the later `-108` quote; changing that price changes EV, not probability.
See `settlement_execution.json` for source hashes, commands and per-event results.

## Closure status

| Issue | Status and evidence | Remaining dependency |
|---|---|---|
| Risk-score validation and stable variance | Implemented and exercised; adversarial and hand-calculated payoff fixtures | Other legacy arithmetic callers are not migrated by this change |
| Product/period/orientation/settlement binding | Implemented and exercised; mismatches rejected, original PMFs preserved | Provider authenticity and head correctness remain independently reviewed |
| Probability-first exact-line ranking | Implemented and exercised on 16 retained candidate contracts | Full opposing NBA quotes were not supplied |
| PMF tail quality and prediction reliability | Not assessed | Eligible later outcomes and registered matched evaluation |
| Current personnel, price freshness and eligibility | Not assessed | Source-bound current inputs and applicable independent qualification |

This is a numerical settlement replay, not production-runner replay or predictive
validation. All output remains research-only; publication is ineligible,
wagering is OFF, and allocation is zero.
