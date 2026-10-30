"""NHL source/settlement semantics independent of frozen forecast kernels.

Goalie reports are normalized upstream captures, not provider authentication.
No status creates a player-effect estimate or a scenario probability.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from models.common.discrete_research import digest, finite, identity, source_hash, stamp

GOALIE_STATUSES = {"CONFIRMED", "PROJECTED", "UNKNOWN"}
PROCEDURE_ID = "nhl.context_controls.research.v1"


def goalie_context(event, reports, *, cutoff_utc, max_age_hours=6):
    """Reconcile source-bound reports without silently selecting a starter.

    Each report is an already byte-verified normalized source row. Latest report
    does not override a disagreement from another source: conflict stays UNKNOWN.
    Confirmation applies only to an explicit source statement, never to a mere
    projected lineup. Unknown records cannot carry an invented player identity.
    """
    cutoff = stamp(cutoff_utc)
    max_age_hours = finite(max_age_hours)
    if max_age_hours <= 0:
        raise ValueError("POSITIVE_GOALIE_AGE_POLICY_REQUIRED")
    if cutoff >= stamp(event["start_time_utc"]):
        raise ValueError("PREGAME_CUTOFF_REQUIRED")
    eid = identity(event["event_id"], "EVENT_ID")
    teams = [identity(event[s + "_id"], "TEAM_ID") for s in ("home", "away")]
    if teams[0] == teams[1]:
        raise ValueError("DISTINCT_TEAMS_REQUIRED")
    relevant = {team: [] for team in teams}
    for source in reports:
        if source.get("event_id") != eid or source.get("team_id") not in relevant:
            raise ValueError("GOALIE_EVENT_TEAM_BINDING")
        status = source.get("status")
        if status not in GOALIE_STATUSES:
            raise ValueError("GOALIE_STATUS_REQUIRED")
        if status == "UNKNOWN":
            if source.get("player_id") is not None:
                raise ValueError("UNKNOWN_GOALIE_CANNOT_HAVE_PLAYER")
        else:
            identity(source.get("player_id"), "PLAYER_ID")
        identity(source.get("source_url"), "SOURCE_URL")
        source_hash(source.get("source_sha256"))
        retrieved = stamp(source["retrieved_at_utc"])
        observed = stamp(source["observed_at_utc"])
        if observed > retrieved or retrieved > cutoff:
            raise ValueError("GOALIE_SOURCE_NOT_AVAILABLE_AT_CUTOFF")
        if source.get("source_record_binding") != "VERIFIED_RAW_NORMALIZED_RECORD":
            raise ValueError("GOALIE_SOURCE_RECORD_BINDING_REQUIRED")
        relevant[source["team_id"]].append({**source, "fresh_at_cutoff": (cutoff-observed).total_seconds() <= max_age_hours*3600})
    sides = {}
    for side, team in zip(("home", "away"), teams):
        sources = relevant[team]
        fresh = [r for r in sources if r["fresh_at_cutoff"]]
        players = {r["player_id"] for r in fresh if r["status"] != "UNKNOWN"}
        # An unknown report does not contradict an identified report, but neither
        # supplies a probability nor upgrades PROJECTED to CONFIRMED.
        conflict = len(players) > 1
        if len(players) == 1:
            player = next(iter(players))
            status = "CONFIRMED" if any(r["status"] == "CONFIRMED" for r in fresh) else "PROJECTED"
        else:
            player, status = None, "UNKNOWN"
        reasons = (["CONFLICTING_GOALIE_REPORTS"] if conflict else
                   ["GOALIE_SOURCE_UNAVAILABLE"] if not sources else
                   ["GOALIE_REPORT_STALE"] if not fresh else
                   ["GOALIE_UNKNOWN"] if status == "UNKNOWN" else [])
        sides[side] = {"team_id": team, "player_id": player, "status": status,
                       "sources": sources, "blocking_reasons": reasons,
                       "adjustment_applied": False, "scenario_weights": None}
    return {"schema": "sports.nhl_goalie_context.v1", "event_id": eid,
            "cutoff_utc": cutoff.isoformat(), "max_age_hours_policy": max_age_hours, "per_side": sides,
            "data_capture": "COMPLETE" if all(relevant.values()) else "PARTIAL",
            "personnel_transform": "FITTED_TRANSFORM_REQUIRED",
            "provider_authenticity": "NOT_ATTESTED_BY_BYTE_BINDING",
            "numerically_used": False, "action_authority": False}


def load_goalie_reports(path):
    """Verify normalized report rows against immutable retained raw JSON.

    This adapter deliberately does not claim that its upstream normalized JSON
    is an official provider response. Provider parsing/authentication is separate.
    The packet stores only raw paths/digests/timing; report values come from bytes.
    """
    path = Path(path).resolve()
    packet = json.loads(path.read_bytes())
    if packet.get("schema") != "sports.nhl_goalie_capture.v1":
        raise ValueError("GOALIE_CAPTURE_SCHEMA")
    reports = []
    seen = set()
    for receipt in packet.get("sources", []):
        relative = receipt["raw_path"]
        raw_path = (path.parent / relative).resolve()
        if Path(relative).is_absolute() or not raw_path.is_relative_to(path.parent):
            raise ValueError("SOURCE_PATH_ESCAPE")
        raw = raw_path.read_bytes()
        sha = source_hash(receipt["source_sha256"])
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("GOALIE_SOURCE_DIGEST_MISMATCH")
        key = (sha, receipt["retrieved_at_utc"], receipt["source_url"])
        if key in seen:
            raise ValueError("DUPLICATE_GOALIE_CAPTURE")
        seen.add(key)
        source = json.loads(raw)
        if source.get("schema") != "sports.nhl_goalie_normalized_source.v1" or not isinstance(source.get("reports"), list):
            raise ValueError("NORMALIZED_GOALIE_SOURCE_REQUIRED")
        for row in source["reports"]:
            reports.append({**{k: row[k] for k in ("event_id", "team_id", "player_id", "status", "observed_at_utc")},
                            **{k: receipt[k] for k in ("source_sha256", "source_url", "retrieved_at_utc")},
                            "source_record_binding": "VERIFIED_RAW_NORMALIZED_RECORD"})
    return reports


def settlement_scores(record, *, settlement):
    """Validate regulation/final score meaning before downstream settlement.

    Supports the repository's explicit FULL_GAME_OT_SO_PLUS_ONE contract only.
    Other bookmaker shootout conventions require another named contract.
    This is observed-score normalization, not a fitted overtime model.
    """
    if settlement not in {"REGULATION", "FULL_GAME_OT_SO_PLUS_ONE"}:
        raise ValueError("UNSUPPORTED_NHL_SETTLEMENT")
    identity(record.get("event_id"), "EVENT_ID")
    if record.get("status") != "FINAL":
        raise ValueError("FINAL_RESULT_REQUIRED")
    mode = record.get("finish_type")
    if mode not in {"REGULATION", "OVERTIME", "SHOOTOUT"}:
        raise ValueError("NHL_FINISH_TYPE_REQUIRED")
    values = {}
    for field in ("regulation_home", "regulation_away", "final_home", "final_away"):
        value = finite(record.get(field))
        if value < 0 or value != int(value):
            raise ValueError("NONNEGATIVE_INTEGER_SCORE_REQUIRED")
        values[field] = int(value)
    rh, ra, fh, fa = (values[k] for k in ("regulation_home", "regulation_away", "final_home", "final_away"))
    if fh == fa:
        raise ValueError("NHL_FINAL_TIE_INVALID")
    if mode == "REGULATION":
        if rh != fh or ra != fa or rh == ra:
            raise ValueError("REGULATION_FINAL_SCORE_CONFLICT")
    elif rh != ra or sorted((fh-rh, fa-ra)) != [0, 1]:
        raise ValueError("NHL_OT_SO_PLUS_ONE_CONFLICT")
    home, away = (rh, ra) if settlement == "REGULATION" else (fh, fa)
    return {"event_id": record["event_id"], "settlement": settlement,
            "home_score": home, "away_score": away, "home_margin": home-away,
            "total": home+away, "finish_type": mode,
            "semantic_validation": "PASS", "source_authenticity": "NOT_ASSESSED",
            "overtime_model_validated": False}
