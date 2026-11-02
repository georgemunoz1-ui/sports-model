"""Conference availability transport; never silently creates personnel-v2 inputs.

Only the public read endpoints observed in the official conference embeds are
implemented. Network capture is disabled unless the separate repository-pinned
permissions registry authorizes it. An imported payload is diagnostic evidence;
its import time never becomes the provider's observation or retrieval time.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zoneinfo import ZoneInfo

from research.efficiency import cfb_personnel_freshness as freshness

PERMISSIONS = Path(__file__).with_name("cfb_personnel_source_permissions.json")
ENDPOINTS = {
    "current": "https://app.hdintelligence.com/api/get-publish-public",
    "archive": "https://app.hdintelligence.com/api/get-archive-public",
}
SOURCES = {
    "SEC": "https://www.secsports.com/fbreports",
    "ACC": "https://theacc.com/sports/2025/8/28/availability-reporting-football.aspx",
    "B12": "https://big12sports.com/sports/2025/8/14/FBreporting.aspx",
}
ZONES = {"ET": "America/New_York", "CT": "America/Chicago"}
MAX_BYTES = 32 * 1024 * 1024
MISSING_PERSONNEL_FIELDS = [
    "PROVIDER_OBSERVATION_TIME_UNAVAILABLE",
    "CANONICAL_EVENT_AND_PLAYER_IDENTITIES_UNRECONCILED",
    "EXPECTED_QB_DESIGNATION_UNAVAILABLE",
    "PRIOR_PASS_ATTEMPT_COUNTS_UNAVAILABLE",
    "OFFENSE_RETURNING_SNAP_COUNTS_UNAVAILABLE",
    "DEFENSE_RETURNING_SNAP_COUNTS_UNAVAILABLE",
    "INDEPENDENT_PARTICIPATION_ASSUMPTION_UNAVAILABLE",
]


def now():
    return datetime.now(timezone.utc)


def raw_hash(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("CFB_SOURCE_DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError("CFB_SOURCE_NONFINITE_JSON")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def exclusive(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(
        value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)


def source_spec(conference, kind):
    if conference not in SOURCES or kind not in ENDPOINTS:
        raise ValueError("CFB_SOURCE_NOT_IMPLEMENTED")
    return ENDPOINTS[kind], {"sport": "Football", "organization": conference,
                             "conference": conference}


def require_permission(conference, purpose):
    """A caller's flag is not a source license. No grants ship enabled."""
    source_spec(conference, "current")
    if purpose not in {"automated_capture", "model_use", "public_redistribution"}:
        raise ValueError("CFB_SOURCE_PERMISSION_PURPOSE_INVALID")
    registry = decode(PERMISSIONS.read_bytes())
    if registry.get("schema") != "cfb.personnel-source-permissions.v1":
        raise ValueError("CFB_SOURCE_PERMISSION_REGISTRY_INVALID")
    grant = registry.get("grants", {}).get(conference)
    if not isinstance(grant, dict) or grant.get(purpose) is not True:
        raise ValueError("CFB_SOURCE_USE_NOT_CLEARED:" + conference + ":" + purpose)
    if not freshness.time(grant["valid_from_utc"]) <= now() < freshness.time(grant["valid_until_utc"]):
        raise ValueError("CFB_SOURCE_PERMISSION_OUTSIDE_VALIDITY")
    # A concrete, retained rights document and reviewed exact source scope are
    # required. This validates identity, not the legal sufficiency of that review.
    if grant.get("source_origin") != "https://app.hdintelligence.com":
        raise ValueError("CFB_SOURCE_PERMISSION_SCOPE_MISMATCH")
    rights = grant.get("rights_document", {})
    path = Path(rights.get("path", ""))
    if not path.is_file() or raw_hash(path.read_bytes()) != rights.get("sha256"):
        raise ValueError("CFB_SOURCE_RIGHTS_DOCUMENT_UNAVAILABLE_OR_CHANGED")
    if not isinstance(grant.get("review_record"), str) or not grant["review_record"].strip():
        raise ValueError("CFB_SOURCE_RIGHTS_REVIEW_REQUIRED")
    return {"permissions_sha256": raw_hash(PERMISSIONS.read_bytes()),
            "rights_document_sha256": rights["sha256"], "review_record": grant["review_record"]}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("CFB_SOURCE_REDIRECT_REQUIRES_REVIEW")


def capture(conference, kind, output):
    """One bounded, public read query after permission; no fallback on denial."""
    url, parameters = source_spec(conference, kind)
    permission = require_permission(conference, "automated_capture")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    requested = now().isoformat()
    receipt = {"schema": "cfb.conference-capture.v1", "conference": conference,
               "kind": kind, "url": url, "request_method": "POST_READ_QUERY",
               "request_parameters": parameters, "official_reference": SOURCES[conference],
               "requested_at_utc": requested, "retrieved_at_utc": None,
               "provider_observed_at_utc": None, "permission": permission,
               "model_usage": "NOT_USED", "action_authority": False,
               "official_release": False}
    request = Request(url, data=json.dumps(parameters).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(MAX_BYTES + 1)
            receipt.update({"retrieved_at_utc": now().isoformat(),
                            "http_status": response.status,
                            "headers": {name: response.headers.get(name) for name in
                                        ("Content-Type", "Date", "ETag", "Last-Modified")}})
            if len(raw) > MAX_BYTES:
                raise ValueError("CFB_SOURCE_RESPONSE_TOO_LARGE")
            if response.status != 200 or "json" not in (response.headers.get("Content-Type") or "").lower():
                raise ValueError("CFB_SOURCE_UNEXPECTED_RESPONSE")
            decode(raw)
            receipt.update({"status": "CAPTURED", "raw_sha256": raw_hash(raw), "bytes": len(raw)})
            exclusive(output / "raw.json", raw)
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        receipt.update({"status": "ACQUIRE_REQUIRED", "error_type": type(exc).__name__,
                        "http_status": getattr(exc, "code", receipt.get("http_status")),
                        "completed_at_utc": now().isoformat()})
        exclusive(output / "capture.json", receipt)
        return receipt
    exclusive(output / "capture.json", receipt)
    return receipt


def imported_receipt(raw, conference, kind):
    """Record an import honestly when the original complete receipt is absent."""
    url, parameters = source_spec(conference, kind)
    return {"schema": "cfb.conference-capture.v1", "conference": conference,
            "kind": kind, "url": url, "request_parameters": parameters,
            "official_reference": SOURCES[conference], "raw_sha256": raw_hash(raw),
            "bytes": len(raw), "status": "IMPORTED_RETAINED_BYTES",
            "imported_at_utc": now().isoformat(), "retrieved_at_utc": None,
            "provider_observed_at_utc": None,
            "original_capture_receipt": "UNAVAILABLE", "model_usage": "NOT_USED",
            "action_authority": False, "official_release": False}


def local_time(day, clock, zone):
    """Interpret reported local time, never HTTP Date or page creation time."""
    if zone not in ZONES or not isinstance(day, str) or not isinstance(clock, str):
        raise ValueError("CFB_SOURCE_REPORT_TIME_UNAVAILABLE")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or not re.fullmatch(r"\d{1,2}:\d{2}:\d{2}", clock):
        raise ValueError("CFB_SOURCE_REPORT_TIME_INVALID")
    stamp = datetime.fromisoformat(day + "T" + clock.zfill(8))
    tz = ZoneInfo(ZONES[zone])
    candidates = {stamp.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)
                  for fold in (0, 1)
                  if stamp.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == stamp}
    if len(candidates) != 1:
        raise ValueError("CFB_SOURCE_REPORT_TIME_AMBIGUOUS_OR_NONEXISTENT")
    return candidates.pop().isoformat()


def inspect_retained(raw, receipt):
    """Normalize only literal availability facts; full v2 output is always absent.

    The public report provides reported publication time, not medical observation
    time. Names/jerseys remain provider labels, not fabricated canonical IDs.
    """
    conference, kind = receipt["conference"], receipt["kind"]
    expected_url, expected_parameters = source_spec(conference, kind)
    if receipt.get("url") != expected_url or receipt.get("request_parameters") != expected_parameters:
        raise ValueError("CFB_SOURCE_RECEIPT_IDENTITY_MISMATCH")
    if raw_hash(raw) != receipt.get("raw_sha256"):
        raise ValueError("CFB_SOURCE_BYTES_CHANGED")
    data = decode(raw)
    retrieved = receipt.get("retrieved_at_utc")
    if retrieved is not None:
        retrieved = freshness.time(retrieved)
        if retrieved > now() or (receipt.get("requested_at_utc") and
                                freshness.time(receipt["requested_at_utc"]) > retrieved):
            raise ValueError("CFB_SOURCE_CAPTURE_CLOCK_INVALID")
    result = {"schema": "cfb.conference-personnel-inspection.v1", "conference": conference,
              "kind": kind, "raw_sha256": raw_hash(raw), "inspected_at_utc": now().isoformat(),
              "retrieved_at_utc": receipt.get("retrieved_at_utc"),
              "provider_observed_at_utc": None, "reports": [], "quarantined": [],
              "source_use_status": "NOT_CLEARED", "historical_original_pit_proven": False,
              "independent_source_authentication": "NOT_ESTABLISHED",
              "historical_parent_model_provenance": "NOT_ASSESSED_BY_SOURCE_ADAPTER",
              "personnel_v2_evidence": None, "admissible_personnel_v2_observations": 0,
              "canonical_prospective_eligible": False, "publication_allowed": False,
              "market_features_used": False, "model_usage": "NOT_USED", "action_authority": False}
    try:
        require_permission(conference, "model_use")
        result["source_use_status"] = "MODEL_USE_GRANT_PRESENT_NOT_PREDICTIVE_QUALIFICATION"
    except ValueError:
        pass
    if kind == "archive":
        if not isinstance(data, dict) or data.get("loaded") is not True or not isinstance(data.get("data"), list):
            raise ValueError("CFB_SOURCE_ARCHIVE_SCHEMA_CHANGED")
        result["archive_rows"] = len(data["data"])
        result["archive_report_stages"] = data.get("report_days")
        result["blockers"] = MISSING_PERSONNEL_FIELDS + [
            "ARCHIVE_HAS_REPORT_STAGES_NOT_ORIGINAL_OBSERVATION_OR_PUBLICATION_TIMES",
            "INDEPENDENT_HISTORICAL_CHRONOLOGY_UNAVAILABLE", "SOURCE_USE_NOT_CLEARED"]
        return result
    if not isinstance(data, dict):
        raise ValueError("CFB_SOURCE_CURRENT_SCHEMA_CHANGED")
    for report_id, report in data.items():
        try:
            if not isinstance(report, dict) or not isinstance(report.get("games"), list) or len(report["games"]) != 2:
                raise ValueError("CFB_SOURCE_MATCHUP_REQUIRED")
            zone = report.get("conferenceTimeZone")
            published = local_time(report.get("publishDate"), report.get("postedTime"), zone)
            if freshness.time(published) > now():
                raise ValueError("CFB_SOURCE_FUTURE_PUBLICATION_CLAIM")
            footer = report.get("footer", {})
            start = local_time(footer.get("date"), footer.get("time"), zone)
            if freshness.time(published) >= freshness.time(start):
                raise ValueError("CFB_SOURCE_REPORT_NOT_PREGAME")
            if retrieved is not None and freshness.time(published) > retrieved:
                raise ValueError("CFB_SOURCE_REPORT_PUBLISHED_AFTER_RETRIEVAL")
            teams, qbs = [], []
            for index, team in enumerate(report["games"]):
                if not isinstance(team.get("teamName"), str) or not isinstance(team.get("rows"), list):
                    raise ValueError("CFB_SOURCE_TEAM_ROWS_REQUIRED")
                teams.append({"provider_team_name": team["teamName"],
                              "provider_display_name": team.get("teamDisplayName"),
                              "team_id": None, "source_pointer": f"/{report_id}/games/{index}"})
                seen = set()
                for row_index, row in enumerate(team["rows"]):
                    label = row.get("name", "")
                    if not isinstance(label, str):
                        raise ValueError("CFB_SOURCE_PLAYER_LABEL_INVALID")
                    if not label.startswith("QB "):
                        continue
                    if label in seen:
                        raise ValueError("CFB_SOURCE_DUPLICATE_QB_ROW")
                    seen.add(label)
                    if not isinstance(row.get("status"), str) or not row["status"].strip():
                        raise ValueError("CFB_SOURCE_QB_STATUS_MISSING")
                    qbs.append({"provider_player_label": label, "player_id": None,
                                "provider_team_name": team["teamName"], "reported_status": row["status"],
                                "provider_exempt_status": row.get("exemptStatus"),
                                "expected_participation_probability": None, "expected_qb_designation": None,
                                "source_pointer": f"/{report_id}/games/{index}/rows/{row_index}"})
            if teams[0]["provider_team_name"] == teams[1]["provider_team_name"]:
                raise ValueError("CFB_SOURCE_DUPLICATE_TEAM")
            result["reports"].append({"provider_report_id": report_id, "event_id": None,
                "report_type": report.get("ReportType"), "reported_publication_at_utc": published,
                "publication_time_source_fields": [f"/{report_id}/{key}" for key in
                                                    ("publishDate", "postedTime", "conferenceTimeZone")],
                "publication_timing_status": "PROVIDER_STATED_NOT_INDEPENDENTLY_ATTESTED",
                "provider_observed_at_utc": None, "reported_start_time_utc": start,
                "future_at_inspection": freshness.time(start) > now(), "teams": teams,
                "quarterback_rows": qbs, "all_position_rows": sum(len(g["rows"]) for g in report["games"]),
                "blockers": list(MISSING_PERSONNEL_FIELDS)})
        except (ValueError, TypeError, KeyError) as exc:
            result["quarantined"].append({"provider_report_id": report_id, "reason": str(exc)})
    result["report_count"] = len(result["reports"])
    result["quarterback_row_count"] = sum(len(row["quarterback_rows"]) for row in result["reports"])
    result["future_report_count"] = sum(row["future_at_inspection"] for row in result["reports"])
    result["blockers"] = MISSING_PERSONNEL_FIELDS + [
        "INDEPENDENT_CHRONOLOGY_UNAVAILABLE", "HISTORICAL_PARENT_MODEL_PROVENANCE_SEPARATE"]
    if result["source_use_status"] == "NOT_CLEARED":
        result["blockers"].append("SOURCE_USE_NOT_CLEARED")
    if not result["future_report_count"]:
        result["blockers"].append("NO_FUTURE_PREGAME_REPORT_IN_CAPTURE")
    return result


def validate_refresh_inputs(example, snapshot):
    """Keep the existing PR #100 gate authoritative; source inspection cannot waive it."""
    return freshness.validate_snapshot(example, snapshot)
