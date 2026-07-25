#!/usr/bin/env python3
"""Exact grading for 2026-07-24. All arithmetic computed, never hand-done.
Grades: (A) ML directional tracking, (B) V13 side directional, (C) V13 total leans (display),
(D) K-projection accuracy on the sourced board, (E) the SHADOW play (no stake, not gate-eligible)."""
import json, math, os, sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "engine")
import kprops

def profit(price): return 100/abs(price) if price < 0 else price/100

# ---------- finals (statsapi schedule, 2026-07-24) ----------
FINAL = {  # away@home : (gamePk, away_runs, home_runs)
 "COL@MIL": (823759,5,2), "KC@DET": (824248,1,2), "CHC@PIT": (823352,3,2),
 "AZ@WSH": (822707,3,2),  "NYY@PHI": (823434,1,0), "ATL@BAL": (824812,7,6),
 "LAD@NYM": (823601,4,2), "CLE@TB": (822952,3,11), "SD@MIA": (823843,4,2),
 "TOR@BOS": (824733,4,6), "HOU@CWS": (824573,9,5), "SEA@TEX": (822872,4,5),
 "ATH@MIN": (823680,2,0), "CIN@STL": (823031,4,2), "LAA@SF": (823196,6,7)}

# ---------- starter K (statsapi boxscores, fields-filtered) ----------
KACT = {"Beck Way":0,"Tarik Skubal":12,"Cam Schlittler":12,"Jesús Luzardo":9,"Matthew Boyd":4,
 "Jared Jones":5,"Tomoyuki Sugano":5,"Shane Drohan":6,"Eduardo Rodriguez":4,"Carson Palmquist":1,
 "Grant Holmes":5,"Trevor Rogers":6,"Roki Sasaki":9,"Sean Manaea":3,"Joey Cantillo":4,
 "Shane McClanahan":3,"Germán Márquez":4,"Ryan Gusto":4,"Trey Yesavage":9,"Patrick Sandoval":3,
 "Davis Martin":3,"Spencer Arrighetti":0,"Bryce Miller":0,"MacKenzie Gore":5,"Jacob Lopez":4,
 "Zebby Matthews":1,"Rhett Lowder":4,"Dustin May":8,"Grayson Rodriguez":3,"Logan Webb":4}
IPACT = {"Beck Way":1.0,"Tarik Skubal":7.1,"Cam Schlittler":7.1,"Jesús Luzardo":7.0,"Matthew Boyd":7.0,
 "Jared Jones":6.0,"Tomoyuki Sugano":5.1,"Shane Drohan":6.0,"Eduardo Rodriguez":6.0,
 "Carson Palmquist":1.1,"Grant Holmes":5.0,"Trevor Rogers":7.0,"Roki Sasaki":7.0,"Sean Manaea":6.0,
 "Joey Cantillo":3.2,"Shane McClanahan":5.0,"Germán Márquez":2.1,"Ryan Gusto":3.1,"Trey Yesavage":4.0,
 "Patrick Sandoval":4.2,"Davis Martin":5.0,"Spencer Arrighetti":1.0,"Bryce Miller":5.1,
 "MacKenzie Gore":5.0,"Jacob Lopez":5.0,"Zebby Matthews":6.0,"Rhett Lowder":5.0,
 "Dustin May":6.0,"Grayson Rodriguez":4.0,"Logan Webb":6.0}

card = json.load(open("cards/2026-07-24_card.json"))
rows = {f"{r['away']}@{r['home']}": r for r in card["rows"]}

print("="*76); print("A. ML DIRECTIONAL TRACKING (display-only, $0 staked)"); print("="*76)
ML = [("NYY","NYY@PHI",112),("ATL","ATL@BAL",100),("SEA","SEA@TEX",-120)]
mw=ml_u=0
for pick,gm,price in ML:
    aw,hm = gm.split("@"); _,ar,hr = FINAL[gm]
    won = (ar>hr) if pick==aw else (hr>ar)
    pl = round(profit(price),2) if won else -1.00
    mw += won; ml_u += pl
    print(f"{pick:<4} {gm:<9} {price:>+5}  {ar}-{hr}  {'WIN ' if won else 'LOSS'}  {pl:+.2f}u")
print(f"  -> 7/24 ML tracking: {mw}-{len(ML)-mw}, {ml_u:+.2f}u")

print(); print("="*76); print("B. V13 SIDE DIRECTIONAL (all 15)"); print("="*76)
sw=sl=0
for gm,(gpk,ar,hr) in FINAL.items():
    r = rows[gm]; hwp = r["v13"]["home_wp"]
    lean = r["home"] if hwp>0.5 else r["away"]
    won = (hr>ar) if lean==r["home"] else (ar>hr)
    sw += won; sl += (not won)
    print(f"{gm:<9} V13 H% {hwp:.0%}  lean {lean:<4} final {ar}-{hr}  {'WIN' if won else 'LOSS'}")
print(f"  -> 7/24 V13 directional: {sw}-{sl}")

print(); print("="*76); print("C. V13 TOTAL LEANS (display-only, totals NOT_READY)"); print("="*76)
tw=tl=tp=0
for gm,(gpk,ar,hr) in FINAL.items():
    r = rows[gm]; line = r["lines"]["total"]; proj = r["v13"]["proj_total"]; act = ar+hr
    if line is None: continue
    lean = "OVER" if proj>line else "UNDER"
    if abs(proj-line) < 0.25: print(f"{gm:<9} line {line:<4} proj {proj:<5} act {act:<3} NO LEAN (|gap|<0.25)"); tp+=1; continue
    won = (act>line) if lean=="OVER" else (act<line)
    tw += won; tl += (not won)
    print(f"{gm:<9} line {line:<4} proj {proj:<5} act {act:<3} {lean:<5} {'WIN' if won else 'LOSS'}")
print(f"  -> 7/24 V13 total leans: {tw}-{tl} ({tp} no-lean)")

print(); print("="*76); print("D. K-PROJECTION ACCURACY — sourced board arms (as-of proj vs actual)"); print("="*76)
raw = json.load(open("data/mlb/props/2026-07-24_kboard.json")); raw.pop("_meta")
ids = kprops._ids()
errs=[]; naive=[]
for name in raw:
    p = kprops.proj(name, ids)
    key = next((k for k in KACT if kprops._norm(k)==kprops._norm(name)), None)
    if not p or key is None: print(f"{name:<20} (no projection or no actual) — excluded"); continue
    ek,gs = p; act = KACT[key]
    errs.append(abs(ek-act)); naive.append(abs(4.6-act))
    print(f"{name:<20} proj {ek:5.2f}  act {act:>2}  err {ek-act:+6.2f}  IP {IPACT.get(key,'?')}")
print(f"  -> n={len(errs)}  MAE {sum(errs)/len(errs):.2f}  vs naive(4.6) MAE {sum(naive)/len(naive):.2f}")

print(); print("="*76); print("E. SHADOW PLAY — NOT staked, NOT gate-eligible (post-slate capture)"); print("="*76)
sh = json.load(open("data/mlb/props/2026-07-24_kboard_shadow.json"))
su=0
for p in sh["shadow_plays"]:
    key = next(k for k in KACT if kprops._norm(k)==kprops._norm(p["pitcher"]))
    act = KACT[key]
    won = (act>p["line"]) if p["side"]=="OVER" else (act<p["line"])
    pl = round(profit(p["price"])*p["weight"],2) if won else -1.00*p["weight"]
    su += pl
    flag = f"   [disp {p['disp']:+.2f} -> R5 AUDIT REQUIRED]" if abs(p["disp"])>=1.5 else ""
    print(f"{p['pitcher']:<20} {p['side']} {p['line']} @{p['price']} ({p['book']})  proj {p['ek']}  "
          f"act {act}  {'WIN' if won else 'LOSS'}  {pl:+.2f}u{flag}")
print(f"  -> shadow: {su:+.2f}u  ** hypothetical only; ledger stays 4-5 / -1.61u, gate stays 9/100 **")
