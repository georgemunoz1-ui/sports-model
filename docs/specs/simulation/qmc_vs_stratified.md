For sports simulations, **quasi-Monte Carlo (QMC)** is usually better for smooth, low-to-moderate-dimensional uncertainty such as team strength, pace, and efficiency. **Stratified sampling** is usually better for discrete, discontinuous scenarios such as lineups, player availability, game scripts, score states, and overtime; the strongest real-time design is often a hybrid of both. [matforge](https://matforge.org/monte-carlo-methods-for-scientific-simulations/)

## Core tradeoffs

| Dimension | Quasi-Monte Carlo | Stratified sampling |
|---|---|---|
| Main idea | Use evenly distributed low-discrepancy points instead of independent random draws | Divide the scenario space into strata and sample each deliberately |
| Best for | Smooth continuous inputs | Discrete or heterogeneous scenario groups |
| Typical examples | Pace, shooting efficiency, team strength, player rates | Player active/out, starter/bench, blowout/close game, score states |
| Convergence | Can outperform ordinary MC for smooth functions | Removes between-stratum variation; improvement depends on good strata |
| Discontinuous outcomes | Advantage may weaken | Usually more robust |
| Error estimation | Use randomized/scrambled QMC replicates | Naturally supports within-stratum variance estimates |
| Adaptability | Less intuitive to update dynamically | Easy to allocate more samples to uncertain strata |
| Complexity | Requires careful dimension/order management | Requires good scenario definitions and allocation |
| Real-time suitability | Excellent for repeated smooth simulations | Excellent for discrete live-game state spaces |

QMC points fill the input space more evenly and can converge faster than ordinary random sampling for smooth, moderate-dimensional problems. Its advantage often decreases for discontinuous or noisy functions and in very high dimensions. [matforge](https://matforge.org/monte-carlo-methods-for-scientific-simulations/)

Stratification directly reduces variance by ensuring that important regions are represented rather than accidentally missed. Its performance depends heavily on how the strata are defined and how samples are allocated. [metricgate](https://metricgate.com/docs/stratified-sampling-monte-carlo/)

## Where each fits in sports

### QMC is strongest for

Use scrambled Sobol sequences for continuous or approximately continuous latent variables:

```text
team offensive strength
team defensive strength
player efficiency
pace factor
shooting environment
weather severity
home-court effect
injury-performance adjustment
model residuals
```

Example:

```text
Sobol dimension 1 → home attack strength
Sobol dimension 2 → away attack strength
Sobol dimension 3 → pace
Sobol dimension 4 → home efficiency
Sobol dimension 5 → away efficiency
Sobol dimension 6 → shooting variance
```

QMC works best when nearby inputs produce reasonably nearby outputs. A small change in pace or efficiency should create a small change in the projected result.

### Stratification is strongest for

Use explicit strata when the simulation has discrete jumps:

```text
player active versus out
starter versus bench role
full minutes versus restriction
close game versus blowout
overtime versus regulation
high versus low pace regime
weather normal versus adverse
home team leads versus trails
```

For a questionable NBA player:

| Stratum | Probability | Meaning |
|---|---:|---|
| Full role | 0.50 | Normal minutes and usage |
| Limited role | 0.30 | Reduced minutes or workload |
| Out | 0.20 | Replacement player and redistributed usage |

Every simulation should include each scenario rather than hoping independent random draws happen to represent the 20% out scenario accurately.

Stratification is particularly useful when the target is an indicator:

```text
home wins
spread covers
total goes over
player exceeds prop
```

These are discontinuous outcomes: a tiny change around the line can flip the result from 0 to 1. That can reduce the benefit of ordinary QMC.

## Best design: hybrid sampling

For your builder, I would use:

```text
Outer layer: stratified discrete scenarios
Inner layer: randomized QMC continuous factors
```

Conceptually:

```python
for scenario in scenarios:
    weight = scenario.probability

    u = scrambled_sobol(
        n=paths_per_scenario,
        dimensions=continuous_factor_count
    )

    factors = inverse_cdf_transform(u)

    outcomes = simulate_game(
        scenario=scenario,
        continuous_factors=factors
    )

    aggregate(weight, outcomes)
```

Example:

```text
Outer strata:
  full lineup
  limited player
  player out
  close game
  blowout

Inner QMC factors:
  pace
  efficiency
  shooting variance
  rebound rate
  turnover rate
  player residuals
```

This separates the two types of uncertainty:

```text
Scenario uncertainty → stratification
Parameter/outcome uncertainty → QMC
```

### Nested scenario design

Be careful not to create too many strata. If you combine:

```text
3 lineup states
× 3 game scripts
× 2 weather states
× 2 pace regimes
```

you already have 36 strata before adding more player combinations.

Use a hierarchy:

```text
Lineup scenario
  ↓
Game-script scenario conditional on lineup
  ↓
Continuous QMC simulation conditional on both
```

Drop or merge scenarios whose probability is negligible or whose outcomes are indistinguishable.

## Allocation and convergence

### Stratified allocation

Let \(w_h\) be the probability of stratum \(h\), \(n_h\) its simulation count, and \(\sigma_h\) its estimated within-stratum standard deviation.

A basic allocation is:

\[
n_h \propto w_h
\]

A more efficient Neyman-style allocation is:

\[
n_h \propto w_h\sigma_h
\]

That gives more simulations to strata that are both likely and variable. [metricgate](https://metricgate.com/docs/stratified-sampling-monte-carlo/)

Start with a pilot batch:

```text
1,000 paths per stratum
estimate variance
allocate remaining budget
```

Do not spend equal simulation effort on:

```text
95% full lineup scenario
5% emergency replacement scenario
```

unless the rare scenario has an outsized effect on the betting decision.

### QMC convergence checks

Do not use one deterministic Sobol sequence and assume the estimate is trustworthy. Use randomized scrambling:

```text
8–16 independent scrambled Sobol replicates
```

Then evaluate:

```text
mean probability across replicates
between-replicate standard error
probability range
bet/no-bet decision stability
```

Randomized QMC preserves the space-filling advantage while giving you a practical way to estimate uncertainty. Randomized QMC methods are specifically used to assess faster convergence and estimator variability. [sciencedirect](https://www.sciencedirect.com/science/article/abs/pii/S0885064X25000676)

### Operational stopping rule

Stop when both conditions hold:

```text
Monte Carlo/QMC uncertainty is below target
AND
the betting decision is stable across replicates
```

For example:

```text
Over probability: 56.8%
80% confidence interval: 56.4%–57.2%
All replicates produce the same bet/no-bet decision
```

If the model probability is 56.8% but the market threshold is 56.5%, the decision is fragile. Increase the simulation budget or classify it as uncertain.

## Sports-specific cautions

### QMC dimension ordering

Sobol performance can degrade as dimensionality increases. Put the most influential variables in the first dimensions:

```text
1. lineup state or key player effect
2. pace
3. team strength
4. opponent strength
5. efficiency
6. game-script factor
7. secondary player effects
```

Do not assign important variables randomly to high-dimensional coordinates.

### Discrete inverse-CDF mapping

QMC can still generate Bernoulli or categorical outcomes by mapping uniform values through an inverse CDF:

```python
u < p_active       → active
p_active ≤ u < ... → limited
otherwise          → out
```

But this creates discontinuities. For heavily branching game simulations, stratifying the categorical state first is usually more reliable.

### Correlation

Neither method automatically creates realistic correlation. You still need to model:

- Shared pace.
- Shared team efficiency.
- Player usage redistribution.
- Game margin and minutes.
- Opponent effects.
- Correlated lineup changes.
- Team scoring and player scoring.

Do not apply QMC independently to every player’s stat and then sum the results. Generate shared game factors first, then condition player outcomes on them.

### In-play state changes

For real-time simulations, use the current state as a fixed prefix:

```text
observed score
observed clock
observed possession
observed fouls
observed lineup
```

Then apply stratification to remaining discrete states and QMC to remaining continuous uncertainty. When the score, clock, possession, or lineup changes materially, invalidate the affected cache.

## Recommendation for your system

Use this policy:

```text
Simple pregame score model:
randomized Sobol QMC

Player-availability scenarios:
stratified sampling

In-play basketball/football:
stratified current-state branches
+ randomized Sobol for continuous factors

Rare props or tail outcomes:
stratification
+ importance sampling if necessary

Many correlated player props:
hybrid scenario/QMC simulation with shared latent factors
```

Benchmark three engines on the same historical states:

```text
A. Standard random Monte Carlo
B. Scrambled Sobol QMC
C. Stratified outer layer + scrambled Sobol inner layer
```

Compare:

- Probability error.
- Runtime.
- Probability stability.
- Tail accuracy.
- Correlation accuracy.
- Calibration by game state.
- Bet/no-bet decision stability.
- CLV and execution performance.

For your five-tier builder, the most practical default is:

```text
Stratify discrete uncertainty first;
use scrambled Sobol points inside each stratum;
allocate extra paths to high-variance or decision-critical strata;
validate with multiple randomized replicates.
```

That gives you the speed of QMC where it works well and the robustness of stratification where sports simulations are discontinuous and scenario-heavy.
