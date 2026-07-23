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


def select_play(quotes, ek, gs, min_edge=0.04, min_disp=0.8):
    """FIXED 7/23 v2 (Taco audit): qualify-then-best across ALL quotes, WITH sample gates enforced:
    gs<5 -> None (skip). Returns dict incl weight (0.5 if gs<10 else 1.0). Directional sanity:
    OVER requires positive displacement, UNDER negative."""
    if gs is None or gs<5: return None
    def imp(ml): return (-ml)/(-ml+100) if ml<0 else 100/(ml+100)
    quals=[]
    for book,line,pu,po in quotes:
        pov=p_over(ek,line)
        for side,p,price in (("OVER",pov,po),("UNDER",1-pov,pu)):
            if price is None: continue
            e=ev(p,price); edge=p-imp(price); disp=ek-line
            if e>0 and edge>=min_edge and abs(disp)>=min_disp and ((side=="OVER")==(disp>0)):
                quals.append((e,dict(book=book,line=line,side=side,price=price,p=round(p,3),
                                     edge=round(edge,3),ev=round(e,3),disp=round(disp,2),
                                     weight=0.5 if gs<10 else 1.0)))
    return max(quals,key=lambda x:x[0])[1] if quals else None

def price_board(board):
    """CANONICAL pregame pricing entry point — the pregame run calls THIS, nothing else.
    board: {pitcher_name: [(book,line,under,over),...]}. Returns (plays, evaluations)."""
    ids=_ids(); plays=[]; evals=[]
    for name,quotes in board.items():
        r=proj(name, ids)
        if not r:
            evals.append((name,None,None,"skip: no log or <5 GS")); continue
        ek,gs=r
        sel=select_play(quotes, ek, gs)
        evals.append((name,round(ek,2),gs, sel or "no qualifying quote"))
        if sel: plays.append(dict(pitcher=name, ek=round(ek,2), gs=gs, **sel))
    return plays, evals

if __name__=="__main__":
    # SELF-TEST (run by healthcheck): the Sale regression + gate enforcement
    fails=[]
    # 1. qualify-then-best: a non-qualifying high-EV quote must not mask a qualifying one
    q=[("FD",6.5,126,-162),("HR",7.5,-145,110)]
    s=select_play(q, ek=6.54, gs=20)
    if not s or s["line"]!=7.5 or s["side"]!="UNDER": fails.append(f"Sale regression: {s}")
    # 2. gs<5 -> None even with a monster edge
    if select_play([("DK",3.5,-140,110)], ek=6.0, gs=2) is not None: fails.append("gs<5 not skipped")
    # 3. gs<10 -> half weight
    s2=select_play([("DK",4.5,-119,-105)], ek=5.4, gs=7)
    if s2 and s2["weight"]!=0.5: fails.append(f"half-weight: {s2}")
    # 4. directional sanity: UNDER with positive displacement must not qualify
    s3=select_play([("DK",4.5,200,-300)], ek=5.6, gs=15)
    if s3 and s3["side"]=="UNDER": fails.append("directional sanity broken")
    print("kprops self-test:", "PASS" if not fails else f"FAIL {fails}")
    import sys; sys.exit(1 if fails else 0)
