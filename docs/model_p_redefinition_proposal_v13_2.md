# MLB Model P Redefinition Proposal — V13.2

Status: **DIAGNOSTIC CANDIDATE ONLY — PROMOTION HELD**  
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

## Observed 2026-09-04 diagnostic evidence

Run `33854661221` produced a 16-game, 100,000-path MLB card with the new PIT and ablation diagnostics. The requested cutoff was `2026-09-04T08:41:00Z`; the maximum live fetch timestamp was about 58 seconds later, so the card was labeled `PIT_ALIGNED` under the 15-minute diagnostic threshold.

The ablation evidence materially narrows the cause of the divergence:

| Diagnostic | 16-game result |
|---|---:|
| Mean Analytic-vs-Sim absolute gap | 6.29 pp |
| Median Analytic-vs-Sim absolute gap | 6.84 pp |
| A fixed-Poisson → B fixed-Gamma mean favorite compression | **6.14 pp** |
| A → B median favorite compression | **6.87 pp** |
| A → B maximum absolute effect | **13.96 pp** |
| B fixed-Gamma → D starter-workload mean effect | **0.01 pp** |
| B → D maximum absolute effect | **0.41 pp** |

Interpretation: on this debugging slate, **Gamma run-rate overdispersion explains nearly all of the large Analytic-vs-Sim compression**, while starter-workload randomness contributes very little additional probability movement. This is diagnostic evidence, not yet calibration evidence.

The proposed Normal-margin candidate also did **not** satisfy the working convergence target on this slate:

| Candidate-vs-Sim check | Result |
|---|---:|
| Mean absolute gap | 2.51 pp |
| Median absolute gap | 2.73 pp |
| Games within 2 pp | **6 / 16 (37.5%)** |
| Maximum absolute gap | 4.57 pp |
| Working target | 90% within 2 pp |

Therefore the V13.2 Normal-margin candidate is **not promoted**. The current evidence argues against replacing Analytic P with `Phi(mu_margin / sigma_margin)` merely to force convergence.

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

The current leading question is no longer simply "which closed form best matches Sim P?" It is whether the Gamma-Poisson stochastic distribution is better calibrated out of sample than the fixed-rate Analytic P, and whether a separate deterministic approximation is needed at all.

### Phase 4 — market overlay

Only after PIT and probability-definition gates pass may sportsbook prices be attached downstream for shadow EV calculations.

## Explicit non-decision

This proposal does **not** declare `Stochastic Sim P`, `Normal-Margin Candidate P`, or any shrinkage formula to be the production action probability. No arbitrary lambda/compression coefficient is authorized.
