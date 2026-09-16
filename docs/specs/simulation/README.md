# Simulation methodology corpus (owner Addendum 7)

The five `.md` files in this directory are **owner-uploaded methodology documents, ingested
VERBATIM** (2026-08-30) as an append-only reference corpus. They are specifications and
design guidance — not implementations, and not evidence. Edit them only by owner instruction.

| File | Source upload | Content |
|---|---|---|
| `mc_design_principles.md` | `...A good sports Monte.txt` | uncertainty/dependencies/game-states/data-availability; correlated game-state sampling; distribution selection; convergence checks; scenario-based EV; decision-state record fields |
| `inplay_realtime_mc.md` | `...For real-time in-pla.txt` | conditional remainder simulation, adaptive sim counts, vectorization, caching, variance reduction, latency budgets, in-play fail-closed controls |
| `qmc_vs_stratified.md` | `...For sports simulatio.txt` | QMC vs stratified tradeoffs; hybrid stratified-outer / scrambled-Sobol-inner; Neyman allocation; convergence/stopping rules |
| `stratification_boundaries_nfl_nba.md` | `...For a first producti.txt` | time×margin×possession buckets; OT as separate ruleset branch; hierarchical sparse-state fallback |
| `all_sports_state_modules.md` | `...For all major sports.txt` | universal canonical event state + sport-specific modules (NFL/NBA/WNBA/MLB/NHL/soccer/tennis/golf/esports); adaptive boundaries |

`SIM1_SPEC.md` is the distilled engineering spec cross-referencing the corpus against the
current repo state, tiered SIM-1a/1b (P1) → SIM-1c/1d (P2) → SIM-1e (P2/backlog).

Note: uploads carried CRLF line endings; the corpus stores LF per repo convention. Content
is otherwise byte-identical to the uploads.
