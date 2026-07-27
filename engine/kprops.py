"""K-prop projection engine (canonical, rebuilt after rollback). START-ONLY accumulation —
relief outings excluded (bug history). Backtest result of record (n=1759): MAE 1.92 vs naive 2.41,
calibrated P(over), displaced lines 62-70%. Usage: proj(name) -> (E[K], starts) as-of latest log."""
import csv, os, unicodedata, numpy as np
from math import exp, factorial
BASE=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGS=os.path.join(BASE,"data/backfill/mlb/2026/pitcher_logs")
LG_KRATE=0.22; LG_TBF=24.0
def _norm(s):
    """Accent-insensitive key (fixed 2026-07-25, same defect class as daily_card.py 10596a3:
    a board listing 'Jesus Luzardo' must resolve to DB 'Jesús Luzardo', not silently skip)."""
    return unicodedata.normalize("NFKD",(s or "")).encode("ascii","ignore").decode().lower().strip()
def _ids():
    return {_norm(r["name"]):r["id"] for r in csv.DictReader(open(os.path.join(BASE,"data/backfill/mlb/2026/pitchers.csv")))}
def _parse(path):
    rows=[]
    for ln in open(path):
        p=ln.strip().split("|")
        if len(p)>=10: rows.append((p[0],float(p[6]),float(p[8]),p[9]=="1"))
        elif len(p)>=7: rows.append((p[0],float(p[3]),float(p[5]),p[6]=="1"))
    rows.sort(); return rows
def proj(name, ids=None):
    ids=ids or _ids(); pid=ids.get(_norm(name))
    if not pid: return None
    f=os.path.join(LOGS,f"{pid}.txt")
    if not os.path.exists(f): return None
    starts=[(so,tbf) for _,so,tbf,gs in _parse(f) if gs]
    if len(starts)<5: return None
    so=sum(s for s,_ in starts); tbf=sum(t for _,t in starts); st=len(starts)
    krate=(so+LG_KRATE*80)/(tbf+80); etbf=(tbf+LG_TBF*3)/(st+3)
    return krate*etbf, st
def _pmf(ek,k): return exp(-ek)*ek**k/factorial(k)
def probs(ek,line):
    """FIXED 7/27 (Taco audit) — PUSH-TERM-MISSING. Returns (p_over, p_push, p_under).

    Half-point line (e.g. 4.5): no push is possible. OVER wins on X>=5, UNDER on X<=4.
    INTEGER line (e.g. 5.0): X==5 is a PUSH — stake returned, neither side wins.
    The old p_over() returned P(X >= ceil(line)) unconditionally, which on an integer
    line is P(X>=5) and scores the push as an OVER win. At ek=5.00 that is 17.55% of
    outcomes priced wrong; at ek=5.68 on a 6 line, 15.92%."""
    if abs(line-round(line))<1e-9:
        L=int(round(line))
        pp=_pmf(ek,L); pu=sum(_pmf(ek,i) for i in range(L))
        return 1.0-pp-pu, pp, pu
    k0=int(np.ceil(line)); pu=sum(_pmf(ek,i) for i in range(k0))
    return 1.0-pu, 0.0, pu
def p_over(ek,line):
    """True P(OVER wins). On an integer line this now EXCLUDES the push — it is no longer
    P(X >= ceil(line)). Callers that price a bet must use probs() and carry p_push."""
    return probs(ek,line)[0]
def ev(p,ml,p_push=0.0):
    """EV per unit staked with a three-outcome settlement. A push returns the stake and
    contributes 0. p is P(win); P(lose) = 1 - p - p_push. p_push=0 reproduces the old
    two-outcome form exactly, so every half-point line is unchanged."""
    prof=100/(-ml) if ml<0 else ml/100; return p*prof-(1.0-p-p_push)


def select_play(quotes, ek, gs, min_edge=0.04, min_disp=0.8):
    """FIXED 7/23 v2 (Taco audit): qualify-then-best across ALL quotes, WITH sample gates enforced:
    gs<5 -> None (skip). Returns dict incl weight (0.5 if gs<10 else 1.0). Directional sanity:
    OVER requires positive displacement, UNDER negative."""
    if gs is None or gs<5: return None
    def imp(ml): return (-ml)/(-ml+100) if ml<0 else 100/(ml+100)
    quals=[]
    for book,line,pu,po in quotes:
        pov,ppush,pund=probs(ek,line)
        for side,p,price in (("OVER",pov,po),("UNDER",pund,pu)):
            if price is None: continue
            e=ev(p,price,ppush)
            # Break-even on a push-eligible bet is p/(p+p_lose) vs implied, i.e. the
            # probability CONDITIONAL on the bet actually settling. On a half-point line
            # p_push=0 and this is identical to the old p - imp(price).
            live=1.0-ppush
            edge=(p/live if live>0 else 0.0)-imp(price); disp=ek-line
            if e>0 and edge>=min_edge and abs(disp)>=min_disp and ((side=="OVER")==(disp>0)):
                quals.append((e,dict(book=book,line=line,side=side,price=price,p=round(p,3),
                                     edge=round(edge,3),ev=round(e,3),disp=round(disp,2),
                                     p_push=round(ppush,3),
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
    # 5. PUSH GUARD (added 7/27). Half-point lines must be unchanged: p_push=0 and the
    #    three probabilities must be the old two-outcome split exactly.
    po,pp,pu=probs(5.0,4.5)
    if pp!=0.0 or abs(po+pu-1.0)>1e-12: fails.append(f"half-point line gained a push: {(po,pp,pu)}")
    if abs(po-(1-sum(exp(-5.0)*5.0**i/factorial(i) for i in range(5))))>1e-12:
        fails.append("half-point P(over) drifted from the pre-fix value")
    # 6. Integer line must carve out the push, and the three must sum to 1.
    po,pp,pu=probs(5.0,5.0)
    if abs(pp-_pmf(5.0,5))>1e-12: fails.append(f"integer push mass wrong: {pp}")
    if abs(pp-0.175467)>1e-5: fails.append(f"P(X=5|5.00) should be ~0.17547, got {pp}")
    if abs(po+pp+pu-1.0)>1e-12: fails.append("integer probs do not sum to 1")
    if po>=1-sum(_pmf(5.0,i) for i in range(5))-1e-12:
        fails.append("integer P(over) did not shrink — push still counted as a win")
    # 7. ev() must treat a push as stake returned, and must be back-compatible at p_push=0.
    if abs(ev(0.5,-110)-(0.5*(100/110)-0.5))>1e-12: fails.append("ev back-compat broken")
    if abs(ev(0.4,+100,0.2)-(0.4*1.0-0.4))>1e-12: fails.append("ev push term wrong")
    # 8. A bet that is a coin flip among LIVE outcomes has zero edge at a fair price,
    #    regardless of how much push mass sits beside it.
    if abs(ev(0.4,+100,0.2))>1e-12: fails.append("fair push-eligible bet not EV-neutral")
    print("kprops self-test:", "PASS" if not fails else f"FAIL {fails}")
    import sys; sys.exit(1 if fails else 0)
