#!/usr/bin/env python3
"""Build a fresh NFL event package for a requested date.

Schedule/personnel are acquired at runtime from nflverse via nflreadpy.  The
registered Week-1 state proof is consumed as immutable prior-state evidence;
historical event packages are never modified or reused as current facts.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, sys
from pathlib import Path
import pandas as pd
import nflreadpy as nfl

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
DATA=ROOT/"data/nfl/contextual_v1"

def digest(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def frame_digest(df):
    return hashlib.sha256(df.sort_index(axis=1).to_csv(index=False).encode()).hexdigest()
def pdframe(x):
    return x.to_pandas() if hasattr(x,"to_pandas") else pd.DataFrame(x)
def canon(t):
    return {"LAR":"LA","JAC":"JAX","WSH":"WAS"}.get(str(t),str(t))
def val(row,*names,default=None):
    for n in names:
        if n in row and pd.notna(row[n]): return row[n]
    return default
def status_norm(x):
    s=str(x or "").upper().replace(" ","_")
    if "OUT" in s:return "OUT"
    if "DOUBT" in s:return "DOUBTFUL"
    if "QUESTION" in s:return "QUESTIONABLE"
    return "NO_DESIGNATION"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--date",required=True);ap.add_argument("--as-of-utc",required=True)
    ap.add_argument("--state-proof",required=True);ap.add_argument("--output",required=True)
    a=ap.parse_args(); cutoff=dt.datetime.fromisoformat(a.as_of_utc.replace("Z","+00:00"))
    if cutoff.tzinfo is None:raise ValueError("TIMEZONE_REQUIRED")
    season=int(a.date[:4]); fetched=dt.datetime.now(dt.timezone.utc).isoformat()
    sched=pdframe(nfl.load_schedules(seasons=[season]))
    games=sched[(sched["gameday"].astype(str)==a.date)&(sched["game_type"].astype(str)=="REG")].copy()
    if games.empty:raise ValueError("NFL_DATE_NOT_SCHEDULED:"+a.date)
    # The requested card date may contain more than one game; build every resolved event.
    source_schedule_hash=frame_digest(sched)
    proof=Path(a.state_proof)
    audit=json.loads((proof/"current_week/audit.json").read_text())
    before_doc=json.loads((proof/"historical_state.json").read_text())
    before=before_doc["states"]
    after=json.loads((proof/"current_week/team_state.json").read_text())
    if audit.get("status")!="reconciled" or not audit.get("state_update_applied"):
        raise ValueError("LATEST_VALID_WEEK1_STATE_PROOF_INVALID")
    from models.nfl.contextual import base_features as bf
    from models.nfl.contextual.model import load_artifact
    from models.nfl.contextual.qb_assimilation import build as build_qb
    from models.nfl.contextual.recovered_inference import digest as model_digest
    artifact=load_artifact(DATA/"model_packed.json")

    # Rebuild the registered QB Week-1 state from current nflverse source.
    pbp=pdframe(nfl.load_pbp(seasons=[season]))
    week1=sched[(sched["season"]==season)&(sched["week"]==1)&(sched["game_type"]=="REG")].copy()
    if len(week1)!=16:raise ValueError("QB_WEEK1_COMPLETE_SCHEDULE_REQUIRED")
    qb_update=build_qb(artifact,pbp,week1,frame_digest(pbp))

    injuries=pdframe(nfl.load_injuries(seasons=[season]))
    depth=pdframe(nfl.load_depth_charts(seasons=[season]))
    injury_hash=frame_digest(injuries);depth_hash=frame_digest(depth)
    states={k:bf.TeamState(**v) for k,v in after.items()}
    events=[];inputs={}
    for _,g in games.iterrows():
        home=canon(g["home_team"]);away=canon(g["away_team"]);gid=str(g["game_id"])
        event={"event_id":gid,"home_team":home,"away_team":away,"gameday":str(g["gameday"]),
               "gametime":str(g["gametime"]),"start_time_utc":pd.Timestamp(g["gametime"] if False else g.get("gameday")).isoformat(),
               "location":str(val(g,"location",default="Home")),"source":"nflverse.load_schedules",
               "event_scope":"FRESH_FORECAST"}
        # nflverse gametime is ET; derive UTC without using the UTC calendar date as local date.
        from zoneinfo import ZoneInfo
        local=dt.datetime.fromisoformat(event["gameday"]+"T"+event["gametime"]).replace(tzinfo=ZoneInfo("America/New_York"))
        event["start_time_utc"]=local.astimezone(dt.timezone.utc).isoformat().replace("+00:00","Z")
        if cutoff>=dt.datetime.fromisoformat(event["start_time_utc"].replace("Z","+00:00")):raise ValueError("NOT_PREGAME")
        row=pd.Series({"game_id":gid,"season":season,"week":int(g["week"]),"gameday":event["gameday"],
            "away_team":away,"home_team":home,"home_score":None,"away_score":None,
            "location":event["location"],"roof":val(g,"roof"),"temp":None,"wind":None,
            "home_rest":val(g,"home_rest"),"away_rest":val(g,"away_rest")})
        base=bf._feature_row(row,states[home],states[away])
        base["state_lineage"]={"state_policy":"AFTER_COMPLETE_WEEK1_REGISTERED_PROOF",
            "state_after_sha256":model_digest(after),"audit_sha256":model_digest(audit)}

        # Current injury rows, restricted to this event's teams and latest week <= event week.
        inj=injuries.copy()
        teamcol=next((c for c in ("team","team_abbr","team_abbreviation") if c in inj.columns),None)
        weekcol="week" if "week" in inj.columns else None
        obs=[]
        if teamcol:
            inj["_team"]=inj[teamcol].map(canon)
            sub=inj[inj["_team"].isin([home,away])]
            if weekcol:sub=sub[pd.to_numeric(sub[weekcol],errors="coerce")<=int(g["week"])]
            for r in sub.to_dict("records"):
                obs.append({"team":canon(r.get(teamcol)),"player":str(val(r,"full_name","player_name","name",default="UNKNOWN")),
                    "position":str(val(r,"position",default="UNK")),"issue":val(r,"report_primary_injury","injury"),
                    "practice":val(r,"practice_status","practice"),"game_status":status_norm(val(r,"report_status","game_status")),
                    "effective_date":str(val(r,"date_modified","date",default=a.date))[:10],
                    "player_id":val(r,"gsis_id","player_id"),"source":"nflverse.load_injuries"})
        # Resolve QB1 identities from latest available depth-chart rows; unresolved IDs are
        # intentionally represented as unknown and handled by the registered QB feature imputer.
        qbs={}
        dc=depth.copy();tcol=next((c for c in ("team","club_code","team_abbr") if c in dc.columns),None)
        if tcol:
            dc["_team"]=dc[tcol].map(canon)
            for team in (home,away):
                sub=dc[dc["_team"].eq(team)]
                pcol=next((c for c in ("position","pos_abb","pos_name") if c in sub.columns),None)
                if pcol:sub=sub[sub[pcol].astype(str).str.upper().eq("QB")]
                rankcol=next((c for c in ("depth_team","depth_chart_order","depth") if c in sub.columns),None)
                if rankcol and not sub.empty:sub=sub.sort_values(rankcol)
                if not sub.empty:
                    r=sub.iloc[-1] if rankcol is None else sub.iloc[0]
                    qbs[team]={"name":str(val(r,"full_name","player_name","name",default="UNKNOWN")),
                        "id":val(r,"gsis_id","player_id"),"depth":"QB1","game_status":"NO_DESIGNATION",
                        "final_inactive_status":"PENDING","workload":"UNKNOWN"}
                else:qbs[team]={"name":"UNKNOWN","id":None,"depth":"QB1_UNRESOLVED","game_status":"NO_DESIGNATION","final_inactive_status":"PENDING","workload":"UNKNOWN"}
        personnel={"quarterbacks":qbs,"injury_observations":obs,"reserve_absences":[],"role_resolutions":{},
                   "final_inactives":"PENDING","workload":"UNKNOWN"}
        rest={"event_id":gid,"retrieved_at_utc":fetched,"available_by_utc":fetched,"published_at_utc":None,
              "source_sha256":source_schedule_hash,"source":"nflverse.load_schedules",
              "home_rest":float(val(g,"home_rest",default=7) or 7),"away_rest":float(val(g,"away_rest",default=7) or 7),
              "definition":"nflverse schedule home_rest/away_rest"}
        personnel_rec={"event_id":gid,"retrieved_at_utc":fetched,"available_by_utc":fetched,"published_at_utc":None,
              "source_sha256":digest({"injuries":injury_hash,"depth":depth_hash}),"source":"nflverse.load_injuries + load_depth_charts","state":personnel}
        assimilation={"audit":audit,"state_before":before,"state_after":after,
                "base_feature_code_sha256":bf.sha256_file(bf.__file__),"qb_update":qb_update}
        events.append(event);inputs[gid]={"base":base,"context":{"rest":rest,"personnel":personnel_rec,"assimilation":assimilation},
            "assimilation":assimilation}
    package={"schema":"nfl.event_package.v2","package_mode":"FRESH_FORECAST","captured_at_utc":fetched,
      "scope":"REQUESTED_DATE_FRESH_ACQUISITION","covered_dates":[a.date],"events":events,
      "model_path":"model_packed.json","model_digest":model_digest(artifact),
      "recovered_parameters_path":"recovered_parameters.json","event_inputs":inputs,
      "source_fetches":[{"source":"nflverse.load_schedules","sha256":source_schedule_hash,"fetched_at_utc":fetched},
        {"source":"nflverse.load_injuries","sha256":injury_hash,"fetched_at_utc":fetched},
        {"source":"nflverse.load_depth_charts","sha256":depth_hash,"fetched_at_utc":fetched},
        {"source":"nflverse.load_pbp(2026)","sha256":frame_digest(pbp),"fetched_at_utc":fetched}],
      "state_certification":"REGISTERED_WEEK1_RECONCILIATION_PROOF",
      "action_authority":False}
    package["source_manifest_hash"]=digest(package["source_fetches"])
    package["package_id"]=f"nfl_{a.date}_{'_'.join(e['event_id'] for e in events)}_asof_{cutoff.strftime('%Y%m%dT%H%M%SZ')}"
    package["writer_registration"]={"status":"AUTHORIZED_SHADOW","created_at_utc":fetched,"package_id":package["package_id"]}
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(package,indent=2,default=str))
    print(json.dumps({"status":"SEALED","package_id":package["package_id"],"events":[e["event_id"] for e in events],
        "source_manifest_hash":package["source_manifest_hash"],"path":str(out)},indent=2))
if __name__=="__main__":main()
