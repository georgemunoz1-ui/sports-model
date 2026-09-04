"""MLB diagnostic-card adapter wired to the registered Gamma-Poisson engine.

Schedule/team run context comes from MLB StatsAPI at runtime. Missing probable
starter profiles intentionally fall through to the engine's registered league
priors and are surfaced as quality adjustments; they never suppress a card.
"""
from __future__ import annotations
import json, math, urllib.request
from pathlib import Path
from models.mlb.monte_carlo_v1 import run as run_mc

CONFIG=Path("data/models/mlb/v13_1_monte_carlo_config_v1.json")
PARKS=Path("data/backfill/mlb/2026/park_factors.json")
BASE="https://statsapi.mlb.com/api/v1"

def _get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"sports-model-diagnostic/1.0"})
    with urllib.request.urlopen(req,timeout=20) as r: return json.load(r)

def load_schedule(card_date, as_of_utc):
    data=_get(f"{BASE}/schedule?sportId=1&date={card_date}&hydrate=probablePitcher,venue")
    rows=[]
    for d in data.get("dates",[]):
      for g in d.get("games",[]):
        rows.append({"event_id":str(g["gamePk"]),"away_team":g["teams"]["away"]["team"]["name"],"home_team":g["teams"]["home"]["team"]["name"],
          "start_time_utc":g["gameDate"],"away_team_id":g["teams"]["away"]["team"]["id"],"home_team_id":g["teams"]["home"]["team"]["id"],
          "away_sp":g["teams"]["away"].get("probablePitcher"),"home_sp":g["teams"]["home"].get("probablePitcher"),"venue":g.get("venue",{}).get("name")})
    return rows

def _standings():
    data=_get(f"{BASE}/standings?leagueId=103,104&season=2026&standingsTypes=regularSeason")
    out={}
    for rec in data.get("records",[]):
      for tr in rec.get("teamRecords",[]):
        tid=int(tr["team"]["id"]); gp=int(tr.get("gamesPlayed") or 0)
        rs=tr.get("runsScored"); ra=tr.get("runsAllowed")
        if gp and rs is not None and ra is not None: out[tid]={"rf_pg":float(rs)/gp,"ra_pg":float(ra)/gp}
    return out

def _pitcher(person):
    if not person or not person.get("id"): return None
    pid=int(person["id"])
    try:
      d=_get(f"{BASE}/people/{pid}/stats?stats=season&group=pitching&season=2026")
      s=d.get("stats",[{}])[0].get("splits",[])
      if not s: return None
      x=s[0].get("stat",{}); bf=float(x.get("battersFaced") or 0); k=float(x.get("strikeOuts") or 0); bb=float(x.get("baseOnBalls") or 0)
      return {"id":pid,"name":person.get("fullName"),"era":x.get("era"),"gs":x.get("gamesStarted",0),"k":100*k/bf if bf else None,"bb":100*bb/bf if bf else None}
    except Exception: return None

def build_context(schedule, as_of_utc, allow_stale=True, overrides_path=None):
    if not CONFIG.exists(): raise RuntimeError(f"MODEL_STATE_UNAVAILABLE:{CONFIG}")
    standings=_standings(); parks=json.loads(PARKS.read_text()) if PARKS.exists() else {}
    overrides={}
    if overrides_path:
      payload=json.loads(Path(overrides_path).read_text()); items=payload if isinstance(payload,list) else [payload]
      overrides={str(x["event_id"]):x for x in items}
    return {"config":json.loads(CONFIG.read_text()),"standings":standings,"parks":parks,"overrides":overrides,"as_of_utc":as_of_utc}

def _poisson_win_prob(mu_h,mu_a,limit=30):
    # Deterministic point estimate for Model P: independent-Poisson score model
    # at the engine-implied mean runs. Ties split 50/50. Sim P remains the
    # registered Gamma-Poisson empirical path fraction and is never averaged in.
    ph=[math.exp(-mu_h)]; pa=[math.exp(-mu_a)]
    for k in range(1,limit+1): ph.append(ph[-1]*mu_h/k); pa.append(pa[-1]*mu_a/k)
    p=0.0
    for h,a_h in enumerate(ph):
      p += a_h*(sum(pa[:h]) + 0.5*pa[h])
    return min(1.0,max(0.0,p))

def forecast_event(event, context, simulations=100000):
    team_a=context["standings"].get(int(event["away_team_id"]),{}); team_h=context["standings"].get(int(event["home_team_id"]),{})
    override=context["overrides"].get(str(event["event_id"]),{}).get("overrides",{})
    away_sp=override.get("away_sp") or _pitcher(event.get("away_sp")); home_sp=override.get("home_sp") or _pitcher(event.get("home_sp"))
    snap={"event_id":str(event["event_id"]),"game_start_utc":event["start_time_utc"],"away_team":event["away_team"],"home_team":event["home_team"],
      "away_rf_pg":team_a.get("rf_pg"),"away_ra_pg":team_a.get("ra_pg"),"home_rf_pg":team_h.get("rf_pg"),"home_ra_pg":team_h.get("ra_pg"),
      "away_sp":away_sp,"home_sp":home_sp,"park_factor":context["parks"].get(event.get("venue"),1.0),"venue":event.get("venue")}
    out=run_mc(snap,context["config"],int(simulations)); p=out["projection"]
    home_model=_poisson_win_prob(float(p["home_runs_mean"]),float(p["away_runs_mean"])); home_sim=float(p["home_win_p_sim"])
    home_pick=home_model>=0.5; model_p=home_model if home_pick else 1-home_model; sim_p=home_sim if home_pick else 1-home_sim
    adj=list(out.get("quality_adjustments",[])); tier="BASELINE" if adj else "PRIMARY_SHADOW"; dose=max(0.2,0.90-0.10*len(adj))
    if not team_a or not team_h: adj.append("TEAM_RUN_CONTEXT_PRIOR_FALLBACK")
    if event.get("venue") not in context["parks"]: adj.append("PARK_NEUTRAL_FALLBACK")
    return {"forecast_tier":tier,"data_quality":out["forecast_quality"],"dose":dose,"model_winner":event["home_team"] if home_pick else event["away_team"],
      "model_p":model_p,"sim_p":sim_p,"projected_margin":float(p["home_margin_mean"]),"projected_total":float(p["total_mean"]),
      "spread_or_runline":"SUPPORTED_AFTER_LINE_ATTACH","total_market":"SUPPORTED_AFTER_LINE_ATTACH","warnings":adj,
      "input_snapshot_hash":out["input_snapshot_hash"],"model_state_config_hash":out["model_state_config_hash"],
      "simulation":{"simulation_engine":out["simulation_engine"],"simulation_engine_version":out["simulation_engine_version"],"simulation_count":out["simulation_count"],"random_seed":out["random_seed"]},
      "provenance":{"model_id":context["config"]["model_id"],"model_version":context["config"]["version"],"output_hash":out["output_hash"],
      "model_p_definition":"deterministic independent-Poisson point estimate at engine-implied mean runs; diagnostic adapter output",
      "sim_p_definition":"registered Gamma-Poisson 100K empirical win fraction"}}
