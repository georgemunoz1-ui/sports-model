"""Opt-in, append-only NBA combination source capture. Never fits or forecasts.

Public HTTP, the documented D&T v2 API (explicit configured credential only),
and rendered Databallr DOM exports have different evidence strengths. Import
time never becomes provider time. Unknown provider clocks stay null and fail
the frozen experiment's strict source_as_of gate.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from scripts.nhl_atomic_capture import atomic, digest, encoded, inside, instant, Response
from research.nba_forecast_combination import FACTORS, FACTOR_VERSION, TARGET, audit, number

SCHEMA = "nba.pregame_source_capture.v1"
PARSER = "nba.external_normalization.v1"
DT = "https://dunksandthrees.com"
DB = "https://databallr.com/teams"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
MAX_BYTES = 5_000_000
ALIASES = {"WSH": "WAS", "GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "UTAH": "UTA"}
TEAMS = dict(zip(
    "ATL BOS CLE NOP CHI DAL DEN GSW HOU LAC LAL MIA MIL MIN BKN NYK ORL IND PHI PHX POR SAC SAS OKC TOR UTA MEM WAS DET CHA".split(),
    range(1610612737, 1610612767)))
IDENTITY = ("event_id", "league", "home", "away", "target", "scheduled_start")


def utc():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    value = ALIASES.get(value, value)
    if value not in TEAMS:
        raise ValueError("UNKNOWN_TEAM:" + str(value))
    return value


def approved_url(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443) or u.fragment:
        raise ValueError("UNAPPROVED_URL")
    allowed = {
        "dunksandthrees.com": {"/games", "/about/epm", "/api/v2/documentation", "/api/v2/game-predictions"},
        "databallr.com": {"/teams"},
        "site.api.espn.com": {"/apis/site/v2/sports/basketball/nba/scoreboard"},
    }
    if u.path not in allowed.get(u.hostname, set()):
        raise ValueError("UNAPPROVED_URL")
    q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    if any(len(v) != 1 for v in q.values()):
        raise ValueError("DUPLICATE_QUERY")
    for k, v in q.items():
        if k in ("date",) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v[0]):
            continue
        if k == "dates" and re.fullmatch(r"\d{8}", v[0]):
            continue
        if (k, v[0]) in (("days", "1"), ("limit", "1000")):
            continue
        raise ValueError("UNAPPROVED_QUERY")
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Especially important for the Authorization header: never forward it.
        return None


def http_transport(url, credential=None):
    approved_url(url)
    headers = {"User-Agent": "sports-model-pregame-research/1.0", "Accept": "application/json,text/html"}
    if credential:
        if urllib.parse.urlsplit(url).path != "/api/v2/game-predictions":
            raise ValueError("CREDENTIAL_ENDPOINT_MISMATCH")
        headers["Authorization"] = credential
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.build_opener(NoRedirect()).open(request, timeout=20)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("RESPONSE_SIZE_LIMIT")
        return Response(body, response.status, dict(response.headers), response.url)


def retain(root, kind, body, started, finished, **meta):
    """Writer-owned first observation and raw bytes. No supplied capture clock."""
    if instant(started) > instant(finished):
        raise ValueError("WRITER_CLOCK_REVERSED")
    attempt = uuid.uuid4().hex
    raw_path = f"raw/{kind}/{attempt}.bin"
    receipt_path = f"receipts/{kind}/{attempt}.json"
    atomic(inside(root, raw_path), body)
    receipt = dict(schema=SCHEMA, kind=kind, attempt_id=attempt, raw_path=raw_path,
                   raw_sha256=digest(body), bytes=len(body), requested_at=started,
                   captured_at=finished, provider_as_of=None,
                   timestamp_authority="LOCAL_WRITER_NOT_INDEPENDENT_TIMESTAMP", **meta)
    atomic(inside(root, receipt_path), encoded(receipt))
    return {"receipt_path": receipt_path, "receipt_sha256": digest(encoded(receipt)), "receipt": receipt}


def capture_http(root, kind, url, *, credential=None, transport=http_transport, clock=utc):
    started = clock()
    try:
        r = transport(url, credential=credential)
        finished = clock()
        if r.final_url != url:
            raise ValueError("UNEXPECTED_FINAL_URL")
        if len(r.body) > MAX_BYTES:
            raise ValueError("RESPONSE_SIZE_LIMIT")
        # Never save request headers, cookies, tokens, or response auth material.
        headers = {k.lower(): v for k, v in r.headers.items() if k.lower() in
                   {"date", "last-modified", "content-type", "etag", "cache-control", "age"}}
        state = "CAPTURED" if r.status == 200 else (
            "ACCESS_DENIED" if r.status in (401, 403) else "RATE_LIMITED" if r.status == 429 else "HTTP_ERROR")
        return retain(root, kind, r.body, started, finished, url=url, final_url=r.final_url,
                      method="DOCUMENTED_API" if credential else "PUBLIC_HTTP", status=state,
                      http_status=r.status, headers=headers)
    except (OSError, ValueError) as exc:
        # Exception messages may contain credentials or URLs; retain only class.
        return retain(root, kind, b"", started, clock(), url=url, final_url=None,
                      method="HTTP", status="TRANSPORT_FAILED", error_type=type(exc).__name__)


def capture_file(root, kind, path, *, clock=utc):
    started = clock()
    body = Path(path).read_bytes()
    if len(body) > MAX_BYTES:
        raise ValueError("IMPORT_SIZE_LIMIT")
    return retain(root, kind, body, started, clock(), status="CAPTURED",
                  method="LOCAL_FILE_FIRST_OBSERVATION", original_filename=Path(path).name)


def verified_raw(root, binding):
    receipt_bytes = inside(root, binding["receipt_path"]).read_bytes()
    if digest(receipt_bytes) != binding["receipt_sha256"]:
        raise ValueError("RECEIPT_HASH_MISMATCH")
    r = json.loads(receipt_bytes)
    if r != binding["receipt"] or r["schema"] != SCHEMA:
        raise ValueError("RECEIPT_BINDING_MISMATCH")
    raw = inside(root, r["raw_path"]).read_bytes()
    if digest(raw) != r["raw_sha256"] or len(raw) != r["bytes"]:
        raise ValueError("RAW_HASH_OR_SIZE_MISMATCH")
    if instant(r["requested_at"]) > instant(r["captured_at"]):
        raise ValueError("RECEIPT_CLOCK_ORDER")
    return raw


class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.skipping = False
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"): self.skipping = True
    def handle_endtag(self, tag):
        if tag in ("script", "style"): self.skipping = False
    def handle_data(self, text):
        if not self.skipping and text.strip(): self.parts.append(text.strip())


def text_of(raw):
    p = Text(); p.feed(raw.decode("utf-8")); return "\n".join(p.parts)


def parse_schedule(raw, date):
    obj = json.loads(raw)
    if not any(x.get("abbreviation") == "NBA" for x in obj.get("leagues", [])):
        raise ValueError("SCHEDULE_LEAGUE_MISMATCH")
    events = []
    for e in obj["events"]:
        if len(e["competitions"]) != 1: raise ValueError("AMBIGUOUS_COMPETITION")
        c = e["competitions"][0]
        if len(c["competitors"]) != 2: raise ValueError("AMBIGUOUS_COMPETITORS")
        teams = {x["homeAway"]: x["team"] for x in c["competitors"]}
        start = instant(c["date"])
        if start != instant(e["date"]): raise ValueError("SCHEDULE_START_CONFLICT")
        if start.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat() != date:
            raise ValueError("SCHEDULE_DATE_MISMATCH")
        row = {"event_id": "NBA:" + str(e["id"]), "league": "NBA", "target": TARGET,
               "scheduled_start": start.isoformat(), "schedule_status": c["status"]["type"]["name"],
               "schedule_state": c["status"]["type"]["state"], "season": e["season"]["year"]}
        for side in ("home", "away"):
            row[side] = canonical(teams[side]["abbreviation"])
            row[side + "_espn_id"] = str(teams[side]["id"])
            row[side + "_nba_id"] = TEAMS[row[side]]
        if row["home"] == row["away"]: raise ValueError("SAME_TEAM")
        events.append(row)
    ids = Counter(e["event_id"] for e in events)
    keys = Counter((e["home"], e["away"], e["scheduled_start"]) for e in events)
    if any(x > 1 for x in (*ids.values(), *keys.values())):
        raise ValueError("DUPLICATE_SCHEDULE_EVENT")
    return events


def parse_dt_public(raw):
    """Read flat, literal game records from public HTML. Never execute site JS."""
    html = raw.decode("utf-8")
    access = re.findall(r"\bhas_access:([01])\b", html)
    if len(access) != 1: raise ValueError("DT_PAGE_SCHEMA_CHANGED")
    records = []
    for fragment in re.findall(r'\{game_id:\d+,[^{}]*\}', html):
        # Exact observed flat object grammar; quoted strings cannot contain keys.
        tokens = re.findall(r'(\w+):("(?:[^"\\]|\\.)*"|null|-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?:,|$)', fragment[1:-1])
        if not tokens or len({k for k, v in tokens}) != len(tokens):
            raise ValueError("DT_RECORD_SCHEMA_CHANGED")
        rec = {}
        for k, v in tokens:
            rec[k] = json.loads(v) if v == "null" or v.startswith('"') else float(v) if any(t in v for t in ".eE") else int(v)
        for k in ("game_id", "home_alias", "away_alias", "home_team_id", "away_team_id", "game_dttm", "status_id", "p_home_score", "p_away_score", "update_dt"):
            if k not in rec: raise ValueError("DT_REQUIRED_FIELD_MISSING:" + k)
        records.append(rec)
    if not records: raise ValueError("DT_NO_GAME_RECORDS")
    return {"records": records, "access": int(access[0]), "source": "public_html"}


def parse_dt_api(raw):
    records = json.loads(raw)
    if not isinstance(records, list) or any(not isinstance(x, dict) for x in records):
        raise ValueError("DT_API_SCHEMA_CHANGED")
    return {"records": records, "access": 1, "source": "documented_v2_api"}


def provider_instant(value):
    # A date, naive update_dt, or HTTP Date is NOT a provider as-of instant.
    try: return instant(value).isoformat()
    except (ValueError, TypeError): return None


def dt_for_event(parsed, event, methodology):
    matches = []
    for r in parsed["records"]:
        if canonical(r.get("home_alias")) == event["home"] and canonical(r.get("away_alias")) == event["away"]:
            # The documented game_dttm is Eastern time; update_dt zone is NOT documented.
            start = datetime.fromisoformat(r["game_dttm"])
            if start.tzinfo is None: start = start.replace(tzinfo=ZoneInfo("America/New_York"))
            if start.astimezone(timezone.utc) == instant(event["scheduled_start"]): matches.append(r)
    if len(matches) != 1: raise ValueError("DT_EVENT_MISSING" if not matches else "DT_EVENT_AMBIGUOUS")
    r = matches[0]
    if parsed["source"] == "documented_v2_api" and r.get("season") != event["season"]:
        raise ValueError("DT_SEASON_MISMATCH")
    for side in ("home", "away"):
        if r[side + "_team_id"] != event[side + "_nba_id"]: raise ValueError("DT_TEAM_ID_MISMATCH")
    reasons = []
    if r.get("status_id") != 1: reasons.append("POST_START_SOURCE")
    if parsed["access"] != 1: reasons.append("SUBSCRIPTION_REQUIRED")
    margin = None
    if parsed["access"] == 1:
        if parsed["source"] == "documented_v2_api":
            if r.get("p_home_mov") is not None: margin = number(r["p_home_mov"])
        elif r.get("p_home_score") is not None and r.get("p_away_score") is not None:
            margin = number(r["p_home_score"]) - number(r["p_away_score"])
    if margin is None: reasons.append("PROJECTION_UNAVAILABLE")
    if margin is not None and r.get("p_home_score") is not None and r.get("p_away_score") is not None:
        if abs(margin - (number(r["p_home_score"]) - number(r["p_away_score"]))) > .01:
            reasons.append("PROVIDER_MARGIN_SCORE_CONFLICT")
    generation = None
    if event["season"] == 2027 and "2026-27:" in methodology and "current model's first live season" in methodology:
        generation = "dunksandthrees.game_predictions.2026_27.current_live"
    else: reasons.append("MODEL_GENERATION_UNVERIFIED")
    if provider_instant(r.get("update_dt")) is None: reasons.append("PROVIDER_TIMEZONE_UNKNOWN")
    return {"values": {"home_margin": margin}, "source_model_version": generation,
            "provider_generation": generation, "provider_build_id": None,
            "source_as_of": provider_instant(r.get("update_dt")), "provider_as_of_raw": r.get("update_dt"),
            "forecast_identity": f"DT:{r['game_id']}:{r.get('update_dt')}",
            "provider_event_id": str(r["game_id"]), "provider_status": r.get("status_id"),
            "exclusions": reasons, "extraction_fields": ["p_home_mov"] if parsed["source"] == "documented_v2_api" else ["p_home_score", "p_away_score"],
            "provider_record": r}


def parse_databallr_dom(raw, season):
    obj = json.loads(raw)
    if obj.get("url") != DB or obj.get("title") != "NBA Team Stats - Six Factor Analysis | databallr":
        raise ValueError("DB_ORIGIN_OR_TITLE_MISMATCH")
    text = obj["page_text"]
    label = f"{season-1}-{str(season)[-2:]}"
    for phrase in (f"Six Factor Analysis • {label} Season", "calculated directly from box-score components",
                   "positive values are good for OFF, DEF, Net, and all six factor components"):
        if phrase not in text: raise ValueError("DB_SEMANTICS_CHANGED")
    controls = {x["text"]: x["html"] for x in obj["controls"]}
    for name in ("NBA", "Full Season", "Overall"):
        if "text-primary-foreground" not in controls.get(name, ""): raise ValueError("DB_FILTER_UNVERIFIED:" + name)
    if label not in controls or "All" not in controls or "bg-muted/80" not in controls.get("Per 100", ""):
        raise ValueError("DB_UNITS_OR_SEASON_UNVERIFIED")
    if len(obj.get("sliders", [])) != 2 or any(s["value"] != "0" for s in obj["sliders"]):
        raise ValueError("DB_LUCK_ADJUSTMENT_UNVERIFIED_OR_NONZERO")
    rows = obj["table_rows"]
    headers = [r for r in rows if "Team" in r and all(k in r for k in FACTORS)]
    if len(headers) != 1 or len(set(headers[0])) != len(headers[0]): raise ValueError("DB_HEADERS_INVALID")
    header = headers[0]; result = {}
    for row in rows[rows.index(header)+1:]:
        if len(row) != len(header): raise ValueError("DB_ROW_WIDTH")
        cells = dict(zip(header, row)); team = cells["Team"]
        if team == "AVG": continue
        team = canonical(team)
        if team in result: raise ValueError("DB_DUPLICATE_TEAM")
        factors = {}
        for k in FACTORS:
            # Discard only the separately displayed rank, never interpret it as value.
            if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:\n#\d+)?", cells[k]): raise ValueError("DB_FACTOR_INVALID")
            factors[k] = number(float(cells[k].split("\n")[0]))
        result[team] = factors
    if set(result) != set(TEAMS): raise ValueError("DB_TEAM_CENSUS_INCOMPLETE")
    return result


def baseline_for_event(raw, event):
    card = json.loads(raw)
    if card.get("league") != "NBA": raise ValueError("B0_LEAGUE_MISMATCH")
    matches = [f for f in card["forecasts"] if f.get("event_id") == event["event_id"]]
    if len(matches) != 1: raise ValueError("B0_EVENT_MISSING_OR_DUPLICATE")
    f = matches[0]
    if instant(f["start_time_utc"]) != instant(event["scheduled_start"]): raise ValueError("B0_START_MISMATCH")
    for side in ("home", "away"):
        if str(f[side + "_id"]) != event[side + "_espn_id"]: raise ValueError("B0_TEAM_ID_MISMATCH")
    if not f["model_id"].startswith("nba.fixed_parent."): raise ValueError("B0_WRONG_HEAD")
    margin = number(f["diagnostics"]["home_margin"])
    for key in ("forecast_procedure_id", "input_snapshot_hash", "model_state_config_hash", "numerical_identity"):
        if not f.get(key): raise ValueError("B0_LINEAGE_MISSING:" + key)
    times = (instant(card["as_of_utc"]), instant(card["generated_at_utc"]), instant(event["scheduled_start"]))
    if not times[0] <= times[1] < times[2]: raise ValueError("B0_ORIGINAL_CHRONOLOGY")
    identity = f["numerical_identity"]
    for k, expected in (("model_id", f["model_id"]), ("event_id", event["event_id"])):
        if identity.get(k) != expected: raise ValueError("B0_NUMERICAL_IDENTITY_MISMATCH:" + k)
    if instant(identity["cutoff_utc"]) != times[0] or instant(identity["start_time_utc"]) != times[2]:
        raise ValueError("B0_NUMERICAL_CLOCK_MISMATCH")
    return {"values": {"home_margin": margin}, "source_model_version": f["model_id"],
            "source_as_of": card["as_of_utc"], "original_created_at": card["generated_at_utc"],
            "forecast_identity": f["numerical_identity"]["identity_sha256"],
            "original_forecast": f, "exclusions": []}


def bind_source(root, event, key, value, binding, cutoff, extra_reasons=()):
    r = binding["receipt"]
    reasons = list(value.get("exclusions", [])) + list(extra_reasons)
    if r["status"] != "CAPTURED": reasons.append(r["status"])
    if not instant(r["captured_at"]) <= instant(cutoff) < instant(event["scheduled_start"]):
        reasons.append("CAPTURE_AFTER_EVENT_CUTOFF")
    if value.get("source_as_of") and instant(value["source_as_of"]) > instant(r["captured_at"]):
        reasons.append("FUTURE_PROVIDER_TIMESTAMP")
    payload = {k: event[k] for k in IDENTITY}
    payload.update(value)
    payload.update(captured_at=r["captured_at"], historical_record_type="live",
                   availability_basis="captured_before_cutoff" if not reasons else "unproven_or_unavailable",
                   raw_receipt={"path": r["raw_path"], "sha256": r["raw_sha256"], "extraction_review": "REVIEWED"},
                   acquisition=binding, parser_version=PARSER,
                   exclusions=sorted(set(reasons)))
    body = encoded(payload); path = f"normalized/{event['event_id'].replace(':', '_')}/{key}.json"
    atomic(inside(root, path), body)
    return {"artifact_path": path, "artifact_hash": digest(body), "payload": payload}


def verify_capture_source(payload, row, root):
    """Re-extract new-capture payloads during the real experiment audit/fit.

    A flag saying REVIEWED or a source hash alone cannot bless edited normalized
    values, invented provider times, a new generation, or altered team orientation.
    Legacy explicit datasets keep their previous contract; no legacy gate is relaxed.
    """
    root = Path(root)
    binding = payload["acquisition"]
    raw = verified_raw(root, binding)
    receipt = binding["receipt"]
    if receipt["status"] != "CAPTURED": raise ValueError("CAPTURE_NOT_SUCCESSFUL")
    if payload["captured_at"] != receipt["captured_at"]: raise ValueError("CAPTURE_TIME_BINDING")
    if payload["raw_receipt"]["path"] != receipt["raw_path"] or payload["raw_receipt"]["sha256"] != receipt["raw_sha256"]:
        raise ValueError("CAPTURE_RAW_BINDING")
    if payload.get("parser_version") != PARSER: raise ValueError("CAPTURE_PARSER_VERSION")
    verified_schedule = verified_raw(root, row["schedule_receipt"])
    slate = instant(row["scheduled_start"]).astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    events = parse_schedule(verified_schedule, slate)
    event = next((e for e in events if e["event_id"] == row["event_id"]), None)
    if event is None or any(row.get(k) != v for k, v in event.items()): raise ValueError("CAPTURE_SCHEDULE_IDENTITY")
    if row["schedule_receipt"]["receipt"]["status"] != "CAPTURED": raise ValueError("SCHEDULE_NOT_CAPTURED")
    if event["schedule_status"] != "STATUS_SCHEDULED" or event["schedule_state"] != "pre": raise ValueError("EVENT_NOT_SCHEDULED")
    cutoff = instant(row["feature_cutoff"])
    if not instant(row["schedule_receipt"]["receipt"]["captured_at"]) <= cutoff:
        raise ValueError("SCHEDULE_AFTER_CUTOFF")
    if not instant(receipt["captured_at"]) <= instant(row["observed_at"]) <= cutoff < instant(event["scheduled_start"]):
        raise ValueError("CAPTURE_EVENT_CHRONOLOGY")
    if cutoff > instant(event["scheduled_start"]) - timedelta(minutes=5): raise ValueError("CAPTURE_DEADLINE")
    kind = receipt["kind"]
    if kind == "B0":
        expected = baseline_for_event(raw, event)
        if instant(expected["original_created_at"]) > instant(receipt["captured_at"]): raise ValueError("B0_CREATED_AFTER_IMPORT")
    elif kind in ("dt_public", "dt_api"):
        if receipt.get("url") != (DT + (f"/games?date={slate}&days=1" if kind == "dt_public" else f"/api/v2/game-predictions?date={slate}&days=1")):
            raise ValueError("DT_CAPTURE_URL")
        evidence = payload["generation_evidence"]
        method = text_of(verified_raw(root, evidence))
        if evidence["receipt"].get("url") != DT + "/about/epm" or evidence["receipt"]["status"] != "CAPTURED":
            raise ValueError("GENERATION_EVIDENCE_ORIGIN")
        if instant(evidence["receipt"]["captured_at"]) > cutoff: raise ValueError("GENERATION_EVIDENCE_LATE")
        expected = dt_for_event(parse_dt_api(raw) if kind == "dt_api" else parse_dt_public(raw), event, method)
    elif kind == "db_dom":
        factors = parse_databallr_dom(raw, event["season"])
        expected = dict(values={"home_factors": factors[event["home"]], "away_factors": factors[event["away"]]},
                        source_model_version=FACTOR_VERSION, source_as_of=None,
                        units="points_per_100_possessions", sign="positive_good",
                        exclusions=["PROVIDER_AS_OF_UNKNOWN", "BROWSER_IMPORT_ORIGIN_NOT_INDEPENDENTLY_ATTESTED"])
    else: raise ValueError("UNKNOWN_CAPTURE_KIND")
    for k, v in expected.items():
        if k == "exclusions": continue
        if payload.get(k) != v: raise ValueError("CAPTURE_EXTRACTION_MISMATCH:" + k)
    if expected["exclusions"]: raise ValueError("CAPTURE_SOURCE_EXCLUDED:" + ";".join(expected["exclusions"]))
    if payload.get("exclusions") or row.get("opportunity_exclusions"): raise ValueError("CAPTURE_EXCLUSIONS_PRESENT")


def normalize(root, captures, date, *, clock=utc):
    schedule = verified_raw(root, captures["schedule"])
    if captures["schedule"]["receipt"]["status"] != "CAPTURED": raise ValueError("SCHEDULE_UNAVAILABLE")
    events = parse_schedule(schedule, date)
    parser_errors = {}; parsed = {}; raw = {}
    for key, binding in captures.items(): raw[key] = verified_raw(root, binding)
    for key, parser in (("dt_public", parse_dt_public), ("dt_api", parse_dt_api)):
        if key not in raw: continue
        try:
            if captures[key]["receipt"]["status"] != "CAPTURED": raise ValueError(captures[key]["receipt"]["status"])
            parsed[key] = parser(raw[key])
        except (ValueError, KeyError, TypeError, UnicodeError) as exc: parser_errors[key] = str(exc)
    method = text_of(raw["dt_method"]) if "dt_method" in raw else ""
    factors = None
    if "db_dom" in raw:
        try:
            seasons = {e["season"] for e in events}
            if len(seasons) != 1: raise ValueError("DB_SEASON_AMBIGUOUS")
            factors = parse_databallr_dom(raw["db_dom"], seasons.pop())
        except (ValueError, KeyError, TypeError, UnicodeError) as exc: parser_errors["db_dom"] = str(exc)
    rows = []
    for event in events:
        # An actual decision observation, individually bounded by tip-off minus 5m.
        completed = clock()
        cutoff = min(instant(completed), instant(event["scheduled_start"]) - timedelta(minutes=5)).isoformat()
        reasons = []
        if event["schedule_status"] != "STATUS_SCHEDULED" or event["schedule_state"] != "pre": reasons.append("EVENT_NOT_SCHEDULED")
        if instant(completed) >= instant(event["scheduled_start"]): reasons.append("POST_START")
        if instant(completed) > instant(cutoff): reasons.append("AFTER_CAPTURE_DEADLINE")
        row = dict(event, feature_cutoff=cutoff, capture_deadline=(instant(event["scheduled_start"])-timedelta(minutes=5)).isoformat(),
                   observed_at=completed, evidence_population="point_in_time_live", sources={},
                   capture_schema=SCHEMA, opportunity_exclusions=reasons, outcome=None,
                   schedule_receipt=captures["schedule"], source_states={})
        if "B0" in raw:
            try:
                b0 = baseline_for_event(raw["B0"], event)
                row["sources"]["B0"] = bind_source(root, event, "B0", b0, captures["B0"], cutoff, reasons)
                row["source_states"]["B0"] = "PRESERVED_ORIGINAL"
            except (ValueError, KeyError, TypeError) as exc: row["source_states"]["B0"] = str(exc)
        else: row["source_states"]["B0"] = "BASELINE_NOT_SUPPLIED"
        # API errors never silently fall back to a different authenticated vintage.
        dt_key = "dt_api" if "dt_api" in captures else "dt_public"
        if dt_key in parsed:
            try:
                b1 = dt_for_event(parsed[dt_key], event, method)
                b1["generation_evidence"] = captures.get("dt_method")
                row["sources"]["B1"] = bind_source(root, event, "B1", b1, captures[dt_key], cutoff, reasons)
                row["source_states"]["B1"] = "PARSED" if not b1["exclusions"] else ";".join(b1["exclusions"])
            except (ValueError, KeyError, TypeError) as exc: row["source_states"]["B1"] = str(exc)
        else: row["source_states"]["B1"] = parser_errors.get(dt_key, "NOT_CAPTURED")
        if factors is not None:
            season_label = f"{event['season']-1}-{str(event['season'])[-2:]}"
            v = dict(source_model_version=FACTOR_VERSION, provider_generation=season_label + " box-score six-factor display",
                     provider_build_id=None, source_as_of=None, provider_as_of_raw=None,
                     units="points_per_100_possessions", sign="positive_good",
                     values={"home_factors": factors[event["home"]], "away_factors": factors[event["away"]]},
                     exclusions=["PROVIDER_AS_OF_UNKNOWN", "BROWSER_IMPORT_ORIGIN_NOT_INDEPENDENTLY_ATTESTED"])
            row["sources"]["databallr"] = bind_source(root, event, "databallr", v, captures["db_dom"], cutoff, reasons)
            row["source_states"]["databallr"] = "PARSED_PROVIDER_AS_OF_UNKNOWN"
        else: row["source_states"]["databallr"] = parser_errors.get("db_dom", "HTML_SHELL_ONLY_RENDERED_CAPTURE_REQUIRED")
        rows.append(row)
    return rows, parser_errors


def run_capture(output, date, *, baseline=None, databallr_dom=None, use_dt_api=False,
                transport=http_transport, clock=utc):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    run_id = "nba-pregame-" + uuid.uuid4().hex
    started = clock()
    # Date is a requested schedule, never an as-of clock. Reject malformed dates.
    day = datetime.strptime(date, "%Y-%m-%d").date()
    captures = {}
    if baseline: captures["B0"] = capture_file(root, "B0", baseline, clock=clock)
    if databallr_dom: captures["db_dom"] = capture_file(root, "db_dom", databallr_dom, clock=clock)
    specs = [("schedule", ESPN + f"?dates={day:%Y%m%d}&limit=1000"),
             ("dt_public", DT + f"/games?date={date}&days=1"),
             ("dt_method", DT + "/about/epm"), ("db_http", DB)]
    for key, url in specs:
        captures[key] = capture_http(root, key, url, transport=transport, clock=clock)
    api_status = "NOT_REQUESTED"
    if use_dt_api:
        key = os.environ.get("DUNKS_AND_THREES_API_KEY")
        if key:
            captures["dt_api"] = capture_http(root, "dt_api", DT + f"/api/v2/game-predictions?date={date}&days=1",
                                              credential=key, transport=transport, clock=clock)
            api_status = captures["dt_api"]["receipt"]["status"]
        else: api_status = "CREDENTIAL_NOT_CONFIGURED"
    errors = {}
    try: rows, errors = normalize(root, captures, date, clock=clock)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        rows = []; errors["normalization"] = str(exc)
    dataset = dict(schema=SCHEMA, parser_version=PARSER, run_id=run_id, rows=rows)
    atomic(root / "dataset.json", encoded(dataset))
    audits = {stage: audit(rows, root, stage) for stage in ("C1", "C2")}
    repo = Path(__file__).resolve().parents[1]
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True)
    code_paths = ("research/nba_pregame_capture.py", "research/nba_forecast_combination.py",
                  "scripts/capture_nba_combination_sources.py", "scripts/nhl_atomic_capture.py",
                  "data/research/nba_forecast_combination_v1/protocol.json")
    report = dict(schema=SCHEMA, run_id=run_id, started_at=started, completed_at=clock(),
                  date=date, timezone="America/Los_Angeles", captures=captures, parser_errors=errors,
                  api_status=api_status, schedule_status="UNAVAILABLE_OR_INVALID" if "normalization" in errors else "CAPTURED",
                  events=len(rows), pregame_opportunities=sum(not r["opportunity_exclusions"] for r in rows),
                  baseline_preserved=sum("B0" in r["sources"] for r in rows),
                  external_margin_values=sum(r.get("sources", {}).get("B1", {}).get("payload", {}).get("values", {}).get("home_margin") is not None for r in rows),
                  databallr_event_pairs=sum("databallr" in r["sources"] for r in rows),
                  source_eligible={stage: audits[stage]["eligible_events"] for stage in audits},
                  fitting_eligible=0, fitting_note="No outcomes ingested; no fit attempted.",
                  audits=audits, source_states=[dict(event_id=r["event_id"], sources=r["source_states"], exclusions=r["opportunity_exclusions"]) for r in rows],
                  code_sha256=digest(Path(__file__).read_bytes()),
                  code_pins={p: digest((repo/p).read_bytes()) for p in code_paths},
                  repository_revision=revision.stdout.strip() if revision.returncode == 0 else None,
                  python_version=sys.version, normalized_values_used_by_fitted_model=False,
                  execution_status="PARTIAL" if errors or any(a["eligible_events"] < len(rows) for a in audits.values()) else "COMPLETED",
                  predictive_validation="NOT_ASSESSED", publication_eligibility="INELIGIBLE",
                  wagering_authority="OFF", canonical_registration=False, coefficients_fitted=False)
    atomic(root / "report.json", encoded(report))
    atomic(root / "manifest.json", encoded({str(p.relative_to(root)): digest(p.read_bytes())
                                             for p in sorted(root.rglob("*")) if p.is_file()}))
    return report
