"""Attach diagnostic quotes to a frozen men's CBB shadow card, or grade that exact card."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import mean


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
    """Read same-provider pairs directly from source. Require matching handicap on both sides."""
    offer = next(
        (o for o in raw.get("pickcenter", []) if o["provider"]["name"] == "DraftKings"),
        {},
    )
    result = []
    for product, key, sides in [
        ("winner", "moneyline", ("home", "away")),
        ("margin", "pointSpread", ("home", "away")),
        ("total", "total", ("over", "under")),
    ]:
        ticks = [offer.get(key, {}).get(s, {}).get("close", {}) for s in sides]
        prices = [parse_price(t.get("odds")) for t in ticks]
        if None in prices:
            continue
        if product == "winner":
            lines = [0.0, 0.0]
        else:
            values = [str(t.get("line", "")) for t in ticks]
            if product == "total":
                if not all(
                    v.lower().startswith(prefix)
                    for v, prefix in zip(values, ("o", "u"))
                ):
                    continue
                values = [v[1:] for v in values]
            try:
                lines = [float(v) for v in values]
            except ValueError:
                continue
            if not all(math.isfinite(v) for v in lines) or (
                lines[0] != (-lines[1] if product == "margin" else lines[1])
            ):
                raise ValueError("Opposing lines differ")
        for i, s in enumerate(sides):
            if product == "winner":
                win = forecast["p_home_win"] if i == 0 else 1 - forecast["p_home_win"]
                probs = {"win": win, "push": 0.0, "loss": 1 - win}
            else:
                handicap = (
                    lines[i]
                    if product == "margin"
                    else (-lines[i] if i == 0 else lines[i])
                )
                probs = probability(
                    forecast["distributions"][product], 1 if i == 0 else -1, handicap
                )
            result.append(
                {
                    "product": product,
                    "side": s,
                    "line": None if product == "winner" else lines[i],
                    "american_price": prices[i],
                    **probs,
                }
            )
    return result


def verified_card(path, expected):
    if digest(path) != expected:
        raise ValueError("Frozen parent SHA-256 mismatch")
    d = json.loads(path.read_bytes())
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
    c = raw["header"]["competitions"][0]
    teams = {t["homeAway"]: t for t in c["competitors"]}
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


def capture(inputs, fc):
    eid = fc["event_id"].split(":")[1]
    source_url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event="
        + eid
    )
    manifest = json.loads((inputs / "manifest.json").read_bytes())
    receipts = [item for item in manifest["sources"] if item["url"] == source_url]
    if len(receipts) != 1:
        raise ValueError("Missing or ambiguous ESPN event receipt")
    receipt = receipts[0]
    path = (inputs / receipt["file"]).resolve()
    if (
        path.parent != (inputs / "raw").resolve()
        or receipt["sha256"] != digest(path)
        or receipt.get("status", 200) != 200
        or stamp(receipt["retrieved_at_utc"]) > datetime.now(timezone.utc)
    ):
        raise ValueError("Unverified ESPN event input")
    raw = json.loads(path.read_bytes())
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


def grade(card, market, inputs, parent_sha):
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
        try:
            _, c, t, receipt = capture(inputs, fc)
            if (
                not c["status"]["type"]["completed"]
                or c["status"]["type"]["name"] != "STATUS_FINAL"
            ):
                row.update(status="PENDING", reason=c["status"]["type"]["name"])
                continue
            if stamp(receipt["retrieved_at_utc"]) <= stamp(fc["start_time_utc"]):
                raise ValueError("Final captured before start")
            home, away = [int(t[s]["score"]) for s in ("home", "away")]
            if min(home, away) < 0 or home == away:
                raise ValueError("Invalid full-game result")
            m, total = home - away, home + away
            row.update(
                status="FINAL",
                reason=None,
                home_score=home,
                away_score=away,
                result_sha256=receipt["sha256"],
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
        except (OSError, KeyError, ValueError) as e:
            row.update(status="RESULT_UNAVAILABLE", reason=str(e))
    done = [r for r in rows if r["status"] == "FINAL"]
    return {
        "schema": "sports.cbb.grades.shadow.v1",
        "date": card["date"],
        "frozen_parent_sha256": parent_sha,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "action_authority": False,
        "rows": rows,
        "finals": len(done),
        "expected": card["forecast_count"],
        "complete": len(done) == card["forecast_count"],
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
    args = ap.parse_args()
    card = verified_card(args.card, args.card_sha)
    if args.command == "attach":
        output = attach(card, args.inputs, args.card_sha)
    else:
        if (
            not args.market
            or not args.market_sha
            or digest(args.market) != args.market_sha
        ):
            ap.error("Frozen --market and --market-sha required")
        output = grade(
            card, json.loads(args.market.read_bytes()), args.inputs, args.card_sha
        )
    with args.output.open("x") as file:
        json.dump(output, file, indent=2, allow_nan=False)
        file.write("\n")
    print(digest(args.output))
