# sportsim

Monte Carlo simulation and prediction for the four major North American leagues —
**NFL, NBA, MLB, NHL**.

Rather than fitting one generic score model and relabelling it per sport, each
league gets a simulator built around how it actually produces points:

| Sport | Engine | Why |
|---|---|---|
| **NFL** | drive-by-drive outcomes (TD / FG / punt / defensive score) | football scores come in 3s and 7s — key numbers at margins of 3 and 7 fall out of the model instead of being bolted on |
| **NBA** | shared possession count × points per possession | the two teams share a pace, which is what makes the final scores correlate and keeps sides consistent with totals |
| **MLB** | plate-appearance base–out Markov chain | gives right-skewed run distributions, walk-off innings, and the home team not batting in the ninth |
| **NHL** | Poisson goals + 3-on-3 overtime + shootout | ~23% of games reach overtime where the winner is nearly a coin flip, which is why hockey moneylines compress |

On top of the game engines: rating estimation, full-season Monte Carlo with real
playoff formats, market/odds tooling, and walk-forward backtesting.

**numpy is the only dependency.**

---

## Install

```bash
git clone <this repo> && cd sports-model
pip install -e .          # or: pip install numpy && export PYTHONPATH=$PWD
```

## Two-minute tour

```bash
python -m sportsim demo --sport nhl
```

Generates a synthetic season, fits ratings to it, prices a game, and projects
the following season with playoff odds — the whole pipeline without needing a
data feed.

### Forecast a game

```bash
python -m sportsim game --sport nba --home BOS --away LAL --games nba_2025.csv \
    --spread -4.5 --total 224.5 \
    --odds '{"moneyline": {"home": -190, "away": 160}}'
```

```
LAL @ BOS   (40,000 simulations)
----------------------------------------------------
  BOS                   117.4   win  63.8%   ML -176
  LAL                   112.6   win  36.2%   ML +176
----------------------------------------------------
  fair spread  BOS -5.0
  fair total   230.0
  80% score range   BOS 101-133   LAL 96-129
  P(BOS -4.5) = 52.9%
  P(over 224.5)   = 66.1%

model vs market
----------------------------------------------------
  ML BOS      model  63.8%  market  63.0%  edge +0.79%  EV +0.036u  kelly  1.03%
```

### Fit ratings

```bash
python -m sportsim rate --sport nfl --games nfl_2025.csv --out ratings.csv
```

### Project a season

```bash
python -m sportsim season --sport mlb --games mlb_2025.csv --sims 10000 --top 12
```

Games with blank scores in the CSV are treated as the remaining schedule, so a
mid-season file gives a rest-of-season projection that respects results so far.

### Backtest

```bash
python -m sportsim backtest --sport nba --games nba_2025.csv --compare
```

---

## Library use

```python
from sportsim import read_games_csv, get_simulator, SeasonSimulator
from sportsim.core.ratings import fit_for_sport

games = read_games_csv("nhl_2025.csv")
played = [g for g in games if g.played]

fit = fit_for_sport(played, "nhl")          # attack / defence multipliers
sim = get_simulator("nhl")

f = sim.forecast(fit.rating("BOS"), fit.rating("MTL"), n=50_000)
print(f.home_win_prob, f.fair_spread(), f.over_prob(6.5))

season = SeasonSimulator("nhl", fit.ratings())
result = season.run([g for g in games if not g.played], n_sims=10_000)
print(result.report(top=10))
print(result.team_report("BOS"))
```

More worked examples in [`examples/`](examples/).

### Data format

`date,home,away,home_score,away_score` — optional `neutral`, `ot`, `season`
columns, and common aliases (`home_team`, `home_points`, `home_runs`, …) are
recognised. Blank scores mean the game has not been played.

```csv
date,home,away,home_score,away_score
2025-10-08,BOS,MTL,4,2
2025-10-11,BOS,TOR,,
```

Any source works — the model never touches the network. Public options include
`nfl_data_py`, `pybaseball`, Retrosheet, and the NHL/NBA stats APIs.

---

## How it fits together

```
 results CSV
     │
     ├── EloModel ................ online ratings, reacts fastest to recent form
     ├── fit_poisson_strength .... attack/defence multipliers  ──┐
     └── fit_ridge_margin ........ additive point ratings + HFA  │
                                                                 ▼
                                          NFL / NBA / MLB / NHL game simulator
                                                                 │
                        ┌────────────────────────────────────────┴───────────┐
                        ▼                                                    ▼
              GameForecast                                        SeasonSimulator
   win prob · fair spread · totals                    standings · playoff odds · title odds
   team totals · market edges · Kelly                 (real brackets and series formats)
```

### Ratings

`fit_poisson_strength` factorises scores into attack and defence multipliers by
iterative proportional fitting: a team's attack rating is what it scored divided
by what an average team would have scored against the same opponents. Two knobs
matter:

- **`shrinkage`** regresses toward league average. A 17-game NFL season needs far
  more of it than a 162-game MLB season; `fit_for_sport` applies per-league
  defaults.
- **`decay_half_life`** down-weights older games so ratings track current form.

`EloModel` is the online alternative, with margin-of-victory scaling damped by
the winner's rating edge and between-season regression to the mean.

### Season simulation

`SeasonSimulator` runs three layers: every distinct matchup is simulated once in
bulk and cached as an empirical score distribution; seasons are replayed by
indexing into that cache; and playoff series are resolved with an exact dynamic
program over the home-court pattern instead of more simulation.

Crucially it samples **season-long rating uncertainty**: each scenario draws a
strength for every team and holds it all year. Skipping this is the most common
way playoff odds end up badly overconfident — a team's true quality being
unknown moves the tails more than game-to-game variance does.

Real formats are implemented: NFL 7-seed conferences with a bye and reseeding,
NBA play-in and fixed bracket, NHL divisional bracket with wild cards, MLB byes
plus best-of-3/5/7 rounds. Standings use points/wins then differential; the
deeper league-specific tiebreakers (head-to-head, common games) are settled by a
random draw instead.

### Market tooling

American/decimal conversion, vig removal (multiplicative, power, Shin), edge vs
a posted price, Kelly staking with a bankroll cap, and closing line value.
`scan_edges` compares a forecast against a full set of moneyline/spread/total
prices at once.

### Evaluation

`walk_forward` refits ratings as it advances so every prediction uses only prior
games. Reported: log loss, Brier, accuracy, Brier skill score, expected
calibration error, a reliability table, margin MAE/RMSE/bias, and ATS records at
-110.

---

## Calibration

League-average matchup, 200k simulations per sport, against typical real league
values:

| | total (real / model) | team score SD | home win% | overtime rate |
|---|---|---|---|---|
| NFL | 45.5 / 45.8 | 10.4 / 10.4 | ~55% / 55.1% | ~6% / 3.4% |
| NBA | 226 / 227.3 | 12.4 / 12.7 | ~57% / 56.9% | ~6% / 3.0% |
| NHL | 6.1 / 6.1 | 1.75 / 1.74 | ~53% / 52.3% | ~23% / 21.9% |
| MLB | 8.8 / 8.8 | 2.9 / 2.9 | ~53% / 53.7% | ~9% / 10.1% |

Ratings mean the same thing everywhere: an `attack` of 1.10 scores 10% more
points in all four simulators, matching the units the fitters produce. The NFL
and MLB engines apply quality through an intermediate quantity — drive outcomes
and on-base rate — whose effect on scoring is naturally convex, so their
exponents are tuned to cancel that out. A test asserts the invariant.

Known gaps, stated plainly:

- **NFL margin spread is ~5% too wide** (14.3 vs ~13.6 in reality), and the
  overtime rate is correspondingly low. Drives are modelled as independent,
  while real games have negative feedback — clock management with a lead,
  garbage time — that compresses margins.
- **Ratings are static within a simulated season.** Injuries, trades and
  in-season development are represented only through the scenario noise term,
  not as ratings that drift game to game.
- **Simplified tiebreakers.** Head-to-head and common-games rules are replaced
  by a random draw, which slightly blurs the odds for teams sitting exactly on a
  playoff cut line.
- **Playoff series reuse regular-season matchup probabilities** where the pairing
  was on the schedule. The postseason rule changes (no ties, sudden-death
  overtime, no ghost runner) move a single-game probability by well under a
  point, and this is what keeps a championship Monte Carlo interactive.
- **No player-level input.** There is no starting-pitcher, quarterback or
  rest/travel adjustment. For MLB in particular, the starting pitcher is worth
  real money on a game line and this model does not see it.

## Performance

2,000 simulated seasons including playoffs, on one core:

| NBA | NHL | NFL | MLB |
|---|---|---|---|
| ~3s | ~4s | ~13s | ~100s |

MLB is the outlier because it simulates every plate appearance. Turn
`samples_per_matchup` down for quicker exploratory runs.

Single-game throughput: NHL 4.6M, NBA 1.8M, NFL 0.8M, MLB 77k games/second.

## Tests

```bash
pip install pytest && python -m pytest tests/ -q
```

Covers odds and staking maths, rating recovery against known true strengths,
per-sport simulator behaviour (key numbers, walk-offs, overtime rates, ties),
season invariants (one champion per simulation, correct playoff field sizes,
monotonic round-by-round probabilities), backtest calibration, and the CLI.

## Responsible use

Live betting markets are efficient and priced with a hold. A model that is
merely reasonable will lose money to the vig. If you use this against real
markets, measure closing line value before you measure profit, bet fractional
Kelly at most, and treat any backtest edge as an upper bound on the real one.
