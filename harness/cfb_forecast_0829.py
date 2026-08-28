"""CFB decision output for 2026-08-29 — the first CFB forecast this system has ever emitted.

WHICH ARM, AND WHY IT IS NOT THE OBVIOUS ONE. The walk-forward showed the full v1 form model beating
both internal baselines across weeks 2-15 and pooled (Brier 0.18223 vs 0.18427 causal Elo, paired
CI95 excluding zero). On WEEK 1 it does the opposite: Brier 0.18828 against Elo's 0.18642, and its
calibration falls outside the registered gates (slope 0.846 against a 0.85 floor, intercept +0.136
against a 0.10 limit). Every game on 2026-08-29 is a season opener.

The cause is not mysterious and the preregistration named it in advance: EWMA form carries LAST
season's scoring into an opener played by a substantially different team, and week_one_policy says
"Never pretend prior-season team form is a complete Week 1 state."

So the Week 1 arm drops the form block and keeps Elo plus the two context flags. Tested over 15
season-openers it posts the lowest Week-1 Brier of any arm tried, 0.18327, and is the ONLY arm whose
Week-1 calibration sits inside both registered gates (slope 0.932, intercept +0.089). Training a
Week-1-only model was also tried and was worse on every arm -- fewer games, more noise.

WHAT IS NOT CLAIMED. The lean arm does NOT significantly beat plain causal Elo on openers: paired
by season the mean difference is -0.00224 with a 95% interval of [-0.00503, +0.00099], which
includes zero. It is the best-calibrated Week 1 arm available and it is not a demonstrated
improvement over Elo. Both are reported.

FIXTURES ARE OWNER-RELAYED, NOT ACQUIRED. The archive ends at the 2025 season, so the 8/29 fixture
list comes from the relayed DraftKings board. That board's "Tomorrow" section was captured from the
top, but Week 1 Saturday carries far more FBS games than the eight relayed -- this is a PARTIAL
slate and is labelled as such. Prices are used ONLY in the action overlay, never as a feature.
"""
from __future__ import annotations

MODULE_ID = "cfb_forecast_0829"

import hashlib
import json
import math
import os
import re
import unicodedata

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfb_v1_port as V1

SLATE_DATE = "2026-08-29"
TEAM_INFO_2026 = ("/home/user/sportsdataverse/cfbfastR-data/team_info/parquet/"
                  "cfb_team_info_2026.parquet")
RELAY = f"data/cfb/odds/2026-08-28_owner_relay_dk_forward.json"
OUT = f"cards/{SLATE_DATE}_cfb_board.json"

ARM_LEAN = "cfb.fbs.elo_context_logit.v1_0.week1_shadow"
ARM_FULL = "cfb.fbs.elo_form_logit_ridge.v1_0.shadow"
ARM_ELO = "cfb.fbs.causal_elo.v1_0.baseline"
ARM_RATE = "cfb.fbs.expanding_home_rate.v1_0.baseline"

LEAN = ["elo_diff_with_home_advantage", "neutral_site", "conference_game"]


def final_elo(feat_source, k, hfa, regress, alpha):
    """Terminal Elo after the last acquired game, then the registered between-season regression."""
    elo, last_season = {}, {}
    for r in feat_source.itertuples(index=False):
        h, a, s = r.home_team, r.away_team, r.season
        for t in (h, a):
            if last_season.get(t) is not None and last_season[t] != s:
                elo[t] = 1500.0 + (elo.get(t, 1500.0) - 1500.0) * regress
            last_season[t] = s
        eh, ea = elo.get(h, 1500.0), elo.get(a, 1500.0)
        adv = 0.0 if bool(r.neutral_site) else hfa
        exp_h = 1.0 / (1.0 + 10 ** (-((eh + adv) - ea) / 400.0))
        res_h = 1.0 if r.home_points > r.away_points else (0.5 if r.home_points == r.away_points
                                                           else 0.0)
        mv = math.log1p(abs(r.home_points - r.away_points))
        elo[h] = eh + k * mv * (res_h - exp_h)
        elo[a] = ea + k * mv * ((1 - res_h) - (1 - exp_h))
    # carry into 2026: one more between-season regression, exactly as any opener would get
    return {t: 1500.0 + (v - 1500.0) * regress for t, v in elo.items()}, last_season


def _norm(x):
    """Fold diacritics and punctuation before matching a team name.

    A first pass matched on lowercase only and refused two real FBS games: the book writes
    "Hawaii" where the team table writes "Hawai\u2019i", and "San Jose State" against
    "San Jos\u00e9 State". Refusing a forecast because of an apostrophe is not caution, it is a
    bug wearing caution's clothes. Folding is narrow -- accents and non-alphanumerics only -- so it
    cannot merge two genuinely different programs.
    """
    x = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", x.lower())


def resolve_teams():
    ti = pd.read_parquet(TEAM_INFO_2026)
    lookup = {}
    for r in ti.itertuples(index=False):
        for nm in (r.school, r.abbreviation, r.alt_name1, r.alt_name2, r.alt_name3):
            if isinstance(nm, str) and nm.strip():
                lookup.setdefault(_norm(nm), []).append(
                    {"school": r.school, "classification": r.classification,
                     "conference": r.conference, "team_id": r.team_id})
    return ti, lookup


def match(name, lookup):
    hits = lookup.get(_norm(name))
    if not hits:
        return None, "NAME_NOT_IN_2026_TEAM_INFO"
    schools = {h["school"] for h in hits}
    if len(schools) > 1:
        return None, f"NAME_AMBIGUOUS_ACROSS_{sorted(schools)}"
    return hits[0], None


def promoted_teams(feat):
    """Teams whose LAST acquired season was not FBS. Their Elo was earned in another subdivision."""
    seen = {}
    for side in ("home", "away"):
        for t, s, dv in zip(feat[f"{side}_team"], feat["season"], feat[f"{side}_division"]):
            if isinstance(t, str) and isinstance(dv, str):
                seen.setdefault(t, {})[int(s)] = dv
    return {t: m[max(m)] for t, m in seen.items() if m and m[max(m)] != "fbs"}


def implied(o):
    return None if o is None else (-o / (-o + 100.0) if o < 0 else 100.0 / (o + 100.0))


def profit(o, stake=100.0):
    return stake * (100.0 / -o) if o < 0 else stake * (o / 100.0)


def build():
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer

    man, d = V1._load()
    best, _ = V1.select_hyperparameters(d)
    feat = V1.build_state(d, best["k"], best["hfa"], best["regress"], best["alpha"])
    elo26, last_season = final_elo(d, best["k"], best["hfa"], best["regress"], best["alpha"])

    tr = feat[(feat.home_division == "fbs") & (feat.away_division == "fbs")]
    lean = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(C=1.0, max_iter=2000)).fit(tr[LEAN], tr["home_win"])
    full = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(C=1.0, max_iter=2000)).fit(tr[V1.FEATURES],
                                                                       tr["home_win"])
    elo_only = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             LogisticRegression(C=1.0, max_iter=2000)).fit(
        tr[["elo_diff_with_home_advantage"]], tr["home_win"])
    marg = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         Ridge(alpha=1.0)).fit(tr[LEAN], tr["home_margin"])
    home_rate = float(tr["home_win"].mean())

    lower_div = promoted_teams(feat)
    ti, lookup = resolve_teams()
    relay = json.load(open(RELAY))
    slate = [g for g in relay["games"] if g["game_date"] == SLATE_DATE]

    rows, refused = [], []
    for g in slate:
        aw, hm = match(g["away"], lookup), match(g["home"], lookup)
        if aw[0] is None or hm[0] is None:
            refused.append({"game": f'{g["away"]} @ {g["home"]}',
                            "reason": aw[1] or hm[1],
                            "detail": "team name could not be resolved against the sourced 2026 "
                                      "team table; no forecast may rest on a guessed identity"})
            continue
        A, H = aw[0], hm[0]
        cohort = f'{A["classification"].upper()}_VS_{H["classification"].upper()}'
        if A["classification"] != "fbs" or H["classification"] != "fbs":
            refused.append({"game": f'{A["school"]} @ {H["school"]}', "cohort": cohort,
                            "reason": "OUT_OF_COHORT_NOT_FBS_VS_FBS",
                            "detail": "the registered cohort is FBS vs FBS; classification is "
                                      "sourced from the 2026 team table, not asserted"})
            continue
        ea, eh = elo26.get(A["school"]), elo26.get(H["school"])
        if ea is None or eh is None:
            refused.append({"game": f'{A["school"]} @ {H["school"]}',
                            "reason": "NO_PRIOR_ELO_STATE",
                            "detail": f'no acquired game history for '
                                      f'{A["school"] if ea is None else H["school"]}'})
            continue
        conf_game = 1.0 if (A["conference"] == H["conference"]) else 0.0
        X = pd.DataFrame([{"elo_diff_with_home_advantage": (eh + best["hfa"]) - ea,
                           "neutral_site": 0.0, "conference_game": conf_game}])
        Xf = X.copy()
        for c in V1.FEATURES:
            if c not in Xf:
                Xf[c] = np.nan
        Xf = Xf[V1.FEATURES]
        p_lean = float(lean.predict_proba(X[LEAN])[0, 1])
        p_full = float(full.predict_proba(Xf)[0, 1])
        p_elo = float(elo_only.predict_proba(X[["elo_diff_with_home_advantage"]])[0, 1])
        m_lean = float(marg.predict(X[LEAN])[0])

        ml = g["moneyline"]
        ov = {"away_price": ml["away"], "home_price": ml["home"]}
        if ml["away"] is not None and ml["home"] is not None:
            be_a, be_h = implied(ml["away"]), implied(ml["home"])
            ov.update({"break_even_away": round(be_a, 6), "break_even_home": round(be_h, 6),
                       "ev_home_per_100": round(p_lean * profit(ml["home"])
                                                - (1 - p_lean) * 100.0, 4),
                       "ev_away_per_100": round((1 - p_lean) * profit(ml["away"])
                                                - p_lean * 100.0, 4),
                       "edge_home_pp": round(100 * (p_lean - be_h), 4),
                       "edge_away_pp": round(100 * ((1 - p_lean) - be_a), 4)})
        else:
            ov["null_reason"] = "MONEYLINE_NOT_OFFERED — padlocked on the book"

        promo = {t: lower_div[t] for t in (A["school"], H["school"]) if t in lower_div}
        side = H["school"] if p_lean >= 0.5 else A["school"]
        spread_disagree = abs(m_lean - (-g["spread"]["home"])) if g["spread"]["home"] is not None \
            else None
        rows.append({
            "game": f'cfb:{A["school"]} @ {H["school"]}', "away": A["school"], "home": H["school"],
            "cohort": cohort, "conference_game": bool(conf_game),
            "away_conference": A["conference"], "home_conference": H["conference"],
            "start_slot_as_relayed": g["slot_as_displayed"],
            "elo_home_carried": round(eh, 2), "elo_away_carried": round(ea, 2),
            "decision_arm": ARM_LEAN,
            "model_side": side, "p_home": round(p_lean, 6),
            "p_side": round(max(p_lean, 1 - p_lean), 6),
            "projected_margin_home": round(m_lean, 3),
            "alternates": {ARM_FULL: round(p_full, 6), ARM_ELO: round(p_elo, 6),
                           ARM_RATE: round(home_rate, 6)},
            "market_overlay": ov,
            "fbs_fcs_extreme_spread_review": (
                None if spread_disagree is None or spread_disagree <= 14 else
                {"model_margin": round(m_lean, 2), "book_home_spread": g["spread"]["home"],
                 "disagreement_points": round(spread_disagree, 2),
                 "status": "AUDIT_REQUIRED",
                 "rule": "week_one_policy: a model-market spread disagreement greater than 14 "
                         "points cannot become a candidate without source and roster review"}),
            "subdivision_transition": (
                None if not promo else
                {"teams": {t: f"last acquired season was {d}, 2026 table says fbs"
                           for t, d in promo.items()},
                 "concern": "Elo carried into this game was earned in another subdivision",
                 "measured_not_assumed": (
                     "I expected this to be a weak spot and measured it instead: across 165 "
                     "out-of-fold games involving a team in its first FBS season the model is NOT "
                     "worse (Brier 0.17441 against 0.18235 elsewhere) and the calibration slope is "
                     "0.968. The calibration INTERCEPT does run high at +0.159 against a 0.10 "
                     "gate, on n=165 — weak evidence, low power. Recorded as a caveat, not a "
                     "blocker, because the data does not support blocking."),
                 "status": "DISCLOSED_LOW_POWER_CAVEAT"}),
            "forecast_status": "FORECAST_REGISTERED",
            "action_status": "NO_SELECTION",
        })

    board = {
        "record_id": f"BOARD-{SLATE_DATE}-CFB",
        "slate_date": SLATE_DATE, "sport": "cfb",
        "builder": "harness/cfb_forecast_0829.py (COMMITTED)",
        "forecast_anchor_utc": "2026-08-28T11:45:00Z",
        "lifecycle": {
            "v2_status": "PREREGISTERED_DATA_ACQUISITION_PENDING — schedules acquired, but the "
                         "EPA, talent, returning-production, quarterback and coach-continuity "
                         "blocks are NOT, so v2 cannot be fit",
            "v2_input_blocked": True,
            "policy_applied": "week_one_policy: publish v1 baseline forecasts with "
                              "V2_INPUT_BLOCKED when the Week 1 blocks are missing",
        },
        "DECISION_ARM": {
            "arm": ARM_LEAN,
            "features": LEAN,
            "why_not_the_full_v1_arm": (
                "the full form arm wins pooled across weeks 2-15 but LOSES on Week 1 (Brier "
                "0.18828 vs causal Elo 0.18642) and its Week-1 calibration falls outside the "
                "registered gates: slope 0.846 against a 0.85 floor and intercept +0.136 against a "
                "0.10 limit. Every 8/29 game is an opener. EWMA form carries last season's scoring "
                "into a game played by a substantially different team."),
            "week1_evidence": {"n_games": 758, "n_seasons": 15,
                               "brier": 0.18327, "calibration_slope": 0.932,
                               "calibration_intercept": 0.089,
                               "gates_slope_range": [0.85, 1.15], "gates_abs_intercept_max": 0.10,
                               "passes_week1_calibration": True},
            "NOT_CLAIMED": (
                "the lean arm is NOT a demonstrated improvement over plain causal Elo on openers. "
                "Paired by season the mean Brier difference is -0.00224 with a 95% interval of "
                "[-0.00503, +0.00099], which INCLUDES ZERO. It is the best-calibrated Week 1 arm "
                "available, not a proven edge over Elo."),
            "also_tried_and_rejected": "a Week-1-only training set was worse on every arm "
                                       "(fewer games, more noise)",
        },
        "hyperparameters_frozen_on": {"window": list(V1.FREEZE_SEASONS), **best},
        "training": {"rows": int(len(tr)), "seasons": f'{int(feat.season.min())}-'
                                                      f'{int(feat.season.max())}',
                     "cohort": "FBS_VS_FBS"},
        "source": {"acquisition_manifest": "data/cfb/model/CFB_V2_ACQUISITION_MANIFEST.json",
                   "repository": man["source"]["repository"],
                   "commit": man["source"]["commit"],
                   "team_table_2026": TEAM_INFO_2026},
        "SLATE_PROVENANCE": {
            "fixtures_from": "owner-relayed DraftKings board (data/cfb/odds/"
                             "2026-08-28_owner_relay_dk_forward.json)",
            "why_not_acquired": "the cfbfastR archive ends at the 2025 season; no 2026 schedule "
                                "exists in it",
            "PARTIAL_SLATE": ("Week 1 Saturday carries far more FBS games than the relayed rows. "
                              "This board covers only what the relay captured and is NOT the "
                              "complete 8/29 slate. No aggregate over it may be described as a "
                              "slate-wide record."),
            "grade": "OWNER_RELAYED_SINGLE_BOOK — identification only; binds no result",
        },
        "MARKET_POSITION": {
            "prices_are_never_features": True,
            "overlay_only": "prices enter the action/EV layer only, after the forecast",
            "de_vig": "NOT PERFORMED — break-even from each side's own posted price",
            "selections": 0,
            "why_zero": "this arm is a week-1 shadow of a model whose own v2 lifecycle is still "
                        "PREREGISTERED_DATA_ACQUISITION_PENDING. Wager authority is NO and stake "
                        "is 0 in the preregistration itself; no EV figure can override that.",
        },
        "n_forecast": len(rows), "n_refused": len(refused),
        "reconciliation": {"relayed_on_date": len(slate), "forecast": len(rows),
                           "refused": len(refused),
                           "identity": f"{len(slate)} = {len(rows)} + {len(refused)}",
                           "holds": len(slate) == len(rows) + len(refused)},
        "refused": refused,
        "rows": rows,
        "wager_authority": "NO",
        "LEDGERS": {"model_authorized_wagers_usd": 0, "n_bets": 0, "units": 0.0},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(board, fh, indent=1, sort_keys=True)
    return board


if __name__ == "__main__":
    b = build()
    print("FROZEN", b["record_id"], "|", hashlib.sha256(open(OUT, "rb").read()).hexdigest()[:8])
    print("decision arm:", b["DECISION_ARM"]["arm"])
    print(f'reconciliation: {b["reconciliation"]["identity"]} holds={b["reconciliation"]["holds"]}')
    print()
    print(f"{'game':<38}{'side':<20}{'p':>8}{'marg':>8}{'DK':>8}{'EV/$100':>10}")
    for r in b["rows"]:
        ov = r["market_overlay"]
        px = ov["home_price"] if r["model_side"] == r["home"] else ov["away_price"]
        ev = ov.get("ev_home_per_100" if r["model_side"] == r["home"] else "ev_away_per_100")
        tag = ""
        if r["fbs_fcs_extreme_spread_review"]:
            tag += f'  AUDIT {r["fbs_fcs_extreme_spread_review"]["disagreement_points"]}pt'
        if r["subdivision_transition"]:
            tag += "  [promoted]"
        print(f'{r["game"][4:]:<38}{r["model_side"]:<20}{r["p_side"]:>8.4f}'
              f'{r["projected_margin_home"]:>8.2f}{(str(px) if px else "lock"):>8}'
              f'{(f"{ev:+.2f}" if ev is not None else "n/a"):>10}{tag}')
    print()
    for x in b["refused"]:
        print("  REFUSED", x["game"], "—", x["reason"])
