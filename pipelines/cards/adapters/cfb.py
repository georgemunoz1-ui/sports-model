"""CFB diagnostic-card adapter wired to cfb.monte_carlo_margin.v1."""
from __future__ import annotations
import csv, json, math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from models.cfb.monte_carlo_v1 import build_snapshot, run as run_mc

SCHEDULE_DIR=Path("data/cfb/source")
STATE=Path("data/models/cfb/cfb_margin_model_state_v1.json")
CARD_TZ=ZoneInfo("America/New_York")

def _dt(s): return datetime.fromisoformat(str(s).replace("Z","+00:00"))
def load_schedule(card_date, as_of_utc):
    schedule_path = SCHEDULE_DIR / f"{card_date}_cfb_schedule.csv"
    if not schedule_path.exists(): raise RuntimeError(f"SCHEDULE_SNAPSHOT_UNAVAILABLE:{schedule_path}")
    rows=[]
    with schedule_path.open(newline="") as f:
        for r in csv.DictReader(f):
            if _dt(r["start_date"]).astimezone(CARD_TZ).date().isoformat()!=card_date: continue
            rows.append({"event_id":str(r["game_id"]),"away_team":r["away_team"],"home_team":r["home_team"],"start_time_utc":r["start_date"],"_row":r})
    return rows

def build_context(schedule, as_of_utc, allow_stale=True, overrides_path=None):
    if not STATE.exists(): raise RuntimeError(f"MODEL_STATE_UNAVAILABLE:{STATE}")
    return {"state":json.loads(STATE.read_text()),"elo_state":{"team_elo":{}},"as_of_utc":as_of_utc}

def forecast_event(event, context, simulations=100000):
    row=event["_row"]
    try: snap=build_snapshot(row,context["elo_state"])
    except SystemExit as exc: raise RuntimeError(f"INPUTS_INCOMPLETE:{exc}") from exc
    out=run_mc(snap,context["state"],int(simulations))
    p=out["projection"]; mu=float(p["home_margin_mean"]); sigma=float(p["home_margin_sd"])
    # Model P is the analytic probability induced by the fitted Normal margin state;
    # Sim P is the empirical fraction of the separately generated seeded paths.
    home_model_p=0.5*(1.0+math.erf(mu/(sigma*math.sqrt(2.0))))
    home_sim_p=float(p["home_win_p_sim"])
    home_is_pick=home_model_p>=0.5
    model_p=home_model_p if home_is_pick else 1.0-home_model_p
    sim_p=home_sim_p if home_is_pick else 1.0-home_sim_p
    tier="EMERGENCY" if out["forecast_tier"]=="EMERGENCY_DIAGNOSTIC" else "PRIMARY_SHADOW"
    dose=0.40 if tier=="EMERGENCY" else 0.85
    warnings=list(out.get("quality_adjustments",[]))
    if tier=="EMERGENCY": warnings.append("CROSS_DIVISION_MEAN_BRIDGE_NOT_FITTED")
    return {"forecast_tier":tier,"data_quality":out["forecast_quality"],"dose":dose,
      "model_winner":event["home_team"] if home_is_pick else event["away_team"],"model_p":model_p,"sim_p":sim_p,
      "projected_margin":mu,"projected_total":"UNSUPPORTED_BY_TIER","spread_or_runline":"DIAGNOSTIC_ONLY_SETTLEMENT_UNSUPPORTED",
      "total_market":"UNSUPPORTED_BY_TIER","warnings":warnings,"input_snapshot_hash":out["input_snapshot_hash"],
      "model_state_config_hash":out["model_state_config_hash"],"simulation":out["simulation"],
      "provenance":{"model_id":out["model"]["model_id"],"model_version":out["model"]["model_version"],"output_hash":out["output_hash"],
      "model_p_definition":"analytic Normal CDF from fitted margin state","sim_p_definition":"empirical seeded Monte Carlo win fraction"}}
