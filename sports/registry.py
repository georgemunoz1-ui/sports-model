"""
SPORT REGISTRY — the extensible core. Each sport declares: its free data endpoints, its
fetch-window size, its season bounds, and its venue/park factors. Adding a sport = adding one
entry here (plus a normalizer note). The FETCH itself is executed by Claude/subagents via the
WebFetch tool (python http is proxy-blocked in this env), then normalized to schema.COLUMNS.

Design rule: results/outcomes first (cheap, reliable from the schedule endpoints), feature
enrichment second (pluggable). This gets a usable labeled dataset fast for every sport.

MLB park factors are DATA-DERIVED from the 2026 backfill (confound-controlled home/road, 30%
shrink) — loaded from park_factors.json when present, else the pre-backfill hand estimates.
"""
import os, json as _json
def _load_pf(default):
    p = os.path.join(os.path.dirname(__file__), "..", "data/backfill/mlb/2026/park_factors.json")
    try:
        return _json.load(open(p))          # authoritative: derived from 1,475 games
    except Exception:
        return default

# ---- ESPN site API is uniform across sports: swap the {league} path segment ----
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={yyyymmdd}&limit=100"
ESPN_ODDS = "https://sports.core.api.espn.com/v2/sports/{path}/events/{eid}/competitions/{eid}/odds"

SPORTS = {
    "mlb": {
        "espn_path": "baseball/mlb",
        # primary results source — MLB StatsAPI (most reliable in this env, rich, no key)
        "results_endpoint": "https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate={start}&endDate={end}&hydrate=linescore,venue",
        "window_days": 7,             # keep payloads under the fetch-summarizer truncation limit
        "season_2026": ("2026-03-25", "2026-11-05"),
        "exclude": "seriesDescription in (Spring Training, Exhibition); status Postponed kept w/ flag",
        "feature_plan": "SP season rates as-of date (statsapi gameLog cumulative), team RF/RA rolling, park, bullpen rest",
        # multiplicative run factors — DATA-DERIVED (backfill) with hand-estimate fallback
        "parks": _load_pf({
            "Coors Field":1.18,"Fenway Park":1.03,"Yankee Stadium":1.02,"T-Mobile Park":0.92,
            "Kauffman Stadium":1.00,"Daikin Park":1.01,"Rogers Centre":1.01,"Wrigley Field":1.00,
            "Angel Stadium":0.97,"Sutter Health Park":1.06,"American Family Field":1.00,
            "Progressive Field":0.98,"Citizens Bank Park":1.04,"Chase Field":1.01,"Truist Park":1.00}),
    },
    "nfl": {
        "espn_path": "football/nfl",
        "results_endpoint": ESPN_SCOREBOARD.format(path="football/nfl", yyyymmdd="{yyyymmdd}"),
        "window_days": 8,             # NFL is weekly; fetch by week (Thu-Mon)
        "season_2026": ("2026-09-10", "2027-02-09"),   # Wk1 ~ Sep 10 2026 → SB LX Feb 2027
        "exclude": "preseason (seasontype=1); keep regular(2)+post(3)",
        "feature_plan": "team EPA/DVOA-style off/def, QB rating, rest days, travel, weather, injuries",
        "parks": {},  # NFL: dome/outdoor + weather handled in features, not a flat factor
        "note": "STUB — ready to populate when 2026 season opens ~Sep 2026",
    },
    "nba": {
        "espn_path": "basketball/nba",
        "results_endpoint": ESPN_SCOREBOARD.format(path="basketball/nba", yyyymmdd="{yyyymmdd}"),
        "window_days": 5,
        "season_2026": ("2026-10-20", "2027-06-20"),   # 2026-27 season opens ~late Oct 2026
        "exclude": "preseason; keep regular+play-in+playoffs",
        "feature_plan": "team off/def rating, pace, rest/B2B, injuries (star availability), travel",
        "parks": {},  # NBA: no park factor; altitude (DEN/UTA) small, in features
        "note": "STUB — ready to populate when 2026-27 season opens ~Oct 2026",
    },
    "wnba": {
        "espn_path": "basketball/wnba",
        "results_endpoint": ESPN_SCOREBOARD.format(path="basketball/wnba", yyyymmdd="{yyyymmdd}"),
        "window_days": 5,
        "season_2026": ("2026-05-15", "2026-10-20"),   # in-season NOW (verified live earlier)
        "exclude": "preseason; keep regular+playoffs",
        "feature_plan": "team off/def rating, rest/B2B, injuries, travel",
        "parks": {},
        "note": "IN-SEASON — can begin populating immediately after MLB backfill",
    },
    "cfb": {
        "espn_path": "football/college-football",
        "results_endpoint": ESPN_SCOREBOARD.format(path="football/college-football", yyyymmdd="{yyyymmdd}"),
        "window_days": 8,
        "season_2026": ("2026-08-22", "2027-01-20"),
        "exclude": "keep FBS; flag FCS/lower-division opponents",
        "feature_plan": "SP+/FEI-style ratings, returning production, home/altitude, rest, pace",
        "parks": {},
        "note": "STUB — opens ~late Aug 2026",
    },
}

def espn_scoreboard_url(sport, yyyymmdd):
    return ESPN_SCOREBOARD.format(path=SPORTS[sport]["espn_path"], yyyymmdd=yyyymmdd)

def espn_odds_url(sport, eid):
    return ESPN_ODDS.format(path=SPORTS[sport]["espn_path"], eid=eid)
