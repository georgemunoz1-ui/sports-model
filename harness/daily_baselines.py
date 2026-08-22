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
# DEFECTS CLOSED 2026-08-22 — STILL NOT WIRED, STILL AWAITING OWNER RATIFICATION
# This module was quarantined the same day after an adversarial review found 8 critical/high
# defects and, worse, that its own fixtures were largely DECORATIVE: 21 of 63 mutants SURVIVED,
# including `brier -> abs(p-y)` and `logloss` with its sign dropped. All 8 are now closed:
#   1  Brier and log loss are pinned to hand-computed constants that do not call this module
#   2  the price-basis check is an ALLOWLIST — an unrecognised basis is refused, not accepted
#   3  book agreement holds over EVERY named board, and `cross_book` is coerced, not identity-checked
#   4  zero common games BLOCKS the gate; below 5 games the BEAT verdict is null with a reason
#   5  format_report renders every report the gate certifies, and the CLI prints the verdict first
#   6  unmarked price timing is UNKNOWN — it no longer defaults into the pregame market baseline
#   7  an available=False block may not leak a score past the gate
#   8  the BEAT boundary is strictly-greater and a tie is pinned by fixture
# plus one found while repairing: a PARTIAL grade snapshot is refused rather than scored as a slate.
#
# `--mutants` runs 32 source mutants and requires the selftest to FAIL for each. 32/32 are KILLED.
# That harness had the same disease it exists to cure — it patched the MUTANTS list literal instead
# of the function whenever the target was defined below the list, silently reporting two real
# mutants as survivors. Fixed; the list region is now excised before patching.
#
# WHAT IS STILL NOT TRUE: this repair has not been independently re-reviewed, and promotion is an
# owner act. The module is READS-ONLY and writes nothing, but it is NOT imported by healthcheck and
# is NOT wired into any card, grade or decision. Numbers from it are diagnostic and must be labeled
# as such until the owner ratifies it.
# Review: docs/audits/2026-08-22_roadmap_module_review.json
# Repair: docs/experiments/2026-08-22_DAILY_BASELINES_REPAIR.json
# =============================================================================================

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(BASE, "data/backfill/mlb/2026/results.csv")
ANALYSIS = os.path.join(BASE, "data/mlb/analysis")
EPS = 1e-6

R1 = "R1: unknown is null plus a reason code — never a default, never invented"

# Below this many common games the headline BEAT/did-not-beat verdict is suppressed: a one- or
# two-game "a blind rule beat the cohort" line reads as a finding and is a coin flip (defect 4).
MIN_GAMES_FOR_VERDICT = 5

# Price-basis handling is an ALLOWLIST, not a denylist (defect 2). A denylist of best-odds spellings
# accepts every spelling nobody thought of — 'best price', 'best_line', 'best_available', 'shop',
# 'consensus' all de-vigged to a number and passed the gate. An unrecognised basis is now REFUSED,
# which is the R1 posture this module claims everywhere else.
SAME_BOARD_BASES = ("", "board", "same_book", "same_board", "single_book", "book", "one_book",
                    "two_sided", "two_sided_same_book")
# Kept as a denylist too, so a KNOWN best-odds label gets the specific 8/3 ruling as its reason
# rather than the generic unrecognised-basis message.
CROSS_BOOK_BASES = ("best_odds", "cross_book", "best_price", "best_line", "best_available",
                    "best", "shop", "shopped", "consensus", "aggregate", "aggregated")

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


def _norm_token(v):
    """Fold a label to a comparison token. Hyphens AND spaces both normalise: 'best odds' and
    'best-odds' are the same claim as 'best_odds', and the earlier hyphen-only fold let the
    space-separated spellings straight through (defect 2)."""
    t = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in t:
        t = t.replace("__", "_")
    return t.strip("_")


def _truthy(v):
    """`cross_book` arrived as the string 'true' through any CSV/YAML/env round-trip and an
    `is True` identity check ignored it (defect 3). Coerce instead."""
    return v is True or _norm_token(v) in ("1", "true", "yes", "y", "t")


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
    basis = _norm_token(entry.get("basis"))
    if _truthy(entry.get("cross_book")) or basis in CROSS_BOOK_BASES:
        return None, ("CROSS_BOOK_DEVIG_PROHIBITED — best-odds prices come from different boards; "
                      "two-sided de-vig across books normalises against a vig no book quoted (8/3 ruling)")
    if basis not in SAME_BOARD_BASES:
        return None, (f"UNRECOGNISED_PRICE_BASIS — basis {entry.get('basis')!r} is not a recognised "
                      f"same-board basis, so the pair cannot be SHOWN to have come off one board. "
                      f"Refused rather than accepted by default; " + R1)
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
    # Every named board on the pair must be the SAME board. The earlier check only fired when BOTH
    # per-side books were present and disagreed, so {"book":"dk","book_away":"fd"} — a shape
    # split_prices produces on its own by merging top-level defaults into every entry — de-vigged
    # happily and passed the gate (defect 3). Agreement is now over the whole named set.
    named = {_norm_token(x) for x in (entry.get("book"), entry.get("book_away"),
                                      entry.get("book_home")) if x}
    if len(named) > 1:
        return None, (f"CROSS_BOOK_DEVIG_PROHIBITED — the pair names more than one board "
                      f"({sorted(named)}); two-sided de-vig requires one board (8/3 ruling)")
    if not named:
        return None, ("PRICE_BOOK_ATTRIBUTION_MISSING — the pair carries no book attribution, so it "
                      "cannot be shown to be same-book; assuming it would reintroduce cross-book de-vig")
    return devig_same_book(a, h), None


def split_prices(prices):
    """Normalise the `prices` argument into (captured, closing, unknown_timing) — THREE buckets.

    An unmarked price file used to fall into `captured` by default, so a closing-price file scored
    as the pregame market baseline was indistinguishable from a genuine pregame capture (defect 6).
    That is the one direction in this module where later information can leak into an earlier
    baseline, so an entry with no timing evidence now lands in `unknown` and is scored by NEITHER
    market baseline. Timing must be stated, per-entry or top-level.

    Accepted: {"games": {...}, "book": ..., "basis": ..., "timing": "close"} with the top-level
    book/basis as per-game defaults, or a bare {game: entry} mapping. A per-game entry may itself
    carry {"captured"/"pregame": ..., "close"/"closing": ...}."""
    if not prices:
        return {}, {}, {}
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
    CLOSE_T = ("close", "closing", "closer", "final", "post")
    PRE_T = ("capture", "captured", "pregame", "pre_game", "pre", "open", "opening", "intake")
    top = _norm_token(prices.get("timing"))
    captured, close, unknown = {}, {}, {}
    for k, e in games.items():
        if not isinstance(e, dict):
            continue
        c = cl = unk = None
        if any(t in e for t in ("captured", "pregame", "close", "closing")):
            c = e.get("captured") or e.get("pregame")
            cl = e.get("close") or e.get("closing")
        else:
            t = _norm_token(e.get("timing")) or top
            if t in CLOSE_T:
                cl = e
            elif t in PRE_T:
                c = e
            else:
                # No timing evidence anywhere. NOT assumed pregame.
                unk = e
        for bucket, val in ((captured, c), (close, cl), (unknown, unk)):
            if isinstance(val, dict):
                bucket[k] = {**defaults, **val}
    return captured, close, unknown


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
    captured, closing, unknown_timing = split_prices(prices)
    if unknown_timing:
        # R1: prices whose capture time is unstated are scored by neither market baseline, and the
        # count is NAMED so the operator sees what was set aside rather than silently absorbed.
        unknown_reason = (
            f"PRICE_CAPTURE_TIME_UNKNOWN — {len(unknown_timing)} price entr"
            f"{'y' if len(unknown_timing) == 1 else 'ies'} carry no timing marker "
            f"(no per-entry captured/pregame/close key, no `timing` field, no top-level `timing`). "
            f"An unmarked file is NOT assumed pregame: scoring a closing file as the pregame market "
            f"baseline would leak later information into an earlier comparator; " + R1)
    cohort_probs = {c: {r["game"]: r["p_home"] for r in rs} for c, rs in by_coh.items()}
    blocks["market_no_vig_when_captured"] = _market_block(
        "market no-vig probability (when captured)", captured, outcomes, games, cohort_probs,
        (unknown_reason if unknown_timing and not captured
         else "NO_PRICE_CAPTURED — no market prices were captured for this slate; " + R1),
        unknown_timing_n=len(unknown_timing))
    blocks["closing_market"] = _market_block(
        "closing market no-vig probability", closing, outcomes, games, cohort_probs,
        (unknown_reason if unknown_timing and not closing
         else "NO_CLOSING_PRICES_CAPTURED — no closing prices exist for this slate; " + R1),
        unknown_timing_n=len(unknown_timing))

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

    headline = _headline(always_home, blocks, other, len(games))
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


def _market_block(label, entries, outcomes, games, cohort_probs, empty_reason, unknown_timing_n=0):
    """Score a market comparator, refusing anything that is not a same-book two-sided de-vig."""
    if not entries:
        return _unavailable(label, empty_reason, per_game_null_reasons={},
                            same_games_as_cohorts=False, unknown_timing_n=unknown_timing_n)
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


def _headline(always_home, blocks, other, n_common=None):
    """The 8/21 question, computed every time: did ALWAYS_HOME beat the best cohort?

    Below MIN_GAMES_FOR_VERDICT the comparison is still COMPUTED and printed, but the BEAT verdict
    is null with a reason and the "the cohort demonstrated nothing" consequence sentence is
    suppressed (defect 4). A one-game slate previously rendered a coin flip in the same imperative
    voice as the 15-game finding this module was written for."""
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
    # STRICTLY greater. A tie is NOT a beat: equal accuracy means the blind rule did not outscore
    # the cohort, and the boundary is pinned by a fixture so `>` can never drift to `>=`.
    beat = always_home["accuracy"] > acc
    small = n_common is not None and n_common < MIN_GAMES_FOR_VERDICT
    msg = (f"ALWAYS_HOME {always_home['side_record']} ({always_home['accuracy']:.4f}) "
           f"{'BEAT' if beat else 'did not beat'} the best cohort {name} {rec} ({acc:.4f}) "
           f"on this slate.")
    out = {"always_home_accuracy": always_home["accuracy"], "best_cohort": name,
           "best_cohort_accuracy": acc, "best_cohort_record": rec,
           "always_home_beat_best_cohort": beat, "verdict_null_reason": None}
    if small:
        # Below the floor the comparison is stated NEUTRALLY. "BEAT", capitalised, reads as a
        # finding even with a qualifier bolted on after it (defect 4).
        msg = (f"ALWAYS_HOME {always_home['side_record']} ({always_home['accuracy']:.4f}) versus the "
               f"best cohort {name} {rec} ({acc:.4f}) — "
               f"{'higher' if beat else ('level' if always_home['accuracy'] == acc else 'lower')} "
               f"on this slate.")
        out["always_home_beat_best_cohort"] = None
        out["raw_comparison_beat"] = beat
        out["verdict_null_reason"] = (
            f"SAMPLE_TOO_SMALL_FOR_A_VERDICT — {n_common} common game"
            f"{'' if n_common == 1 else 's'} is below the {MIN_GAMES_FOR_VERDICT}-game floor. The "
            f"raw comparison is reported for the record; it is NOT a finding about either side, and "
            f"the consequence sentence is withheld deliberately; " + R1)
        out["message"] = msg + " " + out["verdict_null_reason"]
        return out
    if beat:
        msg += (" The cohort demonstrated nothing here — a blind home-side rule scored better. "
                "Report this comparison; do not lead with a cohort-versus-cohort improvement.")
    out["message"] = msg
    return out


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
    if blk.get("available") is False:
        # An unavailable comparator that still carries an n, a record or a Brier reads as scored.
        # The earlier gate only checked the reverse direction (defect 7).
        for fld in SCORE_FIELDS:
            if blk.get(fld) is not None:
                fails.append(f"{name}: available=False but {fld}={blk.get(fld)!r} — an unavailable "
                             f"comparator must not leak a score")
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
    if res.get("n_games_common") == 0:
        fails.append("n_games_common == 0 — no game is common to EVERY cohort, so no head-to-head "
                     "comparison exists. Disjoint cohort game sets are precisely the condition this "
                     "module exists to detect; a report over an empty set is not a comparison")
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
            and hl.get("best_cohort") is not None and not hl.get("verdict_null_reason"):
        fails.append("headline present but the ALWAYS_HOME comparison verdict is null with no "
                     "reason — a suppressed verdict must say why it was suppressed (R1)")
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
                # Guarded exactly like the baseline loop above. An unavailable per-cohort block
                # carries None here, and the unguarded format spec raised TypeError on a report the
                # gate certified as valid (defect 5).
                if sub.get("available") and sub.get("accuracy") is not None \
                        and sub.get("brier") is not None:
                    L.append(f'    = {c} (identical by construction): {sub["side_record"]} '
                             f'acc {sub["accuracy"]:.4f} brier {sub["brier"]:.5f}')
                else:
                    L.append(f'    = {c} (identical by construction): null — '
                             f'{sub.get("null_reason")}')
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
    xprices = {"timing": "pregame", "games": {g: dict(xb) for g in games}}
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
    ev = {"book": "owner_board", "timing": "pregame", "source": "prose claim, not machine-checkable",
          "events": [{"matchup": g, "ml_away": 147, "ml_home": -158} for g in games]}
    if not baselines(DATE, rows, res_rows, ev)["baselines"]["market_no_vig_when_captured"]["available"]:
        fails.append("the repo's events-shaped price capture was not normalised")
    ev_nobook = {"events": [{"matchup": g, "ml_away": 147, "ml_home": -158} for g in games],
                 "timing": "pregame", "source": "same-board two-sided (prose)"}
    mb = baselines(DATE, rows, res_rows, ev_nobook)["baselines"]["market_no_vig_when_captured"]
    if mb["available"] or "PRICE_BOOK_ATTRIBUTION_MISSING" not in (mb["null_reason"] or ""):
        fails.append("an events file whose only same-book claim is prose was de-vigged anyway")

    # RULE: a market priced on only part of the slate is never compared against a cohort scored on
    # all of it — the block must carry the cohort Briers recomputed on the SAME priced subset.
    part = {"timing": "pregame",
            "games": {g: {"book": "vsin", "ml_away": 147, "ml_home": -158} for g in games[:5]}}
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

    # =========================================================================================
    # FIXTURES CLOSING THE 2026-08-22 ADVERSARIAL REVIEW (docs/audits/2026-08-22_roadmap_module_review.json)
    # Every one below is mutation-proven: `--mutants` re-runs this selftest against a source mutant
    # of the rule it guards and REQUIRES the selftest to fail. A fixture that cannot fail is
    # decoration (lesson 21), and the nine defects here all survived the original fixture set.
    # =========================================================================================

    # DEFECT 1 (critical) — the scoring arithmetic itself was never pinned. `brier` could return
    # abs(p-y) and `logloss` could drop its minus sign while the selftest printed PASS and the gate
    # printed green. These constants are hand-computed and do NOT call the module.
    if brier(0.6, 1) != 0.16000000000000003 and round(brier(0.6, 1), 12) != 0.16:
        fails.append(f"brier(0.6,1) = {brier(0.6,1)} — must be (0.6-1)^2 = 0.16")
    if round(brier(0.4, 0), 12) != 0.16:
        fails.append(f"brier(0.4,0) = {brier(0.4,0)} — must be 0.16")
    if round(brier(0.75, 0), 12) != 0.5625:
        fails.append(f"brier(0.75,0) = {brier(0.75,0)} — must be 0.5625")
    if round(brier(1.0, 1), 12) != 0.0 or round(brier(0.0, 1), 12) != 1.0:
        fails.append("brier is not the squared error at its endpoints")
    # -ln(0.6) = 0.5108256237659907 ; -ln(0.25) = 1.3862943611198906
    if round(logloss(0.6, 1), 10) != 0.5108256238:
        fails.append(f"logloss(0.6,1) = {logloss(0.6,1)} — must be -ln(0.6) = 0.5108256238")
    if round(logloss(0.75, 0), 10) != 1.3862943611:
        fails.append(f"logloss(0.75,0) = {logloss(0.75,0)} — must be -ln(0.25) = 1.3862943611")
    if round(logloss(0.5, 1), 10) != 0.6931471806:
        fails.append(f"logloss(0.5,1) = {logloss(0.5,1)} — must be ln(2) = 0.6931471806")
    if logloss(0.0, 1) <= 0 or not math.isfinite(logloss(0.0, 1)):
        fails.append("logloss at the clamp must be finite and POSITIVE — a negative log loss "
                     "printed to an operator is a sign error, not a good score")
    if logloss(0.9, 1) >= logloss(0.6, 1):
        fails.append("logloss is not decreasing in a correct confident probability — sign inverted")
    # ... and pinned again THROUGH score_probs, so a correct scorer wired up wrongly is also caught.
    sp = score_probs("pin", {"g1": 0.6, "g2": 0.75}, {"g1": 1, "g2": 0}, ["g1", "g2"])
    if sp["brier"] != round((0.16 + 0.5625) / 2, 6) or sp["brier"] != 0.36125:
        fails.append(f"score_probs mean Brier = {sp['brier']} — must be (0.16+0.5625)/2 = 0.36125")
    if sp["logloss"] != 0.94856:
        fails.append(f"score_probs mean log loss = {sp['logloss']} — must be "
                     f"(0.5108256238+1.3862943611)/2 = 0.94856")
    if sp["side_record"] != "1-1" or sp["accuracy"] != 0.5:
        fails.append(f"score_probs side accounting wrong: {sp['side_record']} {sp['accuracy']}")

    # DEFECT 2 (critical) — the basis denylist was a closed 3-item tuple. Every spelling below
    # de-vigged to 0.60201 and passed the gate. The check is now an ALLOWLIST.
    for bad_basis in ("best odds", "cross book", "best price", "best_line", "best available",
                      "best", "shop", "consensus", "BEST-ODDS", "  best   odds  ", "aggregate",
                      "screen", "anything nobody thought of"):
        pv, rv = devig_entry({"basis": bad_basis, "book": "vsin", "ml_away": 147, "ml_home": -158})
        if pv is not None:
            fails.append(f"basis {bad_basis!r} produced a market probability {pv} — the basis check "
                         f"must REFUSE what it does not recognise, not accept it by default")
        elif not (("CROSS_BOOK_DEVIG_PROHIBITED" in (rv or ""))
                  or ("UNRECOGNISED_PRICE_BASIS" in (rv or ""))):
            fails.append(f"basis {bad_basis!r} refused with an unrelated reason: {rv}")
    for ok_basis in ("", None, "board", "same_book", "same-board", "single book"):
        pv, rv = devig_entry({"basis": ok_basis, "book": "vsin", "ml_away": 147, "ml_home": -158})
        if pv is None:
            fails.append(f"a stated same-board basis {ok_basis!r} was refused: {rv} — the allowlist "
                         f"must not reject the shape the repo actually captures")

    # DEFECT 3 (critical) — one-sided attribution CONTRADICTING the top-level book was accepted as
    # same-book. split_prices merges the top-level book into every entry, so this shape is reachable
    # from an ordinary capture file, not just hand-built input.
    pv, rv = devig_entry({"book": "dk", "book_away": "fd", "ml_away": 147, "ml_home": -158})
    if pv is not None or "CROSS_BOOK_DEVIG_PROHIBITED" not in (rv or ""):
        fails.append(f"a pair naming dk at top level and fd on the away side de-vigged anyway: "
                     f"{pv} {rv} — agreement must hold over EVERY named board, not just the pair")
    pv, rv = devig_entry({"book": "dk", "book_home": "fd", "ml_away": 147, "ml_home": -158})
    if pv is not None or "CROSS_BOOK_DEVIG_PROHIBITED" not in (rv or ""):
        fails.append(f"top-level/home-side book disagreement de-vigged anyway: {pv} {rv}")
    pv, rv = devig_entry({"book": "dk", "book_away": "DK", "ml_away": 147, "ml_home": -158})
    if pv is None:
        fails.append(f"'dk' and 'DK' were treated as different boards: {rv}")
    for truthy in (True, "true", "True", "yes", "1", 1):
        pv, rv = devig_entry({"cross_book": truthy, "book": "vsin",
                              "ml_away": 147, "ml_home": -158})
        if pv is not None or "CROSS_BOOK_DEVIG_PROHIBITED" not in (rv or ""):
            fails.append(f"cross_book={truthy!r} was ignored — an `is True` identity check misses "
                         f"every string round-trip through CSV/YAML/env")
    # end-to-end: the whole reachable shape must not produce a scored market baseline
    e2e = {"book": "consensus_best", "timing": "pregame",
           "games": {g: {"book_away": "dk", "ml_away": 147, "ml_home": -158} for g in games}}
    mk_e2e = baselines(DATE, rows, res_rows, e2e)["baselines"]["market_no_vig_when_captured"]
    if mk_e2e["available"] or mk_e2e["brier"] is not None:
        fails.append(f"the end-to-end cross-book shape still produced a market Brier "
                     f"{mk_e2e['brier']} with available={mk_e2e['available']}")

    # DEFECT 4 (high) — zero common games passed the gate, and a ONE-game slate printed
    # "the cohort demonstrated nothing" in the same voice as the 15-game finding.
    empty = baselines(DATE, [], res_rows, None)
    if empty["n_games_common"] != 0:
        fails.append("the empty-cohort fixture does not actually produce an empty common set")
    if gate(empty)[0]:
        fails.append("gate PASSED a report with zero common games — no comparison exists there")
    disjoint = baselines(DATE, [
        {"cohort": "v1", "board_game": "A@B", "p_home_model": .6, "home_win": 1},
        {"cohort": "v2", "board_game": "C@D", "p_home_model": .6, "home_win": 1}], res_rows, None)
    if disjoint["n_games_common"] != 0 or gate(disjoint)[0]:
        fails.append("gate PASSED cohorts with DISJOINT game sets — the exact not-a-head-to-head "
                     "condition this module exists to detect")
    one = baselines(DATE, [
        {"cohort": "v1", "board_game": "A@B", "p_home_model": .40, "home_win": 1},
        {"cohort": "v2", "board_game": "A@B", "p_home_model": .45, "home_win": 1}], res_rows, None)
    hl1 = one["headline"]
    if one["n_games_common"] != 1:
        fails.append("the one-game fixture is not one game")
    if hl1.get("always_home_beat_best_cohort") is not None:
        fails.append("a ONE-game slate returned a definitive BEAT verdict — a coin flip rendered "
                     "as a finding is the failure mode this floor exists to stop")
    if "SAMPLE_TOO_SMALL_FOR_A_VERDICT" not in (hl1.get("verdict_null_reason") or ""):
        fails.append("the suppressed verdict carries no reason (R1)")
    if "demonstrated nothing" in (hl1.get("message") or ""):
        fails.append("the consequence sentence was printed below the sample floor")
    if hl1.get("raw_comparison_beat") is None:
        fails.append("the raw comparison was withheld entirely — it belongs in the record, it just "
                     "is not a verdict")
    if not gate(one)[0]:
        fails.append(f"gate rejected a valid small-sample report: {gate(one)[1]} — the floor "
                     "suppresses the VERDICT, it does not invalidate the report")
    # and the floor must not silence the real 15-game finding
    if r["headline"].get("always_home_beat_best_cohort") is not True:
        fails.append("the sample floor suppressed the genuine 15-game verdict")

    # DEFECT 8 (medium) — the BEAT boundary. A tie is NOT a beat, and `>` must not drift to `>=`.
    tie_rows = []
    tg = [f"T{i}@U{i}" for i in range(10)]
    for i, g in enumerate(tg):
        y = 1 if i < 7 else 0                       # ALWAYS_HOME goes 7-3
        # cohort picks home on the same 7 it wins and away on the 3 it loses -> 7-3 as well? no:
        # make the cohort exactly 7-3 by picking home everywhere it is right and away where it is
        # wrong in equal measure. Simplest exact tie: cohort picks home on all 10 -> 7-3.
        tie_rows.append({"cohort": "v1", "board_game": g, "p_home_model": .6, "home_win": y})
    tie = baselines(DATE, tie_rows, res_rows, None)
    ah_acc = tie["always_home"]["accuracy"]
    v1_acc = tie["baselines"]["v1_all_cap_cohort"]["accuracy"]
    if ah_acc != v1_acc:
        fails.append(f"the tie fixture is not a tie ({ah_acc} vs {v1_acc}) — the boundary is untested")
    elif tie["headline"]["always_home_beat_best_cohort"] is not False:
        fails.append("a TIE was reported as ALWAYS_HOME beating the cohort — the comparison must be "
                     "STRICTLY greater")
    elif "did not beat" not in tie["headline"]["message"]:
        fails.append("a tie did not render as 'did not beat'")

    # DEFECT 5 (high) — format_report must render every report the gate certifies as valid.
    for name, rep in (("14-1 slate", r), ("priced", r2), ("one game", one), ("tie", tie),
                      ("empty", empty), ("disjoint", disjoint)):
        try:
            txt = format_report(rep)
        except Exception as exc:
            fails.append(f"format_report raised {type(exc).__name__} on the {name} report: {exc}")
        else:
            if not txt or "DAILY BASELINES" not in txt:
                fails.append(f"format_report produced no report for {name}")
    # the specific crash: a per-cohort block that is unavailable
    crashy = dict(r)
    crashy["baselines"] = dict(r["baselines"])
    crashy["baselines"]["raw_v13_registered_card"] = dict(r["baselines"]["raw_v13_registered_card"])
    crashy["baselines"]["raw_v13_registered_card"]["per_cohort"] = {
        "v9": _unavailable("v9 cohort", "NO_ROWS — nothing to score; " + R1, cohort="v9")}
    try:
        format_report(crashy)
    except Exception as exc:
        fails.append(f"format_report still crashes on an unavailable per-cohort block: "
                     f"{type(exc).__name__}: {exc}")

    # DEFECT 6 (high) — an UNMARKED price file must not populate the pregame market baseline.
    unmarked = {"games": {g: {"book": "vsin", "ml_away": 147, "ml_home": -158} for g in games}}
    ur = baselines(DATE, rows, res_rows, unmarked)
    umk = ur["baselines"]["market_no_vig_when_captured"]
    if umk["available"] or umk["brier"] is not None:
        fails.append("an unmarked price file populated the PREGAME market baseline — a closing file "
                     "would then be scored as the pregame comparator, which is look-ahead")
    if "PRICE_CAPTURE_TIME_UNKNOWN" not in (umk["null_reason"] or ""):
        fails.append(f"unmarked prices refused with the wrong reason: {umk['null_reason']}")
    if ur["baselines"]["closing_market"]["available"]:
        fails.append("an unmarked price file populated the CLOSING baseline")
    if umk.get("unknown_timing_n") != len(games):
        fails.append(f"the set-aside count was not named: {umk.get('unknown_timing_n')}")
    # ... while an explicitly-marked file still works in BOTH directions
    for mark, key, other_key in (("pregame", "market_no_vig_when_captured", "closing_market"),
                                 ("close", "closing_market", "market_no_vig_when_captured")):
        mk_p = {"timing": mark,
                "games": {g: {"book": "vsin", "ml_away": 147, "ml_home": -158} for g in games}}
        mr = baselines(DATE, rows, res_rows, mk_p)["baselines"]
        if not mr[key]["available"]:
            fails.append(f"timing={mark!r} did not populate {key}: {mr[key]['null_reason']}")
        if mr[other_key]["available"]:
            fails.append(f"timing={mark!r} ALSO populated {other_key} — the buckets must be disjoint")

    # DEFECT 7 (medium) — an unavailable block must never leak a score past the gate.
    for fld, val in (("n", 15), ("brier", 0.2), ("accuracy", 0.9333), ("side_record", "14-1"),
                     ("logloss", 0.65)):
        leaky = json.loads(json.dumps(r))
        blk = leaky["baselines"]["closing_market"]
        if blk["available"]:
            fails.append("the leak fixture needs an UNAVAILABLE block to mutate")
            break
        blk[fld] = val
        if gate(leaky)[0]:
            fails.append(f"gate PASSED an available=False block carrying {fld}={val!r} — an "
                         f"unavailable comparator that still prints a score reads as scored")

    # UPSTREAM — a PARTIAL grade snapshot is refused, not scored. This is the source of the
    # one-game 8/21 run the review found printing a directive off a coin flip.
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        # The two refusal branches are tested SEPARATELY. Combined in one fixture they cover for
        # each other: deleting either branch still refuses, so neither is actually proven.
        _R = [{"cohort": "v1", "board_game": "A@B", "p_home_model": .4, "home_win": 1},
              {"cohort": "v2", "board_game": "A@B", "p_home_model": .45, "home_win": 1}]
        cases = [
            # (filename, doc, what the branch is)
            ("skipped_only.json",
             {"already_graded_skipped": ["P4-A", "P4-B"], "rows": _R},
             "a file listing games graded in an EARLIER run (no completeness string at all)"),
            ("completeness_only.json",
             {"completeness": "15 of 15 graded", "rows": _R},
             "a file CLAIMING 15 graded games while carrying 1 distinct game (no skipped list)"),
        ]
        for fn, doc, what in cases:
            pp = os.path.join(td, fn)
            json.dump(doc, open(pp, "w"))
            try:
                _cli_rows("2026-08-21", pp)
            except SystemExit as exc:
                if "PARTIAL_GRADE_SNAPSHOT" not in str(exc):
                    fails.append(f"{what} refused with the wrong reason: {exc}")
            else:
                fails.append(f"{what} was scored as if it were the slate")
        # a COMPLETE snapshot still loads
        full = os.path.join(td, "full_grades.json")
        json.dump({"completeness": "2 of 2 graded", "rows": [
            {"cohort": "v1", "board_game": "A@B", "p_home_model": .4, "home_win": 1},
            {"cohort": "v1", "board_game": "C@D", "p_home_model": .6, "home_win": 1}]},
            open(full, "w"))
        try:
            if len(_cli_rows("2026-08-21", full)) != 2:
                fails.append("a complete grades snapshot did not load")
        except SystemExit as exc:
            fails.append(f"a complete grades snapshot was refused: {exc}")

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


# ----------------------------------------------------------------------------- mutation harness
# LESSON 21: a passing selftest is not a proven fixture. The 2026-08-22 adversarial review ran 63
# mutants against the ORIGINAL fixture set; 21 SURVIVED, including `brier -> abs(p-y)` and
# `logloss -> +(...)`. Every mutant below is a rule this module claims to enforce, expressed as a
# source edit. `--mutants` applies each to a temp copy and REQUIRES that copy's selftest to FAIL.
# A mutant that survives is printed as SURVIVED and the run exits non-zero: the fixture guarding it
# is decoration and the claim it backs must not be made.
MUTANTS = [
    # --- scoring arithmetic (defect 1: NOT ONE value was pinned before)
    ("brier: squared error -> absolute error", "    return (p - y) ** 2", "    return abs(p - y)"),
    ("brier: squared error -> constant", "    return (p - y) ** 2", "    return 0.25"),
    ("logloss: sign dropped", "    return -(y * math.log(p) + (1 - y) * math.log(1 - p))",
     "    return (y * math.log(p) + (1 - y) * math.log(1 - p))"),
    ("logloss: y and 1-y transposed", "    return -(y * math.log(p) + (1 - y) * math.log(1 - p))",
     "    return -((1 - y) * math.log(p) + y * math.log(1 - p))"),
    ("logloss: log -> log10", "    return -(y * math.log(p) + (1 - y) * math.log(1 - p))",
     "    return -(y * math.log10(p) + (1 - y) * math.log10(1 - p))"),
    ("score_probs: mean -> sum", '"brier": round(sum(brier(probs[g], outcomes[g]) for g in gs) / n, 6)',
     '"brier": round(sum(brier(probs[g], outcomes[g]) for g in gs), 6)'),
    # --- de-vig direction and price arithmetic
    ("devig: home/away transposed", "    return ih / (ia + ih)", "    return ia / (ia + ih)"),
    ("imp: favourite/dog branches swapped",
     "    return (-a) / ((-a) + 100) if a < 0 else 100 / (a + 100)",
     "    return 100 / (a + 100) if a < 0 else (-a) / ((-a) + 100)"),
    # --- defect 2: the basis allowlist
    ("basis: allowlist reverted to the 3-item denylist",
     "    if basis not in SAME_BOARD_BASES:", "    if False:"),
    ("basis: space normalisation removed",
     '.replace("-", "_").replace(" ", "_")', '.replace("-", "_")'),
    ("basis: unrecognised accepted by default",
     "SAME_BOARD_BASES = (", "SAME_BOARD_BASES = tuple(CROSS_BOOK_BASES) + ("),
    # --- defect 3: book-set agreement and cross_book coercion
    ("book agreement: only the two per-side books compared (the old check)",
     "    if len(named) > 1:",
     "    if len({_norm_token(x) for x in (entry.get('book_away'), entry.get('book_home')) if x}) > 1:"),
    ("cross_book: coercion reverted to an `is True` identity check",
     "    if _truthy(entry.get(\"cross_book\")) or basis in CROSS_BOOK_BASES:",
     "    if entry.get(\"cross_book\") is True or basis in CROSS_BOOK_BASES:"),
    ("attribution: unattributed pair assumed same-book",
     "    if not named:", "    if False:"),
    # --- defect 4: sample floor and the empty comparison set
    ("gate: zero common games passes",
     '    if res.get("n_games_common") == 0:', "    if False:"),
    ("headline: sample floor removed",
     "    small = n_common is not None and n_common < MIN_GAMES_FOR_VERDICT",
     "    small = False"),
    ("headline: floor lowered to 1 game", "MIN_GAMES_FOR_VERDICT = 5", "MIN_GAMES_FOR_VERDICT = 1"),
    # (`None or (x)` is x — that first attempt was a no-op mutant, which is itself the lesson-21
    #  failure mode one level up: a mutant that changes nothing proves nothing either.)
    ("headline: suppressed verdict loses its reason",
     '        out["verdict_null_reason"] = (', '        out["verdict_null_reason"] = None and ('),
    # --- defect 8: the BEAT boundary
    ("headline: BEAT boundary `>` -> `>=`",
     '    beat = always_home["accuracy"] > acc', '    beat = always_home["accuracy"] >= acc'),
    ("headline: consequence sentence deleted",
     '        msg += (" The cohort demonstrated nothing here', '        msg += ("" or (" '),
    # --- defect 6: price timing
    ("timing: unmarked prices default to `captured` again",
     "                unk = e", "                c = e"),
    ("timing: close and pregame buckets collapsed",
     "            if t in CLOSE_T:", "            if False:"),
    # --- defect 7: unavailable blocks leaking a score
    ("gate: unavailable block may carry a score",
     '    if blk.get("available") is False:', "    if False:"),
    # --- defect 5: rendering
    ("format_report: per-cohort guard removed",
     '                if sub.get("available") and sub.get("accuracy") is not None \\\n                        and sub.get("brier") is not None:',
     "                if True:"),
    # --- rules the ORIGINAL fixtures did hold (kept so a repair cannot silently undo them)
    ("prior: strictly-before -> inclusive (look-ahead)", "        if not d or d >= date:",
     "        if not d or d > date:"),
    ("prior: empty history defaults to 0.500", "        return None, 0, (f\"NO_RESULTS_STRICTLY_BEFORE",
     "        return 0.5, 0, (f\"NO_RESULTS_STRICTLY_BEFORE"),
    ("gate: a missing frozen baseline is tolerated", "        if k not in b:", "        if False:"),
    ("same-games: cohorts may be scored on different games",
     "        if blk.get(\"cohort\") and (not blk.get(\"scored_on_common_set\")",
     "        if False and blk.get(\"cohort\") and (not blk.get(\"scored_on_common_set\")"),
    ("always_home: reports a Brier for a deterministic rule",
     '            "brier": None, "logloss": None,\n            "sides_home": len(ah_games)',
     '            "brier": 0.0667, "logloss": 0.25,\n            "sides_home": len(ah_games)'),
    ("partial grade snapshot scored as the slate", "    if skipped:", "    if False:"),
    ("partial snapshot: completeness mismatch ignored", "    if m and rows and int(m.group(1)) >",
     "    if False and m and rows and int(m.group(1)) >"),
    ("outcome conflicts no longer block the report",
     '    for c in res.get("outcome_conflicts") or []:', "    for c in []:"),
]


def mutation_suite(verbose=True):
    """Run every mutant. Returns the list of SURVIVORS (empty is the only acceptable result)."""
    import subprocess, tempfile
    src = open(os.path.abspath(__file__)).read()
    # The MUTANTS list quotes the very code it patches, so a naive replace(old, new, 1) rewrites the
    # LIST ENTRY instead of the function whenever the target is defined below the list — which
    # silently turned two real mutants into no-ops and reported them as SURVIVORS. The list region
    # is excised before patching, and both halves are searched.
    _i = src.index("MUTANTS = [")
    _j = src.index("\ndef mutation_suite", _i)
    head, block, tail = src[:_i], src[_i:_j], src[_j:]
    survivors, unapplied = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapplied.append(f"{name}: pattern not found in executable source (it may exist only "
                             f"inside the MUTANTS list) — the mutant proves nothing")
            continue
        if where == "head":
            mutated = head.replace(old, new, 1) + block + tail
        else:
            mutated = head + block + tail.replace(old, new, 1)
        if mutated == src:
            unapplied.append(f"{name}: replacement was a no-op")
            continue
        with tempfile.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                         dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mutated)
            path = fh.name
        try:
            pr = subprocess.run([sys.executable, path, "--selftest"],
                                capture_output=True, text=True, timeout=180)
            killed = pr.returncode != 0
        except subprocess.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}")
        if not killed:
            survivors.append(name)
    for u in unapplied:
        print(f"  UNAPPLIED  {u}")
    ok = not survivors and not unapplied
    print(f"mutation suite: {len(MUTANTS) - len(survivors) - len(unapplied)}/{len(MUTANTS)} killed"
          f"{'' if ok else '  — SURVIVORS/UNAPPLIED MEAN THE FIXTURES ARE DECORATIVE'}")
    return survivors + unapplied


def _cli_rows(date, grades_path=None):
    """Load cohort rows for a slate, REFUSING a partial snapshot.

    A grades file is rewritten on every settlement run, and a re-run that re-grades one late game
    lists the other fourteen under `already_graded_skipped` and carries ONE row per cohort. Scoring
    that silently is how the 2026-08-21 slate produced a one-game 'the cohort demonstrated nothing'
    directive off a single coin flip. The sample floor now suppresses that verdict, but the honest
    fix is upstream: a snapshot that says it graded 15 games and hands over 1 is REFUSED here, with
    the discrepancy named, rather than scored as if it were the slate."""
    p = grades_path or os.path.join(ANALYSIS, f"{date}_grades.json")
    if not os.path.exists(p):
        raise SystemExit(f"no graded cohort rows found at {p}")
    doc = json.load(open(p))
    rows = doc.get("rows", [])
    skipped = doc.get("already_graded_skipped") or []
    if skipped:
        raise SystemExit(
            f"PARTIAL_GRADE_SNAPSHOT — {p} carries {len(rows)} row(s) but lists {len(skipped)} "
            f"game(s) as already graded in an earlier run ({', '.join(sorted(skipped)[:3])}"
            f"{'...' if len(skipped) > 3 else ''}). Scoring this file would compare the cohorts on "
            f"a re-graded remainder, not on the slate. Supply the full-slate rows with --grades, or "
            f"rebuild them from the forecast/grade chain; " + R1)
    stated = str(doc.get("completeness") or "")
    m = re.match(r"\s*(\d+)\s+of\s+(\d+)", stated)
    if m and rows and int(m.group(1)) > len({r.get("board_game") or r.get("game") for r in rows}):
        raise SystemExit(
            f"PARTIAL_GRADE_SNAPSHOT — {p} states completeness {stated!r} but carries only "
            f"{len({r.get('board_game') or r.get('game') for r in rows})} distinct game(s); " + R1)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mutants", action="store_true",
                    help="run every mutant against the selftest; a SURVIVOR means the fixture "
                         "guarding that rule is decoration (lesson 21)")
    ap.add_argument("--date")
    ap.add_argument("--grades")
    ap.add_argument("--prices")
    a = ap.parse_args()
    if a.mutants:
        raise SystemExit(1 if mutation_suite() else 0)
    if a.selftest:
        raise SystemExit(selftest())
    if not a.date:
        ap.error("--date or --selftest required")
    prices = json.load(open(a.prices)) if a.prices else None
    res = baselines(a.date, _cli_rows(a.date, a.grades), None, prices)
    # The GATE VERDICT is the operator-facing output and must survive a rendering failure: printing
    # the report first meant a format crash replaced the verdict with a traceback (defect 5).
    ok, gf = gate(res)
    try:
        print(format_report(res))
    except Exception as exc:
        print(f"REPORT RENDERING FAILED ({type(exc).__name__}: {exc}) — the gate verdict below "
              f"still stands and a rendering failure is itself a defect, not a pass")
        ok, gf = False, gf + [f"format_report raised {type(exc).__name__}: {exc}"]
    if not ok:
        print("\nBASELINE GATE: FAIL")
        for f in gf:
            print("  ! " + f)
    raise SystemExit(0 if ok else 1)
