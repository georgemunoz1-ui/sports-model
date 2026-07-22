#!/usr/bin/env python3
"""Session-start integrity gate. Run BEFORE any work. Exit 0 = healthy. Mechanically enforces
what can be enforced (Anthropic/OpenAI harness pattern: rules as tooling, not vibes)."""
import csv, json, os, sys, glob, datetime
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
fails=[]; warns=[]
def check(name, ok, warn=False):
    tag = "OK " if ok else ("WARN" if warn else "FAIL")
    print(f"[{tag}] {name}")
    if not ok:
        (warns if warn else fails).append(name)

# 1. core files exist
for f in ["state.json","AGENTS.md","AUTHORIZATIONS.md","harness/runbook.md",
          "data/backfill/mlb/2026/results.csv","data/backfill/mlb/2026/park_factors.json"]:
    check(f"exists: {f}", os.path.exists(f))
# 2. state.json parses + invariants
try:
    st=json.load(open("state.json"))
    check("state.json parses", True)
    check("real money still 0 / unauthorized", st["ledgers"]["real_money"]["risked"]==0.0 and not st["ledgers"]["real_money"]["authorized"], warn=True)
    check("sides verdict still DEAD (R3)", st["verdicts"]["mlb_sides"]["status"]=="DEAD", warn=True)
except Exception as e:
    check(f"state.json parses ({e})", False)
# 3. results.csv integrity
try:
    rows=list(csv.DictReader(open("data/backfill/mlb/2026/results.csv")))
    ids=[r["game_id"] for r in rows]
    finals=[r for r in rows if r["status"]=="final"]
    check(f"results.csv rows={len(rows)} finals={len(finals)} (>=1505)", len(finals)>=1505)
    check("no duplicate game_ids", len(ids)==len(set(ids)))
    bad=[r for r in finals if r["home_win"] not in ("0","1") or r["total"]=="" ]
    check("all finals have home_win+total", len(bad)==0)
    last=max(r["date"] for r in finals)
    days_stale=(datetime.date.today()-datetime.date.fromisoformat(last)).days
    check(f"dataset freshness: last final {last} ({days_stale}d old)", days_stale<=2, warn=True)
except Exception as e:
    check(f"results.csv readable ({e})", False)
# 4. pitcher logs cache
n=len(glob.glob("data/backfill/mlb/2026/pitcher_logs/*.txt"))
check(f"pitcher_logs cached: {n} (>=310)", n>=310)
# 5. ledger consistency: pending plays graded?
try:
    lp=st["ledgers"]["kprops_paper"]
    pend=[p for p in lp.get("plays_pending",[]) if p["date"]<str(datetime.date.today())]
    check(f"kprop pending plays from past dates: {len(pend)} (grade them!)", len(pend)==0, warn=True)
except Exception: pass
# 6. progress journal fresh
if os.path.exists("docs/progress.md"):
    mtime=datetime.date.fromtimestamp(os.path.getmtime("docs/progress.md"))
    check(f"progress.md last touched {mtime}", (datetime.date.today()-mtime).days<=2, warn=True)
else: check("docs/progress.md exists", False, warn=True)
print(f"\n{'HEALTHY' if not fails else 'UNHEALTHY'} — {len(fails)} fail, {len(warns)} warn")
if fails: print("Fix FAILs before new work:", fails)
sys.exit(1 if fails else 0)
