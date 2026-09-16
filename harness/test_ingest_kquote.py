#!/usr/bin/env python3
"""Regression test for the lenient ingester.

The bar: replaying the 7/26 live-at-processing board through ingest_kquote.py
must reproduce the Jose Soriano registration that was made by hand that day,
field for field. If the ingester and the hand pass ever disagree, the ingester
is wrong -- the hand pass is the one with a ledger row behind it.

Also checks the parts of the leniency that are easy to get subtly wrong:
one arm / one book / both sides is registerable; a locked clock is not; an
unknown capture time is not; a line-only cell is not a market.
"""

MODULE_ID = "test_ingest_kquote"
import json, os, subprocess, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
ING = ["python3", "harness/ingest_kquote.py"]
fails = []


def run(drop, now="2026-07-26T19:15:00Z", extra=()):
    r = subprocess.run(ING + [drop, "--now", now] + list(extra),
                       capture_output=True, text=True)
    if r.returncode != 0:
        fails.append("ingester exited %d on %s\n%s" % (r.returncode, drop, r.stderr[-1200:]))
        return None
    return json.load(open(os.path.splitext(drop)[0] + "_ingest.json"))


def _norm_name(n):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", n) if not unicodedata.combining(c)).lower().strip()


def drop_file(payload, tag):
    p = os.path.join(tempfile.mkdtemp(), "2026-07-26_%s.json" % tag)
    json.dump(payload, open(p, "w"), indent=1)
    return p


# ---- 1. the replay must reproduce the hand-made Soriano row -------------------
out = run("data/mlb/props/drops/2026-07-26_replay-live4.json")
if out:
    row = next((r for r in out["rows"] if r["pitcher"] == "Jose Soriano"), None)
    # The row starts in plays_pending and moves to graded once the game is settled.
    # Grading PRESERVES every as-registered field, so the field-for-field comparison below
    # is unchanged wherever the row currently lives. Searching only plays_pending made this
    # test fail the moment Soriano was graded on 2026-07-27.
    _L = json.load(open("state.json"))["ledgers"]["kprops_paper"]

    # Searching both collections is not enough on its own: next() takes the FIRST match, so a
    # row duplicated across pending and graded would pass silently. Assert identity explicitly.
    # NOTE: the ledger schema has no row_id. (date, normalised pitcher) is the identity the
    # write path dedups on, so it is the identity asserted here.
    def _key(r): return (r["date"], _norm_name(r["pitcher"]))
    _pend = [p for p in _L["plays_pending"] if p["pitcher"] == "Jose Soriano"]
    _grad = [p for p in _L["graded"] if p["pitcher"] == "Jose Soriano"]
    if len(_pend) + len(_grad) != 1:
        fails.append("Soriano must appear EXACTLY ONCE across plays_pending+graded, found %d+%d"
                     % (len(_pend), len(_grad)))
    _pk = {_key(r) for r in _L["plays_pending"]}
    _gk = {_key(r) for r in _L["graded"]}
    if _pk & _gk:
        fails.append("row identity present in BOTH plays_pending and graded: %s" % sorted(_pk & _gk))
    led = (_pend + _grad)[0] if (_pend or _grad) else {}
    if not row or not row["play"]:
        fails.append("replay produced no Soriano play at all")
    else:
        p = row["play"]
        _cmp = [(row["status"], "REGISTERABLE", "status"),
                                (row["gate_eligible"], True, "gate_eligible"),
                                (p["side"], led["side"], "side"),
                                (p["line"], led["line"], "line"),
                                (p["price"], led["price"], "price"),
                                (p["book"], led["book"], "book"),
                                (round(row["ek"], 2), led["ek"], "ek"),
                                (row["gs"], led["gs"], "gs"),
                                (p["p"], led["p"], "p"),
                                (p["weight"], led["weight"], "weight"),
                                (p["edge"], led["edge"], "edge"),
                                (p["ev"], led["ev_per_unit"], "ev"),
                                (p["disp"], led["disp"], "disp"),
                                (row["game"], led["game"], "game"),
                                (row["first_pitch"], led["first_pitch_utc"], "first_pitch")]
        # All 15 as-registered fields must be present and value-identical. Asserting the COUNT
        # stops a future edit from quietly deleting a comparison and still reporting PASS.
        if len(_cmp) != 15:
            fails.append("expected 15 registration-field comparisons, found %d" % len(_cmp))
        for got, want, name in _cmp:
            if got != want:
                fails.append("Soriano %s: ingester %r vs ledger %r" % (name, got, want))
    # and it must not invent extra registrations
    n = len([r for r in out["rows"] if r["status"] == "REGISTERABLE"])
    if n != 1:
        fails.append("replay registered %d plays, expected exactly 1" % n)

# ---- 2. one arm, one book, both sides, single-book page: registerable ---------
p = drop_file(dict(date="2026-07-26", captured_utc="2026-07-26T19:13:00Z",
                   source_type="book_direct", source_note="minimum useful capture",
                   quotes=[["FD", "Jose Soriano", 4.5, 130, -166]]), "min")
out = run(p)
if out:
    r = out["rows"][0]
    if r["status"] != "REGISTERABLE":
        fails.append("minimum capture not registerable: %s / %s" % (r["status"], r["rejections"]))
    if any("T3" in t and "skipped" not in t for t in r["tests"]):
        fails.append("T3 ran on a single-book capture: %s" % r["tests"])

# ---- 3. the clock is not negotiable ------------------------------------------
for tag, kw, now, why in [
        ("late", dict(captured_utc="2026-07-26T20:30:00Z"), "2026-07-26T20:35:00Z", "captured after first pitch"),
        ("noclock", dict(), "2026-07-26T19:15:00Z", "capture time unknown"),
        ("slow", dict(captured_utc="2026-07-26T19:13:00Z"), "2026-07-26T20:30:00Z", "processed after first pitch")]:
    p = drop_file(dict(date="2026-07-26", source_type="book_direct", source_note=why,
                       quotes=[["FD", "Jose Soriano", 4.5, 130, -166]], **kw), tag)
    out = run(p, now=now)
    if out and (out["rows"][0]["gate_eligible"] or out["rows"][0]["status"] == "REGISTERABLE"):
        fails.append("%s: gate-eligible when it must not be (%s)" % (tag, why))
    if out and out["rows"][0]["status"] != "SHADOW":
        fails.append("%s: expected SHADOW, got %s" % (tag, out["rows"][0]["status"]))

# ---- 4. a line with no price is not a market ---------------------------------
p = drop_file(dict(date="2026-07-26", captured_utc="2026-07-26T19:13:00Z",
                   source_type="book_direct", source_note="line only",
                   quotes=[["FD", "Jose Soriano", 4.5, None, None]]), "lineonly")
out = run(p)
if out and out["rows"][0]["quotes_kept"] != 0:
    fails.append("line-only cell was kept as a market")

# ---- 5. aggregator alt ladder gets quarantined by dispersion ------------------
p = drop_file(dict(date="2026-07-26", captured_utc="2026-07-26T19:13:00Z",
                   source_type="aggregator", source_note="alt ladder",
                   quotes=[["DK", "Kyle Freeland", 1.5, 115, -155],
                           ["MGM", "Kyle Freeland", 4.5, -140, 110]]), "ladder")
out = run(p)
if out and not any("T3" in x for x in out["rows"][0]["rejections"]):
    fails.append("3.0 K cross-book spread was not quarantined: %s" % out["rows"][0])

# ---- 6. short posted line is held to shadow unless overridden ----------------
p = drop_file(dict(date="2026-07-26", captured_utc="2026-07-26T19:13:00Z",
                   source_type="book_direct", source_note="opener zone",
                   quotes=[["DK", "Erick Fedde", 2.5, -140, 100]]), "short")
out = run(p)
if out and out["rows"][0]["play"] and out["rows"][0]["status"] == "REGISTERABLE":
    fails.append("a <=3.5 posted line registered without --allow-short-lines")

print("ingest_kquote regression:", "PASS" if not fails else "FAIL")
for f in fails:
    print("  ! " + f)
sys.exit(1 if fails else 0)
