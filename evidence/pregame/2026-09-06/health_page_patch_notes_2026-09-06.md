# Health-page patch notes — 2026-09-06 pregame

```text
GLOBAL_HEALTH                    = RED
MLB_FORECAST_GENERATION          = YELLOW
CFB_FORECAST_GENERATION          = RED
MLS_EVENT_IDENTITY_BLOCKER       = OPEN
LOCAL_REPLAY                     = PASS
REMOTE_DURABILITY                = NOT_ESTABLISHED
PROSPECTIVE_GRADE_ELIGIBLE       = NO
PREDICTIVE_VALIDATION            = UNVALIDATED
MARKET_OVERLAY                   = OFF
ACTION_AUTHORITY                 = OFF
```

- 15/15 MLB games reconciled and forecast at cutoff `2026-09-06T08:54:51Z`; 100,000 deterministic Monte Carlo paths/game; 13 ALIGNED, 2 WATCH, 0 DIVERGENT.
- MLB live inputs remain degraded: all lineups TBD/missing, bullpens unknown, weather/roof unbound, park factor default 1.0; probable starters are official listings but unconfirmed.
- 3/3 CFB games reconciled but forecast/simulation BLOCKED because no independent registered source-model `p_home` exists for Sept. 6; market prices were not substituted.
- WNBA/NFL/MLS regular season/NBA/NHL: no qualifying Sept. 6 league games.
- Sept. 5 MLS home/away identity defect remains open P0 before next MLS card.
- Remote evidence mirror write accepted pregame on a separate branch, but protected-authoritative-branch and readback-hash gates are not satisfied; no canonical prospective eligibility is claimed.
