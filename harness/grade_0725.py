#!/usr/bin/env python3
"""Grade 2026-07-25 from TWO independent sources that must agree.

Source A: user box-score paste, parsed locally (data/mlb/box/2026-07-25_raw.json)
Source B: statsapi hydrated schedule, fresh fetch (data/mlb/box/2026-07-25_statsapi.json)

Doctrine: 'Never grade from a single endpoint.' If A and B disagree on any of the
30 team scores, this script refuses to grade and exits non-zero.

Grades: ml_ev_tracking pending 7/25 rows, v13_forward_directional (15 games),
7/25 total leans. Emits a results.csv backfill block and a K-model calibration
table. Writes nothing to state.json - that is a separate, reviewed step.
"""
import json, sys, csv, unicodedata

def ascii_(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()

box = json.load(open("data/mlb/box/2026-07-25_raw.json"))
api = json.load(open("data/mlb/box/2026-07-25_statsapi.json"))
card = json.load(open("cards/2026-07-25_card.json"))

# ---- cross-source agreement gate -------------------------------------------
NAME2ABBR = {r["away_name"]: r["away"] for r in box["games"]}
NAME2ABBR.update({r["home_name"]: r["home"] for r in box["games"]})
# statsapi uses official club names; the paste uses the aggregator's rendering
ALIAS = {"Arizona Diamondbacks": "AZ", "Athletics": "ATH", "Chicago White Sox": "CWS",
         "Los Angeles Angels": "LAA", "San Francisco Giants": "SF"}

def abbr(name):
    if name in ALIAS: return ALIAS[name]
    if name in NAME2ABBR: return NAME2ABBR[name]
    for k, v in NAME2ABBR.items():
        if k.startswith(name) or name.startswith(k.rsplit(" ", 1)[0]): return v
    raise KeyError(name)

A = {"%s@%s" % (g["away"], g["home"]): (g["away_r"], g["home_r"]) for g in box["games"]}
B, PK = {}, {}
for g in api["games"]:
    k = "%s@%s" % (abbr(g["away_name"]), abbr(g["home_name"]))
    B[k] = (g["away_score"], g["home_score"])
    PK[k] = g["gamePk"]
    if g["status"] != "Final":
        print("REFUSE: %s is %s, not Final" % (k, g["status"])); sys.exit(1)

mismatch = [k for k in set(A) | set(B) if A.get(k) != B.get(k)]
if mismatch:
    for k in mismatch:
        print("REFUSE: %s paste=%s statsapi=%s" % (k, A.get(k), B.get(k)))
    sys.exit(1)
print("cross-source gate : PASS - %d games, %d team scores, 0 disagreements\n" % (len(A), 2 * len(A)))

FIN = A
def won(team, gk):
    a, h = gk.split("@"); ar, hr = FIN[gk]
    return (ar > hr) if team == a else (hr > ar)

def pl(ml, win):
    if not win: return -1.00
    return round(ml / 100.0, 2) if ml > 0 else round(100.0 / abs(ml), 2)

# ---- 1. ml_ev_tracking ------------------------------------------------------
state = json.load(open("state.json"))
led = state["ledgers"]["ml_ev_tracking"]
print("=== ml_ev_tracking (pre-registered, $0 staked, R3 sides DEAD) ===")
graded_now = []
for row in led["pending"]:
    if row["date"] != "2026-07-25": continue
    gk = row["game"]; w = won(row["pick"], gk)
    p = pl(row["ml"], w)
    graded_now.append(dict(row, final="%d-%d" % FIN[gk], gamePk=PK[gk],
                           result="WIN" if w else "LOSS", pl=p))
    print("  %-4s %+5d  %-9s final %-5s  %s  %+.2fu" %
          (row["pick"], row["ml"], gk, "%d-%d" % FIN[gk], "WIN " if w else "LOSS", p))
w0, l0, u0 = led["record_w"], led["record_l"], led["units"]
w1 = w0 + sum(1 for g in graded_now if g["result"] == "WIN")
l1 = l0 + sum(1 for g in graded_now if g["result"] == "LOSS")
u1 = round(u0 + sum(g["pl"] for g in graded_now), 2)
n = w1 + l1
print("  ledger: %d-%d was %+.2fu -> %d-%d %+.2fu   ROI %+.1f%% on %d plays" %
      (w0, l0, u0, w1, l1, u1, 100.0 * u1 / n, n))
print("  gate  : %d/100 graded K-prop plays. This ledger is ML, not K-props;"
      " it advances the gate by ZERO.\n" % 0)

# ---- 2. v13_forward_directional --------------------------------------------
print("=== v13_forward_directional (display-only side lean, no price) ===")
dw = dl = 0
for r in card["rows"]:
    gk = "%s@%s" % (r["away"], r["home"])
    lean = r["home"] if r["v13"]["home_wp"] >= 0.5 else r["away"]
    hit = won(lean, gk)
    dw, dl = dw + hit, dl + (not hit)
    print("  %-9s hwp %.3f -> %-4s  final %-5s  %s" %
          (gk, r["v13"]["home_wp"], lean, "%d-%d" % FIN[gk], "W" if hit else "L"))
fd = state["ledgers"]["v13_forward_directional"]
print("  slate %d-%d (%.1f%%); cumulative %d-%d -> %d-%d\n" %
      (dw, dl, 100.0 * dw / (dw + dl), fd["w"], fd["l"], fd["w"] + dw, fd["l"] + dl))

# ---- 3. total leans ---------------------------------------------------------
print("=== 7/25 total leans (advisory; totals remain NOT_READY) ===")
tw = tl = tp = 0
for r in card["rows"]:
    gk = "%s@%s" % (r["away"], r["home"])
    line = r["lines"].get("total"); lean = r.get("total_lean")
    if line is None or lean not in ("OVER", "UNDER"):
        print("  %-9s no lean" % gk); continue
    act = sum(FIN[gk])
    if act == line: res, tp = "PUSH", tp + 1
    elif (act > line) == (lean == "OVER"): res, tw = "W", tw + 1
    else: res, tl = "L", tl + 1
    print("  %-9s proj %4.1f  line %4.1f  %-5s  actual %2d  %s" %
          (gk, r["v13"]["proj_total"], line, lean, act, res))
print("  slate %d-%d-%d\n" % (tw, tl, tp))

# ---- 4. K-model calibration (exploratory, out-of-sample) --------------------
print("=== K-model calibration: pre-slate E[K] vs actual starter SO ===")
rows, unmatched = [], []
for r in card["rows"]:
    gk = "%s@%s" % (r["away"], r["home"])
    bg = next(g for g in box["games"] if "%s@%s" % (g["away"], g["home"]) == gk)
    for side, key, sp in (("away", "pitchers_away", "asp"), ("home", "pitchers_home", "hsp")):
        want = ascii_(r[sp]); arms = bg[key]
        if not arms: unmatched.append((gk, side, want, "no pitcher rows")); continue
        got = arms[0]
        if got["p"].lower() != want.lower():
            unmatched.append((gk, side, want, "box starter was " + got["p"])); continue
        ek = (r[sp + "_stats"] or {}).get("ek")
        if ek is None:
            unmatched.append((gk, side, want, "no pre-slate E[K] (insufficient GS)")); continue
        rows.append(dict(game=gk, pitcher=want, ek=ek, so=got["so"],
                         ip=got["ip"], capped=r["capped"]))
matched = len(rows)
if matched:
    err = [x["so"] - x["ek"] for x in rows]
    mae = sum(abs(e) for e in err) / matched
    bias = sum(err) / matched
    rmse = (sum(e * e for e in err) / matched) ** 0.5
    for x in sorted(rows, key=lambda z: -(z["so"] - z["ek"])):
        print("  %-9s %-22s E[K] %4.2f  actual %2d  IP %4.1f  err %+5.2f%s" %
              (x["game"], x["pitcher"], x["ek"], x["so"], x["ip"], x["so"] - x["ek"],
               "  (capped game)" if x["capped"] else ""))
    print("  n=%d  MAE %.2f  bias %+.2f (actual - projected)  RMSE %.2f" % (matched, mae, bias, rmse))
for u in unmatched:
    print("  ! unmatched: %s %s card=%s (%s)" % u)
print("  NOTE: exploratory only. No prices existed for these arms, so nothing here"
      "\n        is gate-eligible and no play was or could have been made.\n")

# ---- 5. results.csv backfill block ------------------------------------------
venue = {}
for row in csv.DictReader(open("data/backfill/mlb/2026/results.csv")):
    venue.setdefault(row["home"], set()).add(row["venue"])
out = []
for r in card["rows"]:
    gk = "%s@%s" % (r["away"], r["home"]); ar, hr = FIN[gk]
    v = venue.get(r["home"], set())
    out.append(dict(sport="mlb", season="2026", game_id="mlb:2026:%s" % PK[gk],
                    date="2026-07-25", status="final", away=r["away"], home=r["home"],
                    away_score=ar, home_score=hr, home_win=int(hr > ar), margin=hr - ar,
                    total=ar + hr, neutral_site=0,
                    venue=sorted(v)[-1] if len(v) == 1 else "",
                    close_ml_away=r["lines"]["ml_away"], close_ml_home=r["lines"]["ml_home"],
                    close_spread_home="", close_total=r["lines"]["total"],
                    features_json="", source="statsapi+box_paste(2-source)",
                    ingested_utc="2026-07-26T03:20:00Z"))
    if len(v) != 1:
        print("  ! venue ambiguous/missing for home=%s -> left blank (R1: never invent)" % r["home"])
json.dump(dict(ml_ev_graded=graded_now, ml_ev_new=dict(w=w1, l=l1, units=u1),
               directional=dict(w=dw, l=dl), totals=dict(w=tw, l=tl, p=tp),
               kcal=dict(n=matched, rows=rows, unmatched=unmatched),
               results_rows=out),
          open("data/mlb/box/2026-07-25_grades.json", "w"), indent=1)
print("wrote data/mlb/box/2026-07-25_grades.json (%d results rows staged)" % len(out))
