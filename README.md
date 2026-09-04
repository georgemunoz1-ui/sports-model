# Sports Model Research System

Governed, point-in-time sports forecasting research with deterministic simulation, immutable forecast artifacts, prospective grading, and a strict separation between model inference and market valuation.

> **Current operating posture — September 4, 2026**  
> **DIAGNOSTIC_SHADOW · action authority OFF · market overlay OFF**  
> Forecast generation is allowed for supported diagnostic paths. A model forecast is not a wager and sportsbook prices are not predictive model inputs.

## Current repository status

| Item | Current state |
|---|---|
| Working branch | `codex/nfl-wnba-nba-models-v1` |
| GitHub default branch | `main` — scheduled workflows become active only after merge to the default branch |
| Repository visibility | **Private** |
| Current execution mode | `DIAGNOSTIC_SHADOW` |
| Wager/action authority | **OFF** |
| Market/EV layer | **OFF while MLB probability calibration is unresolved** |
| Forecast → result firewall | **Enforced** |
| MLB full-card execution | **Operational in shadow mode** |
| MLB deterministic reproduction | **Verified** |
| MLB live PIT labeling | **Verified** |
| MLB prospective calibration | **Accumulating; registered 9/4 card currently awaiting outcomes** |

The operational goal is not merely to produce numbers. A sport is treated as operational only when it can produce a complete numerical pregame card from point-in-time inputs, freeze that card immutably, reproduce it deterministically, and grade it later without leaking result information backward into the forecast artifact.

---

## September 4, 2026 milestone

The system crossed an important threshold on September 4: the MLB pipeline produced a complete numerical slate from the repository runtime and then reproduced it exactly in a separate GitHub Actions execution.

### Verified MLB execution chain

```text
live/PIT input capture
→ canonical event + model input snapshot
→ deterministic seed derivation
→ 100,000-path Gamma-Poisson simulation
→ immutable diagnostic card
→ reproduction run
→ registered prospective card
→ append-only grading ledger
→ cumulative calibration summary
```

### Reproduction evidence

| Check | Result |
|---|---:|
| Canonical registered run | `33854661221` |
| Reproduction run | `33854752034` |
| Slate coverage | **16 / 16** |
| Simulations | **100,000 per game** |
| Forecast-core reproduction | **16 / 16 exact** |
| Output-hash reproduction | **16 / 16 exact** |
| RNG | **PCG64, explicitly seeded** |
| Action authority | **OFF** |

Deterministic identity includes the event, frozen input snapshot, model-state/config identity, engine version, and simulation count. Runtime timestamps and orchestration-only metadata do not alter the numerical forecast identity.

---

## Point-in-time provenance

A reproducible forecast can still be mislabeled if its data vintage does not match the claimed cutoff. The MLB card now separates:

- `requested_as_of_utc`
- `actual_data_vintage_utc`
- `generated_at_utc`
- `min_source_timestamp_utc`
- `max_source_timestamp_utc`
- `pit_delta_seconds`
- `pit_mode`
- `pit_reconstruction_supported`
- `pit_status`

### PIT classifications

| Condition | Status | Diagnostic forecast? | Action authority? |
|---|---|---:|---:|
| within 15 minutes | `PIT_ALIGNED` | Yes | Still OFF |
| 15–60 minutes | `PIT_WARN` | Yes, labeled | No |
| >60 minutes from requested cutoff | `PIT_STALE` | Yes, labeled | No |
| source vintage cannot be determined | `PIT_UNKNOWN` | Diagnostic only | No |
| historical replay claimed from a live-only source | `PIT_REPLAY_INVALID` | No retrospective replay claim | No |

MLB StatsAPI is currently treated as a **live snapshot source**, not as a historical PIT reconstruction service. Fetch timestamps are therefore provenance proxies and are never silently represented as historical source-effective timestamps.

---

## Diagnostic Shadow Card workflow

The repository exposes a single execution boundary through:

```text
.github/workflows/diagnostic-shadow-card.yml
```

The workflow can be driven by `workflow_dispatch` or by the branch request-file bridge used from chat/automation.

Core runner:

```bash
python scripts/generate_card_force.py \
  --date YYYY-MM-DD \
  --league mlb \
  --as-of-utc YYYY-MM-DDTHH:MM:SSZ \
  --simulations 100000 \
  --output-dir output/card
```

Generated artifacts include:

```text
diagnostic_card.json
diagnostic_card.csv
diagnostic_card.md
manifest.json
run.log
```

The workflow fails closed on coverage breaches and publishes both a human-readable card and machine-readable artifacts.

### Current adapter reality

The CLI accepts `mlb`, `cfb`, `nfl`, `wnba`, and `nba`, but CLI acceptance alone does **not** make a sport operational. The verified adapter-backed diagnostic paths in this branch are currently MLB and CFB. NBA, WNBA, and NFL remain subject to their separate implementation/validation gates and must not be represented as first-class simply because the workflow exposes a league choice.

---

## MLB probability definitions

MLB currently keeps two probability estimators separate by design:

| Field | Meaning |
|---|---|
| **Analytic P** | independent-Poisson win probability evaluated at point-estimate expected runs |
| **Stochastic Sim P** | empirical win probability from the full Gamma-Poisson Monte Carlo distribution |

They are not averaged or blended.

### September 4 divergence finding

The first full-slate ablation study showed that the main source of disagreement is **Gamma run-rate overdispersion**, not starter-workload randomness.

| Effect | 9/4 diagnostic result |
|---|---:|
| Mean absolute Analytic-vs-Sim gap | ~**6.3 pp** |
| Mean compression attributable to Gamma overdispersion | ~**6.1 pp** |
| Mean additional starter-workload effect | ~**0.01 pp** |
| Strongest observed relationship | absolute projected margin / favorite strength |

This is treated as a **structural limitation of the analytic approximation**, not as a simulator bug. The independent-Poisson formula is doing what it is designed to do; it simply omits the latent run-rate dispersion present in the stochastic engine.

A Normal-margin replacement candidate was tested and **not promoted**. On the 9/4 slate it reached only 6/16 games within 2 percentage points of Stochastic Sim P, far below the proposed convergence target.

The correct unresolved question is therefore:

> **Which estimator is better calibrated out of sample?**

Until prospective grading answers that question, both estimators remain visible and neither is allowed to drive a market/EV layer.

---

## Prospective calibration and grading

Forecast artifacts are immutable. Game results do **not** rewrite `diagnostic_card.json`.

Instead, the evaluation chain is:

```text
immutable forecast artifact
→ final result
→ append-only result-bound grade row
→ cumulative calibration ledger
→ calibration summary
```

### Forecast grading block

Every eligible MLB forecast carries a pregame grading block with frozen home-oriented probabilities and empty outcome fields.

### Grader

The current grader is:

```text
scripts/accumulate_mlb_calibration.py
grader_version = mlb.calibration_grader.v2
```

It stores:

- frozen `analytic_p_home`
- frozen `stochastic_sim_p_home`
- final score and `home_won`
- Brier score for each estimator
- log loss for each estimator
- paired Brier/log-loss differences
- calibration bins
- result source and result observation timestamp
- `probability_clip_epsilon`
- forecast tier and selected diagnostics
- `graded_at_utc`

The idempotency key is derived from:

```text
forecast_output_hash + result_source_id + grader_version
```

An existing grade is reported as `GRADE_ALREADY_EXISTS`; it is not appended twice.

### Registry state machine

```text
REGISTERED
→ AWAITING_OUTCOMES
→ PARTIALLY_GRADED
→ GRADED
```

`REVIEW_REQUIRED` is used for unresolved integrity/eligibility problems.

A card reaches `GRADED` only when all eligible outcomes are resolved with no skipped records.

---

## Grading invariants

`grade_mlb_registry.py` downloads the **specific registered Actions artifact** and verifies the temporal firewall before accepting a state transition.

Hard invariants include:

1. frozen card bytes are unchanged before vs. after grading;
2. forecast output hashes are unique within the card;
3. grade IDs are unique in the durable ledger;
4. ledger `analytic_p_home` equals the frozen pregame value;
5. ledger `stochastic_sim_p_home` equals the frozen pregame value;
6. analytic and sim calibration bins are re-derived from those frozen probabilities and must match;
7. `graded_at_utc` must be later than the forecast creation and game start;
8. result observation must not occur after the grade timestamp;
9. market features remain absent and `action_authority` remains `false`.

Any invariant failure terminates the grading run.

### Latest invariant pass

Grading workflow run `33858774441` completed successfully against the registered 9/4 card.

| Invariant | Result |
|---|---:|
| Forecast rows | **16** |
| Unique forecast output hashes | **16 / 16** |
| Frozen-card mutations | **0** |
| Duplicate grade IDs | **0** |
| Skipped forecasts | **0** |
| Current final outcomes | **0 / 16** at the verification time |
| Pending outcomes | **16 / 16** |
| Invariant status | **PASS** |
| Registry state | `AWAITING_OUTCOMES` |

This is the correct state while the games are still unresolved.

---

## Calibration metrics and decision policy

The grader calculates both headline and paired metrics:

- cumulative Brier score;
- cumulative log loss;
- directional accuracy;
- mean and median paired Brier difference;
- mean and median paired log-loss difference;
- per-estimator lower-loss win counts;
- reliability summaries;
- rolling 30/60/100-game paired comparisons.

For each game:

```text
d_i = Brier_analytic,i - Brier_sim,i
```

Positive `d_i` means Stochastic Sim P had the lower Brier score on that game.

### Sample-size policy

Sample thresholds are operating gates, not statistical guarantees.

| Graded sample | Appropriate use |
|---:|---|
| `< 50` | validate result mapping, settlement, and scoring pipeline only |
| `50–99` | inspect obvious bias/directionality; no promotion |
| `100–249` | paired estimator comparison + broad reliability summaries |
| `250–499` | seasonal/rolling diagnostics; no single-slice calibration transform |
| `500+` | model-definition review may be considered if effects are stable through time |

No estimator promotion or conservative-probability policy is authorized merely because a single cumulative metric is lower.

---

## Calibration workflow

The grading workflow is:

```text
.github/workflows/mlb-calibration-grading.yml
```

It supports:

- `workflow_dispatch`;
- request-file pushes under `grading_requests/*.json` on the working branch;
- nightly cron after merge to the repository default branch.

Scheduled GitHub Actions workflows execute from the default branch, so the request-file/manual bridge is the active execution path until this work is merged.

Durable grading state is stored under:

```text
data/grading/mlb/registry.json
data/grading/mlb/calibration_ledger.jsonl
data/grading/mlb/calibration_summary.json
```

### Current registered card

```text
card_date: 2026-09-04
registered run: 33854661221
status: AWAITING_OUTCOMES
forecast hashes: 16 unique
calibration n: 0
market overlay: OFF
action authority: OFF
```

---

## Sport status at a glance

| Sport | Current research status | Forecast/card status | Action status |
|---|---|---|---|
| **MLB** | Gamma-Poisson diagnostic engine with deterministic reproduction, PIT provenance, divergence ablations, and prospective grader | **16/16 full-card execution verified; calibration accumulating** | **OFF** |
| **CFB** | Adapter/model infrastructure exists; historical margin-distribution work and seeded simulation are present | Diagnostic path exists, but current-slate operational claims require an actual fresh repo run | **OFF** |
| **NBA** | Target pipeline defined around D&T ratings + EPM/minutes scenarios + seeded joint simulation | **Not first-class yet**: fitted parameter state, full future slate, reproduction, and prospective grading remain gating requirements | **OFF** |
| **WNBA** | FF7 recovery/integration remains downstream of NBA full-card completion | Not first-class in the current diagnostic card system | **OFF** |
| **NFL** | Reduced QB-aware scoring-model plan remains downstream of WNBA work | Not first-class in the current diagnostic card system | **OFF** |

### NBA definition of done

NBA is not considered operational until this command produces a complete future numerical slate with fitted parameters and deterministic reproduction:

```bash
python scripts/generate_card_force.py --date YYYY-MM-DD --league nba
```

Required artifact chain:

```text
nba_schedule_snapshot_v1
→ nba_team_ratings_pit_v1
→ nba_epm_player_snapshot_v1
→ nba_availability_snapshot_v1
→ nba_minutes_scenarios_v1
→ nba_event_features_v1
→ nba_model_state_v1
→ nba_game_forecast_bundle_v1
→ nba_full_card_v1
→ nba_forecast_grade_v1
```

No plausible constants may be silently hardcoded to bridge missing fitted parameters.

---

## Governance invariants

The project keeps the following rules fail-closed:

```text
Schedule / Inputs
→ Feature Snapshot
→ Forecast Bundle
→ Market Overlay
→ Action Decision
```

- `NO_ACTION` does not mean `NO_FORECAST`.
- Model probability and simulation probability remain distinct.
- Sportsbook prices do not enter predictive model features.
- A started event may not receive a newly generated pregame forecast.
- A requested cutoff does not override wall-clock first-pitch protection.
- Missing/invalid numerical forecast fields create a coverage breach; they are never filled from sportsbook prices or LLM guesses.
- Unsupported markets are explicit (`UNSUPPORTED_BY_TIER`).
- Reproduction runs must preserve seeds, forecast-core fields, and output hashes.
- The original forecast artifact is never rewritten after results are known.
- Market/EV analysis remains a separate future layer and is currently disabled for MLB while estimator calibration is unresolved.

---

## Recent implementation records

| Change | Commit / run |
|---|---|
| Deterministic diagnostic workflow + card artifacts | `diagnostic-shadow-card.yml` |
| MLB live PIT provenance / source-vintage classification | September 4 PIT patch series |
| MLB engine deterministic reproduction | canonical `33854661221`, reproduction `33854752034` |
| Prospective grading block on forecast bundles | September 4 grading integration |
| Calibration grader v2: paired metrics, result-source identity, log-loss epsilon, idempotency | `032fa5561087057b76dcfd51628d1239a26625bd` |
| Registry v2 behavior: `PARTIALLY_GRADED` + hard invariant verification | `be0ca9bc13f48d2fa2a7689b2ba0fff0da26b29c` |
| First v2 grading invariant execution | run `33858774441` — **PASS** |
| Durable 9/4 grading state update | `34b22f7` |

Earlier August research, governance changes, WNBA shadow work, market-capture experiments, and prior audit history remain available in repository history. This README now reflects the current September 4 operational state rather than the superseded August 30 status snapshot.

---

## Current development order

1. **MLB:** accumulate prospective calibration evidence; do not attach market EV yet.
2. **NBA:** complete fitted PIT pipeline → 100K seeded future full-slate card → deterministic reproduction → prospective grading.
3. **WNBA:** recover and integrate FF7 only after NBA full-card success.
4. **NFL:** build the reduced QB-aware scoring model only after WNBA integration.

The current milestone is therefore:

> **A frozen full card can now produce immutable, reproducible numerical forecasts and be graded later without leaking final information backward into the forecast artifact.**

That is the standard all future sport pipelines must meet.
