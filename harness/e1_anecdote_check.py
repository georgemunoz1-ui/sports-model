#!/usr/bin/env python3
"""Would the E1 log5 opponent-K adjustment have 'repaired' the two motivating misses? Compute each
pitcher's as-of shrunk K-rate + E[TBF] from his log, apply the frozen log5 formula with his actual
opponent's K-rate, and check whether the DECISION (side vs line) would have flipped. If the two
anecdotes don't even flip, the feature cannot be justified by them — only by broad replay merit."""

MODULE_ID = "e1_anecdote_check"
import json, os
LG_KRATE=.22; LG_TBF=24.0
team=json.load(open("data/mlb/team_batting_asof/2026-07-23.json")); L=team["league_k_rate"]
def sp_asof(pid, upto):
    s_so=s_tbf=st=0.0
    for ln in open(f"data/backfill/mlb/2026/pitcher_logs/{pid}.txt"):
        p=ln.strip().split("|")
        if len(p)>=10: d=(p[0],float(p[6]),float(p[8]),p[9]=="1")
        elif len(p)>=7: d=(p[0],float(p[3]),float(p[5]),p[6]=="1")
        else: continue
        if d[0]>=upto: continue          # strict as-of: only starts BEFORE the game
        if d[3]: st+=1; s_so+=d[1]; s_tbf+=d[2]
    krate=(s_so+LG_KRATE*80)/(s_tbf+80); etbf=(s_tbf+LG_TBF*3)/(st+3)
    return krate, etbf, int(st)
def log5(p,o,l):
    a=p*o/l; b=(1-p)*(1-o)/(1-l); return a/(a+b)
def poisson_p_under(lam, line):  # P(K < ceil(line)) = P(under a .5 line)
    from math import exp, factorial
    k0=int(line)  # for x.5 line, under means <= k0
    return sum(exp(-lam)*lam**i/factorial(i) for i in range(k0+1))

cases=[("Gerrit Cole","543037","2026-07-22","PIT","UNDER",6.5,11),
       ("Chris Sale","519242","2026-07-23","SD","UNDER",7.5,11)]
print(f"League K-rate {L:.3f}\n")
for name,pid,date,opp,side,line,actual in cases:
    p,etbf,gs=sp_asof(pid,date); o=team["teams"][opp]["k_rate"]
    ek_base=p*etbf
    adj=log5(p,o,L); ek_adj=adj*etbf
    dU_base=line-ek_base; dU_adj=line-ek_adj
    # decision: UNDER fires if displacement (line-proj) >= 0.8
    fire_base = dU_base>=0.8; fire_adj = dU_adj>=0.8
    print(f"{name} vs {opp} ({o*100:.1f}% K, {'+' if o>=L else ''}{(o-L)*100:.1f} vs lg):")
    print(f"  as-of: K-rate {p*100:.1f}% -> log5 {adj*100:.1f}% ({'+' if adj>=p else ''}{(adj-p)*100:.2f}pp) | E[TBF] {etbf:.1f}, {gs} GS")
    print(f"  E[K]: baseline {ek_base:.2f} -> E1 {ek_adj:.2f} (Δ {ek_adj-ek_base:+.2f}K); line {line} {side}; actual {actual}")
    print(f"  UNDER displacement: {dU_base:+.2f} -> {dU_adj:+.2f} | play fires? base={fire_base} E1={fire_adj} | flipped? {fire_base!=fire_adj}\n")
