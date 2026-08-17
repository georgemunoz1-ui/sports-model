#!/usr/bin/env python3
"""Separate the FORM EFFECT from Monte-Carlo/RNG-coupling noise in the 8/17 cohort contrasts.

WHY (2026-08-17, external auditor): harness/daily_card.py drives every game from ONE global
np.random.default_rng(722), sequentially. numpy's gamma and poisson samplers are rejection-based, so
the NUMBER of underlying uniforms consumed depends on the parameters. Change team form -> lambdas
change -> draw counts change -> every subsequent draw, including in later games on the slate, is
re-coupled. Therefore the observed v2->v3 card delta of 0.455pp is

    observed = true parameter effect  +  RNG re-coupling noise

and bit-for-bit regeneration proves deterministic REPLAY, not a noise-free estimate. The auditor's
own probe (0.1% perturbation, 200 paired seeds) gave SD 0.237pp / mean|d| 0.192pp — material beside
0.455pp. This module measures both terms directly.

TWO STUDIES, same math either way:
  A) REPLICATION AT THE FROZEN SETTING. n=30000, R independent per-game keyed seeds, both arms run
     under the SAME seed per replicate. This is the distribution the single frozen card is one draw
     from. It answers: could 0.455pp be noise?
  B) HIGH-n EFFECT ESTIMATE. n=2,000,000 per replicate collapses MC error to ~0.035pp per run
     (sqrt(.25/n)); averaging R_HI runs tightens it further. The arm difference then estimates the
     TRUE parameter effect, with a Monte-Carlo CI.

The sim math is transcribed verbatim from harness/daily_card.py (lines 62-78) and verified against
it by `--verify-math`, which reproduces the registered v3 card probabilities exactly using the same
global-sequential RNG discipline. NOTHING here changes a model, a card, or a registered forecast:
this is measurement of an already-frozen artifact.

Usage: python3 harness/rng_noise_study.py [--reps 200] [--hi-reps 10] [--quick] [--verify-math]
"""
from __future__ import annotations
import csv, hashlib, json, os, subprocess, sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "engine"))
from hfa import CURRENT as HFA  # noqa: E402

LG_RPG = 4.45; LG_ERA = 4.20; LG_K = 22.0; LG_BB = 8.5
LG_BIP = 1 - (LG_K + LG_BB) / 100
PARK = json.load(open(os.path.join(BASE, "data/backfill/mlb/2026/park_factors.json")))
V2_COMMIT = "da6f44b"   # results.csv state the v2 card was built from
# MUST be daily_card.py's FULL map, verbatim. results.csv carries legacy rows written with full
# team names ("St. Louis Cardinals") alongside abbreviated ones; daily_card folds them into one team
# key. A reduced map silently splits every franchise into two, which is exactly the bug this
# transcription hit before --verify-math caught it.
ABBR = {"Arizona Diamondbacks": "AZ", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
        "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
        "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
        "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KC",
        "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
        "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
        "New York Yankees": "NYY", "Athletics": "ATH", "Philadelphia Phillies": "PHI",
        "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
        "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
        "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
        "OAK": "ATH", "CHW": "CWS", "ARI": "AZ"}


def _ab(t):
    return ABBR.get(t, t if len(t) <= 3 else t)


def team_form(results_text):
    """rf/ra/g/venue per team — transcribed from daily_card.py lines 29-37 (tier-blind, as the frozen
    card is). venue_of is last-final-row-wins and feeds the RAW park factor: the card stores
    round(pf,3) but sim() receives the unrounded value, so the study must recompute it."""
    rf, ra, g, venue_of = {}, {}, {}, {}
    for r in csv.DictReader(results_text.splitlines()):
        if r["status"] != "final" or r["total"] == "":
            continue
        a, h = _ab(r["away"]), _ab(r["home"])
        asc, hsc = int(r["away_score"]), int(r["home_score"])
        for t, f_, a_ in ((a, asc, hsc), (h, hsc, asc)):
            rf[t] = rf.get(t, 0) + f_; ra[t] = ra.get(t, 0) + a_; g[t] = g.get(t, 0) + 1
        venue_of[h] = r["venue"]
    return rf, ra, g, venue_of


def _rfra(form, t):
    rf, ra, g, _v = form
    return (rf.get(t, 0) / g[t] if g.get(t) else LG_RPG,
            ra.get(t, 0) / g[t] if g.get(t) else LG_RPG)


def _shrunk(e, gs):
    w = gs / (gs + 8)
    return w * e + (1 - w) * LG_ERA


def sim_p(asp, hsp, form, aw, hm, pf, n, rng):
    """p_home only. Verbatim transcription of daily_card.py sim() lines 63-76."""
    def rs(sp):
        return max(2.2, _shrunk(sp["era"], sp["gs"]) - ((sp["k"] - sp["bb"]) - 13.5) * 0.03)

    def bip(sp):
        return max(.45, 1 - (sp["k"] + sp["bb"]) / 100)

    rf_a, ra_a = _rfra(form, aw)
    rf_h, ra_h = _rfra(form, hm)
    oa = rf_a / LG_RPG; oh = rf_h / LG_RPG
    pena = .55 * ra_a + .45 * LG_RPG; penh = .55 * ra_h + .45 * LG_RPG
    rah, raa = rs(hsp), rs(asp)
    pfa = 1 + (pf - 1) * (bip(hsp) / LG_BIP); pfh = 1 + (pf - 1) * (bip(asp) / LG_BIP)
    ip = np.clip(rng.normal(5.4, 1.3, n), 2, 8); ip2 = np.clip(rng.normal(5.4, 1.3, n), 2, 8)
    ma = (rah / 9 * ip + penh / 9 * (9 - ip)) * oa * pfa
    mh = (raa / 9 * ip2 + pena / 9 * (9 - ip2)) * oh * pfh * HFA
    sa = np.clip(1.8 + (hsp["k"] - LG_K) * .16, 1.2, 6)
    sh = np.clip(1.8 + (asp["k"] - LG_K) * .16, 1.2, 6)
    raA = rng.poisson(rng.gamma(sa, np.maximum(ma, .3) / sa))
    rhH = rng.poisson(rng.gamma(sh, np.maximum(mh, .3) / sh))
    tie = raA == rhH
    hx = rng.random(n) < (.5 + .04 * np.sign(pena - penh))
    hw = np.where(tie, hx, rhH > raA)
    # MUST be drawn even though p_home does not use it: daily_card.py line 75 draws it, and the RNG
    # is global+sequential, so skipping it desynchronises every subsequent game on the slate.
    _ = raA + rhH + tie * rng.poisson(1.0, n)
    return float(hw.mean())


def raw_pf(form, home):
    """Exactly daily_card.py line 96: PARK.get(venue_of.get(home,""), 1.0) — UNROUNDED."""
    return PARK.get(form[3].get(home, ""), 1.0)


def _seed(game_key, rep):
    h = hashlib.sha256(f"{game_key}|{rep}".encode()).digest()
    return int.from_bytes(h[:8], "big")


def load_arms():
    """(games, form_v2, form_v3). Game inputs come from the registered cards and are identical
    across arms — verified field-by-field by the 2026-08-17 audit."""
    v2 = json.load(open("cards/2026-08-17_card_v2.json"))["rows"]
    v3 = json.load(open("cards/2026-08-17_card_v3.json"))["rows"]
    v1 = json.load(open("cards/2026-08-17_card.json"))["rows"]
    now = open("data/backfill/mlb/2026/results.csv").read()
    then = subprocess.run(["git", "show", f"{V2_COMMIT}:data/backfill/mlb/2026/results.csv"],
                          capture_output=True, text=True).stdout
    return v1, v2, v3, team_form(then), team_form(now)


def paired_study(games_a, games_b, form_a, form_b, key_of, n, reps, label):
    """Per game: paired replicates under a common per-(game,rep) seed. Returns per-game stats."""
    out = []
    for ga, gb in zip(games_a, games_b):
        k = key_of(ga)
        d = []
        for rep in range(reps):
            s = _seed(k, rep)
            pa = sim_p(ga["asp_stats"], ga["hsp_stats"], form_a, _ab(ga["away"]), _ab(ga["home"]),
                       raw_pf(form_a, _ab(ga["home"])), n, np.random.default_rng(s))
            pb = sim_p(gb["asp_stats"], gb["hsp_stats"], form_b, _ab(gb["away"]), _ab(gb["home"]),
                       raw_pf(form_b, _ab(gb["home"])), n, np.random.default_rng(s))
            d.append((pb - pa) * 100)
        d = np.array(d)
        m = d.mean(); sd = d.std(ddof=1); se = sd / np.sqrt(len(d))
        out.append({"game": k, "n_sims": n, "reps": reps,
                    "mean_signed_pp": round(float(m), 4),
                    "mean_abs_pp": round(float(np.abs(d).mean()), 4),
                    "sd_pp": round(float(sd), 4), "se_pp": round(float(se), 4),
                    "ci95_low": round(float(m - 1.96 * se), 4),
                    "ci95_high": round(float(m + 1.96 * se), 4),
                    "distinguishable_from_zero": bool(abs(m) > 1.96 * se),
                    "frac_reps_sign_flip_of_side": None})
    return {"label": label, "games": out}


def verify_math():
    """Reproduce the registered v3 card probabilities exactly, using the frozen global-sequential RNG."""
    _, _, v3, _, form_now = load_arms()
    rng = np.random.default_rng(722)
    bad = []
    for r in v3:
        p = sim_p(r["asp_stats"], r["hsp_stats"], form_now, _ab(r["away"]), _ab(r["home"]),
                  raw_pf(form_now, _ab(r["home"])), 30000, rng)
        if round(p, 3) != r["v13"]["home_wp"]:
            bad.append(f'{r["away"]}@{r["home"]}: transcription {round(p,3)} vs registered {r["v13"]["home_wp"]}')
    if bad:
        print("rng_noise_study --verify-math: FAIL (sim transcription does not match the frozen card)")
        for b in bad:
            print("  " + b)
        return 1
    print(f"rng_noise_study --verify-math: PASS (all {len(v3)} registered v3 probabilities reproduced "
          "exactly by this module's sim transcription under the frozen global-sequential RNG)")
    return 0


def main():
    reps = int(sys.argv[sys.argv.index("--reps") + 1]) if "--reps" in sys.argv else 200
    hi_reps = int(sys.argv[sys.argv.index("--hi-reps") + 1]) if "--hi-reps" in sys.argv else 10
    n_hi = 2_000_000
    if "--quick" in sys.argv:
        reps, hi_reps, n_hi = 30, 3, 200_000
    v1, v2, v3, form2, form3 = load_arms()
    SUF = {"DH1": "-G1", "DH2": "-G2"}
    key3 = lambda r: f'{r["away"]}@{r["home"]}{SUF.get(r["gamePk"],"")}'

    print(f"=== STUDY A: v2 vs v3, frozen n=30000, {reps} paired per-game keyed seeds ===")
    A = paired_study(v2, v3, form2, form3, key3, 30000, reps, "v2_vs_v3_n30000")
    print(f"=== STUDY B: v2 vs v3, n={n_hi:,}, {hi_reps} paired seeds (MC error ~0.035pp/run) ===")
    B = paired_study(v2, v3, form2, form3, key3, n_hi, hi_reps, f"v2_vs_v3_n{n_hi}")

    # v1 vs v2: 10 common games, STL@CIN G2 retained as the no-starter-change control.
    v2_by = {key3(r): r for r in v2}
    pairs_a, pairs_b = [], []
    for r in v1:
        g = f'{r["away"]}@{r["home"]}'
        pairs_a.append(r); pairs_b.append(v2_by[g + "-G2" if g == "STL@CIN" else g])
    key1 = lambda r: f'{r["away"]}@{r["home"]}'
    print(f"=== STUDY C: v1 vs v2, {len(pairs_a)} common games, n={n_hi:,}, {hi_reps} paired seeds ===")
    C = paired_study(pairs_a, pairs_b, form2, form2, key1, n_hi, hi_reps, f"v1_vs_v2_n{n_hi}")

    out = {"record_id": "RNG-NOISE-STUDY-2026-08-17",
           "why": ("daily_card.py uses ONE global sequential RNG; numpy gamma/poisson are rejection "
                   "samplers whose draw counts depend on parameters, so a form change re-couples the "
                   "whole downstream stream. Observed card delta = true effect + coupling noise."),
           "studies": [A, B, C]}
    os.makedirs("data/audit", exist_ok=True)
    json.dump(out, open("data/audit/rng_noise_study.json", "w"), indent=1)

    for st in (A, B, C):
        d = np.array([g["mean_signed_pp"] for g in st["games"]])
        a = np.array([g["mean_abs_pp"] for g in st["games"]])
        sig = sum(1 for g in st["games"] if g["distinguishable_from_zero"])
        print(f"\n[{st['label']}]  per-game mean|signed| {np.abs(d).mean():.4f}pp | "
              f"mean of mean_abs {a.mean():.4f}pp | {sig}/{len(st['games'])} games distinguishable from 0")
        for g in st["games"]:
            star = "*" if g["distinguishable_from_zero"] else " "
            print(f"  {star} {g['game']:12} signed {g['mean_signed_pp']:+7.4f}pp  "
                  f"CI[{g['ci95_low']:+.4f},{g['ci95_high']:+.4f}]  |d| {g['mean_abs_pp']:.4f}  se {g['se_pp']:.4f}")
    print("\nwrote data/audit/rng_noise_study.json")
    return 0


if __name__ == "__main__":
    if "--verify-math" in sys.argv:
        raise SystemExit(verify_math())
    raise SystemExit(main())
