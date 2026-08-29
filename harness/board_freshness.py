"""Glue between the board builders (build_board_0825/0828) and the frozen freshness contract.

This module is the ONLY place the builders convert starter-resolution outcomes into the owner's
status vocabulary. It replaces the defective `owner_class("RESOLVED") -> "PROBABLE"` mapping that
minted full-information PROBABLEs with no age or existence check (the 2026-08-28 HOU@NYM defect:
Hunter Brown's newest retained capture was 2026-07-19, forty days stale, and Christian Scott was
not in the starter store at all; both read as PROBABLE at dose 1.0).

Every starter slot now flows through freshness_contract.resolve_input: FRESH -> ACQUIRING ->
DEGRADED, every rung bettable, degraded inputs widening the dose rather than removing a game.

R3 (frozen stays frozen): nothing here rewrites a frozen board. Boards already frozen keep their
published rows byte-for-byte; this module changes builder behaviour going forward only.
R1 (never invent a number): every dose comes from the contract's DOSE table; this module contains
no arithmetic of its own beyond the cohort product the contract defines.
"""
from __future__ import annotations

MODULE_ID = "board_freshness"

import datetime as dt
import hashlib
import os

import freshness_contract as FC

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: candidate roots under which a "pitcher_logs/<pid>.txt" style source string may resolve
_SOURCE_ROOTS = ("", "data/backfill/mlb/2026")


def _source_sha256(source):
    """sha256 of the underlying log file bytes if the source string names a readable file."""
    if not source:
        return None
    path = str(source).split(" via ")[0].strip()
    for root in _SOURCE_ROOTS:
        cand = os.path.join(BASE, root, path) if root else os.path.join(BASE, path)
        if os.path.isfile(cand):
            return hashlib.sha256(open(cand, "rb").read()).hexdigest()
    return None


def stamp_from_features(name, feats, slate_date, source, grade=FC.CONFIRMED):
    """feats = the OrderedDict returned by sp_asof_strict (has last_start_date).

    Returns a freshness_contract.Stamp:
      - observed_at = feats['last_start_date'] (date str, may be None)
      - effective_at = feats['last_start_date']
      - source = source string (e.g. 'pitcher_logs/<pid>.txt via sp_asof_strict')
      - source_sha256 = sha256 of the underlying log file bytes if available, else None
      - grade = CONFIRMED (canonical retained logs) — callers building from search
        snippets must pass grade=IDENTIFIED_UNCONFIRMED instead

    Raises nothing; a None last_start_date yields Stamp with observed_at=None which
    resolve_input treats as stale/unknowable — correct.
    """
    last = feats.get("last_start_date") if feats else None
    return FC.Stamp(observed_at=last, effective_at=last, source=source,
                    source_sha256=_source_sha256(source), grade=grade, subject=name)


# ---------------------------------------------------------------- sport/kind generalization
#
# The wiring below is the sport-agnostic groundwork: resolve_slot/stamp_from_observation take an
# explicit (sport, kind) so WNBA/CFB/NFL builders plug into the same contract as MLB. The frozen
# freshness_contract already carries per-(sport, kind) MAX_AGE_DAYS; this module just routes.

#: the (sport, kind) pairs a board builder may resolve through this module. Anything else is a
#: bug in the caller and must raise, never silently default (R1).
SLOT_KINDS = {
    "mlb": ("starter", "bullpen", "team_form"),
    "wnba": ("starter", "team_form"),
    "nfl": ("starter", "team_form"),
    "cfb": ("starter", "team_form"),
}

#: What a per-sport board builder must supply to wire a slot through resolve_slot. This is the
#: template the WNBA/CFB/NFL wiring PRs follow; it documents the contract, it is not executable.
#:
#: DATE-TIMEZONE RULE (holds for every sport): every observed_at a builder passes MUST be
#: timezone-qualified — either a datetime carrying tzinfo (UTC preferred) or an ISO-8601 string
#: with an explicit offset (e.g. '2026-09-03T18:00:00Z' or '+00:00'). The frozen contract's
#: parser accepts naive dates/datetimes and treats them as UTC, so they will not raise — but
#: that is a tolerance, not a license: a naive local date silently shifts the observation time,
#: and freshness decisions are only as honest as the timestamps they gate on. Be explicit.
BUILDER_INTEGRATION_CONTRACT = {
    "_timezone_rule": (
        "Every observed_at MUST be timezone-qualified (UTC tzinfo datetime, or ISO-8601 with an "
        "offset). The contract parser accepts naive values as UTC by design; builders must not "
        "rely on that tolerance — an unqualified local timestamp silently lies about age."),
    "_grade_rule": (
        "CONFIRMED only for canonical retained captures of THIS game/slate; "
        "IDENTIFIED_UNCONFIRMED for anything identified through search/relay snippets "
        "(snippets identify, never bind); POST_HOC_NOT_PREGAME for post-hoc reconciliations; "
        "an unknown subject must reach resolve_slot as stamp None (ABSENT), never defaulted."),
    "mlb": {
        "subject": "pitcher display name (e.g. 'Hunter Brown')",
        "sport": "mlb",
        "kinds": SLOT_KINDS["mlb"],
        "observed_at_source": "sp_asof_strict features['last_start_date'] (retained log date)",
        "stamp_constructor": "stamp_from_features (retained logs) or stamp_from_observation",
    },
    "wnba": {
        "subject": "player display name as it appears in the WNBA feature store",
        "sport": "wnba",
        "kinds": SLOT_KINDS["wnba"],
        "observed_at_source": "the WNBA feature store's last-game/last-observation field "
                              "(builder-specific; must be a real capture timestamp, never now)",
        "stamp_constructor": "stamp_from_observation",
    },
    "nfl": {
        "subject": "player display name as it appears in the NFL feature store",
        "sport": "nfl",
        "kinds": SLOT_KINDS["nfl"],
        "observed_at_source": "the NFL feature store's last-game/depth-chart observation field",
        "stamp_constructor": "stamp_from_observation",
    },
    "cfb": {
        "subject": "player display name as it appears in the CFB feature store",
        "sport": "cfb",
        "kinds": SLOT_KINDS["cfb"],
        "observed_at_source": "the CFB feature store's last-game/depth-chart observation field",
        "stamp_constructor": "stamp_from_observation",
    },
}


def validate_sport_kind(sport, kind):
    """Fail loud on an unknown (sport, kind) pair — never default to a limit silently."""
    if sport not in SLOT_KINDS or kind not in SLOT_KINDS.get(sport, ()):
        raise ValueError(
            f"UNKNOWN_SPORT_KIND ({sport!r}, {kind!r}). Allowed: "
            + ", ".join(f"{s}/{k}" for s, kinds in SLOT_KINDS.items() for k in kinds))
    return sport, kind


def stamp_from_observation(subject, observed_at, source, source_sha256=None,
                           grade=FC.CONFIRMED, effective_at=None, fetched_at=None):
    """Generic Stamp constructor for non-MLB-log sources (WNBA/CFB/NFL feature stores).

    effective_at defaults to observed_at, NEVER to now (R1: ingestion time must be real or
    omitted, not fabricated). observed_at=None yields a stamp with no usable timestamp, which
    resolve_slot treats as stale/unknowable — correct; a builder with no timestamp degrades
    honestly rather than inventing one.
    """
    return FC.Stamp(observed_at=observed_at, effective_at=effective_at or observed_at,
                    fetched_at=fetched_at, source=source, source_sha256=source_sha256,
                    grade=grade, subject=subject)


def _status_str(disposition, raw_status):
    """Disposition -> the owner's starter vocabulary. Replaces owner_class entirely.

    NEVER returns bare 'PROBABLE' for anything older than MAX_AGE_DAYS: only FRESH+CONFIRMED
    earns it, and FRESH is defined by the contract's per-(sport, kind) age limit.
    """
    disp, grade = disposition.disposition, disposition.grade
    if grade == FC.POST_HOC_NOT_PREGAME:
        return "POST_HOC_NOT_PREGAME_CAP"
    if disp == FC.FRESH and grade == FC.CONFIRMED:
        return "PROBABLE"
    if disp == FC.ACQUIRING:
        return f"PROBABLE_ACQUIRED[{grade}]"
    if disp == FC.DEGRADED and grade == FC.CONFIRMED:
        return "STALE_DATA_CAP"
    if disp == FC.DEGRADED and grade == FC.ABSENT:
        return f"NAMED_NO_LOG_RETAINED_CAP[{raw_status}]"
    if disp == FC.DEGRADED and grade == FC.IDENTIFIED_UNCONFIRMED:
        return "UNCONFIRMED_STALE_CAP"
    # FRESH + IDENTIFIED_UNCONFIRMED: identified in time, but snippets never bind
    return f"PROBABLE_ACQUIRED[{grade}]"


def resolve_slot(subject, sport, kind, stamp_or_none, raw_status, acquire=None, now=None):
    """The sport/kind-parameterized generalization of resolve_starter_slot.

    One slot -> (status_str, disposition_dict).
    - stamp_or_none None (subject not in any store) -> Stamp.absent(subject, raw_status)
    - validate_sport_kind guards the pair first: unknown pairs raise, never default
    - status vocabulary is the shared sport-agnostic contract (_status_str): the exact same
      strings for every sport — PROBABLE, PROBABLE_ACQUIRED[<grade>], STALE_DATA_CAP,
      NAMED_NO_LOG_RETAINED_CAP[<raw>], UNCONFIRMED_STALE_CAP, POST_HOC_NOT_PREGAME_CAP.
      Bare PROBABLE remains FRESH+CONFIRMED only, and FRESH is defined by the frozen contract's
      per-(sport, kind) MAX_AGE_DAYS.
    """
    validate_sport_kind(sport, kind)
    if stamp_or_none is None:
        stamp = FC.Stamp.absent(subject, raw_status)
    else:
        stamp = stamp_or_none
    try:
        disp = FC.resolve_input(subject, sport, kind, stamp, now=now, acquire=acquire)
    except FC.StampError:
        # e.g. a feature-store row whose observation timestamp is None: age is unknowable, so
        # the slot degrades honestly rather than raising mid-slate or reading as fresh.
        disp = FC.Disposition(
            subject, FC.DEGRADED, stamp.grade, FC.DOSE[(FC.DEGRADED, stamp.grade)],
            "stamp carries no usable timestamp — age is unknowable, so the slot is treated as "
            "stale rather than as fresh",
            stamp=stamp, age_days=None,
            limit_days=FC.MAX_AGE_DAYS.get((sport, kind), FC.DEFAULT_MAX_AGE_DAYS))
    return _status_str(disp, raw_status), disp.to_dict(now or dt.datetime.now(FC.UTC))


def resolve_starter_slot(name, feats_or_none, raw_status, slate_date, source,
                         acquire=None, now=None, grade=FC.CONFIRMED):
    """One starter slot -> (sp_features_dict_or_None, status_str, disposition_dict).

    - feats_or_none None (NO_PID / NO_LOG / TBD) -> Stamp.absent(name, raw_status)
    - else stamp_from_features + resolve_slot(name, 'mlb', 'starter', stamp, acquire=acquire)
    - status_str vocabulary replaces owner_class (see _status_str)
    - NEVER returns bare 'PROBABLE' for anything older than MAX_AGE_DAYS.
    """
    if feats_or_none is None:
        stamp = None
        feats_out = None
    else:
        stamp = stamp_from_features(name, feats_or_none, slate_date, source, grade=grade)
        feats_out = feats_or_none
    status, disp = resolve_slot(name, "mlb", "starter", stamp, raw_status,
                                acquire=acquire, now=now)
    return feats_out, status, disp


def game_dose(dispositions):
    """cohort_dose wrapper; replaces `1.0 - 0.25*capped` / `dose=0.5 on TBD` arithmetic.

    Accepts Disposition objects or their to_dict() dicts (anything with a dose_multiplier).
    Multiplicative, floored at 0.20 by the contract — a degraded game is widened, never removed.
    """
    class _Slot:
        def __init__(self, x):
            self.dose_multiplier = (x.dose_multiplier if hasattr(x, "dose_multiplier")
                                    else x["dose_multiplier"])
    return FC.cohort_dose([_Slot(d) for d in dispositions])
