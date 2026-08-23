#!/usr/bin/env python3
"""PAIRED EVALUATION — baseline vs challenger on identical games, with the audits that can kill it.

OWNER SPECIFICATION 2026-08-23. For every paired game preserve brier/logloss for BOTH arms, their
deltas, the home result, the direction the challenger moved, and the starter-information dose.
Report: mean paired Brier difference, mean paired log-loss difference, percentage of games improved,
a SLATE-CLUSTERED bootstrap confidence interval, calibration intercept and slope, discrimination,
results by information dose, results by move direction, and results on games where the two arms flip
winners.

WHY SLATE-CLUSTERED. Games on one night share weather, umpiring, schedule spot and — decisively —
the night's home/away outcome balance. 2026-08-21 went 14-1 to the home side. Resampling individual
GAMES treats those fifteen as fifteen independent draws and produces an interval far too narrow.
Resampling SLATES keeps the correlated block intact. The unit of independence is the night.

WHY THE DIRECTIONAL AUDIT IS NOT OPTIONAL. On 2026-08-21 three of the four v2 flips moved TOWARD the
home side on a night home teams went 14-1. A model that has simply acquired home-side exposure looks
exactly like a model that has acquired starter information, until you split the result by move
direction. The split is reported unconditionally, not when something looks suspicious.

NEGATIVE IS BETTER throughout: delta = challenger - baseline, on Brier and on log-loss.
"""
from __future__ import annotations

import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Promotion stages (owner specification). These describe what a sample SIZE permits; they never by
# themselves permit anything — the promotion gate, paper-only and wager authority all still apply.
STAGES = ((0, 100, "DESCRIPTIVE_SHADOW_EVIDENCE_ONLY"),
          (100, 500, "PRELIMINARY_CHALLENGER_EVALUATION"),
          (500, 10 ** 9, "ELIGIBLE_FOR_FORMAL_CALIBRATION_AND_SUPERIORITY_REVIEW"))
LONG_TERM_HORIZON = 1000

TOWARD_HOME = "TOWARD_HOME"
TOWARD_AWAY = "TOWARD_AWAY"
NO_MOVE = "NO_MOVE"

DOSE_BINS = (("ALL_CAP_BASELINE", 0.0, 0.0), ("LOW", 0.0, 0.50),
             ("PARTIAL", 0.50, 1.0), ("FULL", 1.0, 1.0))


def brier(p, y):
    return (p - y) ** 2


def logloss(p, y, eps=1e-12):
    p = min(max(p, eps), 1 - eps)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def move_direction(p_prior, p_challenger, tol=0.0):
    d = p_challenger - p_prior
    if abs(d) <= tol:
        return NO_MOVE
    return TOWARD_HOME if d > 0 else TOWARD_AWAY


def dose_bin(frac):
    if frac is None:
        return "UNKNOWN"
    if frac == 0.0:
        return "ALL_CAP_BASELINE"
    if frac >= 1.0:
        return "FULL"
    return "LOW" if frac < 0.50 else "PARTIAL"


def per_game(pairs):
    """The per-game record the owner requires preserved, one row per PAIRED game."""
    out = []
    for p in pairs:
        pb, pc, y = p["p_home_prior"], p["p_home_challenger"], int(p["home_win"])
        bb, bc = brier(pb, y), brier(pc, y)
        lb, lc = logloss(pb, y), logloss(pc, y)
        out.append({
            "game_id": p.get("game_id"),
            "slate_date": p.get("slate_date"),
            "p_home_prior": pb, "p_home_challenger": pc,
            "brier_prior": bb, "brier_challenger": bc, "delta_brier": bc - bb,
            "logloss_prior": lb, "logloss_challenger": lc, "delta_logloss": lc - lb,
            "home_result": y,
            "challenger_move_direction": move_direction(pb, pc),
            "starter_information_fraction": p.get("starter_information_fraction"),
            "winner_flip": (pb >= .5) != (pc >= .5),
            "prior_correct": int((pb >= .5) == (y == 1)),
            "challenger_correct": int((pc >= .5) == (y == 1)),
        })
    return out


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def calibration(rows, key="p_home_challenger"):
    """Intercept and slope of a logistic recalibration: y ~ a + b * logit(p).

    b < 1 is the signature of OVERCONFIDENCE; b > 1 of underconfidence, which is what a compressed
    model looks like. Fitted by Newton steps because the whole point is to have no dependency the
    frozen environment might not carry."""
    import math as _m
    xs, ys = [], []
    for r in rows:
        p = min(max(r[key], 1e-9), 1 - 1e-9)
        xs.append(_m.log(p / (1 - p)))
        ys.append(float(r["home_result"]))
    n = len(xs)
    if n < 3 or len(set(ys)) < 2:
        return {"intercept": None, "slope": None, "n": n,
                "reason": "fewer than three games or a single outcome class — a calibration line "
                          "through one class is not a calibration"}
    a, b = 0.0, 1.0
    for _ in range(100):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            z = a + b * x
            mu = 1 / (1 + _m.exp(-z)) if z >= -700 else 0.0
            w = mu * (1 - mu)
            g0 += (y - mu); g1 += (y - mu) * x
            h00 += w; h01 += w * x; h11 += w * x * x
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            break
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        a += da; b += db
        if abs(da) < 1e-10 and abs(db) < 1e-10:
            break
    return {"intercept": a, "slope": b, "n": n,
            "reading": ("slope below 1 = overconfident; above 1 = underconfident, the signature of "
                        "a compressed model")}


def auc(rows, key="p_home_challenger"):
    """Discrimination. Rank-based with explicit tie handling — half credit for a tie, because a
    model that gives every game the same probability must score 0.5, not 1.0."""
    pos = [r[key] for r in rows if r["home_result"] == 1]
    neg = [r[key] for r in rows if r["home_result"] == 0]
    if not pos or not neg:
        return {"auc": None, "n_pos": len(pos), "n_neg": len(neg),
                "reason": "one outcome class is empty — AUC is undefined"}
    wins = ties = 0
    for a in pos:
        for b in neg:
            if a > b:
                wins += 1
            elif a == b:
                ties += 1
    return {"auc": (wins + 0.5 * ties) / (len(pos) * len(neg)),
            "n_pos": len(pos), "n_neg": len(neg)}


def _lcg(seed):
    """A deterministic generator so a bootstrap interval reproduces exactly. Reported intervals that
    move between runs cannot be audited."""
    state = seed & 0xFFFFFFFF

    def nxt(n):
        # THE LOW BITS OF AN LCG ARE NOT RANDOM. `state % n` for a small n uses exactly those bits:
        # with n=2 this generator's low bit is degenerate, and the first version of this bootstrap
        # resampled the SAME slate every draw and reported a ZERO-WIDTH interval as if it were
        # precision. That is the single most dangerous failure this module could have, so the draw
        # is taken from the HIGH bits and a fixture requires a two-slate interval to span both
        # slates' values.
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return (state >> 15) % n
    return nxt


def slate_bootstrap(rows, stat="delta_brier", reps=2000, seed=20260823, alpha=0.05):
    """Percentile interval over SLATES, not games. The night is the unit of independence.

    Resampling games would treat 2026-08-21's fifteen results — on a 14-1 home night — as fifteen
    independent draws, and report an interval far narrower than the evidence supports."""
    by_slate = {}
    for r in rows:
        by_slate.setdefault(r.get("slate_date"), []).append(r)
    slates = sorted(by_slate)
    k = len(slates)
    if k < 2:
        return {"lo": None, "hi": None, "reps": 0, "n_slates": k, "n_games": len(rows),
                "point": _mean([r[stat] for r in rows]),
                "reason": "a bootstrap over fewer than two slates resamples the same night every "
                          "time and would report a zero-width interval as if it were precision"}
    nxt = _lcg(seed)
    means = []
    for _ in range(reps):
        vals = []
        for _ in range(k):
            for r in by_slate[slates[nxt(k)]]:
                vals.append(r[stat])
        if vals:
            means.append(sum(vals) / len(vals))
    means.sort()
    lo = means[int(alpha / 2 * len(means))]
    hi = means[min(len(means) - 1, int((1 - alpha / 2) * len(means)))]
    return {"lo": lo, "hi": hi, "reps": reps, "n_slates": k, "n_games": len(rows),
            "point": _mean([r[stat] for r in rows]), "seed": seed,
            "cluster_unit": "slate_date",
            "excludes_zero": (hi < 0) or (lo > 0)}


def stage_for(n):
    for lo, hi, name in STAGES:
        if lo <= n < hi:
            return name
    return STAGES[-1][2]


def subgroup(rows, keyfn):
    out = {}
    for r in rows:
        out.setdefault(keyfn(r), []).append(r)
    return {k: {"n": len(v),
                "mean_delta_brier": _mean([x["delta_brier"] for x in v]),
                "mean_delta_logloss": _mean([x["delta_logloss"] for x in v]),
                "pct_improved": _mean([1.0 if x["delta_brier"] < 0 else 0.0 for x in v]),
                "challenger_record": f'{sum(x["challenger_correct"] for x in v)}-'
                                     f'{len(v) - sum(x["challenger_correct"] for x in v)}',
                "baseline_record": f'{sum(x["prior_correct"] for x in v)}-'
                                   f'{len(v) - sum(x["prior_correct"] for x in v)}'}
            for k, v in sorted(out.items(), key=lambda kv: str(kv[0]))}


def report(pairs, reps=2000, seed=20260823):
    """The full required report. Every subgroup split is emitted unconditionally."""
    rows = per_game(pairs)
    n = len(rows)
    rep = {
        "n_paired_games": n,
        "n_slates": len({r.get("slate_date") for r in rows}),
        "promotion_stage": stage_for(n),
        "long_term_horizon_games": LONG_TERM_HORIZON,
        "mean_paired_delta_brier": _mean([r["delta_brier"] for r in rows]),
        "mean_paired_delta_logloss": _mean([r["delta_logloss"] for r in rows]),
        "pct_games_improved": _mean([1.0 if r["delta_brier"] < 0 else 0.0 for r in rows]),
        "baseline": {"brier": _mean([r["brier_prior"] for r in rows]),
                     "logloss": _mean([r["logloss_prior"] for r in rows]),
                     "record": f'{sum(r["prior_correct"] for r in rows)}-'
                               f'{n - sum(r["prior_correct"] for r in rows)}'},
        "challenger": {"brier": _mean([r["brier_challenger"] for r in rows]),
                       "logloss": _mean([r["logloss_challenger"] for r in rows]),
                       "record": f'{sum(r["challenger_correct"] for r in rows)}-'
                                 f'{n - sum(r["challenger_correct"] for r in rows)}'},
        "slate_clustered_bootstrap_delta_brier": slate_bootstrap(rows, "delta_brier", reps, seed),
        "slate_clustered_bootstrap_delta_logloss": slate_bootstrap(rows, "delta_logloss", reps, seed),
        "calibration_challenger": calibration(rows, "p_home_challenger"),
        "calibration_baseline": calibration(rows, "p_home_prior"),
        "discrimination_challenger": auc(rows, "p_home_challenger"),
        "discrimination_baseline": auc(rows, "p_home_prior"),
        "by_information_dose": subgroup(rows, lambda r: dose_bin(r["starter_information_fraction"])),
        "by_move_direction": subgroup(rows, lambda r: r["challenger_move_direction"]),
        "by_slate": subgroup(rows, lambda r: r["slate_date"]),
        "on_winner_flips": subgroup(rows, lambda r: "FLIP" if r["winner_flip"] else "NO_FLIP"),
        "per_game": rows,
    }
    rep["promotion_criteria"] = promotion_check(rep)
    return rep


def promotion_check(rep):
    """The owner's five promotion conditions, evaluated. This NEVER promotes anything: it reports
    which conditions are met, and the promotion gate, paper-only rule and wager authority all
    continue to apply independently."""
    c = {}
    c["negative_paired_brier_difference"] = (rep["mean_paired_delta_brier"] is not None
                                             and rep["mean_paired_delta_brier"] < 0)
    c["negative_paired_logloss_difference"] = (rep["mean_paired_delta_logloss"] is not None
                                               and rep["mean_paired_delta_logloss"] < 0)
    bs = rep["slate_clustered_bootstrap_delta_brier"]
    c["confidence_interval_supports_improvement"] = bool(bs.get("hi") is not None and bs["hi"] < 0)
    cal = rep["calibration_challenger"]
    base = rep["calibration_baseline"]
    c["no_material_calibration_regression"] = (
        cal.get("slope") is not None and base.get("slope") is not None
        and abs(cal["slope"] - 1.0) <= abs(base["slope"] - 1.0) + 0.10)
    def _spread(d):
        vals = [v["mean_delta_brier"] for v in d.values()
                if v["n"] >= 5 and v["mean_delta_brier"] is not None]
        return vals
    broad = []
    for name, d in (("slate", rep["by_slate"]), ("move_direction", rep["by_move_direction"]),
                    ("information_dose", rep["by_information_dose"])):
        vals = _spread(d)
        broad.append(bool(vals) and all(v < 0 for v in vals))
    c["improvement_not_confined_to_one_subgroup"] = all(broad) if any(broad) else False
    c["sample_stage"] = rep["promotion_stage"]
    c["all_conditions_met"] = all(v for k, v in c.items()
                                  if isinstance(v, bool))
    c["note"] = ("Meeting every condition makes a challenger ELIGIBLE FOR REVIEW. It does not "
                 "promote it, does not create action authority, and does not change the standing "
                 "gate, the $0 model-authorized ledger or the paper-only ruling.")
    return c


def selftest():
    f = []
    # --- per-game bookkeeping -------------------------------------------------------------------
    rows = per_game([{"game_id": "g1", "slate_date": "2026-08-19", "p_home_prior": 0.50,
                      "p_home_challenger": 0.60, "home_win": 1,
                      "starter_information_fraction": 0.8}])
    r = rows[0]
    if abs(r["brier_prior"] - 0.25) > 1e-12 or abs(r["brier_challenger"] - 0.16) > 1e-12:
        f.append(f"per-game Brier wrong: {r['brier_prior']} / {r['brier_challenger']}")
    if r["delta_brier"] >= 0:
        f.append("delta_brier is not challenger minus baseline (negative must mean better)")
    if r["delta_logloss"] >= 0:
        f.append("delta_logloss sign convention is wrong")
    if r["challenger_move_direction"] != TOWARD_HOME:
        f.append("a move from .50 to .60 was not recorded as TOWARD_HOME")
    if move_direction(0.6, 0.4) != TOWARD_AWAY or move_direction(0.5, 0.5) != NO_MOVE:
        f.append("move_direction is wrong away from the home case")
    if r["winner_flip"]:
        f.append(".50 -> .60 was called a winner flip; both pick home")
    if not per_game([{"game_id": "x", "slate_date": "d", "p_home_prior": 0.45,
                      "p_home_challenger": 0.55, "home_win": 1}])[0]["winner_flip"]:
        f.append("a genuine winner flip across .5 was not detected")

    # --- dose bins on their boundaries ------------------------------------------------------------
    for frac, want in ((0.0, "ALL_CAP_BASELINE"), (0.01, "LOW"), (0.49, "LOW"), (0.50, "PARTIAL"),
                       (0.99, "PARTIAL"), (1.0, "FULL"), (None, "UNKNOWN")):
        if dose_bin(frac) != want:
            f.append(f"dose_bin({frac}) = {dose_bin(frac)}, expected {want}")

    # --- SLATE CLUSTERING: the check this module exists for ---------------------------------------
    # One night of fifteen correlated games plus one night of one game. A GAME bootstrap would treat
    # this as sixteen independent draws; the SLATE bootstrap must resample nights.
    big = [{"slate_date": "2026-08-21", "delta_brier": -0.05, "delta_logloss": -0.05}
           for _ in range(15)]
    small = [{"slate_date": "2026-08-19", "delta_brier": 0.20, "delta_logloss": 0.20}]
    bs = slate_bootstrap(big + small, reps=500, seed=7)
    if bs["n_slates"] != 2:
        f.append(f"bootstrap clustered on {bs['n_slates']} units, expected 2 slates")
    if bs["cluster_unit"] != "slate_date":
        f.append("the bootstrap does not declare its clustering unit")
    if not (bs["lo"] < bs["point"] < bs["hi"] or bs["lo"] <= bs["point"] <= bs["hi"]):
        f.append(f"the point estimate {bs['point']} lies outside its own interval "
                 f"[{bs['lo']}, {bs['hi']}]")
    # with only two slates, the interval must be WIDE — it must contain both extremes
    if not (bs["lo"] <= -0.05 and bs["hi"] >= 0.15):
        f.append(f"a two-slate bootstrap produced a narrow interval [{bs['lo']:.4f}, "
                 f"{bs['hi']:.4f}] — the slates are not being resampled as blocks")
    # DETERMINISM: the same seed must reproduce the interval exactly
    if slate_bootstrap(big + small, reps=500, seed=7) != bs:
        f.append("two bootstraps with the same seed produced different intervals")
    if slate_bootstrap(big + small, reps=500, seed=8) == bs:
        f.append("changing the seed did not change the bootstrap at all")
    # the RECORDED SEED alone must reproduce the interval. Two datasets over the same two slates,
    # with the same per-slate values but different game counts, must draw the same slate sequence.
    # five slates with distinct values, so the bootstrap mean distribution is rich enough that two
    # different draw sequences cannot land on the same percentile bounds by coincidence
    a1 = [{"slate_date": f"S{i}", "delta_brier": float(i), "delta_logloss": float(i)}
          for i in range(5)]
    a2 = [r for r in a1 for _ in range(3)]
    # checked across a RANGE of seeds: one seed can agree by coincidence, twelve cannot
    for sd in range(1, 13):
        b1 = slate_bootstrap(a1, reps=400, seed=sd)
        b2 = slate_bootstrap(a2, reps=400, seed=sd)
        if (b1["lo"], b1["hi"]) != (b2["lo"], b2["hi"]):
            f.append(f"seed {sd} over the same five slates gave different intervals when the game "
                     f"count changed ({b1['lo']},{b1['hi']}) vs ({b2['lo']},{b2['hi']}) — the draw "
                     f"is seeded by something other than the recorded seed")
            break
        if b1.get("seed") != sd:
            f.append(f"the bootstrap reports seed {b1.get('seed')} but was asked for {sd}")
            break
    # a SINGLE slate cannot support an interval and must say so, not report zero width
    one = slate_bootstrap(big, reps=500, seed=7)
    if one["lo"] is not None or "reason" not in one:
        f.append("a single-slate bootstrap reported an interval instead of refusing")

    # --- calibration ------------------------------------------------------------------------------
    # A perfectly calibrated set must give slope ~1 and intercept ~0.
    perfect = []
    for p, k in ((0.2, 10), (0.5, 10), (0.8, 10)):
        wins = int(round(p * k))
        for i in range(k):
            perfect.append({"p_home_challenger": p, "home_result": 1 if i < wins else 0})
    cal = calibration(perfect)
    if cal["slope"] is None or abs(cal["slope"] - 1.0) > 0.35 or abs(cal["intercept"]) > 0.35:
        f.append(f"calibration on a well-calibrated set gave intercept {cal['intercept']} "
                 f"slope {cal['slope']}")
    # A COMPRESSED model — probabilities near .5 while outcomes are decisive — must give slope > 1.
    comp = [{"p_home_challenger": 0.52, "home_result": 1} for _ in range(20)] + \
           [{"p_home_challenger": 0.48, "home_result": 0} for _ in range(20)]
    cc = calibration(comp)
    if cc["slope"] is None or cc["slope"] <= 1.0:
        f.append(f"a compressed model gave slope {cc['slope']}; compression must read as "
                 f"UNDERCONFIDENCE (slope > 1)")
    over = ([{"p_home_challenger": 0.95, "home_result": 1} for _ in range(14)] +
            [{"p_home_challenger": 0.95, "home_result": 0} for _ in range(6)] +
            [{"p_home_challenger": 0.05, "home_result": 0} for _ in range(14)] +
            [{"p_home_challenger": 0.05, "home_result": 1} for _ in range(6)])
    oc = calibration(over)
    if oc["slope"] is None or oc["slope"] >= 1.0:
        f.append(f"an OVERCONFIDENT set (.95/.05 against 70/30 outcomes) gave slope {oc['slope']}; "
                 f"overconfidence must read as slope < 1")
    if cc["slope"] is not None and oc["slope"] is not None and not (oc["slope"] < 1.0 < cc["slope"]):
        f.append(f"the calibration slope does not separate overconfidence from compression: "
                 f"over={oc['slope']} compressed={cc['slope']}")
    if calibration([{"p_home_challenger": .5, "home_result": 1}])["slope"] is not None:
        f.append("calibration returned a line through a single game")
    if calibration([{"p_home_challenger": .5, "home_result": 1}] * 8)["slope"] is not None:
        f.append("calibration returned a line through a single outcome class")

    # --- discrimination ---------------------------------------------------------------------------
    perfect_sep = [{"p_home_challenger": 0.9, "home_result": 1},
                   {"p_home_challenger": 0.8, "home_result": 1},
                   {"p_home_challenger": 0.2, "home_result": 0}]
    if abs(auc(perfect_sep)["auc"] - 1.0) > 1e-12:
        f.append("AUC is not 1.0 on perfectly separated data")
    flat = [{"p_home_challenger": 0.5, "home_result": 1},
            {"p_home_challenger": 0.5, "home_result": 0}]
    if abs(auc(flat)["auc"] - 0.5) > 1e-12:
        f.append(f"a model giving every game the same probability scored AUC {auc(flat)['auc']}; "
                 f"ties must earn half credit, so it must be exactly 0.5")
    if auc([{"p_home_challenger": .6, "home_result": 1}])["auc"] is not None:
        f.append("AUC was reported with an empty outcome class")

    # --- promotion stages -------------------------------------------------------------------------
    for n, want in ((0, "DESCRIPTIVE_SHADOW_EVIDENCE_ONLY"), (29, "DESCRIPTIVE_SHADOW_EVIDENCE_ONLY"),
                    (99, "DESCRIPTIVE_SHADOW_EVIDENCE_ONLY"), (100, "PRELIMINARY_CHALLENGER_EVALUATION"),
                    (499, "PRELIMINARY_CHALLENGER_EVALUATION"),
                    (500, "ELIGIBLE_FOR_FORMAL_CALIBRATION_AND_SUPERIORITY_REVIEW"),
                    (5000, "ELIGIBLE_FOR_FORMAL_CALIBRATION_AND_SUPERIORITY_REVIEW")):
        if stage_for(n) != want:
            f.append(f"stage_for({n}) = {stage_for(n)}, expected {want}")

    # --- the full report ---------------------------------------------------------------------------
    pairs = []
    for d, k in (("2026-08-19", 15), ("2026-08-21", 14)):
        for i in range(k):
            y = 1 if i % 3 else 0
            pairs.append({"game_id": f"{d}-{i}", "slate_date": d, "p_home_prior": 0.53,
                          "p_home_challenger": 0.58 if y else 0.49, "home_win": y,
                          "starter_information_fraction": 0.73 if d == "2026-08-19" else 0.94})
    rep = report(pairs, reps=300)
    for k in ("mean_paired_delta_brier", "mean_paired_delta_logloss", "pct_games_improved",
              "slate_clustered_bootstrap_delta_brier", "calibration_challenger",
              "discrimination_challenger", "by_information_dose", "by_move_direction",
              "on_winner_flips", "promotion_stage", "promotion_criteria"):
        if k not in rep:
            f.append(f"the report omits the required section {k}")
    if rep["n_paired_games"] != 29 or rep["promotion_stage"] != "DESCRIPTIVE_SHADOW_EVIDENCE_ONLY":
        f.append(f"29 paired games did not land in the descriptive-shadow stage: "
                 f"{rep['promotion_stage']}")
    if set(rep["by_move_direction"]) != {TOWARD_HOME, TOWARD_AWAY}:
        f.append(f"the directional split is missing a direction: {list(rep['by_move_direction'])}")
    if set(rep["by_information_dose"]) != {"PARTIAL"}:
        f.append(f"dose binning wrong in the report: {list(rep['by_information_dose'])}")
    if "FLIP" not in rep["on_winner_flips"]:
        f.append("the report does not split out games where the arms flip winners")
    # PROMOTION NEVER FIRES FROM HERE
    note = rep["promotion_criteria"].get("note", "")
    for phrase in ("does not promote it", "does not create action authority", "paper-only"):
        if phrase not in note:
            f.append(f"the promotion block does not state {phrase!r}: {note[:80]!r}")
    # an all-improving set must NOT satisfy the criteria on one slate alone
    onep = [{"game_id": f"x{i}", "slate_date": "2026-08-21", "p_home_prior": 0.5,
             "p_home_challenger": 0.7, "home_win": 1} for i in range(20)]
    rep1 = report(onep, reps=200)
    if rep1["promotion_criteria"]["confidence_interval_supports_improvement"]:
        f.append("a single-slate sample produced a confidence interval that 'supports improvement'")
    if rep1["promotion_criteria"]["all_conditions_met"]:
        f.append("every promotion condition was met on a single slate of twenty games")

    print("paired_eval selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("delta sign convention flipped so a worse challenger reads as better",
     '            "brier_prior": bb, "brier_challenger": bc, "delta_brier": bc - bb,',
     '            "brier_prior": bb, "brier_challenger": bc, "delta_brier": bb - bc,'),
    ("the bootstrap resamples GAMES, dissolving the correlated night",
     "        for _ in range(k):\n            for r in by_slate[slates[nxt(k)]]:\n                vals.append(r[stat])",
     "        for _ in range(len(rows)):\n            vals.append(rows[nxt(len(rows))][stat])"),
    ("the bootstrap draws from the DEGENERATE low bits of the generator",
     "        return (state >> 15) % n", "        return state % n"),
    ("a single-slate bootstrap reports a zero-width interval instead of refusing",
     "    if k < 2:", "    if False:"),
    ("the bootstrap stops declaring its clustering unit",
     '            "cluster_unit": "slate_date",', '            "cluster_unit": "game",'),
    ("the bootstrap is no longer deterministic",
     "    nxt = _lcg(seed)", "    nxt = _lcg(seed + len(rows))"),
    ("AUC gives ties FULL credit, so a flat model scores 1.0",
     '    return {"auc": (wins + 0.5 * ties) / (len(pos) * len(neg)),',
     '    return {"auc": (wins + ties) / (len(pos) * len(neg)),'),
    ("AUC is reported with an empty outcome class",
     "    if not pos or not neg:", "    if False:"),
    ("calibration fits through a single outcome class",
     "    if n < 3 or len(set(ys)) < 2:", "    if False:"),
    ("calibration reports the slope of the wrong variable, hiding compression",
     "            g0 += (y - mu); g1 += (y - mu) * x", "            g0 += (y - mu); g1 += (y - mu)"),
    ("the dose boundary at 0.50 moves",
     '    return "LOW" if frac < 0.50 else "PARTIAL"', '    return "LOW" if frac <= 0.50 else "PARTIAL"'),
    ("a zero dose is binned as LOW rather than as the baseline",
     '    if frac == 0.0:\n        return "ALL_CAP_BASELINE"', "    if False:\n        pass"),
    ("an unknown dose is silently binned as if it were measured",
     '    if frac is None:\n        return "UNKNOWN"', "    if False:\n        pass"),
    ("move direction ignores the away side",
     "    return TOWARD_HOME if d > 0 else TOWARD_AWAY", "    return TOWARD_HOME"),
    ("a winner flip is no longer detected",
     '            "winner_flip": (pb >= .5) != (pc >= .5),', '            "winner_flip": False,'),
    ("the promotion stage boundary at 100 games moves",
     "STAGES = ((0, 100,", "STAGES = ((0, 30,"),
    ("the promotion stage boundary at 500 games moves",
     '(100, 500, "PRELIMINARY_CHALLENGER_EVALUATION")', '(100, 200, "PRELIMINARY_CHALLENGER_EVALUATION")'),
    ("the confidence-interval condition is satisfied by a point estimate alone",
     '    c["confidence_interval_supports_improvement"] = bool(bs.get("hi") is not None and bs["hi"] < 0)',
     '    c["confidence_interval_supports_improvement"] = bool(bs.get("point") is not None and bs["point"] < 0)'),
    ("the promotion block stops saying it promotes nothing",
     '    c["note"] = ("Meeting every condition makes a challenger ELIGIBLE FOR REVIEW. It does not "',
     '    c["note"] = ("Conditions met. ("'),
    ("the report drops the directional split",
     '        "by_move_direction": subgroup(rows, lambda r: r["challenger_move_direction"]),', "" ),
    ("the report drops the information-dose split",
     '        "by_information_dose": subgroup(rows, lambda r: dose_bin(r["starter_information_fraction"])),', ""),
    ("the report drops the winner-flip split",
     '        "on_winner_flips": subgroup(rows, lambda r: "FLIP" if r["winner_flip"] else "NO_FLIP"),', ""),
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
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=300)
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
    print(__doc__)
