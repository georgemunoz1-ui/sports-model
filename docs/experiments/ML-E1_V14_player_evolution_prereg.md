# ML-E1 PLAYER EVOLUTION V1 + V14 PERSONALIZED CONTEXT MODEL · PRE-REGISTRATION

**Status: SHADOW DEVELOPMENT PROGRAM, owner-directed 2026-07-28.** Runs in parallel with
Phase 4 and **must not touch it**: no change to frozen `d_logistic_2f` (cfg `132523ac…`), V13,
`ml_p4_forward.py`, gates, ledgers, selectors, or any existing forecast. Queue-policy note: the
single-ACTIVE-experiment rule refers to model-changing experiments against production paths;
this program changes no production model and was explicitly owner-authorized to run alongside
ML-P4-FORWARD.

## Objective

Replace the uniform league-average regression destination with an **individualized
skill-evolution model**: regression is retained as uncertainty control, but each player's
shrinkage destination is an individualized prior (history, age, level, role, comparables), not
the league mean.

Formulation (owner-specified, fixed):

```
future skill = player posterior + age-curve adjustment + reliability-shrunk individual trend
```

applied in log-odds space over **mutually exclusive PA/BF events** — `K, BB_HBP, HR, 1B, 2B,
3B, OTHER_OUT` — via a Dirichlet-multinomial posterior and a softmax back-transform, so
projected probabilities always sum to exactly 1. Recency-weighted counts + κ·π prior; log-odds
relative to `OTHER_OUT`; `Δ_age` from learned aging curves; `r_i·Δ_trend` with the individual
trend defined as the **residual after removing the population age curve** (double-counting
guard: the engine takes them as separate inputs and the training procedure must estimate the
trend on age-detrended changes only).

## Model identities

- `ML-E1-PLAYER-EVOLUTION-V1` = **SHADOW_ACTIVE** (development program status).
- `ml.v14.player_context.shadow.v1` and `k.xk_stuff.shadow.v1`: **NOT registered yet.** Per the
  standing rule, a model identity is registered — complete source/config hash — immediately
  before its **first shadow forecast**, and neither model can produce one today (see the data
  gate). Registering an identity for a model that cannot run would be a fiction.

## A. Hitter projections (ML-E1)

Empirical-Bayes per player: multi-year history with season decay `d`; opportunities as
reliability; individualized prior π (age, level, position/role, comparables) with strength κ;
learned **skill-specific** aging curves (power, contact, K-avoidance, BB do NOT share a curve);
reliability-shrunk individual trend; comparable-player prior for thin histories; league prior
**only** when no individualized information exists — and then flagged, never silent.

**Parameter rule (binding):** `d`, κ, age curves, trend shrinkage are LEARNED by rolling as-of
validation on historical player-season pairs. The illustrative constants in the owner's sketch
(`season_decay=0.70`, `prior_strength=300`) are **not adopted**: the engine has no default
values for them, every call must pass parameters carrying a provenance tag, and any output
produced with `PLACEHOLDER_UNTRAINED` parameters is stamped `NON_FORECAST_GRADE` and can never
enter a registry cohort. **No constant may be chosen from the Phase-4 forward cohort.**

Aging curves are learned from matched consecutive player-seasons: within-player change,
opportunity-weighted, run-environment controlled, decliners and MLB-exits included (survivor
bias), hitters and pitchers separate, per-skill curves, every training row strictly as-of.
No generic "players under 27 improve X%" rule.

## B. Pitcher expected K (k.xk_stuff)

Two connected models: (1) pitch-level expected CSW from pre-game-available pitch
characteristics (velocity, movement, extension, type, mix, handedness, batter
swing/contact/called-strike tendencies, count context in training data); (2) a separately
calibrated PA-level model for P(K per PA). `E[K] = E[TBF] × P(K per PA)`; TBF/workload
uncertainty kept separate from strikeout-skill uncertainty. **No fixed CSW→K% multiplier.**
Grouped temporal validation only — pitches from one game never split across train/test. The
"stabilizes after ~80 pitches" claim is a hypothesis to test on our data, not a constant to
borrow.

## C. Context layer

Captured with `observed_at` timestamps, provenance and hashes; raw captures preserved
separately from learned adjustments: confirmed lineups, batter-side splits, starting catcher +
shrunk framing estimate, plate umpire + shrunk zone tendency, temperature/humidity/station
pressure/elevation → computed air density, wind, roof status (roof overrides outdoor weather),
bullpen workload/availability. Catcher and umpire effects heavily shrunk; a missing assignment
is marked UNAVAILABLE, never silently replaced with a neutral multiplier.

## D. Two forecast times

`EARLY` (projected lineup, only genuinely-available context, labeled uncertain) and `FINAL`
(confirmed lineup, catcher, umpire, roof, latest eligible weather) are **separately tracked
records; FINAL never overwrites EARLY** — append-only, enforced by the existing forecast
registry chain when these reach forecast stage.

## E. Integration

Projected lineup offense + pitcher/bullpen run prevention → **one joint score distribution** →
ML, RL and Totals derived from that same distribution (market priority ML → K → RL → TOTAL
unchanged). The dedicated pitcher-K model stays separate but shares the confirmed lineup and
context records. Before lineups post, projected roster-weighted lineup is used and labeled
uncertain — never silent league-average substitution.

## F. Validation ladder (component-wise, sequential, paired)

V14-0 player-neutral baseline → V14-1 personalized hitters → V14-2 personalized pitchers →
V14-3 batter-side matchups → V14-4 bullpen availability → V14-5 weather/roof/air density →
V14-6 catcher + umpire. Each step reports **incremental paired Brier and log loss** against the
previous step and against the frozen `d_logistic_2f` and V13 comparators. Player-level proper
scores are reported before any game-level claim. **No feature is retained because the full
model "looks better."** V14 shadow forecasts begin only after schema + identity freeze, on
future slates, every eligible game.

## DATA-DEPENDENCY GATE (binding; R1 — nothing is invented)

The progression formula **cannot be validated from what the repo holds today**. Current
inventory, verified 2026-07-28: team RF/RA aggregates; 310 per-start pitcher logs
(IP/ER/SO/BB/TBF — no event splits); ONE team-level batting snapshot (2026-07-23, itself
look-ahead-flagged); a FAILED bullpen capture; **zero batter-level event histories, zero
player ages, zero multi-year data, zero pitch-level data, zero lineup/catcher/umpire/weather
captures**. Outbound fetch has been blanket-403 in this environment.

Required before the first real projection — the as-of player-season dataset, schema frozen in
`engine/player_evolution.py`:

| field | rule |
|---|---|
| mlbam_id | required, int |
| season, age | required; age from verified birthdate, not guessed |
| level/league, role | required (position player / SP / RP) |
| opportunities (PA or TBF) | required; event counts must reconcile exactly |
| events | mutually exclusive K/BB_HBP/HR/1B/2B/3B/OTHER_OUT counts |
| source + observed_at_utc + sha256 | required per source artifact |

Until such data arrives (owner upload or restored fetch under R8), ML-E1 consists of: this
pre-registration, the validated projection engine (mathematics proven on synthetic fixtures,
clearly labeled synthetic), the schema validator, and an ingest gate that reports
`EVIDENCE_ABSENT` — **no player projection, no learned parameter, no shadow forecast.**

## Prohibitions

No market odds in any predictive feature (benchmarks stay external). No selector, gate,
ledger, or real-money change. No modification to Phase-4 artifacts or any frozen file. Paper
only; $0; gate 0/100.
