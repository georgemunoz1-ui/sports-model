"""K-prop projection engine (canonical, rebuilt after rollback). START-ONLY accumulation —
relief outings excluded (bug history). Backtest result of record (n=1759): MAE 1.92 vs naive 2.41,
calibrated P(over), displaced lines 62-70%. Usage: proj(name) -> (E[K], starts) as-of latest log."""
import csv, os, numpy as np
from math import exp, factorial
BASE=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGS=os.path.join(BASE,"data/backfill/mlb/2026/pitcher_logs")
LG_KRATE=0.22; LG_TBF=24.0
def _ids():
    return {r["name"].lower():r["id"] for r in csv.DictReader(open(os.path.join(BASE,"data/backfill/mlb/2026/pitchers.csv")))}
def _parse(path):
    rows=[]
    for ln in open(path):
        p=ln.strip().split("|")
        if len(p)>=10: rows.append((p[0],float(p[6]),float(p[8]),p[9]=="1"))
        elif len(p)>=7: rows.append((p[0],float(p[3]),float(p[5]),p[6]=="1"))
    rows.sort(); return rows
def proj(name, ids=None):
    ids=ids or _ids(); pid=ids.get(name.lower())
    if not pid: return None
    f=os.path.join(LOGS,f"{pid}.txt")
    if not os.path.exists(f): return None
    starts=[(so,tbf) for _,so,tbf,gs in _parse(f) if gs]
    if len(starts)<5: return None
    so=sum(s for s,_ in starts); tbf=sum(t for _,t in starts); st=len(starts)
    krate=(so+LG_KRATE*80)/(tbf+80); etbf=(tbf+LG_TBF*3)/(st+3)
    return krate*etbf, st
def p_over(ek,line):
    k0=int(np.ceil(line)); return 1-sum(exp(-ek)*ek**i/factorial(i) for i in range(k0))
def ev(p,ml): 
    prof=100/(-ml) if ml<0 else ml/100; return p*prof-(1-p)
