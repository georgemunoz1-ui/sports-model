"""Synthetic source-bound fixture builder adapted from PR74 tests.
Source: georgemunoz1-ui/sports-model @ d5ab18213253fb2c903a943f06d499fe547afc7d
Path: tests/test_selected_market_independence.py
Git blob: 7accd370573e441d60685ea55fb5da5d60209715
Not predictive evidence or an authentic historical data package.
"""
from models.current import baseline, cfb
from pathlib import Path
import hashlib
from models.nfl.contextual.recovered_inference import digest
from pipelines.cards.selection import select

def head(n, kind, intercept):
    return dict(kind=kind, impute=[0.] * n, mean=[0.] * n, scale=[1.] * n,
                coefficient=[.001 * (i + 1) for i in range(n)], intercept=intercept)


def package(league, week=2):
    event = dict(event_id="SYNTHETIC:" + league, home_team="HOME", away_team="AWAY",
                 home_id="H", away_id="A", start_time_utc="2026-09-23T20:00:00Z",
                 slate_date="2026-09-23", season=2026, neutral_site=False,
                 week=week, division_scope="FBS_VS_FBS", conference_game=True, season_type=2)
    p = dict(schema="sports.current_research_package.v1", league=league,
             action_authority=False, captured_at_utc="2026-09-22T08:00:00Z",
             training_cutoff_utc="2026-09-21T00:00:00Z", ttl_hours=6,
             source_fetches=[dict(source="SYNTHETIC_UNIT_TEST_ONLY", fetched_at_utc="2026-09-22T08:00:00Z")],
             events=[event], covered_dates=[event["slate_date"]], code_pins={},
             data_grade="SYNTHETIC_TEST_NOT_FORECAST", limitations=[], model_lineage={},
             consumed_game_ids=["synthetic-history"])
    if league == "cfb":
        p["model_id"] = select(league, week=week, division="FBS_VS_FBS")["default_model_id"]
        p["parameters"] = dict(regress=.7, hfa=55)
        p["team_state"] = dict(elo={"HOME": 1540., "AWAY": 1490.}, last_season={},
            last={"HOME": "2026-09-15T20:00Z", "AWAY": "2026-09-16T20:00Z"},
            ewpf={"HOME": 31., "AWAY": 25.}, ewpa={"HOME": 21., "AWAY": 23.},
            ewm={"HOME": 10., "AWAY": 2.})
        p["feature_names"] = list(cfb.feature_row(p["team_state"], event, p["parameters"]))
        if week == 1:
            p["feature_names"] = ["elo_diff_with_home_advantage", "neutral_site", "conference_game"]
        n = len(p["feature_names"])
        p["fitted_model"] = dict(winner=head(n, "logistic", .15), margin=head(n, "linear", 2.))
        material = dict(model=p["fitted_model"], state=p["team_state"], parameters=p["parameters"])
    elif league == "wnba":
        p["model_id"] = select(league)["default_model_id"]
        stats = dict(g=12, pts=1010, opts=970, fgm=370, fga=800, fg3m=100, fta=210,
                     oreb=110, tov=140, ofga=810, ooreb=100, otov=150, ofta=190, last="2026-09-20")
        p["team_state"] = [dict(season=2026, team=t, values={**stats, "pts": pts})
                           for t, pts in [("HOME", 1010), ("AWAY", 950)]]
        p["league_state"] = [16000., 100, 8000.]
        p["fitted_model"] = dict(mu=[0.] * 6, sd=[1.] * 6, blog=[.1] + [.2] * 7,
            bmar=[2.] + [1.] * 7, tmu=[160., 0., 0.], tsd=[1.] * 3, btot=[162., .2, .5, 1.])
        material = dict(model=p["fitted_model"], state=p["team_state"], league=p["league_state"])
    elif league == "mlb":
        p["model_id"] = select(league)["default_model_id"]
        event.update(home_pitcher_id=1, away_pitcher_id=2, park_factor=1.02)
        p["team_state"] = {"HOME": dict(rf=4.8, ra=4.), "AWAY": dict(rf=4.2, ra=4.6)}
        p["starter_state"] = {"1": dict(era=3.5, gs=22, k=25., bb=6.), "2": dict(era=4.5, gs=24, k=21., bb=9.)}
        material = dict(pins={}, teams=p["team_state"], starters=p["starter_state"])
    else:
        p["model_id"] = baseline.IDS[league]
        p["prior"] = {"nba": 110., "nhl": 3., "mls": 1.4}[league]
        p["team_state"] = {t: dict(n=20, **{"for": p["prior"] + delta, "against": p["prior"],
                                             "last": "2026-09-20T20:00Z"}) for t, delta in [("H", .2), ("A", -.1)]}
        n = len(baseline.FEATURES)
        p["fitted_model"] = (dict(home_goals=head(n, "poisson", .4), away_goals=head(n, "poisson", .2))
            if league == "mls" else dict(winner=head(n, "logistic", .1), margin=head(n, "linear", 1.),
                                        total=head(n, "linear", 2 * p["prior"])))
        material = dict(model=p["fitted_model"], state=p["team_state"], prior=p["prior"])
    # Real code-pin checks execute in the package loader; these synthetic fixtures
    # do not bypass runtime byte integrity merely to test numeric invariance.
    root = Path(__file__).resolve().parents[1]
    files = ["models/current/common.py", "models/current/linear.py", "pipelines/cards/adapters/" + league + ".py"]
    files.append("models/current/" + (league if league in {"cfb", "wnba", "mlb"} else "baseline") + ".py")
    p["code_pins"] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
    if league == "mlb":
        material["pins"] = p["code_pins"]
    p["model_sha256"] = digest(material)
    return p
