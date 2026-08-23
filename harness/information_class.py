#!/usr/bin/env python3
"""INFORMATION CLASS — an all-CAP slate is a BASELINE COHORT, not a normal card.

OWNER RULING 2026-08-23 (development program, item 1):
    "Turn all-CAP cards into an explicit baseline cohort. Do not present an all-CAP slate as a
     normal card. Use: INFORMATION_CLASS = ALL_CAP_BASELINE, ACTION_AUTHORITY = NONE, continue
     registering it for comparison, fork the actionable challenger only after verified starters
     arrive."

WHY THIS IS NOT COSMETIC. The class is a property of the INPUTS, and until now nothing in the repo
measured it. Scanning every committed card at slot level found:

  * FIVE cards with ZERO resolved starter slots — 2026-08-17, 08-18, 08-19, 08-21, 08-22 — each
    written and read as an ordinary card.
  * 42 slots across the history that PRINTED A PITCHER'S NAME while feeding the model league-average
    CAP stats. 2026-08-19 is the clearest: the card shows "Jackson Jobe" and "AJ Smith-Shawver" and
    is nonetheless 0/30 resolved. A reader seeing names reasonably concludes the card knows who is
    pitching. It does not. THE NAME IS COSMETIC; THE STATS ARE THE INPUT.
  * The cohort label "v1" does NOT mean "baseline". On 08-18, 08-19 and 08-21 the v1 cohort was
    built from an all-CAP card; on 08-20 it was built from a card with 17 of 18 slots RESOLVED.
    Pooling "v1" across those days pools two different information classes under one name. This is
    the concrete instance of the owner's own caution that a pooled score "should not become
    canonical until model identity, eligibility and cohort definitions are verified identical".

CLASSIFICATION IS COMPUTED FROM THE STATS, NEVER FROM A FLAG OR A NAME. Cards carry a row-level
`capped` boolean, but it is per-ROW over TWO slots and cannot distinguish all-CAP from partial; a
card asserting `capped: false` while carrying CAP stats is classified all-CAP anyway. A card cannot
talk its way out of its own class.

THIS MODULE CAN ONLY REMOVE AUTHORITY, NEVER GRANT IT. For every class other than ALL_CAP_BASELINE
it returns GATE_GOVERNED — deferring to the promotion gate (0/100 NO_PROMOTE), the paper-only
ruling and the trust ladder. There is no code path here that returns an affirmative permission.

REGISTRATION IS NOT ACTION. A baseline card stays registration-eligible: the owner asked for it to
keep being registered for comparison. "Cannot be acted on" must never collapse into "not recorded".

R3/R6 COMPLIANCE. Historical cards are NOT retro-stamped — that would rewrite frozen artifacts and
break their registered hashes. The classification lives in a derived, append-only ledger, and the
gate re-derives each class from the card and fails on drift.
"""
from __future__ import annotations

import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, "data/audit/information_class_ledger.json")
CARD_GLOB = os.path.join(BASE, "cards/*.json")

# The league-average fallback a slot receives when no starter is resolved. gs is ZERO, which makes
# every `x or default` idiom silently misclassify CAP as absent — the first draft of this scan did
# exactly that and reported 0 CAP slots across 35 cards. Zero is a value, not a missing marker.
CAP_SIGNATURE = {"era": 4.20, "gs": 0, "k": 22.0, "bb": 8.5}
CAP_TOL = 1e-9
LOW_SAMPLE_GS = 2

RESOLVED = "RESOLVED"
CAP_TBD = "CAP_TBD"
CAP_NAMED_REGISTRY_MISS = "CAP_NAMED_REGISTRY_MISS"
LOW_SAMPLE = "LOW_SAMPLE"
MALFORMED = "MALFORMED"
CAP_STATES = (CAP_TBD, CAP_NAMED_REGISTRY_MISS)

ALL_CAP_BASELINE = "ALL_CAP_BASELINE"
PARTIAL_STARTER_INFORMATION = "PARTIAL_STARTER_INFORMATION"
VERIFIED_STARTER_COHORT = "VERIFIED_STARTER_COHORT"
NOT_CLASSIFIABLE = "NOT_CLASSIFIABLE"
# Two things under cards/ that are NOT unclassifiable slates and must not be reported as if they
# were broken. Both still carry ACTION_AUTHORITY = NONE, because neither can evidence starter
# information — but the ledger says WHY, so "0 resolved" never reads as "the card failed".
NOT_A_CARD = "NOT_A_CARD"                                # prop sheets, EV screens: no slate rows
LEGACY_SCHEMA_NO_SLOT_STATS = "LEGACY_SCHEMA_NO_SLOT_STATS"   # pre-2026-07-22: no per-slot stats

# The ONLY affirmative-sounding value in this module is GATE_GOVERNED, and it grants nothing: it
# names the gate that decides. NONE is terminal.
NONE = "NONE"
GATE_GOVERNED = "GATE_GOVERNED"

ACTION_AUTHORITY_BY_CLASS = {
    ALL_CAP_BASELINE: NONE,
    NOT_CLASSIFIABLE: NONE,
    NOT_A_CARD: NONE,
    LEGACY_SCHEMA_NO_SLOT_STATS: NONE,
    PARTIAL_STARTER_INFORMATION: GATE_GOVERNED,
    VERIFIED_STARTER_COHORT: GATE_GOVERNED,
}

# Fields whose PRESENCE WITH A VALUE constitutes presenting a baseline card as actionable. A null
# schema slot is not a violation — carrying the column is how the card shape stays uniform across
# classes. Populating it is the violation.
ACTION_FIELDS = ("gap_home", "total_lean", "edge", "edge_pp", "ev", "ev_units", "recommendation",
                 "play", "bet", "pick", "stake", "units", "lean", "action")
BASELINE_BANNER = "ALL_CAP_BASELINE — ACTION_AUTHORITY = NONE"


def _num(x):
    """Strict numeric read. None/'' /non-numeric -> None. NEVER coalesces 0 to a default."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, str) and not x.strip():
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def is_cap_slot(stats):
    """True iff every CAP field is present and equals the league-average signature."""
    if not isinstance(stats, dict):
        return False
    for k, v in CAP_SIGNATURE.items():
        x = _num(stats.get(k))
        if x is None or abs(x - v) > CAP_TOL:
            return False
    return True


def slot_state(name, stats):
    """Resolution state of ONE starter slot. The name never overrides the stats."""
    if not isinstance(stats, dict):
        return MALFORMED
    if is_cap_slot(stats):
        nm = (name or "").strip()
        # A slot showing a real name while carrying CAP stats is a REGISTRY MISS, not information.
        # It is the most misleading state on the card and is named separately so it can be counted.
        return CAP_TBD if (not nm or nm.upper() in ("TBD", "NONE", "-", "?")) else CAP_NAMED_REGISTRY_MISS
    gs = _num(stats.get("gs"))
    era = _num(stats.get("era"))
    if gs is None or era is None:
        return MALFORMED
    if gs < LOW_SAMPLE_GS:
        return LOW_SAMPLE
    return RESOLVED


SLOT_STAT_KEYS = ("asp_stats", "hsp_stats")


def has_rows_list(card):
    """A slate card carries a LIST of rows. A prop sheet or EV screen does not."""
    if isinstance(card, list):
        return True
    return isinstance(card, dict) and isinstance(card.get("rows"), list)


def has_slot_stats(rows):
    """Cards before 2026-07-22 carry no per-slot starter stats at all — only a row-level `capped`
    boolean. That boolean is a CLAIM, not an input, and is never read (see the module docstring),
    so those cards are unclassifiable BY SCHEMA rather than malformed."""
    return any(k in r for r in rows for k in SLOT_STAT_KEYS)


def card_rows(card):
    if isinstance(card, dict):
        rows = card.get("rows")
    elif isinstance(card, list):
        rows = card
    else:
        rows = None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def slot_states(card):
    """[(game, side, state)] over both starter slots of every row."""
    out = []
    for r in card_rows(card):
        g = f"{r.get('away')}@{r.get('home')}"
        for side, nk, sk in (("away", "asp", "asp_stats"), ("home", "hsp", "hsp_stats")):
            out.append((g, side, slot_state(r.get(nk), r.get(sk))))
    return out


def classify(card):
    """Compute the information class of a card FROM ITS STATS. Returns a full record."""
    if not has_rows_list(card):
        return {"information_class": NOT_A_CARD,
                "action_authority": ACTION_AUTHORITY_BY_CLASS[NOT_A_CARD],
                "registration_eligible": True, "slots_total": 0, "slots_resolved": 0,
                "slots_cap": 0, "counts": {}, "named_but_cap": [],
                "reason": "no slate rows — this file is not a card"}
    rows = card_rows(card)
    if rows and not has_slot_stats(rows):
        return {"information_class": LEGACY_SCHEMA_NO_SLOT_STATS,
                "action_authority": ACTION_AUTHORITY_BY_CLASS[LEGACY_SCHEMA_NO_SLOT_STATS],
                "registration_eligible": True, "slots_total": 0, "slots_resolved": 0,
                "slots_cap": 0, "counts": {}, "named_but_cap": [],
                "reason": "pre-2026-07-22 schema: no per-slot starter stats were recorded, so the "
                          "information class of this card cannot be recovered from the artifact"}
    states = slot_states(card)
    n = len(states)
    counts = {s: 0 for s in (RESOLVED, CAP_TBD, CAP_NAMED_REGISTRY_MISS, LOW_SAMPLE, MALFORMED)}
    for _, _, s in states:
        counts[s] = counts.get(s, 0) + 1
    n_cap = counts[CAP_TBD] + counts[CAP_NAMED_REGISTRY_MISS]
    n_resolved = counts[RESOLVED]
    if n == 0:
        cls = NOT_CLASSIFIABLE          # fail closed: no slots is not "fully verified"
    elif counts[MALFORMED]:
        cls = NOT_CLASSIFIABLE          # fail closed: unreadable inputs are not information
    elif n_cap == n:
        cls = ALL_CAP_BASELINE
    elif n_resolved == n:
        cls = VERIFIED_STARTER_COHORT
    else:
        cls = PARTIAL_STARTER_INFORMATION
    return {
        "information_class": cls,
        "action_authority": ACTION_AUTHORITY_BY_CLASS[cls],
        "registration_eligible": True,   # every class is recorded; see REGISTRATION IS NOT ACTION
        "slots_total": n,
        "slots_resolved": n_resolved,
        "slots_cap": n_cap,
        "counts": counts,
        "named_but_cap": [f"{g}:{side}" for g, side, s in states if s == CAP_NAMED_REGISTRY_MISS],
    }


def presentation_contract(cls):
    """What a RENDERING of a card in this class must and must not do."""
    if cls in (ALL_CAP_BASELINE, NOT_CLASSIFIABLE):
        return {"banner_required": BASELINE_BANNER if cls == ALL_CAP_BASELINE else
                                   "NOT_CLASSIFIABLE — ACTION_AUTHORITY = NONE",
                "populated_action_fields_forbidden": True}
    return {"banner_required": None, "populated_action_fields_forbidden": False}


def render_guard(rendered, cls):
    """(ok, violations) for a rendered card. `rendered` may be the card dict or display text."""
    c = presentation_contract(cls)
    v = []
    if c["banner_required"]:
        # ensure_ascii=False matters: the banner carries an em-dash, and the default
        # json.dumps escapes it to \u2014 so the banner is never found in a dict render.
        text = rendered if isinstance(rendered, str) else json.dumps(rendered, ensure_ascii=False)
        if c["banner_required"] not in text:
            v.append(f"class {cls} requires the banner {c['banner_required']!r} and it is absent")
    if c["populated_action_fields_forbidden"] and not isinstance(rendered, str):
        for r in card_rows(rendered):
            for fld in ACTION_FIELDS:
                if fld in r and r[fld] is not None:
                    v.append(f"{r.get('away')}@{r.get('home')}: action field {fld}={r[fld]!r} is "
                             f"populated on a class-{cls} card")
    return (not v), v


def fork_authorization(baseline, challenger_model_id, challenger_path,
                       verified_starter_slots, source_attributable):
    """May an ACTIONABLE challenger be forked off a baseline registration? (ok, reason).

    The owner's condition is 'only after verified starters arrive'. Three ways this goes wrong and
    all three are refused here: forking on zero new information, forking by MUTATING the baseline
    (R3 — the registered baseline is frozen the moment it is registered), and forking on starter
    names that came from unattributable prose (R1 — a name in a search snippet is not a source).
    """
    if not isinstance(baseline, dict):
        return False, "no baseline registration record supplied"
    if baseline.get("information_class") != ALL_CAP_BASELINE:
        return False, (f"fork rule applies to an {ALL_CAP_BASELINE} registration; this one is "
                       f"{baseline.get('information_class')!r}")
    if not verified_starter_slots:
        return False, ("no verified starter slot has arrived — a fork with no new information is a "
                       "relabelling of the baseline, not a challenger")
    if not source_attributable:
        return False, ("starter identities are not attributable to a source (R1) — names from "
                       "prose or a search snippet cannot authorise a fork")
    if challenger_model_id == baseline.get("model_id"):
        return False, ("the challenger reuses the baseline model_id; a fork must be a NEW identity "
                       "(R3: the registered baseline is frozen)")
    if challenger_path == baseline.get("path"):
        return False, ("the challenger would overwrite the baseline artifact; a fork must be a NEW "
                       "artifact (R6: append-only)")
    return True, ("fork authorised: baseline stays registered and graded, challenger registers "
                  "separately as its own cohort")


def scan(paths=None):
    """Classify every card. Returns {path: record}."""
    out = {}
    for p in sorted(paths if paths is not None else glob.glob(CARD_GLOB)):
        try:
            card = json.load(open(p))
        except (OSError, ValueError) as e:
            out[os.path.relpath(p, BASE)] = {"information_class": NOT_CLASSIFIABLE,
                                             "action_authority": NONE,
                                             "registration_eligible": True,
                                             "error": f"{type(e).__name__}: {e}"}
            continue
        out[os.path.relpath(p, BASE)] = classify(card)
    return out


def load_ledger(path=None):
    p = path or LEDGER
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p)).get("entries", {})
    except (OSError, ValueError):
        return {}


def gate(ledger_path=None, paths=None):
    """(ok, failures). Fails on: an unclassified card, and any DRIFT between the recorded class and
    the class recomputed from the card today."""
    f = []
    recorded = load_ledger(ledger_path)
    live = scan(paths)
    for rel, rec in live.items():
        if rel not in recorded:
            f.append(f"{rel}: no information-class ledger entry")
            continue
        was, now = recorded[rel].get("information_class"), rec["information_class"]
        if was != now:
            f.append(f"{rel}: recorded class {was} but recomputes as {now} — the card's inputs "
                     f"changed under a registered classification")
        auth = recorded[rel].get("action_authority")
        if auth != ACTION_AUTHORITY_BY_CLASS.get(now):
            f.append(f"{rel}: class {now} must carry action_authority "
                     f"{ACTION_AUTHORITY_BY_CLASS.get(now)}, ledger says {auth}")
    for rel in recorded:
        if rel not in live:
            f.append(f"{rel}: classified in the ledger but the card is gone (R6: append-only)")
    return (not f), f


def selftest():
    f = []
    CAP = dict(CAP_SIGNATURE, ek=None)
    REAL = {"era": 3.11, "gs": 20, "k": 16.2, "bb": 5.9, "ek": 3.92}
    THIN = {"era": 2.00, "gs": 1, "k": 18.0, "bb": 4.0, "ek": 3.00}

    def row(a, h, an, ast, hn, hst, **kw):
        return dict({"away": a, "home": h, "asp": an, "asp_stats": ast,
                     "hsp": hn, "hsp_stats": hst}, **kw)

    # 1. every slot CAP -> ALL_CAP_BASELINE
    allcap = {"rows": [row("TOR", "NYY", "TBD", CAP, "TBD", CAP),
                       row("ATL", "MIL", "TBD", CAP, "TBD", CAP)]}
    r = classify(allcap)
    if r["information_class"] != ALL_CAP_BASELINE:
        f.append(f"an all-CAP card classified as {r['information_class']}")
    # 2. and it carries NO action authority
    if r["action_authority"] != NONE:
        f.append(f"ALL_CAP_BASELINE carries action_authority {r['action_authority']}")
    # 3. THE REAL 2026-08-19 CASE: a printed NAME with CAP stats is not a resolved slot
    named = {"rows": [row("DET", "PIT", "Jackson Jobe", CAP, "TBD", CAP),
                      row("ATL", "MIN", "AJ Smith-Shawver", CAP, "TBD", CAP)]}
    r = classify(named)
    if r["information_class"] != ALL_CAP_BASELINE:
        f.append(f"the real 8/19 card (names printed, stats all CAP) classified as "
                 f"{r['information_class']} — a name is being read as information")
    if len(r["named_but_cap"]) != 2:
        f.append(f"named-but-CAP slots not counted: {r['named_but_cap']}")
    # 4. fully resolved -> VERIFIED_STARTER_COHORT, and authority DEFERS, never grants
    full = {"rows": [row("STL", "CIN", "McGreevy", REAL, "Singer", REAL)]}
    r = classify(full)
    if r["information_class"] != VERIFIED_STARTER_COHORT:
        f.append(f"a fully resolved card classified as {r['information_class']}")
    if r["action_authority"] != GATE_GOVERNED:
        f.append(f"a resolved card returned {r['action_authority']} — this module must defer, and "
                 f"must never return an affirmative permission")
    for cls, auth in ACTION_AUTHORITY_BY_CLASS.items():
        if auth not in (NONE, GATE_GOVERNED):
            f.append(f"class {cls} maps to {auth}, which is neither NONE nor a deferral")
    # 5. mixed -> PARTIAL
    mixed = {"rows": [row("A", "B", "McGreevy", REAL, "TBD", CAP)]}
    if classify(mixed)["information_class"] != PARTIAL_STARTER_INFORMATION:
        f.append("a half-resolved card did not classify as PARTIAL_STARTER_INFORMATION")
    # 6. BOUNDARY: ONE resolved slot in an otherwise all-CAP card is NOT all-CAP
    almost = {"rows": [row("A", "B", "McGreevy", REAL, "TBD", CAP)] +
                      [row("C", "D", "TBD", CAP, "TBD", CAP) for _ in range(14)]}
    r = classify(almost)
    if r["information_class"] == ALL_CAP_BASELINE:
        f.append("a card with 1 of 30 slots resolved was rounded down to ALL_CAP_BASELINE")
    if r["slots_resolved"] != 1 or r["slots_cap"] != 29:
        f.append(f"slot counts wrong: {r['slots_resolved']} resolved / {r['slots_cap']} cap")
    # 7. REGISTRATION IS NOT ACTION
    if not classify(allcap)["registration_eligible"]:
        f.append("ALL_CAP_BASELINE was made registration-INELIGIBLE; the owner requires it to keep "
                 "being registered for comparison")
    # 8. a card cannot talk its way out of its class with a flag
    liar = {"rows": [row("A", "B", "TBD", CAP, "TBD", CAP, capped=False),
                     row("C", "D", "TBD", CAP, "TBD", CAP, capped=False)]}
    if classify(liar)["information_class"] != ALL_CAP_BASELINE:
        f.append("a card asserting capped=false escaped ALL_CAP_BASELINE — the FLAG is being read "
                 "instead of the stats")
    # 9. presentation: a populated action field on a baseline card is a violation
    ok, v = render_guard({"rows": [row("A", "B", "TBD", CAP, "TBD", CAP, gap_home=0.041)],
                          "banner": BASELINE_BANNER}, ALL_CAP_BASELINE)
    if ok:
        f.append("a baseline card presenting a populated gap_home passed the render guard")
    # 10. ...but a NULL schema slot is not
    ok, v = render_guard({"rows": [row("A", "B", "TBD", CAP, "TBD", CAP, gap_home=None,
                                       total_lean=None)],
                          "banner": BASELINE_BANNER}, ALL_CAP_BASELINE)
    if not ok:
        f.append(f"a null action field was treated as a violation: {v}")
    # 11. missing banner is a violation
    ok, v = render_guard({"rows": [row("A", "B", "TBD", CAP, "TBD", CAP)]}, ALL_CAP_BASELINE)
    if ok:
        f.append("a baseline card with no banner passed the render guard")
    # 12. a VERIFIED card needs no banner and may carry populated action fields
    ok, v = render_guard({"rows": [row("A", "B", "M", REAL, "S", REAL, gap_home=0.04)]},
                         VERIFIED_STARTER_COHORT)
    if not ok:
        f.append(f"the render guard fired on a verified-cohort card: {v}")
    # 13-16. FORK RULE
    base = {"information_class": ALL_CAP_BASELINE, "model_id": "ml.v13_1.card.s722n30000",
            "path": "cards/2026-08-22_card.json"}
    ok, why = fork_authorization(base, "ml.v13_1.card.s722n30000.v2", "cards/2026-08-22_card_v2.json",
                                 verified_starter_slots=["TOR@NYY:away"], source_attributable=True)
    if not ok:
        f.append(f"a legitimate fork was refused: {why}")
    ok, why = fork_authorization(base, "ml.v13_1.card.s722n30000.v2", "cards/2026-08-22_card_v2.json",
                                 verified_starter_slots=[], source_attributable=True)
    if ok:
        f.append("a fork was authorised with ZERO verified starter slots — that is a relabelling")
    ok, why = fork_authorization(base, "ml.v13_1.card.s722n30000", "cards/2026-08-22_card_v2.json",
                                 verified_starter_slots=["TOR@NYY:away"], source_attributable=True)
    if ok:
        f.append("a fork REUSING the baseline model_id was authorised (R3 violation)")
    ok, why = fork_authorization(base, "ml.new", "cards/2026-08-22_card.json",
                                 verified_starter_slots=["TOR@NYY:away"], source_attributable=True)
    if ok:
        f.append("a fork OVERWRITING the baseline artifact was authorised (R6 violation)")
    ok, why = fork_authorization(base, "ml.new", "cards/2026-08-22_card_v2.json",
                                 verified_starter_slots=["TOR@NYY:away"], source_attributable=False)
    if ok:
        f.append("a fork was authorised on UNATTRIBUTABLE starter names (R1 violation)")
    # the baseline is never retracted by a fork
    ok, why = fork_authorization(base, "ml.new", "cards/2026-08-22_card_v2.json",
                                 verified_starter_slots=["TOR@NYY:away"], source_attributable=True)
    if ok and "baseline stays registered" not in why:
        f.append("fork authorisation does not state that the baseline registration survives")
    # 17. LOW_SAMPLE is informed but NOT verified
    if slot_state("Rookie", THIN) != LOW_SAMPLE:
        f.append(f"a 1-start pitcher classified as {slot_state('Rookie', THIN)}")
    thin = {"rows": [row("A", "B", "Rookie", THIN, "Singer", REAL)]}
    if classify(thin)["information_class"] != PARTIAL_STARTER_INFORMATION:
        f.append("a LOW_SAMPLE slot was counted as verified")
    # 18. FAIL CLOSED: malformed and empty are never VERIFIED
    bad = {"rows": [row("A", "B", "X", {"era": "n/a"}, "Y", REAL)]}
    if classify(bad)["information_class"] != NOT_CLASSIFIABLE:
        f.append(f"a malformed card classified as {classify(bad)['information_class']}")
    if classify(bad)["action_authority"] != NONE:
        f.append("a malformed card retained action authority")
    if classify({"rows": []})["information_class"] != NOT_CLASSIFIABLE:
        f.append("an EMPTY card classified as something other than NOT_CLASSIFIABLE")
    if classify({"rows": []})["action_authority"] != NONE:
        f.append("an empty card retained action authority")
    # 18b. NOT_A_CARD vs LEGACY vs MALFORMED are three different things and must stay distinct.
    for notcard in ({"date": "2026-07-21", "market": "k", "plays": []},
                    {"rule": "ev", "picks": []}, [], "nope", None):
        rr = classify(notcard) if notcard != [] else classify({"date": "x"})
        if notcard is not None and not isinstance(notcard, (list,)) and \
                rr["information_class"] != NOT_A_CARD:
            f.append(f"a prop/EV file classified as {rr['information_class']}, not NOT_A_CARD")
        if rr["action_authority"] != NONE:
            f.append("a non-card retained action authority")
    legacy = {"rows": [{"game": "CHW@TOR", "hw": 0.454, "capped": False, "low": False},
                       {"game": "NYM@ATL", "hw": 0.512, "capped": False, "low": False}]}
    rr = classify(legacy)
    if rr["information_class"] != LEGACY_SCHEMA_NO_SLOT_STATS:
        f.append(f"a pre-07-22 card classified as {rr['information_class']}")
    if rr["action_authority"] != NONE:
        f.append("a legacy-schema card retained action authority")
    # and the legacy `capped: false` claim still buys it nothing
    if classify(legacy)["information_class"] == VERIFIED_STARTER_COHORT:
        f.append("a legacy card was upgraded to VERIFIED from its own capped=false flag")
    # a MODERN card with a broken slot is NOT legacy — it is unclassifiable
    if classify(bad)["information_class"] != NOT_CLASSIFIABLE:
        f.append("a modern card with a malformed slot was misrouted to the legacy disposition")
    # 19. the ZERO TRAP: gs == 0 is a VALUE. Any `or`-coalescing read breaks CAP detection, which is
    #     how the first scan of this repo reported 0 CAP slots across 35 cards.
    if not is_cap_slot(CAP_SIGNATURE):
        f.append("the CAP signature itself is not detected as CAP — a falsy-zero read of gs=0")
    if is_cap_slot(dict(CAP_SIGNATURE, gs=20)):
        f.append("a 20-start pitcher with league-average rates was called CAP")
    if is_cap_slot({"era": 4.20, "k": 22.0, "bb": 8.5}):
        f.append("a slot MISSING gs was called CAP — absence is not the CAP value")
    if is_cap_slot(dict(CAP_SIGNATURE, gs=None)):
        f.append("a slot with gs=None was called CAP")
    # 20. GATE: drift between the recorded class and the live card FAILS
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        cp = os.path.join(td, "2026-01-01_card.json")
        json.dump(allcap, open(cp, "w"))
        lp = os.path.join(td, "ledger.json")
        rel = os.path.relpath(cp, BASE)
        json.dump({"entries": {rel: {"information_class": ALL_CAP_BASELINE,
                                     "action_authority": NONE}}}, open(lp, "w"))
        ok, ff = gate(ledger_path=lp, paths=[cp])
        if not ok:
            f.append(f"gate failed on a correctly classified card: {ff}")
        json.dump(full, open(cp, "w"))          # the card's inputs changed under its classification
        ok, ff = gate(ledger_path=lp, paths=[cp])
        if ok:
            f.append("gate PASSED after a card silently changed information class")
        # ISOLATE the drift rule: NOT_CLASSIFIABLE and ALL_CAP_BASELINE BOTH map to NONE, so the
        # authority check cannot fire here and only the class-drift comparison can catch it.
        json.dump(allcap, open(cp, "w"))
        json.dump({"entries": {rel: {"information_class": NOT_CLASSIFIABLE,
                                     "action_authority": NONE}}}, open(lp, "w"))
        ok, ff = gate(ledger_path=lp, paths=[cp])
        if ok:
            f.append("gate PASSED on class drift NOT_CLASSIFIABLE -> ALL_CAP_BASELINE, where the "
                     "authority check cannot mask it")
        json.dump(allcap, open(cp, "w"))
        json.dump({"entries": {}}, open(lp, "w"))
        ok, ff = gate(ledger_path=lp, paths=[cp])
        if ok:
            f.append("gate PASSED on a card with no ledger entry at all")
        json.dump({"entries": {rel: {"information_class": ALL_CAP_BASELINE,
                                     "action_authority": GATE_GOVERNED}}}, open(lp, "w"))
        ok, ff = gate(ledger_path=lp, paths=[cp])
        if ok:
            f.append("gate PASSED on a baseline ledgered with action_authority GATE_GOVERNED")
        json.dump({"entries": {"cards/gone.json": {"information_class": ALL_CAP_BASELINE,
                                                   "action_authority": NONE},
                               rel: {"information_class": ALL_CAP_BASELINE,
                                     "action_authority": NONE}}}, open(lp, "w"))
        ok, ff = gate(ledger_path=lp, paths=[cp])
        if ok:
            f.append("gate PASSED after a classified card was deleted (R6)")

    print("information_class selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("class computed from the row `capped` flag instead of the stats",
     "    if is_cap_slot(stats):", "    if stats.get('capped') is True:"),
    ("a printed NAME counts as resolved information",
     "        return CAP_TBD if (not nm or nm.upper() in (\"TBD\", \"NONE\", \"-\", \"?\")) else CAP_NAMED_REGISTRY_MISS",
     "        return CAP_TBD if (not nm or nm.upper() in (\"TBD\", \"NONE\", \"-\", \"?\")) else RESOLVED"),
    ("falsy-zero read of gs — the real defect that reported 0 CAP slots across 35 cards",
     "        x = _num(stats.get(k))", "        x = _num(stats.get(k) or None)"),
    ("a missing CAP field is treated as matching",
     "        if x is None or abs(x - v) > CAP_TOL:", "        if x is not None and abs(x - v) > CAP_TOL:"),
    ("all-CAP threshold rounded down — a mostly-CAP card called baseline",
     "    elif n_cap == n:", "    elif n_cap >= n - 1:"),
    ("baseline granted action authority", "    ALL_CAP_BASELINE: NONE,",
     "    ALL_CAP_BASELINE: GATE_GOVERNED,"),
    ("baseline made registration-INELIGIBLE — 'cannot bet' collapsed into 'not recorded'",
     '        "registration_eligible": True,', '        "registration_eligible": cls != ALL_CAP_BASELINE,'),
    ("empty card fails OPEN as fully verified", "        cls = NOT_CLASSIFIABLE          # fail closed: no slots",
     "        cls = VERIFIED_STARTER_COHORT   # fail closed: no slots"),
    ("malformed inputs fail OPEN", "    elif counts[MALFORMED]:", "    elif False:"),
    ("LOW_SAMPLE promoted to RESOLVED", "    if gs < LOW_SAMPLE_GS:", "    if False:"),
    ("render guard ignores populated action fields",
     "                if fld in r and r[fld] is not None:", "                if False:"),
    ("render guard fires on NULL schema slots",
     "                if fld in r and r[fld] is not None:", "                if fld in r:"),
    ("banner search re-escapes the em-dash so the banner can never be found in a dict render",
     "        text = rendered if isinstance(rendered, str) else json.dumps(rendered, ensure_ascii=False)",
     "        text = rendered if isinstance(rendered, str) else json.dumps(rendered)"),
    ("banner requirement dropped", '        if c["banner_required"] not in text:', "        if False:"),
    ("fork authorised with no verified starters",
     "    if not verified_starter_slots:", "    if False:"),
    ("fork may reuse the baseline model_id (R3)",
     '    if challenger_model_id == baseline.get("model_id"):', "    if False:"),
    ("fork may overwrite the baseline artifact (R6)",
     '    if challenger_path == baseline.get("path"):', "    if False:"),
    ("fork accepts unattributable starter names (R1)",
     "    if not source_attributable:", "    if False:"),
    ("a prop sheet is treated as an unclassifiable CARD",
     "    if not has_rows_list(card):", "    if False:"),
    ("legacy detection swallows modern cards, hiding malformed slots",
     "    if rows and not has_slot_stats(rows):", "    if rows:"),
    ("legacy schema detection removed",
     "    return any(k in r for r in rows for k in SLOT_STAT_KEYS)", "    return True"),
    ("a non-card is granted authority", "    NOT_A_CARD: NONE,", "    NOT_A_CARD: GATE_GOVERNED,"),
    ("a legacy card is granted authority",
     "    LEGACY_SCHEMA_NO_SLOT_STATS: NONE,", "    LEGACY_SCHEMA_NO_SLOT_STATS: GATE_GOVERNED,"),
    ("gate ignores classification drift", "        if was != now:", "        if False:"),
    ("gate ignores unclassified cards", "            f.append(f\"{rel}: no information-class ledger entry\")",
     "            pass"),
    ("gate ignores an authority that contradicts the class",
     "        if auth != ACTION_AUTHORITY_BY_CLASS.get(now):", "        if False:"),
    ("gate ignores a deleted classified card", "        if rel not in live:", "        if False:"),
]


def mutation_suite(verbose=True):
    import subprocess as _sp, tempfile as _tf
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = [")
    j = src.index("\ndef mutation_suite", i)
    head, block, tail = src[:i], src[i:j], src[j:]
    surv, unapp = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapp.append(f"{name}: pattern not found"); continue
        mut = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mut == src:
            unapp.append(f"{name}: no-op"); continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mut); path = fh.name
        try:
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=180)
            killed = pr.returncode != 0
        except _sp.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}")
        if not killed:
            surv.append(name)
    for u in unapp:
        print(f"  UNAPPLIED  {u}")
    print(f"mutation suite: {len(MUTANTS)-len(surv)-len(unapp)}/{len(MUTANTS)} killed"
          f"{'' if not (surv or unapp) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return surv + unapp


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    if "--gate" in sys.argv:
        ok, ff = gate()
        print("information-class gate:", "PASS" if ok else f"FAIL ({len(ff)})")
        for x in ff:
            print("  " + x)
        sys.exit(0 if ok else 1)
    if "--scan" in sys.argv:
        for rel, rec in scan().items():
            print(f"{rel:34s} {rec['information_class']:28s} {rec['action_authority']:14s} "
                  f"resolved {rec.get('slots_resolved')}/{rec.get('slots_total')} "
                  f"named-but-CAP {len(rec.get('named_but_cap') or [])}")
        sys.exit(0)
    print(__doc__)
