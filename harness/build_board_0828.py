"""The 2026-08-28 MLB forecast board builder — COMMITTED, reusing the registered 8/25 engine path.

WHAT CHANGES ON THIS DATE, AND WHY

Every prior board keyed its rows on a SYNTHETIC pseudo-pk: 827000, 827001, ... invented at slate
build time, shaped exactly like an MLB gamePk and bound to nothing. RJ-007 found four dateless
joins resting on that contract, and the 2026-08-27 P0 showed what it costs — five 8/26 finals were
joined onto 8/27 games because the join key was a team matchup, not an identity. On 2026-08-28 the
archive verification of the two INFERRED 8/27 pks closed the argument empirically: 823014 was
right, and 825038 was a FABRICATION (the real AZ@SF id is 823179; 825038 had been decremented from
CHC@AZ, a different matchup, and no such game exists). One of two inferences was wrong.

So this board carries CAPTURED ids only, and it carries them NAMESPACED:

    canonical_id = "<ID_SPACE>:<integer>",  ID_SPACE in {MLB_GAMEPK, ESPN_GAMEID}

Five 8/28 rows have a real MLB gamePk surfaced from a dated mlb.com slug. The other ten do not —
searching found ESPN gameIds instead, and no gamePk. Both id spaces are integers, so putting them
in one bare column is the 8/27 defect in a new form; the namespace is load-bearing. The field is
named canonical_id, NOT gamePk, precisely so that no consumer can read an ESPN id as a gamePk.
The 827000-series contract is retired for this date and is not reintroduced.

WHAT DOES NOT CHANGE. The engine path, priors, seeds, widening solver and arm set are the
registered 8/25 path, untouched. This is an identity fix, not a model change.

SLATE GRADE. SEARCH_IDENTIFIED_UNCONFIRMED: statsapi, ESPN's API, mlb.com and every aggregator are
EGRESS_BLOCKED (fresh receipts in the schedule record). Snippets identify and never bind. Nothing
here settles, promotes, or feeds the estimator.

STARTER CLASSES (owner vocabulary, 2026-08-27): PROBABLE for a named-and-resolved slot (aggregator
naming, not official confirmation); NAMED_NO_LOG_RETAINED_CAP where the pitcher is named but no
public log was retained here — the log exists in the world, the CAP is OUR retention gap;
TBD_CAP where the slot is unresolvable.

IDENTITY RISK IS TRACKED SEPARATELY FROM STARTER CLASS. Three rows carry a side-swap hazard: the
source that produced PIT@STL was verified to have both pitchers on the wrong teams and is corrected
here, which makes its CWS@MIN line suspect, and MIA@WSH asserts Eury Perez — a Marlins-associated
arm — as the NATIONALS starter while Miami is TBD. A wrong side is not a missing name, so it is
recorded in its own register rather than folded into a starter class or silently discounted through
the dose. The registered dose formula is left exactly as registered.

WNBA AND NFL freeze on their own boards. WNBA is BLOCKED until the wehoop commit carrying 8/27
boxes lands (feature rebuild through the cutoff precedes any forecast; wehoop has not advanced past
3316fa3). NFL is a no-forecast benchmark board: preseason is outside the registered scope of
nfl.rs.epa_logit_ridge.v0_2.shadow.
"""
from __future__ import annotations

MODULE_ID = "build_board_0828"

import datetime as dt
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import build_board_0825 as B

SLATE_DATE = "2026-08-28"
B.SLATE_DATE = SLATE_DATE
B.SLATE_PSV = f"data/mlb/slates/{SLATE_DATE}_slate.psv"
SLATE_BINDING = f"data/mlb/slates/{SLATE_DATE}_slate_binding.json"

EARLIEST_START_UTC = "2026-08-28T18:20:00Z"
TZ_NOTE = "SEARCH_INFERRED_START_ET_STATED"

#: Parks that the 8/25 VENUE map never needed. Without these five, park_factors.get returns the
#: 1.0 default silently and five games would be run at a neutral park with no trace of it.
B.VENUE.update({
    "Chicago Cubs": "Wrigley Field",
    "Cleveland Guardians": "Progressive Field",
    "Tampa Bay Rays": "Tropicana Field",
    "Milwaukee Brewers": "American Family Field",
    "Minnesota Twins": "Target Field",
})

ID_SPACES = ("MLB_GAMEPK", "ESPN_GAMEID")

#: game -> (risk, what makes it a risk). Recorded on the row AND at board level; never used to
#: alter a probability, because a disclosed hazard is not the same thing as a corrected input.
IDENTITY_RISK = {
    "mlb:PIT@STL": (
        "SIDE_SWAP_CORRECTED",
        "the source reported 'Cardinals: Jared Jones / Pirates: Quinn Mathews'; a dedicated "
        "verification pass established Jones starts for PIT and Mathews for STL. The board carries "
        "the corrected sides. The uncorrected version would have mis-attributed both.",
    ),
    "mlb:CWS@MIN": (
        "SIDE_SWAP_SUSPECTED",
        "Kremer (CWS) / Castillo (MIN) is single-source and puts both pitchers on clubs differing "
        "from their pre-2026 teams. It comes from the same source whose PIT@STL line was verified "
        "side-swapped. Re-confirm BOTH sides at T-90.",
    ),
    "mlb:MIA@WSH": (
        "SIDE_SWAP_SUSPECTED",
        "Eury Perez — a Marlins-associated arm — is asserted as the WASHINGTON starter while MIAMI "
        "is TBD. Same shape as the confirmed PIT@STL swap. If the side is wrong, the home slot "
        "holds the away team's pitcher and the away slot is empty. Re-confirm at T-90.",
    ),
    "mlb:COL@ATL": (
        "RESOLVED_ON_MAJORITY",
        "an early snippet put Sugano on ATL and another reported ATL as TBD; two later independent "
        "snippets gave Sugano (COL) vs Holmes (ATL) with consistent stat lines. Majority carried, "
        "not confirmed.",
    ),
}

#: game -> note. A start time we could not settle is a chronology hazard, not a cosmetic one.
START_TIME_RISK = {
    "mlb:SEA@TOR": "START_TIME_PLUS_MINUS_8_MIN — 7:15 PM ET on three snippets vs 7:07 PM ET "
                   "(Rogers Centre's customary time) on two; 23:15:00Z carried on the majority. "
                   "Any T-90/T-45 timer keyed to this game must carry an 8-minute tolerance.",
}


def owner_class(raw_status):
    """Registered starter status -> the owner's starter vocabulary."""
    if raw_status == "RESOLVED":
        return "PROBABLE"
    if raw_status == "OFFICIAL_TBD_CAP":
        return "TBD_CAP"
    if raw_status.startswith("STALE_DATA_CAP"):
        # 2026-08-29: the slot HAS data and it is too old to speak of as current. Distinct from
        # NO_LOG — the failure is age, not absence, and conflating them would hide which is which.
        return f"STALE_DATA_CAP[{raw_status}]"
    if raw_status.startswith(("NO_PID_CAP", "NO_LOG_CAP")):
        return f"NAMED_NO_LOG_RETAINED_CAP[{raw_status}]"
    return raw_status


def split_id(canonical_id):
    """'MLB_GAMEPK:824231' -> ('MLB_GAMEPK', '824231'). Refuses anything else, loudly.

    A bare integer here would mean a pseudo-pk had crept back into the slate, which is the exact
    condition this board exists to make impossible. It is a build failure, not a warning.
    """
    if ":" not in str(canonical_id):
        raise ValueError(
            f"UNNAMESPACED_SLATE_KEY {canonical_id!r} — the 827000-series pseudo-pk contract is "
            "retired for this date; every row must carry a CAPTURED '<ID_SPACE>:<int>' id"
        )
    space, val = str(canonical_id).split(":", 1)
    if space not in ID_SPACES:
        raise ValueError(f"UNKNOWN_ID_SPACE {space!r} in {canonical_id!r}")
    if not re.fullmatch(r"\d+", val):
        raise ValueError(f"NON_NUMERIC_ID_VALUE {val!r} in {canonical_id!r}")
    return space, val


def freeze(out_path=f"cards/{SLATE_DATE}_mlb_board.json"):
    import math
    games, wide, target, ev = B.build()
    k = wide["k"]

    def logit(p): return math.log(p / (1 - p))
    def sig(z): return 1 / (1 + math.exp(-z))

    binding = json.load(open(SLATE_BINDING))
    prov = {r["game"]: r["id_provenance"] for r in binding["rows"]}

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    mlb_rows, id_spaces_seen = [], {}
    for g in games:
        # B.load_slate() reads column 0 into a key literally named "gamePk". On this date that
        # column holds a namespaced canonical_id, and ten of fifteen are NOT gamePks — so the
        # value is re-keyed here and the misleading name never reaches the board.
        space, val = split_id(g["gamePk"])
        id_spaces_seen[space] = id_spaces_seen.get(space, 0) + 1
        prospect = ("PROSPECTIVITY_NOT_ESTABLISHED" if g["start_utc"] <= now
                    else "SELF_ASSERTED_PREGAME")
        sp_class = {s: owner_class(g["sp_status"][s]) for s in ("away", "home")}
        risk, why = IDENTITY_RISK.get(g["game"], (None, None))
        base = {"game": g["game"], "sport": "mlb",
                "canonical_id": g["gamePk"], "id_space": space, "id_value": val,
                "id_grade": "CAPTURED", "id_provenance": prov[g["game"]],
                "pseudo_pk_used": False,
                "game_start_utc": g["start_utc"], "start_time_grade": TZ_NOTE,
                "start_time_risk": START_TIME_RISK.get(g["game"]),
                "away_starter": g["away_sp"], "home_starter": g["home_sp"],
                "sp_status": g["sp_status"], "starter_class": sp_class,
                "starter_identification_grade": "SEARCH_IDENTIFIED_UNCONFIRMED",
                "starter_slots_capped": g["starter_slots_capped"],
                "identity_risk": risk, "identity_risk_detail": why,
                "resolved_information_dose": g["information_dose"],
                "dose_note": ("registered formula, unmodified; identity_risk is disclosed "
                              "separately and never silently discounts a probability"),
                "park_factor": g["park_factor"], "forecast_status": "FORECAST_REGISTERED",
                "prospectivity": prospect,
                "action_status": "NO_RETAINED_MARKET_ARTIFACT",
                "lineups": "UNCONFIRMED_AT_REGISTRATION"}
        sim = g["sim"]
        mlb_rows += [
            dict(base, arm="mlb.winner.EXPANDING_HOME_PRIOR", target="winner",
                 p_home=B.PRIOR_P),
            dict(base, arm="mlb.winner.CHAMPION_V13", target="winner", p_home=sim["p_home"],
                 simulation_trials=B.TRIALS, simulation_seed=g["seed"],
                 simulation_version="v13_1", trial_standard="LEGACY_TRIAL_COUNT",
                 monte_carlo_sd_pp=100 * sim["mc_se"]),
            dict(base, arm="mlb.winner.CHALLENGER_ADAPTIVE", target="winner",
                 p_home=g["p_adaptive"], residual_f=g["residual_f"],
                 simulation_trials=0, simulation_version=B.AC.IDENTITY,
                 identity_note=B.AC.SUPERSEDES),
            dict(base, arm="mlb.winner.CHALLENGER_WIDENED", target="winner",
                 p_home=sig(logit(B.PRIOR_P) + k * g["residual_f"]),
                 simulation_version=f"widened({B.AC.IDENTITY})", widening_k=k),
            dict(base, arm="mlb.total.EXPANDING_TOTAL_PRIOR", target="total",
                 projected_total=B.PRIOR_TOTAL, target_authority="NEVER_DECISION_BEARING"),
            dict(base, arm="mlb.total.CHAMPION_V13", target="total",
                 projected_total=sim["proj_total"], target_authority="NEVER_DECISION_BEARING",
                 simulation_trials=B.TRIALS, simulation_seed=g["seed"]),
        ]

    ids = [r["canonical_id"] for r in mlb_rows if r["arm"] == "mlb.winner.CHAMPION_V13"]
    if len(set(ids)) != len(games):
        raise ValueError(f"DUPLICATE_CANONICAL_ID on the board: {len(set(ids))} unique of "
                         f"{len(games)} games")

    def cohort_hash(rows_):
        return hashlib.sha256(json.dumps(rows_, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()

    board = {
        "record_id": f"BOARD-{SLATE_DATE}-MLB",
        "slate_date": SLATE_DATE,
        "sport": "mlb",
        "forecast_anchor_utc": now,
        "generated_at_utc_self_asserted": now,
        "earliest_start_utc": EARLIEST_START_UTC,
        "chronology_status": ("ANCHOR_PRECEDES_EARLIEST_START"
                              if now < EARLIEST_START_UTC else "ANCHOR_AFTER_EARLIEST_START"),
        "prospectivity_status": "SELF_ASSERTED_LOCAL until the CI anchor on this push lands; "
                                "per-game field carries any exception",
        "builder": "harness/build_board_0828.py (COMMITTED)",
        "model_identity": {"winner": ["mlb.winner.EXPANDING_HOME_PRIOR",
                                      "mlb.winner.CHAMPION_V13 (frozen 2026-08-10, v13_1)",
                                      "mlb.winner.CHALLENGER_ADAPTIVE",
                                      "mlb.winner.CHALLENGER_WIDENED"],
                           "total": ["mlb.total.EXPANDING_TOTAL_PRIOR",
                                     "mlb.total.CHAMPION_V13"]},
        "slate_grade": "SEARCH_IDENTIFIED_UNCONFIRMED — see module docstring and "
                       f"data/audit/{SLATE_DATE}_schedule_acquisition.json",
        "GAME_IDENTITY": {
            "field": "canonical_id",
            "form": "<ID_SPACE>:<integer>, ID_SPACE in " + str(list(ID_SPACES)),
            "captured": len(games), "inferred": 0, "synthetic_pseudo_pks": 0,
            "id_space_counts": id_spaces_seen,
            "pseudo_pk_contract": "RETIRED for this date. Prior boards keyed rows on invented "
                                  "827000-series integers shaped like gamePks; those keys could "
                                  "not bind a result and are the enabling condition RJ-007 found.",
            "namespace_is_load_bearing": (
                "MLB_GAMEPK and ESPN_GAMEID are different id spaces that both look like integers. "
                "Stripping the prefix to obtain a bare int reproduces the 8/27 defect in a new "
                "form. Consumers must branch on id_space and never join across spaces."
            ),
            "inference_refused": (
                "The 8/28 ESPN ids run contiguously 401816702-401816716 with 8/29 siblings at "
                "exactly +15, so the ten missing gamePks could have been 'reconstructed' by "
                "adjacency. They were not. Precedent: the INFERRED 8/27 pk 825038 was archive-"
                "verified on 2026-08-28 to be a fabrication (real AZ@SF id 823179)."
            ),
            "binding_status": "IDENTIFIED, NOT BOUND — these ids give a future result-binding pass "
                              "a real key to archive-verify against; they do not themselves bind.",
        },
        "IDENTITY_RISK_REGISTER": {
            "why_separate": "a wrong SIDE is not a missing NAME. Folding it into a starter class "
                            "would understate it; folding it into the dose would silently move a "
                            "probability. It is disclosed here and left visible.",
            "rows": {gm: {"risk": r, "detail": d} for gm, (r, d) in sorted(IDENTITY_RISK.items())},
            "n_suspected_side_swaps": sum(1 for r, _ in IDENTITY_RISK.values()
                                          if r == "SIDE_SWAP_SUSPECTED"),
        },
        "board_scope": {"n_games": len(games), "mlb": len(games)},
        "SEPARATION": "MLB, WNBA and NFL are separate cohorts on separate boards, never pooled",
        "PRIORS": {"mlb_home": {"p": B.PRIOR_P, "n": 1684,
                                "unchanged_because": "no canonical result exists after "
                                                     "2026-08-21; later finals are relayed/"
                                                     "derived, not canonical"},
                   "mlb_total": {"runs": B.PRIOR_TOTAL, "n": 1684}},
        "WIDENING": {"formula": "logit(p_wide) = logit(prior) + k * residual_f",
                     "target_sd_pp": target, "solved_k": k, "solver": wide},
        "ADAPTIVE_IDENTITY": {"identity": B.AC.IDENTITY, "supersedes": B.AC.SUPERSEDES},
        "EVIDENCE": ev,
        "cohort_hashes": {"mlb": cohort_hash(mlb_rows)},
        "mlb": {"cohort_id": f"mlb:{SLATE_DATE}", "n_games": len(games), "rows": mlb_rows},
        "action_authority": "NONE — NO_RETAINED_MARKET_ARTIFACT for this slate at freeze; prices "
                            "attach only as a separately hashed overlay, are never predictive "
                            "features, and enter only the action/EV layer",
        "LEDGERS": {"model_authorized_wagers_usd": 0, "n_bets": 0, "units": 0.0},
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(board, fh, indent=1, sort_keys=True)
    return board


if __name__ == "__main__":
    board = freeze()
    print("FROZEN", board["record_id"], "| mlb", board["cohort_hashes"]["mlb"][:8],
          "| anchor", board["forecast_anchor_utc"], board["chronology_status"])
    print("ids:", board["GAME_IDENTITY"]["id_space_counts"],
          "| synthetic:", board["GAME_IDENTITY"]["synthetic_pseudo_pks"])
    for r in board["mlb"]["rows"]:
        if r["arm"] == "mlb.winner.CHAMPION_V13":
            flag = f"  <{r['identity_risk']}>" if r["identity_risk"] else ""
            print(f"  {r['game']:<14} {r['canonical_id']:<22} V13 {r['p_home']:.4f}"
                  f" dose {r['resolved_information_dose']}"
                  f" [{r['starter_class']['away']} / {r['starter_class']['home']}]{flag}")
