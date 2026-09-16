"""
MLB backfill FEATURE ENRICHMENT — attach pre-game V13 inputs to each 1,475-game result, NO look-ahead.
Key efficiency: only PITCHER game logs need fetching. Team RF/RA as-of-date is computed FREE from the
existing results.csv; each pitcher log entry also identifies the game's starter (so no separate starter
fetch). Output: features.csv keyed by gamePk, ready to score V13 across the season and fit calibration.

Pitcher log cache format (one file per MLBAM id): data/backfill/mlb/2026/pitcher_logs/{id}.txt
  lines: date|team|opp|homeAway|IP|ER|SO|BB|TBF|isStart   (isStart=1 for GS)
"""
import csv, os, json, glob
BASE="data/backfill/mlb/2026"; RES=f"{BASE}/results.csv"; LOGS=f"{BASE}/pitcher_logs"

def team_rfra_asof(results):
    """From results.csv: each team's cumulative runs-for/against per game BEFORE each date. FREE, no fetch."""
    games=[r for r in csv.DictReader(open(results)) if r["status"]=="final" and r["total"]!=""]
    games.sort(key=lambda r:r["date"])
    rf=_dd(); ra=_dd(); g=_dd(); snap={}   # snap[(date,team)] = (rf_pg, ra_pg) using games strictly BEFORE date
    from collections import defaultdict
    # build per-date incremental; store as-of (exclusive) per team per date
    bydate=defaultdict(list)
    for r in games: bydate[r["date"]].append(r)
    for date in sorted(bydate):
        for team in list(rf.keys()) or []:
            pass
        for r in bydate[date]:
            a,h=r["away"],r["home"]; asc,hsc=int(r["away_score"]),int(r["home_score"])
            # snapshot BEFORE applying today's game
            for t in (a,h):
                gp=g[t]; snap[(date,t)]=(round(rf[t]/gp,3) if gp else None, round(ra[t]/gp,3) if gp else None)
            rf[a]+=asc; ra[a]+=hsc; g[a]+=1; rf[h]+=hsc; ra[h]+=asc; g[h]+=1
    return snap

def _dd():
    from collections import defaultdict; return defaultdict(float)

def parse_log(path):
    """Accepts 10-field (date|team|opp|ha|IP|ER|SO|BB|TBF|isStart) or lean 7-field
    (date|IP|ER|SO|BB|TBF|isStart). Only date/IP/ER/SO/BB/TBF/GS feed the as-of math."""
    rows=[]
    for ln in open(path):
        ln=ln.strip()
        if not ln or ln.startswith("date|"): continue
        p=ln.split("|")
        if len(p)>=10:
            rows.append(dict(date=p[0],ip=_f(p[4]),er=_f(p[5]),so=_f(p[6]),bb=_f(p[7]),tbf=_f(p[8]),gs=p[9]=="1"))
        elif len(p)>=7:
            rows.append(dict(date=p[0],ip=_f(p[1]),er=_f(p[2]),so=_f(p[3]),bb=_f(p[4]),tbf=_f(p[5]),gs=p[6]=="1"))
    rows.sort(key=lambda r:r["date"]); return rows

def _f(x):
    try: return float(x)
    except: return 0.0

def pitcher_asof(logrows):
    """For each START, cumulative ERA/K%/BB%/GS BEFORE it (no look-ahead). Returns {date: dict}."""
    out={}; ip=er=so=bb=tbf=gs=0.0
    for r in logrows:
        if r["gs"]:
            era = (er*9/ip) if ip>=1 else None
            kp  = (so/tbf*100) if tbf>=10 else None
            bbp = (bb/tbf*100) if tbf>=10 else None
            out[r["date"]] = dict(gs=int(gs), era=(round(era,2) if era is not None else None),
                                  k=(round(kp,1) if kp is not None else None), bb=(round(bbp,1) if bbp is not None else None))
        ip+=r["ip"]; er+=r["er"]; so+=r["so"]; bb+=r["bb"]; tbf+=r["tbf"]; gs+= 1 if r["gs"] else 0
    return out

def build_features():
    """Join everything -> features.csv. Uses starters.csv (gamePk-keyed, DH-safe) for identity and
    pitcher logs (pid+date) for as-of stats. Team RF/RA as-of is free from results. Pure compute."""
    snap=team_rfra_asof(RES)
    # starters.csv: gamePk -> (asp_id, hsp_id)
    st={}
    for r in csv.DictReader(open(f"{BASE}/starters.csv"), delimiter="|"):
        st[r["gamePk"]]=(r.get("asp_id","").strip(), r.get("hsp_id","").strip())
    # pitcher as-of: {(pid,date): {gs,era,k,bb}}
    pa={}
    for f in glob.glob(f"{LOGS}/*.txt"):
        pid=os.path.basename(f)[:-4]
        for d,a in pitcher_asof(parse_log(f)).items(): pa[(pid,d)]=a
    LGP=json.load(open(f"{BASE}/park_factors.json"))
    games=[r for r in csv.DictReader(open(RES)) if r["status"]=="final" and r["total"]!=""]
    out=[]; full=0
    for r in games:
        d,a,h=r["date"],r["away"],r["home"]; pk=r["game_id"].split(":")[-1]
        asp_id,hsp_id=st.get(pk,("",""))
        asp=pa.get((asp_id,d)); hsp=pa.get((hsp_id,d))
        if asp and hsp: full+=1
        rfa=snap.get((d,a),(None,None)); rfh=snap.get((d,h),(None,None))
        feat=dict(away_sp_id=asp_id, home_sp_id=hsp_id, away_sp=asp, home_sp=hsp,
                  away_rf=rfa[0], away_ra=rfa[1], home_rf=rfh[0], home_ra=rfh[1],
                  park=LGP.get(r["venue"],1.0))
        out.append(dict(gamePk=pk, date=d, away=a, home=h, venue=r["venue"],
                        home_win=r["home_win"], total=r["total"], margin=r["margin"],
                        features=json.dumps(feat)))
    w=csv.DictWriter(open(f"{BASE}/features.csv","w",newline=""), fieldnames=list(out[0].keys()))
    w.writeheader(); [w.writerow(x) for x in out]
    print(f"features.csv: {len(out)} games | {full} fully-enriched (both SP as-of present) | {len(out)-full} pending logs")
    return len(out), full

if __name__=="__main__":
    import sys
    if len(sys.argv)>1 and sys.argv[1]=="build": build_features()
    else: print("logs cached:", len(glob.glob(f'{LOGS}/*.txt')))
