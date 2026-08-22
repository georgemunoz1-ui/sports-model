#!/usr/bin/env python3
"""FROZEN SUBGROUP MONITOR — subgroup cells pre-registered and hash-frozen BEFORE the results land.

WHY THIS EXISTS (owner roadmap item 3, 2026-08-21/22). On the 8/21 slate home teams went 14-1. v2
was 10-1 on its home picks and 0-4 on its away picks; v1 was 8-1 and 0-6. Both cohorts went 0-for on
every away pick, and a trivial always-pick-home heuristic would have gone 14-1 — beating v2's 10-5
by four games. The obvious reflex is to reach for a home-field adjustment. The owner's instruction
is the opposite, and it is the whole reason this module exists:

    an 0-4 away subgroup warrants a MONITORED SUBGROUP, NOT an immediate home-field
    adjustment, and the subgroup tests must be FROZEN BEFORE more results arrive so
    they cannot be tuned to the data that suggested them.

WHY 0-4 IS NOT EVIDENCE. At a 50% coin rate P(0-for-4) = 0.5**4 = 6.25% — one slate in sixteen.
This monitor declares five axes and sixteen cells; a 6%-probability run somewhere among sixteen
cells is the EXPECTED result of looking, not a discovery about away teams. So every cell prints its
n, and any cell under MIN_CELL_N is stamped UNDERPOWERED, refused as a finding, and has its RATES
WITHHELD from the text surface (the record is still printed — the count is the honest number, the
rate is the misleading one). MIN_CELL_N = 30 is a REPORTING FLOOR, not a power calculation: even at
n=30 the 95% interval on an accuracy near .5 is roughly +/-18pp, which is why a cell at or above the
floor is labelled ABOVE_REPORTING_FLOOR and never "powered".

WHAT IS FROZEN, AND WHY A HASH. The axis definitions live in AXIS_SPEC, which is written to a frozen
spec file by freeze_spec() together with a FROZEN_AT timestamp and a sha256 over the canonical spec.
score() recomputes that hash from the LIVE module and REFUSES to score at all when it differs — a
changed bin edge, a changed threshold, a renamed level, or an edited leveller body all move the
hash. It ALSO re-hashes the spec block stored inside the frozen file and refuses when that no longer
matches the hash recorded next to it, because the cheapest way to tune a frozen test is to edit the
frozen record in place and leave its hash alone. Refusal is the entire mechanism: a monitor that
silently re-scores under new definitions is not frozen, it is a search.

The frozen spec embeds impl_fingerprint_sha256, a comment- and layout-insensitive token digest of
the leveller functions themselves, so "the labels stayed the same but the classifier changed" is
also caught. Docstrings inside the levellers ARE part of that digest: the prose is the definition,
and re-wording it is a re-freeze, deliberately.

WHY MARGINAL AXES ONLY (no cross-cells). Crossing all five axes gives 2*4*4*3*3 = 288 cells over a
15-game slate. That is a false-finding generator, and it also destroys the one invariant that makes
this monitor auditable: within each axis the levels PARTITION the rows, so every axis's cells must
sum back to the overall record exactly. Null is a first-class level (NULL_NO_MARKET,
NULL_NO_V1_PAIR, NULL_UNKNOWN_CAP) precisely so the partition survives missing inputs instead of
quietly dropping rows. Cross-cells are out of scope for this frozen version; adding them requires a
new dated freeze with an owner authority string.

R1 THROUGHOUT. Unknown is null plus a reason code, never a substituted value: a game with no market
price is NULL_NO_MARKET, not "agreement"; a game with no v1 counterpart is NULL_NO_V1_PAIR, not
"NO_FLIP"; an unknown CAP count is NULL_UNKNOWN_CAP, not CAP_0. Rows that cannot be scored at all
(no outcome, no probability, out-of-range probability) are EXCLUDED AND COUNTED with reasons, never
silently dropped.

THIS MODULE WRITES NOTHING except a frozen spec file, and freeze_spec() refuses any path inside a
registered-artifact directory and refuses to overwrite an existing spec. score() is pure.

ROW SCHEMA (build_row() constructs one; all optional fields default to None, never to a value):
    row_id         str, unique within the call — a duplicate id REFUSES the whole scoring run
    p_home         float in [0,1], the model's P(home win)
    home_win       0/1 outcome
    cap_slots      0/1/2 CAP starter slots on the game (unified_card.slot_status: TBD or
                   REGISTRY_MISS only), or None
    p_home_v1      the paired v1 cohort P(home win) for the SAME game, or None
    market_p_home  de-vigged market P(home win) from ONE book's two-sided pair, or None

Usage: python3 harness/subgroup_monitor.py --selftest
       python3 harness/subgroup_monitor.py --freeze docs/experiments/2026-08-22_SUBGROUP_SPEC.json
       python3 harness/subgroup_monitor.py --rows rows.json [--spec PATH] [--json]
"""
# =============================================================================================
# QUARANTINED DRAFT — NOT WIRED, NOT AUTHORITATIVE (2026-08-22)
# Built for the owner's roadmap and then adversarially reviewed. The review found critical/high
# defects and, more importantly, that many of this module's own fixtures are DECORATIVE: they stay
# green when the rule they supposedly guard is deleted. A passing selftest here therefore does not
# mean the rules hold. Findings: docs/audits/2026-08-22_roadmap_module_review.json
# This module is NOT imported by healthcheck, NOT used for any card, grade, or decision, and its
# numbers must not be quoted until the defect list is closed and the fixtures are proven killing.
# =============================================================================================

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import inspect
import json
import os
import sys
import tokenize

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_SPEC_PATH = "docs/experiments/2026-08-22_SUBGROUP_MONITOR_FROZEN.json"

# Directories holding registered artifacts. A frozen spec may never be written into one of these:
# this module is a monitor over registered outputs and never writes to them.
REGISTERED_PREFIXES = ("cards/", "data/cards_unified/", "data/mlb/forecasts/",
                       "data/wnba/forecasts/", "data/backfill/")

# --------------------------------------------------------------------------------------------
# FROZEN CONSTANTS. Every one of these is inside the hashed spec, so changing any of them moves
# the spec hash and REFUSES scoring against an older freeze.
# --------------------------------------------------------------------------------------------
SPEC_VERSION = "1.0.0"
MIN_CELL_N = 30                       # reporting floor, not a power calculation — see module docstring
PICK_HOME_IF_P_HOME_GE = 0.5          # p_home exactly .5 is a HOME pick (matches grade_slate.run)
MARKET_HOME_IF_P_HOME_GE = 0.5
CONF_EDGES = [0.0, 0.02, 0.05, 0.10, 1.0]
CONF_ROUND_DP = 6                     # see _lvl_confidence_band — float dust must not decide a bin
MAX_CAP_SLOTS = 2                     # a game has exactly two starter slots

DEFAULT_AUTHORITY = ("owner instruction 2026-08-21/22: the 0-4 away-pick run is a MONITORED "
                     "SUBGROUP, not a home-field adjustment; tests frozen before further results")


# --------------------------------------------------------------------------------------------
# AXIS LEVELLERS. Each takes (row, axis_spec) and returns (level, reason_code_or_None).
# They read their thresholds FROM the spec so that a spec edit is a real behaviour change, not a
# decorative one — the hash then genuinely covers what the monitor does.
# --------------------------------------------------------------------------------------------

def _lvl_venue_side(row, ax):
    """Axis 1 — the side the model itself picked. This is the axis the 8/21 incident lives on:
    v2 0-4 and v1 0-6 on away picks. It is a property of the PICK, not of the game."""
    return ("HOME_PICK" if row["p_home"] >= ax["pick_home_if_p_home_ge"] else "AWAY_PICK"), None


def _lvl_cap_slot_count(row, ax):
    """Axis 2 — how many of the game's two starter slots were CAP (TBD or REGISTRY_MISS, per
    unified_card.slot_status). An absent or out-of-range count is NULL, never CAP_0: 'we do not know
    how many slots were capped' and 'no slot was capped' are different facts (R1)."""
    v = row.get("cap_slots")
    if v is None:
        return "NULL_UNKNOWN_CAP", "R1_CAP_UNKNOWN"
    if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > ax["max_slots"]:
        return "NULL_UNKNOWN_CAP", "R1_CAP_INVALID"
    return f"CAP_{v}", None


def _conf_label(lo, hi):
    return f"CONF_{lo:.2f}_{hi:.2f}"


def _lvl_confidence_band(row, ax):
    """Axis 3 — |p_home - 0.5| binned, each bin left-closed/right-open, the last bin closed.

    The confidence is ROUNDED to conf_round_dp before binning, and that rounding is load-bearing,
    not cosmetic: in IEEE doubles abs(0.60 - 0.5) is 0.09999999999999998, so an unrounded compare
    puts a p_home of exactly .60 in [.05,.10) instead of [.10,1]. A frozen monitor whose cell
    membership flips on float dust is not frozen."""
    c = round(abs(row["p_home"] - 0.5), ax["conf_round_dp"])
    edges = ax["edges"]
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        last = (i == len(edges) - 2)
        if (lo <= c < hi) or (last and c == hi):
            return _conf_label(lo, hi), None
    return "NULL_CONF_OUT_OF_RANGE", "R1_CONF_OUT_OF_RANGE"


def _lvl_flip_status(row, ax):
    """Axis 4 — did the v1 -> v2 starter resolution flip the picked side on this game? Registered
    because 3 of v2's 4 gains on 8/21 were flips TOWARD home on a 14-1 home night: flip status and
    venue side must be monitored as separate axes so that story stays visible instead of being
    absorbed into a headline. No paired v1 row means NULL, never NO_FLIP (R1)."""
    p1 = row.get("p_home_v1")
    if p1 is None:
        return "NULL_NO_V1_PAIR", "R1_NO_V1_PAIR"
    t = ax["pick_home_if_p_home_ge"]
    return ("NO_FLIP" if (p1 >= t) == (row["p_home"] >= t) else "FLIP"), None


def _lvl_market_agreement(row, ax):
    """Axis 5 — does the model's picked winner match the market's? Compared on de-vigged p_home
    from ONE book's two-sided pair (cross-book best-odds de-vig is invalid, 8/3 ruling). Whole
    slates carry no prices at all — 8/21 was MARKET_COMPARISON_UNAVAILABLE slate-wide — so
    NULL_NO_MARKET is a normal, first-class cell and never collapses into AGREE."""
    m = row.get("market_p_home")
    if m is None:
        return "NULL_NO_MARKET", "R1_NO_MARKET"
    return ("AGREE" if (m >= ax["market_home_if_p_home_ge"]) ==
            (row["p_home"] >= ax["pick_home_if_p_home_ge"]) else "DISAGREE"), None


_LEVELLERS = {
    "venue_side": _lvl_venue_side,
    "cap_slot_count": _lvl_cap_slot_count,
    "confidence_band": _lvl_confidence_band,
    "flip_status": _lvl_flip_status,
    "market_agreement": _lvl_market_agreement,
}

R1_TEXT = {
    "R1_CAP_UNKNOWN": "R1_CAP_UNKNOWN — no CAP slot count supplied for this game; unknown is null, not CAP_0",
    "R1_CAP_INVALID": "R1_CAP_INVALID — CAP slot count outside 0..2; the true count is unknown, so the cell is null and the defect is counted",
    "R1_NO_V1_PAIR": "R1_NO_V1_PAIR — no paired v1 forecast for this game, so flip status is undefined, not NO_FLIP",
    "R1_NO_MARKET": "R1_NO_MARKET — no de-vigged market price for this game, so agreement is undefined, not AGREE",
    "R1_CONF_OUT_OF_RANGE": "R1_CONF_OUT_OF_RANGE — |p_home-0.5| fell outside every declared band",
    "R1_EMPTY_CELL": "R1_EMPTY_CELL — no rows fell in this cell, so it has no rate",
}


# --------------------------------------------------------------------------------------------
# IMPLEMENTATION FINGERPRINT — catches "same labels, different classifier".
# --------------------------------------------------------------------------------------------

def _norm_src_text(text):
    """Token digest of source: comments and all layout are dropped, everything else — names,
    numbers, operators, and docstrings — is kept. Docstrings are kept ON PURPOSE: the leveller
    prose IS the axis definition, so re-wording it must force a deliberate re-freeze."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError):
        return "IMPL_SOURCE_UNTOKENIZABLE"
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
            tokenize.DEDENT, tokenize.ENDMARKER}
    return " ".join(t.string for t in toks if t.type not in skip)


def _impl_fingerprint():
    parts = []
    for name in sorted(_LEVELLERS) + ["_conf_label"]:
        fn = _LEVELLERS.get(name) or globals()[name]
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            # Source unavailable (zipped/exec'd). Fail toward REFUSAL rather than toward a
            # fingerprint that silently matches anything.
            return "IMPL_SOURCE_UNAVAILABLE"
        parts.append(name + "::" + _norm_src_text(src))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


# --------------------------------------------------------------------------------------------
# THE FROZEN SPEC
# --------------------------------------------------------------------------------------------

def _conf_levels(edges):
    return [_conf_label(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


def build_axis_spec():
    """The declarative spec. Everything the levellers read lives here, so the spec hash covers the
    monitor's behaviour rather than merely describing it."""
    return {
        "spec_version": SPEC_VERSION,
        "min_cell_n": MIN_CELL_N,
        "cross_cells": ("NOT FROZEN — marginal axes only. Crossing all five axes yields 288 cells "
                        "over a 15-game slate and destroys the per-axis partition invariant. "
                        "Adding cross-cells requires a new dated freeze."),
        "row_schema_required": ["row_id", "p_home", "home_win"],
        "row_schema_optional": ["cap_slots", "p_home_v1", "market_p_home"],
        "axes": {
            "venue_side": {
                "order": 1,
                "definition": "side of the model's own pick: HOME_PICK when p_home >= 0.5, else AWAY_PICK",
                "pick_home_if_p_home_ge": PICK_HOME_IF_P_HOME_GE,
                "levels": ["HOME_PICK", "AWAY_PICK"],
                "null_levels": {},
                "motivating_incident": "2026-08-21: v2 0-4 and v1 0-6 on away picks; home teams went 14-1",
            },
            "cap_slot_count": {
                "order": 2,
                "definition": ("count of CAP starter slots on the game (TBD or REGISTRY_MISS per "
                               "unified_card.slot_status); LOW_SAMPLE is NOT a CAP slot"),
                "max_slots": MAX_CAP_SLOTS,
                "levels": [f"CAP_{i}" for i in range(MAX_CAP_SLOTS + 1)] + ["NULL_UNKNOWN_CAP"],
                "null_levels": {"NULL_UNKNOWN_CAP": R1_TEXT["R1_CAP_UNKNOWN"]},
                "motivating_incident": ("2026-08-21 denominator correction: CAP / LOW_SAMPLE / "
                                        "RESOLVED are distinct predicates and must not conflate"),
            },
            "confidence_band": {
                "order": 3,
                "definition": ("|p_home - 0.5| binned [0,.02) [.02,.05) [.05,.10) [.10,1]; "
                               "left-closed, right-open, last bin closed; confidence rounded to "
                               "conf_round_dp before binning"),
                "edges": list(CONF_EDGES),
                "conf_round_dp": CONF_ROUND_DP,
                "levels": _conf_levels(CONF_EDGES),
                "null_levels": {},
                "motivating_incident": ("compression doctrine: near-50% rows are the ones the "
                                        "market has repeatedly been right about"),
            },
            "flip_status": {
                "order": 4,
                "definition": "did starter resolution flip the picked side between the v1 and v2 cohorts",
                "pick_home_if_p_home_ge": PICK_HOME_IF_P_HOME_GE,
                "levels": ["FLIP", "NO_FLIP", "NULL_NO_V1_PAIR"],
                "null_levels": {"NULL_NO_V1_PAIR": R1_TEXT["R1_NO_V1_PAIR"]},
                "motivating_incident": ("2026-08-21: cohorts disagreed on 4 winners, v2 took 3 of 4, "
                                        "and 3 of those gains were flips toward home on a 14-1 home night"),
            },
            "market_agreement": {
                "order": 5,
                "definition": ("model picked winner vs market picked winner using same-book "
                               "two-sided de-vigged p_home; null when no market exists"),
                "market_home_if_p_home_ge": MARKET_HOME_IF_P_HOME_GE,
                "pick_home_if_p_home_ge": PICK_HOME_IF_P_HOME_GE,
                "levels": ["AGREE", "DISAGREE", "NULL_NO_MARKET"],
                "null_levels": {"NULL_NO_MARKET": R1_TEXT["R1_NO_MARKET"]},
                "motivating_incident": ("8/18 compression cohort: model-vs-market disagreement is the "
                                        "class that has lost; 8/21 carried no prices at all"),
            },
        },
        "impl_fingerprint_sha256": _impl_fingerprint(),
    }


AXIS_SPEC = build_axis_spec()


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def spec_sha256(spec):
    return hashlib.sha256(_canon(spec).encode()).hexdigest()


def _abspath(path):
    return path if os.path.isabs(path) else os.path.join(BASE, path)


# --------------------------------------------------------------------------------------------
# FREEZING
# --------------------------------------------------------------------------------------------

def freeze_spec(path=DEFAULT_SPEC_PATH, authority=DEFAULT_AUTHORITY, frozen_at_utc=None, spec=None):
    """Write the frozen spec. Refuses to overwrite, refuses a registered-artifact path, refuses an
    unattributed freeze. Returns the written document.

    Overwriting is refused because a freeze that can be re-issued in place is not a freeze; a new
    definition gets a NEW dated record and an explicit authority string, exactly like the preregs in
    docs/experiments/."""
    spec = AXIS_SPEC if spec is None else spec
    if not (authority or "").strip():
        raise ValueError("REFUSED: freeze_spec requires an authority string. A frozen test with no "
                         "stated authority is indistinguishable from one tuned to the data.")
    p = _abspath(path)
    rel = os.path.relpath(os.path.abspath(p), BASE)
    if not rel.startswith(".."):
        for pref in REGISTERED_PREFIXES:
            if rel.startswith(pref):
                raise ValueError(f"REFUSED: {rel} is inside a registered-artifact directory "
                                 f"({pref}). This module monitors registered artifacts and never "
                                 "writes to them.")
    if os.path.exists(p):
        raise ValueError(f"REFUSED: {path} already exists. A frozen spec is never overwritten — "
                         "issue a new dated record with its own authority string.")
    now = frozen_at_utc or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {
        "record_id": f"SUBGROUP-MONITOR-FROZEN-{now[:10]}",
        "module": "harness/subgroup_monitor.py",
        "status": ("FROZEN. Monitoring cells only — this record authorises NO model change, no "
                   "home-field adjustment, and no wager."),
        "authority": authority,
        "frozen_at_utc": now,
        "spec_sha256": spec_sha256(spec),
        "spec": spec,
        "refusal_contract": ("score() refuses unless (a) the live AXIS_SPEC hashes to spec_sha256 "
                             "and (b) the stored spec block re-hashes to the stored spec_sha256. "
                             "Editing this file in place is detected, not honoured."),
    }
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w") as fh:
        json.dump(doc, fh, indent=1)
    return doc


# --------------------------------------------------------------------------------------------
# SCORING
# --------------------------------------------------------------------------------------------

def _refused(code, reason, **extra):
    out = {"status": "REFUSED", "reason_code": code, "reason": reason,
           "overall": None, "axes": None}
    out.update(extra)
    return out


def _load_frozen(spec_path):
    p = _abspath(spec_path)
    if not os.path.exists(p):
        return None, _refused("NO_FROZEN_SPEC",
                              f"no frozen spec at {spec_path}; nothing may be scored until the axis "
                              f"definitions are frozen (run --freeze)", spec_path=spec_path)
    try:
        doc = json.load(open(p))
    except Exception as e:
        return None, _refused("SPEC_UNREADABLE", f"frozen spec {spec_path} is unreadable: {e}",
                              spec_path=spec_path)
    if not isinstance(doc, dict) or not isinstance(doc.get("spec"), dict) or not doc.get("spec_sha256"):
        return None, _refused("SPEC_INCOMPLETE",
                              f"frozen spec {spec_path} carries no spec block or no spec_sha256",
                              spec_path=spec_path)
    if not doc.get("frozen_at_utc"):
        return None, _refused("NO_FROZEN_AT",
                              f"frozen spec {spec_path} carries no frozen_at_utc; an unstamped spec "
                              "cannot be shown to predate the results it scores",
                              spec_path=spec_path)
    recomputed = spec_sha256(doc["spec"])
    if recomputed != doc["spec_sha256"]:
        return None, _refused("SPEC_TAMPERED",
                              f"frozen spec {spec_path} was edited in place: its spec block hashes "
                              f"to {recomputed[:16]} but it carries {doc['spec_sha256'][:16]}",
                              spec_path=spec_path, frozen_at_utc=doc.get("frozen_at_utc"),
                              recorded_spec_sha256=doc["spec_sha256"],
                              recomputed_spec_sha256=recomputed)
    return doc, None


def _spec_diff(live, frozen):
    out = []
    for k in sorted(set(live) | set(frozen)):
        if k == "axes":
            continue
        if _canon(live.get(k)) != _canon(frozen.get(k)):
            out.append(f"{k}: frozen={frozen.get(k)!r} live={live.get(k)!r}")
    la = live.get("axes") or {}
    fa = frozen.get("axes") or {}
    for k in sorted(set(la) | set(fa)):
        if k not in fa:
            out.append(f"axes.{k}: axis ADDED since freezing")
        elif k not in la:
            out.append(f"axes.{k}: axis REMOVED since freezing")
        elif _canon(la[k]) != _canon(fa[k]):
            out.append(f"axes.{k}: definition changed since freezing")
    return out


def _brier(p, y):
    return (p - y) ** 2


def _cell_stats(items, min_n, reason_code=None):
    n = len(items)
    w = sum(1 for it in items if it["correct"])
    l = n - w
    st = {
        "n": n,
        "wins": w,
        "losses": l,
        "record": f"{w}-{l}",
        "accuracy": (round(w / n, 4) if n else None),
        "brier": (round(sum(it["brier"] for it in items) / n, 6) if n else None),
        "rate_null_reason": (None if n else R1_TEXT["R1_EMPTY_CELL"]),
        "underpowered": n < min_n,
        "readable_as_finding": n >= min_n,
        "status": ("EMPTY" if n == 0 else ("UNDERPOWERED" if n < min_n else "ABOVE_REPORTING_FLOOR")),
        # For an all-one-way cell, the probability of that run under a 50% coin. 0-4 -> 0.0625:
        # one slate in sixteen, which is why 0-4 is monitored and not acted on.
        "all_one_way_coin_prob": (round(0.5 ** n, 6) if n and (w == 0 or l == 0) else None),
        "null_reason_code": reason_code,
        "null_reason": (R1_TEXT.get(reason_code) if reason_code else None),
    }
    if st["underpowered"]:
        st["note"] = (f"n={n} < {min_n}: UNDERPOWERED. Report the count; the rate is NOT a finding "
                      "and is withheld from the text surface.")
    return st


def _partition_failures(overall, out_axes):
    """THE SUM-BACK RULE. Within an axis the levels partition the scored rows, so every axis's cells
    must reproduce the overall n and W-L exactly. A subgroup table whose cells do not sum back to
    the headline record is not a decomposition of anything — it is a table of unrelated numbers, and
    the missing rows are invisible in it. Checked on every scoring run and refused, not warned."""
    inv = []
    for ax_name, blk in out_axes.items():
        s = blk["cell_sum"]
        if (s["n"], s["wins"], s["losses"]) != (overall["n"], overall["wins"], overall["losses"]):
            inv.append(f"{ax_name}: cells sum to {s['n']}/{s['wins']}-{s['losses']} but the overall "
                       f"record is {overall['n']}/{overall['record']} — the axis does not partition "
                       "the rows")
    return inv


def score(rows, spec_path=DEFAULT_SPEC_PATH, spec=None, scored_at_utc=None):
    """Score rows into the frozen subgroup cells, or REFUSE.

    Returns a dict whose "status" is "SCORED" or "REFUSED". Callers MUST branch on it: a refusal is
    the designed outcome whenever the axis definitions no longer match the freeze, and treating a
    refusal as an empty result would restore exactly the tunability the freeze exists to prevent."""
    spec = AXIS_SPEC if spec is None else spec
    spec_path = spec_path or DEFAULT_SPEC_PATH
    frozen, refusal = _load_frozen(spec_path)
    if refusal:
        return refusal
    live_hash = spec_sha256(spec)
    if live_hash != frozen["spec_sha256"]:
        return _refused("SPEC_CHANGED",
                        "axis definitions have changed since freezing; scoring is refused so the "
                        "cells cannot be re-cut against results that already exist",
                        spec_path=spec_path, frozen_at_utc=frozen["frozen_at_utc"],
                        frozen_spec_sha256=frozen["spec_sha256"], live_spec_sha256=live_hash,
                        detail=_spec_diff(spec, frozen["spec"]))

    axes = spec["axes"]
    min_n = spec["min_cell_n"]

    # de-duplicate defensively: one game counted twice corrupts every cell it touches, and the
    # standing rule is that a forecast is graded exactly once.
    seen = {}
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        rid = r.get("row_id")
        if rid is None:
            continue
        if rid in seen:
            return _refused("DUPLICATE_ROW_ID",
                            f"row_id {rid!r} appears at index {seen[rid]} and {i}; a game counted "
                            "twice would corrupt every cell it lands in",
                            spec_path=spec_path, frozen_at_utc=frozen["frozen_at_utc"])
        seen[rid] = i

    included, excluded, defects = [], [], []
    for i, r in enumerate(rows):
        tag = (r.get("row_id") if isinstance(r, dict) else None) or f"index {i}"
        if not isinstance(r, dict):
            excluded.append({"row": tag, "reason_code": "NOT_A_ROW", "reason": "row is not a dict"})
            continue
        if r.get("row_id") is None:
            excluded.append({"row": tag, "reason_code": "NO_ROW_ID",
                             "reason": "row carries no row_id, so it cannot be de-duplicated or traced"})
            continue
        p = r.get("p_home")
        y = r.get("home_win")
        if p is None or y is None:
            excluded.append({"row": tag, "reason_code": "NOT_GRADEABLE",
                             "reason": "p_home or home_win is null; excluded and counted, never imputed"})
            continue
        if not isinstance(p, (int, float)) or isinstance(p, bool) or not (0.0 <= float(p) <= 1.0):
            excluded.append({"row": tag, "reason_code": "INVALID_P_HOME",
                             "reason": f"p_home {p!r} is not a probability in [0,1]"})
            continue
        if y not in (0, 1, True, False):
            excluded.append({"row": tag, "reason_code": "INVALID_OUTCOME",
                             "reason": f"home_win {y!r} is not 0/1"})
            continue
        p = float(p)
        y = int(y)
        it = {"row_id": r["row_id"], "p_home": p, "home_win": y,
              "correct": int((p >= axes["venue_side"]["pick_home_if_p_home_ge"]) == (y == 1)),
              "brier": _brier(p, y), "levels": {}}
        for ax_name, ax in axes.items():
            lvl, code = _LEVELLERS[ax_name](r, ax)
            if lvl not in ax["levels"]:
                return _refused("UNDECLARED_LEVEL",
                                f"axis {ax_name} produced level {lvl!r}, which is not in the frozen "
                                "level list; the partition is no longer the frozen one",
                                spec_path=spec_path, frozen_at_utc=frozen["frozen_at_utc"])
            it["levels"][ax_name] = lvl
            if code == "R1_CAP_INVALID":
                defects.append({"row": r["row_id"], "reason_code": code, "reason": R1_TEXT[code],
                                "value": r.get("cap_slots")})
        included.append(it)

    overall = _cell_stats(included, min_n)
    out_axes = {}
    for ax_name, ax in sorted(axes.items(), key=lambda kv: kv[1]["order"]):
        cells = {}
        for lvl in ax["levels"]:
            members = [it for it in included if it["levels"][ax_name] == lvl]
            code = next((c for c, txt in R1_TEXT.items() if txt == (ax.get("null_levels") or {}).get(lvl)), None)
            cells[lvl] = _cell_stats(members, min_n, reason_code=code)
        out_axes[ax_name] = {
            "definition": ax["definition"],
            "motivating_incident": ax.get("motivating_incident"),
            "cells": cells,
            "cell_sum": {"n": sum(c["n"] for c in cells.values()),
                         "wins": sum(c["wins"] for c in cells.values()),
                         "losses": sum(c["losses"] for c in cells.values())},
        }

    inv = _partition_failures(overall, out_axes)
    if inv:
        return _refused("PARTITION_INVARIANT_VIOLATED",
                        "at least one axis does not partition the scored rows; a subgroup table "
                        "whose cells do not sum back to the overall record is not reportable",
                        spec_path=spec_path, frozen_at_utc=frozen["frozen_at_utc"], detail=inv)

    return {
        "status": "SCORED",
        "record_id": frozen.get("record_id"),
        "spec_path": spec_path,
        "frozen_at_utc": frozen["frozen_at_utc"],
        "spec_sha256": live_hash,
        "scored_at_utc": (scored_at_utc or
                          dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        "min_cell_n": min_n,
        "rows_in": len(rows),
        "overall": overall,
        "axes": out_axes,
        "excluded": excluded,
        "excluded_n": len(excluded),
        "input_defects": defects,
        "invariants": {"sum_back_ok": True, "failures": []},
        "reading_rules": [
            f"A cell with n < {min_n} is UNDERPOWERED: quote its COUNT, never its rate. "
            "P(0-for-4) under a 50% coin is 0.0625 — one slate in sixteen.",
            "Cells are marginal, one axis at a time; there are no cross-cells in this freeze.",
            "A null cell is a real cell with a reason code, not a missing row.",
            "This monitor authorises no model change. It reports; the owner decides.",
        ],
    }


# --------------------------------------------------------------------------------------------
# ADAPTER + REPORT
# --------------------------------------------------------------------------------------------

def build_row(row_id, p_home, home_win, cap_slots=None, p_home_v1=None, market_p_home=None,
              game=None, cohort=None):
    """Build one monitor row. Absent inputs stay None — this adapter never substitutes a default,
    because a defaulted CAP count or a defaulted market probability would move a game into a real
    cell on invented evidence (R1)."""
    return {"row_id": row_id, "p_home": p_home, "home_win": home_win, "cap_slots": cap_slots,
            "p_home_v1": p_home_v1, "market_p_home": market_p_home, "game": game, "cohort": cohort}


def _cell_line(name, c, min_n):
    if c["n"] == 0:
        return f"{name:<24} n=0     EMPTY — {c['rate_null_reason']}"
    if not c["readable_as_finding"]:
        # Rates are WITHHELD, not merely annotated: an 0-4 printed as ".000" is read as a finding
        # no matter what label sits beside it.
        extra = (f"  P(run|coin)={c['all_one_way_coin_prob']}" if c["all_one_way_coin_prob"] else "")
        return (f"{name:<24} n={c['n']:<4} record {c['record']:<7} rates WITHHELD — "
                f"UNDERPOWERED (n < {min_n}){extra}")
    return (f"{name:<24} n={c['n']:<4} record {c['record']:<7} acc {c['accuracy']:.4f} "
            f"Brier {c['brier']:.5f}  ABOVE_REPORTING_FLOOR")


def report_lines(result):
    if result["status"] != "SCORED":
        L = [f"SUBGROUP MONITOR REFUSED [{result['reason_code']}] {result['reason']}"]
        return L + [f"  - {d}" for d in (result.get("detail") or [])]
    m = result["min_cell_n"]
    L = [f"FROZEN SUBGROUP MONITOR — spec {result['spec_sha256'][:16]} FROZEN_AT {result['frozen_at_utc']}",
         f"scored {result['scored_at_utc']} | reporting floor n >= {m} | {result['record_id']}",
         "",
         _cell_line("OVERALL", result["overall"], m)]
    for ax_name, blk in result["axes"].items():
        L += ["", f"[{ax_name}] {blk['definition']}"]
        for lvl, c in blk["cells"].items():
            L.append("  " + _cell_line(lvl, c, m))
        s = blk["cell_sum"]
        L.append(f"  {'(sums back)':<24} n={s['n']:<4} record {s['wins']}-{s['losses']}")
    if result["excluded"]:
        L += ["", f"EXCLUDED AND COUNTED: {result['excluded_n']}"]
        L += [f"  - {e['row']}: {e['reason_code']} — {e['reason']}" for e in result["excluded"]]
    if result["input_defects"]:
        L += ["", f"INPUT DEFECTS: {len(result['input_defects'])}"]
        L += [f"  ! {d['row']}: {d['reason_code']}" for d in result["input_defects"]]
    L += [""] + [f"* {r}" for r in result["reading_rules"]]
    return L


# --------------------------------------------------------------------------------------------
# SELFTEST
# --------------------------------------------------------------------------------------------

def _incident_shape_rows():
    """The SHAPE of the 8/21 v2 slate: 15 games, 11 home picks 10-1, 4 away picks 0-4, 4 games with
    exactly one CAP slot (26/30 slots resolved), 4 v1->v2 flips of which v2 took 3, and NO market
    prices anywhere (8/21 was MARKET_COMPARISON_UNAVAILABLE slate-wide).

    The probabilities are SYNTHETIC and labelled as such — this module is not permitted to invent
    the registered ones. Only the cell shape is real, and the cell shape is what is being tested."""
    #        id     p_home  home_win  cap  p_home_v1 (None -> same side as p_home, set explicitly below)
    spec = [
        ("G01", 0.5060, 1, 0, 0.5100),
        ("G02", 0.5150, 1, 0, 0.4780),   # FLIP, v2 right
        ("G03", 0.5300, 1, 1, 0.5200),
        ("G04", 0.5400, 1, 0, 0.5350),
        ("G05", 0.5600, 1, 0, 0.4900),   # FLIP, v2 right
        ("G06", 0.5900, 1, 0, 0.5700),
        ("G07", 0.6000, 1, 1, 0.6100),   # p_home .60 -> float-dust bin boundary
        ("G08", 0.6600, 1, 0, 0.6400),
        ("G09", 0.7480, 1, 0, 0.4950),   # FLIP, v2 right
        ("G10", 0.5200, 1, 0, 0.5050),
        ("G11", 0.5100, 0, 0, 0.5300),   # the one home pick that lost
        ("G12", 0.4900, 1, 1, 0.5400),   # FLIP, v2 wrong
        ("G13", 0.4800, 1, 0, 0.4700),
        ("G14", 0.4500, 1, 1, 0.4600),
        ("G15", 0.3800, 1, 0, 0.4200),
    ]
    return [build_row(rid, p, y, cap_slots=cap, p_home_v1=v1, market_p_home=None)
            for rid, p, y, cap, v1 in spec]


def _tmp_freeze(td, name="spec.json", **kw):
    p = os.path.join(td, name)
    freeze_spec(p, frozen_at_utc="2026-08-22T00:00:00Z", **kw)
    return p


def selftest():
    import copy
    import tempfile
    fails = []

    with tempfile.TemporaryDirectory() as td:
        sp = _tmp_freeze(td)

        # ---- 1. REFUSAL: a changed axis definition against an existing freeze ------------------
        mutated = copy.deepcopy(AXIS_SPEC)
        mutated["axes"]["confidence_band"]["edges"] = [0.0, 0.03, 0.05, 0.10, 1.0]
        r = score(_incident_shape_rows(), sp, spec=mutated)
        if r["status"] != "REFUSED" or r["reason_code"] != "SPEC_CHANGED":
            fails.append(f"a changed confidence-band edge was SCORED against an existing freeze: {r['status']}")
        elif not any("confidence_band" in d for d in r["detail"]):
            fails.append("SPEC_CHANGED refusal did not name the axis that changed")
        mutated2 = copy.deepcopy(AXIS_SPEC)
        mutated2["axes"]["venue_side"]["pick_home_if_p_home_ge"] = 0.55
        if score([], sp, spec=mutated2)["status"] != "REFUSED":
            fails.append("a changed pick threshold was not REFUSED")
        mutated3 = copy.deepcopy(AXIS_SPEC)
        del mutated3["axes"]["market_agreement"]
        if score([], sp, spec=mutated3)["status"] != "REFUSED":
            fails.append("a DELETED axis was not REFUSED")
        mutated4 = copy.deepcopy(AXIS_SPEC)
        mutated4["min_cell_n"] = 4
        if score([], sp, spec=mutated4)["status"] != "REFUSED":
            fails.append("lowering the reporting floor to n=4 was not REFUSED")
        mutated5 = copy.deepcopy(AXIS_SPEC)
        mutated5["impl_fingerprint_sha256"] = "0" * 64
        if score([], sp, spec=mutated5)["status"] != "REFUSED":
            fails.append("a changed leveller fingerprint was not REFUSED")
        # the unmutated live spec must still score, or the refusal above proves nothing
        base = score(_incident_shape_rows(), sp)
        if base["status"] != "SCORED":
            fails.append(f"the LIVE spec was refused against its own freeze: {base}")

        # ---- 2. REFUSAL: the frozen file edited in place, hash left alone ----------------------
        doc = json.load(open(sp))
        doc["spec"]["min_cell_n"] = 4          # the cheapest possible tune: lower the floor
        json.dump(doc, open(os.path.join(td, "tampered.json"), "w"), indent=1)
        r = score([], os.path.join(td, "tampered.json"))
        if r["status"] != "REFUSED" or r["reason_code"] != "SPEC_TAMPERED":
            fails.append("an in-place edit of the frozen spec (floor 30 -> 4) was not caught")

        # ---- 3. REFUSAL: no freeze, no frozen_at ----------------------------------------------
        if score([], os.path.join(td, "nope.json"))["reason_code"] != "NO_FROZEN_SPEC":
            fails.append("scoring proceeded with no frozen spec at all")
        json.dump({"frozen_at_utc": "2026-08-22T00:00:00Z"},
                  open(os.path.join(td, "noblock.json"), "w"))
        if score([], os.path.join(td, "noblock.json"))["reason_code"] != "SPEC_INCOMPLETE":
            fails.append("a frozen record carrying no spec block was accepted")
        nostamp = json.load(open(sp))
        nostamp.pop("frozen_at_utc")
        json.dump(nostamp, open(os.path.join(td, "nostamp.json"), "w"), indent=1)
        if score([], os.path.join(td, "nostamp.json"))["reason_code"] != "NO_FROZEN_AT":
            fails.append("a spec with no FROZEN_AT timestamp was accepted")

        # ---- 4. freeze_spec refusals ----------------------------------------------------------
        try:
            freeze_spec(sp, frozen_at_utc="2026-08-23T00:00:00Z")
            fails.append("freeze_spec overwrote an existing frozen spec")
        except ValueError:
            pass
        try:
            freeze_spec(os.path.join(td, "b.json"), authority="  ")
            fails.append("freeze_spec accepted a freeze with no authority string")
        except ValueError:
            pass
        # a name that cannot pre-exist, so the overwrite refusal can never mask this guard
        reg = f"data/mlb/forecasts/_selftest_never_written_{os.getpid()}.json"
        try:
            freeze_spec(reg)
            fails.append("freeze_spec wrote into a registered-artifact directory")
        except ValueError as e:
            if "registered-artifact" not in str(e):
                fails.append(f"registered-artifact path refused for the wrong reason: {e}")
        if os.path.exists(_abspath(reg)):
            os.remove(_abspath(reg))
            fails.append("freeze_spec created a file inside a registered-artifact directory")

        # ---- 5. THE INCIDENT SHAPE ------------------------------------------------------------
        res = base
        ov = res["overall"]
        if (ov["n"], ov["record"]) != (15, "10-5"):
            fails.append(f"overall record wrong: n={ov['n']} {ov['record']} (expected 15, 10-5)")
        vs = res["axes"]["venue_side"]["cells"]
        if (vs["HOME_PICK"]["n"], vs["HOME_PICK"]["record"]) != (11, "10-1"):
            fails.append(f"home-pick cell wrong: {vs['HOME_PICK']['n']} {vs['HOME_PICK']['record']}")
        away = vs["AWAY_PICK"]
        if (away["n"], away["record"]) != (4, "0-4"):
            fails.append(f"away-pick cell wrong: {away['n']} {away['record']}")
        # THE RULE: an n=4 cell is UNDERPOWERED and is not a finding
        if not away["underpowered"] or away["status"] != "UNDERPOWERED" or away["readable_as_finding"]:
            fails.append("the n=4 away-pick cell was NOT flagged UNDERPOWERED — a 4-game cell would "
                         "read as a finding")
        if away["all_one_way_coin_prob"] != 0.0625:
            fails.append(f"0-for-4 coin probability wrong: {away['all_one_way_coin_prob']} (expected 0.0625)")
        if not vs["HOME_PICK"]["underpowered"]:
            fails.append("the n=11 home-pick cell (10-1) was treated as powered — the floor must "
                         "apply to the flattering cell too, or it is not a floor")
        if not ov["underpowered"]:
            fails.append("a 15-game slate was not itself marked underpowered")

        # p_home exactly .5 is a HOME pick, matching grade_slate.run — a coin-flip row must not
        # drift between the two axes' definitions of "the side the model picked"
        if _lvl_venue_side({"p_home": 0.5}, AXIS_SPEC["axes"]["venue_side"])[0] != "HOME_PICK":
            fails.append("p_home exactly 0.5 is not a HOME pick; the pick threshold no longer "
                         "matches grade_slate")
        if _lvl_flip_status({"p_home": 0.5, "p_home_v1": 0.5}, AXIS_SPEC["axes"]["flip_status"])[0] != "NO_FLIP":
            fails.append("two identical .5 probabilities were read as a flip")
        # Brier is the SQUARED error, pinned at known points (grade_slate.brier agrees)
        if _brier(0.5, 1) != 0.25 or _brier(1.0, 1) != 0.0 or _brier(0.0, 1) != 1.0:
            fails.append("Brier is not the squared error at its known points")
        exp_b = round(sum((it["p_home"] - it["home_win"]) ** 2 for it in
                          [{"p_home": p, "home_win": y} for p, y in
                           ((0.4900, 1), (0.4800, 1), (0.4500, 1), (0.3800, 1))]) / 4, 6)
        if away["brier"] != exp_b:
            fails.append(f"away-cell Brier {away['brier']} is not the mean squared error {exp_b}")

        # ---- 6. SUM-BACK, recomputed here rather than trusting the module's own flag ----------
        for ax_name, blk in res["axes"].items():
            n = sum(c["n"] for c in blk["cells"].values())
            w = sum(c["wins"] for c in blk["cells"].values())
            l = sum(c["losses"] for c in blk["cells"].values())
            if (n, w, l) != (ov["n"], ov["wins"], ov["losses"]):
                fails.append(f"axis {ax_name} does not sum back to the overall record: "
                             f"{n}/{w}-{l} vs {ov['n']}/{ov['record']}")
        if not res["invariants"]["sum_back_ok"]:
            fails.append("module reported its own partition invariant as broken")

        # ---- 7. CAP / FLIP / MARKET cells ------------------------------------------------------
        cap = res["axes"]["cap_slot_count"]["cells"]
        if (cap["CAP_0"]["n"], cap["CAP_1"]["n"], cap["CAP_2"]["n"]) != (11, 4, 0):
            fails.append(f"CAP cells wrong: {[cap[k]['n'] for k in ('CAP_0','CAP_1','CAP_2')]} (expected 11/4/0)")
        if cap["CAP_2"]["status"] != "EMPTY" or cap["CAP_2"]["accuracy"] is not None:
            fails.append("an empty CAP_2 cell did not report null-with-reason")
        fl = res["axes"]["flip_status"]["cells"]
        if (fl["FLIP"]["n"], fl["FLIP"]["record"], fl["NO_FLIP"]["n"]) != (4, "3-1", 11):
            fails.append(f"flip cells wrong: FLIP {fl['FLIP']['n']} {fl['FLIP']['record']}, "
                         f"NO_FLIP {fl['NO_FLIP']['n']} (expected 4 3-1 / 11)")
        mk = res["axes"]["market_agreement"]["cells"]
        if mk["NULL_NO_MARKET"]["n"] != 15 or mk["AGREE"]["n"] or mk["DISAGREE"]["n"]:
            fails.append("a priceless slate did not land entirely in NULL_NO_MARKET")
        if mk["NULL_NO_MARKET"]["null_reason_code"] != "R1_NO_MARKET":
            fails.append("the null market cell carries no R1 reason code")

        # ---- 8. NEVER INVENT: unknown cap is not CAP_0, no v1 pair is not NO_FLIP -------------
        rows2 = [build_row("N1", 0.60, 1, cap_slots=None, p_home_v1=None, market_p_home=None),
                 build_row("N2", 0.60, 1, cap_slots=7, p_home_v1=0.60, market_p_home=0.55),
                 build_row("N3", 0.40, 0, cap_slots=0, p_home_v1=0.40, market_p_home=0.55)]
        r2 = score(rows2, sp)
        c2 = r2["axes"]["cap_slot_count"]["cells"]
        if c2["NULL_UNKNOWN_CAP"]["n"] != 2 or c2["CAP_0"]["n"] != 1:
            fails.append(f"an unknown/invalid CAP count leaked into CAP_0: "
                         f"null={c2['NULL_UNKNOWN_CAP']['n']} cap0={c2['CAP_0']['n']} (expected 2/1)")
        if not any(d["reason_code"] == "R1_CAP_INVALID" for d in r2["input_defects"]):
            fails.append("an out-of-range CAP count was absorbed silently instead of counted as a defect")
        if r2["axes"]["flip_status"]["cells"]["NULL_NO_V1_PAIR"]["n"] != 1:
            fails.append("a row with no v1 pair did not land in NULL_NO_V1_PAIR")
        if r2["axes"]["flip_status"]["cells"]["NO_FLIP"]["n"] != 2:
            fails.append("flip status miscounted when a null pair was present")
        mk2 = r2["axes"]["market_agreement"]["cells"]
        if (mk2["AGREE"]["n"], mk2["DISAGREE"]["n"], mk2["NULL_NO_MARKET"]["n"]) != (1, 1, 1):
            fails.append(f"market agreement miscounted: {[mk2[k]['n'] for k in ('AGREE','DISAGREE','NULL_NO_MARKET')]}")

        # ---- 9. CONFIDENCE BAND EDGES, including the float-dust boundary ----------------------
        ax = AXIS_SPEC["axes"]["confidence_band"]
        for p, want in ((0.5000, "CONF_0.00_0.02"), (0.5199, "CONF_0.00_0.02"),
                        (0.5200, "CONF_0.02_0.05"), (0.4800, "CONF_0.02_0.05"),
                        (0.5500, "CONF_0.05_0.10"), (0.6000, "CONF_0.10_1.00"),
                        (0.4000, "CONF_0.10_1.00"), (1.0000, "CONF_0.10_1.00")):
            got = _lvl_confidence_band({"p_home": p}, ax)[0]
            if got != want:
                fails.append(f"confidence band for p_home={p} was {got}, expected {want}")
        # the last bin is CLOSED at its top edge. The frozen axis tops out at 1.0 while the largest
        # attainable |p-.5| is 0.5, so the closure is unreachable through the frozen edges — it is
        # pinned here directly, against a synthetic axis, so the rule cannot be dropped unnoticed.
        if _lvl_confidence_band({"p_home": 1.0}, {"edges": [0.0, 0.5], "conf_round_dp": 6})[0] != "CONF_0.00_0.50":
            fails.append("the last confidence bin is not closed at its top edge")
        if _lvl_confidence_band({"p_home": 1.0}, {"edges": [0.0, 0.4], "conf_round_dp": 6})[1] != "R1_CONF_OUT_OF_RANGE":
            fails.append("a confidence outside every declared band was not reported as null + reason")
        if max(abs(0.0 - 0.5), abs(1.0 - 0.5)) >= CONF_EDGES[-1]:
            fails.append("the top frozen band edge is no longer above the maximum attainable "
                         "confidence, so a real row could now fall outside every band")
        if (0.60 - 0.5) >= 0.10:
            fails.append("fixture assumption broken: abs(.60-.5) is no longer below .10 in IEEE, so "
                         "the float-dust bin fixture no longer tests the rounding rule")
        cb = res["axes"]["confidence_band"]["cells"]
        if [cb[k]["n"] for k in _conf_levels(CONF_EDGES)] != [4, 4, 3, 4]:
            fails.append(f"confidence band counts wrong: {[cb[k]['n'] for k in _conf_levels(CONF_EDGES)]}")

        # ---- 10. EXCLUDED AND COUNTED ---------------------------------------------------------
        rows3 = _incident_shape_rows() + [
            build_row("X1", 0.55, None, cap_slots=0),      # no outcome
            build_row("X2", 1.40, 1, cap_slots=0),         # p_home out of range
            build_row("X3", None, 1, cap_slots=0),         # no probability
            build_row("X4", 0.55, 2, cap_slots=0),         # outcome not 0/1
            build_row(None, 0.55, 1, cap_slots=0),         # untraceable row
            "not a row at all"]
        r3 = score(rows3, sp)
        if r3["overall"]["n"] != 15 or r3["excluded_n"] != 6:
            fails.append(f"ungradeable rows were not excluded-and-counted: n={r3['overall']['n']} "
                         f"excluded={r3['excluded_n']} (expected 15 / 6)")
        got_codes = {e["row"]: e["reason_code"] for e in r3["excluded"]}
        want_codes = {"X1": "NOT_GRADEABLE", "X2": "INVALID_P_HOME", "X3": "NOT_GRADEABLE",
                      "X4": "INVALID_OUTCOME", "index 19": "NO_ROW_ID", "index 20": "NOT_A_ROW"}
        if got_codes != want_codes:
            fails.append(f"exclusion reason codes wrong: {got_codes} (expected {want_codes})")
        if any(ov["n"] != r3["overall"]["n"] for ov in [r3["overall"]]) or r3["overall"]["record"] != "10-5":
            fails.append("an excluded row leaked into the scored record")

        # ---- 10b. THE SUM-BACK RULE ITSELF ----------------------------------------------------
        if _partition_failures(res["overall"], res["axes"]):
            fails.append("the partition rule fired on a correct table")
        broken = copy.deepcopy(res["axes"])
        broken["venue_side"]["cells"]["AWAY_PICK"]["n"] -= 1
        broken["venue_side"]["cell_sum"]["n"] -= 1
        if not _partition_failures(res["overall"], broken):
            fails.append("a cell table that does NOT sum back to the overall record was accepted")

        # ---- 10c. A LEVELLER THAT LEAVES THE FROZEN PARTITION IS REFUSED ----------------------
        _orig = _LEVELLERS["venue_side"]
        try:
            _LEVELLERS["venue_side"] = lambda row, ax: ("SOMEWHERE_ELSE", None)
            r4 = score(_incident_shape_rows(), sp)
            if r4["status"] != "REFUSED" or r4["reason_code"] != "UNDECLARED_LEVEL":
                fails.append("a leveller emitting a level outside the frozen list was scored anyway")
        finally:
            _LEVELLERS["venue_side"] = _orig

        # ---- 11. DUPLICATE ROWS REFUSED -------------------------------------------------------
        dup = _incident_shape_rows() + [_incident_shape_rows()[0]]
        if score(dup, sp)["reason_code"] != "DUPLICATE_ROW_ID":
            fails.append("the same game counted twice was scored instead of REFUSED")

        # ---- 12. THE TEXT SURFACE WITHHOLDS UNDERPOWERED RATES --------------------------------
        txt = report_lines(res)
        away_line = next((l for l in txt if l.strip().startswith("AWAY_PICK")), "")
        if "UNDERPOWERED" not in away_line or "WITHHELD" not in away_line:
            fails.append(f"report line for the 0-4 cell does not mark it UNDERPOWERED: {away_line!r}")
        if "0.0000" in away_line:
            fails.append("report printed a 0.0000 accuracy for a 4-game cell — that is the exact "
                         "misreading this monitor exists to prevent")
        if "n=4" not in away_line or "0-4" not in away_line:
            fails.append("report withheld the COUNT as well as the rate; the count is the honest number")
        empty_line = next((l for l in txt if l.strip().startswith("CAP_2")), "")
        if "EMPTY" not in empty_line or "R1_EMPTY_CELL" not in empty_line:
            fails.append(f"an empty cell did not render as EMPTY + R1 reason: {empty_line!r}")
        if not any(l.startswith("FROZEN SUBGROUP MONITOR") and "FROZEN_AT" in l for l in txt):
            fails.append("report does not carry the spec hash and FROZEN_AT stamp")
        rtxt = report_lines(score([], os.path.join(td, "nope.json")))
        if "REFUSED" not in rtxt[0]:
            fails.append("a refusal did not render as a refusal")

    # ---- 13. FINGERPRINT NORMALISATION -------------------------------------------------------
    a = "def f(x):\n    # a comment\n    return x + 1\n"
    b = "def f(x):\n    # an entirely different comment\n\n    return x + 1\n"
    c = "def f(x):\n    return x + 2\n"
    if _norm_src_text(a) != _norm_src_text(b):
        fails.append("comment/layout-only edits changed the implementation fingerprint")
    if _norm_src_text(a) == _norm_src_text(c):
        fails.append("a changed constant did NOT change the implementation fingerprint — a leveller "
                     "could be re-cut without moving the spec hash")
    if AXIS_SPEC["impl_fingerprint_sha256"] in ("IMPL_SOURCE_UNAVAILABLE", "IMPL_SOURCE_UNTOKENIZABLE"):
        fails.append("leveller source could not be fingerprinted; the spec hash would not cover the code")
    # pinned to its exact formula: sha256 over "name::<token digest>" for every leveller plus the
    # label formatter, newline-joined in sorted order. A constant here would let a leveller be
    # re-cut without moving the spec hash.
    expect = hashlib.sha256("\n".join(
        n + "::" + _norm_src_text(inspect.getsource(_LEVELLERS.get(n) or globals()[n]))
        for n in sorted(_LEVELLERS) + ["_conf_label"]).encode()).hexdigest()
    if AXIS_SPEC["impl_fingerprint_sha256"] != expect:
        fails.append("the spec's impl_fingerprint_sha256 is not the digest of the live leveller "
                     "sources — the frozen hash does not cover the classifier code")
    if _impl_fingerprint() != expect:
        fails.append("_impl_fingerprint() no longer computes its pinned formula")

    # ---- 14. SPEC HASH IS ORDER-INSENSITIVE BUT VALUE-SENSITIVE ------------------------------
    import copy as _copy
    reordered = json.loads(json.dumps(AXIS_SPEC))
    if spec_sha256(reordered) != spec_sha256(AXIS_SPEC):
        fails.append("spec hash is not stable across a JSON round-trip")
    tweaked = _copy.deepcopy(AXIS_SPEC)
    tweaked["axes"]["cap_slot_count"]["levels"] = ["CAP_0", "CAP_1", "CAP_2", "NULL_UNKNOWN_CAP", "CAP_3"]
    if spec_sha256(tweaked) == spec_sha256(AXIS_SPEC):
        fails.append("adding a level did not change the spec hash")

    if fails:
        print("subgroup_monitor selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("subgroup_monitor selftest: PASS (a changed axis definition, a changed threshold, a "
          "deleted axis, a lowered reporting floor, a changed leveller fingerprint and an in-place "
          "edit of the frozen record are all REFUSED against an existing freeze, while the live "
          "spec still scores; the n=4 away cell is UNDERPOWERED with its rate withheld from the "
          "text surface and its 0.0625 coin probability shown; the flattering n=11 cell is "
          "underpowered too; every axis sums back to 15/10-5 with null cells carrying R1 codes; "
          "unknown CAP is not CAP_0 and a missing v1 pair is not NO_FLIP; p_home=.60 bins as "
          "[.10,1] despite IEEE dust; ungradeable rows are excluded-and-counted and a duplicated "
          "game is REFUSED)")
    return 0


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Frozen subgroup monitor (owner roadmap item 3)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--freeze", metavar="PATH", nargs="?", const=DEFAULT_SPEC_PATH,
                    help="write the frozen spec (never overwrites)")
    ap.add_argument("--authority", default=DEFAULT_AUTHORITY)
    ap.add_argument("--rows", metavar="PATH", help="JSON list of monitor rows to score")
    ap.add_argument("--spec", default=DEFAULT_SPEC_PATH)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.freeze:
        doc = freeze_spec(a.freeze, authority=a.authority)
        print(f"FROZE {a.freeze}\n  record_id   {doc['record_id']}\n"
              f"  frozen_at   {doc['frozen_at_utc']}\n  spec_sha256 {doc['spec_sha256']}")
        return 0
    if a.rows:
        rows = json.load(open(_abspath(a.rows)))
        res = score(rows, a.spec)
        if a.json:
            print(json.dumps(res, indent=1))
        else:
            print("\n".join(report_lines(res)))
        return 0 if res["status"] == "SCORED" else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    os.chdir(BASE)
    raise SystemExit(main())
