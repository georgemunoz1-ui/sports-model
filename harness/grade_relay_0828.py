"""Descriptively grade the 2026-08-28 MLB and WNBA cohorts against OWNER-RELAYED finals.

THE LAYER THIS WRITES TO. RESULT_DISPLAY and CANONICAL_EVIDENCE_ADMISSION are separate layers and
this module writes only the first. The finals here were relayed by the owner, not read from a
score-bearing archive; the archives still do not carry 8/28 (see the post-slate binding proofs).
So every number below is DESCRIPTIVE: nothing accrues to settlement, to promotion, or to the
estimator, and the model ledger stays 0 bets / $0. A relay can carry the right identity and the
wrong numbers, which is one keystroke from the original defect.

WHY IT STILL GOES THROUGH THE BINDING GATE. The owner's stated join was
slate_date + canonical_id + away + home. The registered contract is
sport + canonical_game_id + scheduled_date + RESULT_DATE + away + home. result_date is the field
whose absence caused the 8/27 P0, and it is not decorative here: fourteen of these nineteen games
start at or after 8:00 PM ET and therefore carry an August 29 UTC timestamp. Rather than assert the
join was fine, this module rebuilds the rows under the full contract and lets the gate rule.

WHAT IS RECOMPUTED AND WHAT IS TAKEN ON TRUST. Only the FINALS are taken from the relay. Every
record, Brier, logloss, MAE and bias is recomputed from the frozen boards, so the relayed summary
can be CHECKED rather than echoed.

THE LAD@DET COUNTERFACTUAL IS NOT A SCORE. The frozen board had the starters on the wrong clubs.
Correcting them moves the champion's slate Brier from 0.2304 to 0.2236 — in the champion's favour.
That corrected number is reported as a DIAGNOSTIC and must never be recorded as the arm's result:
the registered prospective forecast was the malformed one, and a model does not get to keep the
score it would have earned on input it did not have.
"""
from __future__ import annotations

MODULE_ID = "grade_relay_0828"

import datetime as dt
import hashlib
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))

from result_binding_gate import binding_proof, guarded_aggregate, AggregateRefused  # noqa: E402
from postslate_binding_0828 import gate_board  # noqa: E402

SLATE_DATE = "2026-08-28"
RELAY_SOURCE = ("owner relay, 2026-08-29 — official MLB / WNBA / NFL scoreboards cited by the "
                "owner. NOT an archive read; the score-bearing archives still do not carry 8/28.")

#: (away_score, home_score) keyed by board game key. The ONLY quantities taken from the relay.
MLB_FINALS = {
    "mlb:CIN@CHC": (10, 8), "mlb:LAD@DET": (2, 1), "mlb:MIA@WSH": (2, 9),
    "mlb:KC@CLE": (3, 0), "mlb:HOU@NYM": (3, 1), "mlb:SD@TB": (4, 9),
    "mlb:SEA@TOR": (1, 8), "mlb:COL@ATL": (4, 6), "mlb:BOS@NYY": (0, 1),
    "mlb:TEX@MIL": (1, 6), "mlb:CWS@MIN": (7, 4), "mlb:PIT@STL": (1, 4),
    "mlb:PHI@LAA": (5, 3), "mlb:BAL@ATH": (4, 3), "mlb:AZ@SF": (10, 6),
}
WNBA_FINALS = {
    "wnba:POR@ATL": (101, 83), "wnba:CON@IND": (91, 111),
    "wnba:TOR@LV": (73, 93), "wnba:WSH@LAS": (82, 88),
}
#: BAL@ATH went 10 innings. Flagged so the extra-innings row is visible rather than silently
#: averaged into the totals error, where a 10-inning game is not the same object as a 9-inning one.
EXTRA_INNINGS = {"mlb:BAL@ATH": 10}

MLB_WINNER_ARMS = ["mlb.winner.CHAMPION_V13", "mlb.winner.CHALLENGER_WIDENED",
                   "mlb.winner.CHALLENGER_ADAPTIVE", "mlb.winner.EXPANDING_HOME_PRIOR"]
MLB_TOTAL_ARMS = ["mlb.total.EXPANDING_TOTAL_PRIOR", "mlb.total.CHAMPION_V13"]
WNBA_ARMS = ["wnba.replacement.FEATURE_REFRESH", "wnba.winner.EXPANDING_HOME_PRIOR",
             "wnba.fallback.STANDINGS_LOG5_v1"]

#: archive-confirmed correction; see the 8/28 night review
LADDET_CORRECTED_P_HOME = 0.3736


def _brier(p, y):
    return (p - y) ** 2


def _logloss(p, y):
    p = min(max(p, 1e-12), 1 - 1e-12)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def result_rows(board, rows_key, finals):
    """Rebuild result rows under the FULL registered contract, not the relay's shorter join."""
    gb = gate_board(board, rows_key)
    out = []
    for g, (a, h) in finals.items():
        info = gb["games"][g]
        out.append({
            "sport": board.get("sport"),
            "game_pk": info["game_pk"],          # namespaced canonical id
            "scheduled_date": SLATE_DATE,
            # RESULT_DATE IS DELIBERATELY None, AND THAT IS THE HONEST VALUE.
            #
            # An earlier version of this module stamped SLATE_DATE here. That made the published
            # DATE_COHERENCE_PASS counter read 15/15 while attesting to nothing: the board's date
            # was read from the frozen artifact, but the RELAYED FINALS carry no date of their own,
            # so the constant was being compared against the board rather than against any
            # observation of when these games were actually played. Had the wrong night's finals
            # been relayed — the exact 2026-08-27 P0 — the counter would still have read 15/15.
            #
            # A relay of bare scores has no independently observable result date. The correct
            # output is therefore a counter that says so (0/15 verified) rather than one that
            # manufactures agreement. When an archive publishes these games, it carries a real
            # result_date and the counter becomes meaningful.
            "result_date": None,
            "away": info["away"], "home": info["home"],
            "away_score": a, "home_score": h,
        })
    return gb, out


def identity_match(gb, finals):
    """The WEAKER claim that actually holds for a relay: canonical id + away + home agree.

    This is NOT binding. Binding is sport + canonical_game_id + scheduled_date + result_date +
    away + home, and a relay of bare scores has no result_date, so it cannot bind — the gate's
    selftest B1 refuses a row that omits result_date precisely because omitting it was MORE
    permissive than stating it. Reporting identity agreement as though it were binding is that
    same evasion. So it is computed here, named for what it is, and reported beside the refusal
    rather than in place of it.
    """
    per = []
    for g, (a, h) in finals.items():
        info = gb["games"].get(g)
        per.append({
            "game": g,
            "canonical_id": (info or {}).get("game_pk"),
            "board_matchup": f'{(info or {}).get("away")}@{(info or {}).get("home")}',
            "present_on_board": info is not None,
            "away_score": a, "home_score": h,
        })
    n_ok = sum(1 for x in per if x["present_on_board"] and x["canonical_id"])
    return {"IDENTITY_MATCH": f"{n_ok}/{len(per)}",
            "what_this_is": ("canonical id present on the board and matchup agrees. It proves "
                             "WHICH game each score is attached to. It does NOT prove the score "
                             "is that game's score, and it does NOT establish the date."),
            "what_this_is_not": "binding under the registered contract",
            "per_game": sorted(per, key=lambda x: x["game"])}


def grade_winner(by, finals, arms):
    out = {}
    for arm in arms:
        games = by.get(arm, {})
        n = w = 0
        bs, ls, per = [], [], []
        for g, (a, h) in finals.items():
            r = games.get(g)
            if r is None or r.get("p_home") is None:
                continue
            if a == h:
                continue  # a tie scores no winner; excluded explicitly, not silently
            p, y = r["p_home"], (1 if h > a else 0)
            n += 1
            hit = (p >= 0.5) == (y == 1)
            w += hit
            bs.append(_brier(p, y))
            ls.append(_logloss(p, y))
            per.append({"game": g, "p_home": round(p, 6), "home_won": bool(y),
                        "correct": bool(hit), "brier": round(_brier(p, y), 6)})
        if not n:
            continue
        out[arm] = {"n": n, "record": f"{w}-{n - w}", "wins": w, "losses": n - w,
                    "brier": round(sum(bs) / n, 6), "logloss": round(sum(ls) / n, 6),
                    "per_game": sorted(per, key=lambda x: x["game"])}
    return out


def grade_total(by, finals, arms, field="projected_total"):
    out = {}
    for arm in arms:
        errs = []
        for g, (a, h) in finals.items():
            r = by.get(arm, {}).get(g)
            if r is None or r.get(field) is None:
                continue
            errs.append({"game": g, "proj": r[field], "actual": a + h,
                         "err": round(r[field] - (a + h), 4)})
        if not errs:
            continue
        e = [x["err"] for x in errs]
        n = len(e)
        out[arm] = {"n": n,
                    "mae": round(sum(abs(v) for v in e) / n, 4),
                    "rmse": round(math.sqrt(sum(v * v for v in e) / n), 4),
                    "bias": round(sum(e) / n, 4),
                    "per_game": sorted(errs, key=lambda x: x["game"])}
    return out


def build():
    mlb = json.load(open(f"cards/{SLATE_DATE}_mlb_board.json"))
    wnba = json.load(open(f"cards/{SLATE_DATE}_wnba_board_v2.json"))

    mby, wby = {}, {}
    for r in mlb["mlb"]["rows"]:
        mby.setdefault(r["arm"], {})[r["game"]] = r
    for r in wnba["wnba"]["rows"]:
        wby.setdefault(r["arm"], {})[r["game"]] = r

    proofs, idents = {}, {}
    for sport, board, key, finals in (("mlb", mlb, "mlb", MLB_FINALS),
                                      ("wnba", wnba, "wnba", WNBA_FINALS)):
        gb, rows = result_rows(board, key, finals)
        proofs[sport] = binding_proof(rows, gb, f"{sport}:{SLATE_DATE}")
        idents[sport] = identity_match(gb, finals)

    # THE GUARD, on the path that needed it. binding_proof was called above and then every
    # statistic below was computed with nothing consulting its verdict — the 2026-08-29 audit
    # found aggregate_guard had zero production callers anywhere in the repo. These cohorts DO
    # NOT BIND (a relay of bare scores has no result_date), so publishing a Brier over them
    # requires an explicit, recorded override naming the weaker warrant. It is no longer possible
    # to compute these numbers without that decision appearing in the artifact.
    OVERRIDE = ("IDENTITY_MATCH ONLY. Every relayed score attaches to a canonical id that is on "
                "the board with the same matchup, and that is the whole warrant. The cohort does "
                "not bind under the registered contract because the relay carries no result_date. "
                "These statistics are DESCRIPTIVE and accrue nothing to settlement, promotion or "
                "the estimator.")
    guards = {}
    for sport in ("mlb", "wnba"):
        try:
            guards[sport] = guarded_aggregate(proofs[sport], f"{sport} arm statistics",
                                              descriptive_override=OVERRIDE)
        except AggregateRefused as e:
            raise SystemExit(f"AGGREGATE_REFUSED and no override supplied: {e}")

    mlb_w = grade_winner(mby, MLB_FINALS, MLB_WINNER_ARMS)
    mlb_t = grade_total(mby, MLB_FINALS, MLB_TOTAL_ARMS)
    wnba_w = grade_winner(wby, WNBA_FINALS, WNBA_ARMS)
    wnba_t = grade_total(wby, WNBA_FINALS, ["wnba.replacement.FEATURE_REFRESH"])
    wnba_m = grade_total(wby, {g: (h, a) for g, (a, h) in WNBA_FINALS.items()},
                         ["wnba.replacement.FEATURE_REFRESH"], field="margin_home")
    # margin_home is home-minus-away, so the "actual" it compares against is built by handing
    # grade_total a swapped pair — actual = home - away rather than home + away.
    for arm, d in wnba_m.items():
        for x in d["per_game"]:
            x["actual"] = x["actual"] - 2 * min(WNBA_FINALS[x["game"]])  # not used; recomputed below
    wnba_m = {}
    fr = wby["wnba.replacement.FEATURE_REFRESH"]
    errs = []
    for g, (a, h) in WNBA_FINALS.items():
        r = fr.get(g)
        if r and r.get("margin_home") is not None:
            errs.append({"game": g, "proj_home_margin": r["margin_home"],
                         "actual_home_margin": h - a,
                         "err": round(r["margin_home"] - (h - a), 4)})
    e = [x["err"] for x in errs]
    wnba_m["wnba.replacement.FEATURE_REFRESH"] = {
        "n": len(e), "mae": round(sum(abs(v) for v in e) / len(e), 4),
        "rmse": round(math.sqrt(sum(v * v for v in e) / len(e)), 4),
        "bias": round(sum(e) / len(e), 4),
        "per_game": sorted(errs, key=lambda x: x["game"])}

    # ---- the LAD@DET counterfactual, reported as a diagnostic and never as a score ----
    champ = mby["mlb.winner.CHAMPION_V13"]
    frozen_p = champ["mlb:LAD@DET"]["p_home"]
    a, h = MLB_FINALS["mlb:LAD@DET"]
    y = 1 if h > a else 0
    bs = [_brier(LADDET_CORRECTED_P_HOME if g == "mlb:LAD@DET" else champ[g]["p_home"],
                 1 if hh > aa else 0)
          for g, (aa, hh) in MLB_FINALS.items()]
    counterfactual = {
        "STATUS": "DIAGNOSTIC — NOT A SCORE, NOT RECORDED AS THE ARM'S RESULT",
        "row": "mlb:LAD@DET",
        "frozen_p_home_DET": round(frozen_p, 6),
        "corrected_p_home_DET": LADDET_CORRECTED_P_HOME,
        "frozen_p_LAD": round(1 - frozen_p, 6),
        "corrected_p_LAD": round(1 - LADDET_CORRECTED_P_HOME, 6),
        "row_brier_frozen": round(_brier(frozen_p, y), 6),
        "row_brier_corrected": round(_brier(LADDET_CORRECTED_P_HOME, y), 6),
        "slate_brier_frozen": mlb_w["mlb.winner.CHAMPION_V13"]["brier"],
        "slate_brier_corrected": round(sum(bs) / len(bs), 6),
        "delta": round(sum(bs) / len(bs) - mlb_w["mlb.winner.CHAMPION_V13"]["brier"], 6),
        "reading": (
            "the correction moves the champion's slate Brier from 0.2304 to 0.2236 — IN THE "
            "CHAMPION'S FAVOUR, because the corrected probability is more confident on the side "
            "that actually won. Two things follow and they point opposite ways. The recorded "
            "0.2304 is CONSERVATIVE: the arm was penalised for an input defect, not for its own "
            "judgment. And 0.2236 is NOT claimable: the prospective registered forecast was the "
            "malformed one, and an arm does not get to keep the score it would have earned on "
            "input it never had. The recorded number stays 0.2304."
        ),
        "owner_position_confirmed": (
            "the owner's reading is right — the side stays LAD either way, so the winning result "
            "does not validate the malformed input. Recomputation adds that the defect cost the "
            "champion 0.0068 of Brier rather than flattering it."
        ),
    }

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = {
        "schema": "ops.relay_grading.v1",
        "record_id": f"RELAY-GRADING-{SLATE_DATE}",
        "created_utc": now,
        "EVIDENCE_LAYER": {
            "layer": "RESULT_DISPLAY",
            "is_canonical_evidence_admission": False,
            "relay_source": RELAY_SOURCE,
            "accrual": ("NOTHING. Descriptive grading on relayed finals accrues nothing toward "
                        "settlement, promotion, or the estimator. The archives still do not carry "
                        "8/28; when they do, these numbers must be re-derived from them and any "
                        "disagreement recorded rather than reconciled away."),
            "what_was_taken_from_the_relay": "the FINALS only",
            "what_was_recomputed": ("every record, Brier, logloss, MAE, RMSE and bias — from the "
                                    "frozen boards, so the relayed summary is checked, not echoed"),
        },
        "BINDING": {
            "VERDICT": "NOT BOUND — and it never was. See CORRECTION below.",
            "owner_stated_join": "slate_date + canonical_id + away + home",
            "registered_contract": ("sport + canonical_game_id + scheduled_date + result_date + "
                                    "away + home"),
            "why_it_cannot_bind": (
                "a relay of bare scores carries NO result_date. The gate refuses a row that omits "
                "it — selftest B1 pins that behaviour, because omitting result_date was MORE "
                "permissive than stating it honestly, and the published wrong KC@TOR final on "
                "2026-08-27 bound cleanly precisely by omission. So these rows are correctly "
                "REFUSED under the full contract."),
            "counters_full_contract": {s: p["counters"] for s, p in proofs.items()},
            "gradable_full_contract": {s: p["gradable"] for s, p in proofs.items()},
            "identity_only": idents,
            "CORRECTION": {
                "what_was_published": (
                    "the 2026-08-28 full card and the first version of this record published "
                    "RESULT_BINDING_PASS = 15/15 (mlb) and 4/4 (wnba), DATE_COHERENCE_PASS "
                    "identical, and gradable = true for both cohorts."),
                "why_that_was_wrong": (
                    "this module stamped result_date from its own SLATE_DATE constant. That is "
                    "the missing field being MANUFACTURED so the row would bind — the same "
                    "evasion selftest B1 exists to refuse, performed one level up where B1 could "
                    "not see it. The counter compared a constant against the board's own date and "
                    "was structurally incapable of failing. Had the wrong night's finals been "
                    "relayed — the exact 2026-08-27 P0 — it would still have read 15/15."),
                "what_is_true_instead": (
                    "IDENTITY matches for every game: each relayed score attaches to a canonical "
                    "id that is on the board with the same matchup. That is a real and useful "
                    "claim. It is strictly weaker than binding: it does not establish that the "
                    "score is that game's score, and it establishes nothing about the date."),
                "effect_on_the_grades": (
                    "NONE of the recomputed metrics change. They were always computed by joining "
                    "the frozen board to the relayed finals on the game key, which is the identity "
                    "match. What changes is the WARRANT published beside them: from 'bound, "
                    "gradable' to 'identity-matched, date unestablished, descriptive only'."),
                "how_it_was_found": (
                    "an adversarial audit of this repo's retrieval surface, not by re-reading the "
                    "output. The record and the card both looked correct."),
            },
            "BOARD_SCHEMA_FINDING": {
                "what": ("the MLB board stores away and home ONLY inside the composite game key "
                         "(\"mlb:CIN@CHC\"). The WNBA board stores them as explicit fields. Two "
                         "of the six binding-contract fields are therefore not independently held "
                         "on an MLB board."),
                "how_it_surfaced": ("the first pass refused all 15 MLB rows with "
                                    "MISSING_IDENTITY_FIELD while all 4 WNBA rows bound cleanly. "
                                    "The asymmetry is the board schema, not the relay."),
                "severity": ("BOUNDED. An archive row brings its own away/home, so TEAMS_REVERSED "
                             "can still fire there. The narrow exposure is that a game key BUILT "
                             "backwards at freeze time would have nothing on the board to "
                             "contradict it — the same shape as the LAD@DET starter reversal: one "
                             "source, nothing to disagree with it."),
                "disposition": ("derivation disclosed per board via TEAMS_DERIVED_FROM_GAME_KEY "
                                "rather than performed silently. Carrying away/home as MLB fields "
                                "is the real fix and is NOT applied here — the board is frozen "
                                "under R3."),
            },
        },
        "AGGREGATE_GUARD": {
            "status": ("EVERY statistic in this record was published over a cohort that DID NOT "
                       "BIND, under an explicit descriptive override."),
            "per_sport": guards,
            "why_this_block_exists": (
                "until 2026-08-29 aggregate_guard — the function whose own docstring calls it 'the "
                "check that would have stopped the 8/27 damage' — had ZERO production callers. "
                "binding_proof returned its rule as a STRING and every consumer, this module "
                "included, computed and published statistics without consulting it. The refusal "
                "recorded in BINDING above blocked nothing. It does now: guarded_aggregate raises "
                "unless a caller states, in code, why it is publishing anyway."),
        },
        "MLB": {"winner_arms": mlb_w, "total_arms": mlb_t,
                "extra_innings": EXTRA_INNINGS,
                "note": ("BAL@ATH went 10 innings. It is flagged rather than silently averaged "
                         "into the totals error — a 10-inning game is not the same object as a "
                         "9-inning one, and the totals arms were fit on 9.")},
        "LADDET_COUNTERFACTUAL": counterfactual,
        "WNBA": {"winner_arms": wnba_w, "total": wnba_t, "margin": wnba_m},
        "CFB": {
            "status": "PREGAME_UNGRADED",
            "n_games": 8,
            "owner_correction_accepted": (
                "the earlier seven FCS scores came from the 8/28 acquisition/refusal record, not "
                "from the published Saturday 8/29 CFB board, and are withdrawn from every metric. "
                "The 8/29 board is an 8-game partial and remains pregame."
            ),
        },
        "NFL": {"status": "BENCHMARK_ONLY", "n_games": 10,
                "note": ("no model record, Brier, EV or P&L. The registered NFL shadow is "
                         "regular-season only; SEA 9-9 KC is a tie and would score no winner even "
                         "if an arm had been eligible.")},
        "OWNER_TICKET": {
            "ticket": "217916739", "layer": "OWNER_DISCRETION",
            "legs": [
                {"leg": "KC +110", "final": "KC 3-0 CLE", "settlement": "WON",
                 "model_position": "the model's side was CLE at 50.3% — this leg won AGAINST the "
                                   "model"},
                {"leg": "NYM -110", "final": "HOU 3-1 NYM", "settlement": "LOST",
                 "model_position": "the model's side was NYM at 52.1% — this leg followed the "
                                   "model and lost"},
                {"leg": "POR +13 -110", "final": "POR 101-83 ATL", "settlement": "WON OUTRIGHT",
                 "model_position": "the model's side was ATL at 78.4% with ATL -9.7 — this leg "
                                   "won against the model's most confident WNBA call of the night",
                 "push_branch": "never engaged; POR won outright by 18, so +13 and +12.5 settle "
                                "identically here and the push protection cost nothing and "
                                "bought nothing"},
            ],
            "result": "2 of 3 legs won; the parlay LOST",
            "cash_pnl_usd": -50.0,
            "model_ledger": {"n_bets": 0, "units": 0.0, "exposure_usd": 0,
                             "wager_authority": "NO"},
            "separation": ("7/25 precedent — owner-discretion picks and model EV rules never mix. "
                           "This -$50 does not settle against the model ledger, which stays $0 at "
                           "0 bets. Two of the three legs won against the model's own side, which "
                           "is n=2 and evidence of nothing."),
        },
        "LEDGER": {"n_bets": 0, "units": 0.0, "exposure_usd": 0, "wager_authority": "NO"},
    }
    out = f"data/audit/{SLATE_DATE}_relay_grading.json"
    blob = json.dumps(rec, indent=1, sort_keys=True)
    rec["record_sha256"] = hashlib.sha256(blob.encode()).hexdigest()
    with open(out, "w") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
    return rec, out


if __name__ == "__main__":
    rec, out = build()
    print("WROTE", out, "|", rec["record_sha256"][:12])
    print("  VERDICT:", rec["BINDING"]["VERDICT"])
    for sp, c in rec["BINDING"]["counters_full_contract"].items():
        refused = c["REFUSED_ROWS"]
        nref = len(refused) if isinstance(refused, list) else refused
        print(f"  {sp:<5} full-contract RESULT_BINDING_PASS={c['RESULT_BINDING_PASS']} "
              f"refused={nref}  gradable={rec['BINDING']['gradable_full_contract'][sp]}")
        print(f"        identity-only {rec['BINDING']['identity_only'][sp]['IDENTITY_MATCH']}")
    print("\nMLB winner arms:")
    for a, d in sorted(rec["MLB"]["winner_arms"].items(), key=lambda kv: kv[1]["brier"]):
        print(f"  {a:<38} {d['record']:<6} Brier {d['brier']:.4f}  LogLoss {d['logloss']:.4f}")
    print("MLB totals:")
    for a, d in rec["MLB"]["total_arms"].items():
        print(f"  {a:<38} MAE {d['mae']:.2f}  RMSE {d['rmse']:.2f}  bias {d['bias']:+.2f}")
    print("\nWNBA winner arms:")
    for a, d in sorted(rec["WNBA"]["winner_arms"].items(), key=lambda kv: kv[1]["brier"]):
        print(f"  {a:<38} {d['record']:<6} Brier {d['brier']:.4f}")
    m = rec["WNBA"]["margin"]["wnba.replacement.FEATURE_REFRESH"]
    print(f"  margin MAE {m['mae']:.2f} bias {m['bias']:+.2f}")
    cf = rec["LADDET_COUNTERFACTUAL"]
    print(f"\nLAD@DET diagnostic: slate Brier {cf['slate_brier_frozen']:.4f} -> "
          f"{cf['slate_brier_corrected']:.4f} ({cf['delta']:+.4f}) — NOT claimable")
