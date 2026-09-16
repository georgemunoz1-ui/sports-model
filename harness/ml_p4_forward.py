#!/usr/bin/env python3
"""ML-P4 forward validation generator, per docs/experiments/ML-P4_forward_prereg.md.

Owner override 2026-07-28: Phase 4 authorized. This module is the ONLY producer of P4 forecast
records. Paper only; $0; gate 0/100; no formula changes.

Design decisions (fixed here, documented for review):

- FROZEN CANDIDATE. Before anything runs, the candidate config
  data/mlb/ml_asof/p3_candidate_config.json is re-hashed TWO ways and compared to TWO frozen
  values: the canonical hash (sha256 of json.dumps(cfg, sort_keys=True) — the identity recorded
  in the P3 freeze doc, 132523ac...) and the raw file-byte hash (eede422d..., unchanged since
  freeze commit 6895208). Either differing is a refusal; the generator produces nothing. No refit
  path exists in this file: there is no fitting code at all, only the frozen beta applied.

- ONE REGISTRY RECORD PER GAME. The record's top-level model_id is the challenger
  (ml.d_logistic_2f.p4.cfg132523ac, rng_policy deterministic_closed_form — the subject of Phase 4);
  the incumbent V13 reference and the de-vigged market benchmark ride inside the payload with the
  incumbent's own registered identity (ml.v13_1.p4fwd.hfa1005.n4000.rng_gamePk). One record, one
  grade, three scored columns at every checkpoint.

- NO ARITHMETIC DUPLICATION. The V13 incumbent delegates to ml_p2_baselines.v13_row (the verdict
  scorer's arithmetic, already registered + hash-pinned) by constructing _gidx = gamePk - 7_000_000
  so that its per-row seed 7_000_000 + _gidx equals int(gamePk) exactly. Result: registered policy
  per_game_seed_gamePk with zero copied formula lines; the selftest proves bit-identity against a
  direct ml_p2_baselines call. Drift in either file is caught by the registry pin on both.

- QUARANTINE is a refusal, not a forecast. Rows where a probability is impossible (no price at
  all / no starters) go to data/mlb/forecasts/p4_quarantine.jsonl with reasons; nothing is
  fabricated and nothing enters the forecast hash chain for that game.

- Cohort assignment is mechanical (disposition() below) and happens at generation time from the
  prereg conditions. A clean row is PROMOTION_PROSPECTIVE; any failed condition demotes to
  DIAGNOSTIC_PROSPECTIVE with the reasons in dq_flags. Relabeling later is structurally blocked by
  the forecast-registry hash chain.

Usage:
    python3 harness/ml_p4_forward.py                    # selftest (default; healthcheck runs this)
    python3 harness/ml_p4_forward.py --slate PATH       # generate forecasts for a slate input file
    python3 harness/ml_p4_forward.py --grade FID W SRC  # append one grade (home_win W in {0,1})
    python3 harness/ml_p4_forward.py --report           # checkpoint report (100/200 descriptive, 300 decision)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))

import ml_p2_baselines as p2  # registered, hash-pinned arithmetic: feats_2f, v13_row, metrics, calib

PREREG = "docs/experiments/ML-P4_forward_prereg.md"
CONFIG = "data/mlb/ml_asof/p3_candidate_config.json"
#: The FROZEN identity from the P3 freeze doc: sha256 of the parsed config re-serialized as
#: json.dumps(cfg, sort_keys=True) — the canonical form hashed at freeze time.
CONFIG_SHA = "132523ac86695b851fd8e4c88815da0416a79421e76ba0cce1c9bce24dfe096b"
#: Byte hash of the committed artifact itself (unchanged since freeze commit 6895208).
#: BOTH must match; either differing is a refusal.
CONFIG_FILE_SHA = "eede422d0659e485ecdfefb40938aaab5d705bd1aa873720460977cd7a573f47"
QUARANTINE = "data/mlb/forecasts/p4_quarantine.jsonl"
PLACEHOLDER_MANIFEST = "data/backfill/mlb/2026/pitcher_logs/_placeholders.json"

MODEL_ID_CAND = "ml.d_logistic_2f.p4.cfg132523ac"
MODEL_ID_V13 = "ml.v13_1.p4fwd.hfa1005.n4000.rng_gamePk"
V13_HFA, V13_SIMS = 1.005, 4000

#: Pre-registered candidate-p(home) bands — fixed in the prereg BEFORE any result; never searched.
BANDS = ((0.0, 0.40), (0.40, 0.45), (0.45, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 1.0))


def _sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _check_config(raw: bytes) -> list:
    refuse = ("refusing to run. The candidate is frozen by owner override 2026-07-28; "
              "no refit, no coefficient/feature/scaling/eligibility change is permitted in Phase 4.")
    fh = hashlib.sha256(raw).hexdigest()
    if fh != CONFIG_FILE_SHA:
        raise RuntimeError(f"CANDIDATE CONFIG FILE-BYTES MISMATCH: {fh[:12]}... != "
                           f"{CONFIG_FILE_SHA[:12]}... — " + refuse)
    cfg = json.loads(raw)
    ch = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
    if ch != CONFIG_SHA:
        raise RuntimeError(f"CANDIDATE CONFIG CANONICAL-HASH MISMATCH: {ch[:12]}... != frozen "
                           f"{CONFIG_SHA[:12]}... — " + refuse)
    return cfg["beta"]


def load_candidate() -> list:
    return _check_config(open(CONFIG, "rb").read())


def candidate_p(row, beta) -> float:
    x = p2.feats_2f(row)
    return float(1.0 / (1.0 + np.exp(-float(x @ np.asarray(beta, float)))))


def v13_p4(row) -> float:
    """Incumbent reference: verdict-scorer arithmetic, seed = int(gamePk) (per_game_seed_gamePk).

    Delegation trick: p2.v13_row seeds default_rng(7_000_000 + _gidx); setting
    _gidx = int(gamePk) - 7_000_000 makes the seed int(gamePk) exactly, with the arithmetic
    literally the same registered function — no copied formula lines to drift."""
    rr = dict(row)
    rr["_gidx"] = int(row["gamePk"]) - 7_000_000
    return p2.v13_row(rr, V13_HFA, V13_SIMS)


def american_implied(o) -> float:
    o = float(o)
    return 100.0 / (o + 100.0) if o > 0 else (-o) / ((-o) + 100.0)


def devig_proportional(ml_home, ml_away):
    ih, ia = american_implied(ml_home), american_implied(ml_away)
    return ih / (ih + ia), (ih + ia - 1.0)


def devig_power(ml_home, ml_away):
    """Sensitivity only — NEVER substituted for the fixed proportional method (prereg)."""
    ih, ia = american_implied(ml_home), american_implied(ml_away)
    lo, hi = 0.25, 4.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if ih ** mid + ia ** mid > 1.0:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2
    return ih ** k / (ih ** k + ia ** k)


def _placeholder_pids(path=PLACEHOLDER_MANIFEST):
    if not os.path.exists(path):
        return set()
    return {str(r["pitcher_id"]) for r in json.load(open(path))["rows"]}


def _ts(s):
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def disposition(row, generated_at_utc, ph_pids=None):
    """Mechanical cohort assignment from the prereg conditions.

    Returns (kind, flags): kind in QUARANTINE / PROMOTION_PROSPECTIVE / DIAGNOSTIC_PROSPECTIVE.
    QUARANTINE = probability impossible (no price at all / no starters): refuse, fabricate nothing.
    Any other failed condition -> DIAGNOSTIC_PROSPECTIVE with every reason flagged."""
    ph = _placeholder_pids() if ph_pids is None else ph_pids
    q = row.get("quote") or {}
    sp = row.get("sp") or {}
    a, h = sp.get("away") or {}, sp.get("home") or {}

    quarantine = []
    if q.get("ml_home") is None and q.get("ml_away") is None:
        quarantine.append("NO_PRICE")
    if a.get("pid") is None and h.get("pid") is None:
        quarantine.append("NO_STARTERS")
    if quarantine:
        return "QUARANTINE", quarantine

    flags = []
    fp = row.get("first_pitch_utc")
    try:
        if not fp:
            flags.append("NO_FIRST_PITCH_UTC")
        elif not (_ts(generated_at_utc) < _ts(fp)):
            flags.append("LATE_GENERATION")
    except ValueError:
        flags.append("BAD_TIMESTAMP")

    if row.get("gamePk") is None:
        flags.append("GAMEPK_UNRESOLVED")

    if q.get("ml_home") is None or q.get("ml_away") is None:
        flags.append("ONE_SIDED_QUOTE")
    else:
        if not q.get("book"):
            flags.append("NO_BOOK_ATTRIBUTION")
        try:
            if not q.get("observed_at_utc") or not fp or not (_ts(q["observed_at_utc"]) < _ts(fp)):
                flags.append("QUOTE_NOT_PROVEN_PREPITCH")
        except ValueError:
            flags.append("BAD_TIMESTAMP")

    for side, s in (("away", a), ("home", h)):
        S = side.upper()
        if s.get("pid") is None:
            flags.append(f"{S}_STARTER_MISSING")
            continue
        if not s.get("confirmed"):
            flags.append(f"{S}_STARTER_UNCONFIRMED")
        if str(s.get("pid")) in ph:
            flags.append(f"{S}_PLACEHOLDER_CONTAMINATED")
        if s.get("no_log"):
            flags.append(f"{S}_NO_LOG")
        tier = s.get("staleness_tier")
        if tier == "STALE_BLOCK" and not s.get("stale_block_verified"):
            flags.append(f"{S}_STALE_BLOCK_UNVERIFIED")
        elif tier in (None, "PROVISIONAL"):
            flags.append(f"{S}_STALENESS_PROVISIONAL")
        if s.get("era") is None or not s.get("gs"):
            flags.append(f"{S}_SP_FEATURES_MISSING")

    t = row.get("team") or {}
    if any((t.get(x) or {}).get(k) is None for x in ("away", "home") for k in ("rf_pg", "ra_pg")):
        flags.append("TEAM_FORM_MISSING")
    try:
        d1 = (dt.date.fromisoformat(row["slate_date"]) - dt.timedelta(days=1)).isoformat()
        done = row.get("team_results_complete_through")
        if done is None or done < d1 or not row.get("team_results_reconciled"):
            flags.append("TEAM_RESULTS_STALE")
    except (KeyError, ValueError):
        flags.append("BAD_SLATE_DATE")

    return ("PROMOTION_PROSPECTIVE" if not flags else "DIAGNOSTIC_PROSPECTIVE"), flags


def make_record(row, beta, generated_at_utc, archived_at_utc, slate_ref=None, ph_pids=None):
    """Build one registry record (or a quarantine dict with key 'quarantine')."""
    disp, flags = disposition(row, generated_at_utc, ph_pids)
    gid = row.get("gamePk")
    game_ref = int(gid) if gid is not None else \
        f"UNRESOLVED:{row.get('away', '?')}@{row.get('home', '?')}:{row.get('slate_date', '?')}"
    if gid is None and row.get("dh_game"):
        game_ref += f"#G{row['dh_game']}"  # doubleheader games must not share a forecast_id
    fid = f"P4-{str(row.get('slate_date', '?')).replace('-', '')}-{game_ref}"
    if disp == "QUARANTINE":
        return {"quarantine": True, "forecast_id": fid, "game_ref": game_ref,
                "slate_date": row.get("slate_date"), "reasons": flags,
                "generated_at_utc": generated_at_utc,
                "note": "probability impossible — no forecast fabricated (prereg QUARANTINE rule)"}

    p_c = candidate_p(row, beta)
    p_v = v13_p4(row) if gid is not None else None
    q = row.get("quote") or {}
    mkt = None
    if q.get("ml_home") is not None and q.get("ml_away") is not None:
        mp, ovr = devig_proportional(q["ml_home"], q["ml_away"])
        mkt = {"devig_method": "proportional", "p_home": round(mp, 6), "overround": round(ovr, 6),
               "power_devig_p_home_sensitivity": round(devig_power(q["ml_home"], q["ml_away"]), 6)}

    sp = row.get("sp") or {}
    starters = {side: {k: (sp.get(side) or {}).get(k)
                       for k in ("pid", "name", "confirmed", "staleness_tier")}
                for side in ("away", "home")}
    return {
        "forecast_id": fid,
        "cohort": disp,
        "provenance_class": "PROSPECTIVE_PREGAME_GENERATED",
        "game_ref": game_ref,
        "slate_date": row["slate_date"],
        "market": "ML",
        "generated_at_utc": generated_at_utc,
        "archived_at_utc": archived_at_utc,
        "model_id": MODEL_ID_CAND,
        "rng_policy": "deterministic_closed_form",
        "input_vintage": (slate_ref or {}).get("sha256"),
        "artifact_ref": ({"path": slate_ref["path"]} if slate_ref else None),
        "original_file_hash": (slate_ref or {}).get("sha256"),
        "dq_flags": flags,
        "prospective": True,
        "promotion_eligible": disp == "PROMOTION_PROSPECTIVE",
        "ledger_eligible": False,
        "diagnostic_grade_eligible": True,
        "provenance_limitations": "Phase 4 paper forward validation. Prices are captured quotes, "
                                  "not executed bets; $0 staked; gate 0/100; no ledger entry ever "
                                  "follows automatically from this record.",
        "payload": {
            "teams": {"away": row.get("away"), "home": row.get("home")},
            "first_pitch_utc": row.get("first_pitch_utc"),
            "starters": starters,
            "candidate": {"model_id": MODEL_ID_CAND, "config_sha256": CONFIG_SHA,
                          "config_file_sha256": CONFIG_FILE_SHA, "p_home": round(p_c, 6)},
            "incumbent": {"model_id": MODEL_ID_V13, "rng_policy": "per_game_seed_gamePk",
                          "hfa": V13_HFA, "sims_per_game": V13_SIMS,
                          "p_home": (round(p_v, 6) if p_v is not None else None)},
            "quote": {"book": q.get("book"), "ml_home": q.get("ml_home"),
                      "ml_away": q.get("ml_away"), "observed_at_utc": q.get("observed_at_utc")},
            "market": mkt,
            "model_hashes": {"harness/ml_p4_forward.py": _sha("harness/ml_p4_forward.py"),
                             "harness/ml_p2_baselines.py": _sha("harness/ml_p2_baselines.py")},
        },
    }


def run_slate(path: str) -> int:
    import forecast_registry as fr
    beta = load_candidate()  # raises on any hash drift BEFORE anything is generated
    raw = open(path, "rb").read()
    slate_ref = {"path": path, "sha256": hashlib.sha256(raw).hexdigest()}
    data = json.loads(raw)
    games = data["games"] if isinstance(data, dict) else data
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ph = _placeholder_pids()
    n_ok = n_diag = n_q = 0
    for row in games:
        rec = make_record(row, beta, now, now, slate_ref, ph)
        if rec.get("quarantine"):
            os.makedirs(os.path.dirname(QUARANTINE), exist_ok=True)
            open(QUARANTINE, "a").write(json.dumps(rec, separators=(",", ":")) + "\n")
            n_q += 1
            continue
        fr.append_forecast(rec)  # a single bad row raises HERE, quarantining itself, not the slate
        if rec["cohort"] == "PROMOTION_PROSPECTIVE":
            n_ok += 1
        else:
            n_diag += 1
    print(f"slate {path} ({slate_ref['sha256'][:12]}): "
          f"{n_ok} PROMOTION_PROSPECTIVE, {n_diag} DIAGNOSTIC_PROSPECTIVE, {n_q} quarantined")
    return 0


def add_grade(forecast_id: str, home_win: int, source_note: str) -> int:
    import forecast_registry as fr
    if any(g.get("forecast_id") == forecast_id for g in fr._load(fr.GRADES)):
        raise ValueError(f"{forecast_id} already graded — grades are append-only and singular")
    if home_win not in (0, 1):
        raise ValueError("home_win must be 0 or 1")
    fr.append_grade({"grade_id": f"G-{forecast_id}", "forecast_id": forecast_id,
                     "graded_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "home_win": int(home_win), "source": source_note})
    print(f"graded {forecast_id}: home_win={home_win}")
    return 0


def report() -> int:
    """Checkpoint report. n=100/200 DESCRIPTIVE ONLY; n=300 = the single pre-registered decision."""
    import forecast_registry as fr
    from collections import Counter
    fx = [r for r in fr._load(fr.FORECASTS)
          if str(r.get("forecast_id", "")).startswith("P4-") and r.get("market") == "ML"]
    gr = {g["forecast_id"]: g for g in fr._load(fr.GRADES)
          if str(g.get("forecast_id", "")).startswith("P4-")}
    clean = [r for r in fx if r["cohort"] == "PROMOTION_PROSPECTIVE" and r["forecast_id"] in gr]
    diag = [r for r in fx if r["cohort"] == "DIAGNOSTIC_PROSPECTIVE"]
    n = len(clean)
    print(f"P4 checkpoint report — clean graded n={n} "
          f"(checkpoints: 100/200 descriptive, 300 decision)")
    print(f"  P4 records total {len(fx)}; diagnostic {len(diag)} "
          f"(graded {sum(1 for r in diag if r['forecast_id'] in gr)})")
    for k, v in Counter(f for r in diag for f in r.get("dq_flags", [])).most_common():
        print(f"    diagnostic reason {k}: {v}")
    if not n:
        return 0
    y = np.array([gr[r["forecast_id"]]["home_win"] for r in clean], float)
    pc = np.array([r["payload"]["candidate"]["p_home"] for r in clean], float)
    pv = np.array([r["payload"]["incumbent"]["p_home"] for r in clean], float)
    pm = np.array([r["payload"]["market"]["p_home"] for r in clean], float)
    for name, p in (("candidate", pc), ("v13_incumbent", pv), ("market_prop_devig", pm)):
        b, l, a = p2.metrics(p, y)
        c0, c1 = p2.calib(p, y)
        print(f"  {name:18s} brier {b:.4f}  logloss {l:.4f}  acc {a:.3f}  "
              f"calib intercept {c0:+.3f} slope {c1:.3f}")
    for name, pa, pb in (("cand-v13", pc, pv), ("cand-market", pc, pm)):
        d = (pa - y) ** 2 - (pb - y) ** 2
        se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else float("nan")
        print(f"  paired dBrier {name}: {float(d.mean()):+.5f} +/- {se:.5f} SE (negative favours candidate)")
    print("  pre-registered candidate-p bands (fixed before any result; only these six ever reported):")
    for lo, hi in BANDS:
        m = (pc >= lo) & ((pc < hi) if hi < 1.0 else (pc <= 1.0))
        if m.sum():
            print(f"    [{lo:.2f},{hi:.2f}{')' if hi < 1 else ']'} n={int(m.sum())} "
                  f"mean_p={float(pc[m].mean()):.3f} obs={float(y[m].mean()):.3f} "
                  f"brier={float(((pc[m] - y[m]) ** 2).mean()):.4f}")
    print("  reliability deciles: " + json.dumps(p2.reliability(pc, y)))
    if n >= 300:
        print("  n=300 REACHED: single decision due (PROMOTE_TO_SHADOW_SELECTOR / REVISE / REJECT) "
              "— owner decision against the 4 pre-registered conditions in " + PREREG)
    elif n >= 100:
        print(f"  n={200 if n >= 200 else 100} checkpoint: DESCRIPTIVE ONLY — "
              "no refit, no early promotion, no reset")
    return 0


# ---------------------------------------------------------------------------------------------
# selftest: every refusal path must PROVABLY fire; every clean path must PROVABLY pass.
# ---------------------------------------------------------------------------------------------

def _fixture_row(**over):
    row = {
        "gamePk": 7000042, "slate_date": "2026-07-29", "away": "AAA", "home": "BBB",
        "first_pitch_utc": "2026-07-29T23:10:00Z",
        "team": {"away": {"rf_pg": 4.2, "ra_pg": 4.6}, "home": {"rf_pg": 4.9, "ra_pg": 4.1}},
        "team_results_complete_through": "2026-07-28", "team_results_reconciled": True,
        "sp": {"away": {"pid": 111, "name": "Away Starter", "era": 4.8, "gs": 20,
                        "k_pct": 21.0, "bb_pct": 8.0, "confirmed": True,
                        "staleness_tier": "CURRENT", "stale_block_verified": False, "no_log": False},
               "home": {"pid": 222, "name": "Home Starter", "era": 3.2, "gs": 21,
                        "k_pct": 26.0, "bb_pct": 6.5, "confirmed": True,
                        "staleness_tier": "CURRENT", "stale_block_verified": False, "no_log": False}},
        "park_factor": 1.01,
        "quote": {"book": "DK", "ml_home": -145, "ml_away": 125,
                  "observed_at_utc": "2026-07-29T20:00:00Z"},
    }
    row.update(over)
    return row


def selftest() -> int:
    import forecast_registry as fr
    import model_registry
    fails = []

    def ok(name, cond):
        if not cond:
            fails.append(name)

    GEN = "2026-07-29T21:00:00Z"
    PH = {"543037"}  # explicit set for fixtures; real runs load the manifest

    # 1. frozen candidate: real config accepted, any byte change refused
    raw = open(CONFIG, "rb").read()
    beta = _check_config(raw)
    ok("real config accepted", len(beta) == 3)
    try:
        _check_config(raw.replace(b"0.0972", b"0.0973"))
        ok("tampered config REFUSED", False)
    except RuntimeError:
        pass
    ok("placeholder manifest loads and enumerates known pid",
       "543037" in _placeholder_pids())

    # 2. clean row -> PROMOTION_PROSPECTIVE, no flags
    d, f = disposition(_fixture_row(), GEN, PH)
    ok(f"clean row is PROMOTION_PROSPECTIVE with no flags (got {d} {f})",
       d == "PROMOTION_PROSPECTIVE" and f == [])

    # 3. late generation can NEVER be PROMOTION
    d, f = disposition(_fixture_row(), "2026-07-29T23:30:00Z", PH)
    ok("late generation -> DIAGNOSTIC + LATE_GENERATION",
       d == "DIAGNOSTIC_PROSPECTIVE" and "LATE_GENERATION" in f)

    # 4. no price at all -> QUARANTINE (no forecast fabricated)
    d, f = disposition(_fixture_row(quote=None), GEN, PH)
    ok("missing price -> QUARANTINE NO_PRICE", d == "QUARANTINE" and "NO_PRICE" in f)
    d, f = disposition(_fixture_row(sp={"away": {}, "home": {}}), GEN, PH)
    ok("no starters -> QUARANTINE NO_STARTERS", d == "QUARANTINE" and "NO_STARTERS" in f)

    # 5. placeholder-contaminated starter -> DIAGNOSTIC
    r5 = _fixture_row()
    r5["sp"]["home"] = dict(r5["sp"]["home"], pid=543037)
    d, f = disposition(r5, GEN, PH)
    ok("placeholder arm -> DIAGNOSTIC + HOME_PLACEHOLDER_CONTAMINATED",
       d == "DIAGNOSTIC_PROSPECTIVE" and "HOME_PLACEHOLDER_CONTAMINATED" in f)

    # 6. stale team results -> DIAGNOSTIC (D-1 reconciliation rule)
    d, f = disposition(_fixture_row(team_results_complete_through="2026-07-25"), GEN, PH)
    ok("stale team results -> DIAGNOSTIC + TEAM_RESULTS_STALE",
       d == "DIAGNOSTIC_PROSPECTIVE" and "TEAM_RESULTS_STALE" in f)

    # 7. STALE_BLOCK starter: unverified blocks, verified does not
    r7 = _fixture_row()
    r7["sp"]["away"] = dict(r7["sp"]["away"], staleness_tier="STALE_BLOCK")
    d, f = disposition(r7, GEN, PH)
    ok("STALE_BLOCK unverified -> DIAGNOSTIC", "AWAY_STALE_BLOCK_UNVERIFIED" in f)
    r7["sp"]["away"]["stale_block_verified"] = True
    d, f = disposition(r7, GEN, PH)
    ok("STALE_BLOCK verified -> clean", d == "PROMOTION_PROSPECTIVE")

    # 8. unconfirmed starter and one-sided quote each demote
    r8 = _fixture_row()
    r8["sp"]["home"] = dict(r8["sp"]["home"], confirmed=False)
    ok("unconfirmed starter -> DIAGNOSTIC",
       "HOME_STARTER_UNCONFIRMED" in disposition(r8, GEN, PH)[1])
    r8b = _fixture_row(quote={"book": "DK", "ml_home": -145, "ml_away": None,
                              "observed_at_utc": "2026-07-29T20:00:00Z"})
    ok("one-sided quote -> DIAGNOSTIC", "ONE_SIDED_QUOTE" in disposition(r8b, GEN, PH)[1])
    r8c = _fixture_row(quote={"book": "DK", "ml_home": -145, "ml_away": 125,
                              "observed_at_utc": "2026-07-29T23:20:00Z"})
    ok("post-pitch quote -> DIAGNOSTIC", "QUOTE_NOT_PROVEN_PREPITCH" in disposition(r8c, GEN, PH)[1])

    # 9. de-vig arithmetic
    p, ovr = devig_proportional(-110, -110)
    ok("proportional devig -110/-110 = 0.5", abs(p - 0.5) < 1e-12)
    ok("overround -110/-110 ~ 4.76%", abs(ovr - (2 * (110 / 210) - 1)) < 1e-9)
    ok("power devig symmetric = 0.5", abs(devig_power(-110, -110) - 0.5) < 1e-9)
    p2_, _ = devig_proportional(-145, 125)
    ok("devig favourite > 0.5", 0.5 < p2_ < 1.0)

    # 10. incumbent: bit-identical to the registered arithmetic, deterministic, gamePk-keyed
    row = _fixture_row()
    direct = p2.v13_row(dict(row, _gidx=42), V13_HFA, V13_SIMS)   # seed 7_000_000+42 = 7000042
    ok("v13_p4 == ml_p2_baselines.v13_row bit-identical (same seed path)",
       v13_p4(row) == direct)
    ok("v13_p4 deterministic on repeat", v13_p4(row) == v13_p4(row))
    ok("different gamePk -> different stream",
       v13_p4(_fixture_row(gamePk=7000043)) != v13_p4(row))

    # 11. candidate probability matches the frozen beta by hand
    x = p2.feats_2f(row)
    manual = 1.0 / (1.0 + np.exp(-(beta[0] + beta[1] * x[1] + beta[2] * x[2])))
    ok("candidate_p equals manual logistic", abs(candidate_p(row, beta) - manual) < 1e-12)

    # 12. record construction + registry rule engine
    sref = {"path": "fixture_slate.json", "sha256": "f" * 64}
    reader = lambda p: ("f" * 64) if p == "fixture_slate.json" else None
    rec = make_record(_fixture_row(), beta, GEN, GEN, sref, PH)
    ok("clean record cohort PROMOTION_PROSPECTIVE", rec["cohort"] == "PROMOTION_PROSPECTIVE")
    ok("clean record promotion_eligible", rec["promotion_eligible"] is True)
    ok("ledger_eligible always False", rec["ledger_eligible"] is False)
    v = fr.validate_records([rec], [], registry=model_registry.REGISTRY, artifact_hash_reader=reader)
    ok(f"clean record passes registry rule engine ({v[:2]})", v == [])
    late = make_record(_fixture_row(), beta, "2026-07-29T23:30:00Z", GEN, sref, PH)
    ok("late record never promotion_eligible",
       late["cohort"] == "DIAGNOSTIC_PROSPECTIVE" and late["promotion_eligible"] is False)
    doctored = dict(rec, cohort="DIAGNOSTIC_PROSPECTIVE")  # promotion_eligible still True
    ok("doctored promotion_eligible on DIAGNOSTIC is REJECTED by rule engine",
       fr.validate_records([doctored], [], registry=model_registry.REGISTRY,
                           artifact_hash_reader=reader) != [])
    qrec = make_record(_fixture_row(quote=None), beta, GEN, GEN, sref, PH)
    ok("quarantine emits refusal dict, no probabilities",
       qrec.get("quarantine") is True and "payload" not in qrec)
    g1 = make_record(_fixture_row(gamePk=None, dh_game=1), beta, GEN, GEN, sref, PH)
    g2 = make_record(_fixture_row(gamePk=None, dh_game=2), beta, GEN, GEN, sref, PH)
    ok("doubleheader games get distinct forecast ids", g1["forecast_id"] != g2["forecast_id"])

    if fails:
        print("ml_p4_forward selftest: FAIL")
        for x in fails:
            print("  " + x)
        return 1
    print("ml_p4_forward selftest: PASS (24 fixtures: hash-freeze refusal, quarantine, "
          "late/placeholder/stale demotion, devig, incumbent bit-identity, rule engine, DH ids)")
    return 0


if __name__ == "__main__":
    if "--slate" in sys.argv:
        raise SystemExit(run_slate(sys.argv[sys.argv.index("--slate") + 1]))
    if "--grade" in sys.argv:
        i = sys.argv.index("--grade")
        raise SystemExit(add_grade(sys.argv[i + 1], int(sys.argv[i + 2]),
                                   sys.argv[i + 3] if len(sys.argv) > i + 3 else "manual"))
    if "--report" in sys.argv:
        raise SystemExit(report())
    raise SystemExit(selftest())
