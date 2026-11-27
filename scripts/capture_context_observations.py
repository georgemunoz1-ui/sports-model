"""Research-only venue/weather acquisition. Does not modify forecasts or admission.

Provider team/stadium crosswalks must be independently reviewed and pinned.
Source capture is prospective, never a substitute for a retained pregame artifact.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
import re
import urllib.request
from scripts.recovery_capture import write_once, save_json, utc
from scripts.source_attestation import instant, sha256, attest_sources
from scripts.cbb_reconciliation_gate import parse

NWS = "https://api.weather.gov"
SR = "https://api.sportradar.com"

def require(ok, code):
    if not ok:
        raise ValueError(code)

def nonblank(x):
    return isinstance(x, str) and bool(x.strip())

def number(x):
    return type(x) in (int, float) and math.isfinite(x)

def pinned(path, expected):
    raw = Path(path).read_bytes()
    require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None and sha256(raw) == expected,
            "EVENT_BINDING_PIN_MISMATCH")
    return parse(raw)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("SOURCE_REDIRECT_REFUSED")

def fetch(root, url, headers, kind):
    requested = utc()
    receipt = {"url": url, "kind": kind, "requested_at_utc": requested}
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=25) as response:
            require(response.status == 200 and response.geturl() == url, "SOURCE_URL_OR_STATUS_MISMATCH")
            raw = response.read(20_000_001)
        retrieved = utc()
        require(len(raw) <= 20_000_000, "RESPONSE_LIMIT_EXCEEDED")
        digest = sha256(raw)
        relative = "raw/" + digest + ".json"
        write_once(root / relative, raw)
        receipt.update(status="CAPTURED", retrieved_at_utc=retrieved,
                       raw_sha256=digest, raw_path=relative)
        data = parse(raw)
        return receipt, data
    except Exception as exc:
        # Do not retain exception messages that might include credentials.
        receipt.update(status="FAILED", retrieved_at_utc=utc(), error_type=type(exc).__name__)
        return receipt, None
    finally:
        save_json(root / ("receipt-" + kind + ".json"), receipt)

def check_clock(receipts, kickoff, now):
    require(now < kickoff, "POST_OR_AT_START")
    for r in receipts:
        require(r["status"] == "CAPTURED", "SOURCE_ACQUISITION_FAILED")
        req, seen = instant(r["requested_at_utc"]), instant(r["retrieved_at_utc"])
        require(req <= seen <= now and seen < kickoff and now-seen <= timedelta(hours=6),
                "SOURCE_CHRONOLOGY_INVALID")

def weather_points_url(binding):
    require(binding["league"] == "NFL", "WRONG_LEAGUE")
    require(binding["roof"] == "outdoor", "ROOF_NOT_VERIFIED_OUTDOOR")
    lat, lon = binding["latitude"], binding["longitude"]
    require(number(lat) and number(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
            and nonblank(binding["stadium_id"]), "STADIUM_BINDING_INVALID")
    return NWS + f"/points/{lat:.4f},{lon:.4f}"

def hourly_url(points):
    p = points["properties"]
    url = p["forecastHourly"]
    require(isinstance(url, str) and re.fullmatch(
        r"https://api\.weather\.gov/gridpoints/[A-Z]{3}/-?\d+,-?\d+/forecast/hourly", url),
        "NWS_HOURLY_URL_INVALID")
    require(url == NWS + f"/gridpoints/{p['gridId']}/{p['gridX']},{p['gridY']}/forecast/hourly",
            "NWS_GRID_BINDING_MISMATCH")
    return url

def extract_weather(binding, points, forecast, receipts, now):
    kickoff = instant(binding["start_utc"])
    check_clock(receipts, kickoff, now)
    require(len(receipts) == 2 and receipts[0]["url"] == weather_points_url(binding)
            and receipts[1]["url"] == hourly_url(points), "NWS_RECEIPT_BINDING_MISMATCH")
    p = forecast["properties"]
    updated = instant(p["updateTime"] if "updateTime" in p else p["updated"])
    generated = instant(p["generatedAt"])
    received = instant(receipts[1]["retrieved_at_utc"])
    require(updated <= generated <= received and now-updated <= timedelta(hours=12),
            "NWS_FORECAST_VINTAGE_INVALID")
    periods = [x for x in p["periods"] if instant(x["startTime"]) <= kickoff < instant(x["endTime"])]
    require(len(periods) == 1, "NWS_HOUR_NOT_UNIQUE_OR_MISSING")
    hour = periods[0]
    temp, unit = hour["temperature"], hour["temperatureUnit"]
    require(number(temp) and unit in ("F", "C"), "NWS_TEMPERATURE_INVALID")
    wind = re.fullmatch(r"(\d+)(?: to (\d+))? mph", hour["windSpeed"])
    require(wind is not None, "NWS_WIND_FORMAT_UNSUPPORTED")
    low, high = int(wind[1]), int(wind[2] or wind[1])
    require(0 <= low <= high <= 200, "NWS_WIND_RANGE_INVALID")
    pop = hour["probabilityOfPrecipitation"]["value"]
    require(number(pop) and 0 <= pop <= 100, "NWS_PRECIP_PROBABILITY_MISSING")
    return {"event_id": binding["event_id"], "stadium_id": binding["stadium_id"],
            "temperature_f": temp if unit == "F" else temp*9/5+32,
            "wind_mph_low": low, "wind_mph_high": high,
            "precipitation_probability_pct": pop,
            "valid_from_utc": instant(hour["startTime"]).isoformat(),
            "valid_to_utc": instant(hour["endTime"]).isoformat(),
            "forecast_updated_utc": updated.isoformat(), "forecast_generated_utc": generated.isoformat(),
            "status": "OBSERVED_FORECAST_NOT_CONSUMED"}

def sr_url(binding):
    require(binding["league"] == "CBB", "WRONG_LEAGUE")
    day = datetime.strptime(binding["provider_schedule_date"], "%Y-%m-%d")
    access = binding["access_level"]
    require(access in ("trial", "production"), "SR_ACCESS_LEVEL_INVALID")
    return SR + f"/ncaamb/{access}/v8/en/games/{day:%Y/%m/%d}/schedule.json"

def extract_venue(binding, schedule, receipt, now):
    kickoff = instant(binding["start_utc"])
    check_clock([receipt], kickoff, now)
    require(receipt["url"] == sr_url(binding) and schedule["date"] == binding["provider_schedule_date"],
            "SR_SCHEDULE_BINDING_MISMATCH")
    expected = binding["sr_team_ids"]
    require(isinstance(expected, list) and len(expected) == 2
            and all(nonblank(x) for x in expected) and len(set(expected)) == 2
            and nonblank(binding["sr_venue_id"]), "SR_CROSSWALK_INVALID")
    games = [g for g in schedule["games"] if g.get("id") == binding["sr_game_id"]]
    require(len(games) == 1, "SR_EVENT_NOT_UNIQUE_OR_MISSING")
    g = games[0]
    require({g["home"]["id"], g["away"]["id"]} == set(expected), "SR_TEAM_IDENTITY_MISMATCH")
    require(g["status"] == "scheduled" and g.get("neutral_site") is True,
            "SR_NOT_EXPLICITLY_SCHEDULED_NEUTRAL")
    require(g["venue"]["id"] == binding["sr_venue_id"] and nonblank(g["venue"]["name"]),
            "SR_VENUE_IDENTITY_MISMATCH")
    scheduled = instant(g["scheduled"])
    require(abs((scheduled-kickoff).total_seconds()) <= 60
            and now < min(scheduled,kickoff), "SR_TIP_MISMATCH_OR_LATE")
    return {"event_id": binding["event_id"], "sr_game_id": g["id"],
            "sr_team_ids": expected, "sr_venue_id": g["venue"]["id"],
            "venue_name": g["venue"]["name"], "neutral_site": True,
            "sr_scheduled_utc": scheduled.isoformat(),
            "earliest_observed_start_utc": min(scheduled,kickoff).isoformat(),
            "status": "VENUE_OBSERVED_PENDING_INDEPENDENCE_AND_MAPPER_REVIEW"}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binding", required=True, type=Path)
    ap.add_argument("--binding-sha256", required=True)
    ap.add_argument("--output", required=True, type=Path)
    a = ap.parse_args()
    binding = pinned(a.binding, a.binding_sha256)
    require(nonblank(binding["event_id"]), "EVENT_ID_REQUIRED")
    require(instant(utc()) < instant(binding["start_utc"]), "POST_OR_AT_START")
    if binding["league"] == "NFL":
        url = weather_points_url(binding)
        contact = os.environ.get("NWS_USER_AGENT")
        require(nonblank(contact), "NWS_USER_AGENT_REQUIRED")
        headers = {"User-Agent": contact, "Accept": "application/geo+json"}
    elif binding["league"] == "CBB":
        url = sr_url(binding)
        key = os.environ.get("SPORTRADAR_API_KEY")
        require(nonblank(key), "SPORTRADAR_API_KEY_REQUIRED")
        headers = {"User-Agent": "sports-model-research", "Accept": "application/json", "x-api-key": key}
    else:
        raise ValueError("UNSUPPORTED_LEAGUE")
    a.output.mkdir(parents=True, exist_ok=False)
    write_once(a.output / "binding.json", a.binding.read_bytes())
    require(sha256((a.output / "binding.json").read_bytes()) == a.binding_sha256, "EVENT_BINDING_CHANGED")
    receipts = []
    try:
        r, data = fetch(a.output, url, headers, "primary")
        receipts.append(r)
        require(data is not None, "SOURCE_ACQUISITION_FAILED")
        if binding["league"] == "NFL":
            r2, hourly = fetch(a.output, hourly_url(data), headers, "hourly")
            receipts.append(r2)
            require(hourly is not None, "SOURCE_ACQUISITION_FAILED")
            result = extract_weather(binding, data, hourly, receipts, instant(utc()))
        else:
            result = extract_venue(binding, data, r, instant(utc()))
        status = "SOURCE_OBSERVATION_RETAINED"
    except Exception as exc:
        status = "SOURCE_OBSERVATION_BLOCKED"
        result = {"event_id": binding["event_id"], "error_type": type(exc).__name__,
                  "reason": str(exc) if isinstance(exc, ValueError) else "SCHEMA_OR_ACQUISITION_FAILURE"}
    report = {"schema": "sports.context_acquisition_candidate.v1", "status": status,
              "binding_sha256": a.binding_sha256, "sources": receipts, "observation": result,
              "market_overlay_enabled": False, "action_authority": False, "official_units": 0.0,
              "model_input_changed": False, "historical_pregame_eligibility": False}
    save_json(a.output / "report.json", report)
    if status == "SOURCE_OBSERVATION_RETAINED":
        proof = attest_sources([{"source": r["url"], "sha256": r["raw_sha256"],
                                 "fetched_at_utc": r["retrieved_at_utc"]} for r in receipts],
                               [a.output], instant(utc()).isoformat())
        save_json(a.output / "attestation.json", proof)
    save_json(a.output / "manifest.json", {"files": {str(p.relative_to(a.output)): sha256(p.read_bytes())
              for p in sorted(a.output.rglob("*")) if p.is_file()}})
    return 0 if status == "SOURCE_OBSERVATION_RETAINED" else 2

if __name__ == "__main__":
    raise SystemExit(main())
