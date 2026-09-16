#!/usr/bin/env python3
"""E1 data layer (frozen 2026-07-24): canonical abbreviation table, team-id map, snapshot loader,
and the mechanically-separate VALIDATION/FREEZE GATE. The gate reconciles every team's terminal
G/SO/AB/BB (parsed locally from raw gamelogs) against Taco's 7/23 snapshot. build_replay_table()
and scoring MUST refuse to run unless gate_ok() is True."""

MODULE_ID = "e1_data"
import json, os, glob
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GL=os.path.join(BASE,"data/mlb/team_gamelogs")
SNAP=os.path.join(BASE,"data/mlb/team_batting_asof/2026-07-23.json")

# ---- one explicit abbreviation table: every variant -> canonical ----
CANON={ "ARI":"AZ","ARZ":"AZ","AZ":"AZ", "WSN":"WSH","WAS":"WSH","WSH":"WSH",
  "SDP":"SD","SD":"SD", "SFG":"SF","SF":"SF", "KCR":"KC","KC":"KC", "TBR":"TB","TB":"TB",
  "OAK":"ATH","ATH":"ATH","ATHL":"ATH", "CHW":"CWS","CWS":"CWS",
  "CHC":"CHC","LAA":"LAA","LAD":"LAD","NYM":"NYM","NYY":"NYY","BAL":"BAL","BOS":"BOS","CIN":"CIN",
  "CLE":"CLE","COL":"COL","DET":"DET","HOU":"HOU","MIA":"MIA","MIL":"MIL","MIN":"MIN","PHI":"PHI",
  "PIT":"PIT","SEA":"SEA","STL":"STL","TEX":"TEX","TOR":"TOR","ATL":"ATL"}
FULLNAME={"ARIZONA DIAMONDBACKS":"AZ","ATLANTA BRAVES":"ATL","BALTIMORE ORIOLES":"BAL",
 "BOSTON RED SOX":"BOS","CHICAGO CUBS":"CHC","CHICAGO WHITE SOX":"CWS","CINCINNATI REDS":"CIN",
 "CLEVELAND GUARDIANS":"CLE","COLORADO ROCKIES":"COL","DETROIT TIGERS":"DET","HOUSTON ASTROS":"HOU",
 "KANSAS CITY ROYALS":"KC","LOS ANGELES ANGELS":"LAA","LOS ANGELES DODGERS":"LAD","MIAMI MARLINS":"MIA",
 "MILWAUKEE BREWERS":"MIL","MINNESOTA TWINS":"MIN","NEW YORK METS":"NYM","NEW YORK YANKEES":"NYY",
 "ATHLETICS":"ATH","OAKLAND ATHLETICS":"ATH","PHILADELPHIA PHILLIES":"PHI","PITTSBURGH PIRATES":"PIT",
 "SAN DIEGO PADRES":"SD","SAN FRANCISCO GIANTS":"SF","SEATTLE MARINERS":"SEA","ST. LOUIS CARDINALS":"STL",
 "TAMPA BAY RAYS":"TB","TEXAS RANGERS":"TEX","TORONTO BLUE JAYS":"TOR","WASHINGTON NATIONALS":"WSH"}
def canon(a):
    k=(a or "").upper().strip()
    return CANON.get(k) or FULLNAME.get(k)
# statsapi team id -> canonical abbr (for the fetch loop)
TEAMID={108:"LAA",109:"AZ",110:"BAL",111:"BOS",112:"CHC",113:"CIN",114:"CLE",115:"COL",116:"DET",
  117:"HOU",118:"KC",119:"LAD",120:"WSH",121:"NYM",133:"ATH",134:"PIT",135:"SD",136:"SEA",137:"SF",
  138:"STL",139:"TB",140:"TEX",141:"TOR",142:"MIN",143:"PHI",144:"ATL",145:"CWS",146:"MIA",147:"NYY",
  158:"MIL"}

def load_snapshot():
    s=json.load(open(SNAP))["teams"]
    # snapshot stored per-team: g, ab, bb, bat_so
    return {a:dict(g=t["g"],ab=t["ab"],bb=t["bb"],so=t["bat_so"]) for a,t in s.items()}

def parse_team_file(abbr):
    """raw gamelog file = JSON array of [gamePk, date, AB, BB, SO]. Returns list of dicts."""
    rows=json.load(open(f"{GL}/{abbr}.json"))
    out=[]
    for r in rows:
        gpk,date,ab,bb,so=r
        out.append(dict(gamePk=int(gpk),date=str(date),ab=int(ab),bb=int(bb),so=int(so)))
    return out

def gate_ok(verbose=True):
    """BLOCKING reconciliation: every team's terminal G(unique gamePk)/SO/AB/BB == snapshot."""
    snap=load_snapshot(); fails=[]; missing=[]
    for abbr in TEAMID.values():
        f=f"{GL}/{abbr}.json"
        if not os.path.exists(f): missing.append(abbr); continue
        rows=parse_team_file(abbr)
        g=len({r["gamePk"] for r in rows})
        so=sum(r["so"] for r in rows); ab=sum(r["ab"] for r in rows); bb=sum(r["bb"] for r in rows)
        sn=snap[abbr]
        ok=(g==sn["g"] and so==sn["so"] and ab==sn["ab"] and bb==sn["bb"])
        if not ok:
            fails.append((abbr,dict(G=(g,sn["g"]),SO=(so,sn["so"]),AB=(ab,sn["ab"]),BB=(bb,sn["bb"]))))
        if verbose:
            tag="OK " if ok else "XX "
            print(f"[{tag}] {abbr:4} G {g}/{sn['g']}  SO {so}/{sn['so']}  AB {ab}/{sn['ab']}  BB {bb}/{sn['bb']}")
    if missing: print("MISSING:",missing)
    passed = not fails and not missing
    print(f"\nGATE {'PASS' if passed else 'FAIL'} — {len(TEAMID)-len(fails)-len(missing)}/{len(TEAMID)} reconciled"
          + (f"; fails={[a for a,_ in fails]}; missing={missing}" if not passed else ""))
    return passed, fails, missing

if __name__=="__main__":
    gate_ok()
