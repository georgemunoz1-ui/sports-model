#!/usr/bin/env python3
"""Mechanical freshness and domain gates for the CARD ACTION layer (owner roadmap item 7).

WHICH LAYER THIS TOUCHES — AND WHICH TWO IT MUST NOT
The owner ratified a three-layer separation on 2026-08-20: REGISTER everything, GATE actions,
GRADE everything. This module is the middle layer and nothing else. A gate firing here does not
stop a forecast being registered, does not remove a row from any settlement or diagnostic sample,
and does not touch a grade. It says exactly one thing: the card may not ACT on this row. That is
the same doctrine harness/ats_ledgers.py already encodes ("gate classifies, never filters"), and
it is why 8/19 was never retro-gated. This module reads its argument and writes nothing at all —
no registered artifact is opened, let alone modified.

WHY MECHANICAL. Every one of the six conditions below has already been caught by a human reading
a card, and prose promises to "keep it in mind" have failed repeatedly (the margin-as-spread defect
recurred a second time before it was gate-enforced). A condition that only a careful reader catches
is not a control.

THE SIX GATES (each returns a distinct status token, additive — all that hold are reported):

  FEATURE_STATE_TOO_STALE          the feature state behind the forecast is older than the frozen
                                   maximum (default 21 days). The live 2026-07-22 WNBA freeze was
                                   30 days stale on 8/21; the owner calls that too stale to act on
                                   in late August, when rosters and rotations have moved.
  PERSONNEL_UNAVAILABLE            no official injury report, or not even an expected lineup.
  OUT_OF_DOMAIN_NEUTRAL_SITE       neutral or alternate venue with no neutral-site term in the
                                   frozen feature set.
  STARTER_SOURCE_CONFLICT          sources name different starting pitchers.
  STARTER_NOT_IN_REGISTRY          a NAMED starter is absent from the frozen registry.
  PRICES_INCOMPLETE_OR_CROSS_BOOK  complete same-book prices could not be captured.

UNKNOWN IS NOT CLEAN (R1). Where a gate cannot establish its fact — no feature-state date, no
personnel block, no registry to check against, no book attribution on a price pair — the gate FIRES
and its reason says the value is null and why. Absence of evidence of freshness is not evidence of
freshness; the alternative is a gate that passes precisely the rows nobody has data on. No missing
value is ever filled in with a guess.

WHAT THIS MODULE DELIBERATELY DOES NOT RE-LITIGATE. A TBD (unannounced) starter is absence, not
conflict — "absence of information is not a starter change" (8/19) — and the CAP/LOW_SAMPLE/
REGISTRY_MISS predicates already live in unified_card.slot_status(). Gate 4 fires on CONFLICT and
gate 5 on a NAMED pitcher the registry does not know. Neither pretends to own the TBD case.

API
    evaluate_gates(row, config) -> {"blocked": bool, "statuses": [...], "reasons": [...]}
`statuses` holds each fired token once, in the frozen GATE_ORDER; `reasons[i]` is the plain-English
reason for `statuses[i]` (several causes for one token are joined with "; "). Any single fired gate
blocks card action. Row shape is documented on _ROW_SHAPE below.

Usage: python3 harness/freshness_gates.py --selftest | --row-json PATH
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

MODULE_ID = "freshness_gates"

import argparse
import datetime as dt
import json
import os
import sys
import unicodedata

_ROW_SHAPE = """
row = {
  "sport": "mlb" | "wnba" | ...,
  "game": "AWAY@HOME",
  "slate_date": "YYYY-MM-DD",              # the date the card would ACT on
  "feature_state_as_of": "YYYY-MM-DD",     # when the model's inputs were last refreshed
  "feature_state_age_days": int,           # optional precomputed age (WNBA cards carry staleness_days)
  "personnel": {"injury_report": "OFFICIAL"|"UNAVAILABLE"|None,
                "lineup_state": "OFFICIAL"|"EXPECTED"|"NONE_AVAILABLE"|None},
  "venue": {"neutral_site": bool, "alternate_venue": bool, "venue_name": str},
  "starters": {"away": {"name_by_source": {"source": "Name", ...}, "in_registry": bool|None},
               "home": {...}},             # or {"name": "Name"} for a single-source slot
  "prices": {"book": "dk", "ml_away": -118, "ml_home": +102}          # one board, both sides
           | {"book_away": "dk", "book_home": "dk", ...}              # explicit per-side books
           | {"books": {"dk": {"away": -118, "home": +102}, ...}}     # several boards
           | {"markets": {"moneyline": <entry>, "total": <entry>}},   # per-market completeness
}
"""

# ---- frozen constants ----------------------------------------------------------------------
FEATURE_STATE_MAX_AGE_DAYS = 21  # frozen default (owner, roadmap item 7)

GATE_ORDER = (
    "FEATURE_STATE_TOO_STALE",
    "PERSONNEL_UNAVAILABLE",
    "OUT_OF_DOMAIN_NEUTRAL_SITE",
    "STARTER_SOURCE_CONFLICT",
    "STARTER_NOT_IN_REGISTRY",
    "PRICES_INCOMPLETE_OR_CROSS_BOOK",
)

# Bettor-facing label per status. decision_card.TRANSLATE refuses any internal token that reaches
# the decision surface untranslated; this module cannot edit that file, so it ships its own
# translations for the orchestrator to merge. A new gate with no entry here fails the selftest.
PLAIN_ENGLISH = {
    "FEATURE_STATE_TOO_STALE": "Blocked — the model's team-strength inputs are too old to act on",
    "PERSONNEL_UNAVAILABLE": "Blocked — injury or lineup information is not available",
    "OUT_OF_DOMAIN_NEUTRAL_SITE": "Blocked — neutral or alternate venue the model does not handle",
    "STARTER_SOURCE_CONFLICT": "Blocked — sources name different starting pitchers",
    "STARTER_NOT_IN_REGISTRY": "Blocked — a named starting pitcher is unknown to the frozen registry",
    "PRICES_INCOMPLETE_OR_CROSS_BOOK": "Blocked — no single book quoted a complete price for this game",
}

FROZEN_DEFAULTS = {
    "feature_state_max_age_days": FEATURE_STATE_MAX_AGE_DAYS,  # int, or {sport: int}
    "feature_state_required_sports": ("wnba",),
    # Flips to True only when a neutral-site term actually enters the frozen feature set. Until
    # then it is False and gate 3 fires on every neutral or alternate venue.
    "neutral_site_modeled": False,
    "starter_registry": None,   # iterable of registered starter names; None = no registry supplied
    "as_of_date": None,         # action-date fallback when the row carries none
}

_ABSENT_NAMES = {"", "tbd", "t.b.d.", "tba", "none", "null", "n/a", "na", "unannounced"}
_BEST_ODDS_BASES = ("best_odds", "best_price", "best_available", "best_line", "cross_book")


# ---- helpers -------------------------------------------------------------------------------
def fold(s):
    """NFKD-fold to bare lowercase ascii. Same comparator as grade_slate.fold(): card names carry
    accents ("Cristopher Sanchez", "Martin Perez") and boards do not, and a naive compare reported
    those as starter CHANGES — which once inflated the starter-defect count from 4 to 6. A
    diacritic is not a disagreement."""
    f = unicodedata.normalize("NFKD", (s or "")).encode("ascii", "ignore").decode()
    return " ".join(f.lower().split())


def _max_age(cfg, sport):
    v = cfg.get("feature_state_max_age_days", FEATURE_STATE_MAX_AGE_DAYS)
    if isinstance(v, dict):
        return v.get(sport, v.get("default", FEATURE_STATE_MAX_AGE_DAYS))
    return v


def _date(s):
    try:
        return dt.date.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def _side(entry, which):
    v = entry.get(which)
    return entry.get("ml_" + which) if v is None else v


# ---- gate 1: freshness ---------------------------------------------------------------------
def gate_feature_state(row, cfg):
    """Feature state older than the frozen maximum age blocks card action.

    WHY (owner, 2026-08-21): the live WNBA feature state is frozen at 2026-07-22. On 8/21 that is
    30 days old — a third of a season of roster, rotation and role change that the forecast cannot
    see — and the owner ruled it too stale for late-August action. 21 days is the frozen ceiling.
    The state stays perfectly usable for REGISTRATION and for grading; only the card is gated.

    The age must be CHECKABLE. A row with no feature-state date and no precomputed age fires, and
    so does a state dated after the slate (an age that runs backwards is not interpretable, it is a
    data defect). Both say null-and-why rather than assuming freshness."""
    sport = str(row.get("sport") or "").lower()
    has_field = ("feature_state_as_of" in row) or ("feature_state_age_days" in row)
    required = sport in {str(s).lower() for s in cfg.get("feature_state_required_sports") or ()}
    if not (has_field or required):
        return []  # this sport declares no feature state; nothing to date, nothing to assume
    limit = _max_age(cfg, sport)
    age = row.get("feature_state_age_days")
    as_of_raw = row.get("feature_state_as_of")
    if age is None:
        as_of = _date(as_of_raw)
        action = _date(row.get("slate_date") or row.get("date") or cfg.get("as_of_date"))
        if as_of is None:
            return [("FEATURE_STATE_TOO_STALE",
                     f"the age of the model's team-strength inputs cannot be established "
                     f"(no refresh date recorded; value is null, recorded as null and not guessed), "
                     f"so it cannot be certified inside the {limit}-day freshness limit")]
        if action is None:
            return [("FEATURE_STATE_TOO_STALE",
                     f"the inputs were refreshed {as_of_raw} but this row carries no slate date to "
                     f"measure that against (null), so the {limit}-day freshness limit cannot be checked")]
        age = (action - as_of).days
        if age < 0:
            return [("FEATURE_STATE_TOO_STALE",
                     f"the model's inputs are dated {as_of_raw}, AFTER the slate date "
                     f"{action.isoformat()} — the age runs backwards and is not interpretable")]
    if age > limit:
        stamp = f" (last refreshed {as_of_raw})" if as_of_raw else ""
        return [("FEATURE_STATE_TOO_STALE",
                 f"the model's team-strength inputs are {age} days old{stamp}, past the {limit}-day "
                 f"freshness limit — recent form, roles and roster changes are not represented")]
    return []


# ---- gate 2: personnel ---------------------------------------------------------------------
_OK_INJURY = {"OFFICIAL", "OFFICIAL_NONE_OUT", "OFFICIAL_FULL"}
_OK_LINEUP = {"OFFICIAL", "CONFIRMED", "POSTED", "EXPECTED", "PROJECTED_OFFICIAL"}


def gate_personnel(row, cfg):
    """No official injury report, or not even an expected lineup, blocks card action.

    WHY (2026-08-14 and repeatedly since): V13 simulated CWS@DET and BAL@TB with the wrong people
    on the field and both graded as losses; personnel state has been the top roadmap item ever
    since. A forecast built on the wrong roster is not a weak forecast, it is a forecast of a
    different game.

    THIS GATE ASKS FOR AVAILABILITY, NOT CONFIRMATION, and must never be read as laundering one
    into the other. An EXPECTED lineup satisfies this gate. It does NOT satisfy V14, whose frozen
    rule requires a capture that says CONFIRMED — that ruling (8/20, starvation over contamination)
    stands untouched above this gate."""
    p = row.get("personnel")
    if not isinstance(p, dict):
        return [("PERSONNEL_UNAVAILABLE",
                 "no injury or lineup information was recorded for this game at all (null, which "
                 "is recorded as null — an empty personnel record is not a clean one)")]
    out = []
    inj = p.get("injury_report")
    if inj is None:
        out.append("no official injury report was captured for this game (null)")
    elif str(inj).upper() not in _OK_INJURY:
        out.append(f"the injury report is not official (recorded state: {inj})")
    lu = p.get("lineup_state")
    if lu is None:
        out.append("no lineup information was captured for this game (null)")
    elif str(lu).upper() not in _OK_LINEUP:
        out.append(f"no lineup is available for this game (recorded state: {lu}); an expected "
                   f"lineup would satisfy this check and not even that exists")
    return [("PERSONNEL_UNAVAILABLE", r) for r in out]


# ---- gate 3: domain ------------------------------------------------------------------------
def gate_neutral_site(row, cfg):
    """A neutral or alternate venue with no neutral-site term in the frozen feature set blocks
    card action — permanently for that row, not until prices arrive.

    WHY (2026-08-21, PDX@TOR at Rogers Arena, Vancouver): Toronto was nominally home while playing
    away from its home market. The frozen WNBA feature set has no neutral-site term, so the model
    applied a full home-court advantage to a team that did not have one. "Discount it by an unknown
    amount" is not an executable correction (lesson 18), so the row is blocked instead.

    THE ONE CORRECT OBSERVATION DOES NOT WEAKEN THIS BLOCK. That same PDX@TOR forecast was RIGHT:
    it picked the winner and its margin error, +0.55, was the smallest on the entire slate. It stays
    blocked anyway. A single out-of-domain row landing correctly is luck, not validation — the model
    was still adding an advantage it had not earned, and one draw from an untested regime cannot
    validate that regime in either direction. Reading that hit as evidence would be exactly the
    outcome-driven reasoning the base-rate caveat (lesson 20) was written to stop. The row remains
    in the winner-validation and diagnostic samples so the result is still MEASURED; only card
    action is barred.

    Config `neutral_site_modeled` flips to True only when a neutral-site term actually enters the
    frozen feature set. Until then this fires on every such venue."""
    v = row.get("venue")
    if not isinstance(v, dict):
        return []  # no venue claim at all is not a neutral-site claim; nothing is invented here
    neutral = bool(v.get("neutral_site")) or bool(v.get("alternate_venue"))
    if not neutral:
        return []
    if cfg.get("neutral_site_modeled") is True or v.get("neutral_site_modeled") is True:
        return []
    where = v.get("venue_name") or "an unnamed venue"
    kind = "a neutral site" if v.get("neutral_site") else "an alternate venue"
    return [("OUT_OF_DOMAIN_NEUTRAL_SITE",
             f"this game is at {kind} ({where}) and the model applied a full home-court advantage "
             f"it has not earned there; the frozen inputs carry no neutral-site term, so the "
             f"forecast is outside the model's domain")]


# ---- gates 4 and 5: starters ---------------------------------------------------------------
def _slot_names(slot):
    """{source: name_as_written} for the sources that actually named somebody.

    Names are returned AS WRITTEN so a reason can quote what each source said, and folded only for
    comparison (see _folded). Keeping the two apart matters: an earlier draft compared the raw
    strings and reported the real 8/17 "Cristopher Sanchez"/"Cristopher Sánchez" pair as a source
    conflict — the exact false positive grade_slate's folding was written to kill."""
    if not isinstance(slot, dict):
        return {}
    raw = slot.get("name_by_source")
    if not isinstance(raw, dict):
        raw = {}
        if slot.get("name") is not None:
            raw = {slot.get("source") or "source": slot["name"]}
    return {src: nm for src, nm in raw.items() if fold(nm) not in _ABSENT_NAMES}


def _folded(names):
    """The comparison view: {folded_name: name_as_written}. Two sources agree when, and only when,
    their folded full names are identical."""
    out = {}
    for nm in names.values():
        out.setdefault(fold(nm), nm)
    return out


def _slots(row):
    st = row.get("starters")
    if not isinstance(st, dict):
        return []
    return [(k, st[k]) for k in ("away", "home") if isinstance(st.get(k), dict)]


def gate_starter_conflict(row, cfg):
    """Sources naming different starting pitchers blocks card action.

    WHY (2026-08-19 SF@CLE): the odds board said Houser, the model's v2 basis said Wilkinson's
    debut. The row stayed blocked until an owner attestation resolved it — and the attestation
    proved the board wrong. A three-source, three-name variant already has its own translation in
    decision_card. An unresolved identity is not a small input error: the starter is the single
    largest information term this engine has (starter resolution moved probabilities ~5x more than
    form freshness).

    TWO RULES ABOUT NAMES, both learned the hard way:
      - a diacritic is not a disagreement (Sanchez/Sánchez), so names are folded before comparison;
      - agreement on a SURNAME ALONE is not agreement. On 8/20 four Rodriguezes sat in the registry
        and the slot was unresolvable; on 8/21 the board named Eduardo Rodriguez in full and the
        ambiguity did not recur. Two sources that agree only on a surname leave the identity
        unestablished, which is precisely what this gate exists to catch.
      - absence is not conflict: a source that says TBD has not contradicted anyone."""
    out = []
    for side, slot in _slots(row):
        names = _slot_names(slot)
        distinct = _folded(names)
        if len(distinct) < 2:
            continue
        listing = ", ".join(f"{src} says '{nm}'" for src, nm in sorted(names.items()))
        surname_only = len({n.split()[-1] for n in distinct}) == 1
        note = (" — they agree only on the surname, which leaves the identity unestablished"
                if surname_only else "")
        out.append(("STARTER_SOURCE_CONFLICT",
                    f"sources disagree on the {side} starting pitcher: {listing}{note}"))
    return out


def gate_starter_registry(row, cfg):
    """A NAMED starter absent from the frozen registry blocks card action.

    WHY (2026-08-21): Hayden Wesneski was named for Houston and was not in the frozen pitcher
    registry, so the slot fell back to a league-average CAP — a forecast that names a pitcher while
    modelling an average one. The same defect hid inside a completeness percentage: preflight's
    denominator counted games without a TBD NAME (12/15) and silently excluded registry-missing
    Wesneski, which is how "80% resolved" got printed for a 26/30-slot reality.

    MEMBERSHIP MUST BE PROVEN, NOT ASSUMED. If a frozen registry is supplied it decides, and the
    row's own `in_registry` claim cannot override it. If no registry is supplied and the row carries
    no verified flag, the gate FIRES and says membership is unchecked — an unverifiable name is not
    a verified one. A slot whose sources conflict is skipped here: gate 4 already governs it, and
    testing an unresolved identity against a registry would be noise."""
    registry = cfg.get("starter_registry")
    known = None
    if registry is not None:
        known = {fold(n) for n in (registry.keys() if isinstance(registry, dict) else registry)}
    out = []
    for side, slot in _slots(row):
        distinct = _folded(_slot_names(slot))
        if len(distinct) != 1:
            continue  # absent (nothing named) or conflicting (gate 4 owns it)
        folded, shown = next(iter(distinct.items()))
        if known is not None:
            if folded not in known:
                out.append(("STARTER_NOT_IN_REGISTRY",
                            f"the named {side} starting pitcher '{shown}' is not in the frozen "
                            f"registry, so the forecast names him but models a league-average "
                            f"pitcher in his place"))
            continue
        flag = slot.get("in_registry")
        if flag is True:
            continue
        if flag is False:
            out.append(("STARTER_NOT_IN_REGISTRY",
                        f"the named {side} starting pitcher '{shown}' is recorded as absent from "
                        f"the frozen registry, so a league-average pitcher was modelled instead"))
        else:
            out.append(("STARTER_NOT_IN_REGISTRY",
                        f"registry membership for the named {side} starting pitcher '{shown}' was "
                        f"never checked (no frozen registry supplied and the row records no "
                        f"membership — null, not assumed)"))
    return out


# ---- gate 6: prices ------------------------------------------------------------------------
def _price_defect(entry, label):
    """One market's price entry -> defect string or None. Shapes mirror daily_baselines.devig_entry
    so that a pair this gate passes is a pair that module can legitimately de-vig."""
    if not entry:
        return f"{label}: no prices were captured for this game"
    if not isinstance(entry, dict):
        return f"{label}: the price record is not a readable quote"
    basis = str(entry.get("basis") or "").lower().replace("-", "_").replace(" ", "_")
    if entry.get("cross_book") is True or basis in _BEST_ODDS_BASES:
        return (f"{label}: the only prices available are the best number across several books, "
                f"which no single book would honour as a pair")
    if "books" in entry:
        books = entry.get("books") or {}
        for b in books.values():
            if isinstance(b, dict) and _side(b, "away") is not None and _side(b, "home") is not None:
                return None
        have_a = any(isinstance(b, dict) and _side(b, "away") is not None for b in books.values())
        have_h = any(isinstance(b, dict) and _side(b, "home") is not None for b in books.values())
        if have_a and have_h:
            return (f"{label}: the two sides are quoted on different books and no single book "
                    f"quoted both, so there is no one market to price against")
        return f"{label}: only one side of the market was captured"
    a, h = _side(entry, "away"), _side(entry, "home")
    if a is None or h is None:
        return f"{label}: only one side of the market was captured, so the quote is incomplete"
    ba, bh, bk = entry.get("book_away"), entry.get("book_home"), entry.get("book")
    if ba and bh and fold(ba) != fold(bh):
        return (f"{label}: the away side is priced at {ba} and the home side at {bh} — two "
                f"different books, not one market")
    if not (bk or (ba and bh)):
        return (f"{label}: the pair carries no book attribution, so it cannot be shown to have come "
                f"from one book and is not assumed to have")
    return None


def gate_prices(row, cfg):
    """Complete same-book prices, or no card action.

    WHY (8/3 ruling, re-earned 8/21): a two-sided de-vig across books normalises against a vig no
    book quoted, so a best-odds pair is not a market probability — it is an artefact. On 8/21 the
    web capture surfaced 2 of 15 games, neither cleanly single-book and one one-sided; it was NOT
    ingested and every row stayed blocked. Unattributed pairs are refused rather than assumed
    same-book, because a best-odds screen and a real board look identical once the book label is
    dropped. A row with no prices at all is blocked too — nothing can be acted on at a price that
    does not exist (the entire 8/21 WNBA slate)."""
    prices = row.get("prices")
    if isinstance(prices, dict) and isinstance(prices.get("markets"), dict):
        out = []
        for mkt, entry in sorted(prices["markets"].items()):
            d = _price_defect(entry, str(mkt))
            if d:
                out.append(("PRICES_INCOMPLETE_OR_CROSS_BOOK", d))
        return out
    d = _price_defect(prices, "moneyline")
    return [("PRICES_INCOMPLETE_OR_CROSS_BOOK", d)] if d else []


GATES = (gate_feature_state, gate_personnel, gate_neutral_site,
         gate_starter_conflict, gate_starter_registry, gate_prices)


# ---- the API -------------------------------------------------------------------------------
def evaluate_gates(row, config=None):
    """Every gate that holds for `row`, not just the first. Any one of them blocks card action.

    Additive by design: the 8/21 WNBA slate was stale AND out of domain AND unpriced, and a
    first-match gate would have reported one of the three and quietly repaired nothing. Returned
    `statuses` carries each fired token once in frozen GATE_ORDER, and `reasons[i]` explains
    `statuses[i]` in plain English (multiple causes of one token joined with '; ')."""
    cfg = dict(FROZEN_DEFAULTS)
    cfg.update(config or {})
    fired = []
    for gate in GATES:
        fired.extend(gate(row, cfg) or [])
    unknown = {s for s, _ in fired} - set(GATE_ORDER)
    if unknown:
        # A status outside the frozen set would be dropped by the grouping below; fail loudly
        # instead, because a silently swallowed block is worse than a crash.
        raise ValueError(f"gate produced a status outside the frozen set: {sorted(unknown)}")
    statuses, reasons = [], []
    for st in GATE_ORDER:
        rs = [r for s, r in fired if s == st]
        if rs:
            statuses.append(st)
            reasons.append("; ".join(rs))
    return {"blocked": bool(statuses), "statuses": statuses, "reasons": reasons}


# ---- fixtures ------------------------------------------------------------------------------
def _clean_mlb_row():
    """A row nothing may fire on. The away slot deliberately carries the real 8/17 diacritic
    difference across two sources, so this fixture also proves folding works."""
    return {"sport": "mlb", "game": "ATL@MIL", "slate_date": "2026-08-21",
            "feature_state_as_of": "2026-08-19",
            "personnel": {"injury_report": "OFFICIAL", "lineup_state": "EXPECTED"},
            "venue": {"neutral_site": False, "alternate_venue": False,
                      "venue_name": "American Family Field"},
            "starters": {"away": {"name_by_source": {"owner_board": "Cristopher Sánchez",
                                                     "odds_board": "Cristopher Sanchez"}},
                         "home": {"name_by_source": {"owner_board": "Freddy Peralta"}}},
            "prices": {"book": "dk", "ml_away": -118, "ml_home": +102}}


_CLEAN_CFG = {"starter_registry": ["Cristopher Sanchez", "Freddy Peralta", "Martin Perez",
                                   "Grant Holmes"]}


def _clean_wnba_row():
    return {"sport": "wnba", "game": "MIN@WAS", "slate_date": "2026-08-21",
            "feature_state_as_of": "2026-08-20",
            "personnel": {"injury_report": "OFFICIAL", "lineup_state": "OFFICIAL"},
            "venue": {"neutral_site": False, "venue_name": "Entertainment and Sports Arena"},
            "prices": {"book": "dk", "ml_away": -145, "ml_home": +125}}


def _with(row, **kw):
    r = json.loads(json.dumps(row))
    r.update(kw)
    return r


def selftest():
    fails = []
    _frozen_at_entry = json.dumps(FROZEN_DEFAULTS, sort_keys=True, default=list)

    def st(row, cfg=_CLEAN_CFG):
        return evaluate_gates(row, cfg)

    def expect_only(tag, row, want, cfg=_CLEAN_CFG, says=None):
        """Exactly one status, and (when `says` is given) a reason that names the ACTUAL defect.

        The reason text is asserted, not just its existence: two different price defects that both
        block are not interchangeable — 'no single book quoted both sides' and 'only one side was
        captured' send a reader to different fixes, and a gate that reports the wrong one is wrong
        even though it blocked."""
        r = st(row, cfg)
        if r["statuses"] != [want]:
            fails.append(f"{tag}: expected exactly [{want}], got {r['statuses']}")
        elif not r["blocked"]:
            fails.append(f"{tag}: {want} fired but blocked was False")
        elif len(r["reasons"]) != 1 or not r["reasons"][0]:
            fails.append(f"{tag}: {want} fired with no plain-English reason")
        elif says is not None and says not in r["reasons"][0]:
            fails.append(f"{tag}: reason does not say '{says}' — it says {r['reasons'][0]!r}")

    # ---- the clean rows fire nothing (without this, a gate that always fires would 'pass') ----
    for tag, row in (("clean mlb", _clean_mlb_row()), ("clean wnba", _clean_wnba_row())):
        r = st(row)
        if r["blocked"] or r["statuses"]:
            fails.append(f"{tag} row was blocked: {r['statuses']} {r['reasons']}")

    # ---- 1. FEATURE_STATE_TOO_STALE ----------------------------------------------------------
    # the live case: 2026-07-22 freeze, 8/21 slate = 30 days
    stale = _with(_clean_wnba_row(), feature_state_as_of="2026-07-22")
    expect_only("live 30-day WNBA freeze", stale, "FEATURE_STATE_TOO_STALE")
    if "30 days" not in st(stale)["reasons"][0] or "21-day" not in st(stale)["reasons"][0]:
        fails.append(f"stale reason does not state the age and the limit: {st(stale)['reasons'][0]}")
    # boundary: 21 days is not 'exceeds'; 22 is
    if st(_with(_clean_wnba_row(), feature_state_as_of="2026-07-31"))["statuses"]:
        fails.append("exactly 21 days fired — the frozen rule is EXCEEDS 21, not reaches it")
    expect_only("22 days", _with(_clean_wnba_row(), feature_state_as_of="2026-07-30"),
                "FEATURE_STATE_TOO_STALE")
    # precomputed age (the shape WNBA cards carry) must be honoured
    expect_only("precomputed staleness_days=30",
                _with(_clean_wnba_row(), feature_state_age_days=30), "FEATURE_STATE_TOO_STALE")
    # unknown age is NOT clean
    noage = _clean_wnba_row(); noage.pop("feature_state_as_of")
    expect_only("no feature-state date", noage, "FEATURE_STATE_TOO_STALE",
                says="cannot be established")
    nodate = _clean_wnba_row(); nodate.pop("slate_date")
    expect_only("no slate date to measure against", nodate, "FEATURE_STATE_TOO_STALE",
                says="no slate date")
    expect_only("feature state dated after the slate",
                _with(_clean_wnba_row(), feature_state_as_of="2026-08-25"),
                "FEATURE_STATE_TOO_STALE", says="runs backwards")
    # a sport that declares no feature state is not blocked for lacking one
    nfl = {"sport": "nfl", "game": "NYJ@NYG", "slate_date": "2026-08-21",
           "personnel": {"injury_report": "OFFICIAL", "lineup_state": "EXPECTED"},
           "prices": {"book": "dk", "ml_away": -110, "ml_home": -110}}
    if st(nfl)["statuses"]:
        fails.append(f"a sport with no declared feature state was blocked: {st(nfl)['statuses']}")
    # a configurable limit must actually govern
    if not evaluate_gates(_with(_clean_wnba_row(), feature_state_as_of="2026-08-18"),
                          dict(_CLEAN_CFG, feature_state_max_age_days=2))["blocked"]:
        fails.append("a tightened freshness limit did not govern")

    # ---- 2. PERSONNEL_UNAVAILABLE ------------------------------------------------------------
    expect_only("no official injury report",
                _with(_clean_mlb_row(), personnel={"injury_report": "UNAVAILABLE",
                                                   "lineup_state": "EXPECTED"}),
                "PERSONNEL_UNAVAILABLE", says="injury report is not official")
    expect_only("no lineup at all (the WNBA card's NONE_AVAILABLE)",
                _with(_clean_mlb_row(), personnel={"injury_report": "OFFICIAL",
                                                   "lineup_state": "NONE_AVAILABLE"}),
                "PERSONNEL_UNAVAILABLE", says="no lineup is available")
    nopersonnel = _clean_mlb_row(); nopersonnel.pop("personnel")
    expect_only("no personnel record at all", nopersonnel, "PERSONNEL_UNAVAILABLE",
                says="no injury or lineup information")
    both = st(_with(_clean_mlb_row(), personnel={"injury_report": None, "lineup_state": None}))
    if both["statuses"] != ["PERSONNEL_UNAVAILABLE"] or "; " not in both["reasons"][0]:
        fails.append("two personnel defects did not both reach the single status' reason")
    # EXPECTED lineup satisfies availability (and must not be laundered into CONFIRMED anywhere)
    if st(_with(_clean_mlb_row(), personnel={"injury_report": "OFFICIAL",
                                             "lineup_state": "EXPECTED"}))["statuses"]:
        fails.append("an EXPECTED lineup was treated as unavailable — this gate asks availability")

    # ---- 3. OUT_OF_DOMAIN_NEUTRAL_SITE -------------------------------------------------------
    pdx = _with(_clean_wnba_row(), game="PDX@TOR",
                venue={"neutral_site": True, "venue_name": "Rogers Arena, Vancouver"})
    expect_only("PDX@TOR at Rogers Arena", pdx, "OUT_OF_DOMAIN_NEUTRAL_SITE")
    expect_only("alternate venue",
                _with(_clean_wnba_row(), venue={"alternate_venue": True, "venue_name": "elsewhere"}),
                "OUT_OF_DOMAIN_NEUTRAL_SITE")
    # THE POINT OF THE RULE: the 8/21 PDX@TOR forecast was CORRECT, margin error +0.55, the
    # smallest on the slate. Outcome fields must not move this gate one inch.
    correct = _with(pdx, forecast_correct=True, margin_error=0.55,
                    note="smallest margin error on the 8/21 slate")
    rc = st(correct)
    if not rc["blocked"] or "OUT_OF_DOMAIN_NEUTRAL_SITE" not in rc["statuses"]:
        fails.append("a CORRECT out-of-domain row escaped the block — one lucky row is not validation")
    if rc != st(pdx):
        fails.append("outcome fields changed the gate result; gates must not read outcomes")
    # only a real neutral-site term in the frozen feature set may clear it
    if evaluate_gates(pdx, dict(_CLEAN_CFG, neutral_site_modeled=True))["statuses"]:
        fails.append("a modelled neutral site still fired")
    if st(_with(_clean_wnba_row(), venue={"neutral_site": False, "venue_name": "home"}))["statuses"]:
        fails.append("an ordinary home venue fired the domain gate")

    # ---- 4. STARTER_SOURCE_CONFLICT ----------------------------------------------------------
    conflict = _clean_mlb_row()
    conflict["starters"]["away"]["name_by_source"] = {"odds_board": "Adrian Houser",
                                                      "model_basis": "Mitch Wilkinson"}
    expect_only("SF@CLE Houser/Wilkinson conflict", conflict, "STARTER_SOURCE_CONFLICT")
    three = _clean_mlb_row()
    three["starters"]["home"]["name_by_source"] = {"a": "P One", "b": "P Two", "c": "P Three"}
    r3 = st(three)
    if r3["statuses"] != ["STARTER_SOURCE_CONFLICT"] or "'P Three'" not in r3["reasons"][0]:
        fails.append(f"three-source conflict not fully reported: {r3}")
    # surname-only agreement is NOT agreement (the 8/20 four-Rodriguez slot)
    rod = _clean_mlb_row()
    rod["starters"]["home"]["name_by_source"] = {"board": "Rodriguez", "card": "Eduardo Rodriguez"}
    rr = st(rod)
    if "STARTER_SOURCE_CONFLICT" not in rr["statuses"]:
        fails.append("surname-only agreement passed as agreement — the four-Rodriguez case")
    elif "surname" not in rr["reasons"][0]:
        fails.append("surname-only conflict did not say why it is not agreement")
    # a diacritic is not a disagreement (already inside the clean row, asserted directly here)
    dia = _clean_mlb_row()
    dia["starters"]["home"]["name_by_source"] = {"card": "Martín Pérez", "board": "Martin Perez"}
    if st(dia)["statuses"]:
        fails.append(f"a diacritic-only difference fired a gate: {st(dia)['statuses']} — folded "
                     f"names must match each other AND the folded registry")
    # absence is not conflict (8/19: absence of information is not a starter change)
    tbd = _clean_mlb_row()
    tbd["starters"]["home"]["name_by_source"] = {"card": "TBD", "board": "Freddy Peralta"}
    if st(tbd)["statuses"]:
        fails.append("a TBD source was treated as contradicting a named starter")

    # ---- 5. STARTER_NOT_IN_REGISTRY ----------------------------------------------------------
    wes = _clean_mlb_row()
    wes["starters"]["home"]["name_by_source"] = {"owner_board": "Hayden Wesneski"}
    rw = st(wes)
    if rw["statuses"] != ["STARTER_NOT_IN_REGISTRY"] or "Wesneski" not in rw["reasons"][0]:
        fails.append(f"the registry-missing Wesneski slot did not fire cleanly: {rw}")
    # membership must be PROVEN: no registry and no verified flag is not a pass
    expect_only("no registry supplied", _clean_mlb_row(), "STARTER_NOT_IN_REGISTRY", cfg={},
                says="never checked")
    if evaluate_gates(_clean_mlb_row(), {"starter_registry": []})["statuses"] != ["STARTER_NOT_IN_REGISTRY"]:
        fails.append("an empty registry did not fire on named starters")
    # a row cannot self-certify past a supplied registry
    liar = _clean_mlb_row()
    liar["starters"]["home"] = {"name_by_source": {"owner_board": "Hayden Wesneski"},
                                "in_registry": True}
    if "STARTER_NOT_IN_REGISTRY" not in st(liar)["statuses"]:
        fails.append("a row's own in_registry claim overrode the frozen registry")
    # with no registry supplied, an explicitly verified flag is accepted, False fires
    flagged = _clean_mlb_row()
    for side in ("away", "home"):
        flagged["starters"][side]["in_registry"] = True
    if evaluate_gates(flagged, {})["statuses"]:
        fails.append("an explicitly verified membership flag was ignored when no registry exists")
    flagged["starters"]["home"]["in_registry"] = False
    if evaluate_gates(flagged, {})["statuses"] != ["STARTER_NOT_IN_REGISTRY"]:
        fails.append("an explicit in_registry=False did not fire")
    # a conflicting slot is governed by gate 4 only — an unresolved identity is not registry-tested
    conf_only = _clean_mlb_row()
    conf_only["starters"]["home"]["name_by_source"] = {"a": "Nobody Known", "b": "Someone Else"}
    if st(conf_only)["statuses"] != ["STARTER_SOURCE_CONFLICT"]:
        fails.append("an unresolved identity was also tested against the registry")

    # ---- 6. PRICES_INCOMPLETE_OR_CROSS_BOOK --------------------------------------------------
    noprices = _clean_mlb_row(); noprices.pop("prices")
    expect_only("no prices at all (the 8/21 slates)", noprices, "PRICES_INCOMPLETE_OR_CROSS_BOOK",
                says="no prices were captured")
    expect_only("one-sided quote",
                _with(_clean_mlb_row(), prices={"book": "dk", "ml_away": -118}),
                "PRICES_INCOMPLETE_OR_CROSS_BOOK", says="only one side")
    expect_only("sides from two different books",
                _with(_clean_mlb_row(), prices={"book_away": "dk", "book_home": "fd",
                                                "ml_away": -118, "ml_home": +102}),
                "PRICES_INCOMPLETE_OR_CROSS_BOOK", says="two different books")
    expect_only("unattributed pair (a best-odds screen looks identical)",
                _with(_clean_mlb_row(), prices={"ml_away": -118, "ml_home": +102}),
                "PRICES_INCOMPLETE_OR_CROSS_BOOK", says="no book attribution")
    # a best-odds pair is ATTRIBUTED and two-sided — it looks complete and is not; without the
    # basis rule this fixture would sail through every other price check.
    expect_only("declared best-odds basis",
                _with(_clean_mlb_row(), prices={"book": "best-of-board", "basis": "best-odds",
                                                "ml_away": -110, "ml_home": +105}),
                "PRICES_INCOMPLETE_OR_CROSS_BOOK", says="best number across several books")
    expect_only("explicit cross_book flag on an otherwise complete pair",
                _with(_clean_mlb_row(), prices={"book": "screen", "cross_book": True,
                                                "ml_away": -110, "ml_home": +105}),
                "PRICES_INCOMPLETE_OR_CROSS_BOOK", says="best number across several books")
    expect_only("multi-book map where no single book quoted both sides",
                _with(_clean_mlb_row(), prices={"books": {"dk": {"away": -118},
                                                          "fd": {"home": +102}}}),
                "PRICES_INCOMPLETE_OR_CROSS_BOOK", says="no single book quoted both")
    expect_only("multi-book map holding only one side anywhere",
                _with(_clean_mlb_row(), prices={"books": {"dk": {"away": -118},
                                                          "fd": {"away": -120}}}),
                "PRICES_INCOMPLETE_OR_CROSS_BOOK", says="only one side")
    if st(_with(_clean_mlb_row(), prices={"books": {"dk": {"away": -118, "home": +102},
                                                    "fd": {"home": +104}}}))["statuses"]:
        fails.append("a book quoting BOTH sides was rejected — that pair is legitimately de-viggable")
    if st(_with(_clean_mlb_row(), prices={"book_away": "dk", "book_home": "DK",
                                          "ml_away": -118, "ml_home": +102}))["statuses"]:
        fails.append("one book named with different capitalisation read as two books")
    # per-market completeness: a complete moneyline does not excuse an incomplete total
    mkt = _with(_clean_mlb_row(), prices={"markets": {
        "moneyline": {"book": "dk", "ml_away": -118, "ml_home": +102},
        "total": {"books": {"dk": {"away": -110}, "fd": {"home": -110}}}}})
    rm = st(mkt)
    if rm["statuses"] != ["PRICES_INCOMPLETE_OR_CROSS_BOOK"] or "total" not in rm["reasons"][0]:
        fails.append(f"per-market price completeness did not name the incomplete market: {rm}")

    # ---- additivity: every gate that holds is reported, and any one blocks -------------------
    multi = {"sport": "wnba", "game": "PDX@TOR", "slate_date": "2026-08-21",
             "feature_state_as_of": "2026-07-22",
             "personnel": {"injury_report": None, "lineup_state": "NONE_AVAILABLE"},
             "venue": {"neutral_site": True, "venue_name": "Rogers Arena, Vancouver"},
             "starters": {"home": {"name_by_source": {"a": "Adrian Houser", "b": "Mitch Wilkinson"}},
                          "away": {"name_by_source": {"a": "Hayden Wesneski"}}},
             "prices": {"basis": "best_odds", "ml_away": -110, "ml_home": +100}}
    rmulti = st(multi)
    if sorted(rmulti["statuses"]) != sorted(GATE_ORDER):
        fails.append(f"all six simultaneous gates did not all appear: {rmulti['statuses']}")
    if rmulti["statuses"] != [s for s in GATE_ORDER if s in rmulti["statuses"]]:
        fails.append("fired statuses are not in frozen GATE_ORDER")
    if len(rmulti["reasons"]) != len(rmulti["statuses"]):
        fails.append("statuses and reasons are not index-aligned")
    if len(set(rmulti["statuses"])) != len(rmulti["statuses"]):
        fails.append("a status token was reported more than once")
    if not rmulti["blocked"]:
        fails.append("six simultaneous gates did not block")
    # a real subset case: stale + out of domain + unpriced, and nothing else
    sub = {"sport": "wnba", "game": "PDX@TOR", "slate_date": "2026-08-21",
           "feature_state_as_of": "2026-07-22",
           "personnel": {"injury_report": "OFFICIAL", "lineup_state": "OFFICIAL"},
           "venue": {"neutral_site": True, "venue_name": "Rogers Arena, Vancouver"}}
    if st(sub)["statuses"] != ["FEATURE_STATE_TOO_STALE", "OUT_OF_DOMAIN_NEUTRAL_SITE",
                               "PRICES_INCOMPLETE_OR_CROSS_BOOK"]:
        fails.append(f"the real 8/21 PDX@TOR row reported the wrong gate set: {st(sub)['statuses']}")

    # ---- the gate reads; it never writes, not even to its own argument -----------------------
    # A gate that quietly repairs the row it inspects would launder a defect into the record — the
    # same class of harm as writing to a registered artifact, one call earlier.
    # Both probes are built from FRESH literals, never from `multi` or _CLEAN_CFG: those objects
    # have already been handed to the gates above, so a gate that scribbles on its argument would
    # have scribbled on them BEFORE the snapshot and the diff would show nothing. (That is exactly
    # how the first version of this check passed a mutant that added a key to every row.)
    probe = {"sport": "wnba", "game": "PDX@TOR", "slate_date": "2026-08-21",
             "feature_state_as_of": "2026-07-22",
             "personnel": {"injury_report": None, "lineup_state": "NONE_AVAILABLE"},
             "venue": {"neutral_site": True, "venue_name": "Rogers Arena, Vancouver"},
             "starters": {"home": {"name_by_source": {"a": "Adrian Houser", "b": "Mitch Wilkinson"}},
                          "away": {"name_by_source": {"a": "Hayden Wesneski"}}},
             "prices": {"basis": "best_odds", "ml_away": -110, "ml_home": +100}}
    probe_cfg = {"starter_registry": ["Freddy Peralta"]}
    before, before_cfg = json.dumps(probe, sort_keys=True), json.dumps(probe_cfg, sort_keys=True)
    first = evaluate_gates(probe, probe_cfg)
    if json.dumps(probe, sort_keys=True) != before:
        fails.append("evaluate_gates mutated the row it was given")
    if json.dumps(probe_cfg, sort_keys=True) != before_cfg:
        fails.append("evaluate_gates mutated the config it was given")
    if evaluate_gates(probe, probe_cfg) != first:
        fails.append("evaluate_gates is not deterministic across repeated calls")
    # config is optional and defaults to the FROZEN values (no registry -> membership unchecked)
    if evaluate_gates(_clean_mlb_row())["statuses"] != ["STARTER_NOT_IN_REGISTRY"]:
        fails.append("the frozen defaults did not apply when config was omitted")
    if json.dumps(FROZEN_DEFAULTS, sort_keys=True, default=list) != _frozen_at_entry:
        fails.append("FROZEN_DEFAULTS was mutated by a call — a frozen default that a caller's "
                     "config can edit is not frozen, and would leak into every later row")

    # ---- structural: no status may be produced that the frozen set does not know -------------
    saved = GATES
    try:
        globals()["GATES"] = tuple(saved) + (lambda row, cfg: [("MADE_UP_STATUS", "x")],)
        try:
            evaluate_gates(_clean_mlb_row(), _CLEAN_CFG)
            fails.append("a status outside the frozen set was silently dropped")
        except ValueError:
            pass
    finally:
        globals()["GATES"] = saved

    # ---- every status carries a bettor-facing translation ------------------------------------
    for s in GATE_ORDER:
        if not PLAIN_ENGLISH.get(s):
            fails.append(f"{s} has no plain-English translation for the decision surface")

    # ---- no reason may leak an internal token onto the bettor surface -------------------------
    forbidden = ["PRICE_SENSITIVE", "COMPRESSION_CONFLICT", "AUDIT_REQUIRED", "NO_VALUE",
                 "PRICE_DATA_BLOCKED", "p_home", "hwp", "home_wp", "dq_flags", "cohort",
                 "home win"] + list(GATE_ORDER)
    try:  # prefer the authoritative list; a sibling import must never be able to fail this file
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import decision_card as _dc
        forbidden = list(set(forbidden) | set(_dc.FORBIDDEN_TOKENS))
        if not any(p in "OUT_OF_DOMAIN_NEUTRAL_SITE" for p in _dc.PERMANENT_BLOCKS):
            fails.append("the neutral-site token no longer matches decision_card.PERMANENT_BLOCKS, "
                         "so it would stop forcing a permanent block")
    except Exception:
        pass
    # Swept across rows that between them exercise every reason branch in the module, not just the
    # convenient ones: a token can only leak from a branch somebody actually rendered.
    leak_rows = [(multi, _CLEAN_CFG), (sub, _CLEAN_CFG), (_clean_mlb_row(), {}),
                 (noage, _CLEAN_CFG), (nodate, _CLEAN_CFG),
                 (_with(_clean_wnba_row(), feature_state_as_of="2026-08-25"), _CLEAN_CFG),
                 (stale, _CLEAN_CFG), (noprices, _CLEAN_CFG), (nopersonnel, _CLEAN_CFG),
                 (rod, _CLEAN_CFG), (wes, _CLEAN_CFG),
                 (liar, _CLEAN_CFG), (mkt, _CLEAN_CFG),
                 (_with(_clean_mlb_row(), personnel={"injury_report": "UNAVAILABLE",
                                                     "lineup_state": "NONE_AVAILABLE"}), _CLEAN_CFG),
                 (_with(_clean_wnba_row(), venue={"alternate_venue": True, "venue_name": "x"}), _CLEAN_CFG),
                 (_with(_clean_mlb_row(), prices={"books": {"dk": {"away": -118},
                                                            "fd": {"home": +102}}}), _CLEAN_CFG),
                 (_with(_clean_mlb_row(), prices={"book_away": "dk", "book_home": "fd",
                                                  "ml_away": -118, "ml_home": +102}), _CLEAN_CFG),
                 (_with(_clean_mlb_row(), prices={"ml_away": -118, "ml_home": +102}), _CLEAN_CFG),
                 (_with(_clean_mlb_row(), prices={"book": "b", "basis": "best_odds",
                                                  "ml_away": -110, "ml_home": +105}), _CLEAN_CFG)]
    branches = set()
    for row, cfg in leak_rows:
        res = evaluate_gates(row, cfg)
        branches.update(res["statuses"])
        for text in res["reasons"]:
            for tok in forbidden:
                if tok in text:
                    fails.append(f"a reason leaks the internal token '{tok}': {text[:70]}")
    if branches != set(GATE_ORDER):
        fails.append(f"the leak sweep never rendered a reason for {sorted(set(GATE_ORDER) - branches)}")

    if fails:
        print("freshness_gates selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("freshness_gates selftest: PASS (all six gates fire on their own fixtures and none fires "
          "on a clean row; the 21-day limit is exact; unknown ages, unchecked registries and "
          "unattributed prices block rather than pass; a diacritic is not a starter conflict while "
          "surname-only agreement is; six simultaneous gates all report in frozen order; and the "
          "CORRECT PDX@TOR neutral-site row is still blocked, outcome fields changing nothing)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="mechanical freshness and domain gates (card action layer)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--row-json", help="path to a JSON row (or a {row, config} object) to evaluate")
    ap.add_argument("--shape", action="store_true", help="print the expected row shape")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    if a.shape:
        print(_ROW_SHAPE)
        raise SystemExit(0)
    if a.row_json:
        doc = json.load(open(a.row_json))
        row, config = (doc.get("row", doc), doc.get("config"))
        res = evaluate_gates(row, config)
        print(f'{row.get("game", "?")}: {"BLOCKED FOR CARD ACTION" if res["blocked"] else "no gate fired"}')
        for s, r in zip(res["statuses"], res["reasons"]):
            print(f"  {s}\n    {PLAIN_ENGLISH[s]}\n    {r}")
        raise SystemExit(0)
    ap.print_help()
