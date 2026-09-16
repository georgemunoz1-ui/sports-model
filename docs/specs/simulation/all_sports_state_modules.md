For all major sports, use a **common simulation framework with sport-specific state modules**, not one universal set of score/time buckets. The core state should always include the current phase, time or progress remaining, score state, possession or initiative, personnel, ruleset, market target, and data freshness; sport-specific modules then add the variables that actually drive transitions.

## Universal state design

Use a canonical event state like:

```text
sport
league
season
ruleset_version
event_id
phase
time_or_progress_remaining
score_state
possession_or_initiative
participants_on_field
availability_state
venue
weather
market_type
regulation_or_overtime
state_timestamp
odds_timestamp
```

Then add sport-specific fields:

```text
NFL: down, distance, yard line, timeouts
NBA: team fouls, bonus, lineup, possession
MLB: inning, half-inning, outs, base runners, count
NHL: manpower, period, penalties, empty-net status
Soccer: minute, stoppage time, cards, score, substitutions
Tennis: set, game, point, server, tiebreak status
Golf: hole, round, strokes relative to par, playing group
Esports: map, round, economy, side, players alive, ultimate resources
```

Score, time remaining, team quality, and possession are foundational live-state variables, but the state must be expanded for each sport rather than assuming those four fields are sufficient everywhere. [linkedin](https://www.linkedin.com/posts/pzaimes_according-to-espn-analytics-in-the-four-activity-7472087511377530880-Flq6)

## Sport-specific stratification

| Sport | Primary strata | Fine boundaries near the end | Separate branches |
|---|---|---|---|
| NFL | Quarter/clock, score margin, possession, down, distance, field position, timeouts | Exact or 5–10 second buckets under 2 minutes; exact margins near key numbers | Regular-season OT, postseason OT, two-point/late-game state |
| NBA/WNBA | Quarter/clock, score margin, possession, team fouls, bonus, lineup, timeouts | Exact margins under 3 minutes; 5–10 second buckets in final minute | Overtime, foul-game state, intentional-foul state |
| MLB | Inning/half, score margin, outs, base occupancy, count, pitcher/batter matchup | Exact base/out/count state in late innings | Extra innings, runner-on-second rule, bullpen state |
| NHL | Period/clock, score margin, manpower, possession/zone, penalties, goalie status | Exact score and manpower under 5 minutes; second-level buckets under 60 seconds | Regulation, 3-on-3 OT, shootout |
| Soccer | Minute, score margin, possession/territorial state, red cards, substitutions, expected goal rate | 5-minute buckets normally; 1-minute or exact stoppage-time state late | Regulation, extra time, penalty shootout |
| Tennis | Set, game, point score, server, surface, tiebreak state | Exact point state during tiebreaks and break points | Regular games, tiebreaks, deciding-set rules |
| Golf | Hole, round, strokes relative to par, position, weather, playing group | Hole-by-hole late-round leader states | Playoff format, weather suspension, shortened event |
| Esports | Map, round, score, side, economy, players alive, ultimates/resources | Exact late-round economy and player-count state | Overtime, map point, match point, side switch |

### NFL

Use score boundaries aligned with common scoring outcomes:

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
±24+
```

In the final two minutes, retain exact margins from approximately \(-8\) through \(+8\). A three-point deficit has a different strategy from a four-point deficit, and a seven-point deficit differs materially from an eight-point deficit.

The critical state is not merely score and time:

```text
score margin
+ possession
+ down
+ distance
+ yard line
+ timeouts
+ quarter
```

Treat field position as a continuous or fine-grained variable rather than broad home/away zones when the model is making drive-level decisions.

### NBA and WNBA

Use:

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
±26+
```

Preserve exact margins in the final three minutes. Add:

```text
team foul count
bonus status
timeouts
lineup
player foul trouble
possession
```

The same score and clock can imply very different outcomes if a team is in the bonus, has two timeouts, or has its primary ball-handler on the bench.

Use a separate late-game branch for:

```text
normal possession
intentional fouling
advance-timeout strategy
two-for-one attempt
last-shot possession
overtime possibility
```

### MLB

MLB should not be stratified by “time remaining” because the game clock is not the main state variable. Use a Markov-style base/out/count state:

```text
inning
top/bottom
outs: 0, 1, 2
base occupancy: 000 through 111
count: 0–0 through 3–2
score margin
pitcher
batter
handedness
pitch count
bullpen availability
park/weather
```

The most important state dimensions are:

```text
inning × outs × base state × count
```

Use exact states in high-leverage situations:

```text
late inning
tie or one-run game
runner in scoring position
two outs
full count
closer or top reliever available
```

For player props, separately simulate:

```text
plate-appearance probability
batting-order position
times-through-order effect
pitcher handedness
bullpen transition
park factor
weather
```

Extra innings must be a separate state with its own ruleset and runner-placement assumptions. Do not blend extra-inning observations into regulation inning states.

### NHL

NHL live simulation needs manpower and goalie state:

```text
period
time remaining
score margin
5-on-5
power play
penalty kill
4-on-4
3-on-3
empty-net status
goalie pulled/active
faceoff zone
shot or possession state
```

Suggested score buckets:

```text
tie
±1
±2
±3–4
±5+
```

Use exact score and manpower state in the final five minutes. A tied 5-on-5 game is fundamentally different from a tied game with one team on a power play.

Separate:

```text
regulation
3-on-3 overtime
shootout
```

For goalie and player props, include expected remaining ice time, line assignment, power-play unit, penalty risk, and empty-net probability.

### Soccer

Soccer has fewer scoring events, so score state should remain relatively exact:

```text
tie
home +1
away +1
home +2
away +2
home +3 or more
away +3 or more
```

Use time buckets such as:

```text
0–15
15–30
30–45+
45–60
60–75
75–85
85–90+
stoppage time
```

Add:

```text
red cards
yellow-card accumulation
substitutions
possession or territory
team strength
expected goal rate
fatigue
home/away
competition rules
```

A red card should trigger a new state branch rather than simply become another feature. A team with 10 players has a different scoring and conceding process.

Separate:

```text
regulation
extra time
penalty shootout
```

For markets, explicitly distinguish regulation-only from match-result markets.

### Tennis

Tennis requires point-level state rather than a generic score margin:

```text
set score
game score
point score
server
surface
serve quality
return quality
break-point state
tiebreak status
fatigue
medical timeout
```

Suggested state hierarchy:

```text
match level
  → set level
    → game level
      → point level
```

Preserve exact point states in tiebreaks and break points. A player serving at 5–4, 30–15 is not interchangeable with a player receiving at 5–4, 30–15.

Point-by-point Monte Carlo models are particularly appropriate for tennis because serve and return statistics can be simulated forward through games and sets. [actionnetwork](https://www.actionnetwork.com/tennis/sofia-kenin-vs-venus-williams-prediction-pick-odds-2026-us-open-sunday-august-30)

### Golf

Golf is not a possession sport, so use progress and leaderboard state:

```text
round
hole
strokes relative to par
current score
course difficulty
weather
wind
playing group
tee-time wave
remaining holes
cut status
injury/withdrawal status
```

Stratify more finely:

```text
final 9 holes
final 3 holes
leaders within 1 stroke
leaders within 2 strokes
large field gaps
weather-wave differences
```

Golf requires careful correlation across holes. Do not sample each hole independently if wind, player form, fatigue, and course fit create round-level dependencies.

### Esports

For Valorant, CS, League of Legends, or similar games, use:

```text
map
round
score
side
players alive
economy
weapons
ultimates/resources
spike/bomb/objective state
time remaining
site control
man advantage
timeout state
```

The proper state can change abruptly:

```text
5v5 → 4v5
full buy → eco round
ultimate available → ultimate used
site control lost → retake state
```

Use exact or near-exact states for match point, map point, economy-reset rounds, and overtime.

## Make the boundaries adaptive

Fixed buckets are a good starting point, but your system should change resolution based on data density, variance, and decision sensitivity.

### Adaptive time resolution

Use broad buckets early and fine buckets late:

```text
Early game:
large time intervals

Midgame:
moderate intervals

Late game:
small intervals

Terminal state:
exact clock or event-level state
```

This is better than using 30-second buckets for an entire game. A 30-second error early in an NFL game is negligible; a 30-second error in the final drive is enormous.

### Adaptive score resolution

Use exact score differences when:

```text
the market is near a key number
the game is late
the next score changes strategy
the outcome probability is highly sensitive to margin
```

Use wider buckets when:

```text
the game is early
the margin is extreme
additional points do not materially change strategy
```

### Adaptive strata merging

If a stratum is sparse, use hierarchical backoff:

```text
exact state
  ↓
same phase and nearby score/time
  ↓
same sport and possession/manpower state
  ↓
league/season baseline
```

For example:

```text
NFL Q4, 47 seconds, down 3, opponent red zone
  ↓ if sparse
NFL Q4, under 2 minutes, down 1–6, opponent red zone
  ↓
NFL Q4, under 2 minutes, one-score game
```

Require a minimum number of unique games, not merely rows. Thousands of snapshots from the same game do not equal thousands of independent examples.

### Decision-aware refinement

Add more simulation paths where the result affects the decision:

```text
model probability near market threshold
large uncertainty from lineup status
high book disagreement
high expected value sensitivity
late-game state
rare overtime state
```

Do not spend the same computation on:

```text
win probability = 99.8%, no betting decision nearby
```

as on:

```text
win probability = 51.2%, market threshold = 50.7%
```

## Overtime and special rules

Overtime should be represented as a separate `ruleset_state`, not simply as additional time.

```text
regulation
  ├── home win
  ├── away win
  └── tie → overtime
```

Then branch according to sport:

```text
NFL:
coin toss, possession, rule version, postseason/regular season

NBA:
five-minute OT, foul state, lineups, fatigue, multiple OT possibility

NHL:
3-on-3 overtime, goalie status, shootout

MLB:
extra innings, runner placement, batting order

Soccer:
extra time, substitutions, penalty shootout

Tennis:
tiebreak and deciding-set rule

Golf:
playoff format
```

Keep these target definitions separate:

```text
regulation winner
full-game winner
regulation total
full-game total
regulation spread
full-game spread
```

The NFL ruleset itself has changed, including the treatment of possession in overtime, so the ruleset version must be stored with historical games. [espn](https://www.espn.com/nfl/story/_/id/46150828/nfl-new-regular-season-ot-rules-coin-toss-two-point-conversion)

## Recommended architecture

```text
Canonical state manager
  ├── clock/progress
  ├── score
  ├── possession/initiative
  ├── personnel
  ├── ruleset
  └── timestamp validation

Sport adapter
  ├── NFL state adapter
  ├── NBA state adapter
  ├── MLB state adapter
  ├── NHL state adapter
  ├── soccer state adapter
  ├── tennis state adapter
  ├── golf state adapter
  └── esports state adapter

Stratification engine
  ├── sport-specific boundaries
  ├── adaptive time resolution
  ├── adaptive score resolution
  ├── sparse-state fallback
  └── decision-aware allocation

Simulation engine
  ├── state transitions
  ├── shared latent factors
  ├── player/team correlations
  ├── overtime branches
  └── outcome distributions

Evaluation engine
  ├── state-bucket calibration
  ├── convergence
  ├── market comparison
  ├── CLV
  └── execution latency
```

The best default for all major sports is:

```text
Exact discrete state near terminal events
Coarse state buckets early
Sport-specific transition rules
Adaptive sample allocation
Separate overtime and special-rule branches
Hierarchical fallback for sparse states
Randomized QMC inside continuous factors
```

Do not optimize only for overall accuracy. Check calibration and convergence separately by phase, score state, player availability, overtime status, market type, and sport. A simulator that is accurate pregame can still be badly miscalibrated in the final minute, during a power play, with runners on base, or when a key player’s status changes.
