#!/usr/bin/env python3
"""FROZEN DAILY BASELINES — every settlement scores the cohorts against fixed comparators on the
SAME games, automatically, whether or not the result is flattering.

WHY (owner roadmap item 2; incident 2026-08-21): on that slate home teams went 14-1. The v2
resolved-starters cohort went 10-5, and the settlement report led with "Brier .22619 vs v1 .2408,
+6.1%" — a real-sounding headline for a cohort that a blind ALWAYS-HOME strategy beat outright,
14-1 against 10-5. Nothing in the settlement pipeline computed that comparison, so nobody could see
it. A cohort that loses to "always pick the home team" has demonstrated nothing on that slate, and
that fact has to be PRODUCED at settlement rather than noticed by hand later. Hence baseline 3 is
mandatory, not optional, and `gate()` refuses a report that omits any baseline.

THE SIX FROZEN COMPARATORS (all scored on the SAME game set as the cohorts):
  1. v1 all-CAP cohort               — league-average starters everywhere.
  2. v2 resolved-starters cohort     — the same slate with starters resolved.
  3. EXPANDING HOME-WIN PRIOR        — the running home-win rate over results STRICTLY BEFORE the
     slate date. Expanding, never centered, never including the slate itself: a prior that has seen
     the slate is a look-ahead, and on 2026-08-21 it would have been scored with knowledge of the
     very sweep it is supposed to be a naive comparator for. `d >= date -> skip` IS the rule.
  4. raw V13                         — the registered card probability. It IS the cohort number, so
     it is reported with that identity STATED (per_cohort + independent_comparator=False) rather
     than duplicated silently as if a fourth independent comparator had agreed.
  5. MARKET NO-VIG WHEN CAPTURED     — SAME-BOOK two-sided de-vig only. Cross-book best-odds de-vig
     is prohibited (8/3 ruling): the two sides come off different boards, so the normalisation
     divides by a vig no single book ever quoted and manufactures an edge out of shopping. When the
     only prices are cross-book, the answer is null + CROSS_BOOK_DEVIG_PROHIBITED, never a number.
  6. CLOSING MARKET                  — when captured; null with a reason when not.

R1 THROUGHOUT: an unavailable baseline is NEVER dropped from the output. It appears with every
scoring field null AND a reason string. Silence is how "always-home beat us" stayed invisible, so
`gate()` treats an omitted baseline, or a null field with no reason, as a failure.

ALWAYS_HOME accuracy is additionally reported as its own top-level line (not just implicitly via
the prior), because it is the headline sanity check for the slate.

READS ONLY. This module writes nothing and must never write to a registered artifact.
data/backfill/mlb/2026/results.csv is read for the expanding prior alone, using only its `date`,
`status` and `home_win` columns. That file labels teams with full names while card/cohort keys use
abbreviations; no crosswalk is invented here to reconcile them (R1), so outcomes for the slate come
from the graded cohort rows, not from the results file.

Usage: python3 harness/daily_baselines.py --selftest
       python3 harness/daily_baselines.py --date 2026-08-21 [--grades PATH] [--prices PATH]
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
import csv
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(BASE, "data/backfill/mlb/2026/results.csv")
ANALYSIS = os.path.join(BASE, "data/mlb/analysis")
EPS = 1e-6

R1 = "R1: unknown is null plus a reason code — never a default, never invented"

# The frozen list. Order is the report order. A key missing from a report is a gate failure.
BASELINE_KEYS = (
    "v1_all_cap_cohort",
    "v2_resolved_starters_cohort",
    "expanding_home_win_prior",
    "raw_v13_registered_card",
    "market_no_vig_when_captured",
    "closing_market",
)
COHORT_BASELINE = {"v1": "v1_all_cap_cohort", "v2": "v2_resolved_starters_cohort"}

# Scoring fields every block carries, present even when null (see R1 above).
SCORE_FIELDS = ("n", "side_record", "accuracy", "brier", "logloss")


# ----------------------------------------------------------------------------- price arithmetic
def imp(american):
    """Raw implied probability from an American price. NOT de-vigged."""
    a = float(american)
    return (-a) / ((-a) + 100) if a < 0 else 100 / (a + 100)


def devig_same_book(a_away, a_home):
    """Two-sided proportional de-vig -> p_home. Valid ONLY when both prices come off ONE book."""
    ia, ih = imp(a_away), imp(a_home)
    return ih / (ia + ih)


def brier(p, y):
    return (p - y) ** 2


def logloss(p, y):
    """Clamped at EPS so a degenerate p=0/1 comparator scores finitely instead of raising; the
    clamp is stated rather than hidden because it flatters degenerate probabilities."""
    p = min(max(p, EPS), 1 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def devig_entry(entry):
    """One game's captured prices -> (p_home, reason). Returns (None, REASON) for every case where
    a defensible same-book de-vig does not exist. Accepted shapes:

        {"book": "vsin", "ml_away": +147, "ml_home": -158}        one board, both sides
        {"book_away": "dk", "book_home": "dk", ...}               explicit per-side attribution
        {"books": {"dk": {"away": +147, "home": -158}, ...}}      several boards, mid of same-book de-vigs

    An UNATTRIBUTED pair is refused (PRICE_BOOK_ATTRIBUTION_MISSING) rather than assumed same-book:
    a best-odds screen also looks like {ml_away, ml_home}, and assuming would silently reintroduce
    exactly the cross-book de-vig the 8/3 ruling banned."""
    if not entry:
        return None, "NO_PRICE_CAPTURED — no market prices were captured for this game"
    basis = str(entry.get("basis") or "").lower().replace("-", "_")
    if entry.get("cross_book") is True or basis in ("best_odds", "cross_book", "best_price"):
        return None, ("CROSS_BOOK_DEVIG_PROHIBITED — best-odds prices come from different boards; "
                      "two-sided de-vig across books normalises against a vig no book quoted (8/3 ruling)")
    if "books" in entry:
        pairs = []
        any_away = any_home = False
        for bk, b in (entry.get("books") or {}).items():
            a = b.get("away", b.get("ml_away"))
            h = b.get("home", b.get("ml_home"))
            any_away = any_away or a is not None
            any_home = any_home or h is not None
            if a is not None and h is not None:
                pairs.append(devig_same_book(a, h))
        if pairs:
            return sum(pairs) / len(pairs), None  # mid of the per-book same-book de-vigs
        if any_away and any_home:
            return None, ("CROSS_BOOK_DEVIG_PROHIBITED — the away and home prices exist only on "
                          "DIFFERENT books; no single board quoted both sides (8/3 ruling)")
        return None, "ONE_SIDED_PRICE_NO_DEVIG — only one side was captured, so no vig can be removed"
    a, h = entry.get("ml_away"), entry.get("ml_home")
    if a is None or h is None:
        return None, "ONE_SIDED_PRICE_NO_DEVIG — only one side was captured, so no vig can be removed"
    ba, bh, bk = entry.get("book_away"), entry.get("book_home"), entry.get("book")
    if ba and bh and ba != bh:
        return None, (f"CROSS_BOOK_DEVIG_PROHIBITED — away priced at {ba}, home at {bh}; "
                      f"two-sided de-vig requires one board (8/3 ruling)")
    if not (bk or (ba and bh)):
        return None, ("PRICE_BOOK_ATTRIBUTION_MISSING — the pair carries no book attribution, so it "
                      "cannot be shown to be same-book; assuming it would reintroduce cross-book de-vig")
    return devig_same_book(a, h), None


def split_prices(prices):
    """Normalise the `prices` argument into ({game: entry} captured, {game: entry} closing).

    Accepted: {"games": {...}, "book": ..., "basis": ..., "timing": "close"} with the top-level
    book/basis as per-game defaults, or a bare {game: entry} mapping. A per-game entry may itself
    carry {"captured"/"pregame": ..., "close"/"closing": ...}."""
    if not prices:
        return {}, {}
    defaults = {k: prices[k] for k in ("book", "basis", "cross_book") if k in prices}
    if "events" in prices:
        # the repo's own odds capture shape: {"events": [{"matchup": "STL@CIN", "ml_away": ...}]}.
        # Book attribution still comes from the top level; it is never inferred from a prose
        # `source` string, because "same-board" in prose is not a machine-checkable claim.
        games = {e.get("matchup") or e.get("game"): {k: v for k, v in e.items()
                                                     if k not in ("matchup", "game")}
                 for e in (prices.get("events") or []) if isinstance(e, dict)}
        games.pop(None, None)
    elif "games" in prices:
        games = prices.get("games") or {}
    else:
        games = {k: v for k, v in prices.items()
                 if k not in ("games", "events", "book", "basis", "cross_book", "timing",
                              "source", "evidence_sha256")}
    top_close = str(prices.get("timing") or "").lower() in ("close", "closing")
    captured, close = {}, {}
    for k, e in games.items():
        if not isinstance(e, dict):
            continue
        if any(t in e for t in ("captured", "pregame", "close", "closing")):
            c = e.get("captured") or e.get("pregame")
            cl = e.get("close") or e.get("closing")
        elif str(e.get("timing") or "").lower() in ("close", "closing") or top_close:
            c, cl = None, e
        else:
            c, cl = e, None
        if isinstance(c, dict):
            captured[k] = {**defaults, **c}
        if isinstance(cl, dict):
            close[k] = {**defaults, **cl}
    return captured, close


# ----------------------------------------------------------------------------- expanding prior
def expanding_home_win_prior(date, results_rows):
    """Running home-win rate over finals STRICTLY BEFORE `date` -> (p, n_used, reason).

    The strict inequality is the entire point (incident 2026-08-21): home teams went 14-1 that day,
    and a prior computed over `<= date` would be scored on a slate it had already absorbed. On the
    real season file the difference is visible — .5242 before 8/21 versus .5274 after it.

    No results before the date at all -> (None, 0, reason). Never 0.500 by default (R1)."""
    if results_rows is None:
        return None, 0, "RESULTS_SOURCE_UNAVAILABLE — the results file could not be read; " + R1
    used = wins = 0
    for r in results_rows:
        d = r.get("date") or ""
        if not d or d >= date:            # STRICTLY BEFORE. '>=' here is the no-look-ahead rule.
            continue
        if str(r.get("status") or "").lower() != "final":
            continue
        hw = r.get("home_win")
        if hw in ("", None):
            continue
        try:
            hw = int(hw)
        except (TypeError, ValueError):
            continue
        if hw not in (0, 1):
            continue
        used += 1
        wins += hw
    if used == 0:
        return None, 0, (f"NO_RESULTS_STRICTLY_BEFORE_SLATE_DATE — no graded result predates "
                         f"{date}, so the prior is unknown; " + R1)
    return wins / used, used, None


def load_results(src=None):
    """Read results.csv (or accept an already-loaded list). Missing file -> None, never a stub."""
    if isinstance(src, list):
        return src
    path = src or RESULTS
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return list(csv.DictReader(fh))


# ----------------------------------------------------------------------------- scoring blocks
def _unavailable(label, reason, **extra):
    blk = {"label": label, "available": False, "null_reason": reason,
           "n": None, "side_record": None, "correct": None, "accuracy": None,
           "brier": None, "logloss": None, "sides_home": None, "sides_away": None,
           "games": [], "scored_on_common_set": False}
    blk.update(extra)
    return blk


def score_probs(label, probs, outcomes, games, **extra):
    """Score {game: p_home} against {game: home_win} over `games`. Blocks are uniform so a reader
    (and `gate`) can compare them without special cases."""
    gs = [g for g in games if probs.get(g) is not None and outcomes.get(g) is not None]
    if not gs:
        return _unavailable(label, "NO_SCORABLE_GAMES — no game carried both a probability and a "
                                   "graded outcome; " + R1, **extra)
    n = len(gs)
    correct = sum(1 for g in gs if (probs[g] >= .5) == (outcomes[g] == 1))
    sides_home = sum(1 for g in gs if probs[g] >= .5)
    blk = {
        "label": label, "available": True, "null_reason": None,
        "n": n, "correct": correct,
        "side_record": f"{correct}-{n - correct}",
        "accuracy": round(correct / n, 4),
        "brier": round(sum(brier(probs[g], outcomes[g]) for g in gs) / n, 6),
        "logloss": round(sum(logloss(probs[g], outcomes[g]) for g in gs) / n, 6),
        "sides_home": sides_home, "sides_away": n - sides_home,
        "games": list(gs), "scored_on_common_set": set(gs) == set(games),
    }
    blk.update(extra)
    return blk


def _norm_cohort_rows(cohort_rows):
    """Accept grade_slate.run() rows (p_home_model/board_game/cohort/home_win) or any row carrying
    an equivalent cohort / game / p_home / home_win. Rows that cannot be scored are RETURNED with a
    reason, not dropped on the floor."""
    keep, bad = [], []
    for i, r in enumerate(cohort_rows or []):
        coh = str(r.get("cohort") or r.get("arm") or "v1").strip().lower()
        game = r.get("board_game") or r.get("game")
        if not game and r.get("away") and r.get("home"):
            game = f'{r["away"]}@{r["home"]}'
        p = r.get("p_home_model")
        if p is None:
            p = r.get("p_home")
        if p is None:
            p = r.get("p_home_v13")
        y = r.get("home_win")
        if y is None:
            y = r.get("y")
        if not game:
            bad.append({"row_index": i, "cohort": coh, "reason": "NO_GAME_KEY — row names no game"})
            continue
        if p is None:
            bad.append({"game": game, "cohort": coh,
                        "reason": "NO_MODEL_PROBABILITY — row carries no p_home; " + R1})
            continue
        if y is None or y == "":
            bad.append({"game": game, "cohort": coh,
                        "reason": "NOT_GRADED — row carries no home_win outcome; " + R1})
            continue
        keep.append({"cohort": coh, "game": game, "p_home": float(p), "home_win": int(y),
                     "registered_card": bool(r.get("registered_card"))})
    return keep, bad


# ----------------------------------------------------------------------------- the report
def baselines(date, cohort_rows, results_rows=None, prices=None):
    """Score every frozen baseline for one slate. Reads only; returns the report dict.

    `results_rows` may be a loaded list, a path, or None (defaults to the season results file).
    `prices` shape is documented on `split_prices`/`devig_entry`."""
    rows, unscorable = _norm_cohort_rows(cohort_rows)
    by_coh = {}
    for r in rows:
        by_coh.setdefault(r["cohort"], []).append(r)

    # SAME GAMES: the comparison set is the intersection across every supplied cohort. A game one
    # cohort graded and another did not is excluded WITH a reason — a cohort scored on a game its
    # rival never saw is not a head-to-head.
    game_sets = {c: {r["game"] for r in rs} for c, rs in by_coh.items()}
    common = set.intersection(*game_sets.values()) if game_sets else set()
    union = set.union(*game_sets.values()) if game_sets else set()
    excluded = [{"game": g,
                 "reason": "NOT_IN_EVERY_COHORT — cohorts must be scored on IDENTICAL games; "
                           f"present in {sorted(c for c in game_sets if g in game_sets[c])}"}
                for g in sorted(union - common)]
    games = sorted(common)

    outcomes, conflicts = {}, []
    for r in rows:
        g = r["game"]
        if g in outcomes and outcomes[g] != r["home_win"]:
            conflicts.append(f"{g}: cohorts disagree on the graded outcome "
                             f"({outcomes[g]} vs {r['home_win']}) — one of them graded against a "
                             f"different board; refusing to pick a winner between them")
        outcomes[g] = r["home_win"]

    blocks = {}
    other = {}
    for coh, rs in sorted(by_coh.items()):
        probs = {r["game"]: r["p_home"] for r in rs}
        label = {"v1": "v1 all-CAP cohort (league-average starters)",
                 "v2": "v2 resolved-starters cohort"}.get(coh, f"{coh} cohort")
        blk = score_probs(label, probs, outcomes, games, cohort=coh)
        (blocks if coh in COHORT_BASELINE else other)[COHORT_BASELINE.get(coh, coh)] = blk
    for coh, key in COHORT_BASELINE.items():
        if key not in blocks:
            blocks[key] = _unavailable(
                f"{coh} cohort",
                f"NO_{coh.upper()}_COHORT_ROWS — no rows for cohort {coh} were supplied for this "
                f"slate, so the comparator cannot be scored; " + R1, cohort=coh)

    # 3. EXPANDING HOME-WIN PRIOR — strictly-earlier results only.
    res_rows = load_results(results_rows)
    p_prior, prior_n, prior_reason = expanding_home_win_prior(date, res_rows)
    if p_prior is None:
        blocks["expanding_home_win_prior"] = _unavailable(
            "expanding home-win prior (results strictly before the slate date)", prior_reason,
            prior_p_home=None, prior_sample_n=0, window="strictly-before, expanding")
    else:
        blocks["expanding_home_win_prior"] = score_probs(
            "expanding home-win prior (results strictly before the slate date)",
            {g: p_prior for g in games}, outcomes, games,
            prior_p_home=round(p_prior, 6), prior_sample_n=prior_n,
            window="strictly-before, expanding (no look-ahead: the slate's own games are excluded)",
            side_selection_equals_always_home=(p_prior >= .5))

    # 4. raw V13 — the registered card probability. Identical to the cohorts BY CONSTRUCTION.
    reg = sorted({r["cohort"] for r in rows if r["registered_card"]}) or sorted(by_coh)
    per_cohort = {c: (blocks.get(COHORT_BASELINE.get(c, c)) or other.get(c)) for c in reg}
    per_cohort = {c: b for c, b in per_cohort.items() if b}
    blocks["raw_v13_registered_card"] = {
        "label": "raw V13 (the registered card probability itself)",
        "available": bool(per_cohort),
        "independent_comparator": False,
        "identical_to_cohorts": list(per_cohort),
        "per_cohort": per_cohort,
        "null_reason": ("SCORES_REPORTED_PER_COHORT — raw V13 IS the cohort probability; reporting "
                        "an aggregate here would present the same numbers a second time as if an "
                        "independent comparator had agreed"
                        if per_cohort else "NO_COHORT_ROWS — nothing registered to score; " + R1),
        "n": None, "side_record": None, "correct": None, "accuracy": None,
        "brier": None, "logloss": None, "sides_home": None, "sides_away": None,
        "games": list(games), "scored_on_common_set": bool(per_cohort),
    }

    # 5/6. market baselines — same-book de-vig only, captured and closing kept separate.
    captured, closing = split_prices(prices)
    cohort_probs = {c: {r["game"]: r["p_home"] for r in rs} for c, rs in by_coh.items()}
    blocks["market_no_vig_when_captured"] = _market_block(
        "market no-vig probability (when captured)", captured, outcomes, games, cohort_probs,
        "NO_PRICE_CAPTURED — no market prices were captured for this slate; " + R1)
    blocks["closing_market"] = _market_block(
        "closing market no-vig probability", closing, outcomes, games, cohort_probs,
        "NO_CLOSING_PRICES_CAPTURED — no closing prices exist for this slate; " + R1)

    # ALWAYS_HOME — its own explicit line, because it is the headline sanity check.
    ah_games = [g for g in games if outcomes.get(g) is not None]
    if ah_games:
        wins = sum(1 for g in ah_games if outcomes[g] == 1)
        always_home = {
            "label": "ALWAYS_HOME (bet every home team, no model)", "available": True,
            "n": len(ah_games), "correct": wins,
            "side_record": f"{wins}-{len(ah_games) - wins}",
            "accuracy": round(wins / len(ah_games), 4),
            "brier": None, "logloss": None,
            "sides_home": len(ah_games), "sides_away": 0,
            "games": list(ah_games), "scored_on_common_set": True,
            "null_reason": ("STRATEGY_NOT_A_PROBABILITY — ALWAYS_HOME is a deterministic side rule, "
                            "not a forecast; Brier and log loss are undefined for it (p=1 gives "
                            "infinite log loss on any home loss). Use the expanding prior for the "
                            "probabilistic version."),
        }
    else:
        always_home = _unavailable("ALWAYS_HOME (bet every home team, no model)",
                                   "NO_GRADED_GAMES — no common game carries an outcome; " + R1)

    headline = _headline(always_home, blocks, other)
    return {
        "record_id": f"BASELINES-{date}",
        "date": date,
        "n_games_common": len(games),
        "games": games,
        "excluded_games": excluded,
        "unscorable_rows": unscorable,
        "outcome_conflicts": conflicts,
        "always_home": always_home,
        "headline": headline,
        "baselines": {k: blocks[k] for k in BASELINE_KEYS},
        "other_cohorts": other,
        "reads_only": True,
        "notes": [
            "cohorts are NEVER pooled; each is one arm scored on the identical common game set",
            "the expanding prior uses results STRICTLY BEFORE the slate date (no look-ahead)",
            "market probabilities are same-book two-sided de-vigs only (8/3 ruling)",
            "every unavailable baseline is present with a null_reason — never omitted (R1)",
        ],
    }


def _market_block(label, entries, outcomes, games, cohort_probs, empty_reason):
    """Score a market comparator, refusing anything that is not a same-book two-sided de-vig."""
    if not entries:
        return _unavailable(label, empty_reason, per_game_null_reasons={},
                            same_games_as_cohorts=False)
    probs, reasons = {}, {}
    for g in games:
        p, why = devig_entry(entries.get(g))
        if p is None:
            reasons[g] = why
        else:
            probs[g] = p
    if not probs:
        # Cross-book prohibition dominates the reported reason: it is a RULING, not a data gap.
        cross = [r for r in reasons.values() if r.startswith("CROSS_BOOK_DEVIG_PROHIBITED")]
        reason = cross[0] if cross else (sorted(reasons.values())[0] if reasons else empty_reason)
        return _unavailable(label, reason, per_game_null_reasons=reasons,
                            same_games_as_cohorts=False)
    blk = score_probs(label, probs, outcomes, games, per_game_null_reasons=reasons,
                      same_games_as_cohorts=(len(probs) == len(games)))
    if len(probs) < len(games):
        # An apples-to-apples number, so a market priced on a subset is never compared against a
        # cohort scored on the full slate.
        sub = sorted(probs)
        blk["subset_note"] = (f"priced on {len(sub)} of {len(games)} games; the cohort Briers below "
                              f"are recomputed on that SAME priced subset")
        blk["cohort_brier_on_priced_subset"] = {
            c: round(sum(brier(pp[g], outcomes[g]) for g in sub if g in pp and outcomes.get(g) is not None)
                     / max(1, len([g for g in sub if g in pp and outcomes.get(g) is not None])), 6)
            for c, pp in (cohort_probs or {}).items()}
    return blk


def _headline(always_home, blocks, other):
    """The 8/21 question, computed every time: did ALWAYS_HOME beat the best cohort?"""
    if not always_home.get("available"):
        return {"always_home_accuracy": None, "best_cohort": None, "best_cohort_accuracy": None,
                "always_home_beat_best_cohort": None,
                "message": "ALWAYS_HOME unavailable — " + (always_home.get("null_reason") or "")}
    cands = [(b.get("cohort"), b.get("accuracy"), b.get("side_record"))
             for b in list(blocks.values()) + list(other.values())
             if b.get("available") and b.get("cohort") and b.get("accuracy") is not None]
    if not cands:
        return {"always_home_accuracy": always_home["accuracy"], "best_cohort": None,
                "best_cohort_accuracy": None, "always_home_beat_best_cohort": None,
                "message": "no cohort was scorable, so no comparison exists; " + R1}
    name, acc, rec = max(cands, key=lambda c: c[1])
    beat = always_home["accuracy"] > acc
    msg = (f"ALWAYS_HOME {always_home['side_record']} ({always_home['accuracy']:.4f}) "
           f"{'BEAT' if beat else 'did not beat'} the best cohort {name} {rec} ({acc:.4f}) "
           f"on this slate.")
    if beat:
        msg += (" The cohort demonstrated nothing here — a blind home-side rule scored better. "
                "Report this comparison; do not lead with a cohort-versus-cohort improvement.")
    return {"always_home_accuracy": always_home["accuracy"], "best_cohort": name,
            "best_cohort_accuracy": acc, "best_cohort_record": rec,
            "always_home_beat_best_cohort": beat, "message": msg}


# ----------------------------------------------------------------------------- frozen gate
def _gate_block(name, blk):
    fails = []
    if not isinstance(blk, dict):
        return [f"{name}: not a baseline block"]
    if blk.get("available") is None:
        fails.append(f"{name}: no availability flag")
    for fld in SCORE_FIELDS:
        if fld not in blk:
            fails.append(f"{name}: field {fld} OMITTED — R1 requires null WITH a reason, not absence")
        elif blk.get(fld) is None and not blk.get("null_reason"):
            fails.append(f"{name}: {fld} is null with no reason string (R1)")
    return fails


def gate(res):
    """Refuse a baselines report that hides a comparator. Frozen rules:
      - every one of BASELINE_KEYS is present, available or not
      - no scoring field is absent, and no null field lacks a reason (R1)
      - ALWAYS_HOME appears as its own line with a real accuracy when it is available
      - the headline ALWAYS_HOME-vs-best-cohort comparison is computed, not left to the reader
      - every cohort is scored on the common game set, and all common-set blocks share it
      - cohorts that disagree about a graded outcome block the report entirely"""
    fails = []
    b = res.get("baselines") or {}
    for k in BASELINE_KEYS:
        if k not in b:
            fails.append(f"baseline {k} OMITTED — every frozen baseline must appear, "
                         f"null-with-reason if unavailable (this omission is the 8/21 failure)")
    for k, blk in list(b.items()) + list((res.get("other_cohorts") or {}).items()):
        fails += _gate_block(k, blk)
        for ck, sub in (blk.get("per_cohort") or {}).items() if isinstance(blk, dict) else []:
            fails += _gate_block(f"{k}.per_cohort.{ck}", sub)
    ah = res.get("always_home") if isinstance(res.get("always_home"), dict) else None
    if ah is None:
        fails.append("ALWAYS_HOME line missing — the slate's headline sanity check must be printed")
    if ah is not None:
        fails += _gate_block("always_home", ah)
        if ah.get("available") and ah.get("accuracy") is None:
            fails.append("always_home: available but accuracy is null — that number is the headline")
    hl = res.get("headline") or {}
    if ah and ah.get("available") and not hl:
        fails.append("headline ALWAYS_HOME-vs-cohort comparison missing")
    if ah and ah.get("available") and hl and hl.get("always_home_beat_best_cohort") is None \
            and hl.get("best_cohort") is not None:
        fails.append("headline present but the ALWAYS_HOME comparison verdict is null")
    # SAME GAMES
    common = set(res.get("games") or [])
    for k, blk in list(b.items()) + list((res.get("other_cohorts") or {}).items()):
        if not isinstance(blk, dict) or not blk.get("available"):
            continue
        if blk.get("cohort") and (not blk.get("scored_on_common_set")
                                  or set(blk.get("games") or []) != common):
            fails.append(f"{k}: cohort scored on {sorted(set(blk.get('games') or []))} but the "
                         f"common set is {sorted(common)} — cohorts must be scored on the SAME games")
        elif blk.get("scored_on_common_set") and set(blk.get("games") or []) != common:
            fails.append(f"{k}: claims the common game set but its games differ from {sorted(common)}")
    for c in res.get("outcome_conflicts") or []:
        fails.append(f"outcome conflict blocks the report: {c}")
    return (not fails), fails


def format_report(res):
    L = [f'DAILY BASELINES — {res["date"]}  ({res["n_games_common"]} common games)']
    ah = res["always_home"]
    L.append(f'ALWAYS_HOME            {ah["side_record"] or "-":>8}  acc '
             f'{("%.4f" % ah["accuracy"]) if ah["accuracy"] is not None else "null":>7}  '
             f'brier {"null":>8}  logloss {"null":>8}   <- headline sanity check')
    L.append(f'  {res["headline"].get("message","")}')
    L.append(f'{"baseline":<32}{"n":>4}{"W-L":>8}{"acc":>8}{"brier":>10}{"logloss":>10}')
    for k in BASELINE_KEYS:
        blk = res["baselines"][k]
        if blk.get("available") and blk.get("n") is not None:
            L.append(f'{k:<32}{blk["n"]:>4}{blk["side_record"]:>8}{blk["accuracy"]:>8.4f}'
                     f'{blk["brier"]:>10.5f}{blk["logloss"]:>10.5f}')
        else:
            L.append(f'{k:<32}{"null":>4}{"null":>8}{"null":>8}{"null":>10}{"null":>10}')
            L.append(f'    reason: {blk.get("null_reason")}')
        if k == "raw_v13_registered_card":
            for c, sub in (blk.get("per_cohort") or {}).items():
                L.append(f'    = {c} (identical by construction): {sub["side_record"]} '
                         f'acc {sub["accuracy"]:.4f} brier {sub["brier"]:.5f}')
    for c, blk in (res.get("other_cohorts") or {}).items():
        if blk.get("available") and blk.get("n") is not None:
            L.append(f'{"other cohort " + c:<32}{blk["n"]:>4}{blk["side_record"]:>8}'
                     f'{blk["accuracy"]:>8.4f}{blk["brier"]:>10.5f}{blk["logloss"]:>10.5f}')
        else:
            L.append(f'{"other cohort " + c:<32}{"null":>4}{"null":>8}{"null":>8}'
                     f'{"null":>10}{"null":>10}')
            L.append(f'    reason: {blk.get("null_reason")}')
    for e in res.get("excluded_games") or []:
        L.append(f'  EXCLUDED {e["game"]}: {e["reason"]}')
    for u in res.get("unscorable_rows") or []:
        L.append(f'  UNSCORABLE {u.get("game","?")} [{u.get("cohort","?")}]: {u["reason"]}')
    return "\n".join(L)


# ----------------------------------------------------------------------------- selftest
def _fixture_slate():
    """The 2026-08-21 shape: 15 games, home teams 14-1, v2 10-5, v1 8-7."""
    games = [f"A{i:02d}@H{i:02d}" for i in range(1, 16)]
    outcomes = {g: 1 for g in games}
    outcomes[games[14]] = 0                      # 14-1 home
    rows = []
    for i, g in enumerate(games):
        # v2: right on games 0-8 (y=1) and on game 14 (y=0) -> 10-5
        p2 = .60 if i <= 8 else .40
        # v1: right on games 0-6 and on game 14 -> 8-7
        p1 = .60 if i <= 6 else .40
        rows.append({"cohort": "v1", "board_game": g, "p_home_model": p1, "home_win": outcomes[g]})
        rows.append({"cohort": "v2", "board_game": g, "p_home_model": p2, "home_win": outcomes[g]})
    return games, outcomes, rows


def selftest():
    fails = []
    games, outcomes, rows = _fixture_slate()
    DATE = "2026-08-21"
    # results fixture: 1 of 2 prior games went home. The slate's own 14-1 and a LATER 5-0 day are
    # both present and must be invisible to the prior.
    res_rows = ([{"date": "2026-08-19", "status": "final", "home_win": "1"},
                 {"date": "2026-08-20", "status": "final", "home_win": "0"}]
                + [{"date": DATE, "status": "final", "home_win": str(outcomes[g])} for g in games]
                + [{"date": "2026-08-22", "status": "final", "home_win": "1"} for _ in range(5)])

    # RULE: the expanding prior sees ONLY strictly-earlier dates.
    p, n, why = expanding_home_win_prior(DATE, res_rows)
    if p != 0.5 or n != 2 or why is not None:
        fails.append(f"expanding prior used non-strictly-earlier rows: p={p} n={n} ({why}) — "
                     f"including the slate date would give {15/17:.4f} over 17 games")
    if expanding_home_win_prior("2026-08-22", res_rows)[0] == 0.5:
        fails.append("prior did not change when the slate date became strictly earlier — the "
                     "fixture cannot detect look-ahead, so the test is void")
    # RULE: no prior history -> null WITH a reason, never a 0.500 default.
    p0, n0, why0 = expanding_home_win_prior("2026-03-01", res_rows)
    if p0 is not None or n0 != 0 or "NO_RESULTS_STRICTLY_BEFORE_SLATE_DATE" not in (why0 or ""):
        fails.append(f"empty prior history did not return null+reason: {p0} {n0} {why0}")
    if expanding_home_win_prior(DATE, None)[0] is not None:
        fails.append("a missing results source produced a prior anyway")

    # RULE: cross-book de-vig is prohibited -> null + reason, never a number.
    xb = {"ml_away": 147, "ml_home": -158, "book_away": "dk", "book_home": "fd"}
    pv, rv = devig_entry(xb)
    if pv is not None or "CROSS_BOOK_DEVIG_PROHIBITED" not in (rv or ""):
        fails.append(f"cross-book pair was de-vigged anyway: {pv} {rv}")
    pv, rv = devig_entry({"basis": "best_odds", "ml_away": 147, "ml_home": -158})
    if pv is not None or "CROSS_BOOK_DEVIG_PROHIBITED" not in (rv or ""):
        fails.append("a best-odds screen was accepted as a market probability")
    pv, rv = devig_entry({"books": {"dk": {"away": 147}, "fd": {"home": -158}}})
    if pv is not None or "CROSS_BOOK_DEVIG_PROHIBITED" not in (rv or ""):
        fails.append("sides taken from two different books were de-vigged as if same-book")
    pv, rv = devig_entry({"ml_away": 147, "ml_home": -158})
    if pv is not None or "PRICE_BOOK_ATTRIBUTION_MISSING" not in (rv or ""):
        fails.append("an unattributed price pair was assumed same-book")
    pv, rv = devig_entry({"book": "vsin", "ml_away": 147, "ml_home": -158})
    if pv is None or rv is not None or abs(pv - 0.60201) > 1e-4:
        fails.append(f"a genuine same-book pair was refused or mis-de-vigged: {pv} {rv} "
                     f"(imp(-158)/(imp(147)+imp(-158)) = 0.60201)")
    bal, balr = devig_entry({"books": {"a": {"away": 100, "home": -100}}})
    if balr is not None or abs(bal - 0.5) > 1e-9:
        fails.append(f"balanced same-book pair did not de-vig to 0.5: {bal} {balr}")

    # ---- full report on the 14-1 slate, with only cross-book prices available
    xprices = {"games": {g: dict(xb) for g in games}}
    r = baselines(DATE, rows, res_rows, xprices)
    ok, gf = gate(r)
    if not ok:
        fails.append(f"gate rejected a well-formed report: {gf}")
    # RULE: ALWAYS_HOME accuracy is computed correctly on the 14-1 fixture.
    ah = r["always_home"]
    if ah["side_record"] != "14-1" or ah["accuracy"] != round(14 / 15, 4) or ah["n"] != 15:
        fails.append(f"ALWAYS_HOME wrong on the 14-1 fixture: {ah['side_record']} {ah['accuracy']}")
    if ah["brier"] is not None or ah["logloss"] is not None:
        fails.append("ALWAYS_HOME reported a Brier/log loss for a deterministic strategy")
    # RULE: the headline comparison is produced automatically.
    hl = r["headline"]
    if hl["always_home_beat_best_cohort"] is not True or hl["best_cohort"] != "v2":
        fails.append(f"headline missed that ALWAYS_HOME beat the best cohort: {hl}")
    if "demonstrated nothing" not in hl["message"]:
        fails.append("headline did not state the consequence when a blind rule beat the cohorts")
    # cohort records
    if r["baselines"]["v2_resolved_starters_cohort"]["side_record"] != "10-5":
        fails.append(f'v2 record wrong: {r["baselines"]["v2_resolved_starters_cohort"]["side_record"]}')
    if r["baselines"]["v1_all_cap_cohort"]["side_record"] != "8-7":
        fails.append(f'v1 record wrong: {r["baselines"]["v1_all_cap_cohort"]["side_record"]}')
    # RULE: the prior baseline uses the strictly-earlier value and is scored on the slate.
    pri = r["baselines"]["expanding_home_win_prior"]
    if pri["prior_p_home"] != 0.5 or pri["prior_sample_n"] != 2 or pri["n"] != 15:
        fails.append(f"prior baseline block wrong: {pri['prior_p_home']} {pri['prior_sample_n']} {pri['n']}")
    if pri["side_record"] != "14-1":
        fails.append("prior >= .5 must pick the home side in every game, matching ALWAYS_HOME")
    # RULE: unavailable baselines are PRESENT with a reason, never omitted.
    for k in BASELINE_KEYS:
        if k not in r["baselines"]:
            fails.append(f"{k} omitted from the report")
    mk = r["baselines"]["market_no_vig_when_captured"]
    if mk["available"] or "CROSS_BOOK_DEVIG_PROHIBITED" not in (mk["null_reason"] or ""):
        fails.append(f"cross-book-only prices produced a market baseline: {mk['null_reason']}")
    if any(mk[f] is not None for f in SCORE_FIELDS):
        fails.append("an unavailable market baseline carried non-null scores")
    cl = r["baselines"]["closing_market"]
    if cl["available"] or "NO_CLOSING_PRICES_CAPTURED" not in (cl["null_reason"] or ""):
        fails.append(f"closing baseline not reported as null-with-reason: {cl['null_reason']}")
    # RULE: raw V13 is labeled identical to the cohorts, not duplicated as an independent number.
    rv13 = r["baselines"]["raw_v13_registered_card"]
    if rv13["independent_comparator"] is not False or sorted(rv13["identical_to_cohorts"]) != ["v1", "v2"]:
        fails.append(f"raw V13 not labeled as identical to the cohorts: {rv13.get('identical_to_cohorts')}")
    if rv13["brier"] is not None or "SCORES_REPORTED_PER_COHORT" not in (rv13["null_reason"] or ""):
        fails.append("raw V13 reported an aggregate score, silently duplicating the cohort")
    if rv13["per_cohort"]["v2"]["brier"] != r["baselines"]["v2_resolved_starters_cohort"]["brier"]:
        fails.append("raw V13 per-cohort score is not the cohort's own score")

    # ---- same-book prices, half of them closing
    good = {"games": {g: {"captured": {"book": "vsin", "ml_away": 147, "ml_home": -158},
                          "close": {"book": "vsin", "ml_away": 120, "ml_home": -129}} for g in games}}
    r2 = baselines(DATE, rows, res_rows, good)
    if not r2["baselines"]["market_no_vig_when_captured"]["available"]:
        fails.append("same-book captured prices did not produce a market baseline")
    if not r2["baselines"]["closing_market"]["available"]:
        fails.append("same-book closing prices did not produce a closing baseline")
    if (r2["baselines"]["closing_market"]["brier"]
            == r2["baselines"]["market_no_vig_when_captured"]["brier"]):
        fails.append("closing and captured market baselines collapsed into one number")
    if not gate(r2)[0]:
        fails.append(f"gate rejected the priced report: {gate(r2)[1]}")

    # the repo's own {"events": [...]} capture shape normalises, and top-level book attribution
    # applies to every event (an events file with NO book stays refused, not assumed same-book)
    ev = {"book": "owner_board", "source": "prose claim, not machine-checkable",
          "events": [{"matchup": g, "ml_away": 147, "ml_home": -158} for g in games]}
    if not baselines(DATE, rows, res_rows, ev)["baselines"]["market_no_vig_when_captured"]["available"]:
        fails.append("the repo's events-shaped price capture was not normalised")
    ev_nobook = {"events": [{"matchup": g, "ml_away": 147, "ml_home": -158} for g in games],
                 "source": "same-board two-sided (prose)"}
    mb = baselines(DATE, rows, res_rows, ev_nobook)["baselines"]["market_no_vig_when_captured"]
    if mb["available"] or "PRICE_BOOK_ATTRIBUTION_MISSING" not in (mb["null_reason"] or ""):
        fails.append("an events file whose only same-book claim is prose was de-vigged anyway")

    # RULE: a market priced on only part of the slate is never compared against a cohort scored on
    # all of it — the block must carry the cohort Briers recomputed on the SAME priced subset.
    part = {"games": {g: {"book": "vsin", "ml_away": 147, "ml_home": -158} for g in games[:5]}}
    pm = baselines(DATE, rows, res_rows, part)["baselines"]["market_no_vig_when_captured"]
    if pm["n"] != 5 or "cohort_brier_on_priced_subset" not in pm:
        fails.append("a partial market was reported without the matching cohort subset Briers")
    else:
        want = round(sum(brier(.60 if i <= 8 else .40, outcomes[g])
                         for i, g in enumerate(games[:5])) / 5, 6)
        if pm["cohort_brier_on_priced_subset"].get("v2") != want:
            fails.append(f'subset cohort Brier wrong: {pm["cohort_brier_on_priced_subset"]} != {want}')
        if pm.get("same_games_as_cohorts") is not False:
            fails.append("a partial market claimed it covered the full common game set")

    # the printed surface must not crash on an extra cohort or on a fully-null report
    for _r in (r, r2, baselines(DATE, rows + [{"cohort": "v3", "board_game": games[0],
                                               "p_home_model": .5, "home_win": outcomes[games[0]]}],
                                res_rows, None)):
        txt = format_report(_r)
        if "ALWAYS_HOME" not in txt:
            fails.append("the rendered report dropped the ALWAYS_HOME line")
        for k in BASELINE_KEYS:
            if k not in txt:
                fails.append(f"the rendered report dropped baseline {k} — unavailable is still printed")

    # RULE: cohorts are scored on the SAME games — an extra game in one cohort is excluded, not
    # silently included, and the excluded game is reported with a reason.
    extra = rows + [{"cohort": "v1", "board_game": "ZZ@ZZ", "p_home_model": .9, "home_win": 1}]
    r3 = baselines(DATE, extra, res_rows, None)
    if r3["n_games_common"] != 15 or r3["baselines"]["v1_all_cap_cohort"]["n"] != 15:
        fails.append(f'v1 scored {r3["baselines"]["v1_all_cap_cohort"]["n"]} games against v2\'s 15 '
                     f'— the head-to-head is no longer on identical games')
    if not any(e["game"] == "ZZ@ZZ" for e in r3["excluded_games"]):
        fails.append("a game dropped from the comparison was not reported with a reason")

    # RULE: a cohort with no rows is reported null-with-reason, not omitted.
    only_v2 = [x for x in rows if x["cohort"] == "v2"]
    r4 = baselines(DATE, only_v2, res_rows, None)
    v1b = r4["baselines"]["v1_all_cap_cohort"]
    if v1b["available"] or "NO_V1_COHORT_ROWS" not in (v1b["null_reason"] or ""):
        fails.append("a missing cohort was not reported as null-with-reason")
    if not gate(r4)[0]:
        fails.append(f"gate rejected a report whose missing cohort was properly declared: {gate(r4)[1]}")

    # RULE: ungraded / probability-less rows are surfaced, never silently dropped.
    r5 = baselines(DATE, rows + [{"cohort": "v2", "board_game": "QQ@QQ", "p_home_model": .5}],
                   res_rows, None)
    if not any(u.get("game") == "QQ@QQ" and "NOT_GRADED" in u["reason"] for u in r5["unscorable_rows"]):
        fails.append("an ungraded row vanished without a reason")

    # ---- gate fixtures: each would PASS if the corresponding rule were deleted
    import copy
    g1 = copy.deepcopy(r)
    g1["baselines"].pop("closing_market")
    if gate(g1)[0]:
        fails.append("gate passed a report with a baseline OMITTED — the 8/21 failure mode")
    g2 = copy.deepcopy(r)
    g2["baselines"]["market_no_vig_when_captured"]["null_reason"] = None
    if gate(g2)[0]:
        fails.append("gate passed a null baseline with no reason string (R1)")
    g3 = copy.deepcopy(r)
    g3["baselines"]["v1_all_cap_cohort"]["games"] = games[:14]
    g3["baselines"]["v1_all_cap_cohort"]["scored_on_common_set"] = False
    if gate(g3)[0]:
        fails.append("gate passed a cohort scored on a game set other than the common one")
    g3b = copy.deepcopy(r)                       # claims the common set, games say otherwise
    g3b["baselines"]["expanding_home_win_prior"]["games"] = games[:14]
    if gate(g3b)[0]:
        fails.append("gate passed a block claiming the common game set whose games differ from it")
    g4 = copy.deepcopy(r)
    g4["always_home"] = None
    if gate(g4)[0]:
        fails.append("gate passed a report with no ALWAYS_HOME line")
    g5 = copy.deepcopy(r)
    g5["always_home"]["accuracy"] = None
    if gate(g5)[0]:
        fails.append("gate passed an available ALWAYS_HOME with a null accuracy")
    g6 = copy.deepcopy(r)
    g6["headline"] = {}
    if gate(g6)[0]:
        fails.append("gate passed a report with no ALWAYS_HOME-vs-cohort headline")
    g7 = copy.deepcopy(r)                        # a reasoned block may still not DROP a field:
    del g7["baselines"]["closing_market"]["logloss"]   # null-with-reason, never absent (R1)
    if gate(g7)[0]:
        fails.append("gate passed a block with a scoring field omitted entirely rather than nulled")
    g7b = copy.deepcopy(r)
    del g7b["baselines"]["v2_resolved_starters_cohort"]["logloss"]
    if gate(g7b)[0]:
        fails.append("gate passed a scored cohort missing its log loss")
    conflict = rows + [{"cohort": "v3", "board_game": games[0], "p_home_model": .5, "home_win": 0}]
    r6 = baselines(DATE, conflict, res_rows, None)
    if not r6["outcome_conflicts"] or gate(r6)[0]:
        fails.append("cohorts disagreeing about a graded outcome did not block the report")

    # a cohort that BEATS always-home must not be flagged as beaten
    strong = [dict(x, p_home_model=(.6 if outcomes[x["board_game"]] == 1 else .4))
              for x in rows if x["cohort"] == "v2"]
    r7 = baselines(DATE, strong, res_rows, None)
    if r7["headline"]["always_home_beat_best_cohort"] is not False:
        fails.append("a perfect cohort was still reported as beaten by ALWAYS_HOME")

    # ---- real-data anti-look-ahead check (only if the season file is present)
    if os.path.exists(RESULTS):
        real = load_results()
        a = expanding_home_win_prior("2026-08-21", real)
        b = expanding_home_win_prior("2026-08-22", real)
        if a[0] is None or b[0] is None:
            fails.append("real results file produced no expanding prior")
        elif not (a[1] < b[1] and abs(a[0] - b[0]) > 1e-9):
            fails.append(f"real-file prior did not change when 2026-08-21 became strictly earlier "
                         f"({a} vs {b}) — look-ahead would be undetectable")

    if fails:
        print("daily_baselines selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("daily_baselines selftest: PASS (expanding prior uses strictly-earlier results only and "
          "is null+reason with no history; cross-book/best-odds/unattributed prices return "
          "CROSS_BOOK_DEVIG_PROHIBITED rather than a number while a same-book pair de-vigs; "
          "ALWAYS_HOME is 14-1 = .9333 on the 8/21 fixture and is flagged as beating the best "
          "cohort; raw V13 is labeled identical to the cohort instead of duplicated; every "
          "unavailable baseline is present with a reason and the gate refuses an omitted one)")
    return 0


def _cli_rows(date, grades_path=None):
    p = grades_path or os.path.join(ANALYSIS, f"{date}_grades.json")
    if not os.path.exists(p):
        raise SystemExit(f"no graded cohort rows found at {p}")
    return json.load(open(p)).get("rows", [])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--grades")
    ap.add_argument("--prices")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    if not a.date:
        ap.error("--date or --selftest required")
    prices = json.load(open(a.prices)) if a.prices else None
    res = baselines(a.date, _cli_rows(a.date, a.grades), None, prices)
    print(format_report(res))
    ok, gf = gate(res)
    if not ok:
        print("\nBASELINE GATE: FAIL")
        for f in gf:
            print("  ! " + f)
    raise SystemExit(0 if ok else 1)
