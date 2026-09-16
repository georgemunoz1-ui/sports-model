For a first production version, stratify on **time remaining × score margin × possession**, then add sport-specific state variables. Use much finer buckets near the end of regulation, where one possession or drive can change the result, and keep overtime in a completely separate branch. Live win-probability models commonly rely on score differential, time remaining, pregame strength, and possession as core state variables. [sportsbettingoddscalculator](https://www.sportsbettingoddscalculator.com/live-win-probability)

## NFL boundaries

### Time remaining

Use quarter and clock rather than only total game time:

| Game phase | Suggested time buckets |
|---|---|
| First three quarters | 10–15 min, 5–10 min, 2–5 min, 0–2 min |
| Fourth quarter | 10–15 min, 5–10 min, 2–5 min, 1–2 min, 30–60 sec, 0–30 sec |
| Endgame | Add exact seconds or 5–10 second buckets when under 2 minutes |

For an initial simulator, this is a good compromise:

```text
Q1–Q3:
0–2, 2–5, 5–10, 10–15 minutes

Q4:
0–30, 30–60, 60–120, 120–300,
300–600, 600–900 seconds
```

Use finer buckets inside the final two minutes because timeout usage, clock management, field-goal decisions, and fourth-down strategy change abruptly.

### Score margin

Use scoring and conversion thresholds as boundaries:

```text
tie
±1–2
±3
±4–5
±6
±7–8
±9–11
±12–15
±16–23
±24 or more
```

The \(\pm3\), \(\pm7\), and \(\pm8\) regions deserve special treatment because field goals, touchdowns, and two-point conversions change strategy. Late in the game, preserve exact margins from approximately \(-8\) through \(+8\) rather than combining them into broad buckets.

### Additional NFL state

Score and time alone are insufficient for NFL simulation. Include:

```text
possession
quarter
down
distance
yard line
timeouts remaining
field position
score margin
pregame spread
team strength
offensive/defensive personnel
weather
```

At minimum, stratify or condition on:

```text
possession × down × distance bucket × field-zone bucket
```

Suggested field-position buckets:

```text
own goal line–10
own 11–25
own 26–50
opponent 49–25
opponent 24–11
opponent 10–goal line
```

Suggested down-and-distance buckets:

```text
1st down
2nd and short
2nd and medium
2nd and long
3rd and short
3rd and medium
3rd and long
4th down
```

Do not create the entire Cartesian product as separate strata unless you have enormous data. Keep the major state variables in the transition model and stratify only on the highest-impact combinations.

## NBA boundaries

### Time remaining

NBA scoring is more continuous than NFL scoring, but the value of each possession changes dramatically late.

Use quarter-specific buckets:

| Quarter | Suggested buckets |
|---|---|
| Q1–Q3 | 9–12 min, 6–9 min, 3–6 min, 1–3 min, 0–1 min |
| Q4 | 6–12 min, 3–6 min, 1–3 min, 30–60 sec, 0–30 sec |
| Final possessions | Exact seconds or 5-second buckets under 30 seconds |

A practical representation is:

```text
Q1–Q3:
0–60, 60–180, 180–360, 360–540, 540–720 seconds

Q4:
0–30, 30–60, 60–180, 180–360, 360–720 seconds
```

Use exact clock time for the final 30 seconds if you model fouling, intentional free throws, two-for-one possessions, or last-shot scenarios.

### Score margin

Suggested starting buckets:

```text
tie
±1
±2
±3
±4–5
±6–8
±9–12
±13–18
±19–25
±26 or more
```

Preserve exact margins near the end:

```text
Q4 under 3 minutes:
exact margin from -8 through +8
```

A one-point margin, a three-point margin, and a six-point margin produce different foul and shot-selection strategies. Earlier in the game, broader buckets are usually acceptable.

### Additional NBA state

Add:

```text
possession
quarter
time remaining
score margin
team fouls
bonus status
timeouts
lineup ID
player foul counts
pace
pregame spread
current live spread
```

For player props, add:

```text
current minutes
projected remaining minutes
usage rate
foul trouble
starter/bench role
on-court lineup
blowout probability
```

Team fouls and bonus status are especially important late because they affect free-throw probability and possession value. Lineup state also matters because the same score and clock can have different probabilities depending on which players are on the floor.

## Overtime design

Do not place overtime in the same strata as late regulation. Overtime is a conditional branch with different rules, player usage, fatigue, strategy, and market settlement.

### NBA overtime

Model regulation ending tied as a separate transition:

```text
regulation state
  ├── home wins in regulation
  ├── away wins in regulation
  └── tied → overtime
```

Then reset the overtime clock while retaining:

```text
score
lineups
fouls
timeouts
player fatigue
injury status
team strength
```

Suggested NBA overtime buckets:

```text
0–30 sec
30–120 sec
120–300 sec
```

Use explicit 5-minute overtime rules, and permit multiple overtimes if modeling final score or full-game totals.

### NFL overtime

NFL overtime should be modeled as a separate state machine rather than a normal continuation of the fourth quarter. Current rules distinguish possession, opening kickoff, defensive scores, ties after the overtime period, and regular-season versus postseason outcomes. Under the 2025 rule change described by ESPN, both offenses generally receive a possession in regular-season overtime unless a defensive score or a possession lasting the entire overtime period ends the game; a game can still finish tied after the 10-minute period. [espn](https://www.espn.com/nfl/story/_/id/46150828/nfl-new-regular-season-ot-rules-coin-toss-two-point-conversion)

Recommended NFL overtime state:

```text
overtime_started
coin_toss_winner
first_possession_team
field_position
score_margin
possession_number
time_remaining
timeout_state
```

A simple branch structure:

```text
coin toss
  ↓
first possession outcome
  ├── defensive score
  ├── touchdown
  ├── field goal
  ├── no score
  └── possession consumes overtime

second possession
  ├── win
  ├── tie continues
  └── overtime expires
```

Do not use a generic “50% overtime win probability.” It should depend on team strength, possession, field position, first-possession outcome, and rule set.

### Market-specific overtime

Before simulating, define whether the market includes overtime:

```text
full-game moneyline
regulation-only moneyline
full-game spread
regulation spread
full-game total
regulation total
player prop including overtime
player prop excluding overtime
```

Sportsbook settlement rules can differ by market, and some basketball markets include overtime while others explicitly exclude it. [olg](https://www.olg.ca/en/proline/proline-plus-game-conditions.html)

## Better stratification strategy

Use three levels rather than one giant state table.

### Level 1: high-impact discrete strata

```text
regulation versus overtime
time bucket
score-margin bucket
possession
```

### Level 2: conditional state variables

For NFL:

```text
down
distance
yard line
timeouts
```

For NBA:

```text
team fouls
bonus
lineup
timeouts
foul trouble
```

### Level 3: continuous simulation factors

```text
pace
team efficiency
player efficiency
fatigue
shooting variance
turnover rate
weather
```

Use stratified sampling at Levels 1 and 2, then randomized Sobol or ordinary Monte Carlo draws for Level 3.

```text
Outer stratification:
  Q4, margin = -3, possession = home

Inner QMC:
  pace, efficiency, turnover rate, shooting variance
```

This avoids creating thousands of sparsely populated strata.

### Adaptive allocation

Start with a pilot sample in every important stratum:

```text
1,000 paths per stratum
```

Estimate within-stratum variance, then allocate additional paths using:

\[
n_h \propto w_h\sigma_h
\]

where:

- \(w_h\) is the historical or scenario probability of stratum \(h\),
- \(\sigma_h\) is its estimated outcome variability.

Give more paths to states that are both likely and uncertain. A two-point NBA game with 45 seconds remaining deserves more attention than a 25-point game with 8 minutes remaining if the betting decision is near the market threshold.

## Practical safeguards

Use these rules:

- Estimate data-driven boundaries from the training period only.
- Require a minimum number of unique games per stratum.
- Merge sparse tails into broader buckets.
- Use hierarchical fallback when an exact state is underrepresented.
- Do not mix regulation and overtime observations.
- Do not mix full-game and regulation-only market targets.
- Recalculate boundaries separately for NFL and NBA.
- Check calibration by time bucket and score margin.
- Validate high-leverage late-game states independently.
- Compare 5,000 versus 50,000 paths for convergence.
- Use identical random streams when comparing two lineup or game-script scenarios.

A strong fallback hierarchy is:

```text
exact state
  ↓ if too sparse
same time and nearby score margin
  ↓ if still sparse
same quarter and possession
  ↓
league/season baseline
```

## Recommended starting configuration

### NFL

```text
Strata:
regulation/OT
quarter and time bucket
score margin
possession

Conditional state:
down, distance, yard line, timeouts

OT:
separate rule-based state machine
```

### NBA

```text
Strata:
quarter and time bucket
score margin
possession
regulation/OT

Conditional state:
team fouls, bonus, timeout, lineup, player foul trouble

OT:
separate five-minute continuation model
```

The most important design principle is not to find universal boundaries. It is to place finer boundaries where the **decision function is discontinuous**—near scoring thresholds, the end of regulation, overtime entry, key numbers, foul states, and uncertain lineups—and use broader pooling everywhere else.
