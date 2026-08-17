#!/usr/bin/env python3
"""Render a registered card as MODEL OUTPUT IN BETTING UNITS. No prices required.

WHY (owner, 2026-08-17): "I need the cards having model predictions/output. We can't be having a
blank card. That defeats the entire purpose of this process."

That criticism is correct and the fault was in the RENDERING, not the model. The 2026-08-17 v3 card
carries a full V13 simulation for all 11 games — win probability, projected total, run-line cover
probabilities, blowout probabilities, strikeout expectations — and it was being displayed as a table
of probabilities next to a column of dashes, because the moneyline/total columns are market fields
and no prices exist for this slate.

THE FIX RESTS ON A DISTINCTION THE PRICING FRAME ALREADY MAKES:

    model probability -> FAIR LINE          <- needs only the model
    posted price      -> break-even prob    <- needs the market
    edge = model probability - break-even   <- needs BOTH

The left column is a model output. It was simply never being rendered. A card with no posted price
is missing its EDGE, not its content: fair moneyline, fair run line, projected score, projected
total, blowout risk and strikeout lines are all computable right now, for every game, and they are
what the model is actually saying.

WHAT IS STILL NULL, AND STAYS NULL: edge, EV and selections. Those require a posted price and R1
forbids inventing one. They are reported as null WITH the reason rather than omitted, so the card
never implies a play it cannot support.

HOW THE EXTRA NUMBERS ARE OBTAINED. The stored card does not carry per-side projected scores, so
this module replays the slate under the FROZEN global-sequential RNG (seed 722, n=30000, games in
slate order) using a verbatim transcription of daily_card.py's sim(). Before rendering anything it
VERIFIES that the replay reproduces every stored field of the registered card exactly — home_wp,
proj_total, both run-line covers, both blowout probabilities. If any field disagrees the module
REFUSES to render, because a card whose numbers came from a slightly different sim is worse than no
card at all.

NOTE ON blow_home: daily_card computes mg = home - away, blow_h = mean(mg <= -5). So blow_home is
the probability the HOME team is BLOWN OUT, not the probability it wins big. Rendered under an
unambiguous label.

MEASUREMENT/RENDERING ONLY. Emits no forecast, registers nothing, changes no model parameter, RNG
policy, promotion gate or market input. It re-expresses an already-registered artifact.

Usage: python3 harness/card_render.py [--date 2026-08-17] [--card <path>] [--json] [--selftest]
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "engine"))
from hfa import CURRENT as HFA  # noqa: E402

LG_RPG, LG_ERA, LG_K, LG_BB = 4.45, 4.20, 22.0, 8.5
LG_BIP = 1 - (LG_K + LG_BB) / 100
FROZEN_N, FROZEN_SEED = 30000, 722
RESULTS = "data/backfill/mlb/2026/results.csv"
PARKS = "data/backfill/mlb/2026/park_factors.json"


def _norm_ab():
    import csv
    sys.path.insert(0, os.path.join(BASE, "harness"))
    from rng_noise_study import _ab, team_form
    return _ab, team_form


def american(p):
    """Fair American odds for a probability. None outside (0,1) — never a fabricated price."""
    if p is None or not (0 < p < 1):
        return None
    return -round(100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def decimal(p):
    return round(1 / p, 3) if p and 0 < p < 1 else None


def fmt_am(o):
    return "—" if o is None else (f"+{o}" if o > 0 else str(o))


def _k(v):
    """Expected strikeouts, or an em dash. A TBD/short-log starter has NO K projection — printing
    0.00 there would read as 'we project zero strikeouts' rather than 'we have no projection'."""
    return "—" if v in (None, 0) else f"{v:.2f}"


def sim_full(asp, hsp, form, aw, hm, pf, n, rng):
    """Verbatim transcription of daily_card.py sim(), returning EVERY output it computes plus the
    per-side score means the stored card does not keep. Draw order is identical, so the numbers are
    the same draws the registered card used."""
    from rng_noise_study import _rfra

    def rs(sp):
        w = sp["gs"] / (sp["gs"] + 8)
        e = w * sp["era"] + (1 - w) * LG_ERA
        return max(2.2, e - ((sp["k"] - sp["bb"]) - 13.5) * 0.03)

    def bip(sp):
        return max(.45, 1 - (sp["k"] + sp["bb"]) / 100)

    rf_a, ra_a = _rfra(form, aw)
    rf_h, ra_h = _rfra(form, hm)
    oa, oh = rf_a / LG_RPG, rf_h / LG_RPG
    pena, penh = .55 * ra_a + .45 * LG_RPG, .55 * ra_h + .45 * LG_RPG
    rah, raa = rs(hsp), rs(asp)
    pfa = 1 + (pf - 1) * (bip(hsp) / LG_BIP)
    pfh = 1 + (pf - 1) * (bip(asp) / LG_BIP)
    ip = np.clip(rng.normal(5.4, 1.3, n), 2, 8)
    ip2 = np.clip(rng.normal(5.4, 1.3, n), 2, 8)
    ma = (rah / 9 * ip + penh / 9 * (9 - ip)) * oa * pfa
    mh = (raa / 9 * ip2 + pena / 9 * (9 - ip2)) * oh * pfh * HFA
    sa = np.clip(1.8 + (hsp["k"] - LG_K) * .16, 1.2, 6)
    sh = np.clip(1.8 + (asp["k"] - LG_K) * .16, 1.2, 6)
    raA = rng.poisson(rng.gamma(sa, np.maximum(ma, .3) / sa))
    rhH = rng.poisson(rng.gamma(sh, np.maximum(mh, .3) / sh))
    tie = raA == rhH
    hx = rng.random(n) < (.5 + .04 * np.sign(pena - penh))
    hw = np.where(tie, hx, rhH > raA)
    mg = rhH - raA
    t_arr = raA + rhH + tie * rng.poisson(1.0, n)
    return {"hw": float(hw.mean()), "tot": float(t_arr.mean()),
            "rl_h": float(np.mean(mg >= 2)), "rl_a": float(np.mean(mg <= -2)),
            "blow_h": float(np.mean(mg <= -5)), "blow_a": float(np.mean(mg >= 5)),
            "proj_away": float(raA.mean()), "proj_home": float(rhH.mean()),
            "p_home_by_1": float(np.mean(mg == 1)), "p_away_by_1": float(np.mean(mg == -1)),
            "p_extras": float(tie.mean())}


def render(card_path):
    _ab, team_form = _norm_ab()
    card = json.load(open(card_path))
    rows = card["rows"]
    form = team_form(open(RESULTS).read())
    PARK = json.load(open(PARKS))
    rng = np.random.default_rng(FROZEN_SEED)

    out, mism = [], []
    for r in rows:
        pf = PARK.get(form[3].get(_ab(r["home"]), ""), 1.0)
        s = sim_full(r["asp_stats"], r["hsp_stats"], form, _ab(r["away"]), _ab(r["home"]),
                     pf, FROZEN_N, rng)
        v = r["v13"]
        # every stored field must reproduce, or the replay is not the card's sim
        for key, got, want in (("home_wp", round(s["hw"], 3), v["home_wp"]),
                               ("proj_total", round(s["tot"], 1), v["proj_total"]),
                               ("rl_home_cover", round(s["rl_h"], 3), v["rl_home_cover"]),
                               ("rl_away_cover", round(s["rl_a"], 3), v["rl_away_cover"]),
                               ("blow_home", round(s["blow_h"], 3), v["blow_home"]),
                               ("blow_away", round(s["blow_a"], 3), v["blow_away"])):
            if got != want:
                mism.append(f'{r["away"]}@{r["home"]} {key}: replay {got} vs card {want}')
        ph = v["home_wp"]
        out.append({
            "game": f'{r["away"]}@{r["home"]}', "gamePk": r["gamePk"], "time_utc": r["time"],
            "away": r["away"], "home": r["home"], "away_sp": r["asp"], "home_sp": r["hsp"],
            "starters_capped_to_league_average": r["capped"],
            "park_factor": r["park"],
            "moneyline": {
                "p_home": ph, "p_away": round(1 - ph, 3),
                "fair_home_american": american(ph), "fair_away_american": american(1 - ph),
                "fair_home_decimal": decimal(ph), "fair_away_decimal": decimal(1 - ph),
                "model_side": r["home"] if ph >= .5 else r["away"],
                "confidence_pp_from_coinflip": round(abs(ph - .5) * 100, 1),
            },
            "run_line": {
                "p_home_minus_1_5": v["rl_home_cover"], "p_away_minus_1_5": v["rl_away_cover"],
                "p_home_plus_1_5": round(1 - v["rl_away_cover"], 3),
                "p_away_plus_1_5": round(1 - v["rl_home_cover"], 3),
                "fair_home_minus_1_5_american": american(v["rl_home_cover"]),
                "fair_away_minus_1_5_american": american(v["rl_away_cover"]),
                "fair_home_plus_1_5_american": american(1 - v["rl_away_cover"]),
                "fair_away_plus_1_5_american": american(1 - v["rl_home_cover"]),
            },
            "total": {
                "model_total": v["proj_total"],
                "proj_away_runs": round(s["proj_away"], 2), "proj_home_runs": round(s["proj_home"], 2),
                "p_over_posted_line": None, "p_under_posted_line": None,
                "reason_null": "no posted total on file for this slate",
            },
            "risk": {
                "p_home_blown_out_by_5plus": v["blow_home"],
                "p_away_blown_out_by_5plus": v["blow_away"],
                "p_one_run_game_home": round(s["p_home_by_1"], 3),
                "p_one_run_game_away": round(s["p_away_by_1"], 3),
                "p_extra_innings": round(s["p_extras"], 3),
            },
            "strikeouts_expected": {"away_sp": r["k_away"], "home_sp": r["k_home"]},
            "market": {"posted_ml_home": r["lines"]["ml_home"], "posted_ml_away": r["lines"]["ml_away"],
                       "posted_total": r["lines"]["total"], "break_even_prob": None,
                       "edge_pp": None, "ev_per_unit": None, "selection": None,
                       "reason_null": ("no posted price on file for 2026-08-17 and egress is 403, so "
                                       "break-even, edge, EV and selection are UNDEFINED. R1: reported "
                                       "null and flagged, never estimated.")},
        })
    if mism:
        return {"REFUSED": True, "mismatches": mism}
    out.sort(key=lambda g: -g["moneyline"]["confidence_pp_from_coinflip"])
    for i, g in enumerate(out, 1):
        g["model_confidence_rank"] = i
    return {"card": card_path, "date": card["date"], "mode": card["mode"],
            "model_id": rows[0]["model_id"], "games": len(out),
            "replay_verified_against_registered_card": True,
            "rendered_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rows": out}


def render_wnba(path="data/wnba/forecasts/2026-08-17_card.json"):
    """Same treatment for the WNBA shadow card. No sim replay: that model is a deterministic logistic,
    so its stored p_home IS the model output and only the fair-price conversion is added."""
    if not os.path.exists(path):
        return None
    c = json.load(open(path))
    rows = []
    for r in c["rows"]:
        ph = r["p_home"]
        rows.append({"game": f'{r["away"]}@{r["home"]}', "tip_utc": r["tip_utc"],
                     "p_home": round(ph, 4), "p_away": round(1 - ph, 4),
                     "fair_home_american": american(ph), "fair_away_american": american(1 - ph),
                     "fair_home_decimal": decimal(ph), "fair_away_decimal": decimal(1 - ph),
                     "model_side": r["home"] if ph >= .5 else r["away"],
                     "fair_spread_home": -round(r["margin_home"], 1),
                     "model_margin_home": r["margin_home"], "model_total": r["total"],
                     "coherence_gap_pp": r.get("coherence_gap_pp"),
                     "coherence_pass": r.get("coherence_pass"),
                     "games_used": r.get("games_used"),
                     "market": {"posted": None, "break_even_prob": None, "edge_pp": None,
                                "ev_per_unit": None, "selection": None,
                                "reason_null": "no posted WNBA price on file for this slate"}})
    return {"card": path, "date": c["slate_date"], "model_id": c["model_id"],
            "feature_state_as_of": c["feature_state_as_of"], "staleness_days": c["staleness_days"],
            "authority": c["authority"], "rows": rows}


def selftest():
    fails = []
    r = render("cards/2026-08-17_card_v3.json")
    if r.get("REFUSED"):
        fails.append(f"replay does not reproduce the registered card: {r['mismatches'][:2]}")
    else:
        if len(r["rows"]) != 11:
            fails.append(f"expected 11 games, got {len(r['rows'])}")
        for g in r["rows"]:
            m = g["moneyline"]
            if abs(m["p_home"] + m["p_away"] - 1) > 0.0011:
                fails.append(f'{g["game"]}: ML probabilities do not complement')
            # a fair line must round-trip back to its probability
            fa = m["fair_home_american"]
            back = (-fa) / (-fa + 100) if fa < 0 else 100 / (fa + 100)
            if abs(back - m["p_home"]) > 0.002:
                fails.append(f'{g["game"]}: fair ML {fa} does not round-trip to p={m["p_home"]}')
            if g["total"]["proj_away_runs"] + g["total"]["proj_home_runs"] > g["total"]["model_total"] + 0.01:
                fails.append(f'{g["game"]}: side projections exceed the projected total')
            if g["market"]["edge_pp"] is not None or g["market"]["selection"] is not None:
                fails.append(f'{g["game"]}: an edge or selection was produced with no posted price')
            side = g["moneyline"]["model_side"]
            if (side == g["home"]) != (m["p_home"] >= .5):
                fails.append(f'{g["game"]}: model_side disagrees with p_home')
    # falsification: a corrupted stored probability must be caught, not rendered over
    import copy, tempfile
    c = json.load(open("cards/2026-08-17_card_v3.json"))
    c2 = copy.deepcopy(c); c2["rows"][0]["v13"]["home_wp"] = 0.999
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(c2, f); tmp = f.name
    if not render(tmp).get("REFUSED"):
        fails.append("a card whose stored probability disagrees with the sim was rendered anyway")
    os.unlink(tmp)
    if american(0.5) != -100 or american(0.75) != -300 or american(0.25) != 300:
        fails.append("fair-odds conversion wrong at known points")
    if american(0) is not None or american(1) is not None or american(None) is not None:
        fails.append("a degenerate probability produced a price instead of None")
    if fails:
        print("card_render selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("card_render selftest: PASS (replay reproduces all 6 stored fields on 11/11 games; fair "
          "lines round-trip to their probabilities; side projections sum within the total; a "
          "corrupted stored probability is REFUSED; no edge or selection is produced without a price)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-08-17")
    ap.add_argument("--card", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    path = a.card or f"cards/{a.date}_card_v3.json"
    if not os.path.exists(path):
        path = f"cards/{a.date}_card.json"
    r = render(path)
    if r.get("REFUSED"):
        print("REFUSED — replay does not reproduce the registered card:")
        for m in r["mismatches"][:10]:
            print("  " + m)
        raise SystemExit(1)
    os.makedirs("data/audit", exist_ok=True)
    op = f'data/audit/card_render_{r["date"]}.json'
    json.dump(r, open(op, "w"), indent=1)
    if a.json:
        print(json.dumps(r, indent=1))
        raise SystemExit(0)
    print(f'MLB {r["date"]} — {r["games"]} games — {r["model_id"]}')
    print(f'replay verified against the registered card: {r["replay_verified_against_registered_card"]}\n')
    print(f'{"#":>2} {"game":<13}{"time":>7}  {"FAIR ML (a/h)":>16}  {"proj score":>11}{"tot":>6}'
          f'  {"FAIR RL -1.5 a/h":>18}  {"1-run":>6}{"XI":>6}  {"blowout a/h":>9}  {"K a/h":>11}')
    for g in r["rows"]:
        m, rl, t, k, rk = g["moneyline"], g["run_line"], g["total"], g["strikeouts_expected"], g["risk"]
        tag = "*" if g["starters_capped_to_league_average"] else " "
        print(f'{g["model_confidence_rank"]:>2}{tag}{g["game"]+("-"+g["gamePk"] if g["gamePk"].startswith("DH") else ""):<13}'
              f'{g["time_utc"]:>7}  {fmt_am(m["fair_away_american"]):>7}/{fmt_am(m["fair_home_american"]):<8}'
              f'{t["proj_away_runs"]:>5.2f}-{t["proj_home_runs"]:<5.2f}{t["model_total"]:>6.1f}'
              f'  {fmt_am(rl["fair_away_minus_1_5_american"]):>8}/{fmt_am(rl["fair_home_minus_1_5_american"]):<9}'
              f'{(rk["p_one_run_game_home"]+rk["p_one_run_game_away"])*100:>5.0f}%{rk["p_extra_innings"]*100:>5.0f}%'
              f'  {rk["p_away_blown_out_by_5plus"]*100:>3.0f}%/{rk["p_home_blown_out_by_5plus"]*100:>3.0f}%'
              f'  {_k(k["away_sp"]):>5}/{_k(k["home_sp"]):<5}')
    print("\n* = a starter is TBD/short-log, so that side runs on league-average pitching")
    print(f'wrote {op}')
    w = render_wnba(f'data/wnba/forecasts/{r["date"]}_card.json')
    if w:
        print(f'\nWNBA {w["date"]} — {len(w["rows"])} game(s) — {w["model_id"]}')
        print(f'  features as-of {w["feature_state_as_of"]} ({w["staleness_days"]}d stale) — SHADOW, wager authority NO')
        print(f'  {"game":<10}{"tip":>8}  {"FAIR ML (a/h)":>16}  {"fair spread":>12}{"total":>8}{"coh":>7}')
        for g in w["rows"]:
            print(f'  {g["game"]:<10}{g["tip_utc"][-6:]:>8}  '
                  f'{fmt_am(g["fair_away_american"]):>7}/{fmt_am(g["fair_home_american"]):<8}'
                  f'{g["home"] if False else "":>0}{g["fair_spread_home"]:>+12.1f}{g["model_total"]:>8.1f}'
                  f'{("ok" if g["coherence_pass"] else "FAIL"):>7}')
        json.dump(w, open(f'data/audit/card_render_wnba_{w["date"]}.json', "w"), indent=1)
    print("\nEDGE / EV / SELECTION: null for every game — no posted price on file and egress is 403. "
          "Fair lines above are MODEL output and need no market; edge needs both.")
