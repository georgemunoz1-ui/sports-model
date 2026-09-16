#!/usr/bin/env python3
"""Grade a slate's registered cohorts against a tier-1 finals board. Each cohort exactly once.

STANDING RULES THIS ENFORCES:
  - a forecast is graded EXACTLY ONCE; a second grade for the same forecast_id is REFUSED, not
    overwritten (R6 append-only)
  - cohorts are graded separately and NEVER pooled; v1/v2/v3 are distinct arms of the same slate and
    a combined score would be three correlated reads of eleven games presented as one
  - every forecast must map to exactly one board game or the module refuses; no fuzzy matching
  - prices that arrive AFTER the final are CLOSING prices. They may be used for EV-at-close
    evaluation and may never be presented as a pregame selection.

DIACRITICS: card starter names carry accents ("Cristopher Sánchez", "Martín Pérez") and the board
does not. A naive string compare reports those as starter CHANGES, which would have inflated the
starter-defect count from 4 to 6. Names are NFKD-folded before comparison.

DOUBLEHEADER MAPPING is by SCHEDULED ORDER, not by starter. The 2026-08-17 card assigned Rhett
Lowder to the 17:40Z game; the board shows he actually started game 2. The forecast was made FOR the
17:40Z game, so it grades against game 1 and the starter is recorded as a forecast-input DEFECT.
Mapping by starter instead would silently regrade a forecast against a different game than the one
it was registered for.

Usage: python3 harness/grade_slate.py --date 2026-08-17 --board <evidence.json> [--commit] [--selftest]
"""
from __future__ import annotations

MODULE_ID = "grade_slate"
import argparse, datetime as dt, hashlib, json, math, os, sys, unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
FORECASTS = "data/mlb/forecasts/forecasts.jsonl"
GRADES = "data/mlb/forecasts/grades.jsonl"
EPS = 1e-6


def fold(s):
    return unicodedata.normalize("NFKD", (s or "")).encode("ascii", "ignore").decode().lower().strip()


def last_name(s):
    f = fold(s)
    return f.split()[-1] if f else ""


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def implied(american):
    """Raw implied probability from an American price. NOT de-vigged."""
    a = float(american)
    return (-a) / ((-a) + 100) if a < 0 else 100 / (a + 100)


def devig_two_sided(a_away, a_home):
    """Same-book two-sided proportional de-vig -> (p_away, p_home). Valid because both sides come
    from ONE board. Cross-book best-odds de-vig is INVALID for market probability (8/3 ruling)."""
    ia, ih = implied(a_away), implied(a_home)
    s = ia + ih
    return ia / s, ih / s


def decimal_from_american(a):
    a = float(a)
    return 1 + (100 / (-a)) if a < 0 else 1 + (a / 100)


def brier(p, y):
    return (p - y) ** 2


def logloss(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def board_key(g):
    return f'{g["away"]}@{g["home"]}' + (f'-{g["dh"]}' if g.get("dh") else "")


def load_board(path):
    b = json.load(open(path))
    return b, {board_key(g): g for g in b["games"]}


def cohort_of(fid):
    """P4-20260817-X -> v1 ; P4-20260817v2-X -> v2 ; P4-20260817v3-X -> v3"""
    head = fid.split("-")[1]
    return head[8:] if len(head) > 8 else "v1"


def map_forecast(fid, card_rows, board, date):
    """Return the board game this forecast grades against, or None. Mapping is by the CARD ROW the
    forecast was registered from — never by starter, never by fuzzy name match."""
    tail = fid.split("-", 2)[2]  # e.g. "STL@CIN-G1" or "BAL@TB"
    row = next((r for r in card_rows if _row_tail(r) == tail), None)
    if row is None:
        return None, f"{fid}: no card row with tail {tail}"
    if row["gamePk"].startswith("DH"):
        # scheduled order: DH1 -> board G1, DH2 -> board G2
        key = f'{row["away"]}@{row["home"]}-G{row["gamePk"][2:]}'
    else:
        key = f'{row["away"]}@{row["home"]}'
        # a single-row STL@CIN in a doubleheader slate must be disambiguated by TIME, not guessed
        if key not in board:
            cands = [k for k in board if k.startswith(key + "-")]
            if len(cands) != 1:
                by_time = _dh_by_time(row, board, key)
                if by_time is None:
                    return None, (f"{fid}: {key} is a doubleheader on the board ({cands}) and the card "
                                  f"row has no unambiguous scheduled-order or time mapping")
                key = by_time
            else:
                key = cands[0]
    g = board.get(key)
    return (g, None) if g else (None, f"{fid}: board has no game {key}")


def _row_tail(r):
    return f'{r["away"]}@{r["home"]}' + ("-G" + r["gamePk"][2:] if r["gamePk"].startswith("DH") else "")


def _dh_by_time(row, board, key):
    """A v1-style single row for a date that turned out to be a doubleheader: the row's scheduled
    time decides which game it was FOR. 22:40Z on 2026-08-17 is the second game."""
    t = row.get("time")
    if not t or t == "TBD":
        return None
    order = sorted(k for k in board if k.startswith(key + "-"))
    if not order:
        return None
    # earliest board game is G1; a row scheduled at the later slot is G2
    return order[-1] if t >= "20:00Z" else order[0]


class BoardDateMismatch(ValueError):
    """The finals board is not the board for the date being graded."""


def assert_board_is_for_date(board_doc, date, board_path):
    """RESULT_DATE_COHORT_CONTAMINATION guard (2026-08-28, owner-caught).

    board_key() is (away,home) — deliberately, because a finals board holds one slate. But a
    continuing series repeats the matchup on consecutive days, so that key silently joins a
    forecast to the WRONG DAY's final if the board handed in is the wrong board. Measured on this
    repo: all 15 matchups repeat between 2026-08-18 and 2026-08-19 and 12 of the 15 have opposite
    winners, so grading 8/19 against the 8/18 board produced 15 confidently wrong labels and zero
    errors — and with --commit those labels are appended to the append-only grade ledger, where
    grade_ledger.rebuild treats them as canonical.

    The board declares its own date. Requiring it to match is the whole fix; every finals board in
    data/mlb/evidence carries slate_date at doc level.
    """
    bd = board_doc.get("slate_date") or board_doc.get("date")
    if bd is None:
        raise BoardDateMismatch(
            f"BOARD_DATE_UNDECLARED: {board_path} carries no slate_date; a finals board without "
            f"its own date cannot be verified against --date {date} and a repeated series would "
            f"join silently")
    if str(bd) != str(date):
        raise BoardDateMismatch(
            f"BOARD_DATE_MISMATCH: --date {date} but {board_path} declares slate_date {bd}. "
            f"Refusing: a repeated series makes (away,home) non-unique across dates, so this "
            f"would grade the forecasts against another day's finals.")
    return str(bd)


LEGACY_WRITE_SUSPENDED = "LEGACY_GRADING_PATH_WRITE_SUSPENDED"


def assert_board_can_prove_binding(board_doc, board_path):
    """P0 requirement (owner, 2026-08-28): no record, Brier, P&L, thesis, promotion evidence or
    estimator input may compute until EVERY row passes reconciliation on
    sport + canonical_game_id + scheduled_date + both teams.

    This path cannot meet that bar today: every finals board under data/mlb/evidence carries a
    doc-level date and NO per-game canonical id, so a row here is reconciled on teams + a
    board-level date only. The date check above closes the cross-date hole that caused the
    incident, but it cannot prove WHICH game within a date — a doubleheader is still ambiguous,
    and an id typo is undetectable.

    So the WRITE is suspended rather than the read: dry-run analysis stays available, and nothing
    reaches the append-only grade ledger (where grade_ledger.rebuild would treat it as canonical)
    until the board schema carries per-game ids. Unblock condition is stated, not implied.
    """
    games = board_doc.get("games") or []
    with_id = [g for g in games if g.get("gamePk") or g.get("game_pk") or g.get("game_id")]
    if len(with_id) != len(games) or not games:
        raise BoardDateMismatch(
            f"{LEGACY_WRITE_SUSPENDED}: {board_path} carries per-game canonical ids for "
            f"{len(with_id)}/{len(games)} games. Committing grades from a board that cannot "
            f"identify its own games would write unreconcilable rows into the append-only ledger. "
            f"Dry run is unaffected. UNBLOCK: add gamePk to each board game, then bind through "
            f"harness/result_binding_gate.bind_cohort and attach the binding proof.")
    return True


def run(date, board_path, commit=False):
    board_doc, board = load_board(board_path)
    assert_board_is_for_date(board_doc, date, board_path)
    if commit:
        assert_board_can_prove_binding(board_doc, board_path)
    fc = [json.loads(l) for l in open(FORECASTS) if l.strip()]
    fc = [r for r in fc if r.get("slate_date") == date]
    already = {json.loads(l)["forecast_id"] for l in open(GRADES) if l.strip()} if os.path.exists(GRADES) else set()

    cards = {}
    for suffix, path in (("v1", f"cards/{date}_card.json"), ("v2", f"cards/{date}_card_v2.json"),
                         ("v3", f"cards/{date}_card_v3.json")):
        if os.path.exists(path):
            cards[suffix] = json.load(open(path))["rows"]

    rows, errors, skipped = [], [], []
    for f in sorted(fc, key=lambda x: x["forecast_id"]):
        fid = f["forecast_id"]
        coh = cohort_of(fid)
        if coh not in cards:
            errors.append(f"{fid}: no card artifact for cohort {coh}")
            continue
        if fid in already:
            skipped.append(fid)
            continue
        g, err = map_forecast(fid, cards[coh], board, date)
        if err:
            errors.append(err)
            continue
        tail = fid.split("-", 2)[2]
        crow = next(r for r in cards[coh] if _row_tail(r) == tail)
        p = crow["v13"]["home_wp"]
        y = int(g["home_score"] > g["away_score"])
        # 2026-08-20: a finals board with no closing prices grades winner/total normally;
        # every market-relative field is null with the reason carried in the record (R1) —
        # a missing price is never invented and never blocks the winner grade.
        priced = g.get("close_ml_away") is not None and g.get("close_ml_home") is not None
        side_home = p >= .5
        p_side = p if side_home else 1 - p
        if priced:
            pa, ph = devig_two_sided(g["close_ml_away"], g["close_ml_home"])
            be = ph if side_home else pa
            price = g["close_ml_home"] if side_home else g["close_ml_away"]
            dec = decimal_from_american(price)
        else:
            pa = ph = be = price = dec = None
        rows.append({
            "forecast_id": fid, "cohort": coh, "board_game": board_key(g),
            "away": g["away"], "home": g["home"],
            "p_home_model": p, "home_win": y,
            "correct": int((p >= .5) == (y == 1)),
            "brier": round(brier(p, y), 6), "logloss": round(logloss(p, y), 6),
            "final": f'{g["away_score"]}-{g["home_score"]}',
            "actual_total": g["away_score"] + g["home_score"],
            "model_total": crow["v13"]["proj_total"],
            "total_error": round(crow["v13"]["proj_total"] - (g["away_score"] + g["home_score"]), 2),
            "close_total_line": g.get("close_total"),
            "closing_price_devig_p_home": (round(ph, 4) if priced else None),
            "model_minus_market_pp": (round((p - ph) * 100, 2) if priced else None),
            "model_side": g["home"] if side_home else g["away"],
            "model_side_price": price,
            "break_even_prob_at_close": (round(be, 4) if priced else None),
            "edge_pp_at_close": (round((p_side - be) * 100, 2) if priced else None),
            "ev_per_unit_at_close": (round(p_side * (dec - 1) - (1 - p_side), 4) if priced else None),
            "market_fields_null_reason": (None if priced else "board carries no closing prices"),
            "model_side_won": int((side_home and y == 1) or (not side_home and y == 0)),
            "starter_defect": _starter_defect(crow, g),
        })
    return {"date": date, "board": board_path, "board_sha256": sha(board_path),
            "board_captured_utc": board_doc.get("captured_at_utc"),
            "price_timing": board_doc.get("price_timing"),
            "rows": rows, "errors": errors, "already_graded_skipped": skipped}


def _starter_defect(crow, g):
    a_card, h_card = last_name(crow.get("asp")), last_name(crow.get("hsp"))
    a_act, h_act = last_name(g["away_sp"]), last_name(g["home_sp"])
    bad = []
    if a_card != a_act:
        bad.append(f'away: card {crow.get("asp") or "TBD"} -> actual {g["away_sp"]}')
    if h_card != h_act:
        bad.append(f'home: card {crow.get("hsp") or "TBD"} -> actual {g["home_sp"]}')
    return bad or None


def _ledger_forecasts_for(date):
    """forecast_ids the ledger already holds an ACTIVE grade for on this date."""
    import grade_ledger as GL
    fdates = {}
    for f in GL._read_jsonl(GL.FORECASTS):
        fdates.setdefault(f.get("forecast_id"), f.get("slate_date"))
    return [fid for fid in GL.resolve(GL._read_jsonl(GL.GRADES))["active"]
            if fdates.get(fid) == date]


def summarize(res, date=None):
    """Cohort statistics REBUILT FROM THE LEDGER, never from this run's rows.

    OWNER RULING 2026-08-23. summarize() used to average `res["rows"]` — the rows graded in THIS
    RUN — so a re-settlement that graded one late game reported n=1 for a cohort of 15 and pushed
    the rest into already_graded_skipped. The 2026-08-21 v2 headline .230621 was overwritten with
    .292681 that way. The core statistics now come from every active non-superseded ledger record
    for the date and cohort, and the artifact binds the grade ids and an input hash so the rebuild
    is checkable rather than merely asserted.

    Market and totals fields cannot come from the ledger (it carries no prices or scores), so they
    are computed from this run's rows and are emitted ONLY when this run covered the whole active
    cohort. A partial market statistic is exactly the defect this ruling removes, so when the run is
    partial every market/totals field is null with the reason carried (R1)."""
    import grade_ledger as GL
    date = date or res.get("date")
    cohorts = sorted({r["cohort"] for r in res["rows"]} |
                     {GL.cohort_of(f) for f in _ledger_forecasts_for(date)})
    out = {}
    for coh in cohorts:
        t = GL.rebuild(date, coh)
        if t["n"] == 0:
            continue
        rs = [r for r in res["rows"] if r["cohort"] == coh]
        active_ids = {b["grade_id"] for b in t["bound_grades"]}
        run_ids = {f'G-{r["forecast_id"]}' for r in rs}
        covered = active_ids <= run_ids
        pr = [r for r in rs if r.get("closing_price_devig_p_home") is not None] if covered else []
        n = t["n"]
        partial_reason = (None if covered else
                          f"this run graded {len(rs)} of {n} active rows in the cohort; market and "
                          f"totals fields need per-game prices and scores that the ledger does not "
                          f"carry, and a partial market statistic is not reported (R1)")
        out[coh] = {
            "n": n,
            "correct": t["correct"],
            "accuracy": t["accuracy"],
            "brier": t["brier"],
            "logloss": t["logloss"],
            "bound_grade_ids": sorted(active_ids),
            "cohort_input_sha256": t["cohort_input_sha256"],
            "rebuilt_from_ledger": True,
            "run_covered_full_cohort": covered,
            "market_and_totals_null_reason": partial_reason,
            "mean_abs_total_error": round(sum(abs(r["total_error"]) for r in rs) / len(rs), 3) if covered and rs else None,
            "mean_signed_total_error": round(sum(r["total_error"] for r in rs) / len(rs), 3) if covered and rs else None,
            "market_brier_at_close": (round(sum(brier(r["closing_price_devig_p_home"], r["home_win"])
                                                for r in pr) / len(pr), 6) if pr else None),
            # every field below this line is scoped to THIS RUN's rows and is null unless the run
            # covered the whole active cohort
            "ev_at_close_flat_unit_sum": (round(sum(
                (r["ev_per_unit_at_close"]) for r in pr), 4) if pr else None),
            "realized_units_flat_1u_all_model_sides": (round(sum(
                (decimal_from_american(r["model_side_price"]) - 1) if r["model_side_won"] else -1
                for r in pr), 4) if pr else None),
            "priced_rows": len(pr),
        }
    return out


def selftest():
    fails = []

    # RESULT_DATE_COHORT_CONTAMINATION guard, exercised on the real repeated series in this repo.
    # 2026-08-18 and 2026-08-19 share all 15 matchups and 12 have opposite winners, so grading one
    # against the other's board is 15 confident wrong labels appended to the grade ledger.
    import json as _j
    b18, b19 = ("data/mlb/evidence/2026-08-18_owner_finals.json",
                "data/mlb/evidence/2026-08-19_owner_finals.json")
    if os.path.exists(b18) and os.path.exists(b19):
        d18 = _j.load(open(b18))
        try:
            assert_board_is_for_date(d18, "2026-08-19", b18)
            fails.append("the 8/18 board was accepted for grading 2026-08-19")
        except BoardDateMismatch:
            pass
        try:
            assert_board_is_for_date(d18, "2026-08-18", b18)
        except BoardDateMismatch:
            fails.append("the 8/18 board was refused for its own date")
        # the overlap that makes the join dangerous is real, not hypothetical
        k18 = {board_key(g) for g in d18["games"]}
        k19 = {board_key(g) for g in _j.load(open(b19))["games"]}
        if len(k18 & k19) < 10:
            fails.append("expected a large matchup overlap between consecutive slates")
    # the WRITE path is suspended while boards cannot identify their own games; the READ is not
    if os.path.exists(b18):
        d18b = _j.load(open(b18))
        try:
            assert_board_can_prove_binding(d18b, b18)
            fails.append("a board with no per-game canonical ids was cleared to commit")
        except BoardDateMismatch as e:
            if LEGACY_WRITE_SUSPENDED not in str(e):
                fails.append("the write suspension did not name itself")
        # and a board that DOES carry ids passes, so the suspension has a real unblock
        ok_board = {"slate_date": "2026-08-18",
                    "games": [{"away": "A", "home": "H", "gamePk": 1}]}
        try:
            assert_board_can_prove_binding(ok_board, "<synthetic>")
        except BoardDateMismatch:
            fails.append("a board WITH per-game ids was still refused — the unblock is unreachable")

    # a board with no date of its own cannot be verified at all
    try:
        assert_board_is_for_date({"games": []}, "2026-08-19", "<undeclared>")
        fails.append("a board with no declared date was accepted")
    except BoardDateMismatch:
        pass

    if abs(implied(-110) - 0.5238) > 1e-3 or abs(implied(+150) - 0.4) > 1e-3:
        fails.append("implied probability wrong at known prices")
    pa, ph = devig_two_sided(+232, -252)
    if abs(pa + ph - 1) > 1e-9:
        fails.append("de-vigged probabilities do not sum to 1")
    if not (ph > pa):
        fails.append("the favourite did not get the larger de-vigged probability")
    if abs(decimal_from_american(-110) - 1.909) > 1e-3 or abs(decimal_from_american(+150) - 2.5) > 1e-3:
        fails.append("decimal conversion wrong")
    if last_name("Cristopher Sánchez") != "sanchez" or last_name("Martín Pérez") != "perez":
        fails.append("diacritic folding failed — accented names would read as starter changes")
    if last_name("Rhett Lowder") == last_name("Andrew Emanuel"):
        pass
    else:
        pass
    # a genuine change and a diacritic-only difference must be distinguished
    crow = {"asp": "Martín Pérez", "hsp": "Rhett Lowder"}
    if _starter_defect(crow, {"away_sp": "Perez", "home_sp": "Lowder"}) is not None:
        fails.append("a diacritic-only difference was reported as a starter defect")
    if _starter_defect(crow, {"away_sp": "Perez", "home_sp": "Emanuel"}) is None:
        fails.append("a real starter change was NOT reported")
    if brier(0.5, 1) != 0.25 or abs(logloss(0.5, 1) - math.log(2)) > 1e-9:
        fails.append("scoring rules wrong at p=0.5")
    # EV identity: at a fair price the EV of a bet must be 0
    p = 0.6
    d = 1 / p
    if abs(p * (d - 1) - (1 - p)) > 1e-9:
        fails.append("EV at a fair price is not zero — the EV formula is wrong")
    # THE 2026-08-21 REGRESSION. summarize() must report the WHOLE cohort from the ledger even when
    # this run graded nothing at all. Run with res["rows"] EMPTY — the shape of a re-settlement that
    # skipped every already-graded forecast — and the cohort must still come back complete.
    sys.path.insert(0, os.path.join(BASE, "harness"))
    empty_run = {"date": "2026-08-21", "rows": [], "errors": [], "already_graded_skipped": []}
    try:
        s21 = summarize(empty_run, "2026-08-21")
    except Exception as e:
        s21 = {}
        fails.append(f"summarize raised on a run that graded nothing: {type(e).__name__}: {e}")
    for coh, want_n, want_brier in (("v1", 15, 0.246333), ("v2", 15, 0.230621)):
        blk = s21.get(coh)
        if blk is None:
            fails.append(f"summarize dropped cohort {coh} when this run graded no rows — this is "
                         f"the defect that rewrote 2026-08-21 to n=1")
            continue
        if blk["n"] != want_n:
            fails.append(f"{coh} summarised n={blk['n']} from an empty run; the ledger holds "
                         f"{want_n} active grades")
        if abs(blk["brier"] - want_brier) > 5e-6:
            fails.append(f"{coh} brier {blk['brier']} != the ledger's {want_brier}")
        if not blk.get("bound_grade_ids") or not blk.get("cohort_input_sha256"):
            fails.append(f"{coh} statistics are not bound to grade ids and an input hash")
        # a run that covered nothing must not report market or totals statistics
        if blk.get("run_covered_full_cohort") is not False:
            fails.append(f"{coh} claimed the run covered the full cohort when it graded no rows")
        if blk.get("mean_abs_total_error") is not None:
            fails.append(f"{coh} reported a totals statistic from a run with no rows")
        if not blk.get("market_and_totals_null_reason"):
            fails.append(f"{coh} nulled its market fields without carrying the reason (R1)")
    if fails:
        print("grade_slate selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("grade_slate selftest: PASS (price conversions correct at known points; two-sided de-vig "
          "normalises and favours the favourite; diacritic-only name differences are NOT starter "
          "defects while real changes are; EV at a fair price is exactly zero)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-08-17")
    ap.add_argument("--board", default="data/mlb/evidence/2026-08-17_owner_board.json")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    res = run(a.date, a.board, a.commit)
    if res["errors"]:
        print("MAPPING ERRORS — refusing to grade:")
        for e in res["errors"]:
            print("  " + e)
        raise SystemExit(1)
    sys.path.insert(0, os.path.join(BASE, "harness"))
    if a.commit:
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        src = (f'tier1 owner board {res["board"]} sha256:{res["board_sha256"]} status=FINAL')
        # APPEND THROUGH THE REGISTRY, never around it. forecast_registry maintains a hash chain over
        # both jsonl files plus head.json; a raw file append leaves head stale and the chain reads as
        # BROKEN. An earlier version of this module wrote directly and did exactly that.
        import forecast_registry as FR
        for r in res["rows"]:
            FR.append_grade({"grade_id": f'G-{r["forecast_id"]}',
                             "forecast_id": r["forecast_id"], "graded_at_utc": now,
                             "home_win": r["home_win"], "source": src})
        print(f'appended {len(res["rows"])} grades through forecast_registry (chain + head updated)')
    else:
        print("DRY RUN — pass --commit to append grades (each forecast graded exactly once)")
    # THE SUMMARY IS REBUILT FROM THE LEDGER, and therefore only after the ledger is current.
    s = summarize(res, a.date)
    print(f'{a.date} — board {res["board_sha256"][:16]} captured {res["board_captured_utc"]}')
    if res["already_graded_skipped"]:
        print(f'  {len(res["already_graded_skipped"])} forecast(s) already graded and SKIPPED (graded once)')
    print(f'\n{"cohort":<8}{"n":>4}{"W-L":>8}{"acc":>7}{"Brier":>9}{"logloss":>9}'
          f'{"mktBrier":>10}{"totErr":>8}{"EV@close":>10}{"realized":>10}')
    for c, v in s.items():
        print(f'{c:<8}{v["n"]:>4}{str(v["correct"])+"-"+str(v["n"]-v["correct"]):>8}{v["accuracy"]:>7.3f}'
              f'{v["brier"]:>9.5f}{v["logloss"]:>9.5f}{v["market_brier_at_close"]:>10.5f}'
              f'{v["mean_signed_total_error"]:>+8.2f}{v["ev_at_close_flat_unit_sum"]:>+10.3f}'
              f'{v["realized_units_flat_1u_all_model_sides"]:>+10.3f}')
    print(f'\n{"game":<14}{"coh":>4}{"p_home":>8}{"final":>8}{"y":>3}{"ok":>4}{"mkt p_h":>9}'
          f'{"m-mkt":>8}{"side":>6}{"edge":>8}{"EV":>8}{"totE":>7}  starter defect')
    for r in res["rows"]:
        if r["cohort"] != "v3":
            continue
        print(f'{r["board_game"]:<14}{r["cohort"]:>4}{r["p_home_model"]:>8.3f}{r["final"]:>8}'
              f'{r["home_win"]:>3}{("Y" if r["correct"] else "n"):>4}{r["closing_price_devig_p_home"]:>9.3f}'
              f'{r["model_minus_market_pp"]:>+8.1f}{r["model_side"]:>6}{r["edge_pp_at_close"]:>+8.2f}'
              f'{r["ev_per_unit_at_close"]:>+8.3f}{r["total_error"]:>+7.1f}  '
              f'{"; ".join(r["starter_defect"]) if r["starter_defect"] else "-"}')
    os.makedirs("data/mlb/analysis", exist_ok=True)
    op = f"data/mlb/analysis/{a.date}_grades.json"
    json.dump({"summary": s, "contract": "grade_summary_contract_v1",
               "already_graded_skipped_is_audit_only": (
                   "This list records which forecasts this RUN skipped because they were already "
                   "graded. It never reduces a cohort statistic: every number in `summary` is "
                   "rebuilt from the full set of active non-superseded ledger records."),
               **res}, open(op, "w"), indent=1)
    print(f"\nwrote {op}")

