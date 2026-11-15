"""Offline sensitivity analysis for the frozen CBB card and reconciled review.

The two fixed transforms are exploratory. This executable cannot register an arm,
change a default, declare a prospective grade, or issue a betting selection.
"""
import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from statistics import mean


def sha(data):
    return hashlib.sha256(data).hexdigest()


def clock(value):
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.utcoffset() is None:
        raise ValueError("timezone required")
    return t


def expanded_margin(distribution, scale=1.25):
    """Scale about the PMF mean, projecting to legal margins without moving the mean."""
    support, masses = distribution["support"], distribution["masses"]
    if (not support or len(support) != len(masses) or sorted(set(support)) != support
            or any(type(x) is not int or x == 0 for x in support)
            or any(not math.isfinite(p) or p < 0 for p in masses)
            or not math.isclose(sum(masses), 1, abs_tol=1e-8)
            or not math.isfinite(scale) or scale < 1):
        raise ValueError("invalid full-game OT margin distribution or scale")
    center = sum(x * p for x, p in zip(support, masses)) / sum(masses)
    law = defaultdict(float)
    for x, mass in zip(support, masses):
        y = center + scale * (x - center)
        lo, hi = math.floor(y), math.ceil(y)
        if lo == 0:
            lo = -1
        if hi == 0:
            hi = 1
        if lo == hi:
            law[lo] += mass
        else:
            law[lo] += mass * (hi - y) / (hi - lo)
            law[hi] += mass * (y - lo) / (hi - lo)
    return law


def normalized_home(quotes):
    def implied(odds):
        if type(odds) is not int or abs(odds) < 100:
            raise ValueError("missing paired American odds")
        return 100 / (100 + odds) if odds > 0 else -odds / (100 - odds)
    h, a = (implied(quotes[s]["odds"]) for s in ("home", "away"))
    return h / (h + a)


def paired_probability(product, forecast, row, model, side, line, parent_sha):
    if product == "moneyline":
        if model["frozen_source"] != parent_sha:
            raise ValueError("winner source mismatch")
        p = forecast["p_home_win"]
        q = normalized_home(row["quotes"][product])
        if not 0 <= p <= 1:
            raise ValueError("invalid winner probability")
        b = 0.75 * p + 0.25 * q
        return (p, b, q) if side == "home" else (1-p, 1-b, 1-q)

    if model["frozen_source"] != forecast["distribution_input_sha256"]:
        raise ValueError("margin source mismatch")
    if line is None or abs(line) % 1 != 0.5:
        raise ValueError("half-point spread required")
    if row["quotes"]["spread"][side]["line"] != line:
        raise ValueError("line mismatch")
    di = forecast["distributions"]["margin"]
    law = expanded_margin(di)
    sign = 1 if side == "home" else -1
    def cover(items):
        return sum(p for x, p in items if sign * x + line > 0)
    pair = row["quotes"]["spread"]
    other = "away" if side == "home" else "home"
    q = None
    if pair.get(other, {}).get("line") == -line:
        try:
            home_price = normalized_home(pair)
            q = home_price if side == "home" else 1 - home_price
        except (KeyError, ValueError):
            pass
    return cover(zip(di["support"], di["masses"])), cover(law.items()), q


def run(parent, board, grades, parent_sha):
    if (parent["schema"] != "sports.cbb.shadow_card.v2" or parent["league"] != "CBB"
            or parent["market_input"] is not False or board["slate_date"] != parent["date"]):
        raise ValueError("wrong parent, slate or information set")
    forecasts = {f["event_id"]: f for f in parent["forecasts"]}
    rows = {(r["away"] + " at " + r["home"]): r for r in board["rows"] if r["league"] == "CBB"}
    if len(forecasts) != len(parent["forecasts"]) or len(rows) != sum(r["league"] == "CBB" for r in board["rows"]):
        raise ValueError("ambiguous fixture")
    seen, scored, excluded = set(), [], []
    for league, label, score, product, side, line, _reported, settled in grades:
        if league != "CBB" or product not in {"moneyline", "spread"}:
            continue
        r = rows[label]
        key = (r["event_id"], product)
        if key in seen:
            raise ValueError("duplicate graded market")
        seen.add(key)
        f = forecasts[r["event_id"]]
        m = r["markets"][product][0]
        try:
            if (r["hold"] or f["forecast_status"] != "FORECAST_GENERATED" or side not in {"home","away"}
                    or (f["home_team"], f["away_team"]) != (r["home"], r["away"])
                    or clock(f["start_time_utc"]) != clock(r["start"])
                    or m["period"] != f["settlement"] or f["settlement"] != "FULL_GAME_INCLUDING_OVERTIME"
                    or m["model"] != f["model_id"] or m["preferred"] != side
                    or m["quote_cohort"] != "POST_SEAL_PRESTART" or not r.get("book")
                    or not r.get("quote_sha256")):
                raise ValueError("unmatched frozen event or comparison price")
            if not (clock(parent["as_of_utc"]) == clock(m["cutoff"]) <= clock(m["issue"])
                    == clock(parent["generated_at_utc"]) <= clock(r["quote_utc"]) < clock(r["start"])):
                raise ValueError("chronology mismatch")
            p, b, q = paired_probability(product, f, r, m, side, line, parent_sha)
            if not math.isclose(p, m["preferred_data"]["win"], abs_tol=1e-9):
                raise ValueError("incumbent replay mismatch")
            away, home = map(int, score.split("–"))
            margin = (home-away) * (1 if side == "home" else -1)
            if home == away or min(away, home) < 0:
                raise ValueError("invalid final")
            y = int(margin + (line if product == "spread" else 0) > 0)
            if settled != ("W" if y else "L"):
                raise ValueError("settlement mismatch")
            scored.append(dict(event_id=key[0], product=product, side=side, line=line,
                               p=p, challenger=b, market=q, y=y, model_id=f["model_id"],
                               state_sha256=f["model_state_config_hash"], quote_sha256=r["quote_sha256"]))
        except ValueError as err:
            excluded.append(dict(event_id=key[0], product=product, reason=str(err)))
    return scored, excluded


def summary(rows):
    if not rows:
        return {"n": 0}
    probs = ["p", "challenger"] + (["market"] if all(r["market"] is not None for r in rows) else [])
    return dict(n=len(rows), wins=sum(r["y"] for r in rows),
                brier={k: mean((r[k]-r["y"])**2 for r in rows) for k in probs},
                mean_probability={k: mean(r[k] for r in rows) for k in probs})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for f in ("parent", "board", "grades", "output"):
        parser.add_argument(f, type=Path)
    args = parser.parse_args()
    inputs = [p.read_bytes() for p in (args.parent, args.board, args.grades)]
    p, b, g = map(json.loads, inputs)
    rows, exclusions = run(p, b, g, sha(inputs[0]))
    spreads = [r for r in rows if r["product"] == "spread"]
    result = dict(status="RETROSPECTIVE_EXPOSED_DIAGNOSTIC", action="OFF", official_units=0,
                  prospective_grade_eligible=False, release_eligible=False, slate_date=p["date"],
                  procedures={"spread": "centered_integer_OT_margin_scale_1.25",
                              "moneyline": "postquote_market_informed_linear_pool_weight_0.25"},
                  code_sha256=sha(Path(__file__).read_bytes()),
                  input_sha256=dict(zip(("parent","board","grades"),map(sha,inputs))),
                  metrics={"ML":summary([r for r in rows if r["product"]=="moneyline"]),
                           "spread":summary(spreads),
                           "spread_abs15plus":summary([r for r in spreads if abs(r["line"])>=15]),
                           "spread_p70plus":summary([r for r in spreads if r["p"]>=0.70])},
                  rows=rows, exclusions=exclusions)
    encoded=json.dumps(result, indent=2, allow_nan=False)+"\n"
    with args.output.open("x") as dest:
        dest.write(encoded)


if __name__ == "__main__":
    main()
