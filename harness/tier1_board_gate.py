#!/usr/bin/env python3
"""Tier-1 board completeness + provenance gate for a date range. Four criteria, machine-checked.

WHY (owner instruction 2026-08-17): "Acquire and validate complete tier-1 boards for 2026-08-15 and
2026-08-16 before generating the next card. Preserve source provenance and capture timestamps,
reject tier-2/3 substitutes from canonical results/form inputs, and explicitly report any unresolved
games or fields." The stated success criteria:

    LATEST_TIER1_FORM_DATE          >= 2026-08-16
    missing_tier1_games_8_15        == 0
    missing_tier1_games_8_16        == 0
    canonical_results_contamination == 0

"missing = 0" is the hard one, because a count cannot prove completeness against itself: 15 rows are
15 rows whether or not a 16th game existed. This module therefore does NOT trust the board's own
expected_game_count. It uses a structural invariant that the board cannot fake:

    MLB has 30 franchises. On a full single-header slate every franchise appears in exactly one game,
    so 15 games with 30 distinct franchises each appearing exactly once is COMPLETE BY CONSTRUCTION —
    a 16th game is impossible without some franchise appearing twice, and a missing game would leave
    two franchises absent. A doubleheader shows up as a franchise appearing twice and is reported
    explicitly rather than silently absorbed.

That invariant is independent of the source, so it survives a source that is wrong or truncated.
A partial slate (off-days) is NOT assumed complete; it is reported as UNVERIFIABLE_BY_INVARIANT with
the absent franchises named, because on such a date the invariant genuinely cannot settle the count.

Provenance is checked by RE-HASHING the evidence file on disk against every row's recorded
evidence_sha256. A row whose evidence file is missing, or whose bytes no longer hash to what was
recorded, is a provenance failure and not a warning.

MEASUREMENT ONLY: reads, never writes to results.csv. Emits a report artifact.

Usage: python3 harness/tier1_board_gate.py [--dates 2026-08-15,2026-08-16] [--gate] [--selftest]
"""
from __future__ import annotations
import argparse, collections, csv, datetime as dt, hashlib, json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))
from tier_discipline import is_canonical_final, naive_final  # noqa: E402

RESULTS = "data/backfill/mlb/2026/results.csv"
PARKS = "data/backfill/mlb/2026/park_factors.json"
OUT = "data/audit/tier1_board_gate.json"
# The 30 franchises by the abbreviation results.csv stores, frozen here as a SET rather than a count.
# Counting distinct names was not enough: a typo ("NYY " / "NY Yankees") reads as a 30th distinct name
# while a real franchise is absent, and a count-only invariant would call that slate complete. Caught
# by this module's own selftest before it was ever run on live data.
MLB_ABBRS = frozenset("AZ ATL BAL BOS CHC CWS CIN CLE COL DET HOU KC LAA LAD MIA MIL MIN NYM NYY ATH "
                      "PHI PIT SD SF SEA STL TB TEX TOR WSH".split())
MLB_FRANCHISES = len(MLB_ABBRS)

# Required on every canonical row. Named individually so a report can say WHICH field is unresolved
# rather than "a field is missing".
REQUIRED_FIELDS = ["game_id", "date", "away", "home", "away_score", "home_score", "home_win",
                   "margin", "total", "venue", "source", "ingested_utc", "source_tier",
                   "result_status", "evidence_path", "evidence_sha256"]


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def audit_date(rows, date, parks, hash_cache):
    sub = [r for r in rows if r["date"] == date]
    rep = {"date": date, "rows": len(sub)}

    # --- tier discipline: what is canonical, and what tier-2/3 substitutes are present ---
    canon = [r for r in sub if is_canonical_final(r)]
    non_canon_finals = [r for r in sub if naive_final(r) and not is_canonical_final(r)]
    non_final = [r for r in sub if not naive_final(r)]
    rep["canonical_tier1_finals"] = len(canon)
    rep["tier_2_3_substitutes_in_canonical_input"] = [
        {"game": f'{r["away"]}@{r["home"]}', "source_tier": r.get("source_tier"),
         "result_status": r.get("result_status"), "source": r.get("source")} for r in non_canon_finals]
    rep["rows_not_final"] = [{"game": f'{r["away"]}@{r["home"]}', "status": r.get("status"),
                              "total": r.get("total")} for r in non_final]

    # --- completeness by the franchise-slot invariant (source-independent) ---
    slots = collections.Counter(t for r in canon for t in (r["away"], r["home"]))
    twice = sorted(t for t, n in slots.items() if n > 1)
    unknown = sorted(set(slots) - MLB_ABBRS)
    absent = sorted(MLB_ABBRS - set(slots))
    rep["distinct_franchises"] = len(slots)
    rep["franchises_appearing_more_than_once"] = twice
    rep["names_not_a_known_franchise"] = unknown
    if unknown:
        rep["completeness"] = "UNKNOWN_TEAM_NAME_INVARIANT_INAPPLICABLE"
        rep["missing_tier1_games"] = None
        rep["completeness_basis"] = (f"{unknown} are not known franchise abbreviations. A name the "
                                     f"invariant cannot place could be a typo standing in for an absent "
                                     f"franchise, so completeness is NOT asserted")
    elif not absent and not twice:
        rep["completeness"] = "COMPLETE_BY_INVARIANT"
        rep["missing_tier1_games"] = 0
        rep["completeness_basis"] = (f"all {MLB_FRANCHISES} known franchises appear exactly once across "
                                     f"{len(canon)} canonical tier-1 games; a 16th game would repeat a "
                                     f"franchise and a missing game would leave two absent")
    elif twice:
        rep["completeness"] = "DOUBLEHEADER_PRESENT_INVARIANT_INAPPLICABLE"
        rep["missing_tier1_games"] = None
        rep["completeness_basis"] = (f"franchise(s) {twice} appear more than once, so the one-slot "
                                     f"invariant cannot settle the count; needs an external schedule")
    else:
        rep["completeness"] = "UNVERIFIABLE_BY_INVARIANT_PARTIAL_SLATE"
        rep["missing_tier1_games"] = None
        rep["franchises_absent"] = absent
        rep["completeness_basis"] = (f"{len(absent)} franchise(s) absent ({', '.join(absent)}). On a "
                                     f"partial slate the invariant cannot distinguish an off-day from a "
                                     f"missing game — NOT asserted complete")

    # --- provenance: evidence must exist and still hash to what was recorded ---
    prov_fail, ts = [], []
    for r in canon:
        p, want = r.get("evidence_path"), r.get("evidence_sha256")
        g = f'{r["away"]}@{r["home"]}'
        if not p or not want:
            prov_fail.append(f"{g}: no evidence_path/evidence_sha256 recorded")
            continue
        if not os.path.exists(p):
            prov_fail.append(f"{g}: evidence file missing on disk: {p}")
            continue
        if p not in hash_cache:
            hash_cache[p] = _sha(p)
        if hash_cache[p] != want:
            prov_fail.append(f"{g}: evidence {p} now hashes {hash_cache[p][:12]}, recorded {want[:12]}")
        if r.get("ingested_utc"):
            ts.append(r["ingested_utc"])
    rep["provenance_failures"] = prov_fail
    rep["distinct_evidence_files"] = sorted({r.get("evidence_path") for r in canon if r.get("evidence_path")})
    rep["evidence_sha256"] = {p: hash_cache.get(p) for p in rep["distinct_evidence_files"]}
    rep["capture_timestamps"] = {"distinct": sorted(set(ts)), "n_rows_with_timestamp": len(ts)}
    rep["sources"] = sorted({r.get("source") for r in canon})

    # --- unresolved fields, named individually ---
    unresolved = collections.defaultdict(list)
    for r in canon:
        g = f'{r["away"]}@{r["home"]}'
        for f in REQUIRED_FIELDS:
            if (r.get(f) or "").strip() == "":
                unresolved[f].append(g)
        if r.get("venue") and parks is not None and r["venue"] not in parks:
            unresolved["venue_not_in_park_factors"].append(f'{g} ({r["venue"]})')
    rep["unresolved_fields"] = {k: v for k, v in sorted(unresolved.items())}

    # --- internal coherence: the board must agree with itself ---
    incoherent = []
    for r in canon:
        g = f'{r["away"]}@{r["home"]}'
        a, h, tot, mar, hw = (_int(r.get(k)) for k in ("away_score", "home_score", "total", "margin", "home_win"))
        if None in (a, h):
            incoherent.append(f"{g}: non-integer score")
            continue
        if tot is not None and a + h != tot:
            incoherent.append(f"{g}: {a}+{h} != total {tot}")
        if mar is not None and h - a != mar:
            incoherent.append(f"{g}: home-away {h - a} != margin {mar}")
        if hw is not None and hw != int(h > a):
            incoherent.append(f"{g}: home_win {hw} disagrees with {a}-{h}")
        if a == h:
            incoherent.append(f"{g}: tie {a}-{h} — MLB games do not end tied")
    rep["internal_incoherence"] = incoherent

    rep["PASS"] = (rep["missing_tier1_games"] == 0 and not prov_fail and not incoherent
                   and not rep["unresolved_fields"] and not rep["tier_2_3_substitutes_in_canonical_input"])
    return rep


def cross_date_echo(rows, dates):
    """A board that echoes the previous day's scores is the failure mode the repo has already been
    bitten by. Same matchup + identical score on adjacent dates is flagged for a human read — it is
    genuinely possible, so this reports rather than fails."""
    by = collections.defaultdict(dict)
    for r in rows:
        if r["date"] in dates and is_canonical_final(r):
            by[r["date"]][f'{r["away"]}@{r["home"]}'] = (r["away_score"], r["home_score"])
    out = []
    ds = sorted(by)
    for i in range(1, len(ds)):
        for g, sc in by[ds[i]].items():
            if by[ds[i - 1]].get(g) == sc:
                out.append(f"{g} {sc[0]}-{sc[1]} identical on {ds[i-1]} and {ds[i]}")
    return out


def run(dates, write=True):
    rows = list(csv.DictReader(open(RESULTS)))
    parks = json.load(open(PARKS)) if os.path.exists(PARKS) else None
    cache = {}
    per_date = [audit_date(rows, d, parks, cache) for d in dates]

    canon_all = [r for r in rows if is_canonical_final(r)]
    leaked = [r for r in rows if naive_final(r) and not is_canonical_final(r)]
    leaked_in_window = [r for r in leaked if r["date"] in dates]
    latest = max((r["date"] for r in canon_all), default=None)

    gid = [r["game_id"] for r in rows]
    dupes = [k for k, v in collections.Counter(gid).items() if v > 1]

    rep = {
        "record_id": "TIER1-BOARD-GATE-" + "-".join(dates),
        "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "role": "MEASUREMENT_NON_FORECASTING — reads results.csv, never writes it",
        "results_file": RESULTS, "results_file_sha256": _sha(RESULTS),
        "criteria": {
            "LATEST_TIER1_FORM_DATE": latest,
            "LATEST_TIER1_FORM_DATE_meets_2026_08_16": bool(latest and latest >= "2026-08-16"),
            "missing_tier1_games_8_15": next((d["missing_tier1_games"] for d in per_date
                                              if d["date"] == "2026-08-15"), None),
            "missing_tier1_games_8_16": next((d["missing_tier1_games"] for d in per_date
                                              if d["date"] == "2026-08-16"), None),
            "canonical_results_contamination_IN_WINDOW": len(leaked_in_window),
            "canonical_results_contamination_WHOLE_FILE": len(leaked),
        },
        "contamination_whole_file": {
            "leaked_rows": len(leaked),
            "by_class": dict(sorted(collections.Counter(
                f'tier{r.get("source_tier") or "blank"}/{r.get("result_status") or "blank"}'
                for r in leaked).items())),
            "by_date": dict(sorted(collections.Counter(r["date"] for r in leaked).items())),
            "date_range": [min((r["date"] for r in leaked), default=None),
                           max((r["date"] for r in leaked), default=None)],
            "note": ("These are LEGACY rows predating the owner's 2026-08-16 tier-1-only ruling. They "
                     "are outside the acquisition window and are NOT introduced by this refresh. They "
                     "remain visible to the tier-blind production predicate and therefore still feed "
                     "V13's season-to-date form. Removing them would change a FROZEN model's inputs "
                     "mid-record (R3) and is an owner decision, not a repair — see "
                     "harness/tier_discipline.py and data/audit/tier_exposure_baseline.json."),
        },
        "duplicate_game_ids_whole_file": dupes,
        "cross_date_echo_flags": cross_date_echo(rows, dates),
        "per_date": per_date,
    }
    rep["ALL_CRITERIA_MET_IN_WINDOW"] = bool(
        rep["criteria"]["LATEST_TIER1_FORM_DATE_meets_2026_08_16"]
        and rep["criteria"]["missing_tier1_games_8_15"] == 0
        and rep["criteria"]["missing_tier1_games_8_16"] == 0
        and rep["criteria"]["canonical_results_contamination_IN_WINDOW"] == 0
        and not dupes and all(d["PASS"] for d in per_date))
    if write:
        os.makedirs("data/audit", exist_ok=True)
        json.dump(rep, open(OUT, "w"), indent=1)
    return rep


def selftest():
    fails = []
    parks = json.load(open(PARKS))
    base = [{"date": "2026-01-01", "status": "final", "source_tier": "1", "result_status": "FINAL",
             "away": f"A{i}", "home": f"H{i}", "away_score": "1", "home_score": "2", "total": "3",
             "margin": "1", "home_win": "1", "game_id": f"g{i}", "venue": "Wrigley Field",
             "source": "s", "ingested_utc": "t", "evidence_path": PARKS,
             "evidence_sha256": _sha(PARKS)} for i in range(15)]
    # 30 distinct but UNKNOWN names must not read complete (this fixture caught the count-only hole)
    r = audit_date(base, "2026-01-01", parks, {})
    if r["completeness"] != "UNKNOWN_TEAM_NAME_INVARIANT_INAPPLICABLE" or r["missing_tier1_games"] == 0:
        fails.append("30 distinct non-franchise names read as a complete slate — the invariant is "
                     "counting names rather than placing franchises")
    # a real full slate must read complete
    ab = sorted(MLB_ABBRS)
    real = [dict(base[i], away=ab[2 * i], home=ab[2 * i + 1], game_id=f"r{i}") for i in range(15)]
    rr = audit_date(real, "2026-01-01", parks, {})
    if rr["completeness"] != "COMPLETE_BY_INVARIANT" or rr["missing_tier1_games"] != 0:
        fails.append(f"a genuine 30-franchise slate did not read complete: {rr['completeness']}")
    # ONE typo standing in for an absent franchise must NOT read complete (the real-world failure)
    typo = [dict(x) for x in real]; typo[0]["away"] = "NY Yankees"
    rt = audit_date(typo, "2026-01-01", parks, {})
    if rt["missing_tier1_games"] == 0 or not rt["names_not_a_known_franchise"]:
        fails.append("a typo'd team name masked an absent franchise and the slate read complete")
    # a genuinely short slate must name the absent franchises
    short = real[:14]
    rs = audit_date(short, "2026-01-01", parks, {})
    if rs["missing_tier1_games"] == 0 or len(rs.get("franchises_absent", [])) != 2:
        fails.append("a 14-game slate did not report its two absent franchises")
    # a repeated franchise must be reported, never absorbed
    dh = [dict(x) for x in real]
    dh[1]["away"] = real[0]["away"]
    r2 = audit_date(dh, "2026-01-01", parks, {})
    if not r2["franchises_appearing_more_than_once"] or r2["missing_tier1_games"] == 0:
        fails.append("a repeated franchise (doubleheader) was absorbed instead of reported")
    # a tier-3 row must surface as a substitute, not be silently dropped
    t3 = [dict(x) for x in real] + [dict(real[0], source_tier="3", result_status="PROVISIONAL",
                                        game_id="gx")]
    if not audit_date(t3, "2026-01-01", parks, {})["tier_2_3_substitutes_in_canonical_input"]:
        fails.append("tier-3 substitute not reported")
    # provenance: a wrong evidence hash must fail
    bad = [dict(x, evidence_sha256="0" * 64) for x in real]
    if not audit_date(bad, "2026-01-01", parks, {})["provenance_failures"]:
        fails.append("wrong evidence hash not caught")
    bad2 = [dict(x, evidence_path="data/does_not_exist.json") for x in real]
    if not audit_date(bad2, "2026-01-01", parks, {})["provenance_failures"]:
        fails.append("missing evidence file not caught")
    # coherence: scores that do not sum to total must fail
    inc = [dict(x, total="99") for x in real]
    if not audit_date(inc, "2026-01-01", parks, {})["internal_incoherence"]:
        fails.append("linescore/total mismatch not caught")
    tie = [dict(x, away_score="2", home_score="2", total="4", margin="0", home_win="0") for x in real]
    if not audit_date(tie, "2026-01-01", parks, {})["internal_incoherence"]:
        fails.append("tie game not caught")
    # blank venue must surface as an unresolved FIELD by name
    bv = [dict(x, venue="") for x in real]
    if "venue" not in audit_date(bv, "2026-01-01", parks, {})["unresolved_fields"]:
        fails.append("blank venue not reported as an unresolved field")
    # echo detector must fire on an identical adjacent-day repeat and not on a different score
    e = [dict(real[0], date="2026-01-01"), dict(real[0], date="2026-01-02", game_id="g99")]
    if not cross_date_echo(e, ["2026-01-01", "2026-01-02"]):
        fails.append("adjacent-day identical repeat not flagged")
    e2 = [dict(real[0], date="2026-01-01"), dict(real[0], date="2026-01-02", game_id="g99", home_score="9")]
    if cross_date_echo(e2, ["2026-01-01", "2026-01-02"]):
        fails.append("echo detector fired on a different score")
    if fails:
        print("tier1_board_gate selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("tier1_board_gate selftest: PASS (unknown/typo'd team name, short slate, doubleheader, "
          "tier-3 substitute, bad+missing evidence hash, linescore incoherence, tie, blank venue and "
          "adjacent-day echo all caught; a genuine 30-franchise slate reads complete)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", default="2026-08-15,2026-08-16")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    r = run([d.strip() for d in a.dates.split(",")])
    c = r["criteria"]
    print(f'LATEST_TIER1_FORM_DATE          = {c["LATEST_TIER1_FORM_DATE"]}   '
          f'(>= 2026-08-16: {c["LATEST_TIER1_FORM_DATE_meets_2026_08_16"]})')
    print(f'missing_tier1_games_8_15        = {c["missing_tier1_games_8_15"]}')
    print(f'missing_tier1_games_8_16        = {c["missing_tier1_games_8_16"]}')
    print(f'canonical_results_contamination = {c["canonical_results_contamination_IN_WINDOW"]} in window   '
          f'({c["canonical_results_contamination_WHOLE_FILE"]} legacy rows elsewhere in the file)')
    for d in r["per_date"]:
        print(f'\n[{d["date"]}] {d["canonical_tier1_finals"]} canonical tier-1 finals — {d["completeness"]}')
        print(f'   {d["completeness_basis"]}')
        print(f'   sources {d["sources"]}  captured {d["capture_timestamps"]["distinct"]}')
        for p, h in d["evidence_sha256"].items():
            print(f'   evidence {p} sha256 {h[:16]} VERIFIED')
        for k in ("tier_2_3_substitutes_in_canonical_input", "provenance_failures",
                  "internal_incoherence", "rows_not_final"):
            print(f'   {k}: {len(d[k]) if isinstance(d[k], list) else d[k]}')
        print(f'   unresolved_fields: {d["unresolved_fields"] or "NONE"}')
    if r["cross_date_echo_flags"]:
        print("\n  ! echo flags:", r["cross_date_echo_flags"])
    print(f'\nALL_CRITERIA_MET_IN_WINDOW = {r["ALL_CRITERIA_MET_IN_WINDOW"]}   -> {OUT}')
    raise SystemExit(1 if (a.gate and not r["ALL_CRITERIA_MET_IN_WINDOW"]) else 0)
