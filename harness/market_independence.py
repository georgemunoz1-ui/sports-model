"""Enforce the Market-Independent Prediction Rule (docs/MARKET_INDEPENDENCE_RULE.md).

WHY THIS IS CODE AND NOT PROSE. This repository has now produced three separate instances of the
same failure: a value computed, returned, and never consumed. sp_asof_strict's last_start_date was
dropped one line before the word RESOLVED. aggregate_guard — the function whose own docstring calls
it "the check that would have stopped the 8/27 damage" — had zero production callers for its entire
life. resolved_information_dose reached the row, the validator, stdout and the published HTML and
was never multiplied into any probability. A governance rule written only as a document is the
fourth instance waiting to happen, so this module exists and healthcheck.py calls it.

WHAT IT REFUSES.

  1. FEATURE FIREWALL. No market-derived key in a forecast row's feature position.
  2. ORDERING. A market artifact must be captured at or after forecast_anchor_utc. A price
     observed BEFORE the freeze cannot be shown not to have influenced it.
  3. LAYER SEPARATION. MODEL FORECAST / UNCERTAINTY / MARKET COMPARISON / BET DECISION distinct.
  4. CONTRARIAN DRIFT. Flagged, never refused — see below.

THE FIREWALL IS DELIBERATELY NARROW, AND THAT IS THE POINT. An earlier crude firewall in this repo
matched the substring "point" and rejected home_ewma_points_for — a PREREGISTERED feature. A
false positive that breaks a legitimate model is not a safe failure; it silently removes real
signal and looks like caution. So the token list matches price SEMANTICS, carries an explicit
allow-list, and selftest F3 pins that exact historical false positive.

CONTRARIAN DRIFT IS A DIAGNOSTIC, NOT A REFUSAL. The anti-contrarian clause exists because "ignore
the books" mutates easily into "always fade the favorite," which is market anchoring with the sign
flipped. But an all-fade slate CAN occur honestly, and refusing one would be its own anchoring —
the model would be constrained to agree with the market some minimum share of the time, which is
exactly what the rule forbids. It is surfaced for a human to look at.
"""
from __future__ import annotations

MODULE_ID = "market_independence"

import datetime as dt
import re
import sys

#: Keys whose SEMANTICS are a sportsbook price or a market-behaviour signal. Matched as whole
#: tokens against snake_case key parts, never as bare substrings.
MARKET_TOKENS = {
    "odds", "ml", "moneyline", "vig", "juice", "devig", "de_vig", "implied",
    "spread", "line", "handicap", "puckline", "runline", "hook",
    "consensus", "book", "sportsbook", "dk", "fanduel", "pinnacle", "vsin",
    "steam", "rlm", "handle", "tickets", "public", "sharp", "money",
    "closing", "clv", "opener", "price", "payout", "juice_adj",
}
#: Preregistered / structural feature names that CONTAIN a market-ish token but are not market
#: data. Each entry is a real feature this repo uses; removing one silently deletes signal.
FEATURE_ALLOWLIST = {
    "home_ewma_points_for", "away_ewma_points_for",
    "home_ewma_points_against", "away_ewma_points_against",
    "points_for", "points_against", "line_yards",          # OL/DL metric, not a betting line
    "offensive_line_yards", "defensive_line_yards",
    "money_down_conversion",                                # football situational rate
}
#: Row keys that legitimately carry market data on a board — the ACTION layer, not features.
MARKET_LAYER_KEYS = {"market_overlay", "action_status", "market", "market_comparison",
                     "bet_decision", "alternates", "market_position",
                     # The preregistered extreme-disagreement audit flag. It CARRIES a book spread
                     # but is computed AFTER the model margin exists and compares the two, so it is
                     # a MARKET COMPARISON output, not a feature. Classified here on first run of
                     # this gate against the live 2026-08-29 CFB board, and the underlying finding
                     # is recorded rather than waved through: that board has NO structural layer
                     # separation — a comparison artifact sits in the same namespace as features,
                     # so the only thing distinguishing them is this list. That is fragile, and it
                     # is why REQUIRED_LAYERS exists for artifacts going forward.
                     "fbs_fcs_extreme_spread_review"}

REQUIRED_LAYERS = ("MODEL_FORECAST", "UNCERTAINTY", "MARKET_COMPARISON", "BET_DECISION")


class MarketIndependenceError(Exception):
    def __init__(self, violations):
        self.violations = violations
        super().__init__("; ".join(violations))


def _tokens(key):
    return {t for t in re.split(r"[^a-z0-9]+", str(key).lower()) if t}


def market_keys_in(row, allowlist=None):
    """Market-derived keys sitting in a row's FEATURE position. Returns [(key, token), ...]."""
    allow = FEATURE_ALLOWLIST | set(allowlist or ())
    out = []
    for k in row:
        if k in allow or k in MARKET_LAYER_KEYS:
            continue
        hit = _tokens(k) & MARKET_TOKENS
        if hit:
            out.append((k, sorted(hit)[0]))
    return out


def _parse(ts):
    if ts in (None, ""):
        return None
    s = str(ts).strip().replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def validate_board(board, rows, market_captured_utc=None, allowlist=None):
    """Refuse a board that lets market data reach the forecast. Returns True or raises."""
    v = []
    for i, row in enumerate(rows):
        for k, tok in market_keys_in(row, allowlist):
            v.append(f"row {i} ({row.get('game', '?')}): key {k!r} is market-derived "
                     f"(token {tok!r}) and sits in the feature position")
    anchor = _parse(board.get("forecast_anchor_utc"))
    cap = _parse(market_captured_utc)
    if anchor and cap and cap < anchor:
        v.append(f"ORDERING: market captured {cap.isoformat()} BEFORE the forecast froze at "
                 f"{anchor.isoformat()} — a price observed before the freeze cannot be shown not "
                 "to have influenced it")
    if v:
        raise MarketIndependenceError(v)
    return True


def validate_layers(artifact):
    missing = [k for k in REQUIRED_LAYERS if k not in artifact]
    if missing:
        raise MarketIndependenceError(
            [f"published decision artifact is missing layer(s) {missing}; a reader cannot tell "
             "which claims are price-blind"])
    return True


def contrarian_drift(model_sides, market_favorites):
    """DIAGNOSTIC. Fraction of games where the model agrees with the market favorite."""
    n = len(model_sides)
    if not n or len(market_favorites) != n:
        return {"n": n, "agree": None, "flag": "INSUFFICIENT_DATA"}
    agree = sum(1 for a, b in zip(model_sides, market_favorites) if a == b)
    flag = "OK"
    if n >= 4 and agree == 0:
        flag = ("CONTRARIAN_DRIFT_SUSPECTED — the model took the non-favorite in every game. This "
                "is a flag for a human to look at, NOT a refusal: an all-fade slate can be honest, "
                "and forcing some minimum agreement with the market would be anchoring with the "
                "sign flipped, which the rule forbids.")
    return {"n": n, "agree": agree, "agree_share": round(agree / n, 4), "flag": flag}


# ====================================================================== selftest

def selftest():
    f = []
    ANCHOR = "2026-08-28T12:00:00Z"
    board = {"forecast_anchor_utc": ANCHOR}

    # F1 — a clean statistical row passes.
    clean = {"game": "mlb:A@B", "p_home": 0.55, "park_factor": 1.02, "home_ewma_points_for": 4.4,
             "rest_days": 2, "k_pct": 24.0}
    try:
        validate_board(board, [clean])
    except MarketIndependenceError as e:
        f.append(f"F1: a clean row was refused: {e}")

    # F2 — market data in the feature position is refused, one violation per offending key.
    for bad_key in ("ml_home", "implied_prob", "closing_line", "devig_p", "consensus_spread",
                    "public_pct", "steam_move", "dk_price"):
        try:
            validate_board(board, [dict(clean, **{bad_key: 1})])
            f.append(f"F2: {bad_key!r} passed the feature firewall")
        except MarketIndependenceError:
            pass

    # F3 — THE HISTORICAL FALSE POSITIVE. A crude firewall in this repo matched the substring
    #      "point" and rejected home_ewma_points_for, a PREREGISTERED feature. Pinned so the
    #      firewall can never become "safe" by deleting real signal.
    for legit in ("home_ewma_points_for", "away_ewma_points_against", "line_yards",
                  "offensive_line_yards", "money_down_conversion"):
        try:
            validate_board(board, [{"game": "g", legit: 1.0}])
        except MarketIndependenceError:
            f.append(f"F3: legitimate preregistered feature {legit!r} was refused — this is the "
                     "2026-08 'point' false positive reopening")

    # F4 — the ACTION layer may carry market data; that is where it belongs.
    try:
        validate_board(board, [dict(clean, market_overlay={"ml_home": -150},
                                    action_status="NO_RETAINED_MARKET_ARTIFACT")])
    except MarketIndependenceError as e:
        f.append(f"F4: market data in the action layer was refused: {e}")

    # F5 — ORDERING. A price captured before the freeze is refused.
    try:
        validate_board(board, [clean], market_captured_utc="2026-08-28T11:00:00Z")
        f.append("F5: a market artifact captured BEFORE the forecast froze was accepted")
    except MarketIndependenceError:
        pass
    try:
        validate_board(board, [clean], market_captured_utc="2026-08-28T13:00:00Z")
    except MarketIndependenceError as e:
        f.append(f"F5: a market artifact captured after the freeze was refused: {e}")

    # F6 — layer separation.
    try:
        validate_layers({"MODEL_FORECAST": 1, "UNCERTAINTY": 1, "MARKET_COMPARISON": 1})
        f.append("F6: an artifact missing BET_DECISION was accepted")
    except MarketIndependenceError:
        pass

    # F7 — anti-contrarian clause. Agreeing with the favorite must NEVER be a violation.
    d7 = contrarian_drift(["A", "B", "C", "D"], ["A", "B", "C", "D"])
    if d7["flag"] != "OK":
        f.append("F7: a model agreeing with every favorite was flagged — the rule explicitly "
                 "permits selecting the favorite when the data supports it")
    d7b = contrarian_drift(["A", "B", "C", "D"], ["W", "X", "Y", "Z"])
    if not str(d7b["flag"]).startswith("CONTRARIAN_DRIFT_SUSPECTED"):
        f.append("F7: an all-fade slate was not flagged")

    # F8 — tonight's real CFB board must pass the firewall.
    try:
        import json
        b = json.load(open("cards/2026-08-29_cfb_board.json"))
        rows = b.get("rows") or b.get("cfb", {}).get("rows", [])
        validate_board(b, rows)
    except MarketIndependenceError as e:
        f.append(f"F8: the live CFB board fails the firewall: {e}")
    except FileNotFoundError:
        pass

    print(f"{MODULE_ID} selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  !", x)
    return 0 if not f else 1


if __name__ == "__main__":
    sys.exit(selftest())
