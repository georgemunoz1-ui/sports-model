#!/usr/bin/env python3
"""Parse Taco's 7/23 season-to-date team stats (batting + pitching) into a team K-rate-taken table.
Batting SO = strikeouts TAKEN by that offense (the opponent-K signal E1 needs). K-rate proxy =
SO/(AB+BB) [PA approximated as AB+BB; ~3% understated vs true PA, uniform across teams; the per-game
statsapi fetch will use exact plateAppearances]. SNAPSHOT ONLY — using this as an as-of historical
feature would be look-ahead; it seeds FORWARD adjustment and validates the fetch endpoint."""

MODULE_ID = "parse_team_stats"
import json, os, re
SRC="/root/.claude/uploads/89dc228f-5581-5f9d-87f5-493d59afc3d1/b67bcc0f-Team_stats_723_date.txt"
ABBR={"Washington Nationals":"WSH","New York Yankees":"NYY","Houston Astros":"HOU","Atlanta Braves":"ATL",
"Philadelphia Phillies":"PHI","Cincinnati Reds":"CIN","Los Angeles Dodgers":"LAD","Pittsburgh Pirates":"PIT",
"Chicago White Sox":"CWS","Chicago Cubs":"CHC","Athletics":"ATH","Detroit Tigers":"DET","Minnesota Twins":"MIN",
"Baltimore Orioles":"BAL","New York Mets":"NYM","Seattle Mariners":"SEA","Colorado Rockies":"COL",
"Texas Rangers":"TEX","San Diego Padres":"SD","San Francisco Giants":"SF","Los Angeles Angels":"LAA",
"St. Louis Cardinals":"STL","Kansas City Royals":"KC","Miami Marlins":"MIA","Cleveland Guardians":"CLE",
"Tampa Bay Rays":"TB","Toronto Blue Jays":"TOR","Arizona Diamondbacks":"AZ","Boston Red Sox":"BOS",
"Milwaukee Brewers":"MIL"}
ALIAS={"AZ":"ARI","ATH":"OAK"}  # results.csv/statsapi join aliases

lines=[l.rstrip("\n") for l in open(SRC)]
# split pages
pb=next(i for i,l in enumerate(lines) if "PAGE BREAK" in l)
def parse(section, expect):
    out={}
    prevname=None
    for l in section:
        s=l.strip()
        if not s: continue
        toks=s.split()
        if toks[0] in ("AL","NL") and len(toks)>=expect:
            out[prevname]=toks
        elif not re.fullmatch(r"\d+",s):  # not a rank line -> it's a team name
            prevname=s
    return out
bat=parse(lines[:pb],17)     # league,G,AB,R,H,2B,3B,HR,RBI,BB,SO,SB,CS,AVG,OBP,SLG,OPS
pit=parse(lines[pb:],20)     # league,W,L,ERA,G,GS,...,IP,H,R,ER,HR,?,BB,SO,WHIP,AVG

teams={}
tot_so=tot_pa=0
for name,t in bat.items():
    if name not in ABBR: continue
    ab=int(t[2]); bb=int(t[9]); so=int(t[10]); g=int(t[1])
    pa=ab+bb                      # PA proxy
    kr=so/pa
    ab2=ABBR[name]
    teams[ab2]=dict(team=name,abbr=ab2,alias=ALIAS.get(ab2),league=t[0],g=g,ab=ab,bb=bb,
                    bat_so=so,pa_proxy=pa,k_rate=round(kr,4))
    tot_so+=so; tot_pa+=pa
# attach pitching SO for context
for name,t in pit.items():
    if name in ABBR and ABBR[name] in teams:
        teams[ABBR[name]]["pit_so"]=int(t[17]); teams[ABBR[name]]["ip"]=t[10]

league_kr=tot_so/tot_pa
for a in teams: teams[a]["k_rate_vs_lg"]=round(teams[a]["k_rate"]-league_kr,4)
ranked=sorted(teams.values(),key=lambda x:-x["k_rate"])
for i,r in enumerate(ranked,1): r["rank_high_k"]=i

os.makedirs("data/mlb/team_batting_asof",exist_ok=True)
out=dict(as_of="2026-07-23",source="Taco upload (season-to-date snapshot)",
         note="SNAPSHOT not per-game; k_rate=SO/(AB+BB) proxy; look-ahead if used as historical as-of feature",
         league_k_rate=round(league_kr,4),
         high_k_cut=0.24,low_k_ref=0.20,teams={r["abbr"]:r for r in ranked})
json.dump(out,open("data/mlb/team_batting_asof/2026-07-23.json","w"),indent=1)

print(f"League K-rate (SO/(AB+BB)) = {league_kr:.3f}\n")
print(f"{'#':>2} {'TEAM':4} {'K-rate':>7} {'vs lg':>6} {'batSO':>6}  tier")
for r in ranked:
    tier="HIGH-K" if r["k_rate"]>=0.24 else ("low-K" if r["k_rate"]<=0.205 else "")
    print(f"{r['rank_high_k']:>2} {r['abbr']:4} {r['k_rate']*100:6.1f}% {r['k_rate_vs_lg']*100:+5.1f} {r['bat_so']:>6}  {tier}")
print("\nCross-check vs the two E1 anecdotes:")
for code,who in [("PIT","Cole 7/22 opp"),("SD","Sale 7/23 opp")]:
    r=teams[code]; print(f"  {code} ({who}): {r['k_rate']*100:.1f}% K, rank {r['rank_high_k']}/30, {r['k_rate_vs_lg']*100:+.1f} vs lg")
print(f"\nHigh-K offenses (>=24%): {[r['abbr'] for r in ranked if r['k_rate']>=0.24]}")
print(f"Lowest-K (contact) offenses: {[r['abbr'] for r in ranked[-5:]]}")
