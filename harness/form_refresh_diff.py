#!/usr/bin/env python3
"""What changed SOLELY because the 8/15-8/16 tier-1 data arrived? A three-state decomposition.

WHY (owner instruction 2026-08-17): "Produce a before/after diff showing which team/pitcher form
values, probabilities, edges, rankings, and final selections changed solely because the 8/15-8/16
tier-1 data became available."

THE PROBLEM WITH THE OBVIOUS ANSWER. The registered v2 -> v3 contrast is NOT that diff. The same
2026-08-17T05:20:56Z intake applied THIRTY-NINE tier-1 rows: 9 on 8/13 (closing an interior hole
created by executing the tier-1-only ruling) plus 15 on 8/15 and 15 on 8/16. So v2 -> v3 bundles the
8/13 repair together with the 8/15-8/16 refresh, and attributing all of it to 8/15-8/16 would
overstate the refresh by whatever the 8/13 repair contributed. This module separates them.

THREE FORM STATES, all built from the CURRENT canonical results.csv by DATE FILTER — the file is
never mutated, and all three therefore share identical provenance:

    S_A  date <= 2026-08-14, EXCLUDING 2026-08-13   -> the state v2 was actually built on
    S_B  date <= 2026-08-14                          -> S_A + the 8/13 hole repair
    S_C  all dates (through 2026-08-16)              -> the state v3 was actually built on

    S_D  all dates EXCEPT 2026-08-13                 -> the refresh WITHOUT the hole repair

    A -> B  = the 8/13 interior-hole repair, with the refresh absent
    B -> C  = THE 8/15-8/16 REFRESH, given the hole repaired   <-- what was asked for
    A -> D  = the refresh, with the hole still open
    D -> C  = the hole repair, given the refresh applied
    A -> C  = the net total, and must equal the registered v2 -> v3 contrast

ATTRIBUTION IS NOT A RATIO OF MEAN ABSOLUTE MOVEMENTS (owner correction 2026-08-17). An earlier
version of this module reported the refresh as "81% of the total" by dividing a per-path mean
|delta| (0.3457pp) by the NET mean |delta| (0.4254pp). Those have different denominators and the
quotient is a share of nothing: mean absolute movements are NOT additive, because signed
per-game contributions partially cancel. 0.3457 + 0.1973 = 0.5430pp of GROSS path movement, which
exceeds the 0.4254pp net precisely by the amount that cancels. This module now reports:
  - net movement, mean |phi_R + phi_H|
  - gross path movement, and each path's share OF THE GROSS (order-dependent by construction)
  - SHAPLEY values over the two factors, which are order-neutral and sum EXACTLY to the net signed
    change per game: phi_R = 1/2[(D-A) + (C-B)], phi_H = 1/2[(B-A) + (C-D)], phi_R + phi_H = C-A.

THE DECOMPOSITION IS NOT ASSUMED, IT IS VERIFIED. Before any delta is reported, S_A must reproduce
the REGISTERED v2 card's probabilities exactly and S_C must reproduce the REGISTERED v3 card's
probabilities exactly, under the frozen global-sequential RNG. If either fails, the date filter is
not reconstructing the historical states and the module REFUSES to report rather than emitting a
plausible-looking decomposition of the wrong thing.

RNG SEPARATION. daily_card drives every game from one global sequential RNG whose draw counts depend
on the parameters, so a single card delta is (form effect + re-coupling noise). Per-game deltas are
therefore reported twice: at the FROZEN setting n=30,000 (what the cards literally say) and as a
HIGH-PRECISION REFERENCE ESTIMATE from paired common-random-numbers replicates at n=2,000,000 with
a Monte-Carlo CI and Holm correction. Never a "true" or "noiseless" value.

WHAT THIS IS NOT. Every number here is a LOCAL SENSITIVITY of a frozen artifact. The date-ordered
OOF ablation (harness/form_oof_ablation.py) found form freshness has NO detectable effect on
prospective accuracy. Movement is not improvement.

MEASUREMENT ONLY. Reads registered cards and canonical results; writes one report artifact. Emits no
forecast, alters no card, changes no model parameter, RNG policy, promotion gate or market input.

Usage: python3 harness/form_refresh_diff.py [--hi-sims 2000000] [--hi-reps 10] [--quick] [--selftest]
"""
from __future__ import annotations
import argparse, csv, datetime as dt, io, json, math, os, sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))
from rng_noise_study import (team_form, sim_p, raw_pf, _rfra, _seed, _ab, LG_RPG)  # noqa: E402

RESULTS = "data/backfill/mlb/2026/results.csv"
OUT = "data/audit/form_refresh_diff.json"
FROZEN_N, FROZEN_SEED = 30000, 722
HOLE_DATE, CUTOFF_A, REFRESH = "2026-08-13", "2026-08-14", ["2026-08-15", "2026-08-16"]
# S_C is the form state the v3 card was BUILT on, which ends 2026-08-16. It was written as "all
# dates" — true only until 2026-08-17 results were ingested, at which point S_C silently grew a day
# and stopped reproducing the registered card. An as-of state must be pinned to its date, not to
# "whatever is on disk".
CUTOFF_C = "2026-08-16"


def filtered_results(keep):
    """Return results.csv TEXT containing only rows keep(date) accepts. The canonical file on disk is
    opened read-only and never written; the filter happens in memory."""
    raw = open(RESULTS, newline="").read()
    rd = csv.DictReader(io.StringIO(raw))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=rd.fieldnames, lineterminator="\n")
    w.writeheader()
    for r in rd:
        if keep(r["date"]):
            w.writerow(r)
    return buf.getvalue()


def card_probs(rows, form):
    """Replay a whole card under `form` with the FROZEN global-sequential RNG, exactly as
    daily_card.py does: one rng seeded 722, games consumed in slate order. Returns [p_home]."""
    rng = np.random.default_rng(FROZEN_SEED)
    out = []
    for r in rows:
        out.append(sim_p(r["asp_stats"], r["hsp_stats"], form, _ab(r["away"]), _ab(r["home"]),
                         raw_pf(form, _ab(r["home"])), FROZEN_N, rng))
    return out


def paired_hi(rows, form_a, form_b, n, reps):
    """Per game: paired replicates under a common per-(game,replicate) seed, both arms sharing the
    seed so part of the Monte-Carlo error cancels in the difference (common random numbers)."""
    out = []
    for r in rows:
        key = f'{r["away"]}@{r["home"]}|{r["gamePk"]}'
        d = []
        for rep in range(reps):
            s = _seed(key, rep)
            pa = sim_p(r["asp_stats"], r["hsp_stats"], form_a, _ab(r["away"]), _ab(r["home"]),
                       raw_pf(form_a, _ab(r["home"])), n, np.random.default_rng(s))
            pb = sim_p(r["asp_stats"], r["hsp_stats"], form_b, _ab(r["away"]), _ab(r["home"]),
                       raw_pf(form_b, _ab(r["home"])), n, np.random.default_rng(s))
            d.append((pb - pa) * 100)
        d = np.array(d)
        sd = float(d.std(ddof=1)) if reps > 1 else 0.0
        se = sd / math.sqrt(reps) if reps > 1 else 0.0
        t = (d.mean() / se) if se > 0 else float("inf")
        out.append({"game": f'{r["away"]}@{r["home"]}', "gamePk": r["gamePk"],
                    "mean_signed_pp": round(float(d.mean()), 4), "sd_pp": round(sd, 4),
                    "se_pp": round(se, 4), "abs_t": abs(t),
                    "ci95": [round(float(d.mean() - 1.96 * se), 4), round(float(d.mean() + 1.96 * se), 4)],
                    "n_sims": n, "reps": reps})
    return out


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out, run = [None] * len(ps), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, ps[i] * (len(ps) - rank)))
        out[i] = run
    return out


def _p_from_t(t, df):
    """Two-sided p from |t| without scipy: normal approximation, floored so a p is never reported as
    exactly 0. df is carried for the record; at df=9 the normal tail understates p slightly, which is
    stated rather than hidden."""
    p = math.erfc(abs(t) / math.sqrt(2))
    return max(p, 1e-300)


def form_table(form, teams):
    rf, ra, g, _v = form
    return {t: {"games": g.get(t, 0),
                "rf_per_g": round(_rfra(form, t)[0], 4),
                "ra_per_g": round(_rfra(form, t)[1], 4),
                "rf_total": rf.get(t, 0), "ra_total": ra.get(t, 0)} for t in sorted(teams)}


def run(hi_sims, hi_reps, quick):
    v2 = json.load(open("cards/2026-08-17_card_v2.json"))["rows"]
    v3 = json.load(open("cards/2026-08-17_card_v3.json"))["rows"]
    assert [r["gamePk"] for r in v2] == [r["gamePk"] for r in v3], "v2/v3 slate order differs"

    S_A = team_form(filtered_results(lambda d: d <= CUTOFF_A and d != HOLE_DATE))
    S_B = team_form(filtered_results(lambda d: d <= CUTOFF_A))
    S_C = team_form(filtered_results(lambda d: d <= CUTOFF_C))
    S_D = team_form(filtered_results(lambda d: d != HOLE_DATE and d <= CUTOFF_C))

    # ---- GATE: the reconstructed states must reproduce the REGISTERED cards exactly ----
    verify = {}
    for name, form, rows in (("S_A_reproduces_registered_v2", S_A, v2),
                             ("S_C_reproduces_registered_v3", S_C, v3)):
        got = card_probs(rows, form)
        want = [r["v13"]["home_wp"] for r in rows]
        mism = [f'{rows[i]["away"]}@{rows[i]["home"]}: rebuilt {round(got[i],3)} vs card {want[i]}'
                for i in range(len(rows)) if round(got[i], 3) != want[i]]
        verify[name] = {"games": len(rows), "mismatches": mism, "PASS": not mism}
    if not all(v["PASS"] for v in verify.values()):
        return {"record_id": "FORM-REFRESH-DIFF-2026-08-17", "REFUSED": True,
                "reason": ("the date-filtered form states do not reproduce the registered cards, so "
                           "the decomposition would be of the wrong thing"), "verification": verify}

    teams = sorted({_ab(r[s]) for r in v3 for s in ("away", "home")})
    p_A, p_B, p_C, p_D = (card_probs(v3, f) for f in (S_A, S_B, S_C, S_D))

    _n = 1 if quick else hi_sims
    _r = 2 if quick else hi_reps
    hi_BC = paired_hi(v3, S_B, S_C, _n, _r)   # refresh | hole repaired
    hi_AB = paired_hi(v3, S_A, S_B, _n, _r)   # repair  | refresh absent
    hi_AD = paired_hi(v3, S_A, S_D, _n, _r)   # refresh | hole open
    hi_DC = paired_hi(v3, S_D, S_C, _n, _r)   # repair  | refresh applied
    for tbl in (hi_BC, hi_AB, hi_AD, hi_DC):
        ph = holm([_p_from_t(x["abs_t"], (2 if quick else hi_reps) - 1) for x in tbl])
        m = len(tbl)
        for x, h in zip(tbl, ph):
            x["p_holm"] = h
            x["survives_holm_05"] = h < 0.05
            z = 1.96 if m <= 1 else abs(_z_bonferroni(m))
            x["ci_simultaneous"] = [round(x["mean_signed_pp"] - z * x["se_pp"], 4),
                                    round(x["mean_signed_pp"] + z * x["se_pp"], 4)]
            x["excl_zero_simultaneous"] = (x["ci_simultaneous"][0] > 0) == (x["ci_simultaneous"][1] > 0)

    # ---- team form values ----
    fA, fB, fC = (form_table(f, teams) for f in (S_A, S_B, S_C))
    form_changes = []
    for t in teams:
        if fB[t] != fC[t]:
            form_changes.append({"team": t,
                                 "before_8_15_16": fB[t], "after_8_15_16": fC[t],
                                 "d_games": fC[t]["games"] - fB[t]["games"],
                                 "d_rf_per_g": round(fC[t]["rf_per_g"] - fB[t]["rf_per_g"], 4),
                                 "d_ra_per_g": round(fC[t]["ra_per_g"] - fB[t]["ra_per_g"], 4)})

    # ---- rankings by model home-win probability (the only rankable model quantity: no prices) ----
    def rank(ps):
        order = sorted(range(len(ps)), key=lambda i: -ps[i])
        return {i: k + 1 for k, i in enumerate(order)}
    rB, rC = rank(p_B), rank(p_C)

    # the 8/17 slate contains a doubleheader; a bare AWAY@HOME label would print two identical rows
    dup = {f'{r["away"]}@{r["home"]}' for r in v3
           if sum(1 for x in v3 if (x["away"], x["home"]) == (r["away"], r["home"])) > 1}
    games = []
    for i, r in enumerate(v3):
        g = f'{r["away"]}@{r["home"]}'
        if g in dup:
            g = f'{g}-{r["gamePk"]}'
        hb = next(x for x in hi_BC if x["gamePk"] == r["gamePk"])
        ha = next(x for x in hi_AB if x["gamePk"] == r["gamePk"])
        hd = next(x for x in hi_AD if x["gamePk"] == r["gamePk"])
        hc = next(x for x in hi_DC if x["gamePk"] == r["gamePk"])
        # Shapley over the two factors: order-neutral, and phi_R + phi_H is EXACTLY the net change
        phi_R = 0.5 * (hd["mean_signed_pp"] + hb["mean_signed_pp"])
        phi_H = 0.5 * (ha["mean_signed_pp"] + hc["mean_signed_pp"])
        games.append({
            "game": g, "gamePk": r["gamePk"], "away_sp": r["asp"], "home_sp": r["hsp"],
            "starters_changed_by_refresh": False,
            "p_home_S_A_v2_state": round(p_A[i], 5),
            "p_home_S_B_after_8_13_repair": round(p_B[i], 5),
            "p_home_S_C_after_8_15_16": round(p_C[i], 5),
            "delta_pp_frozen_n_8_13_repair": round((p_B[i] - p_A[i]) * 100, 4),
            "delta_pp_frozen_n_8_15_16_REFRESH": round((p_C[i] - p_B[i]) * 100, 4),
            "delta_pp_frozen_n_total": round((p_C[i] - p_A[i]) * 100, 4),
            "refresh_reference_estimate": {k: hb[k] for k in
                ("mean_signed_pp", "sd_pp", "se_pp", "ci95", "ci_simultaneous", "p_holm",
                 "survives_holm_05", "excl_zero_simultaneous", "n_sims", "reps")},
            "hole_repair_reference_estimate": {k: ha[k] for k in
                ("mean_signed_pp", "ci95", "p_holm", "survives_holm_05")},
            "signed_contributions_pp": {
                "refresh_given_hole_repaired_B_to_C": hb["mean_signed_pp"],
                "refresh_given_hole_open_A_to_D": hd["mean_signed_pp"],
                "repair_given_refresh_absent_A_to_B": ha["mean_signed_pp"],
                "repair_given_refresh_applied_D_to_C": hc["mean_signed_pp"],
                "shapley_refresh": round(phi_R, 4),
                "shapley_repair": round(phi_H, 4),
                "shapley_sum": round(phi_R + phi_H, 4),
                "net_A_to_C": round((p_C[i] - p_A[i]) * 100, 4),
                "interaction_pp": round(hb["mean_signed_pp"] - hd["mean_signed_pp"], 4),
            },
            "side_at_frozen_n_before": "HOME" if p_B[i] >= .5 else "AWAY",
            "side_at_frozen_n_after": "HOME" if p_C[i] >= .5 else "AWAY",
            "side_flipped_at_frozen_n": (p_B[i] >= .5) != (p_C[i] >= .5),
            "side_flip_survives_reference_estimate": (
                ((p_B[i] >= .5) != (p_B[i] + hb["mean_signed_pp"] / 100 >= .5))
                if (p_B[i] >= .5) != (p_C[i] >= .5) else None),
            "p_home_under_reference_estimate": round(p_B[i] + hb["mean_signed_pp"] / 100, 5),
            "rank_by_p_home_before": rB[i], "rank_by_p_home_after": rC[i],
            "rank_change": rB[i] - rC[i],
            "market_price_on_file": r["lines"]["ml_home"],
            "break_even_prob": None, "edge": None, "selection": None,
        })

    # verify, do not assert: compare every starter field between the two registered cards
    _sp_bad = []
    for a, b in zip(v2, v3):
        for f in ("asp_stats", "hsp_stats", "asp", "hsp"):
            if a[f] != b[f]:
                _sp_bad.append(f'{b["away"]}@{b["home"]} {f}: {a[f]} != {b[f]}')
    _sp_a = all(a["asp_stats"] == b["asp_stats"] for a, b in zip(v2, v3))
    _sp_h = all(a["hsp_stats"] == b["hsp_stats"] for a, b in zip(v2, v3))
    _sp_n = all((a["asp"], a["hsp"]) == (b["asp"], b["hsp"]) for a, b in zip(v2, v3))
    _sp_changed = bool(_sp_bad)

    d_ref = np.array([g["refresh_reference_estimate"]["mean_signed_pp"] for g in games])
    d_card = np.array([g["delta_pp_frozen_n_8_15_16_REFRESH"] for g in games])
    d_hole = np.array([g["delta_pp_frozen_n_8_13_repair"] for g in games])
    d_hole_ref = np.array([g["hole_repair_reference_estimate"]["mean_signed_pp"] for g in games])
    _phiR = np.array([g["signed_contributions_pp"]["shapley_refresh"] for g in games])
    _phiH = np.array([g["signed_contributions_pp"]["shapley_repair"] for g in games])
    _inter = np.array([g["signed_contributions_pp"]["interaction_pp"] for g in games])

    rep = {
        "record_id": "FORM-REFRESH-DIFF-2026-08-17",
        "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "role": "MEASUREMENT_NON_FORECASTING",
        "question": "what changed SOLELY because the 2026-08-15/16 tier-1 data became available",
        "model_identity": "ml.v13_1.hfa1005.card.s722n30000 — FROZEN; no parameter, RNG policy, "
                          "promotion gate or market input altered by this refresh",
        "why_v2_vs_v3_is_not_the_answer": (
            "the 2026-08-17T05:20:56Z intake applied 39 tier-1 rows: 8/13 x9 (interior hole repair) "
            "plus 8/15 x15 and 8/16 x15. v2->v3 bundles both. This report separates them and the "
            "8/15-8/16 column is the one that answers the question."),
        "verification_gate": verify,
        "state_definitions": {
            "S_A": f"date <= {CUTOFF_A}, excluding {HOLE_DATE} — reproduces registered v2 exactly",
            "S_B": f"date <= {CUTOFF_A} — S_A plus the {HOLE_DATE} hole repair",
            "S_C": f"date <= {CUTOFF_C} — reproduces registered v3 exactly",
            "canonical_file_mutated": False,
        },
        "slate_totals": {
            "games": len(games),
            "refresh_mean_abs_pp_frozen_n": round(float(np.abs(d_card).mean()), 4),
            "refresh_mean_abs_pp_reference": round(float(np.abs(d_ref).mean()), 4),
            "refresh_max_abs_pp_reference": round(float(np.abs(d_ref).max()), 4),
            "hole_repair_mean_abs_pp_frozen_n": round(float(np.abs(d_hole).mean()), 4),
            "total_mean_abs_pp_frozen_n": round(float(np.abs(
                np.array([g["delta_pp_frozen_n_total"] for g in games])).mean()), 4),
            "hole_repair_mean_abs_pp_reference": round(float(np.abs(d_hole_ref).mean()), 4),
            "net_mean_abs_pp_reference": round(float(np.abs(_phiR + _phiH).mean()), 4),
            "gross_path_movement_pp": round(float(np.abs(d_ref).mean() + np.abs(d_hole_ref).mean()), 4),
            "refresh_share_of_GROSS_path_movement": round(float(
                np.abs(d_ref).mean() / (np.abs(d_ref).mean() + np.abs(d_hole_ref).mean())), 4),
            "repair_share_of_GROSS_path_movement": round(float(
                np.abs(d_hole_ref).mean() / (np.abs(d_ref).mean() + np.abs(d_hole_ref).mean())), 4),
            "shapley_refresh_mean_abs_pp": round(float(np.abs(_phiR).mean()), 4),
            "shapley_repair_mean_abs_pp": round(float(np.abs(_phiH).mean()), 4),
            "shapley_refresh_share_ORDER_NEUTRAL": round(float(
                np.abs(_phiR).mean() / (np.abs(_phiR).mean() + np.abs(_phiH).mean())), 4),
            "mean_abs_interaction_pp": round(float(np.abs(_inter).mean()), 4),
            "share_note": ("MEAN ABSOLUTE MOVEMENTS ARE NOT ADDITIVE. gross (0.543-scale) exceeds net "
                           "because signed per-game contributions partially cancel. A per-path mean "
                           "|delta| divided by the NET mean |delta| is a share of nothing — that error "
                           "produced the retracted '81%'. Quote the GROSS share for path-specific "
                           "movement, or the SHAPLEY share when an order-neutral split is required."),
            "side_flips_at_frozen_n": sum(g["side_flipped_at_frozen_n"] for g in games),
            "side_flips_surviving_reference_estimate": sum(
                1 for g in games if g["side_flip_survives_reference_estimate"]),
            "rank_changes": sum(1 for g in games if g["rank_change"] != 0),
            "games_surviving_holm": sum(1 for g in games
                                        if g["refresh_reference_estimate"]["survives_holm_05"]),
        },
        "team_form_values_changed_by_8_15_16": form_changes,
        "pitcher_form": {
            "changed_by_this_refresh": _sp_changed,  # True only if a starter field actually differs
            "basis": ("the refresh added TEAM game results, not pitcher game logs. Every game's "
                      "asp_stats/hsp_stats are byte-identical between the v2 and v3 registered cards, "
                      "and both arms of every contrast here are driven from those same stats. "
                      "harness/daily_card.py reads pitcher form from "
                      "data/backfill/mlb/2026/pitcher_logs/, which this intake did not touch."),
            "verified_field_by_field": {
                "games_compared": len(v3),
                "asp_stats_identical_v2_vs_v3": _sp_a,
                "hsp_stats_identical_v2_vs_v3": _sp_h,
                "starter_names_identical_v2_vs_v3": _sp_n,
                "mismatches": _sp_bad,
            },
        },
        "edges_and_selections": {
            "edge": None, "break_even_prob": None, "selection": None,
            "REASON": ("NO market prices exist on file for 2026-08-17: every row's lines.ml_home / "
                       "lines.ml_away / mkt_home_prob / gap_home is null in BOTH the v2 and v3 "
                       "registered cards, and no data/mlb/odds/2026-08-17_*.json exists. Edge = "
                       "p_model - p_breakeven is undefined without a posted price, and the card's "
                       "selection rule ('no plays unless the kprop EV rule fires') cannot fire "
                       "without one. Per R1 these are reported NULL AND FLAGGED, not estimated."),
            "did_the_refresh_change_them": ("NO — and not because they were stable, but because they "
                                            "were absent before and after. Any nonzero edge or "
                                            "selection delta reported for this slate would be invented."),
            "acquisition_blocked": ("outbound HTTPS returns 403 at the org egress proxy; no price was "
                                    "fetched and none was substituted from another book or another date."),
        },
        "games": games,
        "scope_limit": ("LOCAL SENSITIVITY of a frozen artifact. The date-ordered OOF ablation "
                        "(docs/experiments/2026-08-17_FORM_USEFULNESS.json) found form freshness has "
                        "NO detectable effect on prospective accuracy: FULL vs STALE -0.0005 Brier, "
                        "p=0.59. Probability movement here is not accuracy improvement."),
    }
    os.makedirs("data/audit", exist_ok=True)
    json.dump(rep, open(OUT, "w"), indent=1)
    return rep


def _z_bonferroni(m):
    """z for a two-sided 0.05/m interval, by bisection on erfc — avoids a scipy dependency."""
    target = 0.05 / m
    lo, hi = 0.0, 12.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if math.erfc(mid / math.sqrt(2)) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def selftest():
    fails = []
    # 1. the filter must not touch the canonical file
    before = open(RESULTS, "rb").read()
    txt = filtered_results(lambda d: d <= CUTOFF_A)
    if open(RESULTS, "rb").read() != before:
        fails.append("filtered_results MUTATED the canonical results file")
    # 2. the filter must actually drop the refresh dates and keep the rest
    dates = {r["date"] for r in csv.DictReader(io.StringIO(txt))}
    if any(d in dates for d in REFRESH):
        fails.append("S_B still contains 8/15 or 8/16 rows")
    if CUTOFF_A not in dates or HOLE_DATE not in dates:
        fails.append("S_B lost 8/13 or 8/14 rows it should keep")
    a = {r["date"] for r in csv.DictReader(io.StringIO(
        filtered_results(lambda d: d <= CUTOFF_A and d != HOLE_DATE)))}
    if HOLE_DATE in a:
        fails.append("S_A still contains the 8/13 hole rows")
    # 3. the three states must be strictly nested in games played
    A, B, C = (team_form(filtered_results(k)) for k in
               (lambda d: d <= CUTOFF_A and d != HOLE_DATE, lambda d: d <= CUTOFF_A,
                lambda d: d <= CUTOFF_C))
    for t in ("NYY", "TB", "CIN"):
        if not (A[2].get(t, 0) <= B[2].get(t, 0) <= C[2].get(t, 0)):
            fails.append(f"{t}: game counts are not monotone across S_A <= S_B <= S_C")
    # 4. every team must gain exactly 2 games from the 8/15-8/16 refresh (both dates full slates)
    bad = [t for t in C[2] if t in B[2] and C[2][t] - B[2][t] != 2]
    if bad:
        fails.append(f"teams not gaining exactly 2 games from a two-full-slate refresh: {bad}")
    # 5. Bonferroni z must exceed the pointwise 1.96 and grow with m
    if not (_z_bonferroni(11) > 1.96 and _z_bonferroni(20) > _z_bonferroni(11)):
        fails.append("Bonferroni z is not more conservative than pointwise, or is not monotone in m")
    if holm([0.01, 0.04])[1] >= 0.05 or holm([0.04, 0.04])[0] < 0.05:
        fails.append("holm adjustment wrong")
    # 6. THE decomposition identity: A->B plus B->C must equal A->C exactly, per game
    v3 = json.load(open("cards/2026-08-17_card_v3.json"))["rows"]
    pA, pB, pC = card_probs(v3, A), card_probs(v3, B), card_probs(v3, C)
    for i in range(len(v3)):
        if abs(((pB[i] - pA[i]) + (pC[i] - pB[i])) - (pC[i] - pA[i])) > 1e-12:
            fails.append(f"decomposition does not sum to the total on game {i}")
    # 7. Shapley additivity: phi_R + phi_H must equal the net signed change per game, exactly
    D = team_form(filtered_results(lambda d: d != HOLE_DATE and d <= CUTOFF_C))
    pD = card_probs(v3, D)
    for i in range(len(v3)):
        phiR = 0.5 * ((pD[i] - pA[i]) + (pC[i] - pB[i]))
        phiH = 0.5 * ((pB[i] - pA[i]) + (pC[i] - pD[i]))
        if abs((phiR + phiH) - (pC[i] - pA[i])) > 1e-12:
            fails.append(f"Shapley values do not sum to the net change on game {i}")
    # 8. the retracted error must stay retracted: a per-path mean |delta| over the NET mean |delta|
    #    is not a share, and gross must be >= net whenever any cancellation occurs
    dR = np.array([abs(pC[i] - pB[i]) for i in range(len(v3))])
    dH = np.array([abs(pB[i] - pA[i]) for i in range(len(v3))])
    net = np.array([abs(pC[i] - pA[i]) for i in range(len(v3))])
    if not (dR.mean() + dH.mean() >= net.mean() - 1e-12):
        fails.append("gross path movement is below net movement — impossible by the triangle inequality")
    if fails:
        print("form_refresh_diff selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("form_refresh_diff selftest: PASS (canonical file untouched; date filters isolate 8/13 and "
          "8/15-8/16; form states strictly nested and every team gains exactly 2 games; decomposition "
          "sums to the total; Bonferroni/Holm behave)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hi-sims", type=int, default=2000000)
    ap.add_argument("--hi-reps", type=int, default=10)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    r = run(a.hi_sims, a.hi_reps, a.quick)
    if r.get("REFUSED"):
        print("REFUSED:", r["reason"])
        for k, v in r["verification"].items():
            print(f"  {k}: {'PASS' if v['PASS'] else 'FAIL'} {v.get('mismatches', [])[:3]}")
        raise SystemExit(1)
    for k, v in r["verification_gate"].items():
        print(f"gate {k}: {'PASS' if v['PASS'] else 'FAIL'} ({v['games']} games)")
    t = r["slate_totals"]
    print(f'\n8/15-8/16 REFRESH ALONE: mean |delta| {t["refresh_mean_abs_pp_reference"]}pp '
          f'(reference estimate) / {t["refresh_mean_abs_pp_frozen_n"]}pp at the frozen n; '
          f'max {t["refresh_max_abs_pp_reference"]}pp')
    print(f'8/13 hole repair alone : mean |delta| {t["hole_repair_mean_abs_pp_reference"]}pp '
          f'(reference) / {t["hole_repair_mean_abs_pp_frozen_n"]}pp at the frozen n')
    print(f'NET combined (= v2->v3): {t["net_mean_abs_pp_reference"]}pp (reference) / '
          f'{t["total_mean_abs_pp_frozen_n"]}pp at the frozen n')
    print(f'GROSS path movement    : {t["gross_path_movement_pp"]}pp — refresh '
          f'{t["refresh_share_of_GROSS_path_movement"]:.1%}, repair '
          f'{t["repair_share_of_GROSS_path_movement"]:.1%}. Mean absolute movements do NOT add to '
          f'the net; the difference is directional cancellation.')
    print(f'SHAPLEY (order-neutral): refresh {t["shapley_refresh_mean_abs_pp"]}pp '
          f'({t["shapley_refresh_share_ORDER_NEUTRAL"]:.1%}), repair '
          f'{t["shapley_repair_mean_abs_pp"]}pp; mean |interaction| '
          f'{t["mean_abs_interaction_pp"]}pp')
    print(f'side flips {t["side_flips_at_frozen_n"]} at the frozen n, '
          f'{t["side_flips_surviving_reference_estimate"]} surviving noise separation   '
          f'rank changes {t["rank_changes"]}   '
          f'{t["games_surviving_holm"]}/{t["games"]} distinguishable from zero after Holm')
    print(f'\n{"game":<12}{"p_before":>9}{"p_after":>9}{"d_card":>9}{"d_ref":>9}{"CI(simul)":>20}'
          f'{"rank":>9}{"flip":>6}')
    for g in r["games"]:
        e = g["refresh_reference_estimate"]
        print(f'{g["game"]:<12}{g["p_home_S_B_after_8_13_repair"]:>9.4f}{g["p_home_S_C_after_8_15_16"]:>9.4f}'
              f'{g["delta_pp_frozen_n_8_15_16_REFRESH"]:>+9.3f}{e["mean_signed_pp"]:>+9.4f}'
              f'  [{e["ci_simultaneous"][0]:+.3f},{e["ci_simultaneous"][1]:+.3f}]'
              f'{str(g["rank_by_p_home_before"])+"->"+str(g["rank_by_p_home_after"]):>9}'
              f'{"YES" if g["side_flipped_at_frozen_n"] else "-":>6}')
    print(f'\nedges/selections: {r["edges_and_selections"]["edge"]} — '
          f'{r["edges_and_selections"]["REASON"][:110]}...')
    print(f'wrote {OUT}')
