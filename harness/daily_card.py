#!/usr/bin/env python3
"""FULL-TRACKING daily card generator (standard from 2026-07-22, per Taco: display ALL matchup
predictions + signals + lines on every card, for visual tracking; engines stay closed for betting).
Computes everything LOCALLY (results.csv + pitcher_logs) then merges data/mlb/odds/DATE_pregame.json
and (if present) a RotoWire props CSV. Usage: python3 harness/daily_card.py YYYY-MM-DD slate.psv
  slate.psv lines: gamePk|Away Full Name|Home Full Name|utcTime|AwaySP name|HomeSP name (TBD ok)
Outputs cards/DATE_card.{json,html}. Paper/tracking only — plays require kprop EV rule + prices."""
import csv, json, os, sys, glob, unicodedata
def _norm(s): return unicodedata.normalize("NFKD",(s or "")).encode("ascii","ignore").decode().lower().strip()
import numpy as np
from math import exp, factorial
rng=np.random.default_rng(722)
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(BASE)
LG_RPG=4.45; LG_ERA=4.20; LG_K=22.0; LG_BB=8.5; LG_BIP=1-(LG_K+LG_BB)/100; LG_KRATE=.22; LG_TBF=24.0
ABBR={"Arizona Diamondbacks":"AZ","Atlanta Braves":"ATL","Baltimore Orioles":"BAL","Boston Red Sox":"BOS",
"Chicago Cubs":"CHC","Chicago White Sox":"CWS","Cincinnati Reds":"CIN","Cleveland Guardians":"CLE",
"Colorado Rockies":"COL","Detroit Tigers":"DET","Houston Astros":"HOU","Kansas City Royals":"KC",
"Los Angeles Angels":"LAA","Los Angeles Dodgers":"LAD","Miami Marlins":"MIA","Milwaukee Brewers":"MIL",
"Minnesota Twins":"MIN","New York Mets":"NYM","New York Yankees":"NYY","Athletics":"ATH",
"Philadelphia Phillies":"PHI","Pittsburgh Pirates":"PIT","San Diego Padres":"SD","San Francisco Giants":"SF",
"Seattle Mariners":"SEA","St. Louis Cardinals":"STL","Tampa Bay Rays":"TB","Texas Rangers":"TEX",
"Toronto Blue Jays":"TOR","Washington Nationals":"WSH","OAK":"ATH","CHW":"CWS","ARI":"AZ"}
def ab(t): return ABBR.get(t, t if len(t)<=3 else t)
# ---- team form + venues from results.csv (as-of everything on disk) ----
rf={}; ra={}; g={}; venue_of={}
for r in csv.DictReader(open("data/backfill/mlb/2026/results.csv")):
    if r["status"]!="final" or r["total"]=="": continue
    a,h=ab(r["away"]),ab(r["home"]); asc,hsc=int(r["away_score"]),int(r["home_score"])
    for t,f_,a_ in [(a,asc,hsc),(h,hsc,asc)]:
        rf[t]=rf.get(t,0)+f_; ra[t]=ra.get(t,0)+a_; g[t]=g.get(t,0)+1
    venue_of[h]=r["venue"]
def team_rf(t): return rf.get(t,0)/g[t] if g.get(t) else LG_RPG
def team_ra(t): return ra.get(t,0)/g[t] if g.get(t) else LG_RPG
PARK=json.load(open("data/backfill/mlb/2026/park_factors.json"))
IDS={_norm(r["name"]):r["id"] for r in csv.DictReader(open("data/backfill/mlb/2026/pitchers.csv"))}
def sp_asof(name):
    pid=IDS.get(_norm(name))
    if not pid or not os.path.exists(f"data/backfill/mlb/2026/pitcher_logs/{pid}.txt"): return None
    ip=er=so=bb=tbf=st=0.0; s_so=s_tbf=0.0
    for ln in open(f"data/backfill/mlb/2026/pitcher_logs/{pid}.txt"):
        p=ln.strip().split("|")
        if len(p)>=10: d=dict(ip=float(p[4]),er=float(p[5]),so=float(p[6]),bb=float(p[7]),tbf=float(p[8]),gs=p[9]=="1")
        elif len(p)>=7: d=dict(ip=float(p[1]),er=float(p[2]),so=float(p[3]),bb=float(p[4]),tbf=float(p[5]),gs=p[6]=="1")
        else: continue
        ip+=d["ip"]; er+=d["er"]; so+=d["so"]; bb+=d["bb"]; tbf+=d["tbf"]
        if d["gs"]: st+=1; s_so+=d["so"]; s_tbf+=d["tbf"]
    if tbf<10: return None
    era=er*9/ip if ip>=1 else LG_ERA
    kp=so/tbf*100; bbp=bb/tbf*100
    ek=None
    if st>=5:
        krate=(s_so+LG_KRATE*80)/(s_tbf+80); etbf=(s_tbf+LG_TBF*3)/(st+3); ek=krate*etbf
    return dict(era=round(era,2),gs=int(st),k=round(kp,1),bb=round(bbp,1),ek=(round(ek,2) if ek else None))
def shrunk(e,gs): w=gs/(gs+8); return w*e+(1-w)*LG_ERA
def sim(asp,hsp,aw,hm,pf,n=30000):
    def rs(sp): return max(2.2, shrunk(sp["era"],sp["gs"])-((sp["k"]-sp["bb"])-13.5)*0.03)
    def bip(sp): return max(.45,1-(sp["k"]+sp["bb"])/100)
    oa=team_rf(aw)/LG_RPG; oh=team_rf(hm)/LG_RPG
    pena=.55*team_ra(aw)+.45*LG_RPG; penh=.55*team_ra(hm)+.45*LG_RPG
    rah,raa=rs(hsp),rs(asp)
    pfa=1+(pf-1)*(bip(hsp)/LG_BIP); pfh=1+(pf-1)*(bip(asp)/LG_BIP)
    ip=np.clip(rng.normal(5.4,1.3,n),2,8); ip2=np.clip(rng.normal(5.4,1.3,n),2,8)
    ma=(rah/9*ip+penh/9*(9-ip))*oa*pfa; mh=(raa/9*ip2+pena/9*(9-ip2))*oh*pfh*1.005
    sa=np.clip(1.8+(hsp["k"]-LG_K)*.16,1.2,6); sh=np.clip(1.8+(asp["k"]-LG_K)*.16,1.2,6)
    raA=rng.poisson(rng.gamma(sa,np.maximum(ma,.3)/sa)); rhH=rng.poisson(rng.gamma(sh,np.maximum(mh,.3)/sh))
    tie=raA==rhH; hx=rng.random(n)<(.5+.04*np.sign(pena-penh)); hw=np.where(tie,hx,rhH>raA); mg=rhH-raA
    return dict(hw=float(hw.mean()),tot=float((raA+rhH+tie*rng.poisson(1.0,n)).mean()),
        rl_h=float(np.mean(mg>=2)),rl_a=float(np.mean(mg<=-2)),
        blow_h=float(np.mean(mg<=-5)),blow_a=float(np.mean(mg>=5)))
def devig(a,h):
    f=lambda m:(-m)/(-m+100) if m<0 else 100/(m+100); pa,ph=f(a),f(h); s=pa+ph; return pa/s,ph/s
def p_ge(lam,line): k0=int(np.ceil(line)); return 1-sum(exp(-lam)*lam**i/factorial(i) for i in range(k0))

date=sys.argv[1]; slate=[l.strip().split("|") for l in open(sys.argv[2]) if l.strip()]
odds={}
op=f"data/mlb/odds/{date}_pregame.json"
if os.path.exists(op):
    for e in json.load(open(op))["events"]:
        m=e["matchup"].replace("ARI","AZ").replace("CHW","CWS").replace("OAK","ATH")
        odds.setdefault(m,[]).append(e)
CAP=dict(era=LG_ERA,gs=0,k=LG_K,bb=LG_BB,ek=None)
rows=[]
for pk,awf,hmf,t,aspn,hspn in slate:
    aw,hm=ab(awf),ab(hmf)
    asp=sp_asof(aspn) or dict(CAP); hsp=sp_asof(hspn) or dict(CAP)
    capped=(asp["gs"]<2)or(hsp["gs"]<2)or(aspn=="TBD")or(hspn=="TBD")
    pf=PARK.get(venue_of.get(hm,""),1.0)
    s=sim(asp,hsp,aw,hm,pf)
    cands=odds.get(f"{aw}@{hm}") or [{}]
    with_ml=[c for c in cands if c.get("ml_away")]
    o=with_ml[0] if with_ml else cands[0]   # prefer priced entry (DH placeholders have none)
    ml_a,ml_h,tl=o.get("ml_away"),o.get("ml_home"),o.get("total")
    mkt_h=devig(ml_a,ml_h)[1] if (ml_a and ml_h) else None
    rows.append(dict(gamePk=pk,away=aw,home=hm,time=t,asp=aspn,hsp=hspn,
        asp_stats=asp,hsp_stats=hsp,capped=capped,park=round(pf,3),
        v13=dict(home_wp=round(s["hw"],3),proj_total=round(s["tot"],1),rl_home_cover=round(s["rl_h"],3),
                 rl_away_cover=round(s["rl_a"],3),blow_home=round(s["blow_h"],3),blow_away=round(s["blow_a"],3)),
        lines=dict(ml_away=ml_a,ml_home=ml_h,total=tl,over=o.get("over"),under=o.get("under"),
                   rl=o.get("rl_fav"),rl_note=o.get("note")),
        mkt_home_prob=(round(mkt_h,3) if mkt_h else None),
        gap_home=(round(s["hw"]-mkt_h,3) if mkt_h else None),
        total_lean=("OVER" if (tl and s["tot"]>tl) else ("UNDER" if tl else None)),
        k_away=asp.get("ek"), k_home=hsp.get("ek")))
json.dump({"date":date,"mode":"FULL-TRACKING (no plays unless kprop EV rule fires)","rows":rows},
          open(f"cards/{date}_card.json","w"),indent=1)
print(f"cards/{date}_card.json: {len(rows)} games")
for r in rows:
    L=r["lines"]; v=r["v13"]
    ml=f"{L['ml_away']}/{L['ml_home']}" if L['ml_away'] else "—"
    gap=f"{r['gap_home']:+.0%}" if r['gap_home'] is not None else "  —"
    print(f"{r['away']}@{r['home']:<4} ML {ml:>10} tot {str(L['total'] or '—'):>4} | V13 H% {v['home_wp']:.0%} projT {v['proj_total']:.1f} {r['total_lean'] or '':<5} gap(H){gap} blow {v['blow_away']:.0%}/{v['blow_home']:.0%} | K: {r['asp']} {r['k_away'] or '—'} / {r['hsp']} {r['k_home'] or '—'}{'  [CAP]' if r['capped'] else ''}")
