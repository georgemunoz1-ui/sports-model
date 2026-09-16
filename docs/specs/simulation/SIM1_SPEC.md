# SIM-1 — Monte Carlo simulation layer: distilled engineering spec

**Status:** SPEC ONLY (docs-only PR; nothing implemented). **Tiering:** SIM-1a/1b = P1, SIM-1c/1d = P2, SIM-1e = P2/backlog.
**Corpus (owner Addendum 7, ingested verbatim, append-only reference):**

| File | Content |
|---|---|
| `mc_design_principles.md` | uncertainty/dependencies/game-states/data-availability; correlated game-state sampling; distribution selection; convergence checks; scenario-based EV; decision-state record fields |
| `inplay_realtime_mc.md` | conditional remainder simulation, adaptive sim counts, vectorization, caching, variance reduction, latency budgets, in-play fail-closed controls |
| `qmc_vs_stratified.md` | QMC vs stratified tradeoffs; hybrid stratified-outer / scrambled-Sobol-inner design; Neyman allocation; convergence/stopping rules |
| `stratification_boundaries_nfl_nba.md` | time×margin×possession buckets; OT as a separate ruleset branch; hierarchical sparse-state fallback |
| `all_sports_state_modules.md` | universal canonical event state + sport-specific modules (NFL/NBA/WNBA/MLB/NHL/soccer/tennis/golf/esports); adaptive boundaries |

## Current state (what this spec is framed against)

- **mc_engine local lineage:** `TRIALS=30000`, `BLOCKS=10`, `CONVERGENCE_SIGMAS=3.0`; the ported gate `MC_CONVERGENCE_TOL_PP=2.7386pp` (worst-case p=0.5, derived not tuned) merged via PR #5 (`harness/mc_convergence.py`), bound into the forecastable/actionable gate: CONVERGENCE_FAIL demotes to `REGISTERED_FALLBACK_ONLY`, never promotes.
- **WNBA shadow model:** margin SD 13.97 (coherence-only provenance).
- **GSV@POR scenario engine:** done BY HAND on the 8/30 V3 card — the exact thing SIM-1a formalizes.
- **Calibration layer:** shipped DORMANT in PR #7 (sample-size gate; WNBA bound Tier-1 base is n=4).
- **Causal rules:** Addendum 3 (PR #7 `backtest_causal`) — residual pools, correlations, and boundaries below inherit them.
- **Frozen σ provenance:** CFB 18.385 Week-1; WNBA 13.97 coherence-only. Comparisons against these are allowed; silent replacement is not.

**Governance invariant (explicit):** nothing in SIM-1 changes `TRIALS`, `BLOCKS`, `CONVERGENCE_SIGMAS`, or `MC_CONVERGENCE_TOL_PP` without an owner-gated candidate config (the `p3_candidate_config` pattern: proposed, hashed, evaluated beside the frozen default, promoted only by owner decision).

---

## SIM-1a (P1) — scenario engine formalization

Formalize what the 8/30 V3 card did by hand.

- Stratified **discrete** scenarios wrapping the existing margin simulation: player availability `{active, starter, limited, out}` with probabilities; game-script strata `{close, home leads, away leads, blowout, OT}` conditional on lineup (nested hierarchy, per `qmc_vs_stratified.md` — do not explode the Cartesian product).
- Per-scenario EV; aggregate `E[EV] = Σ_s P(s)·EV_s`; **record worst-case and lower-percentile EV** — a positive mean EV that goes strongly negative in a plausible scenario reduces stake or flips to no-bet (per `mc_design_principles.md` §Scenario-based betting).
- **Hybrid sampling:** stratified outer layer over discrete scenarios + scrambled-Sobol inner layer for continuous factors (pace, efficiency, residuals).
- **Neyman allocation** `n_h ∝ w_h·σ_h` after a 1,000-path-per-stratum pilot; decision-critical strata get budget regardless of weight.
- Common random numbers across scenarios being compared (lineup A vs B, ±0.5pt line).
- Acceptance: a replay of the hand-built GSV@POR V3 scenario set reproduces its recorded EV table within MC error, with the scenario distribution stored.

## SIM-1b (P1) — decision-state record on every sim output

Every simulation output carries (aligning with the decision-state format already used on the 8/30 V3 card):

```text
raw_model_probability
calibrated_probability          # raw until the dormant calibration gate opens (PR #7)
no_vig_market_probability       # from the PR #7 market layer; valuation-only
expected_value                  # at the entry price at decision_time, never the close
simulation_seed
simulation_count
scenario_distribution
mc_standard_error               # SE = sqrt(p(1-p)/N)
```

Model probabilities and market prices stay separate column families (PR #7 governance); EV is computed at the price available at the simulated decision time.

## SIM-1c (P2) — adaptive stopping rule (config-gated ALTERNATIVE, never a silent constant change)

- Proposed as a **candidate config** beside frozen `TRIALS=30000`, exactly like `p3_candidate_config`: hashed, registered, evaluated in parallel; frozen defaults stay frozen pending the owner gate.
- Stopping condition (both required): `SE < target` AND bet/no-bet decision stable across **8–16 randomized (scrambled) replicates** (`qmc_vs_stratified.md` §Operational stopping rule; `inplay_realtime_mc.md` §2).
- Fragile decisions (model prob within a named band of the market threshold) escalate budget or classify `uncertain` — they never silently accept the first batch.

## SIM-1d (P2) — distribution upgrades

- Empirical residual simulation grouped by context: minutes bucket, role, opponent, pace, home/away (`mc_design_principles.md` §4).
- Student-t / heavy-tail check vs normal margins, compared against the frozen σ provenance (CFB 18.385 Week-1, WNBA 13.97 coherence-only) — reported as a comparison, adopted only via owner gate.
- Residual pools built **walk-forward only**: only residuals available before the simulated date; Addendum 3 causal rules apply (PointInTime store, purge/embargo, no backfill).

## SIM-1e (P2/backlog) — canonical live-state schema + sport adapters + correlation generator

The long-term architecture (`all_sports_state_modules.md`, `stratification_boundaries_nfl_nba.md`):

- Canonical event state (sport/league/season/ruleset_version/event_id/phase/time/score/possession/personnel/ruleset/market_type/regulation_or_overtime/timestamps) + per-sport adapters (NFL down/distance/yard-line; NBA/WNBA fouls/bonus/lineup; MLB base/out/count Markov state; NHL manpower; etc.).
- OT as a separate `ruleset_state` branch per sport, never blended into regulation strata; ruleset_version stored with historical games.
- Correlated game generator with shared latent factors (`pace_factor`, efficiency factors, usage redistribution) — player outcomes sampled conditional on game state.
- **Explicit scope note:** our current engine samples *margins*, not game states. Player-prop correlation is out of scope until state modules exist; SIM-1e is architecture, not a near-term PR.
- Hierarchical sparse-state fallback (exact → phase+nearby → possession/manpower → league baseline), minimum unique-GAMES per stratum (snapshots ≠ independent games).

## In-play failure controls (cross-reference)

The corpus's in-play no-output conditions (stale clock/score, disagreeing feeds, uncertain event identity, market suspended, SE above threshold) map onto existing machinery: the P0 `dq_gate` in PR #7 (`market_quality`: STALE_QUOTE, SUSPENDED_MARKET, DUPLICATE_EVENT, timestamp-ordering) and the mc_convergence demotion gate (PR #5). SIM-1's in-play work consumes those gates rather than inventing parallel ones.

## Sequencing

SIM-1a + 1b first (formalizes proven hand work; record format already in use). SIM-1c/1d as gated candidates once 1a/1b land. SIM-1e is the multi-PR architecture track.
