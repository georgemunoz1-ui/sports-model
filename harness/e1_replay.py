#!/usr/bin/env python3
"""BUILD the E1 replay (task 20, v2 — paired on the experiment-of-record population).
Population of record = engine-eligible starts: n_prior_starts >= 5 (kprops.proj returns None below 5)
AND date <= 2026-07-19 (the horizon at which the n=1759 record was set). Post-horizon resolvable
starts go to the CONSTRUCTION table only, never the score. Opponent+gamePk resolved via starters.csv,
then 10-field log opp, then pitcher-team+results.csv fallback, so NO eligible row is quarantined.
row_id = pitcher_id|gamePk (Taco join key). Baseline formula UNCHANGED; E1 adds only opponent-K."""
import csv, glob, os, sys, json
import e1_data as E
BASE=E.BASE; os.chdir(BASE)
LG_KRATE=0.22; KP=80; TBFP0=24.0; TBFP_N=3; N0=200.0
HORIZON="2026-07-19"; MIN_PRIOR=5

ok,_,_=E.gate_ok(verbose=False)
if not ok: print("GATE NOT PASSED — abort."); sys.exit(1)

# team as-of cumulative
team_games={a:sorted(((r["date"],r["so"],r["ab"]+r["bb"]) for r in E.parse_team_file(a))) for a in E.TEAMID.values()}
all_games=sorted(g for gs in team_games.values() for g in gs)
def cum_before(games,D):
    so=ab=0
    for d,s,a in games:
        if d>=D: break
        so+=s; ab+=a
    return so,ab
def league_L(D):
    so,ab=cum_before(all_games,D); return so/ab if ab>0 else LG_KRATE
def opp_o(opp,D,L):
    g=team_games.get(opp)
    if g is None: return None
    so,ab=cum_before(g,D); return (so+L*N0)/(ab+N0)
def log5(p,o,L):
    a=p*o/L; b=(1-p)*(1-o)/(1-L); return a/(a+b)

# ---- resolvers from starters.csv (pipe-delimited) ----
opp_start={}; pid_team={}
for ln in open("data/backfill/mlb/2026/starters.csv"):
    r=ln.rstrip("\n").split("|")
    if r[0]=="gamePk" or len(r)<8: continue
    gpk,date,away,home,ven,aspid,aspn,hspid=r[0],r[1],E.canon(r[2]),E.canon(r[3]),r[4],r[5],r[6],r[7]
    if aspid: opp_start[(aspid,date)]=(home,gpk); pid_team.setdefault(aspid,set()).add(away)
    if hspid: opp_start[(hspid,date)]=(away,gpk); pid_team.setdefault(hspid,set()).add(home)
# results index for gamePk + fallback
res_by_date={}
for r in csv.DictReader(open("data/backfill/mlb/2026/results.csv")):
    gpk=r["game_id"].split(":")[-1]
    res_by_date.setdefault(r["date"],[]).append((gpk,E.canon(r["away"]),E.canon(r["home"])))

def resolve(pid,date,log_team,log_opp):
    if (pid,date) in opp_start: return opp_start[(pid,date)]          # 1. starters.csv
    if log_opp and log_team:                                          # 2. 10-field log opp -> gpk via results
        for gpk,a,h in res_by_date.get(date,[]):
            if {a,h}=={log_team,log_opp}: return (log_opp,gpk)
        return (log_opp,None)
    for T in pid_team.get(pid,()):                                    # 3. pitcher-team + results fallback
        cand=[(gpk,(h if a==T else a)) for gpk,a,h in res_by_date.get(date,[]) if T in (a,h)]
        opps={o for _,o in cand}
        if len(opps)==1:  # single game OR same-opponent doubleheader -> opp unambiguous; pick min gamePk
            return (cand[0][1], min(g for g,_ in cand))
    return (None,None)

def parse_start(p):
    if len(p)>=10: return dict(date=p[0],team=E.canon(p[1]),opp=E.canon(p[2]),so=float(p[6]),tbf=float(p[8]),gs=p[9]=="1")
    if len(p)>=7:  return dict(date=p[0],team=None,opp=None,so=float(p[3]),tbf=float(p[5]),gs=p[6]=="1")
    return None

allrows=[]; qutimeline=[]
for f in glob.glob("data/backfill/mlb/2026/pitcher_logs/*.txt"):
    pid=os.path.basename(f)[:-4]
    log=sorted((d for d in (parse_start(ln.strip().split("|")) for ln in open(f)) if d), key=lambda x:x["date"])
    cs=ct=n=0
    for d in log:
        if not d["gs"]: continue
        if n>=1:
            p=(cs+LG_KRATE*KP)/(ct+KP); etbf=(ct+TBFP0*TBFP_N)/(n+TBFP_N)
            opp,gpk=resolve(pid,d["date"],d["team"],d["opp"])
            rec=dict(pid=pid,date=d["date"],gamePk=gpk,opp=opp,actual=int(d["so"]),n_prior=n,
                     p_asof=round(p,4),etbf=round(etbf,3),ek_base=round(p*etbf,4))
            if opp is not None:
                L=league_L(d["date"]); o=opp_o(opp,d["date"],L)
                rec.update(o=(round(o,4) if o is not None else None),L=round(L,4),
                    ek_e1=(round(log5(p,o,L)*etbf,4) if o is not None else None),
                    premium=int(p>=0.27),highk=int(o is not None and o>=0.24))
            allrows.append(rec)
        cs+=d["so"]; ct+=d["tbf"]; n+=1

# ---- populations ----
def eligible(r): return r["n_prior"]>=MIN_PRIOR and r["date"]<=HORIZON
score_pop=[r for r in allrows if eligible(r)]
quar_in_pop=[r for r in score_pop if r["opp"] is None or r.get("o") is None or r.get("gamePk") is None]
score_pop=[r for r in score_pop if r not in quar_in_pop]
for r in allrows: r["row_id"]=f"{r['pid']}|{r['gamePk']}"

cols=["row_id","pid","gamePk","date","opp","actual","n_prior","p_asof","etbf","o","L","ek_base","ek_e1","premium","highk"]
def dump(path,rs):
    with open(path,"w",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=cols,extrasaction="ignore"); w.writeheader()
        for r in rs: w.writerow(r)
dump("data/mlb/e1_construction_table.csv",allrows)
dump("data/mlb/e1_score_pop.csv",score_pop)

mae=lambda rs,k: sum(abs(r[k]-r["actual"]) for r in rs)/len(rs)
print(f"construction table: {len(allrows)} rows (all n_prior>=1, all dates)")
print(f"SCORE population (n_prior>={MIN_PRIOR} AND date<={HORIZON}, opp+gamePk resolved): {len(score_pop)}")
print(f"  baseline MAE on score pop = {mae(score_pop,'ek_base'):.3f}  (record: n=1759, MAE 1.92)")
print(f"  premium {sum(r['premium'] for r in score_pop)} | highK {sum(r['highk'] for r in score_pop)}"
      f" | interaction {sum(r['premium']*r['highk'] for r in score_pop)}")
print(f"  unique row_ids: {len(set(r['row_id'] for r in score_pop))} (must == count)")
print(f"QUARANTINED-IN-POPULATION (must be 0 before scoring): {len(quar_in_pop)}")
for r in quar_in_pop[:12]: print("   ",r["pid"],r["date"],"opp=",r["opp"],"gpk=",r.get("gamePk"))
json.dump([dict(pid=r["pid"],date=r["date"],opp=r["opp"],gamePk=r.get("gamePk"),n_prior=r["n_prior"]) for r in quar_in_pop],
          open("data/mlb/e1_quar_in_pop.json","w"),indent=1)
