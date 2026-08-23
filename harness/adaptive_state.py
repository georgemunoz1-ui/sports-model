#!/usr/bin/env python3
"""ADAPTIVE STATE — ratings that learn, shrunk so one bad night cannot move them much.

OWNER SPECIFICATION 2026-08-23. The FAST layer: expanding Bayesian home prior, team offensive and
defensive strength, hierarchical pitcher profiles, and recency with PREREGISTERED decay.

    "posterior pitcher rating = historical prior + new performance evidence.
     One bad start should move an established pitcher very little; it can move a rookie more,
     while also maintaining wider uncertainty."

    "Use frozen decay rules rather than selecting the best lookback after seeing results.
     Test these as challengers. Do not silently choose whichever window won yesterday."

THE SHRINKAGE IS THE WHOLE MECHANISM. A rating that updates by simple averaging moves as far on a
rookie's second start as on an ace's thirtieth, which is how a model learns to chase. A hierarchical
posterior weights new evidence by how much the prior already knows: with a prior strength of k
starts, one new start carries weight 1/(k+1). For an established starter that is a few percent; for
a debut it is most of the estimate — AND the debut carries a far wider posterior interval, which is
what the action screen consumes downstream.

WINDOWS ARE PREREGISTERED, NOT CHOSEN. Every decay window in this module is a frozen constant with a
registration date. Selecting a lookback after seeing which one won is the oldest way to manufacture
a backtest, and it is indistinguishable from learning when you only look at the result. Alternatives
are declared as CANDIDATES and must be run as challengers through the paired evaluation, never
swapped in.

TEMPORAL SAFETY IS NOT OPTIONAL HERE. Every builder takes an as-of cutoff and refuses to read a game
at or after it. A rating is a function of a date, not of "now".
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(BASE, "data/backfill/mlb/2026/results.csv")

# ---------------------------------------------------------------------------------------------
# PREREGISTERED WINDOWS. Frozen 2026-08-23. Changing any of these is a SLOW-layer act (a formal
# model release), and an alternative is a CHALLENGER, never a substitution.
# ---------------------------------------------------------------------------------------------
REGISTERED_WINDOWS = {
    "team_form_days": {"value": 30, "registered_utc": "2026-08-23T00:00:00Z",
                       "candidates": [30, 60], "layer": "MEDIUM"},
    "bullpen_days": {"value": 3, "registered_utc": "2026-08-23T00:00:00Z",
                     "candidates": [3, 7], "layer": "MEDIUM"},
    "starter_prior_strength_starts": {"value": 10, "registered_utc": "2026-08-23T00:00:00Z",
                                      "candidates": [5, 10, 20], "layer": "MEDIUM"},
    "calibration_trailing_predictions": {"value": 150, "registered_utc": "2026-08-23T00:00:00Z",
                                         "candidates": [100, 150, 250], "layer": "MEDIUM"},
    "team_rating_prior_strength_games": {"value": 25, "registered_utc": "2026-08-23T00:00:00Z",
                                         "candidates": [15, 25, 40], "layer": "MEDIUM"},
}
WINDOWS_FROZEN_AT = "2026-08-23T00:00:00Z"

# Beta prior on the league home-win rate. alpha+beta is the pseudo-count; the centre is 0.5 so an
# empty pool gives EXACTLY 0.5 and the baseline-offset identity at zero residual is exact.
HOME_PRIOR_ALPHA = 10.0
HOME_PRIOR_BETA = 10.0

LEAGUE_MEAN_RUNS = 4.35     # the shrinkage target for team scoring rates


def window(name):
    w = REGISTERED_WINDOWS.get(name)
    if w is None:
        raise KeyError(f"{name!r} is not a preregistered window; a window not registered before use "
                       f"is a window chosen after seeing the result")
    return w["value"]


def window_change_is_a_challenger(name, proposed):
    """(ok, reason). Never returns ok=True for an in-place swap. This exists so the refusal is a
    call site rather than a convention someone can forget."""
    w = REGISTERED_WINDOWS.get(name)
    if w is None:
        return False, f"{name!r} is not a registered window"
    if proposed == w["value"]:
        return False, f"{name} is already {proposed}"
    known = proposed in w["candidates"]
    tail = ("It is a preregistered candidate." if known else
            "It is not even in the preregistered candidate set, so it was chosen after seeing "
            "results.")
    return False, (f"{name} {w['value']} -> {proposed}: this is a CHALLENGER, not a substitution. "
                   f"Register it alongside the champion, evaluate paired, and promote through the "
                   f"gates. {tail}")


def load_results(path=None):
    p = path or RESULTS
    if not os.path.exists(p):
        return []
    return list(csv.DictReader(open(p)))


def asof(rows, cutoff_date, tier_filter=("1",)):
    """Completed games STRICTLY BEFORE the cutoff date, from the permitted evidence tiers.

    Strictly before, always: a rating that can see the day it is forecasting is not a rating."""
    out = []
    for r in rows:
        if str(r.get("status", "")).lower() != "final":
            continue
        if (r.get("date") or "") >= cutoff_date:
            continue
        if tier_filter is not None and str(r.get("source_tier", "")) not in tier_filter:
            continue
        out.append(r)
    return sorted(out, key=lambda r: (r.get("date", ""), r.get("game_id", "")))


def home_prior_beta(cutoff_date, rows=None, alpha=HOME_PRIOR_ALPHA, beta=HOME_PRIOR_BETA,
                    tier_filter=("1",)):
    """Expanding Bayesian home prior: (wins + alpha) / (games + alpha + beta), with its interval."""
    rows = load_results() if rows is None else rows
    pool = [r for r in asof(rows, cutoff_date, tier_filter) if r.get("home_win") not in (None, "")]
    n = len(pool)
    w = sum(int(r["home_win"]) for r in pool)
    a, b = w + alpha, (n - w) + beta
    mean = a / (a + b)
    var = (a * b) / (((a + b) ** 2) * (a + b + 1))
    return {"p_home_prior": mean, "prior_games_n": n, "prior_home_wins": w,
            "posterior_alpha": a, "posterior_beta": b,
            "prior_sd": math.sqrt(var),
            "prior_cutoff_date": cutoff_date,
            "prior_cutoff_utc": f"{cutoff_date}T00:00:00Z",
            "prior_last_game_date": (pool[-1].get("date") if pool else None),
            "prior_source_hash": hashlib.sha256(json.dumps(
                [[r.get("game_id"), r.get("date"), int(r["home_win"])] for r in pool],
                separators=(",", ":")).encode()).hexdigest()}


# ---------------------------------------------------------------------------------------------
# TEAM RATINGS — shrunk scoring rates, updated after every settlement.
# ---------------------------------------------------------------------------------------------

# TEAM IDENTITY IS FRAGMENTED IN results.csv AND MUST BE NORMALISED BEFORE ANY RATING IS BUILT.
# Rows dated before 2026-07-19 carry FULL NAMES ("Atlanta Braves"); rows from 2026-07-19 carry
# ABBREVIATIONS ("ATL"). An unnormalised group-by therefore returns 62 keys for a 30-team league and
# splits every team's season in two. It does this SILENTLY: the ratings still look plausible, they
# are just built from a quarter of the games and shrunk far harder toward the league mean than they
# should be. ATL had 23 games under its abbreviation and 97 more under its full name.
# daily_card.py has always normalised (its ABBR map); this module did not, so the CHALLENGER arm
# was affected and the CHAMPION was not.
TEAM_ABBR = {
    "Arizona Diamondbacks": "AZ", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
    "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Athletics": "ATH", "Oakland Athletics": "ATH",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD",
    "San Francisco Giants": "SF", "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB", "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH", "OAK": "ATH", "CHW": "CWS", "ARI": "AZ",
}
EXPECTED_TEAMS = 30


def normalize_team(t):
    """One canonical abbreviation per franchise. An unmapped long name is returned unchanged so it
    shows up as an anomaly rather than being silently folded into some other team."""
    if t is None:
        return None
    return TEAM_ABBR.get(t, t)


def team_identity_audit(rows=None, cutoff_date=None, tier_filter=("1",)):
    """Positive evidence that the pool resolves to one key per franchise."""
    rows = load_results() if rows is None else rows
    pool = asof(rows, cutoff_date, tier_filter) if cutoff_date else rows
    raw, norm = set(), set()
    for r in pool:
        for k in ("away", "home"):
            if r.get(k):
                raw.add(r[k]); norm.add(normalize_team(r[k]))
    unmapped = sorted(t for t in norm if len(t) > 4)
    return {"raw_keys": len(raw), "normalised_keys": len(norm),
            "expected": EXPECTED_TEAMS,
            "ok": len(norm) == EXPECTED_TEAMS and not unmapped,
            "unmapped_long_names": unmapped,
            "note": ("raw_keys above expected means the source mixes naming conventions; "
                     "normalised_keys is what any rating must be grouped by")}


def team_ratings(cutoff_date, rows=None, tier_filter=("1",),
                 prior_strength=None, league_mean=LEAGUE_MEAN_RUNS):
    """Offensive and defensive runs-per-game per team, shrunk toward the league mean.

    A team with three games played does not get a rating built from three games: it gets the league
    mean nudged by three games. The shrinkage weight is n / (n + k) with k the preregistered prior
    strength, so early-season noise cannot produce a confident extreme."""
    rows = load_results() if rows is None else rows
    k = window("team_rating_prior_strength_games") if prior_strength is None else prior_strength
    acc = {}
    for r in asof(rows, cutoff_date, tier_filter):
        try:
            a, h = int(r["away_score"]), int(r["home_score"])
        except (KeyError, TypeError, ValueError):
            continue
        for team, scored, allowed in ((normalize_team(r.get("away")), a, h),
                                      (normalize_team(r.get("home")), h, a)):
            if not team:
                continue
            d = acc.setdefault(team, {"n": 0, "scored": 0, "allowed": 0})
            d["n"] += 1; d["scored"] += scored; d["allowed"] += allowed
    out = {}
    for team, d in acc.items():
        n = d["n"]
        w = n / (n + k) if (n + k) else 0.0
        off = w * (d["scored"] / n) + (1 - w) * league_mean if n else league_mean
        dfn = w * (d["allowed"] / n) + (1 - w) * league_mean if n else league_mean
        out[team] = {"games": n, "shrink_weight": w,
                     "off_rpg": off, "def_rpg": dfn,
                     "raw_off_rpg": (d["scored"] / n) if n else None,
                     "raw_def_rpg": (d["allowed"] / n) if n else None}
    return {"cutoff_date": cutoff_date, "prior_strength_games": k, "league_mean": league_mean,
            "identity_audit": team_identity_audit(rows, cutoff_date, tier_filter),
            "teams": out}


# ---------------------------------------------------------------------------------------------
# HIERARCHICAL PITCHER PROFILES — the owner's central requirement.
# ---------------------------------------------------------------------------------------------

def pitcher_posterior(prior_mean, prior_strength_starts, observations, obs_sd=2.60):
    """posterior = historical prior + new performance evidence, weighted by what the prior knows.

    observations: list of per-start values (e.g. runs allowed per nine). The posterior mean is
        (k * prior_mean + n * obs_mean) / (k + n)
    so one new start carries weight 1/(k+1). With the registered k=10, one bad start moves an
    established pitcher by about 9% of the gap to that start; a debut (k inherited but n=1 against
    no history of its own) is dominated by it.

    THE UNCERTAINTY MATTERS AS MUCH AS THE MEAN. The posterior sd falls as sqrt(1/(k+n)), so a
    pitcher with one start keeps a wide interval and the action screen downstream sees it. A model
    that updates the mean but not the interval has learned nothing about how little it knows."""
    obs = [float(x) for x in (observations or [])]
    n = len(obs)
    k = float(prior_strength_starts)
    if k <= 0:
        raise ValueError("prior strength must be positive; a zero-strength prior is no prior")
    mean = (k * prior_mean + sum(obs)) / (k + n)
    # CONJUGATE FORM. Expressing the prior as "worth k observations of the same spread" makes the
    # posterior variance obs_sd^2/(k+n), which is monotone decreasing in n by construction. The
    # first version of this used a two-term mixture whose prior weight fell as k/(k+n)^2 while the
    # evidence weight rose as n/(k+n)^2, so with a wide observation spread the interval WIDENED for
    # the first several starts. A posterior that gets less certain as evidence arrives is not a
    # posterior, and the monotonicity fixture is what caught it.
    sd = obs_sd / math.sqrt(k + n)
    return {"posterior_mean": mean, "posterior_sd": sd, "n_observations": n,
            "prior_mean": prior_mean, "prior_strength_starts": k,
            "evidence_weight": n / (k + n) if (k + n) else 0.0,
            "shift_from_prior": mean - prior_mean}


ESTABLISHED = "ESTABLISHED"
DEVELOPING = "DEVELOPING"
DEBUT = "DEBUT"
NO_PROFILE = "NO_PROFILE"


def pitcher_tier(career_starts):
    if career_starts is None:
        return NO_PROFILE
    if career_starts >= 30:
        return ESTABLISHED
    if career_starts >= 5:
        return DEVELOPING
    if career_starts >= 1:
        return DEBUT
    return NO_PROFILE


def pitcher_profile(name, career_starts, career_mean, season_observations,
                    league_mean=4.20, prior_strength=None):
    """A full hierarchical profile. A pitcher with NO history falls back to the LEAGUE mean with the
    widest interval — which is exactly the CAP slot the information class already names. The
    fallback is not a number pretending to be knowledge; it carries its own uncertainty."""
    tier = pitcher_tier(career_starts)
    k = window("starter_prior_strength_starts") if prior_strength is None else prior_strength
    if tier == NO_PROFILE:
        # a league-average fallback: the prior IS the league mean, and the strength is deliberately
        # LOW so that the first real evidence moves it, while the sd stays wide
        # a weak prior AND a wider assumed spread: an unknown arm is both less anchored and more
        # variable, and both must show up in the interval the action screen consumes
        post = pitcher_posterior(league_mean, max(k * 0.2, 1.0), season_observations, obs_sd=3.20)
        post["fallback"] = "LEAGUE_AVERAGE_CAP"
    else:
        # an established pitcher's prior is strong in proportion to his career sample
        strength = k * (2.0 if tier == ESTABLISHED else 1.0 if tier == DEVELOPING else 0.5)
        post = pitcher_posterior(career_mean, strength, season_observations)
        post["fallback"] = None
    post.update({"pitcher": name, "career_starts": career_starts, "tier": tier})
    return post


def selftest():
    f = []
    ROWS = []
    for i in range(40):
        ROWS.append({"status": "final", "date": f"2026-06-{i%28+1:02d}", "game_id": f"g{i}",
                     "away": "AAA", "home": "BBB", "away_score": "3", "home_score": "5",
                     "home_win": "1", "source_tier": "1"})
    ROWS.append({"status": "final", "date": "2026-07-01", "game_id": "same", "away": "AAA",
                 "home": "BBB", "away_score": "9", "home_score": "0", "home_win": "0",
                 "source_tier": "1"})
    ROWS.append({"status": "final", "date": "2026-06-05", "game_id": "t3", "away": "AAA",
                 "home": "BBB", "away_score": "1", "home_score": "2", "home_win": "1",
                 "source_tier": "3"})

    # --- PREREGISTERED WINDOWS ------------------------------------------------------------------
    if window("team_form_days") != 30 or window("bullpen_days") != 3:
        f.append("a registered window does not hold its frozen value")
    try:
        window("whatever_won_yesterday")
        f.append("an UNREGISTERED window was served — a window not registered before use is one "
                 "chosen after seeing the result")
    except KeyError:
        pass
    # a window change is ALWAYS a challenger, never a swap — including for a preregistered candidate
    for name, proposed in (("team_form_days", 60), ("bullpen_days", 7),
                           ("calibration_trailing_predictions", 250),
                           ("team_form_days", 14)):
        ok, why = window_change_is_a_challenger(name, proposed)
        if ok:
            f.append(f"{name} -> {proposed} was permitted as an in-place substitution")
        if "CHALLENGER" not in why:
            f.append(f"{name} -> {proposed} refusal does not say it must run as a challenger")
    if "not even in the preregistered candidate set" not in \
            window_change_is_a_challenger("team_form_days", 14)[1]:
        f.append("a window OUTSIDE the preregistered candidate set was not named as such")
    if "not even in" in window_change_is_a_challenger("team_form_days", 60)[1]:
        f.append("a preregistered candidate was wrongly described as unregistered")

    # --- AS-OF SAFETY ----------------------------------------------------------------------------
    pool = asof(ROWS, "2026-07-01")
    if any(r["game_id"] == "same" for r in pool):
        f.append("a game dated ON the cutoff entered the as-of pool")
    if any(r["game_id"] == "t3" for r in pool):
        f.append("a tier-3 row entered the as-of pool under the tier-1 filter")
    if len(pool) != 40:
        f.append(f"as-of pool held {len(pool)} rows, expected 40")

    # --- BAYESIAN HOME PRIOR ----------------------------------------------------------------------
    hp = home_prior_beta("2026-07-01", ROWS)
    if hp["prior_games_n"] != 40 or hp["prior_home_wins"] != 40:
        f.append(f"home prior pool wrong: {hp['prior_games_n']} games, {hp['prior_home_wins']} wins")
    if abs(hp["p_home_prior"] - (40 + 10) / (40 + 20)) > 1e-12:
        f.append(f"the Beta posterior mean is wrong: {hp['p_home_prior']}")
    # 40-0 must NOT give a prior of 1.0 — that is the whole point of the Beta prior
    if hp["p_home_prior"] >= 1.0:
        f.append("a 40-0 pool produced a prior of 1.0; the Beta prior is not shrinking")
    # an EMPTY pool must be exactly .5 so the baseline-offset identity at zero residual is exact
    e = home_prior_beta("2026-01-01", ROWS)
    if e["prior_games_n"] != 0 or e["p_home_prior"] != 0.5:
        f.append(f"an empty pool gave p={e['p_home_prior']}")
    # the interval must NARROW as evidence accumulates
    if not (home_prior_beta("2026-01-01", ROWS)["prior_sd"] > hp["prior_sd"]):
        f.append("the prior sd did not narrow as games accumulated")

    # --- TEAM RATINGS -----------------------------------------------------------------------------
    tr = team_ratings("2026-07-01", ROWS)
    bbb = tr["teams"]["BBB"]
    if abs(bbb["raw_off_rpg"] - 5.0) > 1e-9:
        f.append(f"raw offensive rate wrong: {bbb['raw_off_rpg']}")
    # SHRINKAGE: the rated value must sit strictly between the raw rate and the league mean
    if not (LEAGUE_MEAN_RUNS < bbb["off_rpg"] < bbb["raw_off_rpg"]):
        f.append(f"the shrunk rating {bbb['off_rpg']} is not between the league mean "
                 f"{LEAGUE_MEAN_RUNS} and the raw rate {bbb['raw_off_rpg']}")
    # a THREE-GAME team must be pulled much harder than a forty-game team
    few = [dict(ROWS[i]) for i in range(3)]
    for r in few:
        r["away"], r["home"] = "CCC", "DDD"
    tr2 = team_ratings("2026-07-01", ROWS + few)
    if not (abs(tr2["teams"]["DDD"]["off_rpg"] - LEAGUE_MEAN_RUNS) <
            abs(tr2["teams"]["BBB"]["off_rpg"] - LEAGUE_MEAN_RUNS)):
        f.append("a three-game team was not shrunk harder toward the league mean than a "
                 "forty-game team with the same raw rate")
    if tr2["teams"]["DDD"]["shrink_weight"] >= tr2["teams"]["BBB"]["shrink_weight"]:
        f.append("the shrink weight does not increase with sample size")

    # --- TEAM IDENTITY MUST NORMALISE BEFORE ANY RATING IS BUILT --------------------------------
    # The real defect: results.csv carries FULL NAMES before 2026-07-19 and ABBREVIATIONS after, so
    # an unnormalised group-by returned 62 keys for a 30-team league and split every season in two.
    MIXED = ([{"status": "final", "date": "2026-05-0%d" % (i + 1), "game_id": f"m{i}",
               "away": "New York Mets", "home": "Atlanta Braves", "away_score": "3",
               "home_score": "5", "home_win": "1", "source_tier": "1"} for i in range(9)] +
             [{"status": "final", "date": "2026-08-0%d" % (i + 1), "game_id": f"a{i}",
               "away": "NYM", "home": "ATL", "away_score": "3", "home_score": "5",
               "home_win": "1", "source_tier": "1"} for i in range(3)])
    tr_mixed = team_ratings("2026-08-23", MIXED)
    if set(tr_mixed["teams"]) != {"ATL", "NYM"}:
        f.append(f"a mixed-naming pool produced {sorted(tr_mixed['teams'])} instead of two "
                 f"canonical keys — every franchise's season is being split in two")
    if tr_mixed["teams"]["ATL"]["games"] != 12:
        f.append(f"ATL was built from {tr_mixed['teams']['ATL']['games']} games, not the 12 in the "
                 f"pool; the full-name rows were dropped")
    aud = tr_mixed["identity_audit"]
    if aud["raw_keys"] != 4 or aud["normalised_keys"] != 2:
        f.append(f"the identity audit miscounted: {aud}")
    for full, ab in (("Atlanta Braves", "ATL"), ("Oakland Athletics", "ATH"), ("CHW", "CWS"),
                     ("ARI", "AZ"), ("Athletics", "ATH")):
        if normalize_team(full) != ab:
            f.append(f"normalize_team({full!r}) = {normalize_team(full)!r}, expected {ab!r}")
    if normalize_team("ATL") != "ATL":
        f.append("an already-canonical abbreviation was rewritten")
    if normalize_team(None) is not None:
        f.append("a missing team was coerced")
    # an UNMAPPED long name must SHOW UP, never be folded into another team
    unk = [{"status": "final", "date": "2026-05-01", "game_id": "u", "away": "Portland Pilots",
            "home": "ATL", "away_score": "1", "home_score": "2", "home_win": "1",
            "source_tier": "1"}]
    au = team_identity_audit(unk)
    if au["ok"] or "Portland Pilots" not in au["unmapped_long_names"]:
        f.append("an unmapped long team name was silently accepted")
    # the LIVE repository must resolve to exactly 30 franchises
    try:
        live = team_ratings("2026-08-23")
        if not live["identity_audit"]["ok"]:
            f.append(f"the live results table does not resolve to 30 franchises: "
                     f"{live['identity_audit']}")
        if len(live["teams"]) != EXPECTED_TEAMS:
            f.append(f"the live ratings hold {len(live['teams'])} teams, expected {EXPECTED_TEAMS}")
    except (OSError, KeyError):
        pass

    # --- HIERARCHICAL PITCHER PROFILES: the owner's central requirement --------------------------
    # ONE BAD START moves an established pitcher very little and a debut a great deal.
    est = pitcher_profile("Ace", career_starts=120, career_mean=3.20, season_observations=[9.0])
    deb = pitcher_profile("Rookie", career_starts=1, career_mean=3.20, season_observations=[9.0])
    if not (abs(est["shift_from_prior"]) < abs(deb["shift_from_prior"])):
        f.append(f"one bad start moved the ESTABLISHED pitcher ({est['shift_from_prior']:.3f}) at "
                 f"least as much as the DEBUT ({deb['shift_from_prior']:.3f})")
    if abs(est["shift_from_prior"]) > 0.5:
        f.append(f"one bad start moved an established pitcher by {est['shift_from_prior']:.3f} "
                 f"runs — that is chasing, not learning")
    # ...and the debut keeps a WIDER interval while it moves more
    if not (deb["posterior_sd"] > est["posterior_sd"]):
        f.append(f"the debut's posterior sd {deb['posterior_sd']:.3f} is not wider than the "
                 f"established pitcher's {est['posterior_sd']:.3f}")
    # evidence weight must rise monotonically with observations
    ws = [pitcher_posterior(3.2, 10, [4.0] * n)["evidence_weight"] for n in (0, 1, 5, 20)]
    if ws != sorted(ws) or ws[0] != 0.0:
        f.append(f"evidence weight is not monotone in the number of observations: {ws}")
    # with NO observations the posterior IS the prior
    p0 = pitcher_posterior(3.2, 10, [])
    if abs(p0["posterior_mean"] - 3.2) > 1e-12 or p0["shift_from_prior"] != 0.0:
        f.append("with no new evidence the posterior is not the prior")
    # the sd must SHRINK as evidence accumulates
    sds = [pitcher_posterior(3.2, 10, [4.0] * n)["posterior_sd"] for n in (0, 1, 10, 50)]
    if sds != sorted(sds, reverse=True):
        f.append(f"the posterior sd does not narrow with evidence: {sds}")
    # a zero-strength prior is refused
    try:
        pitcher_posterior(3.2, 0, [4.0])
        f.append("a zero-strength prior was accepted; that is no prior at all")
    except ValueError:
        pass
    # tiers
    for cs, want in ((None, NO_PROFILE), (0, NO_PROFILE), (1, DEBUT), (4, DEBUT), (5, DEVELOPING),
                     (29, DEVELOPING), (30, ESTABLISHED), (200, ESTABLISHED)):
        if pitcher_tier(cs) != want:
            f.append(f"pitcher_tier({cs}) = {pitcher_tier(cs)}, expected {want}")
    # a pitcher with NO history falls back to the league mean and SAYS SO, with a wide interval
    nop = pitcher_profile("Unknown", career_starts=None, career_mean=None, season_observations=[])
    if nop["fallback"] != "LEAGUE_AVERAGE_CAP":
        f.append("a no-history pitcher did not declare its league-average fallback")
    if abs(nop["posterior_mean"] - 4.20) > 1e-9:
        f.append(f"the no-history fallback is not the league mean: {nop['posterior_mean']}")
    if not (nop["posterior_sd"] > est["posterior_sd"]):
        f.append("the league-average fallback does not carry a wider interval than a real profile")
    # an ESTABLISHED pitcher's prior must be strictly stronger than a DEBUT's
    a = pitcher_profile("A", 120, 3.2, [9.0])["prior_strength_starts"]
    b = pitcher_profile("B", 2, 3.2, [9.0])["prior_strength_starts"]
    if not (a > b):
        f.append(f"an established pitcher's prior strength {a} is not greater than a debut's {b}")

    print("adaptive_state selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("an unregistered window is served instead of refused",
     '        raise KeyError(f"{name!r} is not a preregistered window;', '        return 30  # (f"{name!r}'),
    ("a window change becomes an in-place substitution",
     '    return False, (f"{name} {w[\'value\']} -> {proposed}: this is a CHALLENGER',
     '    return True, (f"{name} {w[\'value\']} -> {proposed}: this is a CHALLENGER'),
    ("a window outside the candidate set is described as preregistered",
     '    known = proposed in w["candidates"]', "    known = True"),
    ("as-of leaks the cutoff day itself",
     '        if (r.get("date") or "") >= cutoff_date:', '        if (r.get("date") or "") > cutoff_date:'),
    ("as-of drops the tier filter",
     '        if tier_filter is not None and str(r.get("source_tier", "")) not in tier_filter:',
     "        if False:"),
    ("the home prior loses its Beta shrinkage, so 40-0 gives certainty",
     "    a, b = w + alpha, (n - w) + beta", "    a, b = w, (n - w)"),
    ("the prior interval no longer narrows with evidence",
     "    var = (a * b) / (((a + b) ** 2) * (a + b + 1))", "    var = 0.25"),
    ("team identity is not normalised, splitting every franchise in two",
     '        for team, scored, allowed in ((normalize_team(r.get("away")), a, h),\n                                      (normalize_team(r.get("home")), h, a)):',
     '        for team, scored, allowed in ((r.get("away"), a, h), (r.get("home"), h, a)):'),
    ("the abbreviation map is emptied, so full names never fold",
     "    return TEAM_ABBR.get(t, t)", "    return t"),
    ("an unmapped long name is hidden instead of surfaced",
     '    unmapped = sorted(t for t in norm if len(t) > 4)', "    unmapped = []"),
    ("the identity audit passes whatever the key count",
     '            "ok": len(norm) == EXPECTED_TEAMS and not unmapped,', '            "ok": True,'),
    ("team ratings are unshrunk raw rates",
     "        w = n / (n + k) if (n + k) else 0.0", "        w = 1.0"),
    ("team shrinkage is constant, so a 3-game team is treated like a 40-game team",
     "        w = n / (n + k) if (n + k) else 0.0", "        w = 0.5"),
    ("the pitcher posterior ignores the prior, so one start rewrites the rating",
     "    mean = (k * prior_mean + sum(obs)) / (k + n)",
     "    mean = (sum(obs) / n) if n else prior_mean"),
    ("the pitcher posterior weights the prior EQUALLY however much it knows",
     "    mean = (k * prior_mean + sum(obs)) / (k + n)",
     "    mean = (prior_mean + sum(obs)) / (1 + n)"),
    ("the posterior interval stops narrowing with evidence",
     "    sd = obs_sd / math.sqrt(k + n)", "    sd = obs_sd"),
    ("the posterior interval NARROWS for an unknown pitcher instead of widening",
     "        post = pitcher_posterior(league_mean, max(k * 0.2, 1.0), season_observations, obs_sd=3.20)",
     "        post = pitcher_posterior(league_mean, k * 5.0, season_observations, obs_sd=0.40)"),
    ("a zero-strength prior is accepted", "    if k <= 0:", "    if False:"),
    ("an established pitcher's prior is no stronger than a debut's",
     '        strength = k * (2.0 if tier == ESTABLISHED else 1.0 if tier == DEVELOPING else 0.5)',
     "        strength = k"),
    ("the league-average fallback stops declaring itself",
     '        post["fallback"] = "LEAGUE_AVERAGE_CAP"', '        post["fallback"] = None'),
    ("the pitcher tier boundary at 30 career starts moves",
     "    if career_starts >= 30:", "    if career_starts >= 10:"),
    ("a pitcher with no history is treated as a debut",
     "    if career_starts is None:\n        return NO_PROFILE", "    if False:\n        return NO_PROFILE"),
]


def mutation_suite(verbose=True):
    import subprocess as _sp, tempfile as _tf
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = [")
    j = src.index("\ndef mutation_suite", i)
    head, block, tail = src[:i], src[i:j], src[j:]
    surv, unapp = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapp.append(f"{name}: pattern not found"); continue
        mut = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mut == src:
            unapp.append(f"{name}: no-op"); continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mut); path = fh.name
        try:
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=180)
            killed = pr.returncode != 0
        except _sp.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}")
        if not killed:
            surv.append(name)
    for u in unapp:
        print(f"  UNAPPLIED  {u}")
    print(f"mutation suite: {len(MUTANTS)-len(surv)-len(unapp)}/{len(MUTANTS)} killed"
          f"{'' if not (surv or unapp) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return surv + unapp


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    if "--windows" in sys.argv:
        print(json.dumps(REGISTERED_WINDOWS, indent=1))
        sys.exit(0)
    print(__doc__)
