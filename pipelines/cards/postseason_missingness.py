"""Postseason MLB operator sidecar. The registered kernels remain byte-pinned."""
import copy
import json
from pathlib import Path

from .missingness import seal_audit, verify_audit


def _binding(forecast):
    event=forecast.get("used_inputs") or forecast["inputs"]
    return {"league":"mlb","event_id":event["event_id"],"model_id":forecast["model_id"],
            "products":["postseason_winner_including_extra_innings"],"forecast":forecast}


def evidence(forecast):
    from research.mlb_postseason_v1 import validate_inputs
    event=forecast.get("used_inputs") or forecast["inputs"]
    validate_inputs(event)
    probes={}
    for side in ("home","away"):
        for field in ("observed_game_ids","era","gs","k","bb"):
            altered=copy.deepcopy(event)
            altered["sp_"+side][field]=[] if field=="observed_game_ids" else None
            try:
                validate_inputs(altered)
            except ValueError as exc:
                probes[side+"_"+field]=str(exc)
            else:
                raise ValueError("POSTSEASON_STARTER_PROBE_ACCEPTED:"+field)
    details={"status":"POSTSEASON_OBSERVED_STARTER_REFUSALS_REPLAYED",
             "starter_history":{s:{k:event["sp_"+s][k] for k in ("gs","era","k","bb","observed_game_ids")} for s in ("away","home")},
             "park_factor":event["park_factor"],"starter_withheld":probes,
             "model_output":"MONTE_CARLO_ONLY","current_state":"OBSERVED_STARTERS_REQUIRED",
             "historical_support":"UNMEASURED","limits":"UNREVIEWED",
             "simulation":"Two runs at the frozen seed must reproduce the retained draws",
             "refresh":{"status":"NO_PAIRED_PARENT"}}
    if "stage" in forecast:
        context=forecast["context"]; scope={}
        for side, record in context.items():
            workload=record["workload"]
            lineup=record.get("lineup")
            relief=record.get("bullpen")
            scope[side]={"workload_prior":workload["prior"],"workload_role":workload["role"],
                         "workload_prior_game_count":len(workload["used_game_ids"]),
                         "zero_appearance_lineup_ids":sorted(k for k,v in (lineup or {}).get("players",{}).items()
                                                             if v["pa"]==0) if lineup else None,
                         "bullpen_members":len(relief["members"]) if relief else None}
        manual=forecast.get("manual_review",{})
        details.update(stage=forecast["stage"], applied_context=scope,
                       availability_source_state="UNRESOLVED_IDENTITY_OR_COVERAGE" if not manual.get("unavailable_ids")
                       else "REVIEWED_REPORTED_IDS_ONLY",
                       fallback_rules={"starter_workload":"Shrinks observed starts toward 3 starts at 5.4 innings, 1.3 SD",
                                       "lineup":"Nine unique confirmed IDs required; unavailable/no history source fail. No batting opportunity uses .720 OPS and 100 PA shrinkage.",
                                       "bullpen":"Relievers without relief history excluded; empty pool refuses; ERA shrinks toward 4.2 over 60 outs.",
                                       "calibrated":"Only stage 4 consumes a separately bound slope"},
                       stage_sensitivity="OTHER_CONTEXT_TRANSITIONS_UNMEASURED")
    return seal_audit(**_binding(forecast),details=details)


def write_sidecar(path, forecast):
    audit=evidence(forecast)
    with (Path(path)/"missingness_audit.json").open("x") as handle:
        json.dump(audit,handle,indent=2,allow_nan=False)
    check_sidecar(path,forecast)
    return audit["receipt_sha256"]


def check_sidecar(path,forecast):
    receipt_path=Path(path)/"missingness_audit.json"
    if not receipt_path.is_file():
        raise ValueError("POSTSEASON_MISSINGNESS_RECEIPT_REQUIRED")
    audit=json.loads(receipt_path.read_bytes())
    if not verify_audit(audit,**_binding(forecast)) or audit!=evidence(forecast):
        raise ValueError("POSTSEASON_MISSINGNESS_RECEIPT_INVALID")
    return audit["receipt_sha256"]
