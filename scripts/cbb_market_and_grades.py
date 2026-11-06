"""Attach diagnostic quotes to a frozen men's CBB shadow card, or grade that exact card."""

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from functools import cache, partial
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.capture_cbb_daily import (
    ESPN,
    PACIFIC,
    ncaa_events,
    ncaa_url,
    paired_market_quotes,
    reconcile_event,
)
from scripts.capture_cbb_daily import (
    sides as competition_sides,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(value):
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("UTC offset required")
    return instant


def probability(pmf, sign, handicap):
    support, masses = pmf["support"], pmf["masses"]
    if not support or len(set(support)) != len(support) or len(support) != len(masses):
        raise ValueError("Invalid support")
    if any(type(k) is not int for k in support) or not all(
        math.isfinite(p) and 0 <= p <= 1 for p in masses
    ):
        raise ValueError("Invalid probability input")
    if (
        sign not in (-1, 1)
        or not math.isfinite(handicap)
        or not math.isclose(math.fsum(masses), 1, abs_tol=1e-10, rel_tol=0)
    ):
        raise ValueError("Invalid probability mass or line")
    margins = [sign * k + handicap for k in support]
    return {
        key: math.fsum(p for p, m in zip(masses, margins) if pred(m))
        for key, pred in [
            ("win", lambda m: m > 0),
            ("push", lambda m: m == 0),
            ("loss", lambda m: m < 0),
        ]
    }


def parse_price(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if abs(n) >= 100 else None


def market_rows(raw, forecast):
    """Use the collector's exact book-ambiguity and paired-contract policy."""
    _, quotes = paired_market_quotes(raw)
    result = []
    for quote in quotes:
        product, side, line = quote["product"], quote["side"], quote["line"]
        if product == "winner":
            win = forecast["p_home_win"]
            if side == "away":
                win = 1 - win
            probs = {"win": win, "push": 0.0, "loss": 1 - win}
        else:
            positive = side in ("home", "over")
            handicap = line if product == "margin" or not positive else -line
            probs = probability(
                forecast["distributions"][product],
                1 if positive else -1,
                handicap,
            )
        result.append({**quote, **probs})
    return result


def pinned_json(path, expected, decode=json.loads):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch: {path.name}")
    return decode(raw)


def verified_card(path, expected):
    d = pinned_json(path, expected)
    if (d["schema"], d["league"], d["market_input"], d["action_authority"]) != (
        "sports.cbb.shadow_card.v1",
        "CBB",
        False,
        False,
    ):
        raise ValueError("Wrong forecast identity or authority")
    if (
        len({r["event_id"] for r in d["forecasts"]}) != len(d["forecasts"])
        or len(d["forecasts"]) != d["scheduled"]
    ):
        raise ValueError("Coverage mismatch")
    return d


def identity(raw, fc):
    event_id = fc["event_id"].split(":")[1]
    if len(raw["header"]["competitions"]) != 1:
        raise ValueError("Ambiguous ESPN summary competition")
    c = raw["header"]["competitions"][0]
    teams = competition_sides(c)
    snapshot = fc["model_input_snapshot"]
    if (
        str(raw["header"]["id"]) != event_id
        or str(c["id"]) != event_id
        or stamp(c["date"]) != stamp(fc["start_time_utc"])
        or str(teams["home"]["id"]) != snapshot["h"]
        or str(teams["away"]["id"]) != snapshot["a"]
    ):
        raise ValueError("Result or quote identity mismatch")
    return c, teams


def source_json(inputs, manifest, source_url, decode=json.loads):
    receipts = [item for item in manifest["sources"] if item["url"] == source_url]
    if len(receipts) != 1:
        raise ValueError("Missing or ambiguous source receipt")
    receipt = receipts[0]
    path = (inputs / receipt["file"]).resolve()
    if (
        path.parent != (inputs / "raw").resolve()
        or receipt.get("status", 200) != 200
        or stamp(receipt["retrieved_at_utc"]) > datetime.now(timezone.utc)
    ):
        raise ValueError("Unverified capture receipt")
    return pinned_json(path, receipt["sha256"], decode), receipt


def capture(inputs, fc, manifest=None):
    eid = fc["event_id"].split(":")[1]
    source_url = ESPN + "summary?event=" + eid
    if manifest is None:
        manifest = json.loads((inputs / "manifest.json").read_bytes())
    raw, receipt = source_json(inputs, manifest, source_url)
    c, teams = identity(raw, fc)
    return raw, c, teams, receipt


def attach(card, inputs, parent_sha):
    cutoff = stamp(card["as_of_utc"])
    generated = stamp(card["generated_at_utc"])
    rows = []
    for fc in card["forecasts"]:
        if fc["forecast_status"] != "FORECAST_GENERATED":
            continue
        entry = {
            "event_id": fc["event_id"],
            "book": "DraftKings",
            "settlement": fc["settlement"],
            "contracts": [],
            "provider_quote_observed_at_utc": None,
            "qualification": "NO_PICK",
        }
        try:
            raw, c, _, receipt = capture(inputs, fc)
            start = stamp(fc["start_time_utc"])
            now = datetime.now(timezone.utc)
            retrieved = stamp(receipt["retrieved_at_utc"])
            if (
                not retrieved <= cutoff <= generated <= now < start
                or c["status"]["type"]["state"] != "pre"
            ):
                raise ValueError("Capture outside pregame decision window")
            entry.update(
                source_sha256=receipt["sha256"],
                source_url=receipt["url"],
                quote_retrieved_at_utc=receipt["retrieved_at_utc"],
                contracts=market_rows(raw, fc),
            )
            entry["status"] = (
                "DIAGNOSTIC_RETRIEVAL_TIME_ONLY"
                if entry["contracts"]
                else "NO_PAIRED_PRICES"
            )
        except (OSError, KeyError, ValueError) as e:
            entry.update(status="QUOTE_UNAVAILABLE", detail=str(e))
        rows.append(entry)
    return {
        "schema": "sports.cbb.market.shadow.v1",
        "date": card["date"],
        "frozen_parent_sha256": parent_sha,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "action_authority": False,
        "rows": rows,
    }


def reconciled_result(inputs, fc, manifest, coverage, day, load_board):
    eid = fc["event_id"]
    records = [r for r in coverage["events"] if r["event_id"] == eid]
    if len(records) != 1:
        raise ValueError("Missing or ambiguous event reconciliation")
    rec = records[0]
    issues = [
        i["issue"]
        for i in coverage["issues"]
        if i["event_id"] == eid and i["issue"] != "QUOTE_SOURCE_UNAVAILABLE"
    ]
    if issues or rec["status"] not in ("FINAL_RECONCILED", "PENDING"):
        raise ValueError(", ".join(issues) if issues else rec["status"])

    espn = rec["espn_scoreboard_url"]
    ncaa = rec["ncaa_scoreboard_url"]
    if espn not in {
        f"{ESPN}scoreboard?dates={day + timedelta(days=n):%Y%m%d}&limit=1000&groups=50"
        for n in (-1, 0, 1)
    } or ncaa not in {ncaa_url(day), ncaa_url(day + timedelta(days=1))}:
        raise ValueError("Unexpected scoreboard URL or slate date")
    board, espn_receipt = load_board(espn)
    official, ncaa_receipt = load_board(ncaa, ncaa_events)
    es = [event for event in board["events"] if "CBB:" + event["id"] == eid]
    ns = [c for c in official if c["contestId"] == rec["ncaa_contest_id"]]
    if len(es) != 1 or len(ns) != 1:
        raise ValueError("Event not unique in source scoreboard")
    if reconcile_event(es[0], espn_receipt, ns[0], ncaa_receipt) != rec:
        raise ValueError("Reconciliation differs from raw provider evidence")
    _, comp, teams, receipt = capture(inputs, fc, manifest)
    start = stamp(fc["start_time_utc"])
    snap = fc["model_input_snapshot"]
    if (
        start.astimezone(PACIFIC).date() != day
        or stamp(rec["start_time_utc"]) != start
        or (rec["home_id"], rec["away_id"]) != (snap["h"], snap["a"])
        or rec["neutral_site"] is not snap["neutral"]
        or comp["neutralSite"] is not snap["neutral"]
    ):
        raise ValueError("Reconciled event identity differs from frozen card")
    st = comp["status"]["type"]
    final = (
        st["completed"] is True
        and st["name"] == "STATUS_FINAL"
        and st["state"] == "post"
    )
    if final != (rec["status"] == "FINAL_RECONCILED"):
        raise ValueError("Summary and scoreboards disagree on final status")
    if final:
        if any(
            stamp(r["retrieved_at_utc"]) <= start
            for r in (espn_receipt, ncaa_receipt, receipt)
        ):
            raise ValueError("Final receipt precedes start")
        for side in ("home", "away"):
            if str(teams[side]["score"]) != str(rec[side + "_score"]):
                raise ValueError("Summary and scoreboards disagree on final score")
    return rec, receipt


def grade(card, market, inputs, parent_sha, manifest_sha, *, market_sha):
    """Grade pre-verified card and market objects with the exact pinned postgame bundle."""
    if not all(
        isinstance(pin, str) and re.fullmatch(r"[a-f0-9]{64}", pin)
        for pin in (parent_sha, market_sha)
    ):
        raise ValueError("Invalid parent or market SHA-256")
    if (
        market["schema"] != "sports.cbb.market.shadow.v1"
        or market["frozen_parent_sha256"] != parent_sha
        or market["date"] != card["date"]
        or market.get("action_authority") is not False
    ):
        raise ValueError("Market attachment or date mismatch")
    q = {r["event_id"]: r for r in market["rows"]}
    if len(q) != len(market["rows"]) or set(q) != {
        r["event_id"]
        for r in card["forecasts"]
        if r["forecast_status"] == "FORECAST_GENERATED"
    }:
        raise ValueError("Market comparison coverage mismatch")
    if card["forecast_count"] != len(q):
        raise ValueError("Incorrect frozen forecast count")
    manifest = pinned_json(inputs / "manifest.json", manifest_sha)
    coverage_sha = manifest.get("coverage_sha256")
    coverage = pinned_json(inputs / "coverage.json", coverage_sha)
    day = date.fromisoformat(card["date"])
    if (
        manifest.get("date") != day.strftime("%Y%m%d")
        or coverage.get("date") != manifest["date"]
    ):
        raise ValueError("COVERAGE_DATE_MISMATCH")
    reconciliation = {
        "source": "coverage.json",
        "sha256": coverage_sha,
        "date": coverage["date"],
        "status": coverage["status"],
    }
    blocked = coverage["status"] == "BLOCKED"
    if not blocked and (
        coverage["status"] not in ("RECONCILED", "REQUIRES_REVIEW")
        or not isinstance(coverage.get("events"), list)
        or not isinstance(coverage.get("issues"), list)
    ):
        raise ValueError("Missing or invalid postgame reconciliation coverage")
    load_board = cache(partial(source_json, inputs, manifest))
    rows = []
    for fc in card["forecasts"]:
        row = {
            "event_id": fc["event_id"],
            "status": "EXCLUDED",
            "reason": fc.get("reason"),
            "products": [],
        }
        rows.append(row)
        if fc["forecast_status"] != "FORECAST_GENERATED":
            continue
        if blocked:
            row.update(
                status="RECONCILIATION_REQUIRED",
                reason="COVERAGE_BLOCKED:" + str(coverage.get("reason")),
            )
            continue
        try:
            rec, receipt = reconciled_result(
                inputs, fc, manifest, coverage, day, load_board
            )
        except (OSError, IndexError, KeyError, ValueError, TypeError) as exc:
            row.update(status="FINAL_RECONCILIATION_REQUIRED", reason=str(exc))
            continue
        if rec["status"] == "PENDING":
            row.update(status="PENDING", reason=rec["espn_status"])
            continue
        try:
            home, away = rec["home_score"], rec["away_score"]
            m, total = home - away, home + away
            row.update(
                status="FINAL",
                reason=None,
                home_score=home,
                away_score=away,
                result_sha256=receipt["sha256"],
                reconciliation=rec,
                source=receipt["url"],
                result_retrieved_at_utc=receipt["retrieved_at_utc"],
                margin_error=m - fc["home_margin"],
                total_error=total - fc["total"],
                home_win_brier=(fc["p_home_win"] - (m > 0)) ** 2,
                winner_correct=(fc["p_home_win"] > 0.5) == (m > 0)
                if fc["p_home_win"] != 0.5
                else None,
            )
            attachment = q[fc["event_id"]]
            contracts = attachment["contracts"]
            if contracts and not (
                stamp(attachment["quote_retrieved_at_utc"])
                <= stamp(card["as_of_utc"])
                <= stamp(card["generated_at_utc"])
                <= stamp(market["created_at_utc"])
                < stamp(fc["start_time_utc"])
            ):
                raise ValueError("Contract not attached pregame")
            for product in ("margin", "total"):
                pair = [v for v in contracts if v["product"] == product]
                if len(pair) != 2 or abs(pair[0]["win"] - pair[1]["win"]) < 1e-12:
                    continue
                best = max(pair, key=lambda v: v["win"])
                line = best["line"]
                side = best["side"]
                value = (
                    (m if side == "home" else -m) + line
                    if product == "margin"
                    else (total - line) * (1 if side == "over" else -1)
                )
                result = "win" if value > 0 else "loss" if value < 0 else "push"
                row["products"].append(
                    {
                        "product": product,
                        "side": side,
                        "line": line,
                        "result": result,
                        "conditional_brier": None
                        if value == 0
                        else (best["win"] / (1 - best["push"]) - (value > 0)) ** 2,
                    }
                )
        except (OSError, KeyError, ValueError, TypeError) as e:
            row.clear()
            row.update(
                event_id=fc["event_id"],
                status="RESULT_UNAVAILABLE",
                reason=str(e),
                products=[],
            )
    done = [r for r in rows if r["status"] == "FINAL"]
    return {
        "schema": "sports.cbb.grades.shadow.v2",
        "postgame_manifest_sha256": manifest_sha,
        "coverage_sha256": coverage_sha,
        "reconciliation": reconciliation,
        "frozen_market_sha256": market_sha,
        "date": card["date"],
        "frozen_parent_sha256": parent_sha,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "action_authority": False,
        "rows": rows,
        "finals": len(done),
        "expected": card["forecast_count"],
        "complete": not blocked and len(done) == card["forecast_count"],
        "graded_margin_mae": mean(abs(r["margin_error"]) for r in done)
        if done
        else None,
        "graded_total_mae": mean(abs(r["total_error"]) for r in done) if done else None,
        "graded_winner_brier": mean(r["home_win_brier"] for r in done)
        if done
        else None,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["attach", "grade"])
    for arg in ("card", "inputs", "output"):
        ap.add_argument("--" + arg, type=Path, required=True)
    ap.add_argument("--card-sha", required=True)
    ap.add_argument("--market", type=Path)
    ap.add_argument("--market-sha")
    ap.add_argument("--manifest-sha")
    ap.add_argument("--previous-grade", type=Path)
    ap.add_argument("--previous-grade-sha")
    args = ap.parse_args()
    card = verified_card(args.card, args.card_sha)
    if args.command == "attach":
        if args.previous_grade or args.previous_grade_sha or args.manifest_sha:
            ap.error("Postgame evidence arguments apply only to grade")
        output = attach(card, args.inputs, args.card_sha)
    else:
        if not args.market or not args.market_sha or not args.manifest_sha:
            ap.error(
                "Frozen --market, --market-sha, and postgame --manifest-sha required"
            )
        if bool(args.previous_grade) != bool(args.previous_grade_sha):
            ap.error("Provide both --previous-grade and --previous-grade-sha")
        market = pinned_json(args.market, args.market_sha)
        output = grade(
            card,
            market,
            args.inputs,
            args.card_sha,
            args.manifest_sha,
            market_sha=args.market_sha,
        )
        if args.previous_grade:
            previous = pinned_json(args.previous_grade, args.previous_grade_sha)
            if (
                previous.get("schema")
                not in ("sports.cbb.grades.shadow.v1", "sports.cbb.grades.shadow.v2")
                or previous.get("date") != card["date"]
                or previous.get("frozen_parent_sha256") != args.card_sha
                or previous.get("action_authority") is not False
                or (
                    previous["schema"].endswith(".v2")
                    and previous.get("frozen_market_sha256") != args.market_sha
                )
            ):
                ap.error("Previous grade does not belong to this frozen assessment")
            output["previous_grade_sha256"] = args.previous_grade_sha
            output["previous_market_binding"] = (
                "VERIFIED"
                if previous["schema"].endswith(".v2")
                else "UNVERIFIABLE_LEGACY_GRADE"
            )
    encoded = json.dumps(output, indent=2, allow_nan=False) + "\n"
    with args.output.open("x") as file:
        file.write(encoded)
    print(digest(args.output))
    if args.command == "grade" and not output["complete"]:
        raise SystemExit(2)
