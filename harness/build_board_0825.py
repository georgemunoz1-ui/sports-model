"""The 2026-08-25 forecast board builder — COMMITTED, because the 8/24 builder died in a scratchpad.

Both the adaptive_v0_1 constants and the exact champion invocation for 8/24 were lost with that
session's uncommitted script; reconstruction was impossible without fabricating identities. This
builder is therefore a registered module: deterministic given the repo state, re-runnable, and
gated. Every input it reads is named below; every arm it emits carries its identity, seed and
version.

Arms per MLB game (five winner + three total), all price-independent:
    mlb.winner.EXPANDING_HOME_PRIOR    p = 0.520540 (1,684-game canonical pool, unchanged — 8/22-24
                                       results are not canonical and do not move it)
    mlb.winner.CHAMPION_V13            v13_sim, 30,000 trials (LEGACY_TRIAL_COUNT), keyed seed
    mlb.winner.CHALLENGER_ADAPTIVE     adaptive_v0_2 (harness/adaptive_challenger.py; v0_1 CLOSED)
    mlb.winner.CHALLENGER_WIDENED      logit(prior) + k * residual_f, k solved numerically to match
                                       the champion's cross-game dispersion on THIS slate
    mlb.total.EXPANDING_TOTAL_PRIOR / CHAMPION_V13, both NEVER_DECISION_BEARING

Starters resolve through build_ml_asof.sp_asof_strict (the registered parser — exact-width
dispatch, per-batter-faced percentages). An official TBD or a missing log takes the frozen CAP
rule: league-default inputs, the slot counted, the dose reduced. Names are never substituted.
"""

from __future__ import annotations

MODULE_ID = "build_board_0825"

import csv
import datetime as dt
import hashlib
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))

import adaptive_challenger as AC
import build_ml_asof as ASOF
import keyed_seed as KS
import run_v13_historical as V13
import widening_rule as WR

SLATE_DATE = "2026-08-25"
SLATE_PSV = f"data/mlb/slates/{SLATE_DATE}_slate.psv"
PITCHERS = "data/backfill/mlb/2026/pitchers.csv"
PARKS = "data/backfill/mlb/2026/park_factors.json"
RESULTS = "data/backfill/mlb/2026/results.csv"
PRIOR_P = 0.5205399061032864          # 1,684-game pool; unchanged, and why is stated above
PRIOR_TOTAL = 8.991092636579573
TRIALS = 30000
VENUE = {  # home team -> park name, for park_factors.json lookup
    "Detroit Tigers": "Comerica Park", "Miami Marlins": "loanDepot park",
    "Washington Nationals": "Nationals Park", "New York Yankees": "Yankee Stadium",
    "Toronto Blue Jays": "Rogers Centre", "New York Mets": "Citi Field",
    "Atlanta Braves": "Truist Park", "Chicago White Sox": "Rate Field",
    "St. Louis Cardinals": "Busch Stadium", "Los Angeles Angels": "Angel Stadium",
    "Arizona Diamondbacks": "Chase Field", "San Diego Padres": "Petco Park",
    "Athletics": "Sutter Health Park", "Seattle Mariners": "T-Mobile Park",
    "San Francisco Giants": "Oracle Park",
}


def name_to_pid():
    return {r["name"]: r["id"] for r in csv.DictReader(open(PITCHERS))}


def team_form_rf_ra():
    """Full-season per-game runs for/against from canonical rows strictly before the slate."""
    rf, ra, n = {}, {}, {}
    for r in csv.DictReader(open(RESULTS)):
        if not (r["status"] == "final" and r["result_status"] == "FINAL"
                and r["source_tier"] == "1" and r["date"] < SLATE_DATE):
            continue
        aw, hm = AC._abbr(r["away"]), AC._abbr(r["home"])
        a, h = int(r["away_score"]), int(r["home_score"])
        for t, f_, a_ in ((aw, a, h), (hm, h, a)):
            rf[t] = rf.get(t, 0.0) + f_; ra[t] = ra.get(t, 0.0) + a_; n[t] = n.get(t, 0) + 1
    return ({t: rf[t] / n[t] for t in n}, {t: ra[t] / n[t] for t in n}, n)


def load_slate():
    rows = []
    for ln in open(SLATE_PSV):
        f = ln.strip().split("|")
        rows.append({"gamePk": f[0], "away": f[1], "home": f[2], "start_utc": f[3],
                     "away_sp": f[4], "home_sp": f[5]})
    return rows


def starter(pid_map, name):
    """(sp_dict_for_v13, status, rs_or_None). CAP on TBD or missing/immature log — never a guess."""
    if name == "TBD":
        return V13._sp({}), "OFFICIAL_TBD_CAP", None
    pid = pid_map.get(name)
    if pid is None:
        return V13._sp({}), f"NO_PID_CAP({name})", None
    feats, flags = ASOF.sp_asof_strict(pid, SLATE_DATE, set())
    if feats is None:
        return V13._sp({}), f"NO_LOG_CAP({flags['reason']})", None
    sp = {"era": feats["era"], "gs": feats["gs"], "k": feats["k_pct"], "bb": feats["bb_pct"]}
    return sp, "RESOLVED", V13.rs(sp["era"], sp["gs"], sp["k"], sp["bb"])


def build():
    pid_map = name_to_pid()
    rf, ra, ng = team_form_rf_ra()
    form, form_n = AC.form_table(SLATE_DATE)
    parks = json.load(open(PARKS))
    slate = load_slate()
    evidence = {
        "results_sha256": hashlib.sha256(open(RESULTS, "rb").read()).hexdigest(),
        "slate_sha256": hashlib.sha256(open(SLATE_PSV, "rb").read()).hexdigest(),
        "information_cutoff": "canonical rows strictly before " + SLATE_DATE +
                              " (latest canonical date 2026-08-21)",
    }
    games, adaptive_residuals = [], []
    for g in slate:
        aab, hab = AC._abbr(g["away"]), AC._abbr(g["home"])
        gid = f"mlb:{aab}@{hab}"
        spa, sa_status, rs_a = starter(pid_map, g["away_sp"])
        sph, sh_status, rs_h = starter(pid_map, g["home_sp"])
        capped = int(sa_status != "RESOLVED") + int(sh_status != "RESOLVED")
        dose = 1.0 - 0.25 * capped if capped else 1.0
        if "OFFICIAL_TBD" in sa_status or "OFFICIAL_TBD" in sh_status:
            dose = 0.5
        pf = parks.get(VENUE.get(g["home"], ""), 1.0)
        seed = KS.seed_for(f"mlb.winner.CHAMPION_V13.{TRIALS}", SLATE_DATE, gid, "v13_1")
        sim = V13.v13_sim(spa, sph, rf.get(aab), ra.get(aab), rf.get(hab), ra.get(hab),
                          pf, seed, TRIALS)
        res_f = AC.residual(aab, hab, form, rs_a, rs_h)
        adaptive_residuals.append(res_f)
        games.append({"game": gid, "gamePk": g["gamePk"], "start_utc": g["start_utc"],
                      "away": g["away"], "home": g["home"],
                      "away_sp": g["away_sp"], "home_sp": g["home_sp"],
                      "sp_status": {"away": sa_status, "home": sh_status},
                      "starter_slots_capped": capped, "information_dose": dose,
                      "park_factor": pf, "seed": seed, "sim": sim, "residual_f": res_f,
                      "p_adaptive": AC.probability(PRIOR_P, res_f)})
    champs = [g["sim"]["p_home"] for g in games]
    mean = sum(champs) / len(champs)
    target_sd_pp = 100 * math.sqrt(sum((p - mean) ** 2 for p in champs) / len(champs))
    wide = WR.solve_k(PRIOR_P, adaptive_residuals, target_sd_pp)
    return games, wide, target_sd_pp, evidence


def freeze(out_path=f"cards/{SLATE_DATE}_board.json"):
    """Assemble, hash and write the frozen board. Deterministic given the repo state."""
    import wnba_model_v1 as W
    games, wide, target, ev = build()
    k = wide["k"]

    def logit(p): return math.log(p / (1 - p))
    def sig(z): return 1 / (1 + math.exp(-z))

    mlb_rows = []
    for g in games:
        base = {"game": g["game"], "sport": "mlb", "gamePk": g["gamePk"],
                "game_start_utc": g["start_utc"], "away_starter": g["away_sp"],
                "home_starter": g["home_sp"], "sp_status": g["sp_status"],
                "starter_slots_capped": g["starter_slots_capped"],
                "resolved_information_dose": g["information_dose"],
                "park_factor": g["park_factor"], "forecast_status": "FORECAST_REGISTERED",
                "action_status": "PASS_REFERENCE_ONLY", "lineups": "UNCONFIRMED_AT_REGISTRATION"}
        sim = g["sim"]
        mlb_rows += [
            dict(base, arm="mlb.winner.EXPANDING_HOME_PRIOR", target="winner", p_home=PRIOR_P),
            dict(base, arm="mlb.winner.CHAMPION_V13", target="winner", p_home=sim["p_home"],
                 simulation_trials=TRIALS, simulation_seed=g["seed"], simulation_version="v13_1",
                 trial_standard="LEGACY_TRIAL_COUNT",
                 monte_carlo_sd_pp=100 * sim["mc_se"]),
            dict(base, arm="mlb.winner.CHALLENGER_ADAPTIVE", target="winner",
                 p_home=g["p_adaptive"], residual_f=g["residual_f"],
                 simulation_trials=0, simulation_version=AC.IDENTITY,
                 identity_note=AC.SUPERSEDES),
            dict(base, arm="mlb.winner.CHALLENGER_WIDENED", target="winner",
                 p_home=sig(logit(PRIOR_P) + k * g["residual_f"]),
                 simulation_version=f"widened({AC.IDENTITY})", widening_k=k),
            dict(base, arm="mlb.total.EXPANDING_TOTAL_PRIOR", target="total",
                 projected_total=PRIOR_TOTAL, target_authority="NEVER_DECISION_BEARING"),
            dict(base, arm="mlb.total.CHAMPION_V13", target="total",
                 projected_total=sim["proj_total"], target_authority="NEVER_DECISION_BEARING",
                 simulation_trials=TRIALS, simulation_seed=g["seed"]),
        ]

    wgames = W.build_games()
    rows, ts, lg = W.make_rows(wgames)
    model = W.fit_full(rows)
    wsl = [("CHI", "CON", "2026-08-25T23:00:00Z", "1022600284"),
           ("PDX", "DAL", "2026-08-26T00:00:00Z", "1022600285"),
           ("WAS", "PHX", "2026-08-26T02:00:00Z", "1022600286")]
    preds = W.predict_slate(model, ts, lg, [(a, h, t) for a, h, t, _ in wsl])
    W_PRIOR = 0.536585
    wnba_rows = []
    for (a, h, t, gid), pr in zip(wsl, preds):
        wb = {"game": f"wnba:{a}@{h}", "sport": "wnba", "official_game_id": gid,
              "game_start_utc": t, "personnel": "PERSONNEL_UNVERIFIED",
              "forecast_status": "FORECAST_REGISTERED",
              "staleness_days": 34, "action_status": "ACTION_BLOCKED",
              "evidence_class": "DIAGNOSTIC_ONLY", "promotion_eligible": False,
              "block_reason": "feature state frozen 2026-07-22, 34 days stale against a 21-day "
                              "ceiling; the staged pool does not contain this slate"}
        wnba_rows += [
            dict(wb, arm="wnba.winner.EXPANDING_HOME_PRIOR", target="winner", p_home=W_PRIOR,
                 action_status="PASS_REFERENCE_ONLY", block_reason=None),
            dict(wb, arm="wnba.winner.CHAMPION_WNBA_SHADOW", target="winner",
                 p_home=pr["p_home"]),
            dict(wb, arm="wnba.winner.NEGATIVE_CONTROL", target="winner", p_home=W_PRIOR,
                 action_status="PASS_REFERENCE_ONLY", block_reason=None,
                 control_note="reproduces the prior exactly, by construction"),
            dict(wb, arm="wnba.margin.CHAMPION_WNBA_SHADOW", target="margin",
                 projected_home_margin=pr["margin_home"],
                 target_authority="NEVER_DECISION_BEARING"),
            dict(wb, arm="wnba.total.CHAMPION_WNBA_SHADOW", target="total",
                 projected_total=pr["total"], target_authority="NEVER_DECISION_BEARING"),
        ]

    def cohort_hash(rows_):
        return hashlib.sha256(json.dumps(rows_, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()

    board = {
        "record_id": f"BOARD-{SLATE_DATE}",
        "slate_date": SLATE_DATE,
        "generated_at_utc_self_asserted": dt.datetime.now(dt.timezone.utc)
                                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prospectivity": "SELF_ASSERTED_LOCAL until the CI anchor on this push lands",
        "builder": "harness/build_board_0825.py (COMMITTED — the 8/24 builder died uncommitted)",
        "board_scope": {"n_games": 18, "mlb": 15, "wnba": 3},
        "SEPARATION": "MLB and WNBA are separate cohorts: separate hashes, cluster counts and "
                      "promotion denominators. Never pooled.",
        "PRIORS": {"mlb_home": {"p": PRIOR_P, "n": 1684,
                                "unchanged_because": "no canonical result exists after 2026-08-21"},
                   "mlb_total": {"runs": PRIOR_TOTAL, "n": 1684},
                   "wnba_home": {"p": W_PRIOR, "n": 21, "evidence": "PROVISIONAL"}},
        "WIDENING": {"formula": "logit(p_wide) = logit(prior) + k * residual_f",
                     "target_sd_pp": target, "solved_k": k, "solver": wide},
        "ADAPTIVE_IDENTITY": {"identity": AC.IDENTITY, "supersedes": AC.SUPERSEDES,
                              "constants": {"W_FORM": AC.W_FORM, "W_SP": AC.W_SP,
                                            "PRIOR_STRENGTH": AC.PRIOR_STRENGTH,
                                            "FORM_DAYS": AC.FORM_DAYS}},
        "EVIDENCE": ev,
        "cohort_hashes": {"mlb": cohort_hash(mlb_rows), "wnba": cohort_hash(wnba_rows)},
        "mlb": {"cohort_id": f"mlb:{SLATE_DATE}", "n_games": 15, "rows": mlb_rows},
        "wnba": {"cohort_id": f"wnba:{SLATE_DATE}", "n_games": 3, "rows": wnba_rows},
        "action_authority": "NONE — no market board is captured for this slate "
                            "(FORECAST_ONLY_NO_MARKET_GRADE) and the system is "
                            "SYSTEM_NOT_DECISION_READY. Prices, if captured pregame, attach only "
                            "as a separately hashed overlay.",
        "LEDGERS": {"model_authorized_wagers_usd": 0, "n_bets": 0},
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(board, fh, indent=1, sort_keys=True)
    return board


if __name__ == "__main__":
    if "--freeze" in sys.argv:
        board = freeze()
        print("FROZEN", board["record_id"], "| mlb", board["cohort_hashes"]["mlb"][:8],
              "| wnba", board["cohort_hashes"]["wnba"][:8])
        raise SystemExit(0)
    games, wide, target, ev = build()
    print(f"{len(games)} games | champion cross-game SD {target:.4f}pp | widening: "
          f"{wide.get('status')} k={wide.get('k')}")
    for g in games:
        print(f"  {g['game']:<14} V13 {g['sim']['p_home']:.4f}  adapt {g['p_adaptive']:.4f}  "
              f"tot {g['sim']['proj_total']:>6.2f}  dose {g['information_dose']}  "
              f"caps {g['starter_slots_capped']} [{g['sp_status']['away']}/{g['sp_status']['home']}]")
