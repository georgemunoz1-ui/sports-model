# MC-engine lineage archive (parallel session tree)

**Date:** 2026-08-30
**Origin tree:** `/mnt/agents/output/project` (Kimi session family) — master @ `5c1256c`,
P0 branch `freshness-p0` @ `3dcd502`. This tree shares no commits with
`sportsmodel/main`; it was built in a separate sandbox checkout.

## Why this archive exists

Two lineages of this project evolved in parallel during 2026-08-29/30 and both
independently fixed the same two P0 freshness holes on 2026-08-30:

| | This tree (`freshness-p0`) | codex/p0-freshness-health-20260830 (PR #4) |
|---|---|---|
| H1 starter identity vs rates | `Stamp.confirms_identity=False`; starter-slot reads capped at IDENTIFIED_UNCONFIRMED (0.75 fresh / 0.50 degraded) | game logs downgraded to `POST_HOC_NOT_PREGAME` + exact normalized full-name identity match (never `people[0]`) |
| H2 stale rates into V13 | `MLBV13Component._gate_starter` reroutes non-fresh/confirmed slots to league-default `_sp({})`, reroute in `provenance["starter_routing"]` | `build_board_0825.starter()` CAPs stale/non-pregame evidence to `V13._sp({})`, stale observation retained in disposition |
| Tests | 27 new (11 mutants, HOU@NYM 40-day regression, acquisition identity/grade); suite 174 -> 201, verified 7/7 by an independent verifier incl. mutant reversion | test_starter_freshness_regression.py + selftests; reported 23/23 targeted, 171/174 in a pyarrow-stub env |

The codex branch additionally separates fallback forecasts from action eligibility
(fail-closed wins over "every rung stays bettable") and binds the health dashboard
to a machine-readable patch registry. Its exact-name identity binding closes a hole
this tree's fix does not; port it if the trees ever merge.

## What is archived here

- `harness/mc_engine.py` — governed multi-sport Monte Carlo (30k trials, 10 keyed-seed
  blocks, 3-sigma convergence gate that RAISES, logit-scale dose-weighted ensemble,
  proportional de-vig firewalled to the valuation layer, MLB Poisson lambda solve
  seeded by Skellam and verified in MC). Frozen constants carry owner rulings:
  CFB_MARGIN_SD=16.64 (MAE 13.279 x sqrt(pi/2)), WNBA 13.97 = coherence tolerance
  only, WNBA_COVER_SD=12.53 measured + 14.91 alt, NFL priors declared but gated off.
- `harness/mc_components.py` — market-independent arms as components: WNBA ff7 (real
  wnba_model_v1 + governed ESPN extension), MLB CHAMPION_V13 (real
  run_v13_historical.py wired; interim arm superseded behind a flag), CFB house arm
  (live or frozen-board rungs), NFLComponent structural refusal. Signature-level
  market firewall + output-field validation.
- `harness/CARD_UPDATE_PROTOCOL.md` — standing owner directive: "update card" means
  an ALL-sports sweep (results, lines, audit clause, scoring, hypothesis watch).
- `tests/test_freshness_p0.py` — the P0 regression + 11-mutant suite (27 tests).

## Not archived (exists in both lineages in different forms)

`freshness_contract.py`, `acquisition.py`, `board_freshness.py` — each lineage has
its own; this tree's versions add `confirms_identity` and `_starter_effective_grade`.
Also in the origin tree: tests/test_mc_engine.py (23), tests/test_mc_components.py
(20), tests/test_arm_restore.py (15), tests/test_v13_wiring.py (12),
tests/test_mlb_reference_rates.py (4) — regenerable from the origin tree on request.

## Status

Origin tree suite: **201 passed** (174 on master + 27 on freshness-p0), real pyarrow.
The codex session's "171/174" was its stub environment, not a code defect.
The 8/29 slate builder on freshness-p0 exits 1 with CONVERGENCE_FAIL refusals on
HOU@NYM and COL@ATL — intended fail-loud consequence of withholding 40-day-old
starter rates from V13.
