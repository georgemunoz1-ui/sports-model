"""The shared freshness contract for forecast-critical inputs: MLB, WNBA, CFB, NFL.

WHAT THIS EXISTS TO STOP. On 2026-08-28 the MLB board carried
sp_status={'away':'RESOLVED','home':'RESOLVED'}, starter_class PROBABLE/PROBABLE,
resolved_information_dose 1.0 and starter_slots_capped 0 for HOU@NYM. Behind that: Hunter Brown's
only retained stat capture was 2026-07-19T11:23:55Z, FORTY DAYS before first pitch, and Christian
Scott was not in the starter stat store at all. Slate-wide, 21 of 30 starter slots had no retained
log; the board capped 7. Fourteen slots were credited with information that did not exist.

THE MECHANISM WAS FOUR LINES, and no field was missing:

    def owner_class(raw_status):
        if raw_status == "RESOLVED":
            return "PROBABLE"          # no age check, no existence check

`starter_class` answers "did we get a NAME?". The dose formula reads it as "do we have usable
DATA?". Those are different claims and nothing converted one into the other.

WHY PRIOR FIXES DID NOT CLOSE IT. They were built in the wrong layer. data/mlb/ml_asof/ is a
properly governed as-of store: its manifest carries source_hashes for pitchers, starters, results
and park factors, a strict time_rule, and every one of its 1,943 rows carries
source_observation_cutoff plus starter_confirmed_pregame=False and a starter_status that says in
words "NOT a pregame confirmation". The production board builders never read it. The word RESOLVED
therefore means opposite things in the two layers: carefully-qualified post-hoc in the evaluation
store, and full-information PROBABLE on the board. This module makes the qualification travel.

TERMINAL BEHAVIOUR IS FETCH, NOT BLOCK (owner, 2026-08-29). A stale input triggers ACQUISITION.
Only when acquisition fails does the input degrade — to a widened prior, never to an unbettable
game. The ladder is FRESH -> ACQUIRING -> DEGRADED, and every rung is bettable.

TWO PLACES THIS DELIBERATELY DEPARTS FROM THE DICTATED SPEC, both disclosed rather than silent:

  1. derived_age = now - max(observed_at, effective_at, fetched_at) is implemented exactly as
     specified, because it is the right thing to GATE on. But max() has a hole: a re-fetch that
     returns the SAME stale announcement resets the clock to zero, so a source that keeps serving
     a 40-day-old probable would read as fresh forever. content_age = now - observed_at is
     therefore computed beside it, and clear_requires_new_content() refuses to let a bare re-fetch
     clear a staleness flag when the observation itself did not move. Fetching is not learning.

  2. MAX_AGE for an MLB starter is 2 days, not the illustrative 7. A starting rotation turns every
     five days, so a 7-day-old "probable" spans more than a full turn and cannot distinguish "the
     same pitcher" from "a different pitcher" — the exact ambiguity that produced this defect. The
     limit is one constant per (sport, kind) below and is meant to be argued with.

WHAT ACQUISITION MAY AND MAY NOT DO HERE. Standing constraint: never route around the org egress
proxy, and use approved browsing/search/fetch tools rather than shell HTTP against sports sites.
Standing evidence rule: search snippets IDENTIFY and never BIND. So an acquisition that succeeds
through search yields IDENTIFIED_UNCONFIRMED — a real freshness upgrade and NOT a confirmation.
No adapter in this module performs network I/O; adapters are injected by the caller, and the
default registry is empty so that an unconfigured deployment DEGRADES rather than silently
pretending it acquired something.

R1 (never invent a number), R3 (frozen stays frozen) and R6 (append-only) all hold. Nothing here
rewrites a frozen board; the contract applies to builders going forward. Stake language is
deliberately absent: execution is UNAUTHORIZED and the model ledger is $0 at 0 bets, so a
degraded input widens a DOSE, it does not size a wager.
"""
from __future__ import annotations

MODULE_ID = "freshness_contract"

import datetime as dt
import hashlib
import json
import sys

UTC = dt.timezone.utc

# ---------------------------------------------------------------- grades

CONFIRMED = "CONFIRMED"                      # official/archive attestation for THIS game
IDENTIFIED_UNCONFIRMED = "IDENTIFIED_UNCONFIRMED"   # search/relay identified it; never binding
POST_HOC_NOT_PREGAME = "POST_HOC_NOT_PREGAME"       # ml_asof's own self-description
ABSENT = "ABSENT"                            # the store has never heard of it

#: grades that may carry a full information dose when also fresh
FULL_DOSE_GRADES = (CONFIRMED,)

# ---------------------------------------------------------------- dispositions

FRESH = "FRESH"
ACQUIRING = "ACQUIRING"
DEGRADED = "DEGRADED"

# ---------------------------------------------------------------- age limits
#: (sport, kind) -> max derived_age in days before acquisition is triggered.
#: These are arguable on purpose and each carries its reason.
MAX_AGE_DAYS = {
    ("mlb", "starter"): 2,    # rotations turn every ~5d; 7d cannot distinguish pitcher identity
    ("mlb", "bullpen"): 3,
    ("mlb", "team_form"): 3,
    ("wnba", "starter"): 2,
    ("wnba", "team_form"): 3,
    ("nfl", "starter"): 4,    # weekly cadence; a Wednesday depth chart still describes Sunday
    ("nfl", "team_form"): 8,
    ("cfb", "starter"): 4,
    ("cfb", "team_form"): 8,
}
DEFAULT_MAX_AGE_DAYS = 2

#: dose multipliers by disposition+grade. A degraded input is never zero: the game stays bettable.
DOSE = {
    (FRESH, CONFIRMED): 1.00,
    (FRESH, IDENTIFIED_UNCONFIRMED): 0.75,
    (FRESH, POST_HOC_NOT_PREGAME): 0.50,
    (ACQUIRING, CONFIRMED): 1.00,
    (ACQUIRING, IDENTIFIED_UNCONFIRMED): 0.75,
    (ACQUIRING, POST_HOC_NOT_PREGAME): 0.50,
    (DEGRADED, CONFIRMED): 0.50,
    (DEGRADED, IDENTIFIED_UNCONFIRMED): 0.50,
    (DEGRADED, POST_HOC_NOT_PREGAME): 0.35,
    (DEGRADED, ABSENT): 0.25,
    (ACQUIRING, ABSENT): 0.25,
    (FRESH, ABSENT): 0.25,   # unreachable by construction; present so the table is total
}

REQUIRED_STAMP_FIELDS = ("observed_at", "effective_at", "source", "grade")


class StampError(ValueError):
    """A stamp that cannot be trusted. Raised rather than defaulted — R1."""


def _parse(ts):
    if ts is None:
        return None
    if isinstance(ts, dt.datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    s = str(ts).strip()
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = dt.datetime.fromisoformat(s[:10])
        except ValueError:
            raise StampError(f"UNPARSEABLE_TIMESTAMP {ts!r}")
    return d if d.tzinfo else d.replace(tzinfo=UTC)


class Stamp:
    """Freshness provenance for ONE forecast-critical input.

    observed_at   when the event actually happened (the pitcher was announced)
    effective_at  when this system first saw it (store ingestion)
    fetched_at    when the acquisition layer last touched it
    source        where it came from, as a string a reader can act on
    source_sha256 content hash of the bytes this was read from
    grade         CONFIRMED / IDENTIFIED_UNCONFIRMED / POST_HOC_NOT_PREGAME / ABSENT
    """

    def __init__(self, observed_at=None, effective_at=None, fetched_at=None,
                 source=None, source_sha256=None, grade=None, subject=None):
        self.subject = subject
        self.observed_at = _parse(observed_at)
        self.effective_at = _parse(effective_at)
        self.fetched_at = _parse(fetched_at)
        self.source = source
        self.source_sha256 = source_sha256
        self.grade = grade

    @classmethod
    def absent(cls, subject, reason):
        s = cls(grade=ABSENT, source=f"NOT_IN_STORE: {reason}", subject=subject)
        s.absent_reason = reason
        return s

    # ---- ages ----------------------------------------------------------
    def derived_age_days(self, now):
        """now - max(observed_at, effective_at, fetched_at). The gate keys on this."""
        stamps = [t for t in (self.observed_at, self.effective_at, self.fetched_at) if t]
        if not stamps:
            return None
        return (now - max(stamps)).total_seconds() / 86400.0

    def content_age_days(self, now):
        """now - observed_at. What a re-fetch CANNOT change.

        Kept separate because derived_age uses max(), so a source that keeps re-serving the same
        stale announcement would read as fresh forever. Fetching is not learning.
        """
        base = self.observed_at or self.effective_at
        return None if base is None else (now - base).total_seconds() / 86400.0

    def validate(self):
        if self.grade == ABSENT:
            return
        missing = [f for f in REQUIRED_STAMP_FIELDS if getattr(self, f, None) in (None, "")]
        if missing:
            raise StampError(
                f"INCOMPLETE_STAMP for {self.subject!r}: missing {missing}. A forecast-critical "
                "input with no provenance must be declared ABSENT, never defaulted to fresh.")
        if self.grade not in (CONFIRMED, IDENTIFIED_UNCONFIRMED, POST_HOC_NOT_PREGAME):
            raise StampError(f"UNKNOWN_GRADE {self.grade!r} for {self.subject!r}")

    def to_dict(self, now):
        return {
            "subject": self.subject,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z") if self.observed_at else None,
            "effective_at": self.effective_at.isoformat().replace("+00:00", "Z") if self.effective_at else None,
            "fetched_at": self.fetched_at.isoformat().replace("+00:00", "Z") if self.fetched_at else None,
            "source": self.source,
            "source_sha256": self.source_sha256,
            "grade": self.grade,
            "derived_age_days": (None if self.derived_age_days(now) is None
                                 else round(self.derived_age_days(now), 4)),
            "content_age_days": (None if self.content_age_days(now) is None
                                 else round(self.content_age_days(now), 4)),
        }


def clear_requires_new_content(before: Stamp, after: Stamp):
    """Did an acquisition actually LEARN something, or merely touch the same bytes again?

    Returns (cleared, reason). A re-fetch that returns an unchanged observed_at AND an unchanged
    content hash has not refreshed anything, so it must not clear a staleness flag — even though
    it moves fetched_at and therefore moves derived_age to ~0. This is the hole in max().
    """
    if after.grade == ABSENT:
        return False, "acquisition returned nothing"
    moved_obs = before.observed_at != after.observed_at
    moved_hash = (before.source_sha256 or "") != (after.source_sha256 or "")
    if moved_obs or moved_hash:
        return True, ("observation moved" if moved_obs else "source content changed")
    return False, ("REFETCH_WITHOUT_NEW_CONTENT — observed_at and source_sha256 are both unchanged, "
                   "so this fetch touched the same stale bytes again. derived_age reset to ~0 but "
                   "nothing was learned; the staleness flag stands.")


class Disposition:
    def __init__(self, subject, disposition, grade, dose_multiplier, reason,
                 stamp=None, age_days=None, limit_days=None, acquisition=None):
        self.subject = subject
        self.disposition = disposition
        self.grade = grade
        self.dose_multiplier = dose_multiplier
        self.reason = reason
        self.stamp = stamp
        self.age_days = age_days
        self.limit_days = limit_days
        self.acquisition = acquisition

    @property
    def bettable(self):
        """Always true. The contract degrades confidence; it never removes a game."""
        return True

    def to_dict(self, now):
        return {
            "subject": self.subject,
            "disposition": self.disposition,
            "grade": self.grade,
            "dose_multiplier": self.dose_multiplier,
            "age_days": None if self.age_days is None else round(self.age_days, 4),
            "limit_days": self.limit_days,
            "reason": self.reason,
            "acquisition": self.acquisition,
            "stamp": self.stamp.to_dict(now) if self.stamp else None,
        }


def resolve_input(subject, sport, kind, stamp, now=None, acquire=None, max_age_days=None):
    """THE read-time gate. Returns a Disposition; never returns a bare value.

    stamp   a Stamp, or None. None is NOT treated as fresh — it is ABSENT.
    acquire optional callable(subject, sport, kind) -> Stamp. Injected by the caller. When it is
            None the input DEGRADES rather than silently claiming acquisition happened.
    """
    now = now or dt.datetime.now(UTC)
    limit = max_age_days if max_age_days is not None else MAX_AGE_DAYS.get(
        (sport, kind), DEFAULT_MAX_AGE_DAYS)

    if stamp is None:
        stamp = Stamp.absent(subject, "no stamp supplied")
    stamp.validate()

    if stamp.grade == ABSENT:
        got = _try_acquire(subject, sport, kind, acquire, stamp)
        if got is None:
            return Disposition(subject, DEGRADED, ABSENT, DOSE[(DEGRADED, ABSENT)],
                               "NOT IN STORE and acquisition unavailable or failed — falling back "
                               "to the league-average prior with a widened dose. The game stays "
                               "bettable; the confidence does not survive.",
                               stamp=stamp, age_days=None, limit_days=limit,
                               acquisition=_acq_note(acquire))
        stamp, acq = got
        age = stamp.derived_age_days(now)
        return Disposition(subject, ACQUIRING, stamp.grade,
                           DOSE[(ACQUIRING, stamp.grade)],
                           f"was ABSENT; acquisition supplied a {stamp.grade} stamp", stamp=stamp,
                           age_days=age, limit_days=limit, acquisition=acq)

    age = stamp.derived_age_days(now)
    c_age = stamp.content_age_days(now)
    if age is None:
        return Disposition(subject, DEGRADED, stamp.grade, DOSE[(DEGRADED, stamp.grade)],
                           "stamp carries no usable timestamp — age is unknowable, so it is "
                           "treated as stale rather than as fresh",
                           stamp=stamp, age_days=None, limit_days=limit)

    # BOTH ages must clear the limit. 2026-08-29: this used to test derived_age ALONE, and
    # derived_age is now - max(observed, effective, fetched) — the most generous reading. So a
    # stamp whose OBSERVATION was 59 days old but whose fetched_at was now read derived_age 0.00
    # and returned FRESH at dose 1.0, with no acquisition involved. content_age was computed, this
    # module's own docstring said it existed to stop exactly that, and nothing ever gated on it.
    # Computed, returned, thrown away — the same shape as sp_asof_strict's discarded
    # last_start_date, inside the module written to close it. Fetching is not learning, and a
    # gate that only reads the generous clock is not a gate.
    if age <= limit and (c_age is None or c_age <= limit):
        return Disposition(subject, FRESH, stamp.grade, DOSE[(FRESH, stamp.grade)],
                           f"derived_age {age:.2f}d and content_age "
                           f"{'n/a' if c_age is None else format(c_age, '.2f') + 'd'} both within "
                           f"the {limit}d limit for {sport}/{kind}",
                           stamp=stamp, age_days=age, limit_days=limit)
    if age <= limit and c_age is not None and c_age > limit:
        # the fetch clock is fresh, the observation is not. Name it precisely.
        return Disposition(subject, DEGRADED, stamp.grade, DOSE[(DEGRADED, stamp.grade)],
                           f"REFETCHED_BUT_STALE — derived_age {age:.2f}d is within the {limit}d "
                           f"limit only because fetched_at moved; the OBSERVATION is {c_age:.2f}d "
                           "old. A re-fetch that returns the same aged observation refreshes the "
                           "clock, not the knowledge.",
                           stamp=stamp, age_days=age, limit_days=limit)

    got = _try_acquire(subject, sport, kind, acquire, stamp)
    if got is None:
        return Disposition(subject, DEGRADED, stamp.grade, DOSE[(DEGRADED, stamp.grade)],
                           f"derived_age {age:.2f}d EXCEEDS the {limit}d limit and acquisition was "
                           "unavailable or failed — degraded to a widened dose rather than "
                           "inheriting the stale value as though it were current",
                           stamp=stamp, age_days=age, limit_days=limit,
                           acquisition=_acq_note(acquire))
    fresh, acq = got
    cleared, why = clear_requires_new_content(stamp, fresh)
    if not cleared:
        return Disposition(subject, DEGRADED, stamp.grade, DOSE[(DEGRADED, stamp.grade)],
                           f"derived_age {age:.2f}d exceeded the {limit}d limit; acquisition ran "
                           f"but did not refresh the content — {why}",
                           stamp=stamp, age_days=age, limit_days=limit, acquisition=acq)
    new_age = fresh.derived_age_days(now)
    new_c = fresh.content_age_days(now)
    # THE ACQUIRED STAMP IS RE-GATED. It used to be trusted purely because it was new: the age was
    # computed and never compared to the limit, so an acquisition that returned a genuinely
    # different but still-ancient observation minted ACQUIRING at dose 1.0. New is not the same as
    # fresh, and an adapter that can only reach old data must not be able to launder it.
    if new_age is None or new_age > limit or (new_c is not None and new_c > limit):
        shown = "unknown" if new_c is None else f"{new_c:.2f}d"
        return Disposition(subject, DEGRADED, fresh.grade, DOSE[(DEGRADED, fresh.grade)],
                           f"acquisition returned NEW content ({why}) but it is still stale: "
                           f"observation {shown} against a {limit}d limit. New is not fresh.",
                           stamp=fresh, age_days=new_age, limit_days=limit, acquisition=acq)
    return Disposition(subject, ACQUIRING, fresh.grade, DOSE[(ACQUIRING, fresh.grade)],
                       f"was {age:.2f}d stale; acquisition refreshed it to {new_age:.2f}d ({why})",
                       stamp=fresh, age_days=new_age, limit_days=limit, acquisition=acq)


def _acq_note(acquire):
    if acquire is None:
        return {"attempted": False,
                "why": ("no acquisition adapter injected. This module performs NO network I/O by "
                        "design — adapters are supplied by the caller and must route through "
                        "approved browsing/search/fetch tools, never shell HTTP against sports "
                        "sites. An unconfigured deployment degrades; it never pretends.")}
    return {"attempted": True, "succeeded": False}


def _try_acquire(subject, sport, kind, acquire, before):
    if acquire is None:
        return None
    try:
        fresh = acquire(subject, sport, kind)
    except Exception as e:                                   # an adapter fault degrades, never crashes a slate
        return None if not isinstance(e, StampError) else None
    if fresh is None or getattr(fresh, "grade", ABSENT) == ABSENT:
        return None
    fresh.validate()
    return fresh, {"attempted": True, "succeeded": True, "grade": fresh.grade}



def shrink_to_prior(p, dose, prior):
    """Consume the dose: pull a probability toward the REGISTERED PRIOR by the missing information.

        p' = prior + dose * (p - prior)

    dose 1.0 leaves p untouched; dose 0.25 keeps a quarter of the model's departure from the
    prior; dose 0 would return the prior itself. This is what "widen toward the prior" has to mean
    in code, and until 2026-08-29 nothing performed it: resolved_information_dose was written to
    the row, validated as a fraction, printed and rendered in HTML, and never multiplied into any
    probability. A DEGRADED starter and a FRESH one produced identical numbers. Computed,
    returned, thrown away — the third instance of that shape in this system.

    THE TARGET IS THE REGISTERED PRIOR, NOT 0.5, and the difference is not cosmetic. Shrinking
    toward 0.5 would strip home-field advantage out of every degraded row: with the MLB expanding
    home prior at 0.5205, a coin-flip shrink pushes every degraded home side BELOW its own
    baseline, which is a systematic bias introduced by the safety mechanism. Widening uncertainty
    must not move the central estimate. Passing prior=0.5 is legitimate only where the registered
    prior genuinely is 0.5.
    """
    if not (0.0 <= dose <= 1.0):
        raise ValueError(f"dose {dose!r} is not a fraction")
    if not (0.0 < prior < 1.0):
        raise ValueError(f"prior {prior!r} is not a probability strictly inside (0,1)")
    if p is None:
        return None
    return prior + dose * (p - prior)


def cohort_dose(dispositions):
    """Combine per-slot dispositions into one game-level dose. Multiplicative, floored.

    Multiplicative because two independently degraded slots are worse than one, and floored at
    0.20 because the contract's terminal behaviour is a widened prior, never an excluded game.
    """
    d = 1.0
    for x in dispositions:
        d *= x.dose_multiplier
    return max(0.20, round(d, 6))


# ====================================================================== selftest

def _stamp(days_old, grade=CONFIRMED, now=None, sha="a" * 8, obs_days=None):
    now = now or dt.datetime.now(UTC)
    t = now - dt.timedelta(days=days_old)
    o = now - dt.timedelta(days=obs_days if obs_days is not None else days_old)
    return Stamp(observed_at=o, effective_at=t, source="test", source_sha256=sha, grade=grade,
                 subject="test")


def selftest():
    now = dt.datetime(2026, 8, 28, 23, 10, tzinfo=UTC)
    f = []

    # A1 — THE 2026-08-28 HOU@NYM CASE, both slots, replayed.
    brown = Stamp(observed_at="2026-07-19T11:23:55Z", effective_at="2026-07-19T11:23:55Z",
                  source="data/mlb/stats/sp_2026-07-19.json", source_sha256="deadbeef",
                  grade=CONFIRMED, subject="Hunter Brown")
    d = resolve_input("Hunter Brown", "mlb", "starter", brown, now=now)
    if d.disposition != DEGRADED:
        f.append(f"A1a: a 40-day-old starter stamp resolved {d.disposition}, expected DEGRADED")
    if d.dose_multiplier >= 1.0:
        f.append(f"A1a: 40-day-old stamp kept dose {d.dose_multiplier}")

    scott = Stamp.absent("Christian Scott", "not present in any sp_*.json capture")
    d2 = resolve_input("Christian Scott", "mlb", "starter", scott, now=now)
    if d2.disposition != DEGRADED or d2.grade != ABSENT:
        f.append(f"A1b: an absent starter resolved {d2.disposition}/{d2.grade}")
    if d2.dose_multiplier >= 0.5:
        f.append(f"A1b: an absent starter kept dose {d2.dose_multiplier}")

    # the whole game must NOT have come out at dose 1.0 — the published value
    if cohort_dose([d, d2]) >= 1.0:
        f.append("A1c: HOU@NYM still produced a full information dose")

    # A2 — the game stays BETTABLE. Terminal behaviour is fetch/degrade, never block.
    if not (d.bettable and d2.bettable):
        f.append("A2: a degraded input made a game unbettable; the contract forbids that")
    if cohort_dose([d, d2]) <= 0:
        f.append("A2: cohort dose collapsed to zero")

    # A3 — None is not fresh.
    d3 = resolve_input("nobody", "mlb", "starter", None, now=now)
    if d3.disposition != DEGRADED or d3.grade != ABSENT:
        f.append(f"A3: a missing stamp resolved {d3.disposition}/{d3.grade}, expected DEGRADED/ABSENT")

    # A4 — a stamp with no timestamps is stale, not fresh.
    nots = Stamp(observed_at=None, effective_at=None, source="x", grade=CONFIRMED, subject="x")
    try:
        resolve_input("x", "mlb", "starter", nots, now=now)
        f.append("A4: a stamp missing observed_at AND effective_at was accepted")
    except StampError:
        pass

    # A5 — fresh confirmed keeps full dose.
    d5 = resolve_input("fresh guy", "mlb", "starter", _stamp(0.5, now=now), now=now)
    if d5.disposition != FRESH or d5.dose_multiplier != 1.0:
        f.append(f"A5: a same-day confirmed starter got {d5.disposition}/{d5.dose_multiplier}")

    # A6 — IDENTIFIED_UNCONFIRMED never reaches full dose even when fresh.
    d6 = resolve_input("searched", "mlb", "starter",
                       _stamp(0.5, grade=IDENTIFIED_UNCONFIRMED, now=now), now=now)
    if d6.dose_multiplier >= 1.0:
        f.append("A6: a search-identified starter reached full dose; snippets identify, never bind")

    # A7 — POST_HOC_NOT_PREGAME is capped hard. This is ml_asof's own self-description and it
    #      must never be promoted to a pregame confirmation by passing through a loader.
    d7 = resolve_input("posthoc", "mlb", "starter",
                       _stamp(0.5, grade=POST_HOC_NOT_PREGAME, now=now), now=now)
    if d7.dose_multiplier > 0.5:
        f.append("A7: a post-hoc row was treated as a pregame confirmation")

    # A8 — THE max() HOLE. A re-fetch that returns identical content must NOT clear staleness,
    #      even though it drives derived_age to ~0.
    stale = _stamp(40, now=now, sha="samehash")
    def refetch_same(subject, sport, kind):
        s = _stamp(40, now=now, sha="samehash")
        s.fetched_at = now                       # fetched NOW; observation and hash unchanged
        return s
    d8 = resolve_input("rotting", "mlb", "starter", stale, now=now, acquire=refetch_same)
    if d8.disposition != DEGRADED:
        f.append(f"A8: a refetch of identical bytes cleared staleness -> {d8.disposition}")
    # The DISPOSITION is now guarded twice — the content_age gate (A14) catches this case too, so
    # asserting DEGRADED alone no longer proves clear_requires_new_content still runs. The two
    # situations are diagnostically different and an operator has to tell them apart: "the source
    # served me the same bytes again" is a SOURCE problem, while "the source gave me something new
    # and it is still old" is a DATA problem. So the REASON is asserted, which is what only
    # clear_requires_new_content can produce.
    if "did not refresh the content" not in (d8.reason or ""):
        f.append(f"A8b: the refetch-of-identical-bytes case no longer names itself; reason was "
                 f"{d8.reason!r}. Two guards cover this hole, and the suite must still be able to "
                 "tell which one fired.")

    # A9 — a real refresh DOES clear it.
    def refetch_new(subject, sport, kind):
        s = _stamp(0.2, now=now, sha="newhash")
        s.fetched_at = now
        return s
    d9 = resolve_input("rotting", "mlb", "starter", stale, now=now, acquire=refetch_new)
    if d9.disposition != ACQUIRING or d9.dose_multiplier != 1.0:
        f.append(f"A9: a genuine refresh did not restore dose -> {d9.disposition}/{d9.dose_multiplier}")

    # A10 — an adapter that raises degrades; it must not take the slate down.
    def boom(subject, sport, kind):
        raise RuntimeError("network down")
    d10 = resolve_input("x", "mlb", "starter", _stamp(40, now=now), now=now, acquire=boom)
    if d10.disposition != DEGRADED:
        f.append("A10: an exploding adapter did not degrade cleanly")

    # A11 — per-sport limits are real and differ.
    nfl = resolve_input("qb", "nfl", "starter", _stamp(3, now=now), now=now)
    mlb = resolve_input("sp", "mlb", "starter", _stamp(3, now=now), now=now)
    if nfl.disposition != FRESH or mlb.disposition != DEGRADED:
        f.append(f"A11: sport-specific limits not applied (nfl={nfl.disposition} mlb={mlb.disposition})")

    # A13 — two degraded slots must COMPOUND, not take the better of the two. A game with both
    #       starters stale is worse informed than a game with one, and a max() combiner would hide
    #       exactly the HOU@NYM shape (40d away + 43d home) behind its least-bad slot.
    both = cohort_dose([d, d2])
    if not both < min(d.dose_multiplier, d2.dose_multiplier):
        f.append(f"A13: two degraded slots combined to {both}, which is not worse than the better "
                 f"slot ({min(d.dose_multiplier, d2.dose_multiplier)}) — the combiner is not "
                 "compounding")

    # A17 — THE DOSE MUST BE CONSUMED. A degraded row and a fresh row must not produce the same
    #       probability, and the shrink must target the REGISTERED PRIOR rather than 0.5.
    PRIOR = 0.5205399061032864          # mlb.winner.EXPANDING_HOME_PRIOR
    if shrink_to_prior(0.62, 1.0, PRIOR) != 0.62:
        f.append("A17: a full dose altered the probability; dose 1.0 must be identity")
    half = shrink_to_prior(0.62, 0.5, PRIOR)
    if not (PRIOR < half < 0.62):
        f.append(f"A17: a half dose put p at {half}, not strictly between the prior and p")
    if abs(shrink_to_prior(0.62, 0.0, PRIOR) - PRIOR) > 1e-12:
        f.append("A17: a zero dose did not return the prior exactly")
    # the direction matters on BOTH sides of the prior — an away-leaning row must move UP
    low = shrink_to_prior(0.40, 0.25, PRIOR)
    if not (0.40 < low < PRIOR):
        f.append(f"A17: a degraded away-leaning row moved to {low}; it must rise toward the prior")
    # and shrinking toward 0.5 instead of the prior would BIAS a degraded home side downward
    if shrink_to_prior(PRIOR, 0.25, PRIOR) != PRIOR:
        f.append("A17: a row sitting exactly at the prior moved under a partial dose")
    if abs((0.5 + 0.25 * (PRIOR - 0.5)) - PRIOR) < 1e-9:
        f.append("A17: the 0.5-target and prior-target shrinks are indistinguishable in this "
                 "fixture, so the test cannot detect the bias it exists to detect")

    # A14 — THE REFETCH-BUT-STALE HOLE. A fresh fetched_at over an ancient observation must NOT
    #       read FRESH. derived_age uses max(), so this stamp's generous clock reads 0.00d while
    #       its observation is 59 days old. Before 2026-08-29 this returned FRESH at dose 1.0.
    refetched = Stamp(observed_at="2026-07-01T00:00:00Z", effective_at="2026-07-01T00:00:00Z",
                      fetched_at=now, source="s", source_sha256="h", grade=CONFIRMED, subject="r")
    d14 = resolve_input("r", "mlb", "starter", refetched, now=now)
    if d14.disposition != DEGRADED:
        f.append(f"A14: a 59-day-old observation with a fresh fetched_at resolved "
                 f"{d14.disposition} — the generous clock is being read alone")
    if d14.dose_multiplier >= 1.0:
        f.append("A14: refetched-but-stale kept a full dose")

    # A15 — an acquisition that returns genuinely NEW content which is STILL older than the limit
    #       must degrade. New is not fresh; an adapter that can only reach old data must not be
    #       able to launder it into ACQUIRING at full dose.
    ancient = Stamp(observed_at="2026-06-01T00:00:00Z", effective_at="2026-06-01T00:00:00Z",
                    source="s", source_sha256="old", grade=CONFIRMED, subject="a")
    def _new_but_old(subject, sport, kind):
        return Stamp(observed_at="2026-07-01T00:00:00Z", effective_at="2026-07-01T00:00:00Z",
                     fetched_at=now, source="s2", source_sha256="new", grade=CONFIRMED,
                     subject=subject)
    d15 = resolve_input("a", "mlb", "starter", ancient, now=now, acquire=_new_but_old)
    if d15.disposition != DEGRADED:
        f.append(f"A15: acquisition of new-but-ancient content resolved {d15.disposition}")

    # A16 — and a GENUINELY fresh acquisition must still restore full dose, or the gate is a
    #       blanket cap and acquisition buys nothing.
    def _really_fresh(subject, sport, kind):
        return Stamp(observed_at="2026-08-27T00:00:00Z", effective_at="2026-08-27T00:00:00Z",
                     fetched_at=now, source="s2", source_sha256="new", grade=CONFIRMED,
                     subject=subject)
    d16 = resolve_input("a", "mlb", "starter", ancient, now=now, acquire=_really_fresh)
    if d16.disposition != ACQUIRING or d16.dose_multiplier != 1.0:
        f.append(f"A16: a genuinely fresh acquisition got {d16.disposition}/"
                 f"{d16.dose_multiplier}; acquisition must still be able to restore confidence")

    # A12 — the dose table is total; no lookup can KeyError mid-slate.
    for disp in (FRESH, ACQUIRING, DEGRADED):
        for gr in (CONFIRMED, IDENTIFIED_UNCONFIRMED, POST_HOC_NOT_PREGAME, ABSENT):
            if (disp, gr) not in DOSE:
                f.append(f"A12: DOSE has no entry for {(disp, gr)}")

    print(f"freshness_contract selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  !", x)
    return 0 if not f else 1


# ====================================================================== mutation suite

def mutation_suite():
    """Break the contract on purpose; every mutant must be caught by selftest.

    A gate nobody can prove is a gate nobody should trust — the 8/27 lesson, applied here.
    """
    import copy
    global MAX_AGE_DAYS, DOSE
    mutants = []

    def run(name, patch, restore):
        patch()
        try:
            caught = selftest() != 0
        except Exception:
            caught = True
        restore()
        mutants.append((name, caught))

    orig_age = dict(MAX_AGE_DAYS)
    orig_dose = dict(DOSE)

    run("M1 mlb starter limit widened to 90d",
        lambda: MAX_AGE_DAYS.update({("mlb", "starter"): 90}),
        lambda: (MAX_AGE_DAYS.clear(), MAX_AGE_DAYS.update(orig_age)))
    run("M2 absent input restored to full dose",
        lambda: DOSE.update({(DEGRADED, ABSENT): 1.0}),
        lambda: (DOSE.clear(), DOSE.update(orig_dose)))
    run("M3 degraded confirmed restored to full dose",
        lambda: DOSE.update({(DEGRADED, CONFIRMED): 1.0}),
        lambda: (DOSE.clear(), DOSE.update(orig_dose)))
    run("M4 search-identified promoted to full dose",
        lambda: DOSE.update({(FRESH, IDENTIFIED_UNCONFIRMED): 1.0}),
        lambda: (DOSE.clear(), DOSE.update(orig_dose)))
    run("M5 post-hoc promoted to pregame confirmation",
        lambda: DOSE.update({(FRESH, POST_HOC_NOT_PREGAME): 1.0}),
        lambda: (DOSE.clear(), DOSE.update(orig_dose)))
    run("M6 nfl and mlb limits collapsed to one value",
        lambda: MAX_AGE_DAYS.update({("mlb", "starter"): 4}),
        lambda: (MAX_AGE_DAYS.clear(), MAX_AGE_DAYS.update(orig_age)))

    # M7/M8 mutate FUNCTIONS, restored by reference
    g = globals()
    orig_clear = g["clear_requires_new_content"]
    run("M7 refetch-without-new-content allowed to clear staleness",
        lambda: g.__setitem__("clear_requires_new_content", lambda b, a: (True, "mutant")),
        lambda: g.__setitem__("clear_requires_new_content", orig_clear))

    orig_content = g["Stamp"].content_age_days
    run("M9 content_age ignored — gate reads only the generous derived_age",
        lambda: setattr(g["Stamp"], "content_age_days", lambda self, now: None),
        lambda: setattr(g["Stamp"], "content_age_days", orig_content))

    orig_cohort = g["cohort_dose"]
    run("M8 cohort dose takes the max instead of the product",
        lambda: g.__setitem__("cohort_dose", lambda ds: max(x.dose_multiplier for x in ds)),
        lambda: g.__setitem__("cohort_dose", orig_cohort))

    n = sum(1 for _, c in mutants if c)
    print(f"\nfreshness_contract mutation suite: {n}/{len(mutants)} caught")
    for name, c in mutants:
        print(f"  {'CAUGHT ' if c else 'ESCAPED'} {name}")
    return n == len(mutants)


def gate():
    ok = selftest() == 0
    print(f"freshness contract gate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--gate" in sys.argv:
        sys.exit(gate())
    print(__doc__)
