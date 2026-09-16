#!/usr/bin/env python3
"""Is team form USEFUL, or merely ACTIVE? A date-ordered out-of-sample ablation on Brier/log-loss.

WHY (owner caution 2026-08-17): the RNG noise study established that swapping V13's form state moves
its output by a mean absolute 0.427pp, and that starter resolution moves it ~5.02x more. Those are
LOCAL SENSITIVITIES of a frozen artifact. A feature can move a model's output by any amount and
still carry zero or negative out-of-sample skill — magnitude of response says nothing about
correctness of response. The owner's instruction: "To establish that form is useful — not merely
active — run a date-ordered OOF ablation comparing form vs no-form on paired Brier/log-loss."

THREE ARMS, one shared frozen input file, one shared sim function:
  FULL     V13 with as-of team form (away_rf/ra, home_rf/ra) exactly as the frozen features carry it
  STALE    V13 with each team's most recent form snapshot dated at least --lag-days EARLIER. Read
           straight off the same frozen features file (a team's row on an earlier date IS that
           team's form as of then), so it is leak-free by construction and introduces no new as-of
           computation. This is the direct analogue of the 8/17 v2->v3 freshness contrast.
  NO_FORM  V13 with all four form inputs set to None. This is not a hack: harness/run_v13_historical
           .v13_sim already falls back to LG_RPG on None, giving offense multiplier 1.0 and
           league-average bullpen penalty for both sides. SP, park factor and HFA remain. The arm
           therefore measures the INCREMENTAL value of team form GIVEN the rest of the model.

WHY THIS IS OUT-OF-SAMPLE. V13 fits nothing. There is no training set, no refit, no hyperparameter
touched by an outcome. Every input row is the strict as-of state (source cutoff: date < slate date)
captured in data/backfill/mlb/2026/features.csv, and every game is scored against a label the model
never saw. That is a stronger guarantee than a train/test split, and it makes the comparison
date-ordered by construction. Results are additionally reported per month so any regime dependence
is visible rather than averaged away.

NO NEW SIM MATH. v13_sim, load_rows and _sp are IMPORTED from harness/run_v13_historical.py (pinned,
unmodified). Transcribing the sim again would have been the third opportunity this week to introduce
a transcription bug, and the noise study already demonstrated how easily that happens.

INFERENCE. Games on the same date share weather, umpires, rest and league-wide scoring conditions,
so game-level rows are not independent. The primary interval is a DATE-BLOCK bootstrap (resample
slate dates with replacement, 10,000 draws), matching the WNBA v1 methodology already in the repo.
Holm is applied across the primary family (2 metrics x 2 contrasts). A per-date sign test is
reported alongside as a distribution-free check.

MEASUREMENT ONLY. Emits no forecast, registers nothing, touches no card, ledger or gate.

Usage: python3 harness/form_oof_ablation.py [--sims 200000] [--lag-days 3] [--quick] [--selftest]
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "harness"))
os.chdir(BASE)
from run_v13_historical import v13_sim, load_rows, _sp, FEATURES  # noqa: E402

OUT = "data/audit/form_oof_ablation.json"
EPS = 1e-6  # log-loss clip; the number of rows it binds is reported, never hidden


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def stale_form(rows, lag_days):
    """For each row, each team's most recent form snapshot from a game at least lag_days earlier.

    A team's features row on date D carries that team's as-of state entering D. Taking the latest
    such row with D' <= D - lag therefore yields strictly older information — no look-ahead is even
    representable. Returns gamePk -> {away_rf, away_ra, home_rf, home_ra, lag_days_actual} or None
    when a side has no qualifying earlier snapshot (early season), which excludes the row.
    """
    hist = {}  # team -> list of (date, rf, ra) in date order, form entering that date
    out, prior_games = {}, {}
    for r in rows:
        # how many prior games the WEAKER-SUPPORTED side's form rests on, counted from this same
        # frozen file and strictly before the row -> leak-free. V13 applies rf/LG_RPG with NO
        # shrinkage, so this is the axis on which an unshrunk rate is expected to misbehave.
        prior_games[r["gamePk"]] = min(len(hist.get(r["away"], [])), len(hist.get(r["home"], [])))
        f = r["f"]
        d = dt.date.fromisoformat(r["date"])
        got, lags = {}, []
        for side in ("away", "home"):
            team = r[side]
            snap = None
            for sd, rf, ra in reversed(hist.get(team, [])):
                if (d - sd).days >= lag_days:
                    snap = (sd, rf, ra)
                    break
            if snap is None or snap[1] is None or snap[2] is None:
                got = None
                break
            got[f"{side}_rf"], got[f"{side}_ra"] = snap[1], snap[2]
            lags.append((d - snap[0]).days)
        out[r["gamePk"]] = (dict(got, lag_days_actual=max(lags)) if got else None)
        # append AFTER computing, so a game never sees its own date
        for side in ("away", "home"):
            hist.setdefault(r[side], []).append((d, f.get(f"{side}_rf"), f.get(f"{side}_ra")))
    return out, prior_games


def brier(p, y):
    return (p - y) ** 2


def logloss(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def block_bootstrap(by_date, draws=10000, seed=20260817):
    """Resample slate DATES with replacement; statistic = mean over all games in the drawn dates."""
    rng = np.random.default_rng(seed)
    dates = list(by_date)
    vals = [np.asarray(by_date[d]) for d in dates]
    sums = np.array([v.sum() for v in vals])
    cnts = np.array([len(v) for v in vals])
    k = len(dates)
    idx = rng.integers(0, k, size=(draws, k))
    b = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    return float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5)), float((b >= 0).mean())


def holm(pvals):
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    out = [None] * len(pvals)
    running = 0.0
    for rank, i in enumerate(order):
        adj = min(1.0, pvals[i] * (len(pvals) - rank))
        running = max(running, adj)
        out[i] = running
    return out


def contrast(name, diffs_by_date, n_games):
    """diffs = arm_minus_reference, so NEGATIVE means the arm scores BETTER (both metrics are losses)."""
    allv = np.concatenate([np.asarray(v) for v in diffs_by_date.values()])
    lo, hi, p_ge0 = block_bootstrap(diffs_by_date)
    # two-sided bootstrap p: proportion of draws on the wrong side of 0, doubled
    p_boot = min(1.0, 2 * min(p_ge0, 1 - p_ge0))
    per_date = np.array([np.mean(v) for v in diffs_by_date.values()])
    n_neg = int((per_date < 0).sum()); n_pos = int((per_date > 0).sum())
    # exact two-sided sign test on per-date means
    from math import comb
    m = n_neg + n_pos
    k = min(n_neg, n_pos)
    p_sign = min(1.0, 2 * sum(comb(m, i) for i in range(k + 1)) / (2 ** m)) if m else 1.0
    return {"contrast": name, "n_games": n_games, "n_dates": len(diffs_by_date),
            "mean_diff": float(allv.mean()), "ci95_block_bootstrap": [lo, hi],
            "p_two_sided_block_bootstrap": p_boot,
            "dates_arm_better": n_neg, "dates_arm_worse": n_pos, "p_sign_test_on_dates": p_sign,
            "direction": ("ARM BETTER" if allv.mean() < 0 else "ARM WORSE" if allv.mean() > 0 else "TIED")}


def run(sims, lag_days, quick):
    rows = load_rows()
    if quick:
        rows = rows[-200:]
    stale, prior_games = stale_form(rows, lag_days)

    recs = []
    clipped = 0
    for r in rows:
        f = r["f"]
        spa, sph = _sp(f["away_sp"]), _sp(f["home_sp"])
        g_seed = 722 + int(r["gamePk"])  # common random numbers: identical seed in every arm
        pf, y = f.get("park"), r["home_win"]
        has_form = all(f.get(k) is not None for k in ("away_rf", "away_ra", "home_rf", "home_ra"))
        p_full = v13_sim(spa, sph, f.get("away_rf"), f.get("away_ra"), f.get("home_rf"),
                         f.get("home_ra"), pf, g_seed, sims)["p_home"]
        p_none = v13_sim(spa, sph, None, None, None, None, pf, g_seed, sims)["p_home"]
        s = stale.get(r["gamePk"])
        p_stale = (v13_sim(spa, sph, s["away_rf"], s["away_ra"], s["home_rf"], s["home_ra"],
                           pf, g_seed, sims)["p_home"] if s else None)
        for p in (p_full, p_none, p_stale):
            if p is not None and not (EPS < p < 1 - EPS):
                clipped += 1
        recs.append({"gamePk": r["gamePk"], "date": r["date"], "y": y, "has_form": has_form,
                     "p_full": p_full, "p_none": p_none, "p_stale": p_stale,
                     "stale_lag_days": (s["lag_days_actual"] if s else None),
                     "prior_games": prior_games[r["gamePk"]]})

    def gather(sel, a, b, metric):
        d = {}
        for x in recs:
            if not sel(x) or x[a] is None or x[b] is None:
                continue
            d.setdefault(x["date"], []).append(metric(x[a], x["y"]) - metric(x[b], x["y"]))
        return d, sum(len(v) for v in d.values())

    informative = lambda x: x["has_form"]          # arms are byte-identical without form
    everything = lambda x: True

    families, results = [], {}
    for subset, sel in (("form_present_only_PRIMARY", informative), ("all_labelled_rows", everything)):
        block = {}
        for metric_name, metric in (("brier", brier), ("logloss", logloss)):
            for cname, a, b in (("FULL_vs_NO_FORM", "p_full", "p_none"),
                                ("FULL_vs_STALE", "p_full", "p_stale"),
                                ("STALE_vs_NO_FORM", "p_stale", "p_none")):
                d, n = gather(sel, a, b, metric)
                if not d:
                    continue
                c = contrast(cname, d, n)
                block[f"{metric_name}::{cname}"] = c
                if subset == "form_present_only_PRIMARY" and cname != "STALE_vs_NO_FORM":
                    families.append((f"{metric_name}::{cname}", c["p_two_sided_block_bootstrap"]))
        results[subset] = block

    ph = holm([p for _, p in families])
    holm_tbl = [{"test": t, "p_raw": p, "p_holm": h, "survives_holm_05": h < 0.05}
                for (t, p), h in zip(families, ph)]

    # absolute levels, so a "better" arm is not reported without saying better than what
    levels = {}
    for arm in ("p_full", "p_none", "p_stale"):
        v = [(x[arm], x["y"]) for x in recs if x["has_form"] and x[arm] is not None]
        if v:
            levels[arm] = {"n": len(v),
                           "brier": round(float(np.mean([brier(p, y) for p, y in v])), 6),
                           "logloss": round(float(np.mean([logloss(p, y) for p, y in v])), 6),
                           "mean_p": round(float(np.mean([p for p, _ in v])), 6)}
    base = np.mean([x["y"] for x in recs if x["has_form"]])
    levels["reference_constant_base_rate"] = {
        "p": round(float(base), 6), "brier": round(float(base * (1 - base)), 6),
        "logloss": round(float(-(base * np.log(base) + (1 - base) * np.log(1 - base))), 6),
        "note": "in-sample home-win base rate; a floor that uses no game information at all"}

    by_month = {}
    for x in recs:
        if not x["has_form"] or x["p_none"] is None:
            continue
        by_month.setdefault(x["date"][:7], []).append(brier(x["p_full"], x["y"]) - brier(x["p_none"], x["y"]))
    monthly = {m: {"n": len(v), "mean_brier_diff_full_minus_noform": round(float(np.mean(v)), 6)}
               for m, v in sorted(by_month.items())}

    # STRATIFICATION BY SUPPORT. V13 applies rf/LG_RPG with no shrinkage, so a team 3 games into the
    # season can carry a 2x offense multiplier off pure noise. If form hurts, the damage should
    # concentrate where the rate is least supported — and that is a falsifiable prediction, not a
    # post-hoc excuse: a flat profile across buckets would refute it.
    BUCKETS = [(0, 9, "0-9_prior_games"), (10, 24, "10-24"), (25, 49, "25-49"), (50, 10 ** 6, "50+")]
    strata = {}
    for lo_b, hi_b, label in BUCKETS:
        sel = lambda x, lo_b=lo_b, hi_b=hi_b: x["has_form"] and lo_b <= x["prior_games"] <= hi_b
        d, n = gather(sel, "p_full", "p_none", brier)
        if not d:
            continue
        c = contrast("FULL_vs_NO_FORM", d, n)
        dl, _ = gather(sel, "p_full", "p_none", logloss)
        strata[label] = {"n_games": n, "n_dates": len(d),
                         "mean_brier_diff": round(c["mean_diff"], 6),
                         "ci95": [round(v, 6) for v in c["ci95_block_bootstrap"]],
                         "p": c["p_two_sided_block_bootstrap"],
                         "mean_logloss_diff": round(float(np.concatenate(
                             [np.asarray(v) for v in dl.values()]).mean()), 6),
                         "direction": c["direction"]}

    out = {
        "record_id": "FORM-OOF-ABLATION-2026-08-17",
        "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "role": "MEASUREMENT_NON_FORECASTING",
        "question": "Is team form USEFUL (out-of-sample skill), not merely ACTIVE (output sensitivity)?",
        "sign_convention": "diffs are arm minus reference on a LOSS. NEGATIVE = the arm predicts better.",
        "sims_per_game": sims, "stale_lag_days_min": lag_days,
        "features_file": FEATURES, "features_file_sha256": _sha(FEATURES),
        "window": {"first_date": recs[0]["date"], "last_date": recs[-1]["date"], "games": len(recs)},
        "out_of_sample_basis": ("V13 fits nothing: no training set, no refit, no outcome-tuned "
                                "parameter. Inputs are the strict as-of state (cutoff: date < slate "
                                "date); labels were never seen. Date-ordered by construction."),
        "logloss_rows_hitting_clip": clipped,
        "absolute_levels_form_present_rows": levels,
        "contrasts": results,
        "holm_primary_family": holm_tbl,
        "monthly_brier_diff_full_minus_noform": monthly,
        "stratified_by_form_support_FULL_vs_NO_FORM": strata,
        "scope_limits": [
          "Measures team form's INCREMENTAL value GIVEN V13's SP, park and HFA terms — not form's value in isolation, and not its value inside a different model.",
          "The frozen feature window ends 2026-07-19, so this does not cover the 2026-08-17 slate the sensitivity study used.",
          "The STALE arm lags form by at least the stated number of days using each team's own earlier snapshot. It is an analogue of the 8/17 v2->v3 freshness contrast, not a reconstruction of it.",
          "A null result here is evidence of no detectable skill AT THIS SAMPLE SIZE, which is not the same as evidence of no effect.",
        ],
    }
    os.makedirs("data/audit", exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    return out


def selftest():
    fails = []
    rows = load_rows()
    st, _pg = stale_form(rows, 3)
    # falsification 1: no stale snapshot may come from the game's own date or later
    hist = {}
    for r in rows:
        d = dt.date.fromisoformat(r["date"])
        s = st.get(r["gamePk"])
        if s and s["lag_days_actual"] < 3:
            fails.append(f'{r["gamePk"]}: stale lag {s["lag_days_actual"]} < 3 — look-ahead')
        hist[r["gamePk"]] = d
    # falsification 2: opening-day rows can have no stale snapshot at all
    if st[rows[0]["gamePk"]] is not None:
        fails.append("first game of the season was given a stale form snapshot out of nowhere")
    # falsification 3: with form present, FULL and NO_FORM must actually differ; without, be identical
    f = rows[-1]["f"]
    spa, sph = _sp(f["away_sp"]), _sp(f["home_sp"])
    a = v13_sim(spa, sph, f["away_rf"], f["away_ra"], f["home_rf"], f["home_ra"], f["park"], 1, 20000)["p_home"]
    b = v13_sim(spa, sph, None, None, None, None, f["park"], 1, 20000)["p_home"]
    if f["away_rf"] is not None and a == b:
        fails.append("form-present row: FULL and NO_FORM arms are identical — the ablation is inert")
    c = v13_sim(spa, sph, None, None, None, None, f["park"], 1, 20000)["p_home"]
    if b != c:
        fails.append("NO_FORM arm is not deterministic under a fixed seed")
    # falsification 4: the bootstrap must find no signal in pure noise
    rng = np.random.default_rng(1)
    noise = {f"d{i}": list(rng.normal(0, 1, 10)) for i in range(60)}
    r = contrast("noise", noise, 600)
    if r["p_two_sided_block_bootstrap"] < 0.05:
        fails.append(f"block bootstrap called pure noise significant (p={r['p_two_sided_block_bootstrap']})")
    # falsification 5: and must find a real one
    shift = {f"d{i}": list(rng.normal(-0.5, 1, 10)) for i in range(60)}
    if contrast("shift", shift, 600)["p_two_sided_block_bootstrap"] > 0.01:
        fails.append("block bootstrap missed a real 0.5 SD shift")
    if holm([0.01, 0.04])[1] >= 0.05 or holm([0.04, 0.04])[0] < 0.05:
        fails.append("holm adjustment wrong")
    if fails:
        print("form_oof_ablation selftest: FAIL")
        for x in fails:
            print("  " + x)
        return 1
    print(f"form_oof_ablation selftest: PASS (stale snapshots respect the lag on {len(st)} rows; "
          f"arms differ where form exists; bootstrap rejects noise and detects a real shift)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=200000)
    ap.add_argument("--lag-days", type=int, default=3)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    o = run(a.sims, a.lag_days, a.quick)
    L = o["absolute_levels_form_present_rows"]
    print(f'window {o["window"]["first_date"]}..{o["window"]["last_date"]}  '
          f'{o["window"]["games"]} games, n={o["sims_per_game"]:,} sims/game/arm')
    print(f'{"arm":<34}{"n":>6}{"brier":>10}{"logloss":>10}')
    for k, v in L.items():
        print(f'{k:<34}{v.get("n",""):>6}{v["brier"]:>10.5f}{v["logloss"]:>10.5f}')
    for sub, block in o["contrasts"].items():
        print(f"\n[{sub}]")
        for k, c in block.items():
            print(f'  {k:<34} {c["mean_diff"]:+.6f}  CI[{c["ci95_block_bootstrap"][0]:+.6f},'
                  f'{c["ci95_block_bootstrap"][1]:+.6f}]  p={c["p_two_sided_block_bootstrap"]:.4f}  '
                  f'dates {c["dates_arm_better"]}-{c["dates_arm_worse"]}  {c["direction"]}')
    print("\nFULL vs NO_FORM by how many prior games the weaker side's form rests on:")
    for k, v in o["stratified_by_form_support_FULL_vs_NO_FORM"].items():
        print(f'  {k:<18} n={v["n_games"]:>4}  brier {v["mean_brier_diff"]:+.6f} '
              f'CI[{v["ci95"][0]:+.6f},{v["ci95"][1]:+.6f}]  logloss {v["mean_logloss_diff"]:+.6f}  '
              f'p={v["p"]:.4f}  {v["direction"]}')
    print("\nmonthly brier diff (FULL - NO_FORM):")
    for k, v in o["monthly_brier_diff_full_minus_noform"].items():
        print(f'  {k}  n={v["n"]:>4}  {v["mean_brier_diff_full_minus_noform"]:+.6f}')
    print("\nHolm (primary family):")
    for h in o["holm_primary_family"]:
        print(f'  {h["test"]:<34} p_raw {h["p_raw"]:.4f} -> p_holm {h["p_holm"]:.4f}  '
              f'{"SURVIVES" if h["survives_holm_05"] else "does not survive"}')
    print(f"\nwrote {OUT}")
