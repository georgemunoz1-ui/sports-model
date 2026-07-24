#!/usr/bin/env python3
"""BUILD the E1 replay table (task 20). Refuses to run unless the reconciliation GATE passes.
For every start (start-only accumulation) computes: as-of pitcher shrunk K-rate p + E[TBF] (prior
starts, date<D), opponent as-of K-rate o = (SigmaSO + L*200)/(Sigma(AB+BB) + 200) with strict date<D
(DH=start-of-day both), as-of league L, baseline E[K]=p*etbf, and E1 E[K]=log5(p,o,L)*etbf.
Freezes to data/mlb/e1_replay_table.csv. Quarantines starts whose opponent can't be resolved."""
import csv, glob, os, sys, json
import e1_data as E
BASE=E.BASE; os.chdir(BASE)
LG_KRATE=0.22; KP=80; TBFP0=24.0; TBFP_N=3; N0=200.0

ok,_,_=E.gate_ok(verbose=False)
if not ok:
    print("GATE NOT PASSED — refusing to build replay table."); sys.exit(1)

# ---- team as-of cumulative (sorted by date; strict date<D) ----
team_games={}  # abbr -> sorted list of (date, so, abbb)
for abbr in E.TEAMID.values():
    rows=E.parse_team_file(abbr)
    team_games[abbr]=sorted(((r["date"],r["so"],r["ab"]+r["bb"]) for r in rows))
# league as-of: merge all games
all_games=sorted((g for gs in team_games.values() for g in gs))
def cum_before(games, D):
    so=ab=0
    for d,s,a in games:
        if d>=D: break
        so+=s; ab+=a
    return so,ab
def league_L(D):
    so,ab=cum_before(all_games,D)
    return so/ab if ab>0 else LG_KRATE
def opp_o(opp,D,L):
    games=team_games.get(opp)
    if games is None: return None
    so,ab=cum_before(games,D)
    return (so+L*N0)/(ab+N0)   # ab=0 -> o=L (no info -> no adjustment)

def log5(p,o,L):
    a=p*o/L; b=(1-p)*(1-o)/(1-L); return a/(a+b)

# ---- (pid,date) -> opponent from starters.csv ----
opp_map={}
for ln in open("data/backfill/mlb/2026/starters.csv"):
    r=ln.rstrip("\n").split("|")   # starters.csv is PIPE-delimited
    if r[0]=="gamePk" or len(r)<8: continue
    gpk,date,away,home,ven,aspid,aspn,hspid=r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7]
    if aspid: opp_map[(aspid,date)]=E.canon(home)
    if hspid: opp_map[(hspid,date)]=E.canon(away)

def parse_start(p):
    if len(p)>=10: return dict(date=p[0],opp=E.canon(p[2]),so=float(p[6]),tbf=float(p[8]),gs=p[9]=="1")
    if len(p)>=7:  return dict(date=p[0],opp=None,so=float(p[3]),tbf=float(p[5]),gs=p[6]=="1")
    return None

rows=[]; quarantine=[]; n_zeroprior=0
for f in glob.glob("data/backfill/mlb/2026/pitcher_logs/*.txt"):
    pid=os.path.basename(f)[:-4]
    log=[]
    for ln in open(f):
        d=parse_start(ln.strip().split("|"))
        if d: log.append(d)
    log.sort(key=lambda x:x["date"])
    cum_so=cum_tbf=n=0  # start-only prior accumulation
    for d in log:
        if not d["gs"]:
            continue  # relief: skip entirely (engine start-only)
        if n>=1:  # need >=1 prior start for as-of signal
            p=(cum_so+LG_KRATE*KP)/(cum_tbf+KP)
            etbf=(cum_tbf+TBFP0*TBFP_N)/(n+TBFP_N)
            opp=d["opp"] or opp_map.get((pid,d["date"]))
            if opp is None:
                quarantine.append((pid,d["date"],"unresolved-opponent"))
            else:
                L=league_L(d["date"]); o=opp_o(opp,d["date"],L)
                if o is None:
                    quarantine.append((pid,d["date"],f"unmatched-team:{opp}"))
                else:
                    ek_base=p*etbf; ek_e1=log5(p,o,L)*etbf
                    rows.append(dict(date=d["date"],pid=pid,opp=opp,actual=int(d["so"]),
                        n_prior=n,p_asof=round(p,4),etbf=round(etbf,3),o=round(o,4),L=round(L,4),
                        ek_base=round(ek_base,4),ek_e1=round(ek_e1,4),
                        premium=int(p>=0.27),highk=int(o>=0.24)))
        else:
            n_zeroprior+=1
        cum_so+=d["so"]; cum_tbf+=d["tbf"]; n+=1

rows.sort(key=lambda r:(r["date"],r["pid"]))
cols=["date","pid","opp","actual","n_prior","p_asof","etbf","o","L","ek_base","ek_e1","premium","highk"]
with open("data/mlb/e1_replay_table.csv","w",newline="") as fh:
    w=csv.DictWriter(fh,fieldnames=cols); w.writeheader(); w.writerows(rows)

print(f"replay table: {len(rows)} starts (excluded {n_zeroprior} zero-prior first starts)")
print(f"  premium-K arms (p>=27%): {sum(r['premium'] for r in rows)} | high-opp-K (o>=24%): {sum(r['highk'] for r in rows)}"
      f" | interaction: {sum(r['premium']*r['highk'] for r in rows)}")
print(f"  QUARANTINED (excluded, never league-avg-substituted): {len(quarantine)}")
for q in quarantine[:8]: print("   ",q)
json.dump(quarantine,open("data/mlb/e1_quarantine.json","w"),indent=1)
print("frozen -> data/mlb/e1_replay_table.csv")
