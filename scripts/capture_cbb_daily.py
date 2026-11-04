"""Capture a Pacific men's D-I slate and separate DraftKings quote evidence, before or after tip."""

import argparse
import datetime as dt
import json
import math
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.recovery_capture import digest, save_json, utc, write_once

PACIFIC = ZoneInfo("America/Los_Angeles")
ESPN = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/"
)
STANDINGS = "https://site.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/standings"
NCAA = "https://sdataprod.ncaa.com/"
# Public GetContests_web persisted query advertised by the NCAA scoreboard.
NCAA_QUERY = "4bcb5e6432fa9da365c0c19af01b1f9015cc7eb5c21e7af2dba308784a166df7"


def ncaa_url(day):
    payload = {
        "sportCode": "MBB",
        "division": 1,
        "seasonYear": day.year - int(day.month < 7),
        "contestDate": day.strftime("%Y/%m/%d"),
    }
    params = {
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": NCAA_QUERY}},
        "variables": payload,
    }
    return (
        NCAA
        + "?"
        + urlencode(
            {k: json.dumps(v, separators=(",", ":")) for k, v in params.items()}
        )
    )


# Reviewed NCAA short names where ESPN's own location/short name/abbreviation disagree.
NCAA_ALIASES = {
    "2029": ["Ark.-Pine Bluff"],
    "3134": ["Champion Chris."],
    "94": ["Northern Ky."],
    "88": ["Southern Ind."],
    "2397": ["Milligan"],
    "2460": ["UNI"],
    "2155": ["Cornell College"],
    "2518": ["Regis (CO)"],
    "3246": ["Bethesda (CA)"],
    "2703": ["Western N.M."],
    "2333": ["Lewis & Clark"],
    "126956": ["Framingham St."],
    "2964": ["Central (IA)"],
    "494": ["Blue Mountain (MS)"],
    "3153": ["Randolph"],
    "126824": ["St. Mary-Woods"],
    "134743": ["Grace (CA)"],
    "2351": ["LMU (CA)"],
    "2511": ["Queens (NC)"],
    "2608": ["Saint Mary's (CA)"],
    "2433": ["ULM"],
    "2430": ["UNC Greensboro"],
    "2623": ["Missouri St."],
    "2448": ["N.C. A&T"],
    "2439": ["UNLV"],
    "2347": ["La. Christian"],
    "2856": ["California Baptist"],
    "21": ["San Diego St."],
}


def fetch(output, url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "sports-model-evidence-capture/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as res:
        body = res.read(30_000_001)
    if len(body) > 30_000_000:
        raise ValueError("SOURCE_TOO_LARGE")
    stamp = utc()
    sha = digest(body)
    name = "raw/" + sha + ".json"
    write_once(output / name, body)
    return body, {"url": url, "file": name, "sha256": sha, "retrieved_at_utc": stamp}


def sides(comp):
    competitors = comp["competitors"]
    pair = {r["homeAway"]: r for r in competitors}
    if (
        len(competitors) != 2
        or set(pair) != {"away", "home"}
        or pair["home"]["id"] == pair["away"]["id"]
    ):
        raise ValueError("TEAM_IDENTITY")
    return pair


def normalize(event, members):
    if len(event["competitions"]) != 1:
        raise ValueError("COMPETITION_IDENTITY")
    comp = event["competitions"][0]
    team = sides(comp)
    status = comp["status"]["type"]
    final = status["completed"] and status["name"] == "STATUS_FINAL"
    start = dt.datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError("NAIVE_TIP")
    row = {
        "event_id": "CBB:" + event["id"],
        "source_event_id": event["id"],
        "start_time_utc": start.isoformat(),
        "neutral_site": comp["neutralSite"],
        "status": status["name"],
        "completed": final,
        "season_type": event["season"]["type"],
    }
    for side, t in team.items():
        row.update(
            {
                side + "_id": t["id"],
                side + "_team": t["team"]["displayName"],
                side + "_d1": t["id"] in members,
                side + "_score": int(t["score"]) if final else None,
            }
        )
    row["both_d1"] = row["home_d1"] and row["away_d1"]
    if row["completed"] and (
        row["home_score"] == row["away_score"]
        or min(row["home_score"], row["away_score"]) <= 0
    ):
        raise ValueError("INVALID_FINAL")
    return row


def ncaa_events(body):
    data = json.loads(body)
    if data.get("errors") or not isinstance(
        (data.get("data") or {}).get("contests"), list
    ):
        raise ValueError("NCAA_SCOREBOARD_UNREADABLE")
    return data["data"]["contests"]


def label(x):
    return re.sub(
        r"[^a-z0-9]", "", x.lower().replace("state", "st").replace("saint", "st")
    )


def same_team(team, official):
    names = [
        team.get(k, "")
        for k in ("location", "shortDisplayName", "abbreviation", "displayName")
    ]
    names.extend(NCAA_ALIASES.get(team["id"], []))
    candidates = [
        official.get(k) or ""
        for k in ("nameShort", "name6Char", "name8Char", "seoname")
    ]
    return bool(({label(v) for v in names} & {label(v) for v in candidates}) - {""})


def match_ncaa(e, contest):
    t = sides(e["competitions"][0])
    n = {("home" if x["isHome"] else "away"): x for x in contest["teams"]}
    return set(n) == set(t) and all(same_team(t[s]["team"], n[s]) for s in t)


def american(value):
    if not re.fullmatch(r"[+-]?\d+", str(value)) or abs(int(value)) < 100:
        return None
    return int(value)


def empty_quote(row, receipt, source_state, quote_status):
    keys = (
        "event_id",
        "source_event_id",
        "both_d1",
        "away_team",
        "home_team",
        "start_time_utc",
        "completed",
    )
    result = {key: row[key] for key in keys}
    result.update(
        settlement="FULL_GAME_INCLUDING_OVERTIME",
        provider="ESPN",
        book=None,
        source_sha256=receipt.get("sha256"),
        source_file=receipt.get("file"),
        source_url=receipt["url"],
        quote_retrieved_at_utc=receipt.get("retrieved_at_utc"),
        provider_quote_observed_at_utc=None,
        source_state=source_state,
        quote_status=quote_status,
        timestamp_basis="ESPN pickcenter side.close; no provider tick",
    )
    fields = (
        "home_spread",
        "away_spread",
        "home_spread_price",
        "away_spread_price",
        "total",
        "over_price",
        "under_price",
        "home_ml_price",
        "away_ml_price",
    )
    result.update(dict.fromkeys(fields))
    return result


def quote(row, data, receipt):
    if str(data["header"]["id"]) != row["source_event_id"]:
        raise ValueError("QUOTE_EVENT_MISMATCH")
    if len(data["header"]["competitions"]) != 1:
        raise ValueError("QUOTE_COMPETITION_IDENTITY")
    comp = data["header"]["competitions"][0]
    t = sides(comp)
    if any(t[s]["id"] != row[s + "_id"] for s in t) or dt.datetime.fromisoformat(
        comp["date"]
    ) != dt.datetime.fromisoformat(row["start_time_utc"]):
        raise ValueError("QUOTE_EVENT_SCOPE_MISMATCH")
    books = [
        b
        for b in data.get("pickcenter", [])
        if b.get("provider", {}).get("name") == "DraftKings"
    ]
    if len(books) > 1:
        raise ValueError("AMBIGUOUS_BOOK")
    book = books[0] if books else {}
    st = comp["status"]["type"]
    pre = st["state"] == "pre" and dt.datetime.fromisoformat(
        receipt["retrieved_at_utc"]
    ) < dt.datetime.fromisoformat(row["start_time_utc"])
    r = empty_quote(row, receipt, st["name"], "UNQUOTED")
    if book:
        r["book"] = "DraftKings"
    if not pre and not (st["completed"] and st["name"] == "STATUS_FINAL"):
        r["quote_status"] = "NO_PREGAME_OR_FINAL_QUOTE"
        return r

    def legs(product, a, b):
        m = book.get(product, {})
        return m.get(a, {}).get("close", {}), m.get(b, {}).get("close", {})

    a, b = legs("pointSpread", "home", "away")
    if (
        american(a.get("odds"))
        and american(b.get("odds"))
        and all(x.get("line") is not None for x in (a, b))
    ):
        ah, bh = float(a["line"]), float(b["line"])
        if not math.isfinite(ah) or ah + bh != 0:
            raise ValueError("SPREAD_COMPLEMENTS")
        r.update(
            home_spread=ah,
            away_spread=bh,
            home_spread_price=american(a["odds"]),
            away_spread_price=american(b["odds"]),
        )
    a, b = legs("total", "over", "under")
    if (
        american(a.get("odds"))
        and american(b.get("odds"))
        and a.get("line")
        and b.get("line")
    ):
        if not a["line"].lower().startswith("o") or not b["line"].lower().startswith(
            "u"
        ):
            raise ValueError("TOTAL_SIDE")
        line = float(a["line"][1:])
        if not math.isfinite(line) or line <= 0 or line != float(b["line"][1:]):
            raise ValueError("TOTAL_MISMATCH")
        r.update(
            total=line, over_price=american(a["odds"]), under_price=american(b["odds"])
        )
    a, b = legs("moneyline", "home", "away")
    if american(a.get("odds")) and american(b.get("odds")):
        r.update(home_ml_price=american(a["odds"]), away_ml_price=american(b["odds"]))
    if any(r[k] is not None for k in ("home_spread", "total", "home_ml_price")):
        r["quote_status"] = "REPORTED_CLOSE" if st["completed"] else "CAPTURED_PRETIP"
    return r


def daily(day, output, get=fetch):
    output.mkdir(parents=True, exist_ok=False)
    receipts = []
    failures = []
    events = {}
    official = {}
    key = day.strftime("%Y%m%d")
    season = day.year + int(day.month >= 7)

    def acquire(url):
        try:
            data, rec = get(output, url)
            receipts.append(rec)
            return data, rec
        except Exception as ex:
            failures.append({"url": url, "reason": str(ex)})
            raise

    try:
        raw, standing = acquire(f"{STANDINGS}?season={season}&level=3")
        s = json.loads(raw)
        if s["season"]["year"] != season:
            raise ValueError("DIVISION_SEASON_MISMATCH")
        members = {
            v["team"]["id"] for c in s["children"] for v in c["standings"]["entries"]
        }
        if len(members) < 300:
            raise ValueError("INCOMPLETE_DIVISION_DIRECTORY")
        for offset in (-1, 0, 1):
            d = day + dt.timedelta(days=offset)
            raw, rec = acquire(
                f"{ESPN}scoreboard?dates={d:%Y%m%d}&limit=1000&groups=50"
            )
            if d == day:
                primary = rec
            for e in json.loads(raw)["events"]:
                if (
                    dt.datetime.fromisoformat(e["date"]).astimezone(PACIFIC).date()
                    != day
                ):
                    continue
                row = normalize(e, members)
                eid = e["id"]
                if eid in events and row != events[eid][0]:
                    raise ValueError("CONFLICTING_SCOREBOARD")
                events[eid] = (row, e)
        for d in (day, day + dt.timedelta(days=1)):
            raw, _ = acquire(ncaa_url(d))
            for c in ncaa_events(raw):
                if (
                    dt.datetime.fromtimestamp(c["startTimeEpoch"], PACIFIC).date()
                    == day
                ):
                    official[c["contestId"]] = c
        unmatched = set(official)
        issues = []
        for row, e in events.values():
            ids = [i for i in unmatched if match_ncaa(e, official[i])]
            if len(ids) != 1:
                issues.append(
                    {"event_id": row["event_id"], "issue": "IDENTITY_NOT_CROSS_CHECKED"}
                )
                continue
            i = ids[0]
            n = official[i]
            unmatched.remove(i)
            row["ncaa_contest_id"] = i
            nteams = {("home" if x["isHome"] else "away"): x for x in n["teams"]}
            official_start = dt.datetime.fromtimestamp(
                n["startTimeEpoch"], dt.timezone.utc
            )
            row["ncaa_start_time_utc"] = official_start.isoformat()
            if dt.datetime.fromisoformat(row["start_time_utc"]) != official_start:
                issues.append(
                    {
                        "event_id": row["event_id"],
                        "issue": "TIP_RECONCILIATION_REQUIRED",
                    }
                )
            disagreed_final = row["completed"] != (n["gameState"] == "F")
            if disagreed_final or (
                row["completed"]
                and any(
                    row[side + "_score"] != nteams[side]["score"] for side in nteams
                )
            ):
                issues.append(
                    {
                        "event_id": row["event_id"],
                        "issue": "FINAL_RECONCILIATION_REQUIRED",
                    }
                )
        rows = [
            r
            for r, e in sorted(
                events.values(),
                key=lambda v: (v[0]["start_time_utc"], v[0]["event_id"]),
            )
        ]
        save_json(
            output / f"schedule-{key}.json",
            {
                "date": key,
                "timezone": PACIFIC.key,
                "source": primary,
                "division_source": standing,
                "events": rows,
            },
        )

        def market(row):
            url = ESPN + "summary?event=" + row["source_event_id"]
            receipt = {"url": url}
            try:
                raw, receipt = acquire(url)
                return quote(row, json.loads(raw), receipt)
            except (KeyError, ValueError, OSError, TypeError, IndexError) as exc:
                result = empty_quote(row, receipt, None, "QUOTE_SOURCE_UNAVAILABLE")
                result["issue"] = str(exc)
                return result

        with ThreadPoolExecutor(max_workers=8) as pool:
            quotes = list(pool.map(market, rows))
        issues.extend(
            {
                "event_id": r["event_id"],
                "issue": r["quote_status"],
                "detail": r["issue"],
            }
            for r in quotes
            if r["quote_status"] == "QUOTE_SOURCE_UNAVAILABLE"
        )
        save_json(
            output / f"quotes-{key}.json",
            {"date": key, "timezone": PACIFIC.key, "quotes": quotes},
        )
        coverage = {
            "status": "RECONCILED"
            if not unmatched and not issues
            else "REQUIRES_REVIEW",
            "espn_events": len(rows),
            "ncaa_events": len(official),
            "d1_vs_d1": sum(r["both_d1"] for r in rows),
            "outside_d1_pair_scope": sum(not r["both_d1"] for r in rows),
            "unmatched_ncaa": [official[k] for k in sorted(unmatched)],
            "issues": issues,
        }
    except (KeyError, ValueError, OSError, TypeError, IndexError) as exc:
        coverage = {"status": "BLOCKED", "reason": str(exc)}
    save_json(output / "coverage.json", coverage)
    save_json(
        output / "manifest.json",
        {
            "date": key,
            "sources": sorted(receipts, key=lambda x: x["url"]),
            "failures": failures,
            "finished_at_utc": utc(),
        },
    )
    return coverage


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = daily(args.date, args.output)
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "RECONCILED" else 2)
