"""Capture a Pacific men's D-I slate and separate DraftKings quote evidence, before or after tip."""

import argparse
import datetime as dt
import json
import math
import re
import sys
import urllib.request
from collections import Counter
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
    if comp["id"] != event["id"] or any(
        t["id"] != t["team"]["id"] for t in team.values()
    ):
        raise ValueError("TEAM_OR_COMPETITION_IDENTITY")
    status = comp["status"]["type"]
    final = (
        status["completed"] is True
        and status["name"] == "STATUS_FINAL"
        and status["state"] == "post"
    )
    start = dt.datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
    if start.tzinfo is None or dt.datetime.fromisoformat(comp["date"]) != start:
        raise ValueError("COMPETITION_TIP_MISMATCH")
    if type(comp["neutralSite"]) is not bool:
        raise ValueError("INVALID_VENUE_FLAG")
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
        if final and not re.fullmatch(r"[0-9]+", str(t["score"])):
            raise ValueError("INVALID_FINAL_SCORE")
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
    if (
        contest.get("sportUrl", "basketball-men") != "basketball-men"
        or len(contest["teams"]) != 2
        or any(type(x["isHome"]) is not bool for x in contest["teams"])
    ):
        return False
    n = {("home" if x["isHome"] else "away"): x for x in contest["teams"]}
    return set(n) == set(t) and all(same_team(t[s]["team"], n[s]) for s in t)


def ncaa_identity(contest):
    return contest["startTimeEpoch"], {
        t["isHome"]: (t.get("nameShort"), t.get("seoname")) for t in contest["teams"]
    }


def ncaa_final_scores(contest):
    if contest["gameState"] != "F":
        return {}
    return {
        ("home" if t["isHome"] else "away"): t.get("score") for t in contest["teams"]
    }


def reconcile_event(event, espn_receipt, contest, ncaa_receipt):
    """Reproduce one event's settlement evidence from the two specific scoreboards."""
    row = normalize(event, set())
    matched = contest is not None and match_ncaa(event, contest)
    ncaa_state = contest["gameState"] if matched else None
    ncaa_scores = ncaa_final_scores(contest) if matched else {}
    evidence = {
        k: row[k]
        for k in ("event_id", "start_time_utc", "home_id", "away_id", "neutral_site")
    }
    evidence.update(
        espn_scoreboard_url=espn_receipt["url"],
        espn_scoreboard_sha256=espn_receipt["sha256"],
        ncaa_scoreboard_url=ncaa_receipt["url"] if matched else None,
        ncaa_scoreboard_sha256=ncaa_receipt["sha256"] if matched else None,
        ncaa_contest_id=contest["contestId"] if matched else None,
        espn_status=row["status"],
        ncaa_status=ncaa_state,
        espn_home_score=row["home_score"],
        espn_away_score=row["away_score"],
        ncaa_home_score=ncaa_scores.get("home"),
        ncaa_away_score=ncaa_scores.get("away"),
        home_score=None,
        away_score=None,
    )
    issues = []
    if not matched:
        issues.append("IDENTITY_NOT_CROSS_CHECKED")
    else:
        if row["completed"] != (ncaa_state == "F") or (
            row["completed"]
            and any(
                type(ncaa_scores.get(s)) is not int
                or ncaa_scores[s] != row[s + "_score"]
                for s in ("home", "away")
            )
        ):
            issues.append("FINAL_RECONCILIATION_REQUIRED")
        if dt.datetime.fromtimestamp(
            contest["startTimeEpoch"], dt.timezone.utc
        ) != dt.datetime.fromisoformat(row["start_time_utc"]):
            issues.append("TIP_RECONCILIATION_REQUIRED")
    if issues:
        status = issues[0]
    elif row["completed"]:
        status = "FINAL_RECONCILED"
        evidence.update(home_score=row["home_score"], away_score=row["away_score"])
    else:
        status = "PENDING"
    return {**evidence, "status": status, "issues": issues}


def american(value):
    if not re.fullmatch(r"[+-]?\d+", str(value)) or abs(int(value)) < 100:
        return None
    return int(value)


def quoted_american(value):
    """Only explicit OFF/null means unavailable; malformed prices refuse the event."""
    if value is None or value == "OFF":
        return None
    if type(value) not in (int, str):
        raise ValueError("INVALID_QUOTE_PRICE")
    price = american(value)
    if price is None:
        raise ValueError("INVALID_QUOTE_PRICE")
    return price


def paired_market_quotes(data):
    """Return only unambiguous, same-book, two-sided full-game quotes.

    Duplicate book entries are rejected even when their bytes agree. Missing
    products and explicitly unavailable prices are unquoted; an offered product
    with incomplete scope rejects the whole event, never a partial attachment.
    """
    offers = data.get("pickcenter", [])
    if not isinstance(offers, list):
        raise ValueError("QUOTE_SCOPE_MISSING:pickcenter")
    books = []
    for offer in offers:
        provider = offer.get("provider") if isinstance(offer, dict) else None
        name = provider.get("name") if isinstance(provider, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError("QUOTE_SCOPE_MISSING:provider.name")
        if name == "DraftKings":
            books.append(offer)
    if len(books) > 1:
        raise ValueError("AMBIGUOUS_BOOK")
    if not books:
        return None, []
    book = books[0]
    rows = []
    for product, key, pair in (
        ("winner", "moneyline", ("home", "away")),
        ("margin", "pointSpread", ("home", "away")),
        ("total", "total", ("over", "under")),
    ):
        if key not in book:
            continue
        market = book[key]
        if not isinstance(market, dict):
            raise ValueError("QUOTE_SCOPE_MISSING:" + key)
        ticks = []
        for side in pair:
            leg = market.get(side)
            tick = leg.get("close") if isinstance(leg, dict) else None
            if not isinstance(tick, dict) or "odds" not in tick:
                raise ValueError("QUOTE_SCOPE_MISSING:" + key + "." + side)
            ticks.append(tick)
        prices = [quoted_american(t["odds"]) for t in ticks]
        if None in prices:
            continue
        lines = [None, None]
        if product != "winner":
            if any("line" not in t or t["line"] is None for t in ticks):
                raise ValueError("QUOTE_SCOPE_MISSING:" + key + ".line")
            values = [str(t["line"]) for t in ticks]
            if product == "total":
                if not all(
                    v.lower().startswith(prefix)
                    for v, prefix in zip(values, ("o", "u"))
                ):
                    raise ValueError("TOTAL_SIDE")
                values = [v[1:] for v in values]
            try:
                lines = [float(value) for value in values]
            except ValueError as exc:
                raise ValueError("INVALID_MARKET_LINE") from exc
            if not all(math.isfinite(value) for value in lines):
                raise ValueError("INVALID_MARKET_LINE")
            if product == "margin" and lines[0] != -lines[1]:
                raise ValueError("SPREAD_COMPLEMENTS")
            if product == "total" and (lines[0] <= 0 or lines[0] != lines[1]):
                raise ValueError("TOTAL_MISMATCH")
        rows.extend(
            {
                "product": product,
                "side": side,
                "line": line,
                "american_price": price,
            }
            for side, line, price in zip(pair, lines, prices)
        )
    return "DraftKings", rows


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
    book, contracts = paired_market_quotes(data)
    st = comp["status"]["type"]
    pre = st["state"] == "pre" and dt.datetime.fromisoformat(
        receipt["retrieved_at_utc"]
    ) < dt.datetime.fromisoformat(row["start_time_utc"])
    r = empty_quote(row, receipt, st["name"], "UNQUOTED")
    r["book"] = book
    if not pre and not (st["completed"] and st["name"] == "STATUS_FINAL"):
        r["quote_status"] = "NO_PREGAME_OR_FINAL_QUOTE"
        return r

    for contract in contracts:
        side = contract["side"]
        product = contract["product"]
        if product == "winner":
            r[side + "_ml_price"] = contract["american_price"]
        elif product == "margin":
            r[side + "_spread"] = contract["line"]
            r[side + "_spread_price"] = contract["american_price"]
        else:
            r["total"] = contract["line"]
            r[side + "_price"] = contract["american_price"]
    if any(r[k] is not None for k in ("home_spread", "total", "home_ml_price")):
        r["quote_status"] = "REPORTED_CLOSE" if st["completed"] else "CAPTURED_PRETIP"
    return r


def daily(day, output, get=fetch):
    output.mkdir(parents=True, exist_ok=False)
    receipts = []
    failures = []
    events = {}
    official = {}
    conflicting_events = set()
    conflicting_contests = set()
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
                    previous = events[eid][0]
                    if any(
                        row[k] != previous[k]
                        for k in (
                            "start_time_utc",
                            "home_id",
                            "away_id",
                            "neutral_site",
                        )
                    ):
                        raise ValueError("CONFLICTING_ESPN_IDENTITY")
                    conflicting_events.add(eid)
                events[eid] = (row, e, rec)
        for d in (day, day + dt.timedelta(days=1)):
            raw, rec = acquire(ncaa_url(d))
            for c in ncaa_events(raw):
                if (
                    dt.datetime.fromtimestamp(c["startTimeEpoch"], PACIFIC).date()
                    == day
                ):
                    key_id = c["contestId"]
                    if key_id in official:
                        previous = official[key_id][0]

                        if ncaa_identity(c) != ncaa_identity(previous):
                            raise ValueError("CONFLICTING_NCAA_IDENTITY")
                        if c["gameState"] != previous["gameState"] or ncaa_final_scores(
                            c
                        ) != ncaa_final_scores(previous):
                            conflicting_contests.add(key_id)
                    official[key_id] = (c, rec)
        unmatched = set(official)
        issues = []
        reconciliations = []
        matches = {
            eid: [i for i, (c, _) in official.items() if match_ncaa(e, c)]
            for eid, (_, e, _) in events.items()
        }
        claims = Counter(i for ids in matches.values() for i in ids)
        for eid, (row, e, rec) in events.items():
            ids = matches[eid]
            n = ncaa_rec = None
            if len(ids) == 1 and claims[ids[0]] == 1:
                i = ids[0]
                n, ncaa_rec = official[i]
                unmatched.remove(i)
                row["ncaa_contest_id"] = i
                row["ncaa_start_time_utc"] = dt.datetime.fromtimestamp(
                    n["startTimeEpoch"], dt.timezone.utc
                ).isoformat()
            result = reconcile_event(e, rec, n, ncaa_rec)
            if (
                eid in conflicting_events
                or result["ncaa_contest_id"] in conflicting_contests
            ):
                if "FINAL_RECONCILIATION_REQUIRED" not in result["issues"]:
                    result["issues"].append("FINAL_RECONCILIATION_REQUIRED")
                result.update(
                    status="FINAL_RECONCILIATION_REQUIRED",
                    home_score=None,
                    away_score=None,
                )
            reconciliations.append(result)
            issues.extend(
                {"event_id": row["event_id"], "issue": issue}
                for issue in result["issues"]
            )
        rows = [
            r
            for r, _, _ in sorted(
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
            "unmatched_ncaa": [official[k][0] for k in sorted(unmatched)],
            "issues": issues,
            "events": sorted(reconciliations, key=lambda e: e["event_id"]),
        }
    except (KeyError, ValueError, OSError, TypeError, IndexError) as exc:
        coverage = {"status": "BLOCKED", "reason": str(exc)}
    coverage["date"] = key
    save_json(output / "coverage.json", coverage)
    save_json(
        output / "manifest.json",
        {
            "date": key,
            "coverage_sha256": digest((output / "coverage.json").read_bytes()),
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
