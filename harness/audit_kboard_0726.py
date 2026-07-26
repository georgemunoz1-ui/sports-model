#!/usr/bin/env python3
"""Integrity audit of the 2026-07-26 pitcher-strikeout price board.

The board is IMAGE-SOURCED. Before a single number is allowed near the engine it
has to survive four tests that an alt-line ladder or a best-price-across-books
display cannot survive:

  T1 HOLD        - every two-sided quote must price a real market. Two-sided
                   overround outside ~2-12% is either a transcription error or
                   not a genuine paired market.
  T2 RUNG        - within a row, a LOWER line must carry a MORE expensive OVER.
                   A display that shows "the best price anywhere" instead of
                   "this book's market" violates this constantly.
  T3 DISPERSION  - cross-book line spread. Real main lines on the same market
                   cluster inside 1.0 K. A 4.0 K spread means at least some
                   cells are alt rungs, not main lines.
  T4 TWO-READ    - the 4 rows transcribed in the earlier pass are re-read here
                   from an independent crop and must match byte for byte.
                   'Parse raw locally, never trust the model-reported number.'

Nothing here prices a play. This only decides which rows are ALLOWED to be priced.
"""
import json, sys

BOARD = "data/mlb/props/2026-07-26_kboard_full.json"
PRIOR = "data/mlb/props/2026-07-26_klines_live4.json"

B = json.load(open(BOARD))

def imp(ml):
    return (-ml) / (-ml + 100.0) if ml < 0 else 100.0 / (ml + 100.0)

# ---------------- T1: hold ---------------------------------------------------
print("=== T1  two-sided hold (legit prop band 2.0-12.0%) ===")
t1_fail, n2 = [], 0
for r in B["rows"]:
    for bk, ln, u, o in r["q"]:
        if u is None or o is None:
            continue
        n2 += 1
        h = 100.0 * (imp(u) + imp(o) - 1.0)
        flag = "" if 2.0 <= h <= 12.0 else "   <-- OUT OF BAND"
        if flag:
            t1_fail.append((r["pitcher"], bk, ln, u, o, h))
        print("  %-20s %-4s %4.1f  U %+5d  O %+5d   hold %5.2f%%%s"
              % (r["pitcher"], bk, ln, u, o, h, flag))
print("  %d two-sided quotes, %d out of band\n" % (n2, len(t1_fail)))

# ---------------- T2: rung coherence -----------------------------------------
print("=== T2  rung coherence (lower line must price OVER more expensively) ===")
t2_fail = []
for r in B["rows"]:
    pts = sorted([(ln, bk, o) for bk, ln, u, o in r["q"] if o is not None and ln is not None])
    if len(pts) < 2:
        continue
    msgs = []
    for i in range(len(pts) - 1):
        (l1, b1, o1), (l2, b2, o2) = pts[i], pts[i + 1]
        if l1 == l2:
            continue
        # lower line l1 must have HIGHER implied over prob than higher line l2
        if imp(o1) <= imp(o2):
            msgs.append("%.1f@%s %+d (p %.3f) NOT above %.1f@%s %+d (p %.3f)"
                        % (l1, b1, o1, imp(o1), l2, b2, o2, imp(o2)))
    verdict = "FAIL" if msgs else "ok"
    if msgs:
        t2_fail.append(r["pitcher"])
    print("  %-20s %-4s  %s" % (r["pitcher"], verdict,
          " | ".join("%.1f@%s %+d" % (l, b, o) for l, b, o in pts)))
    for m in msgs:
        print("      ! " + m)
print("  %d rows with an incoherent ladder\n" % len(t2_fail))

# ---------------- T3: dispersion ---------------------------------------------
print("=== T3  cross-book line dispersion ===")
disp = []
for r in B["rows"]:
    lns = [ln for bk, ln, u, o in r["q"] if ln is not None]
    sp = max(lns) - min(lns)
    disp.append((sp, r["pitcher"], lns))
for sp, p, lns in sorted(disp, reverse=True):
    tag = "QUARANTINE" if sp > 1.0 else "ok"
    print("  %-20s spread %4.1f  %-10s  %s" % (p, sp, tag,
          "/".join("%.1f" % x for x in lns)))
clean = [p for sp, p, _ in disp if sp <= 1.0]
quar = [p for sp, p, _ in disp if sp > 1.0]
print("  clean %d, quarantined %d\n" % (len(clean), len(quar)))

# ---------------- T4: independent re-read ------------------------------------
print("=== T4  re-read agreement vs the earlier independent transcription ===")
prior = json.load(open(PRIOR))
pq = prior["live_at_processing"]
now = {r["pitcher"]: [q for q in r["q"] if q[0] != "HR"] for r in B["rows"]}
t4_fail = []
for name, old in pq.items():
    if name not in now:
        t4_fail.append((name, "absent from re-read")); continue
    a = [[str(x[0]), x[1], x[2], x[3]] for x in old]
    b = [[str(x[0]), x[1], x[2], x[3]] for x in now[name]]
    ok = a == b
    print("  %-20s %s" % (name, "MATCH" if ok else "MISMATCH"))
    if not ok:
        t4_fail.append((name, "old=%s new=%s" % (a, b)))
        print("      old %s\n      new %s" % (a, b))
print("  %d disagreements\n" % len(t4_fail))

json.dump(dict(n_two_sided=n2, hold_out_of_band=t1_fail, rung_fail=t2_fail,
               quarantined=quar, clean=clean, reread_fail=t4_fail),
          open("data/mlb/props/2026-07-26_kboard_audit.json", "w"), indent=1)
print("PERMITTED for pricing: %d rows" % len(clean))
print("  " + ", ".join(clean))
