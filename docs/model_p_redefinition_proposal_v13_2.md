# MLB Model P Redefinition Proposal — V13.2

Status: **DIAGNOSTIC CANDIDATE ONLY**  
Action authority: **OFF**  
Market/EV overlay: **DISABLED**

## Why this proposal exists

The current MLB card exposes two distinct probability definitions:

- **Analytic P** — independent-Poisson fixed-rate win probability evaluated at the engine-implied realized mean runs. Ties are split 50/50.
- **Stochastic Sim P** — empirical win fraction from the registered 100,000-path Gamma-Poisson simulation with starter-workload uncertainty.

These fields are intentionally not averaged. Large disagreement is a model-integrity signal, not an invitation to choose whichever probability produces the larger betting edge.

The divergence investigation must precede any canonical probability change.

## Candidate definition

The V13.2 candidate is the Normal approximation to the simulated margin distribution:

```text
P_home_candidate = Phi(mu_margin / sigma_margin)
```

where:

- `mu_margin` is the simulated mean home margin.
- `sigma_margin` is the simulated margin standard deviation.
- `Phi` is the standard Normal CDF.

The diagnostic card currently exposes this value as:

```text
model_p_candidate_normal_margin
```

and labels it:

```text
DIAGNOSTIC_ONLY_NOT_CANONICAL
```

It is **not** used to choose the forecast side, dose, action status, or any market/EV calculation.

## Required naming

During evaluation, retain all three concepts explicitly:

```text
Analytic P
    independent-Poisson, fixed-rate probability

Stochastic Sim P
    full Gamma-Poisson empirical probability

Normal-Margin Candidate P
    Phi(mu_margin / sigma_margin), diagnostic only
```

A future calibrated action probability, if one is justified, must have a separate name such as `Conservative P`. It must not silently replace either diagnostic field.

## Acceptance gates before promotion

The candidate may not become the canonical MLB probability until all of the following are satisfied:

1. **PIT integrity**
   - Requested cutoff and actual source-fetch vintage are separately recorded.
   - Historical replay claims are blocked when the live-only adapter cannot reconstruct the requested cutoff.

2. **Deterministic reproduction**
   - Same event + input snapshot hash + model-state hash + engine version + simulation count reproduces the same seed and numerical output hash.

3. **Divergence explanation**
   - The ablation harness identifies how much of Analytic-vs-Sim divergence is attributable to Gamma overdispersion and starter-workload uncertainty.
   - Unsupported components such as shared run environment or bullpen sequencing are explicitly reported as not modeled rather than assumed.

4. **Out-of-sample calibration**
   - Evaluate Analytic P, Stochastic Sim P, and Normal-Margin Candidate P chronologically on a sufficiently large historical/prospective sample.
   - Report Brier score, log loss, calibration slope/intercept, reliability bins, and discrimination.
   - Do not infer production readiness from a single 16-game slate.

5. **Convergence target**
   - Candidate-vs-Sim disagreement should be reviewed across the full validation sample. A working engineering target is <2 percentage points for at least 90% of games, but this is not itself sufficient for promotion; calibration must also improve or remain non-inferior.

6. **No market leakage**
   - Sportsbook prices, implied probability, spread, total, or closing-line information remain excluded from the forecast-generation features.

## Current-engine ablation interpretation

The divergence report exposes these variants:

| Variant | Gamma variance | Shared environment | Starter workload | Bullpen sequencing | Interpretation |
|---|---:|---:|---:|---:|---|
| A | No | No | No | No | Fixed-rate independent-Poisson baseline |
| B | Yes | No | No | No | Isolates Gamma run-rate overdispersion |
| C | — | — | — | — | Not applicable: shared environment is not modeled |
| D | Yes | No | Yes | No | Adds starter-workload randomness |
| E | Yes | No | Yes | No | Full current engine; presently equivalent to D because bullpen sequencing is not modeled |

This distinction matters: the current engine does **not** contain a shared run-environment factor or bullpen sequencing model, so those mechanisms must not be cited as causes until implemented and validated.

## Migration plan

### Phase 1 — observe

Keep:

```text
model_p           -> backward-compatible alias of Analytic P
analytic_p        -> explicit Analytic P
sim_p             -> backward-compatible alias of Stochastic Sim P
stochastic_sim_p  -> explicit Stochastic Sim P
model_p_candidate_normal_margin -> diagnostic candidate
```

Renderer/UI must show **Analytic P** and **Stochastic Sim P** separately with the registered divergence category.

### Phase 2 — validate

Run the divergence report on every MLB shadow card and aggregate results over several hundred forecasts. Backtest all three probability definitions chronologically without market inputs.

### Phase 3 — decide

Only after calibration evidence exists may a model-state change designate one probability definition as canonical. The decision must be versioned and frozen in a model-state artifact.

### Phase 4 — market overlay

Only after PIT and probability-definition gates pass may sportsbook prices be attached downstream for shadow EV calculations.

## Explicit non-decision

This proposal does **not** declare `Stochastic Sim P`, `Normal-Margin Candidate P`, or any shrinkage formula to be the production action probability. No arbitrary lambda/compression coefficient is authorized.
