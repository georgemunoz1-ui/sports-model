#!/usr/bin/env python3
"""Append 7/23 actual start rows (7-field: date|IP|ER|SO|BB|TBF|GS — the format both parsers accept;
the runbook's 8-field opp-first spec BREAKS sp_asof, tracked as a known issue). Correct Sale's
pre-filled placeholder row to actuals. TBF = 3*outs + H + BB (HBP/ROE negligible for accumulation)."""
import os
D="data/backfill/mlb/2026/pitcher_logs"
# id : (date, IP, ER, SO, BB, TBF, GS)  — verified from Savant box scores 7/23
ROWS={
 "693855":("2026-07-23","6.0","2","7","1","24","1"),   # Ian Seymour (TB) 6IP 5H 1BB
 "668909":("2026-07-23","7.0","0","11","0","23","1"),  # Gavin Williams (CLE) 7IP 2H 0BB
 "671737":("2026-07-23","7.0","1","5","3","26","1"),   # Taj Bradley (MIN) 7IP 2H 3BB
 "700241":("2026-07-23","6.1","4","3","3","29","1"),   # Michael McGreevy (STL) 19 outs 7H 3BB
 "677976":("2026-07-23","5.0","0","3","1","20","1"),   # Randy Dobnak (KC) 5IP 4H 1BB
 "694297":("2026-07-23","6.0","2","1","2","27","1"),   # Brandon Pfaadt (AZ) 6IP 7H 2BB
 "669456":("2026-07-23","7.0","1","3","0","24","1"),   # Shane Bieber (TOR) 7IP 3H 0BB
 "675512":("2026-07-23","5.0","2","5","4","24","1"),   # Troy Melton (DET) 5IP 5H 4BB
 "656288":("2026-07-23","2.2","4","4","0","13","1"),   # Griffin Canning (SD) 8 outs 5H 0BB
}
for pid,r in ROWS.items():
    f=f"{D}/{pid}.txt"
    if not os.path.exists(f): print(f"  MISSING {pid}"); continue
    if any("2026-07-23" in ln for ln in open(f)): print(f"  {pid} already has 7/23 — skip"); continue
    with open(f,"a") as fh: fh.write("|".join(r)+"\n")
    print(f"  appended {pid}: {'|'.join(r)}")

# --- correct Sale placeholder (3.2|3|7|1|17 -> actual 6.0|3|11|1|24) ---
sf=f"{D}/519242.txt"
lines=open(sf).read().splitlines()
for i,ln in enumerate(lines):
    if ln.startswith("2026-07-23"):
        lines[i]="2026-07-23|6.0|3|11|1|24|1"; print(f"  Sale 7/23 corrected -> {lines[i]}")
open(sf,"w").write("\n".join(lines)+"\n")

# --- recount Sale season (GS/SO/TBF) for sanity vs external 18GS/123SO pre-7/23 ---
gs=so=tbf=0
for ln in open(sf):
    p=ln.strip().split("|")
    if len(p)==7 and p[6]=="1": gs+=1; so+=float(p[3]); tbf+=float(p[5])
    elif len(p)>=10 and p[9]=="1": gs+=1; so+=float(p[6]); tbf+=float(p[8])
print(f"  Sale season now: {gs} GS, {int(so)} SO, {int(tbf)} TBF (external pre-7/23 was 18GS/123SO; +11 tonight -> expect 19GS/134SO)")
