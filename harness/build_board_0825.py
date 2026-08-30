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

FRESHNESS CONTRACT WIRING (2026-08-29). starter() no longer drops last_start_date at the
RESOLVED-minting line; every slot flows through harness/board_freshness.resolve_starter_slot into
the frozen harness/freshness_contract.py gate, and the game-level information_dose is
board_freshness.game_dose() (the contract's multiplicative, 0.20-floored cohort dose), replacing
the old `1.0 - 0.25*capped` / `dose=0.5 on TBD` arithmetic. The v13 engine's sp dict is unchanged
(exactly {era, gs, k, bb}); freshness travels in the new 4th return value of starter().

R3 (frozen stays frozen): boards already frozen keep their published rows byte-for-byte. This
patch changes builder behaviour going forward only; nothing here rewrites a frozen board.

WNBA COHORT — CONTRACT-WIRED GOING FORWARD (R3: frozen boards unchanged). The WNBA cohort now
flows through the same freshness contract as MLB: staleness_days is COMPUTED from the pool's own
max game date (slate_date - feature_state_as_of), never a literal; every game row carries an
input_freshness disposition from board_freshness.resolve_slot(sport="wnba", kind="team_form")
against the contract's 3-day wnba/team_form limit, with the same ACQUIRE hook the MLB starter
path uses; each row carries a namespaced canonical_id (WNBA_OFFICIAL:<id> — the ids in the slate
tuples live in the same id space as the base pool's gids, the WNBA official schedule feed) and a
scheduled_date derived in America/New_York from the real tip instant; and the cohort passes
harness/board_shape.validate_board_shape before any bytes are written. Freshness is ADDITIVE
EVIDENCE only: the board's governance statuses (ACTION_BLOCKED / promotion_eligible) are
owner-registered and are not unblocked by this wiring.
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
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))

import adaptive_challenger as AC
import board_freshness as BF
import build_ml_asof as ASOF
import freshness_contract as FC
import keyed_seed as KS
import run_v13_historical as V13
import widening_rule as WR
from board_shape import validate_board_shape

ET = ZoneInfo("America/New_York")   # slate_date / scheduled_date semantics for all cohorts

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


def scheduled_date_et(start_utc):
    """ET (America/New_York) calendar date of a real UTC start instant.

    Same derivation as the NFL builder: the instant is captured, so converting it is arithmetic,
    not invention. Accepts 'Z' or an explicit offset; a naive value raises (instants must be
    offset-qualified).
    """
    instant = dt.datetime.fromisoformat(str(start_utc).replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError(f"start instant {start_utc!r} is naive — instants must be offset-qualified")
    return instant.astimezone(ET).date().isoformat()


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


#: Acquisition hook. Default None = degrade honestly (the contract's unconfigured behaviour).
#: Inject an adapter via set_acquisition(); build() passes it down as acquire=ACQUIRE.
ACQUIRE = None


def set_acquisition(adapter):
    """Register the acquisition adapter (harness/acquisition.py chain) for starter slots."""
    global ACQUIRE
    ACQUIRE = adapter


def starter(pid_map, name, acquire=None, now=None):
    """(sp_dict_for_v13, status, rs_or_None, disposition_dict).

    last_start_date is NO LONGER dropped: the full feats OrderedDict goes to
    board_freshness.resolve_starter_slot, which applies the freshness contract. The v13 engine's
    sp dict stays exactly {era, gs, k, bb}; freshness travels only in the 4th return value.
    CAP on TBD, missing, immature, stale, or non-pregame evidence — never a guess. The stale
    observation stays in the disposition for audit but does not feed V13. The registered league
    treatment is used until a current canonical observation binds.
    """
    if name == "TBD":
        _, status, disp = BF.resolve_starter_slot(name, None, "OFFICIAL_TBD_CAP", SLATE_DATE,
                                                  None, acquire=acquire, now=now)
        return V13._sp({}), status, None, disp
    pid = pid_map.get(name)
    if pid is None:
        _, status, disp = BF.resolve_starter_slot(name, None, f"NO_PID_CAP({name})", SLATE_DATE,
                                                  None, acquire=acquire, now=now)
        return V13._sp({}), status, None, disp
    source = f"pitcher_logs/{pid}.txt via sp_asof_strict"
    feats, flags = ASOF.sp_asof_strict(pid, SLATE_DATE, set())
    if feats is None:
        _, status, disp = BF.resolve_starter_slot(name, None, f"NO_LOG_CAP({flags['reason']})",
                                                  SLATE_DATE, source, acquire=acquire, now=now)
        return V13._sp({}), status, None, disp
    feats, status, disp = BF.resolve_starter_slot(name, feats, "RESOLVED", SLATE_DATE, source,
                                                  acquire=acquire, now=now)
    if feats is None:
        return V13._sp({}), status, None, disp
    sp = {"era": feats["era"], "gs": feats["gs"], "k": feats["k_pct"], "bb": feats["bb_pct"]}
    return sp, status, V13.rs(sp["era"], sp["gs"], sp["k"], sp["bb"]), disp


def starter_slot_capped(disposition):
    """Return whether the registered CAP, rather than current observed values, was used.

    ACQUIRING+CONFIRMED remains non-actionable until a new board freeze. The resolver therefore
    withholds the acquired raw values; counting that slot as uncapped would make the board's
    evidence summary contradict the inputs actually simulated.
    """
    return not bool(disposition.get("actionable", False))


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
        spa, sa_status, rs_a, disp_a = starter(pid_map, g["away_sp"], acquire=ACQUIRE)
        sph, sh_status, rs_h, disp_h = starter(pid_map, g["home_sp"], acquire=ACQUIRE)
        # A slot is uncapped only when the contract authorizes its CURRENT_OBSERVED_VALUE.
        # ACQUIRING is deliberately fallback-only until refreeze, even with a CONFIRMED grade.
        capped = int(starter_slot_capped(disp_a)) + int(starter_slot_capped(disp_h))
        dose = BF.game_dose([disp_a, disp_h])
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
                      "starter_dispositions": {"away": disp_a, "home": disp_h},
                      "starter_slots_capped": capped, "information_dose": dose,
                      "park_factor": pf, "seed": seed, "sim": sim, "residual_f": res_f,
                      "p_adaptive": AC.probability(PRIOR_P, res_f)})
    champs = [g["sim"]["p_home"] for g in games]
    mean = sum(champs) / len(champs)
    target_sd_pp = 100 * math.sqrt(sum((p - mean) ** 2 for p in champs) / len(champs))
    wide = WR.solve_k(PRIOR_P, adaptive_residuals, target_sd_pp)
    return games, wide, target_sd_pp, evidence


def freeze(out_path=f"cards/{SLATE_DATE}_board.json", now=None):
    """Assemble, hash and write the frozen board. Deterministic given the repo state.

    `now` is the freeze time as an aware datetime, used as the freshness gate's reference
    instant (defaults to the real wall clock, UTC). Tests inject it so dispositions are
    reproducible.
    """
    import wnba_model_v1 as W
    freeze_now = now or dt.datetime.now(dt.timezone.utc)
    if freeze_now.tzinfo is None:
        raise ValueError("freeze `now` must be timezone-aware")
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

    # --- WNBA freshness wiring -------------------------------------------------
    # feature_state_as_of is MEASURED from the pool's own game dates (post-Track-A these are
    # ET-corrected where applicable). R1: staleness_days is computed, never a literal. An empty
    # pool degrades honestly: as_of None -> stamp with no timestamp -> DEGRADED unknowable-age.
    # AS-OF FILTER (2026-08-29). This was max() over the WHOLE pool with no slate bound. Once the
    # extension artifact is rebuilt the pool runs past older slates, so a retrospective build
    # produced an observed_at AFTER the slate it forecasts — a NEGATIVE age, which resolve_input
    # reads as age <= limit and reports FRESH. A staleness gate returning FRESH on future data is
    # the mirror image of the defect this contract exists to close. sp_asof_strict already applies
    # exactly this bound on the MLB side (`if d >= slate_date: continue`); the WNBA pool now does
    # too. Leakage and staleness are the same as-of question asked from opposite directions.
    feature_state_as_of = max((g["date"] for g in wgames if g["date"] < SLATE_DATE), default=None)
    wnba_staleness = (None if feature_state_as_of is None else
                      (dt.date.fromisoformat(SLATE_DATE)
                       - dt.date.fromisoformat(feature_state_as_of)).days)
    wnba_source = "staged official-plus-one pool (+ extension artifact when present)"
    wnba_rows = []
    for (a, h, t, gid), pr in zip(wsl, preds):
        subject = f"wnba_feature_state:{a}@{h}"
        stamp = BF.stamp_from_observation(
            subject,
            observed_at=(feature_state_as_of + "T00:00:00Z"
                         if feature_state_as_of is not None else None),
            source=wnba_source, grade=FC.CONFIRMED)
        _slot_status, wnba_disp = BF.resolve_slot(
            subject, "wnba", "team_form", stamp, "POOL_FEATURE_STATE",
            acquire=ACQUIRE, now=freeze_now)
        block_reason = (f"feature state as of {feature_state_as_of}, {wnba_staleness} days "
                        f"stale against a 21-day ceiling; the staged pool does not contain "
                        f"this slate" if feature_state_as_of is not None else
                        "feature state as-of unknowable (empty pool); the staged pool does "
                        "not contain this slate")
        if wnba_disp["disposition"] == FC.DEGRADED:
            block_reason += f"; freshness: {wnba_disp['reason']}"
        wb = {"game": f"wnba:{a}@{h}", "sport": "wnba", "official_game_id": gid,
              "game_start_utc": t, "scheduled_date": scheduled_date_et(t),
              "personnel": "PERSONNEL_UNVERIFIED",
              "forecast_status": "FORECAST_REGISTERED",
              "feature_state_as_of": feature_state_as_of,
              "staleness_days": wnba_staleness,
              "input_freshness": wnba_disp,
              "freshness_note": (
                  "freshness is additive evidence, not a promotion path: the governance "
                  "statuses below are owner-registered. A DEGRADED disposition appends its "
                  "reason to block_reason; FRESH/ACQUIRING leaves the registered "
                  "action_status/promotion_eligible semantics untouched."),
              "action_status": "ACTION_BLOCKED",
              "evidence_class": "DIAGNOSTIC_ONLY", "promotion_eligible": False,
              "block_reason": block_reason}
        if gid:
            # The wsl ids (e.g. "1022600284") live in the same id space as the base pool's
            # gids — the WNBA official schedule feed — so the namespace is WNBA_OFFICIAL.
            wb["canonical_id"] = f"WNBA_OFFICIAL:{gid}"
            wb["id_space"] = "WNBA_OFFICIAL"
            wb["id_grade"] = "CAPTURED"
        else:
            # R1: absence is declared, never filled with an invented id.
            wb["id_status"] = ("NOT_CAPTURED: the slate tuple carried no official game id "
                               "for this game")
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
        "date_timezone": "America/New_York",
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
        "wnba": {"cohort_id": f"wnba:{SLATE_DATE}", "n_games": 3,
                 "date_timezone": "America/New_York",
                 "feature_state_as_of": feature_state_as_of, "rows": wnba_rows},
        "action_authority": "NONE — no market board is captured for this slate "
                            "(FORECAST_ONLY_NO_MARKET_GRADE) and the system is "
                            "SYSTEM_NOT_DECISION_READY. Prices, if captured pregame, attach only "
                            "as a separately hashed overlay.",
        "LEDGERS": {"model_authorized_wagers_usd": 0, "n_bets": 0},
    }
    # Fail loud and total, BEFORE any bytes hit disk: the WNBA cohort must conform to
    # BOARD_SHAPE_CONTRACT (rows at board['wnba']['rows'], namespaced canonical ids or an
    # explicit id_status, declared date_timezone, per-row date fields).
    validate_board_shape(board, "wnba")
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
