#!/usr/bin/env python3
"""BOARD INVARIANTS — the pre-publication checks that refuse a self-contradicting card.

THE INCIDENT, 2026-08-30. cards/2026-08-30_pregame_board_v6_canonical.json, game MIN @ ATL,
published with two market rows that cannot both be true:

    ML     row : model_win_pct 39.7, decision PASS, note "ML edge negative; divergence from
                 spread recorded"
    SPREAD row : model_cover_pct 64.2, edge_pp 14.3, usable_edge_pp 6.9, decision LEAN,
                 note "cover p = Phi(5.1/13.97)", entry.price_american = null,
                 market_no_vig_cover_pct = 50.0

Invert both against the sigma the row itself declares (13.97) and the contradiction is arithmetic,
not a matter of taste: the spread row projects ATL winning by 2.58, the ML row projects ATL LOSING
by 3.65. Same game, same row group, same declared sigma, opposite sign, 6.23 points apart. The
board already owns a CONVERGENCE_FAIL posture and used it exactly once in that file, on HOU@NYM —
not here. The divergence was written into a prose note and the contradicting arm was then promoted
to the board's only LEAN.

The second half of the same defect: that 14.3pp edge is model minus an ASSUMED 50.0 no-vig. No
price was captured on either side of that spread (entry.price_american is null, and this schema
has no field for the opposite side at all), so 50.0 is the sentence "a spread is a coin flip at
the number" typed into a field. usable_edge_pp then discounts 14.3 by DQ 0.65 x Unc 0.75 and
publishes 6.9 — which launders a wrong base into a number that LOOKS conservatively derived. A
discount applied to an invented base does not repair it; it disguises it.

This module is a MODEL-CONSISTENCY gate. It is deliberately independent of everything about
sources: score_admission.py answers "may this score be believed", and this file answers "does this
card contradict itself". A card can be built entirely from validated canonical feeds and still be
incoherent, which is exactly what happened on 8/30. The two defects were found the same day and
share nothing but a date.

FOUR INVARIANTS, each with named codes (all emitted codes are listed in REASON_MEANING):

  MISSING_MARKET_PRICE     entry.price_american null => an edge and a usable_edge MUST NOT exist.
                           Fires only on a row that actually makes a priced claim (carries an edge,
                           or is decided LEAN/PLAY) — a NO_LINE row with no price and no edge is
                           not a defect, and a check that fires on all 39 null-price rows would be
                           noise nobody reads.
  MARKET_NO_VIG_ASSUMED_NOT_CAPTURED
                           the subtler form: a no-vig probability standing where no price was ever
                           captured. Roundness (50.0) is the TELL, not the rule — gating on
                           roundness would let 51.3 through, and an assumed 51.3 is worse because
                           it looks derived. The rule is "no captured price", and detail records
                           whether the value is round.
  MODEL_CONVERGENCE_FAIL   when an ML probability and a spread cover probability are presented as
                           one distribution, invert BOTH to a projected margin at the declared
                           sigma and compare. Materially incompatible => suppress LEAN/PLAY. The
                           two margins and the gap are GENERATED here and reported; nothing about
                           them is typed.
  AVAILABILITY_UNKNOWN     availability stale or unresolved => state is UNKNOWN and any play that
                           depends on it is suppressed. Unresolved is the DEFAULT: a board that
                           ships no availability record has not answered the question, and
                           treating silence as "available" is how the MIN@ATL note
                           ("Brionna Jones out (pre-open); ATL possible B2B - model blind")
                           coexisted with a LEAN.
  STALE_FEATURES           decision or signal_decision LEAN/PLAY while data_quality.status is
                           STALE or CAP. On 8/30 the board's one LEAN sat on a STALE row.

SIGMA DISCIPLINE, and why it is read from a file. 13.97 is a REGISTERED COHERENCE TOLERANCE, not a
distributional constant — data/audit/2026-08-30_sigma_provenance_register.json says so in as many
words ("NOT a cover law and NOT a residual SD. Using it as a distributional constant is a category
error regardless of any measurement"). The measured WNBA figures are 12.5523 (margin residual) and
18.0156 (totals residual), n=1721 each. This module therefore READS the register instead of
carrying a number, classifies whatever sigma a row declares, and emits UNMEASURED_SIGMA when the
register does not call it MEASURED. That code is a WARNING and does not by itself suppress,
because on a row like MIN@ATL SPREAD_RL the sigma is the SMALLEST thing wrong: the row is already
refused for a missing price and a contradiction. If the register file is absent the module RAISES
(SigmaRegisterMissing) rather than falling back to a default — a fallback sigma would be exactly
the invented number R1 forbids, and it would silently re-legitimise 13.97.

WHERE THE OWNER'S TWO STATEMENTS DISAGREE, and the resolution implemented here. The directive says
"if market_price is null: ... decision = PASS_DATA_QUALITY", and it also states the exact required
output for the row that IS the null-price case:

    {"decision": "PASS", "reason_codes": ["MISSING_MARKET_PRICE", "AVAILABILITY_UNKNOWN",
                                          "MODEL_CONVERGENCE_FAIL"]}

Both cannot be written into one field. The resolution, stated rather than silently picked: the
artifact's `decision` field speaks a four-value vocabulary (PASS, LEAN, NO_LINE, CLV_ONLY) and
widening it here would fork the board schema, so `decision` carries the owner's literal answer,
PASS, and the diagnosis PASS_DATA_QUALITY / CONVERGENCE_FAIL is carried beside it as `posture`.
Nothing is lost and nothing is invented: the codes say which invariants fired, posture says which
one governs, decision says what may be done. score_admission.MIN_ATL_REQUIRED_ROW is asserted
against directly, so the two modules test one object rather than two copies of a list of strings.

SUPPRESSION NEVER PROMOTES. A suppressed row's decision becomes PASS only when it was LEAN or
PLAY. A NO_LINE row stays NO_LINE: NO_LINE is already non-actionable AND more specific, and
overwriting it with PASS would destroy information to satisfy a rule that has nothing to add.

R3, and how it is proved rather than promised. enforce() never mutates its input. It deep-copies,
edits the copy, and then compares a sha256 of the canonical JSON of the input taken BEFORE and
AFTER the edit; a mismatch raises. The selftest additionally hashes the frozen file on disk before
and after a full enforce() run. A promise not to mutate is not a control; the hash is.

NO NETWORK. This module reads two files (the card under test and the sigma register) and reaches
nothing. ALLOW_DIRECT_HTTP is declared False so the posture is stated, and selftest S0 scans this
file's own source for network call sites — needles assembled by concatenation so the scan cannot
match itself — so the claim is a check and not a comment. There is no fetch entry point, so this
module is deliberately NOT registered in test_egress_discipline.GUARDED; if one is ever added,
register it in the same commit.

THE 2026-08-30 ADVERSARIAL REVIEW, and what it found still broken in here. The record is
data/audit/2026-08-30_isolation_layer_review.json (SCORE-ISOLATION-LAYER-REVIEW-2026-08-30, 35
HIGH findings across 15 clusters). Four landed on this file, and every one of them was on the
WRITE path or in the suite that was supposed to be watching it — the checks themselves were
right, which is precisely why nobody noticed:

  G  enforce() never actually removed the edge. The suppression was computed correctly and then
     discarded: the enforced copy still published edge_pp 14.3, usable_edge_pp 6.9 and the assumed
     market_no_vig_cover_pct 50.0 verbatim, so a downstream reader of the ENFORCED card found the
     laundered number exactly where the frozen one left it. That is compute-then-discard for the
     sixth independent time in this repo. Now: those figures are set to None on any row whose
     codes prohibit them, the keys are KEPT (three sibling modules read them), and every removal
     is recorded with its prior value and reason under row["board_invariants"]["redacted"] and in
     the change log. See PROHIBITED_EDGE_FIELDS.
  H  enforce() keyed row verdicts by MARKET NAME, so a game carrying two rows of one market
     applied both verdicts to the LAST row: the offending row kept its LEAN with no reason codes
     and a clean row was demoted with an empty list. Verdicts now carry RowVerdict.row_index and
     are bound by index, CONFIRMED against (market, selection, line). S19 is the two-row fixture.
  I  _markets_of() returned [] where _games_of() raises for the same class of hazard, so a board
     whose per-game rows live under any other key was reported CLEAN with every LEAN intact and
     enforce() reporting zero changes. It raises now. A checker that finds nothing to check must
     say so, not pass.
     POSITIONAL PAIRING WITH NO IDENTITY ASSERTION. enforce() paired verdicts to games by
     position, and when handed a path it read the file TWICE — once for `original`, once inside
     check_board. The R3 sha256 proves the input OBJECT was not mutated; it cannot notice that the
     verdict describes a different board, which is owner regression fixture 7 (same matchup,
     different date) landing inside this module, nor that the two reads of one filename returned
     different bytes (the mutable-archive hazard the contract names). The path is read ONCE now
     (check_board grew a `source=` label so the read need not be repeated to keep the name) and
     every pairing asserts identity: game count, then (event_id, game), then the row tuple.
  O  the mutation suite counted ANY exception as a kill, including a mutant dying at import before
     a fixture ran. Kills are now only NAMED assertion failures (or a specifically expected
     exception type) and the tally reads "N killed, M errored, K survived". Fixtures that used to
     die of an IndexError under a mutant — S3's [0] lookups — were rewritten to fail by name.

THE 2026-08-30 RE-ATTACK (round two), and what it found still broken in here. The record is
data/audit/2026-08-30_isolation_layer_reattack.json. Round one found untouched defects; round two
found INCOMPLETE FIXES — "a guard added and then made skippable, a value nulled in one place and
republished in another". Four of them were in this file:

  G, MOVED NOT REMOVED. enforce() nulled probabilities.edge_pp, usable_edge_pp and the assumed
     no-vig — and then republished the same three numbers as LIVE values, under the same key
     names, at row["board_invariants"]["detail"]: 14.3, 6.9 and 50.0, intact, in the enforced
     copy, with no refusal marker on them. check_row records what it judged and enforce() copied
     dict(rv.detail) onto the row, so the redaction was applied to one representation of the
     figure and not to the other. SANITISATION MEANS THE VALUE IS GONE — not that the primary
     field is null while a copy survives elsewhere. The prohibition is now applied where the
     figure is BORN, inside RowVerdict (section 6b), so the verdict object, its to_dict(), the
     enforced row's diagnostics block and anything a caller serialises downstream all inherit it
     instead of each copy needing its own removal. S23 walks the ENTIRE enforced structure
     recursively and refuses to find either figure as a live number anywhere outside the labelled
     refusal ledger.

  I, ONE LEVEL DOWN. check_game() silently SKIPPED a non-mapping entry in game["markets"] while
     _games_of() and _markets_of() raise for the same class of hazard. Executed against this
     module: the frozen 8/30 board with every dict row wrapped in a ONE-ELEMENT LIST came back
     ROWS_CHECKED "0/0", GAMES_CHECKED "19/19", clean=True, reason_totals {} — and enforce() then
     passed every row through byte-identical, republishing the laundered edge and the LEAN. The
     counter could not report the gap because both sides of it were the FILTERED count
     ("%d/%d" % (n_rows, n_rows) is a check that cannot fail). Now: a non-mapping row is a
     BoardInvariantsError naming the game and the index; ROWS_CHECKED's denominator is the rows
     SUPPLIED (GameVerdict.rows_supplied, taken from the published list before anything is
     filtered); and a board with any unchecked row is NOT clean.

  R3, PROVED OVER THE WRONG WINDOW. enforce() took its baseline hash AFTER check_board had already
     run on the caller's object — load_board() returns the caller's dict by reference — so any
     mutation check_board made was folded into the "before" and INPUT_UNCHANGED could not see it.
     The hash is taken FIRST now, immediately after load_board and before the check runs. S26
     monkeypatches check_board with one that stamps a key on the board it is handed and requires
     enforce() to raise.

  O, HALF APPLIED. The crash half was closed here in round one (an ERRORED mutant is not a kill).
     The MISDIRECTION half was not: this runner credited a KILL to ANY named failure, so a mutant
     dying on a DIFFERENT protection's assertion was tallied as its own kill. Every MUTANTS entry
     now DECLARES the fixture that owns the guard it removes; a kill requires that fixture to
     fire and anything else is MISDIRECTED; and an ERROR_CANARY tests the classifier itself
     rather than trusting it, as score_admission's has since round one.

Vocabulary is IMPORTED from harness/score_admission.py wherever it overlaps (decisions, the four
board reason codes, AVAILABILITY_UNKNOWN, MIN_ATL_REQUIRED_ROW). Retyping a string literal is how
a vocabulary forks, and three modules were built against this contract in parallel. Note one
naming difference worth stating out loud: the directive's prose calls the assumed-no-vig code
"ASSUMED_NO_VIG_PRICE"; the shared contract spells it MARKET_NO_VIG_ASSUMED_NOT_CAPTURED. This
module emits the SHARED spelling and records the prose name in DIRECTIVE_NAME_ALIASES so a reader
searching for the directive's wording lands on the answer instead of inventing a second code.

Usage: python3 harness/board_invariants.py [--selftest] [--mutants] [--gate]
"""
from __future__ import annotations

MODULE_ID = "board_invariants"

import copy
import hashlib
import json
import math
import os
import re
import sys
from statistics import NormalDist

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import score_admission as sa            # noqa: E402  shared vocabulary, bound not retyped

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: This module reaches nothing over the network. The flag DECLARES the posture; S0 proves it.
ALLOW_DIRECT_HTTP = False


class BoardInvariantsError(RuntimeError):
    """The board could not be checked at all — shape refused, not rows refused."""


class SigmaRegisterMissing(RuntimeError):
    """The sigma provenance register is absent. Fail loudly; never assume a sigma (R1)."""


# ---------------------------------------------------------------------------------------------
# 1. VOCABULARY.  Four codes are IMPORTED from score_admission; six are owned here.
# ---------------------------------------------------------------------------------------------

DECISION_PASS = sa.DECISION_PASS
DECISION_LEAN = sa.DECISION_LEAN
DECISION_PASS_DATA_QUALITY = sa.DECISION_PASS_DATA_QUALITY
DECISION_CONVERGENCE_FAIL = sa.DECISION_CONVERGENCE_FAIL

REASON_MISSING_MARKET_PRICE = sa.BOARD_REASON_MISSING_MARKET_PRICE
REASON_AVAILABILITY_UNKNOWN = sa.BOARD_REASON_AVAILABILITY_UNKNOWN
REASON_MODEL_CONVERGENCE_FAIL = sa.BOARD_REASON_MODEL_CONVERGENCE_FAIL
REASON_ASSUMED_NO_VIG = sa.BOARD_REASON_ASSUMED_NO_VIG

#: Owned here. Named after the failure mode, not the check, so a future maintainer cannot "fix" a
#: refusal by loosening the wrong thing.
REASON_STALE_FEATURES = "STALE_FEATURES"
REASON_SIGMA_DISAGREEMENT = "SIGMA_DISAGREEMENT"
REASON_CONVERGENCE_UNVERIFIABLE = "CONVERGENCE_UNVERIFIABLE"
REASON_UNMEASURED_SIGMA = "UNMEASURED_SIGMA"
REASON_EDGE_NOT_REPRODUCIBLE = "EDGE_NOT_REPRODUCIBLE_FROM_FIELDS"
REASON_NO_VIG_ONE_SIDED = "MARKET_NO_VIG_NOT_REPRODUCIBLE_ONE_SIDED_PRICE"

#: The directive's prose name -> the code actually emitted. Recorded so the two spellings resolve
#: to ONE code instead of two.
DIRECTIVE_NAME_ALIASES = {"ASSUMED_NO_VIG_PRICE": REASON_ASSUMED_NO_VIG}

#: Emission order. The first three are the owner's order in MIN_ATL_REQUIRED_ROW and are asserted
#: against it, so the required row reads back in the order it was written.
BOARD_REASON_ORDER = (
    REASON_MISSING_MARKET_PRICE,
    REASON_AVAILABILITY_UNKNOWN,
    REASON_MODEL_CONVERGENCE_FAIL,
    REASON_ASSUMED_NO_VIG,
    REASON_STALE_FEATURES,
    REASON_SIGMA_DISAGREEMENT,
    REASON_CONVERGENCE_UNVERIFIABLE,
    REASON_UNMEASURED_SIGMA,
    REASON_EDGE_NOT_REPRODUCIBLE,
    REASON_NO_VIG_ONE_SIDED,
)

#: Codes that remove an action.
SUPPRESSING_REASONS = frozenset({
    REASON_MISSING_MARKET_PRICE, REASON_AVAILABILITY_UNKNOWN, REASON_MODEL_CONVERGENCE_FAIL,
    REASON_ASSUMED_NO_VIG, REASON_STALE_FEATURES, REASON_SIGMA_DISAGREEMENT,
    REASON_CONVERGENCE_UNVERIFIABLE,
})

#: Codes that are recorded and do not by themselves suppress. UNMEASURED_SIGMA is here on the
#: owner's instruction: on a row that is already refused twice over it is the smallest thing wrong.
WARNING_REASONS = frozenset({
    REASON_UNMEASURED_SIGMA, REASON_EDGE_NOT_REPRODUCIBLE, REASON_NO_VIG_ONE_SIDED,
})

REASON_MEANING = {
    REASON_MISSING_MARKET_PRICE:
        "entry.price_american is null on a row that carries an edge or is decided LEAN/PLAY. No "
        "price means no market probability means no edge; the edge must not exist.",
    REASON_AVAILABILITY_UNKNOWN:
        "injury/roster availability is unresolved or stale, so availability_state is UNKNOWN and "
        "any play depending on it is suppressed. Silence is UNKNOWN, never AVAILABLE.",
    REASON_MODEL_CONVERGENCE_FAIL:
        "the ML arm and the spread arm invert to materially incompatible projected margins at the "
        "declared sigma. Two arms of one distribution disagreeing about the outcome is not a "
        "divergence to record in a note; it is a card that cannot be published.",
    REASON_ASSUMED_NO_VIG:
        "a market_no_vig_* probability stands on a row where no price was captured, so it was "
        "assumed rather than derived. Discounting an edge built on it by DQ x Unc launders the "
        "base instead of repairing it.",
    REASON_STALE_FEATURES:
        "decision or signal_decision is LEAN/PLAY while data_quality.status is STALE or CAP.",
    REASON_SIGMA_DISAGREEMENT:
        "two arms of one game declare different sigmas, so they are not one distribution by "
        "construction and no margin comparison between them is meaningful.",
    REASON_CONVERGENCE_UNVERIFIABLE:
        "both arms claim a probability but the comparison cannot be performed — no sigma is "
        "declared, or the spread row does not identify its side/signed line. An unverifiable "
        "coherence claim suppresses, because the alternative is publishing on an unchecked one.",
    REASON_UNMEASURED_SIGMA:
        "the sigma used is not classified MEASURED by the sigma provenance register (13.97 is a "
        "REGISTERED_TOLERANCE). WARNING: recorded, does not suppress on its own.",
    REASON_EDGE_NOT_REPRODUCIBLE:
        "edge_pp does not equal model probability minus the no-vig probability at the published "
        "precision, so the field was not generated from the fields beside it. WARNING.",
    REASON_NO_VIG_ONE_SIDED:
        "a no-vig probability is published from a schema that stores exactly one side's price, so "
        "it cannot be reproduced by normalising two implied probabilities. WARNING.",
}

REASON_CODES = tuple(sorted(REASON_MEANING))

#: Decisions that assert an action. Suppression only ever removes one of these.
PLAY_DECISIONS = frozenset({DECISION_LEAN, "PLAY"})

#: data_quality.status values that must not carry a play.
SUPPRESSING_DQ_STATUSES = frozenset({"STALE", "CAP"})

#: Market names in this card schema. Convergence concerns the first two only.
MARKET_ML = "ML"
MARKET_SPREAD = "SPREAD_RL"
MARKET_TOTALS = "TOTALS"
CONVERGENCE_MARKETS = (MARKET_ML, MARKET_SPREAD)

#: The model probability field that carries "this side wins / this side covers", per market. The
#: probabilities block is polymorphic by market, so a checker must dispatch before it can name a
#: field; hard-coding one name is how a TOTALS row gets read as a moneyline.
MODEL_PROBABILITY_FIELD = {MARKET_ML: "model_win_pct",
                           MARKET_SPREAD: "model_cover_pct",
                           MARKET_TOTALS: "model_over_pct"}
NO_VIG_FIELD = {MARKET_ML: "market_no_vig_pct",
                MARKET_SPREAD: "market_no_vig_cover_pct",
                MARKET_TOTALS: "market_no_vig_selected_pct"}

AVAILABILITY_UNKNOWN = sa.AVAILABILITY_UNKNOWN
AVAILABILITY_NOT_SUPPLIED = "NOT_SUPPLIED"
AVAILABILITY_EXPLICIT_UNKNOWN = "EXPLICIT_UNKNOWN"
AVAILABILITY_STALE = "STALE"
AVAILABILITY_RESOLVED = "RESOLVED"

#: How old an availability observation may be before it stops answering the question. Stated, not
#: derived: a lineup/injury report older than a day has been superseded by at least one news cycle
#: and a shootaround. Overridable per entry via "max_age_hours".
AVAILABILITY_MAX_AGE_HOURS = 24.0


# ---------------------------------------------------------------------------------------------
# 2. SIGMA PROVENANCE.  Read the register; never carry a sigma.
# ---------------------------------------------------------------------------------------------

SIGMA_REGISTER_PATH = os.path.join(REPO_ROOT, "data", "audit",
                                   "2026-08-30_sigma_provenance_register.json")

SIGMA_KIND_MEASURED = "MEASURED"

_REGISTER_CACHE = {}


def load_sigma_register(path=None):
    """The sigma provenance register, or a loud refusal.

    R1: if this file is gone there is no honest sigma to use. A default here would re-legitimise
    13.97 — the exact value the register exists to demote — under a different name.
    """
    p = path or SIGMA_REGISTER_PATH
    if p in _REGISTER_CACHE:
        return _REGISTER_CACHE[p]
    if not os.path.exists(p):
        raise SigmaRegisterMissing(
            "sigma provenance register not found at %r. Refusing to assume a sigma: the register "
            "is the only artifact that says which values are MEASURED and which are a registered "
            "coherence tolerance." % p)
    with open(p) as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or not isinstance(doc.get("REGISTER"), dict):
        raise SigmaRegisterMissing(
            "sigma provenance register at %r has no REGISTER map; it cannot classify anything" % p)
    _REGISTER_CACHE[p] = doc
    return doc


def sigma_kind(value, register=None):
    """The register's classification of a sigma value, or None if the register never heard of it.

    Matched at the precision the register itself wrote: "13.97" is two decimals, so a row saying
    13.97 matches and one saying 13.9 does not. Nothing is rounded INTO a match.
    """
    v = _num(value)
    if v is None:
        return None
    reg = (register or load_sigma_register()).get("REGISTER", {})
    for key, entry in reg.items():
        kv = _num(key)
        if kv is None:
            continue
        decimals = len(key.split(".")[1]) if "." in key else 0
        if abs(kv - v) <= 0.5 * (10.0 ** -decimals):
            return (entry or {}).get("kind")
    return None


def sigma_is_measured(value, register=None):
    return sigma_kind(value, register) == SIGMA_KIND_MEASURED


def measured_sigmas(register=None):
    """Every value the register calls MEASURED, with its declared base and n. Generated, not typed."""
    reg = (register or load_sigma_register()).get("REGISTER", {})
    out = {}
    for key, entry in sorted(reg.items()):
        if (entry or {}).get("kind") == SIGMA_KIND_MEASURED:
            out[key] = {"base": entry.get("base"), "n": entry.get("n"), "file": entry.get("file")}
    return out


# ---------------------------------------------------------------------------------------------
# 3. THE ARITHMETIC.  Every number below is produced here and reported; none is typed into a rule.
# ---------------------------------------------------------------------------------------------

_NORMAL = NormalDist()

#: Two arms agree if their implied margins sit within this many points of each other. Stated
#: reason: at the sigma this board declares (13.97) one point of projected margin is worth
#: Phi(1/13.97) - 0.5 = 2.85 percentage points of win probability, while the board publishes
#: probabilities on a 0.1pp grid. A gap under a point is therefore inside the publication
#: rounding by an order of magnitude; a gap over it is not rounding.
CONVERGENCE_MARGIN_TOLERANCE_POINTS = 1.0

#: A sign disagreement is qualitative — the ML market is a bet ON the sign — so it counts even
#: when the magnitudes are small. This floor keeps pure rounding noise out: +-0.25 points is about
#: +-0.7pp at 13.97, well inside the grid.
CONVERGENCE_SIGN_MATERIALITY_POINTS = 0.25

#: edge_pp is published to 0.1pp, so a recomputation may differ by half a grid step and no more.
EDGE_RECOMPUTE_TOLERANCE_PP = 0.051

#: A no-vig probability landing exactly on this grid is "round". Roundness is reported as a tell;
#: it is NOT the rule (see the module docstring).
ASSUMED_NO_VIG_ROUND_GRID_PP = 5.0

_PHI_RE = re.compile(r"Phi\(\s*[-+]?[0-9]*\.?[0-9]+\s*/\s*([0-9]*\.?[0-9]+)\s*\)")
_SIGNED_SELECTION_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9._-]*)\s*([+-]\s*[0-9]*\.?[0-9]+)\s*$")
_BARE_SELECTION_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9._-]*)\s*$")
_MATCHUP_RE = re.compile(r"^\s*(\S+)\s*@\s*(\S+)\s*$")


def _num(value):
    """A float, or None. Booleans are not numbers here — True must never read as 1.0 percent."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def implied_margin_from_win_pct(win_pct, sigma):
    """Invert P(win) to a projected margin: mu = sigma * Phi^-1(p)."""
    p = _num(win_pct)
    s = _num(sigma)
    if p is None or s is None or s <= 0 or not (0.0 < p < 100.0):
        return None
    return s * _NORMAL.inv_cdf(p / 100.0)


def implied_margin_from_cover_pct(cover_pct, signed_line, sigma):
    """Invert P(cover) to a projected margin for the SELECTED side.

    A side laying/taking `signed_line` covers when margin + signed_line > 0, so
    p = Phi((mu + signed_line)/sigma) and mu = sigma * Phi^-1(p) - signed_line. For MIN@ATL the
    board's own note states the numerator, Phi(5.1/13.97) at line +2.5, which is this identity
    written out: 5.0824 - 2.5 = 2.5824.
    """
    p = _num(cover_pct)
    s = _num(sigma)
    line = _num(signed_line)
    if p is None or s is None or line is None or s <= 0 or not (0.0 < p < 100.0):
        return None
    return s * _NORMAL.inv_cdf(p / 100.0) - line


def _is_round_no_vig(value):
    v = _num(value)
    if v is None:
        return False
    return abs(v / ASSUMED_NO_VIG_ROUND_GRID_PP - round(v / ASSUMED_NO_VIG_ROUND_GRID_PP)) < 1e-9


def _order_codes(codes):
    """Canonical emission order; unknown codes sort after the known ones, alphabetically."""
    known = {c: i for i, c in enumerate(BOARD_REASON_ORDER)}
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return sorted(out, key=lambda c: (known.get(c, len(known)), c))


# ---------------------------------------------------------------------------------------------
# 4. ROW / GAME ACCESSORS.  The probabilities block is polymorphic; dispatch before naming a field.
# ---------------------------------------------------------------------------------------------

def _markets_of(game):
    """The game's market rows, or a forensic refusal — never a silent empty list.

    CLUSTER I, adversarial review 2026-08-30. This function used to answer `[]` for a game whose
    rows live under any key but "markets", while _games_of() raises for the same class of hazard
    one level up. The consequence was not a mild one: a board shaped like the CFB card (rows
    parked at board["rows"]) came back CLEAN, every LEAN intact, enforce() reporting zero changes
    and the counters printing "0/0" as though that were a result. A checker that finds nothing to
    check must say so. Same refusal as _games_of, same reason, one level down.
    """
    if not isinstance(game, dict):
        raise BoardInvariantsError("game is not a mapping: %r" % type(game).__name__)
    m = game.get("markets")
    if not isinstance(m, list):
        raise BoardInvariantsError(
            "game %r carries no ['markets'] list (it has %s; markets is %s). This module refuses "
            "to go looking for the rows: board_shape.py exists because the CFB board parked its "
            "rows at board['rows'] and the NFL board moved them between 8/27 and 8/28. Returning "
            "[] here reports a board CLEAN because nothing was checked, which is the one answer "
            "an invariant checker must never give."
            % (game.get("game"), sorted(game), type(m).__name__))
    return m


def _market_named(game, name):
    for m in _markets_of(game):
        if isinstance(m, dict) and m.get("market") == name:
            return m
    return None


def model_probability_of(market_row):
    """(field_name, value) for the row's own 'this side' probability, or (None, None)."""
    field = MODEL_PROBABILITY_FIELD.get((market_row or {}).get("market"))
    if not field:
        return None, None
    return field, _num(((market_row or {}).get("probabilities") or {}).get(field))


def no_vig_of(market_row):
    """(field_name, value) for the row's market no-vig probability, or (None, None)."""
    field = NO_VIG_FIELD.get((market_row or {}).get("market"))
    if not field:
        return None, None
    return field, _num(((market_row or {}).get("probabilities") or {}).get(field))


def teams_of(game):
    """(away, home) parsed from the 'AWY @ HOM' label, or (None, None). Never guessed."""
    m = _MATCHUP_RE.match(str((game or {}).get("game") or ""))
    return (m.group(1), m.group(2)) if m else (None, None)


def declared_sigmas(game):
    """Every sigma this game DECLARES, keyed by market: {market: (value, where)}.

    This schema has no sigma field, so the value is read out of the row's own prose note
    ("cover p = Phi(5.1/13.97)"). That IDENTIFIES the declared sigma; it does not bind a result,
    and a row that declares nothing is not given one (R1). An explicit `sigma` key on the row or
    the game wins over the note, so a future schema that carries the field is read from the field.
    """
    out = {}
    g_sigma = _num((game or {}).get("sigma"))
    for row in _markets_of(game):
        if not isinstance(row, dict):
            continue
        name = row.get("market")
        row_sigma = _num(row.get("sigma"))
        if row_sigma is not None:
            out[name] = (row_sigma, "row.sigma")
            continue
        note = row.get("note")
        if isinstance(note, str):
            m = _PHI_RE.search(note)
            if m:
                v = _num(m.group(1))
                if v is not None:
                    out[name] = (v, "note:%s" % m.group(0))
                    continue
        if g_sigma is not None:
            out[name] = (g_sigma, "game.sigma")
    return out


def selection_side(market_row):
    """(team, signed_line) from a selection string. ('ATL +2.5' -> ('ATL', 2.5), 'ATL' -> ('ATL', None))

    A bare team code with a positive `line` field is NOT resolved to a signed line here: the 8/30
    board carries three spread rows with selection null and a signed line (-1.5, -4.5, -13.5) whose
    side is unanswerable from the row, and the card spec forbids inferring one market's side from
    another's. Unanswerable is reported, not guessed.
    """
    sel = (market_row or {}).get("selection")
    if not isinstance(sel, str) or not sel.strip():
        return None, None
    m = _SIGNED_SELECTION_RE.match(sel)
    if m:
        return m.group(1), _num(m.group(2).replace(" ", ""))
    m = _BARE_SELECTION_RE.match(sel)
    if m:
        return m.group(1), None
    return None, None


# ---------------------------------------------------------------------------------------------
# 5. AVAILABILITY.  Silence is UNKNOWN.
# ---------------------------------------------------------------------------------------------

def resolve_availability(value, now_utc=None):
    """(state, why). Accepts None, a state string, or {"state","as_of_utc","max_age_hours"}.

    Roster semantics are deliberately not modelled. The only question asked is whether the
    availability question has been ANSWERED, and answered recently enough to still be an answer.
    """
    if value is None:
        return AVAILABILITY_UNKNOWN, AVAILABILITY_NOT_SUPPLIED
    if isinstance(value, str):
        if not value.strip() or value.strip().upper() == AVAILABILITY_UNKNOWN:
            return AVAILABILITY_UNKNOWN, AVAILABILITY_EXPLICIT_UNKNOWN
        return value.strip().upper(), AVAILABILITY_RESOLVED
    if isinstance(value, dict):
        state = value.get("state")
        if not isinstance(state, str) or not state.strip() \
                or state.strip().upper() == AVAILABILITY_UNKNOWN:
            return AVAILABILITY_UNKNOWN, AVAILABILITY_EXPLICIT_UNKNOWN
        as_of = value.get("as_of_utc")
        now = now_utc if now_utc is not None else value.get("now_utc")
        if as_of is not None and now is not None:
            try:
                age_h = (sa.parse_utc(now) - sa.parse_utc(as_of)).total_seconds() / 3600.0
            except (ValueError, TypeError):
                return AVAILABILITY_UNKNOWN, AVAILABILITY_EXPLICIT_UNKNOWN
            limit = _num(value.get("max_age_hours"))
            if limit is None:
                limit = AVAILABILITY_MAX_AGE_HOURS
            if age_h > limit:
                return AVAILABILITY_UNKNOWN, AVAILABILITY_STALE
        return state.strip().upper(), AVAILABILITY_RESOLVED
    return AVAILABILITY_UNKNOWN, AVAILABILITY_EXPLICIT_UNKNOWN


# ---------------------------------------------------------------------------------------------
# 6. CONVERGENCE.  Two arms, one distribution, or the card does not publish.
# ---------------------------------------------------------------------------------------------

UNVERIFIABLE_NO_SIGMA = "NO_SIGMA_DECLARED"
UNVERIFIABLE_SIDE = "SPREAD_SIDE_UNIDENTIFIED"
UNVERIFIABLE_LINE = "SPREAD_LINE_UNSIGNED"


def check_convergence(game, *, sigma=None, register=None):
    """Compare the ML arm and the spread arm of one game. None when the question does not arise.

    The question arises only when BOTH arms publish a model probability. A game whose spread row
    carries model_cover_pct null is not claiming a second view of the same distribution, and
    inventing one for it in order to have something to check would be the defect, not the check.
    On the 8/30 board that makes this run on exactly one of nineteen games — which is why the
    mutation suite carries synthetic pairs: a check with one live case has no evidence it can fail.
    """
    ml = _market_named(game, MARKET_ML)
    sp = _market_named(game, MARKET_SPREAD)
    _, ml_p = model_probability_of(ml)
    _, cov_p = model_probability_of(sp)
    if ml_p is None or cov_p is None:
        return None

    codes, warnings = [], []
    detail = {"ml_model_pct": ml_p, "spread_cover_pct": cov_p,
              "tolerance_points": CONVERGENCE_MARGIN_TOLERANCE_POINTS,
              "sign_materiality_points": CONVERGENCE_SIGN_MATERIALITY_POINTS}

    declared = declared_sigmas(game)
    pair = {m: declared[m] for m in CONVERGENCE_MARKETS if m in declared}
    distinct = sorted({round(v, 6) for v, _ in pair.values()})
    detail["declared_sigmas"] = {m: {"value": v, "where": w} for m, (v, w) in sorted(pair.items())}

    if sigma is not None:
        used, source = _num(sigma), "caller"
    elif len(distinct) > 1:
        codes.append(REASON_SIGMA_DISAGREEMENT)
        detail["sigma_values_in_one_game"] = distinct
        return {"applicable": True, "codes": _order_codes(codes), "warnings": warnings,
                "detail": detail}
    elif distinct:
        used = distinct[0]
        source = sorted(w for _, w in pair.values())[0]
    else:
        used, source = None, None

    detail["sigma"] = used
    detail["sigma_source"] = source
    if used is None:
        codes.append(REASON_CONVERGENCE_UNVERIFIABLE)
        detail["unverifiable_reason"] = UNVERIFIABLE_NO_SIGMA
        return {"applicable": True, "codes": _order_codes(codes), "warnings": warnings,
                "detail": detail}

    detail["sigma_kind"] = sigma_kind(used, register)
    if not sigma_is_measured(used, register):
        warnings.append(REASON_UNMEASURED_SIGMA)

    ml_team, _ = selection_side(ml)
    sp_team, signed_line = selection_side(sp)
    away, home = teams_of(game)
    detail.update({"ml_side": ml_team, "spread_side": sp_team, "signed_line": signed_line,
                   "away": away, "home": home})

    known = {t for t in (away, home) if t}
    if ml_team is None or sp_team is None or (known and not {ml_team, sp_team} <= known):
        codes.append(REASON_CONVERGENCE_UNVERIFIABLE)
        detail["unverifiable_reason"] = UNVERIFIABLE_SIDE
        return {"applicable": True, "codes": _order_codes(codes), "warnings": warnings,
                "detail": detail}
    if signed_line is None:
        codes.append(REASON_CONVERGENCE_UNVERIFIABLE)
        detail["unverifiable_reason"] = UNVERIFIABLE_LINE
        return {"applicable": True, "codes": _order_codes(codes), "warnings": warnings,
                "detail": detail}

    mu_ml = implied_margin_from_win_pct(ml_p, used)
    mu_sp = implied_margin_from_cover_pct(cov_p, signed_line, used)
    if mu_ml is None or mu_sp is None:
        codes.append(REASON_CONVERGENCE_UNVERIFIABLE)
        detail["unverifiable_reason"] = UNVERIFIABLE_NO_SIGMA
        return {"applicable": True, "codes": _order_codes(codes), "warnings": warnings,
                "detail": detail}

    aligned = mu_sp if sp_team == ml_team else -mu_sp
    gap = abs(mu_ml - aligned)
    opposite = ((mu_ml > 0) != (aligned > 0)
                and min(abs(mu_ml), abs(aligned)) >= CONVERGENCE_SIGN_MATERIALITY_POINTS)
    detail.update({
        "implied_margin_ml": round(mu_ml, 4),
        "implied_margin_spread": round(mu_sp, 4),
        "implied_margin_spread_aligned_to_ml_side": round(aligned, 4),
        "gap_points": round(gap, 4),
        "opposite_signs": opposite,
        "aligned_by_flip": sp_team != ml_team,
    })
    if opposite or gap > CONVERGENCE_MARGIN_TOLERANCE_POINTS:
        codes.append(REASON_MODEL_CONVERGENCE_FAIL)
    return {"applicable": True, "codes": _order_codes(codes), "warnings": warnings,
            "detail": detail}


# ---------------------------------------------------------------------------------------------
# 6b. PROHIBITED FIGURES.  One rule, one home, applied to EVERY representation of the figure.
# ---------------------------------------------------------------------------------------------
#: CLUSTER G, adversarial review 2026-08-30, and its ROUND-TWO REGRESSION. The owner invariant is
#: "if market_price is null: prohibit edge calculation, prohibit usable_edge calculation" — the
#: CALCULATION, not the LEAN.
#:
#: ROUND ONE. enforce() computed the suppression correctly and then published the enforced row
#: with edge_pp 14.3, usable_edge_pp 6.9 and market_no_vig_cover_pct 50.0 verbatim: compute-then-
#: discard, the sixth independent occurrence of that shape in this repo.
#:
#: ROUND TWO. The fix nulled those three fields in probabilities and the SAME THREE NUMBERS came
#: back as live values under the same key names at row["board_invariants"]["detail"], because
#: check_row records what it judged and enforce() copies dict(rv.detail) onto the enforced row.
#: A figure that is null in one representation and intact in another has been MOVED, not removed.
#: So the prohibition is applied HERE, at the point the verdict is constructed, and every
#: downstream representation inherits it: RowVerdict.detail, RowVerdict.to_dict(), the game and
#: board verdicts that embed it, row["board_invariants"]["detail"] in the enforced copy, and the
#: full verdict dict enforce() returns under "verdict".
#:
#: THE CHOICE, STATED ONCE: the keys are KEPT and their values set to None, never dropped. Three
#: sibling modules read row["probabilities"]["edge_pp"] positively; deleting the key turns a
#: refusal into a KeyError somewhere else, which is a different accident, not a fix.
#:
#: THE THREE BOUNDARIES, STATED RATHER THAN LEFT TO BE DISCOVERED, because a scan that quietly
#: exempts things is how cluster G survived a fix pass:
#:   1. row["board_invariants"]["redacted"] keeps the refused value as a NUMBER. It is the
#:      labelled refusal ledger — {field, was, reason_code, reason} — and it is the ONE place the
#:      figure may exist; harness/test_score_admission.py:1001 binds it by value. "We refused
#:      14.3" is the opposite of publishing 14.3, and the change log carries the same record.
#:   2. A verdict's own detail block records its refusals with the value as a STRING
#:      (`was_repr`), so nothing inside a diagnostics block is a number a consumer could read
#:      back and use.
#:   3. detail["no_vig_pct"] (50.0) and detail["edge_pp_recomputed"] (14.2) STAY. They are the
#:      EVIDENCE for the codes that refused the row — the assumed base itself, and this module's
#:      own recomputation that showed the published 14.3 does not reproduce from the fields
#:      beside it — and both are bound by name in harness/test_score_admission.py:890 and :923.
#:      Neither is the published edge. The two figures the invariant prohibits are gone.
PROHIBITED_EDGE_FIELDS = ("edge_pp", "usable_edge_pp")

#: The same two figures as they appear in a VERDICT's own detail block. Named separately from
#: PROHIBITED_EDGE_FIELDS so a future maintainer cannot close one representation and believe the
#: other followed — which is precisely what happened between round one and round two.
PROHIBITED_DETAIL_FIELDS = ("edge_pp", "usable_edge_pp")

#: The codes that prohibit an edge from EXISTING, as opposed to prohibiting a play. A row with no
#: captured price has nothing for an edge to be an edge AGAINST; a row whose no-vig base was
#: assumed has an edge whose entire denominator was typed in.
EDGE_PROHIBITING_REASONS = frozenset({REASON_MISSING_MARKET_PRICE, REASON_ASSUMED_NO_VIG})

REDACTION_REASON = {
    REASON_MISSING_MARKET_PRICE:
        "REFUSED by board_invariants: entry.price_american is null, so there is no market "
        "probability for this figure to be an edge AGAINST. The owner invariant prohibits the "
        "calculation, so the enforced copy must not carry its result.",
    REASON_ASSUMED_NO_VIG:
        "REFUSED by board_invariants: no price was captured on either side of this market, so "
        "this no-vig probability was assumed and not derived. An assumed base publishes as None.",
}


def _figure_repr(value):
    """A refused figure as TEXT. json.dumps so 14.3 reads back as the string "14.3" and not as a
    number a consumer could pick up and compute with: named in an explanation, never live."""
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)


def _refuse_prohibited_detail(detail, codes):
    """Strip the prohibited derived figures out of a verdict's OWN detail block.

    Returns (detail, refusals). The keys stay and their values become None; each removal is
    recorded as {field, was_repr, reason_code, reason} under detail["prohibited_figures_refused"]
    with the value as a STRING, so the refusal is auditable and the number is not readable.
    """
    prohibiting = [c for c in _order_codes(codes) if c in EDGE_PROHIBITING_REASONS]
    if not prohibiting:
        return detail, []
    code = prohibiting[0]
    refusals = []
    for field in PROHIBITED_DETAIL_FIELDS:
        if detail.get(field) is None:
            continue
        refusals.append({"field": field, "was_repr": _figure_repr(detail[field]),
                         "reason_code": code, "reason": REDACTION_REASON[code]})
        detail[field] = None
    if refusals:
        detail["prohibited_figures_refused"] = refusals
    return detail, refusals


# ---------------------------------------------------------------------------------------------
# 7. VERDICTS.  Plain classes, not dataclasses.
#     `from __future__ import annotations` + @dataclass resolves annotations through
#     sys.modules[cls.__module__], which does not exist when a file is exec'd into a throwaway
#     namespace — which is exactly what a Style-A mutation suite does. score_admission hit this
#     and reported 12/12 KILLED while every mutant was dying of an AttributeError at import, i.e.
#     the suite proved nothing. Plain classes remove the failure mode.
# ---------------------------------------------------------------------------------------------

def _posture_for(codes, decision_in):
    """The most specific diagnosis, most severe first. Decision says what may be done; posture
    says which invariant governs. Both are reported because the owner asked for both spellings."""
    if {REASON_MODEL_CONVERGENCE_FAIL, REASON_SIGMA_DISAGREEMENT,
            REASON_CONVERGENCE_UNVERIFIABLE} & set(codes):
        return DECISION_CONVERGENCE_FAIL
    if {REASON_MISSING_MARKET_PRICE, REASON_ASSUMED_NO_VIG,
            REASON_STALE_FEATURES} & set(codes):
        return DECISION_PASS_DATA_QUALITY
    if REASON_AVAILABILITY_UNKNOWN in codes:
        return DECISION_PASS
    return decision_in


def _suppress(decision_in, codes):
    """Suppression removes an action; it never overwrites a more specific non-action label."""
    if any(c in SUPPRESSING_REASONS for c in codes) and decision_in in PLAY_DECISIONS:
        return DECISION_PASS
    return decision_in


class RowVerdict:
    """One market row's verdict.

    `row_index` is the row's position in game["markets"] and is the ONLY thing enforce() pairs on.
    Cluster H, adversarial review 2026-08-30: enforce() used to key verdicts by market NAME, so a
    game carrying two rows of one market applied BOTH verdicts to the LAST row — the offending row
    kept its LEAN with no codes on it, and a clean row was demoted. A market name is not an
    identity. Added as a trailing keyword with a None default so a caller that predates it still
    constructs; enforce() refuses a verdict that carries None rather than guessing.
    """

    __slots__ = ("event_id", "game", "market", "decision_in", "decision", "signal_decision_in",
                 "signal_decision", "posture", "reason_codes", "warnings", "detail", "row_index",
                 "refused_figures")

    def __init__(self, event_id, game, market, decision_in, signal_decision_in, codes, warnings,
                 detail, row_index=None):
        self.event_id = event_id
        self.game = game
        self.market = market
        self.row_index = row_index
        self.decision_in = decision_in
        self.signal_decision_in = signal_decision_in
        self.reason_codes = _order_codes(codes)
        self.warnings = _order_codes(warnings)
        self.detail = dict(detail or {})
        # CLUSTER G, ROUND TWO. The figure is refused where it is BORN, so every representation
        # downstream inherits the refusal rather than each copy needing its own: the enforced
        # row's diagnostics block republished 14.3 and 6.9 as live values for exactly as long as
        # this was done one copy at a time. Section 6b states the rule and its three boundaries.
        self.detail, self.refused_figures = _refuse_prohibited_detail(self.detail,
                                                                      self.reason_codes)
        self.decision = _suppress(decision_in, self.reason_codes)
        self.signal_decision = _suppress(signal_decision_in, self.reason_codes)
        self.posture = _posture_for(self.reason_codes, self.decision)

    @property
    def suppressed(self):
        return any(c in SUPPRESSING_REASONS for c in self.reason_codes)

    @property
    def changed(self):
        return (self.decision != self.decision_in
                or self.signal_decision != self.signal_decision_in
                or bool(self.reason_codes))

    def __repr__(self):
        return "RowVerdict(%s/%s#%s %s->%s %s)" % (self.game, self.market, self.row_index,
                                                   self.decision_in, self.decision,
                                                   self.reason_codes)

    def to_dict(self):
        return {"schema": "ops.board_invariants.row.v1", "event_id": self.event_id,
                "game": self.game, "market": self.market, "row_index": self.row_index,
                "decision_in": self.decision_in, "decision": self.decision,
                "signal_decision_in": self.signal_decision_in,
                "signal_decision": self.signal_decision, "posture": self.posture,
                "reason_codes": list(self.reason_codes), "warnings": list(self.warnings),
                "suppressed": self.suppressed, "changed": self.changed,
                "refused_figures": [dict(r) for r in self.refused_figures],
                "detail": dict(self.detail)}


class GameVerdict:
    """One game's verdict: the union of its rows plus the cross-market convergence finding."""

    __slots__ = ("event_id", "game", "decision_in", "decision", "posture", "reason_codes",
                 "warnings", "rows", "detail", "rows_supplied")

    def __init__(self, event_id, game, decision_in, rows, detail=None, rows_supplied=None):
        """`rows_supplied` is the length of game["markets"] AS PUBLISHED, before anything is
        filtered, and it is the DENOMINATOR of ROWS_CHECKED.

        Round two of the 2026-08-30 review: the counter read "%d/%d" % (n_rows, n_rows), both
        sides of it the count of rows that parsed, so a board whose rows were all skipped reported
        "0/0" and clean=True. A counter that cannot show a shortfall is not a counter. Added as a
        trailing keyword so a caller that predates it still constructs; when it is not supplied
        the denominator falls back to the rows this verdict holds, which is honest for a
        hand-built verdict and never happens on the check_game path.
        """
        self.event_id = event_id
        self.game = game
        self.decision_in = decision_in
        self.rows = list(rows)
        self.rows_supplied = len(self.rows) if rows_supplied is None else int(rows_supplied)
        codes, warns = [], []
        for r in self.rows:
            codes.extend(r.reason_codes)
            warns.extend(r.warnings)
        self.reason_codes = _order_codes(codes)
        self.warnings = _order_codes(warns)
        self.decision = _suppress(decision_in, self.reason_codes)
        self.posture = _posture_for(self.reason_codes, self.decision)
        self.detail = dict(detail or {})

    @property
    def changed(self):
        return self.decision != self.decision_in or any(r.changed for r in self.rows)

    def __repr__(self):
        return "GameVerdict(%s %s->%s %s)" % (self.game, self.decision_in, self.decision,
                                              self.reason_codes)

    def to_dict(self):
        return {"schema": "ops.board_invariants.game.v1", "event_id": self.event_id,
                "game": self.game, "rows_supplied": self.rows_supplied,
                "decision_in": self.decision_in, "decision": self.decision,
                "posture": self.posture, "reason_codes": list(self.reason_codes),
                "warnings": list(self.warnings), "changed": self.changed,
                "detail": dict(self.detail),
                "rows": [r.to_dict() for r in self.rows]}


class BoardVerdict:
    """The whole card. counters are GENERATED here; none of them is typed."""

    __slots__ = ("source", "games", "counters", "reason_totals", "sigma_register", "detail")

    def __init__(self, source, games, sigma_register, detail=None):
        self.source = source
        self.games = list(games)
        self.sigma_register = dict(sigma_register or {})
        self.detail = dict(detail or {})
        rows = self.rows
        totals = {}
        for r in rows:
            for c in list(r.reason_codes) + list(r.warnings):
                totals[c] = totals.get(c, 0) + 1
        self.reason_totals = dict(sorted(totals.items()))
        n_rows = len(rows)
        # SUPPLIED, not parsed. See GameVerdict.rows_supplied: the old denominator was the
        # numerator, so the re-attack's list-shaped board reported "0/0" and clean=True.
        n_supplied = sum(g.rows_supplied for g in self.games)
        n_games = len(self.games)
        conv = [g for g in self.games if g.detail.get("convergence_applicable")]
        self.counters = {
            "ROWS_CHECKED": "%d/%d" % (n_rows, n_supplied),
            "ROWS_NOT_CHECKED": n_supplied - n_rows,
            "GAMES_CHECKED": "%d/%d" % (n_games, n_games),
            "ROWS_SUPPRESSED": sum(1 for r in rows if r.suppressed),
            "ROWS_DECISION_CHANGED": sum(1 for r in rows if r.decision != r.decision_in),
            "GAMES_DECISION_CHANGED": sum(1 for g in self.games
                                          if g.decision != g.decision_in),
            "ROWS_WITH_NULL_PRICE": sum(
                1 for r in rows if r.detail.get("price_american") is None),
            "ROWS_WITH_EDGE_ON_NULL_PRICE": sum(
                1 for r in rows if REASON_MISSING_MARKET_PRICE in r.reason_codes),
            "CONVERGENCE_CHECKS_RUN": "%d/%d" % (len(conv), n_games),
            "CONVERGENCE_FAILURES": sum(
                1 for g in self.games if REASON_MODEL_CONVERGENCE_FAIL in g.reason_codes),
            "WARNINGS": sum(len(r.warnings) for r in rows),
        }

    @property
    def rows(self):
        return [r for g in self.games for r in g.rows]

    @property
    def clean(self):
        """CLEAN means every supplied row was checked AND none of them had a finding.

        A board that reported clean=True having checked nothing is the whole shape of cluster I,
        and the re-attack produced it again one level down. An unchecked row is an unanswered
        question, not a pass.
        """
        if self.counters.get("ROWS_NOT_CHECKED"):
            return False
        return not any(g.reason_codes for g in self.games)

    def for_game(self, key):
        """Look a game up by event_id or by its 'AWY @ HOM' label. Raises if it is not there —
        a lookup that silently returns None turns an acceptance assertion into a no-op."""
        for g in self.games:
            if key in (g.event_id, g.game):
                return g
        raise BoardInvariantsError("no game %r on this board; have %s"
                                   % (key, [g.game for g in self.games]))

    def to_dict(self):
        return {"schema": "ops.board_invariants.board.v1", "source": self.source,
                "counters": dict(self.counters), "reason_totals": dict(self.reason_totals),
                "clean": self.clean, "sigma_register": dict(self.sigma_register),
                "detail": dict(self.detail),
                "games": [g.to_dict() for g in self.games]}


# ---------------------------------------------------------------------------------------------
# 8. THE CHECKS.
# ---------------------------------------------------------------------------------------------

def load_board(board_json):
    """A board dict from a dict or a path. A path is read; nothing is ever written back."""
    if isinstance(board_json, dict):
        return board_json
    if isinstance(board_json, str):
        with open(board_json) as fh:
            return json.load(fh)
    raise BoardInvariantsError("board must be a dict or a path, got %r"
                               % type(board_json).__name__)


def _games_of(board):
    games = board.get("games")
    if not isinstance(games, list):
        raise BoardInvariantsError(
            "no board['games'] list. This module refuses to go looking: board_shape.py exists "
            "because the CFB board parked its rows at board['rows'] and the NFL board moved them "
            "between 8/27 and 8/28, and a checker that guesses the location silently checks the "
            "wrong thing. Declare the shape or fix the board.")
    return games


def check_row(market_row, *, game, availability_state=None, sigma=None, register=None,
              row_index=None):
    """The four invariants as they apply to ONE market row, plus the two reproducibility warnings.

    Every invariant is evaluated against the row AS PUBLISHED, independently of the others, and
    the results are combined afterwards. Short-circuiting on the first violation is how MIN@ATL
    would have come back with MISSING_MARKET_PRICE alone and the contradiction would have gone
    unrecorded a second time.
    """
    if not isinstance(market_row, dict):
        raise BoardInvariantsError("market row is not a mapping: %r"
                                   % type(market_row).__name__)
    if not isinstance(game, dict):
        # Was a silent `game = {}`. Cluster I: a row judged against an empty game is judged with
        # the convergence question suppressed, and the caller is never told.
        raise BoardInvariantsError(
            "check_row needs the game that owns the row; got %r. The convergence invariant is a "
            "CROSS-market comparison, so a row judged without its game is judged with the 8/30 "
            "defect switched off." % type(game).__name__)
    market = market_row.get("market")
    entry = market_row.get("entry") if isinstance(market_row.get("entry"), dict) else {}
    probs = (market_row.get("probabilities")
             if isinstance(market_row.get("probabilities"), dict) else {})
    dq = (market_row.get("data_quality")
          if isinstance(market_row.get("data_quality"), dict) else {})

    codes, warnings, detail = [], [], {}
    price = _num(entry.get("price_american"))
    edge = _num(probs.get("edge_pp"))
    usable = _num(probs.get("usable_edge_pp"))
    nv_field, no_vig = no_vig_of(market_row)
    mp_field, model_p = model_probability_of(market_row)
    decision_in = market_row.get("decision")
    signal_in = market_row.get("signal_decision")

    play_bearing = decision_in in PLAY_DECISIONS or signal_in in PLAY_DECISIONS
    edge_bearing = edge is not None or usable is not None
    priced_claim = edge_bearing or play_bearing

    detail.update({"price_american": entry.get("price_american"),
                   # Row identity, recorded so enforce() can assert it rather than trust position.
                   "row_index": row_index,
                   "selection": market_row.get("selection"), "line": market_row.get("line"),
                   "edge_pp": edge, "usable_edge_pp": usable,
                   "model_probability_field": mp_field, "model_probability_pct": model_p,
                   "no_vig_field": nv_field, "no_vig_pct": no_vig,
                   "data_quality_status": dq.get("status"),
                   "play_bearing": play_bearing, "edge_bearing": edge_bearing})

    # --- MISSING_MARKET_PRICE ---------------------------------------------------------------
    # A null price on a row that makes no priced claim is not a defect; 39 rows on the 8/30 board
    # are exactly that and flagging them would bury the one that matters.
    if price is None and priced_claim:
        codes.append(REASON_MISSING_MARKET_PRICE)

    # --- MARKET_NO_VIG_ASSUMED_NOT_CAPTURED --------------------------------------------------
    # The rule is "no captured price", not "the number looks round". 50.0 is the tell.
    if price is None and no_vig is not None and priced_claim:
        codes.append(REASON_ASSUMED_NO_VIG)
        detail["no_vig_is_round"] = _is_round_no_vig(no_vig)
    elif price is not None and no_vig is not None:
        # This schema stores ONE side's price, so no no-vig in it can be reproduced by
        # normalising two implied probabilities. Recorded, not suppressed: the base is at least
        # anchored to a price that was actually captured.
        warnings.append(REASON_NO_VIG_ONE_SIDED)

    # --- EDGE_NOT_REPRODUCIBLE_FROM_FIELDS ---------------------------------------------------
    # Counters are generated by code, never typed by hand. MIN@ATL SPREAD_RL publishes 14.3 where
    # 64.2 - 50.0 is 14.2, and its own usable_edge_pp (6.9) agrees with 14.2, not with 14.3.
    if edge is not None and model_p is not None and no_vig is not None:
        recomputed = round(model_p - no_vig, 1)
        detail["edge_pp_recomputed"] = recomputed
        if abs(recomputed - edge) > EDGE_RECOMPUTE_TOLERANCE_PP:
            warnings.append(REASON_EDGE_NOT_REPRODUCIBLE)

    # --- AVAILABILITY_UNKNOWN -----------------------------------------------------------------
    state, why = resolve_availability(availability_state)
    detail["availability_state"] = state
    detail["availability_reason"] = why
    if state == AVAILABILITY_UNKNOWN and play_bearing:
        codes.append(REASON_AVAILABILITY_UNKNOWN)

    # --- STALE_FEATURES -----------------------------------------------------------------------
    if play_bearing and dq.get("status") in SUPPRESSING_DQ_STATUSES:
        codes.append(REASON_STALE_FEATURES)

    # --- MODEL_CONVERGENCE_FAIL ---------------------------------------------------------------
    # The finding attaches to BOTH arms. The ML row is not innocent because it happens to be the
    # arm that said PASS: it is half of the contradiction, and a reader who sees the code only on
    # the spread row will "fix" the spread row.
    if market in CONVERGENCE_MARKETS:
        conv = check_convergence(game, sigma=sigma, register=register)
        if conv:
            codes.extend(conv["codes"])
            warnings.extend(conv["warnings"])
            detail["convergence"] = conv["detail"]

    return RowVerdict(game.get("event_id"), game.get("game"), market, decision_in, signal_in,
                      codes, warnings, detail, row_index)


def check_game(game, *, availability_state=None, sigma=None, register=None):
    """Every market row of one game, plus the cross-market convergence finding.

    The index passed to check_row is the row's position in game["markets"] AS PUBLISHED, so a
    verdict always names the row it was computed from (cluster H).

    CLUSTER I, ONE LEVEL DOWN — the 2026-08-30 re-attack, executed. This function used to FILTER
    non-mapping rows out (`... for i, r in enumerate(_markets_of(game)) if isinstance(r, dict)`)
    while _games_of() and _markets_of() raise for the same class of hazard. The frozen 8/30 board
    with each dict row wrapped in a one-element list therefore came back ROWS_CHECKED "0/0",
    GAMES_CHECKED "19/19", clean=True, reason_totals {}, and enforce() passed every row through
    byte-identical — the acceptance board reporting CLEAN with zero findings while every
    laundered value was republished. A checker that finds nothing to check must SAY SO. The
    refusal names the game and the row index, because "some row somewhere is malformed" is not a
    finding anyone can act on.
    """
    if not isinstance(game, dict):
        raise BoardInvariantsError("game is not a mapping: %r" % type(game).__name__)
    markets = _markets_of(game)
    rows = []
    for i, r in enumerate(markets):
        if not isinstance(r, dict):
            raise BoardInvariantsError(
                "game %r market row %d is not a mapping (it is %s). This row cannot be checked, "
                "and a row that cannot be checked is not a row that passed: skipping it reports "
                "the board CLEAN because nothing was checked, which is the one answer an "
                "invariant checker must never give."
                % (game.get("game"), i, type(r).__name__))
        rows.append(check_row(r, game=game, availability_state=availability_state, sigma=sigma,
                              register=register, row_index=i))
    conv = check_convergence(game, sigma=sigma, register=register)
    state, why = resolve_availability(availability_state)
    detail = {"convergence_applicable": conv is not None,
              "availability_state": state, "availability_reason": why,
              "rows_supplied": len(markets),
              "sport": game.get("sport"), "start_time": game.get("start_time")}
    if conv:
        detail["convergence"] = conv["detail"]
    return GameVerdict(game.get("event_id"), game.get("game"), game.get("game_status"), rows,
                       detail, rows_supplied=len(markets))


def check_board(board_json, *, availability=None, sigma=None, register=None, source=None):
    """Every game on a card. Returns a BoardVerdict; writes nothing, mutates nothing.

    `availability` maps event_id OR the 'AWY @ HOM' label to a state string or an
    {"state","as_of_utc","max_age_hours"} record. Anything not named in it is UNRESOLVED, which
    is UNKNOWN — the 8/30 card carried no availability record at all and its one LEAN sat on a
    game whose own note says "model blind".

    `source` labels the verdict when the caller already read the bytes and is handing over the
    parsed object. It exists so enforce() can read a path ONCE and still record which file the
    verdict came from; without it, "read the file twice" was the only way to keep the label.
    """
    board = load_board(board_json)
    games = _games_of(board)
    reg = register if register is not None else load_sigma_register()
    meta = board.get("card_metadata") if isinstance(board.get("card_metadata"), dict) else {}
    now_utc = meta.get("decision_time")

    avail = availability or {}
    verdicts = []
    for g in games:
        if not isinstance(g, dict):
            raise BoardInvariantsError("board['games'] holds a non-mapping entry: %r"
                                       % type(g).__name__)
        entry = avail.get(g.get("event_id"))
        if entry is None:
            entry = avail.get(g.get("game"))
        if isinstance(entry, dict) and now_utc is not None and "now_utc" not in entry:
            entry = dict(entry, now_utc=now_utc)
        verdicts.append(check_game(g, availability_state=entry, sigma=sigma, register=reg))

    provenance = {"path": SIGMA_REGISTER_PATH,
                  "record_id": reg.get("record_id"),
                  "record_sha256": reg.get("record_sha256"),
                  "measured": measured_sigmas(reg)}
    detail = {"board_version": meta.get("board_version"), "card_version": meta.get("card_version"),
              "decision_time": now_utc,
              "availability_supplied_for": sorted(avail) if avail else [],
              "module": MODULE_ID}
    src = source if source is not None else (
        board_json if isinstance(board_json, str) else meta.get("v1_sha256"))
    return BoardVerdict(src, verdicts, provenance, detail)


# ---------------------------------------------------------------------------------------------
# 9. ENFORCE.  A new structure. R3: frozen stays frozen, and the hash proves it.
# ---------------------------------------------------------------------------------------------

def _canonical_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


#: The only two places a refused figure may still exist AS A NUMBER: the labelled per-row refusal
#: ledger (row["board_invariants"]["redacted"][i].was) and the change-log entry that records the
#: same removal. Both are marked as refusals and carry the reason code; everything else is a live
#: value a consumer could read. Anchored to the ledger's own shape rather than to a key name, so
#: a NEW key called "was" somewhere else does not inherit the exemption.
REFUSAL_LEDGER_PATH_RE = re.compile(r"\.redacted\[\d+\]\.|^\$\.changes\[\d+\]\.from$")


def _number_paths(node, figures, path="$", out=None):
    """Every path in `node` at which one of `figures` survives as a live number.

    Bools are not numbers here: True == 1 in Python and a flag is not a figure.
    """
    if out is None:
        out = []
    if isinstance(node, dict):
        for k in sorted(node, key=str):
            _number_paths(node[k], figures, "%s.%s" % (path, k), out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _number_paths(v, figures, "%s[%d]" % (path, i), out)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        if any(abs(float(node) - float(x)) < 1e-9 for x in figures):
            out.append((path, node))
    return out


def prohibited_figure_leaks(enforced, figures):
    """Every place a prohibited figure survives as a LIVE number in an enforced structure.

    P0-C, the 2026-08-30 re-attack: the round-one fix nulled probabilities.edge_pp and then
    republished 14.3 under the same key name in the diagnostics block, so a fixture that read the
    three keys back saw a refusal while a downstream reader saw the number. Reading keys back
    cannot detect that; walking the whole structure can. Sanitisation means the value is GONE
    from every representation — the row, the diagnostics block, the verdict this module
    serialises — not that the primary field is null while a copy survives elsewhere.
    """
    return [(p, v) for p, v in _number_paths(enforced, figures)
            if not REFUSAL_LEDGER_PATH_RE.search(p)]


#: The prohibition table lives in section 6b, beside the rule it implements. ONE home for "which
#: figures may not exist", applied to the ENFORCED ROW here and to the VERDICT'S OWN DETAIL in
#: RowVerdict — round two of the review found the fix applied to the first and not the second.


def _bind_game_verdict(gv, game, index):
    """Refuse a verdict that does not belong to this game.

    POSITIONAL PAIRING WITH NO IDENTITY ASSERTION, adversarial review 2026-08-30. enforce() pairs
    verdicts to games by position. The R3 sha256 guard proves the INPUT OBJECT was not mutated; it
    cannot notice that the verdict describes a DIFFERENT BOARD — which is owner regression fixture
    7 (same matchup, different date) landing inside this module, and it is exactly what a
    two-reads-of-one-path enforce() invited. Position is how the rows are found; identity is what
    says the find was right.
    """
    if gv.event_id is None and gv.game is None:
        raise BoardInvariantsError(
            "the verdict for board position %d carries neither event_id nor a game label, so it "
            "cannot be bound to a row group by identity. A verdict that can only be located by "
            "counting is a verdict that can be applied to the wrong card." % index)
    if (gv.event_id, gv.game) != (game.get("event_id"), game.get("game")):
        raise BoardInvariantsError(
            "verdict/board identity mismatch at position %d: the verdict describes %r (%s) and "
            "the board holds %r (%s). Verdicts are paired by position and CHECKED by identity; "
            "this is a verdict computed on a different board."
            % (index, gv.game, gv.event_id, game.get("game"), game.get("event_id")))


def _bind_row_verdict(rv, markets, gv):
    """The row this verdict was computed from, located by index and CONFIRMED by identity.

    CLUSTER H: keyed by market NAME, a game with two SPREAD_RL rows applied both verdicts to the
    last one — the offending row kept its LEAN with no codes and a clean row was demoted with an
    empty list. The index is the pairing key; (market, selection, line) is the assertion that the
    index still points where the verdict was computed.
    """
    idx = rv.row_index
    if idx is None:
        raise BoardInvariantsError(
            "the verdict for %s/%s carries no row_index, so it can only be paired by market name "
            "— and a market name is not unique on a board that carries two rows of one market."
            % (gv.game, rv.market))
    if not isinstance(idx, int) or not 0 <= idx < len(markets) \
            or not isinstance(markets[idx], dict):
        raise BoardInvariantsError(
            "the verdict for %s/%s names row index %r, which is not a market row on this game "
            "(it holds %d rows)." % (gv.game, rv.market, idx, len(markets)))
    row = markets[idx]
    have = (row.get("market"), row.get("selection"), row.get("line"))
    want = (rv.market, rv.detail.get("selection"), rv.detail.get("line"))
    if have != want:
        raise BoardInvariantsError(
            "verdict/row identity mismatch at %s row %d: the verdict was computed from "
            "(market, selection, line) %r and the board holds %r. The rows moved under the "
            "verdict." % (gv.game, idx, want, have))
    return row


def _redact_prohibited_fields(row, rv):
    """Remove from the ENFORCED row every figure the fired invariants prohibit (cluster G).

    Returns the removal records. Values become None; the keys stay; nothing is deleted and nothing
    disappears unrecorded.
    """
    probs = row.get("probabilities")
    if not isinstance(probs, dict):
        return []
    codes = set(rv.reason_codes)
    targets = []
    if REASON_MISSING_MARKET_PRICE in codes:
        targets.extend((field, REASON_MISSING_MARKET_PRICE) for field in PROHIBITED_EDGE_FIELDS)
    if REASON_ASSUMED_NO_VIG in codes:
        nv_field = NO_VIG_FIELD.get(rv.market)
        if nv_field:
            targets.append((nv_field, REASON_ASSUMED_NO_VIG))
    removed = []
    for field, code in targets:
        if probs.get(field) is None:
            continue
        removed.append({"field": field, "was": probs[field], "reason_code": code,
                        "reason": REDACTION_REASON[code]})
        probs[field] = None
    return removed


def enforce(board_json, *, availability=None, sigma=None, register=None, verdict=None):
    """Apply the verdicts to a COPY of the board and say exactly what changed.

    Returns {"schema","board","changes","counters","verdict","input_sha256"}. The input object is
    hashed before and after the edit and a mismatch RAISES — R3 is proved on every call rather
    than promised in a comment. Nothing is written to disk here: R6 says a committed artifact is
    append-only, so the caller decides where the enforced copy lands, if anywhere.

    THREE THINGS THE 2026-08-30 REVIEW FOUND HERE, and what each is now:

      * the enforced row still published edge_pp / usable_edge_pp / an assumed no-vig (cluster G).
        Those fields are now None on any row whose codes prohibit them, with the prior value and
        the reason recorded under row["board_invariants"]["redacted"] and in the change log.
      * verdicts were keyed by MARKET NAME (cluster H). They are now bound by row index and
        confirmed by (market, selection, line); an unbindable verdict raises rather than `continue`.
      * a path was read TWICE — once for `original`, once inside check_board — and the verdicts
        were paired to the second read POSITIONALLY with nothing asserting they described the same
        board. The file is now read ONCE and the pairing asserts identity per game.

    AND THE ONE THE RE-ATTACK FOUND (round two): the R3 baseline was taken TOO LATE. load_board()
    returns the CALLER'S dict by reference when a dict is handed in, check_board() then ran on
    that object, and only afterwards was `before` computed — so anything the check mutated was
    folded into the baseline and INPUT_UNCHANGED could not see it. The proof did not cover the
    window it claimed. The hash is taken IMMEDIATELY after load_board and before the check runs,
    so it now spans the whole call, check_board included. S26 is the fixture: it hands enforce a
    check_board that stamps a key on the board and requires the R3 assertion to raise.
    """
    original = load_board(board_json)                       # READ ONCE. The second read was the
    before = _canonical_hash(original)                      # hazard, not the label it preserved.
    v = verdict if verdict is not None else check_board(
        original, availability=availability, sigma=sigma, register=register,
        source=board_json if isinstance(board_json, str) else None)
    new = copy.deepcopy(original)
    changes = []

    games = _games_of(new)
    if len(v.games) != len(games):
        raise BoardInvariantsError(
            "the verdict covers %d games and this board holds %d. Positional pairing over two "
            "different lengths silently misaligns every game after the first difference."
            % (len(v.games), len(games)))

    for index, (gv, g) in enumerate(zip(v.games, games)):
        _bind_game_verdict(gv, g, index)
        if gv.decision != gv.decision_in:
            changes.append({"event_id": gv.event_id, "game": gv.game, "market": None,
                            "row_index": None,
                            "field": "game_status", "from": gv.decision_in, "to": gv.decision,
                            "reason_codes": list(gv.reason_codes)})
            g["game_status"] = gv.decision
        if gv.reason_codes or gv.warnings:
            g["board_invariants"] = {"schema": "ops.board_invariants.game.v1",
                                     "posture": gv.posture,
                                     "reason_codes": list(gv.reason_codes),
                                     "warnings": list(gv.warnings),
                                     "generated_by": MODULE_ID}
        markets = _markets_of(g)
        for rv in gv.rows:
            row = _bind_row_verdict(rv, markets, gv)
            if rv.decision != rv.decision_in:
                changes.append({"event_id": gv.event_id, "game": gv.game, "market": rv.market,
                                "row_index": rv.row_index,
                                "field": "decision", "from": rv.decision_in, "to": rv.decision,
                                "reason_codes": list(rv.reason_codes)})
                row["decision"] = rv.decision
            if rv.signal_decision != rv.signal_decision_in:
                changes.append({"event_id": gv.event_id, "game": gv.game, "market": rv.market,
                                "row_index": rv.row_index,
                                "field": "signal_decision", "from": rv.signal_decision_in,
                                "to": rv.signal_decision,
                                "reason_codes": list(rv.reason_codes)})
                row["signal_decision"] = rv.signal_decision
            redacted = _redact_prohibited_fields(row, rv)
            for rec in redacted:
                changes.append({"event_id": gv.event_id, "game": gv.game, "market": rv.market,
                                "row_index": rv.row_index,
                                "field": "probabilities." + rec["field"],
                                "from": rec["was"], "to": None,
                                "reason_codes": [rec["reason_code"]]})
            if rv.reason_codes or rv.warnings:
                row["reason_codes"] = list(rv.reason_codes)
                row["board_invariants"] = {"schema": "ops.board_invariants.row.v1",
                                           "posture": rv.posture,
                                           "reason_codes": list(rv.reason_codes),
                                           "warnings": list(rv.warnings),
                                           "redacted": redacted,
                                           "detail": dict(rv.detail),
                                           "generated_by": MODULE_ID}

    after = _canonical_hash(original)
    if before != after:
        raise BoardInvariantsError(
            "enforce() mutated its input: sha256 %s -> %s. R3 says frozen stays frozen; this is "
            "the check, not the promise." % (before[:12], after[:12]))

    new["board_invariants"] = {"schema": "ops.board_invariants.board.v1",
                               "generated_by": MODULE_ID,
                               "input_sha256": before,
                               "counters": dict(v.counters),
                               "reason_totals": dict(v.reason_totals),
                               "sigma_register": dict(v.sigma_register)}
    counters = {"CHANGES": len(changes),
                # keyed by ROW, not by (game, market): two rows of one market are two rows.
                "ROWS_CHANGED": len({(c["event_id"], c["market"], c["row_index"])
                                     for c in changes if c["market"]}),
                "GAMES_CHANGED": len({c["event_id"] for c in changes}),
                "FIELDS_REDACTED": sum(1 for c in changes
                                       if str(c["field"]).startswith("probabilities.")),
                "INPUT_UNCHANGED": before == after}
    return {"schema": "ops.board_invariants.enforced.v1", "board": new, "changes": changes,
            "counters": counters, "input_sha256": before, "verdict": v.to_dict()}


# ---------------------------------------------------------------------------------------------
# 10. FIXTURES.  Every synthetic number below is GENERATED from a stated projected margin, so a
#     reader can see what the fixture means without reverse-engineering a percentage. The one
#     real artifact used is the frozen 8/30 card, and it is only ever READ.
# ---------------------------------------------------------------------------------------------

CANONICAL_BOARD_PATH = os.path.join(REPO_ROOT, "cards",
                                    "2026-08-30_pregame_board_v6_canonical.json")

FIXTURE_PROVENANCE = {
    CANONICAL_BOARD_PATH:
        "CAPTURED — the frozen V6 canonical board published 2026-08-30. R3: read only. The "
        "MIN@ATL rows in it are the incident, not a reconstruction of it.",
    SIGMA_REGISTER_PATH:
        "CAPTURED — data/audit/2026-08-30_sigma_provenance_register.json, record "
        "SIGMA-PROVENANCE-2026-08-30. The only artifact that says which sigma is measured.",
    "synthetic:convergence":
        "SYNTHETIC_UNVERIFIED — margin pairs constructed to sit on both sides of each threshold. "
        "The live board offers exactly ONE game where both arms publish a probability, so a suite "
        "built only on it could not tell a working comparison from a comparison that always "
        "agrees. These pairs are the negative controls.",
    "synthetic:availability":
        "SYNTHETIC_UNVERIFIED — the 8/30 card carries no availability record of any kind, so the "
        "stale-report case (owner regression fixture 10) has to be constructed.",
}


def _mkrow(market, **kw):
    """A market row in the V6 card shape. Unspecified fields take the card's null defaults."""
    row = {"market": market,
           "selection": kw.pop("selection", None),
           "line": kw.pop("line", None),
           "entry": {"book": kw.pop("book", "SYNTH_BOOK"),
                     "price_american": kw.pop("price", None),
                     "timestamp": kw.pop("timestamp", None)},
           "probabilities": kw.pop("probabilities", {}),
           "movement": {"classification": None, "confidence": None, "open": None,
                        "current": None, "market": None, "side": None},
           "data_quality": {"status": kw.pop("dq", "OK"), "score": None,
                            "reason": kw.pop("dq_reason", "SYNTHETIC_UNVERIFIED fixture")},
           "decision": kw.pop("decision", "PASS"),
           "note": kw.pop("note", None)}
    row["signal_decision"] = kw.pop("signal", row["decision"])
    row.update(kw)
    return row


def _mkgame(label, rows, status="PASS", event_id=None, sport="WNBA"):
    return {"event_id": event_id or ("synthetic:" + label.replace(" ", "").lower()),
            "game": label, "sport": sport, "start_time": None, "game_status": status,
            "markets": rows, "note": None}


#: A "not given" marker distinct from None, because None is a MEANINGFUL selection value here:
#: it is what the 8/30 board's three other spread rows carry — a signed line with no side at all.
_UNSET = object()


def _pct(mu, sigma, signed_line=0.0):
    """P(this side wins / covers) implied by a projected margin. Generated, then rounded to the
    0.1pp grid the card publishes on, so the fixture carries the same rounding the artifact does."""
    return round(_NORMAL.cdf((mu + signed_line) / sigma) * 100.0, 1)


def convergence_fixture(label, mu_ml, mu_spread, sigma, signed_line, *, ml_team="SYH",
                        spread_team=None, decision="PASS", dq="OK", declare_sigma=True,
                        spread_selection=_UNSET):
    """A two-arm game whose arms project mu_ml and mu_spread points respectively.

    spread_selection defaults to _UNSET rather than None because None is a MEANINGFUL value
    here — it is the 8/30 board's three spread rows that carry a signed line and no side at all.
    """
    spread_team = spread_team or ml_team
    ml = _mkrow(MARKET_ML, selection=ml_team, price=-110, decision=decision, dq=dq,
                probabilities={"model_win_pct": _pct(mu_ml, sigma),
                               "model_loss_pct": round(100.0 - _pct(mu_ml, sigma), 1),
                               "model_draw_pct": None, "market_no_vig_pct": None,
                               "edge_pp": None, "usable_edge_pp": None})
    sel = (("%s %+g" % (spread_team, signed_line)) if spread_selection is _UNSET
           else spread_selection)
    note = ("cover p = Phi(%g/%g)" % (mu_spread + signed_line, sigma)) if declare_sigma else None
    sp = _mkrow(MARKET_SPREAD, selection=sel, line=abs(signed_line), price=-110,
                decision=decision, dq=dq, note=note,
                probabilities={"model_cover_pct": _pct(mu_spread, sigma, signed_line),
                               "model_push_pct": 0.0,
                               "model_noncover_pct": round(
                                   100.0 - _pct(mu_spread, sigma, signed_line), 1),
                               "market_no_vig_cover_pct": None,
                               "edge_pp": None, "usable_edge_pp": None})
    return _mkgame(label, [ml, sp], status=decision)


def acceptance_report():
    """Print the MIN@ATL verdict produced from the frozen 8/30 card. Nothing is written."""
    v = check_board(CANONICAL_BOARD_PATH)
    g = v.for_game("MIN @ ATL")
    required = sa.MIN_ATL_REQUIRED_ROW
    ok = (g.decision == required["decision"]
          and g.reason_codes[:len(required["reason_codes"])] == required["reason_codes"])
    print(json.dumps({"required": required,
                      "produced": {"decision": g.decision, "reason_codes": g.reason_codes},
                      "match": ok,
                      "game": g.to_dict(),
                      "counters": v.counters,
                      "reason_totals": v.reason_totals}, indent=1))
    return 0 if ok else 1


# ---------------------------------------------------------------------------------------------
# 11. SELFTEST.
# ---------------------------------------------------------------------------------------------

def selftest():
    """Each block below is the incident it protects against, not a test number."""
    f = []
    seen = set()

    def harvest(v):
        seen.update(v.reason_codes)
        seen.update(v.warnings)
        return v

    # ---- S0  NO NETWORK.  Needles are assembled at runtime so the scan cannot match itself. ----
    try:
        src0 = open(os.path.abspath(__file__)).read()
        needles = ["requests" + ".get", "requests" + ".post", "urllib" + ".request",
                   "url" + "open", "http" + ".client", "aio" + "http", "socket" + ".socket"]
        hits = [n for n in needles if n in src0]
        if hits:
            f.append("S0 network call sites in a module that declares it reaches nothing: %s"
                     % hits)
        if ALLOW_DIRECT_HTTP is not False:
            f.append("S0 ALLOW_DIRECT_HTTP is not literally False")
    except Exception as e:
        f.append("S0 source scan failed: %r" % (e,))

    # ---- S1  THE SIGMA REGISTER IS READ, AND ITS ABSENCE IS LOUD ------------------------------
    # "if it is missing, FAIL loudly rather than assuming" — a default sigma here would quietly
    # re-legitimise 13.97, the exact value the register exists to demote.
    reg = None
    try:
        reg = load_sigma_register()
        if not reg.get("REGISTER"):
            f.append("S1 register loaded with no REGISTER map")
        if reg.get("record_id") != "SIGMA-PROVENANCE-2026-08-30":
            f.append("S1 register record_id is %r, not the 8/30 record" % reg.get("record_id"))
    except Exception as e:
        f.append("S1 the real sigma register did not load: %r" % (e,))
    missing = os.path.join(REPO_ROOT, "data", "audit", "no_such_sigma_register__fixture.json")
    try:
        load_sigma_register(missing)
        f.append("S1 a missing sigma register did NOT raise — the module assumed a sigma")
    except SigmaRegisterMissing:
        pass
    except Exception as e:
        f.append("S1 a missing register raised %s, not SigmaRegisterMissing — a file error is "
                 "not a refusal" % type(e).__name__)

    # ---- S2  13.97 IS A TOLERANCE, NOT A MEASUREMENT ------------------------------------------
    if reg is not None:
        if sigma_kind(13.97, reg) != "REGISTERED_TOLERANCE":
            f.append("S2 13.97 classified as %r; the register calls it REGISTERED_TOLERANCE"
                     % sigma_kind(13.97, reg))
        if sigma_is_measured(13.97, reg):
            f.append("S2 13.97 read as MEASURED — that is the category error the register names")
        for good in (12.5523, 18.0156, 16.716, 18.385):
            if not sigma_is_measured(good, reg):
                f.append("S2 %s should be MEASURED per the register" % good)
        if sigma_kind(12.384, reg) != "INFERRED":
            f.append("S2 12.3840 should be INFERRED")
        if sigma_kind(99.0, reg) is not None:
            f.append("S2 an unregistered sigma should classify as None, not %r"
                     % sigma_kind(99.0, reg))
        m = measured_sigmas(reg)
        if "12.5523" not in m or m["12.5523"].get("n") != 1721:
            f.append("S2 measured_sigmas lost the n=1721 WNBA margin residual: %r" % (m,))

    # ---- S3  THE ACCEPTANCE.  The frozen 8/30 card, game MIN @ ATL ----------------------------
    board_v = None
    try:
        board_v = check_board(CANONICAL_BOARD_PATH)
    except Exception as e:
        f.append("S3 check_board on the frozen 8/30 card raised %r" % (e,))
    gv = spread = ml = tot = None
    req = sa.MIN_ATL_REQUIRED_ROW
    if board_v is not None:
        try:
            gv = harvest(board_v.for_game("MIN @ ATL"))
        except BoardInvariantsError as e:
            f.append("S3 the frozen card no longer yields a MIN @ ATL verdict: %s" % e)
    if gv is not None:
        for r in gv.rows:
            harvest(r)
        if gv.decision != req["decision"]:
            f.append("S3 MIN@ATL decision is %r, required %r" % (gv.decision, req["decision"]))
        if gv.reason_codes[:3] != req["reason_codes"]:
            f.append("S3 MIN@ATL first three reason codes are %s, required %s"
                     % (gv.reason_codes[:3], req["reason_codes"]))
        if not set(req["reason_codes"]) <= set(gv.reason_codes):
            f.append("S3 MIN@ATL is missing required codes: %s"
                     % sorted(set(req["reason_codes"]) - set(gv.reason_codes)))
        if gv.decision_in != DECISION_LEAN:
            f.append("S3 the fixture stopped being the incident: MIN@ATL game_status was %r, "
                     "expected LEAN" % gv.decision_in)
        # Located by a NAMED lookup, not by [0]: under a mutant that empties the row list this
        # block used to die of an IndexError, which the old suite scored as a kill. Cluster O: an
        # unexpected exception is an ERROR and proves nothing; a named failure proves something.
        def _one_row(market):
            got = [r for r in gv.rows if r.market == market]
            if len(got) != 1:
                f.append("S3 MIN@ATL should carry exactly one %s row; the checker produced %d "
                         "(rows: %s)" % (market, len(got), [r.market for r in gv.rows]))
                return None
            return got[0]

        spread = _one_row(MARKET_SPREAD)
        ml = _one_row(MARKET_ML)
        tot = _one_row(MARKET_TOTALS)
    if spread is not None:
        if spread.decision != DECISION_PASS or spread.decision_in != DECISION_LEAN:
            f.append("S3 the SPREAD_RL row went %r -> %r, expected LEAN -> PASS"
                     % (spread.decision_in, spread.decision))
        if spread.posture != DECISION_CONVERGENCE_FAIL:
            f.append("S3 SPREAD_RL posture is %r, expected CONVERGENCE_FAIL" % spread.posture)
        if not set(req["reason_codes"]) <= set(spread.reason_codes):
            f.append("S3 the SPREAD_RL row itself is missing required codes: %s"
                     % spread.reason_codes)
        if REASON_ASSUMED_NO_VIG not in spread.reason_codes:
            f.append("S3 the assumed 50.0 no-vig was not flagged on the SPREAD_RL row")
        if spread.detail.get("no_vig_is_round") is not True:
            f.append("S3 50.0 was not recognised as a round assumed no-vig")
        if REASON_STALE_FEATURES not in spread.reason_codes:
            f.append("S3 a LEAN on a STALE row was not flagged")
        if REASON_UNMEASURED_SIGMA not in spread.warnings:
            f.append("S3 sigma 13.97 did not raise UNMEASURED_SIGMA")
        if REASON_UNMEASURED_SIGMA in spread.reason_codes:
            f.append("S3 UNMEASURED_SIGMA suppressed on its own; the owner made it a WARNING")
    # The ML arm is half the contradiction and must carry the code too.
    if ml is not None:
        if REASON_MODEL_CONVERGENCE_FAIL not in ml.reason_codes:
            f.append("S3 the ML arm does not carry MODEL_CONVERGENCE_FAIL; a reader who sees the "
                     "code on one arm only will 'fix' that arm")
        if REASON_MISSING_MARKET_PRICE in ml.reason_codes:
            f.append("S3 the ML arm has a captured price (+114) and must not be flagged for one")
    # The TOTALS row has a null price and no priced claim: not a defect.
    if tot is not None:
        if tot.reason_codes:
            f.append("S3 the null-price NO_LINE TOTALS row was flagged %s — the check is not "
                     "discriminating" % tot.reason_codes)
        if tot.decision != "NO_LINE":
            f.append("S3 suppression overwrote NO_LINE with %r; it must only remove an action"
                     % tot.decision)

    # ---- S4  THE MARGINS ARE GENERATED, AND THEY ARE THE ONES THE INCIDENT REPORTS -------------
    if gv is not None:
        d = gv.detail.get("convergence") or {}
        checks = [("implied_margin_ml", -3.65), ("implied_margin_spread", 2.58),
                  ("gap_points", 6.23)]
        for key, want in checks:
            got = d.get(key)
            if got is None or abs(got - want) > 0.01:
                f.append("S4 %s is %r, expected about %s" % (key, got, want))
        if d.get("opposite_signs") is not True:
            f.append("S4 the two arms were not detected as opposite-signed")
        if d.get("sigma") != 13.97 or d.get("sigma_source", "").startswith("note") is False:
            f.append("S4 sigma was not read from the row's own note: %r / %r"
                     % (d.get("sigma"), d.get("sigma_source")))

    # ---- S5..S7  CONVERGENCE, ON BOTH SIDES OF EVERY THRESHOLD --------------------------------
    S = 12.5523      # MEASURED per the register, so these fixtures carry no sigma warning
    cases = [
        # label,            mu_ml, mu_spread, line,  expect MODEL_CONVERGENCE_FAIL
        ("agree",             3.0,   3.0,      2.5,  False),
        ("same sign, gap 8",  1.0,   9.0,      2.5,  True),
        ("opposite, gap 0.7", -0.3,  0.4,      2.5,  True),
        ("opposite, noise",  -0.1,   0.1,      2.5,  False),
        ("gap just inside",   3.0,   3.9,      2.5,  False),
        ("gap just outside",  3.0,   4.2,      2.5,  True),
    ]
    for label, mu_ml, mu_sp, line, want_fail in cases:
        g = convergence_fixture("SYA @ SYH", mu_ml, mu_sp, S, line)
        conv = check_convergence(g, register=reg)
        if conv is None:
            f.append("S5 %s: convergence did not run on a game where both arms publish" % label)
            continue
        got_fail = REASON_MODEL_CONVERGENCE_FAIL in conv["codes"]
        if got_fail != want_fail:
            f.append("S5 %s: fail=%s expected %s (mu_ml=%.4f mu_sp=%.4f gap=%.4f)"
                     % (label, got_fail, want_fail, conv["detail"].get("implied_margin_ml", 0.0),
                        conv["detail"].get("implied_margin_spread_aligned_to_ml_side", 0.0),
                        conv["detail"].get("gap_points", 0.0)))
        if conv["warnings"]:
            f.append("S5 %s: a MEASURED sigma produced warnings %s" % (label, conv["warnings"]))
    # the side flip: the ML arm names the home side, the spread arm names the away side
    flip = convergence_fixture("SYA @ SYH", 3.0, -3.0, S, 3.0, ml_team="SYH", spread_team="SYA")
    conv = check_convergence(flip, register=reg)
    if conv is None or REASON_MODEL_CONVERGENCE_FAIL in conv["codes"]:
        f.append("S6 the side flip was not applied: two arms naming opposite teams and agreeing "
                 "were read as a contradiction (%r)" % (conv and conv["detail"]))
    if conv and conv["detail"].get("aligned_by_flip") is not True:
        f.append("S6 aligned_by_flip was not recorded on a flipped pair")

    # ---- S8  UNVERIFIABLE IS NOT THE SAME AS VERIFIED ------------------------------------------
    unverifiable = [
        ("no sigma declared", convergence_fixture("SYA @ SYH", 3.0, 3.0, S, 2.5,
                                                  decision=DECISION_LEAN, declare_sigma=False),
         UNVERIFIABLE_NO_SIGMA),
        ("spread side unnamed", convergence_fixture("SYA @ SYH", 3.0, 3.0, S, 2.5,
                                                    decision=DECISION_LEAN,
                                                    spread_selection=None),
         UNVERIFIABLE_SIDE),
        ("line carries no sign", convergence_fixture("SYA @ SYH", 3.0, 3.0, S, 2.5,
                                                     decision=DECISION_LEAN,
                                                     spread_selection="SYH"),
         UNVERIFIABLE_LINE),
    ]
    for label, g, why in unverifiable:
        gv = harvest(check_game(g, availability_state="AVAILABLE", register=reg))
        for r in gv.rows:
            harvest(r)
        if REASON_CONVERGENCE_UNVERIFIABLE not in gv.reason_codes:
            f.append("S8 %s: expected CONVERGENCE_UNVERIFIABLE, got %s" % (label, gv.reason_codes))
        if (gv.detail.get("convergence") or {}).get("unverifiable_reason") != why:
            f.append("S8 %s: unverifiable_reason is %r, expected %r"
                     % (label, (gv.detail.get("convergence") or {}).get("unverifiable_reason"),
                        why))
        if gv.decision != DECISION_PASS:
            f.append("S8 %s: a LEAN survived an unverifiable coherence claim (decision %r)"
                     % (label, gv.decision))

    # ---- S9  TWO SIGMAS IN ONE GAME ARE NOT ONE DISTRIBUTION ----------------------------------
    two = convergence_fixture("SYA @ SYH", 3.0, 3.0, S, 2.5, decision=DECISION_LEAN)
    two["markets"][0]["note"] = "p = Phi(3.0/12.5523)"
    two["markets"][1]["note"] = "cover p = Phi(5.5/13.97)"
    gv = harvest(check_game(two, availability_state="AVAILABLE", register=reg))
    for r in gv.rows:
        harvest(r)
    if REASON_SIGMA_DISAGREEMENT not in gv.reason_codes:
        f.append("S9 two arms declaring 12.5523 and 13.97 were accepted as one distribution: %s"
                 % gv.reason_codes)
    if gv.decision != DECISION_PASS:
        f.append("S9 a LEAN survived a sigma disagreement (decision %r)" % gv.decision)

    # ---- S10  AVAILABILITY: SILENCE IS UNKNOWN, AND SO IS A STALE ANSWER -----------------------
    # Owner regression fixture 10: a stale injury report exceeding the freshness deadline.
    avail_row = _mkrow(MARKET_ML, selection="SYH", price=-110, decision=DECISION_LEAN,
                       probabilities={"model_win_pct": 60.0, "model_loss_pct": 40.0})
    avail_game = _mkgame("SYA @ SYH", [avail_row], status=DECISION_LEAN)
    avail_cases = [
        ("not supplied", None, True, AVAILABILITY_NOT_SUPPLIED),
        ("explicit UNKNOWN", AVAILABILITY_UNKNOWN, True, AVAILABILITY_EXPLICIT_UNKNOWN),
        ("resolved and fresh",
         {"state": "AVAILABLE", "as_of_utc": "2026-08-30T06:00:00Z",
          "now_utc": "2026-08-30T12:00:00Z"}, False, AVAILABILITY_RESOLVED),
        ("resolved but 48h old",
         {"state": "AVAILABLE", "as_of_utc": "2026-08-28T12:00:00Z",
          "now_utc": "2026-08-30T12:00:00Z"}, True, AVAILABILITY_STALE),
        ("stale under a widened per-entry limit",
         {"state": "AVAILABLE", "as_of_utc": "2026-08-28T12:00:00Z",
          "now_utc": "2026-08-30T12:00:00Z", "max_age_hours": 72.0}, False,
         AVAILABILITY_RESOLVED),
    ]
    for label, av, want_code, want_why in avail_cases:
        rv = harvest(check_row(avail_row, game=avail_game, availability_state=av, register=reg))
        got = REASON_AVAILABILITY_UNKNOWN in rv.reason_codes
        if got != want_code:
            f.append("S10 %s: AVAILABILITY_UNKNOWN=%s expected %s" % (label, got, want_code))
        if rv.detail.get("availability_reason") != want_why:
            f.append("S10 %s: reason %r expected %r"
                     % (label, rv.detail.get("availability_reason"), want_why))
        if want_code and rv.decision != DECISION_PASS:
            f.append("S10 %s: a LEAN survived unknown availability" % label)

    # ---- S11  STALE / CAP FEATURES UNDER A PLAY -----------------------------------------------
    for dq, decision, want in (("STALE", DECISION_LEAN, True), ("CAP", DECISION_LEAN, True),
                               ("OK", DECISION_LEAN, False), ("STALE", "PASS", False),
                               ("STALE", "NO_LINE", False)):
        row = _mkrow(MARKET_ML, selection="SYH", price=-110, decision=decision, dq=dq,
                     probabilities={"model_win_pct": 60.0})
        game = _mkgame("SYA @ SYH", [row], status=decision)
        rv = harvest(check_row(row, game=game, availability_state="AVAILABLE", register=reg))
        if (REASON_STALE_FEATURES in rv.reason_codes) != want:
            f.append("S11 dq=%s decision=%s: STALE_FEATURES=%s expected %s"
                     % (dq, decision, REASON_STALE_FEATURES in rv.reason_codes, want))

    # ---- S12  NULL PRICE, ASSUMED NO-VIG, AND EDGE REPRODUCIBILITY ----------------------------
    priced = _mkrow(MARKET_SPREAD, selection="SYH +2.5", line=2.5, price=-110,
                    decision=DECISION_LEAN,
                    probabilities={"model_cover_pct": 64.2, "market_no_vig_cover_pct": 52.0,
                                   "edge_pp": 12.2, "usable_edge_pp": 6.0})
    unpriced = _mkrow(MARKET_SPREAD, selection="SYH +2.5", line=2.5, price=None,
                      decision=DECISION_LEAN,
                      probabilities={"model_cover_pct": 64.2, "market_no_vig_cover_pct": 50.0,
                                     "edge_pp": 14.2, "usable_edge_pp": 6.9})
    quiet = _mkrow(MARKET_TOTALS, line=176.5, price=None, decision="NO_LINE",
                   probabilities={"model_over_pct": None, "model_push_pct": 0.0})
    bad_edge = _mkrow(MARKET_SPREAD, selection="SYH +2.5", line=2.5, price=-110,
                      decision="PASS",
                      probabilities={"model_cover_pct": 64.2, "market_no_vig_cover_pct": 50.0,
                                     "edge_pp": 14.3, "usable_edge_pp": 6.9})
    pg = _mkgame("SYA @ SYH", [priced, unpriced, quiet, bad_edge])
    rv_priced = harvest(check_row(priced, game=pg, availability_state="AVAILABLE", register=reg))
    rv_unpriced = harvest(check_row(unpriced, game=pg, availability_state="AVAILABLE",
                                    register=reg))
    rv_quiet = harvest(check_row(quiet, game=pg, availability_state="AVAILABLE", register=reg))
    rv_bad = harvest(check_row(bad_edge, game=pg, availability_state="AVAILABLE", register=reg))
    if REASON_MISSING_MARKET_PRICE in rv_priced.reason_codes:
        f.append("S12 a row with a captured price was flagged for a missing one")
    if REASON_NO_VIG_ONE_SIDED not in rv_priced.warnings:
        f.append("S12 a no-vig published from a one-sided price was not recorded")
    if REASON_MISSING_MARKET_PRICE not in rv_unpriced.reason_codes:
        f.append("S12 an edge on a null price was not refused")
    if REASON_ASSUMED_NO_VIG not in rv_unpriced.reason_codes:
        f.append("S12 an assumed no-vig on a null price was not flagged")
    if rv_unpriced.decision != DECISION_PASS or rv_unpriced.posture != DECISION_PASS_DATA_QUALITY:
        f.append("S12 null-price row came out %r/%r, expected PASS/PASS_DATA_QUALITY"
                 % (rv_unpriced.decision, rv_unpriced.posture))
    if rv_quiet.reason_codes:
        f.append("S12 a NO_LINE row with no price and no edge was flagged %s"
                 % rv_quiet.reason_codes)
    if REASON_EDGE_NOT_REPRODUCIBLE not in rv_bad.warnings:
        f.append("S12 edge_pp 14.3 against 64.2 - 50.0 = 14.2 was not caught")
    if REASON_EDGE_NOT_REPRODUCIBLE in rv_priced.warnings:
        f.append("S12 a reproducible edge (64.2 - 52.0 = 12.2) was flagged anyway")

    # ---- S13  ENFORCE DOES NOT MUTATE, AND SAYS WHAT IT CHANGED --------------------------------
    try:
        raw = open(CANONICAL_BOARD_PATH, "rb").read()
        disk_before = hashlib.sha256(raw).hexdigest()
        loaded = json.loads(raw.decode())
        deep_before = _canonical_hash(loaded)
        out = enforce(loaded)
        if _canonical_hash(loaded) != deep_before:
            f.append("S13 enforce() mutated the board it was handed (R3)")
        if open(CANONICAL_BOARD_PATH, "rb").read() != raw:
            f.append("S13 the frozen card on disk changed; sha256 was %s" % disk_before[:12])
        eb = out["board"]
        emin = [g for g in eb["games"] if g["game"] == "MIN @ ATL"][0]
        espread = [m for m in emin["markets"] if m["market"] == MARKET_SPREAD][0]
        if emin["game_status"] != DECISION_PASS:
            f.append("S13 enforced game_status is %r, expected PASS" % emin["game_status"])
        if espread["decision"] != DECISION_PASS:
            f.append("S13 enforced SPREAD_RL decision is %r" % espread["decision"])
        if espread["signal_decision"] != DECISION_PASS:
            f.append("S13 signal_decision LEAN survived enforcement: %r"
                     % espread["signal_decision"])
        if espread.get("reason_codes", [])[:3] != sa.MIN_ATL_REQUIRED_ROW["reason_codes"]:
            f.append("S13 enforced row reason_codes are %s" % espread.get("reason_codes"))
        if loaded["games"][0]["markets"][1]["decision"] != DECISION_LEAN:
            f.append("S13 the input row's decision was changed in place")
        if not out["changes"] or out["counters"]["INPUT_UNCHANGED"] is not True:
            f.append("S13 enforce reported no changes on a board that has one: %r"
                     % out["counters"])
        fields = {(c["market"], c["field"]) for c in out["changes"]}
        for want in ((None, "game_status"), (MARKET_SPREAD, "decision"),
                     (MARKET_SPREAD, "signal_decision")):
            if want not in fields:
                f.append("S13 change log does not name %r" % (want,))
    except Exception as e:
        f.append("S13 enforce raised %r" % (e,))

    # ---- S18  THE ENFORCED ROW DOES NOT REPUBLISH THE EDGE (cluster G) ------------------------
    # The suppression was computed correctly and discarded on the write path: the enforced copy
    # carried edge_pp 14.3, usable_edge_pp 6.9 and the assumed no-vig 50.0 verbatim. The owner
    # invariant prohibits the CALCULATION, so the calculation's result must not survive the gate.
    try:
        out18 = enforce(CANONICAL_BOARD_PATH)
        emin18 = [g for g in out18["board"]["games"] if g.get("game") == "MIN @ ATL"]
        if len(emin18) != 1:
            f.append("S18 the enforced copy holds %d games labelled MIN @ ATL" % len(emin18))
        else:
            rows18 = {m.get("market"): m for m in emin18[0]["markets"]}
            esp = rows18.get(MARKET_SPREAD, {})
            eprobs = esp.get("probabilities") or {}
            for field, was in (("edge_pp", 14.3), ("usable_edge_pp", 6.9),
                               ("market_no_vig_cover_pct", 50.0)):
                if eprobs.get(field) is not None:
                    f.append("S18 the enforced SPREAD_RL row still publishes %s=%r on a row with "
                             "no captured price; the frozen card said %r and the gate changed "
                             "nothing" % (field, eprobs.get(field), was))
            red = {r.get("field"): r
                   for r in (esp.get("board_invariants") or {}).get("redacted") or []}
            for field, was, code in (("edge_pp", 14.3, REASON_MISSING_MARKET_PRICE),
                                     ("usable_edge_pp", 6.9, REASON_MISSING_MARKET_PRICE),
                                     ("market_no_vig_cover_pct", 50.0, REASON_ASSUMED_NO_VIG)):
                rec = red.get(field)
                if rec is None:
                    f.append("S18 %s was removed with no stated reason; a value that vanishes "
                             "without a record is not a refusal" % field)
                    continue
                if rec.get("was") != was:
                    f.append("S18 the removal record for %s says it was %r; the frozen card says "
                             "%r" % (field, rec.get("was"), was))
                if rec.get("reason_code") != code or not rec.get("reason"):
                    f.append("S18 the removal of %s cites %r, expected %r with a stated reason"
                             % (field, rec.get("reason_code"), code))
            named18 = {(c["market"], c["field"]) for c in out18["changes"]}
            for want in ((MARKET_SPREAD, "probabilities.edge_pp"),
                         (MARKET_SPREAD, "probabilities.usable_edge_pp"),
                         (MARKET_SPREAD, "probabilities.market_no_vig_cover_pct")):
                if want not in named18:
                    f.append("S18 the change log does not name the removal %r" % (want,))
            if out18["counters"].get("FIELDS_REDACTED") != 3:
                f.append("S18 FIELDS_REDACTED is %r; the 8/30 card carries exactly three "
                         "prohibited figures" % out18["counters"].get("FIELDS_REDACTED"))
            # Redaction is driven by the codes that fired, not by the row's neighbours: the ML row
            # has a captured price (+114) and keeps its edge.
            eml18 = (rows18.get(MARKET_ML, {}).get("probabilities") or {})
            if eml18.get("edge_pp") != -5.2 or eml18.get("market_no_vig_pct") != 44.9:
                f.append("S18 the priced ML row lost figures it is entitled to keep: edge %r, "
                         "no-vig %r (frozen card: -5.2 and 44.9)"
                         % (eml18.get("edge_pp"), eml18.get("market_no_vig_pct")))
    except Exception as e:
        f.append("S18 the enforced-copy redaction check raised %r" % (e,))

    # ---- S19  TWO ROWS OF ONE MARKET IN ONE GAME (cluster H) ----------------------------------
    # Keyed by market NAME, both verdicts landed on the LAST row: the offending row kept its LEAN
    # with no reason codes and the clean row was demoted. A market name is not an identity.
    dup_bad = _mkrow(MARKET_SPREAD, selection="SYH +2.5", line=2.5, price=None,
                     decision=DECISION_LEAN,
                     probabilities={"model_cover_pct": 64.2, "market_no_vig_cover_pct": 50.0,
                                    "edge_pp": 14.2, "usable_edge_pp": 6.9})
    dup_ok = _mkrow(MARKET_SPREAD, selection="SYA -7.5", line=7.5, price=-110,
                    decision=DECISION_LEAN,
                    probabilities={"model_cover_pct": 55.0, "edge_pp": None,
                                   "usable_edge_pp": None})
    dup_board = {"games": [_mkgame("SYA @ SYH", [dup_bad, dup_ok], status=DECISION_LEAN,
                                   event_id="synthetic:two-spread-rows")]}
    try:
        gv19 = harvest(check_game(dup_board["games"][0], availability_state="AVAILABLE",
                                  register=reg))
        for r in gv19.rows:
            harvest(r)
        if [r.row_index for r in gv19.rows] != [0, 1]:
            f.append("S19 the two SPREAD_RL verdicts carry row indices %r; without a unique key "
                     "they cannot be told apart" % [r.row_index for r in gv19.rows])
        out19 = enforce(dup_board, availability={"synthetic:two-spread-rows": "AVAILABLE"},
                        register=reg)
        m19 = out19["board"]["games"][0]["markets"]
        if m19[0].get("decision") != DECISION_PASS:
            f.append("S19 the OFFENDING row (index 0, no price, edge 14.2) came out %r; its own "
                     "verdict was applied to the other row" % m19[0].get("decision"))
        if REASON_MISSING_MARKET_PRICE not in (m19[0].get("reason_codes") or []):
            f.append("S19 the offending row carries reason codes %r; the codes went to the wrong "
                     "row" % (m19[0].get("reason_codes"),))
        if (m19[0].get("probabilities") or {}).get("edge_pp") is not None:
            f.append("S19 the offending row kept its unpriced edge %r"
                     % (m19[0]["probabilities"]["edge_pp"],))
        if m19[1].get("decision") != DECISION_LEAN or m19[1].get("signal_decision") \
                != DECISION_LEAN:
            f.append("S19 the CLEAN row (index 1, priced -110, no edge) was demoted to %r/%r"
                     % (m19[1].get("decision"), m19[1].get("signal_decision")))
        if "reason_codes" in m19[1] or "board_invariants" in m19[1]:
            f.append("S19 the clean row was annotated with %r / %r — a demotion carrying an empty "
                     "list is still a demotion"
                     % (m19[1].get("reason_codes"), m19[1].get("board_invariants")))
        if (m19[1].get("probabilities") or {}).get("model_cover_pct") != 55.0:
            f.append("S19 the clean row's probabilities were edited: %r"
                     % (m19[1].get("probabilities"),))
        if out19["counters"]["ROWS_CHANGED"] != 1:
            f.append("S19 ROWS_CHANGED is %r; exactly one of the two rows changed"
                     % out19["counters"]["ROWS_CHANGED"])
    except Exception as e:
        f.append("S19 the two-rows-of-one-market fixture raised %r" % (e,))

    # ---- S20  ROWS THAT ARE NOT UNDER "markets" ARE A REFUSAL, NOT A CLEAN BOARD (cluster I) ---
    # _markets_of returned [] where _games_of raises for the same hazard, so a board carrying its
    # rows under any other key came back CLEAN with every LEAN intact and zero enforced changes.
    for label20, bad_game in (
            ("rows parked under 'rows'",
             {"event_id": "synthetic:wrong-key", "game": "SYA @ SYH",
              "rows": [_mkrow(MARKET_ML, selection="SYH", price=None, decision=DECISION_LEAN,
                              probabilities={"model_win_pct": 60.0, "edge_pp": 9.0})]}),
            ("markets is a mapping, not a list",
             {"event_id": "synthetic:wrong-shape", "game": "SYA @ SYH",
              "markets": {MARKET_ML: {}}})):
        try:
            v20 = check_board({"games": [bad_game]}, register=reg)
            f.append("S20 %s: the board was checked anyway and reported clean=%r with counters "
                     "%r — a checker that found nothing to check must say so"
                     % (label20, v20.clean, v20.counters.get("ROWS_CHECKED")))
        except BoardInvariantsError:
            pass
        except Exception as e:
            f.append("S20 %s: raised %s, not BoardInvariantsError" % (label20, type(e).__name__))

    # ---- S21  A VERDICT BELONGS TO ONE BOARD (owner regression fixture 7, inside this module) --
    # Verdicts are paired to games POSITIONALLY. The R3 hash proves the input object was not
    # mutated; it cannot notice that the verdict describes a different card.
    def _mk_one_game_board(event_id, label):
        return {"games": [_mkgame(label,
                                  [_mkrow(MARKET_ML, selection="SYH", price=-110,
                                          decision=DECISION_LEAN,
                                          probabilities={"model_win_pct": 60.0})],
                                  status=DECISION_LEAN, event_id=event_id)]}

    board_a = _mk_one_game_board("synthetic:board-a", "SYA @ SYH")
    board_b = _mk_one_game_board("synthetic:board-b", "SYB @ SYC")
    board_c = _mk_one_game_board("synthetic:board-a", "SYA @ SYH")
    board_c["games"][0]["markets"][0]["selection"] = "SYA"
    try:
        verdict_a = check_board(board_a, register=reg)
    except Exception as e:
        verdict_a = None
        f.append("S21 check_board on the one-game fixture raised %r" % (e,))
    if verdict_a is not None:
        for label21, target in (("a different board", board_b),
                                ("the same board with the row's side changed", board_c)):
            try:
                enforce(target, verdict=verdict_a, register=reg)
                f.append("S21 a verdict computed on board-a was applied to %s without complaint; "
                         "positional pairing cannot tell them apart" % label21)
            except BoardInvariantsError:
                pass
            except Exception as e:
                f.append("S21 pairing a verdict to %s raised %s, not BoardInvariantsError"
                         % (label21, type(e).__name__))
        # A verdict SHORTER than the board: zip() truncates in silence, so every game after the
        # verdict's last one ships unenforced while the counters report a clean run.
        board_d = _mk_one_game_board("synthetic:board-a", "SYA @ SYH")
        board_d["games"].append(copy.deepcopy(board_b["games"][0]))
        try:
            enforce(board_d, verdict=verdict_a, register=reg)
            f.append("S21 a one-game verdict was applied to a two-game board without complaint; "
                     "the second game shipped unenforced and nothing said so")
        except BoardInvariantsError:
            pass
        except Exception as e:
            f.append("S21 a short verdict raised %s, not BoardInvariantsError"
                     % type(e).__name__)
        try:
            enforce(board_a, verdict=verdict_a, register=reg)
        except Exception as e:
            f.append("S21 enforce refused a verdict that belongs to its own board: %r" % (e,))

    # ---- S22  THE PATH IS READ ONCE ------------------------------------------------------------
    # Two reads of one filename are two observations of possibly different bytes (the mutable
    # archive hazard, stated in the contract), and the verdicts from read #1 were then applied
    # positionally to read #2.
    _g22 = globals()
    _real_load = _g22["load_board"]
    _disk_reads = []

    def _counting_load_board(board_json, _real=_real_load, _seen=_disk_reads):
        if isinstance(board_json, str):
            _seen.append(board_json)
        return _real(board_json)

    _g22["load_board"] = _counting_load_board
    try:
        enforce(CANONICAL_BOARD_PATH)
    except Exception as e:
        f.append("S22 enforce(path) raised %r" % (e,))
    finally:
        _g22["load_board"] = _real_load
    if len(_disk_reads) != 1:
        f.append("S22 enforce(path) read the card from disk %d times, expected 1: a verdict from "
                 "one read applied to another read of the same filename is exactly the mutable-"
                 "archive hazard" % len(_disk_reads))

    # ---- S23  THE REFUSED FIGURE DOES NOT EXIST ANYWHERE ELSE (cluster G, round two) ---------
    # Round one nulled probabilities.edge_pp and the round-two re-attack found the SAME NUMBERS
    # republished as live values at row["board_invariants"]["detail"] — 14.3, 6.9 and 50.0 — with
    # no refusal marker on them. The guarding fixtures read the three keys back, which cannot see
    # a copy under a different path. This one walks the ENTIRE enforced structure instead.
    try:
        frozen23 = json.load(open(CANONICAL_BOARD_PATH))
        spread23 = [m for g23 in frozen23["games"] if g23.get("game") == "MIN @ ATL"
                    for m in g23["markets"] if m.get("market") == MARKET_SPREAD]
        if len(spread23) != 1:
            f.append("S23 the frozen card no longer carries exactly one MIN@ATL SPREAD_RL row "
                     "(found %d)" % len(spread23))
        else:
            # R1: the needles are READ from the frozen artifact, never typed into this fixture.
            figures23 = [spread23[0]["probabilities"][name] for name in PROHIBITED_EDGE_FIELDS]
            if sorted(figures23) != [6.9, 14.3]:
                f.append("S23 the frozen card's prohibited pair reads %r; the incident published "
                         "14.3 and 6.9 and this fixture is pointed at the wrong bytes" % figures23)
            out23 = enforce(CANONICAL_BOARD_PATH)
            leaks23 = prohibited_figure_leaks(out23, figures23)
            if leaks23:
                f.append("S23 the enforced structure still publishes a prohibited figure as a "
                         "LIVE number at %r. Nulled in one representation and republished in "
                         "another is cluster G MOVED, not removed." % (leaks23[:6],))
            # ... and the scan is not vacuous: the labelled refusal ledger must still hold them.
            if len(_number_paths(out23, figures23)) < 2:
                f.append("S23 neither prohibited figure appears anywhere in the enforced "
                         "structure, not even in the refusal ledger — this scan is asserting the "
                         "absence of something that was never there")
            # Every numeric "from" in the change log is a REDACTION record, or the exemption the
            # scan grants to $.changes[i].from would launder an ordinary field.
            bad_from23 = [c for c in out23["changes"]
                          if isinstance(c.get("from"), (int, float))
                          and not isinstance(c.get("from"), bool)
                          and not (str(c.get("field") or "").startswith("probabilities.")
                                   and c.get("to") is None)]
            if bad_from23:
                f.append("S23 the change log carries a numeric 'from' that is not a redaction "
                         "record: %r" % (bad_from23[:3],))
            # The three representations the owner named, asserted one at a time as well, so a
            # failure says WHICH copy leaked rather than only that one did.
            erow23 = [m for g23 in out23["board"]["games"] if g23.get("game") == "MIN @ ATL"
                      for m in (g23.get("markets") or []) if m.get("market") == MARKET_SPREAD]
            if len(erow23) != 1:
                f.append("S23 the enforced copy holds %d MIN@ATL SPREAD_RL rows" % len(erow23))
            else:
                audit23 = erow23[0].get("board_invariants") or {}
                det23 = audit23.get("detail") or {}
                for name in PROHIBITED_DETAIL_FIELDS:
                    if (erow23[0].get("probabilities") or {}).get(name) is not None:
                        f.append("S23 the enforced ROW republishes probabilities.%s" % name)
                    if det23.get(name) is not None:
                        f.append("S23 board_invariants.detail republishes %s=%r as a live value; "
                                 "the row is null and the diagnostics block is not, which is the "
                                 "same number reachable by a second path"
                                 % (name, det23.get(name)))
                refused23 = {r.get("field"): r
                             for r in (det23.get("prohibited_figures_refused") or [])}
                for name in PROHIBITED_DETAIL_FIELDS:
                    rec23 = refused23.get(name)
                    if rec23 is None:
                        f.append("S23 detail.%s was emptied with no record; a value that vanishes "
                                 "unrecorded is not a refusal" % name)
                    elif not isinstance(rec23.get("was_repr"), str) or not rec23.get("reason"):
                        f.append("S23 the refusal of detail.%s does not name what it removed as "
                                 "text: %r" % (name, rec23))
                # The VERDICT this module serialises is a representation too: enforce() returns
                # it, and the round-two finding was about a copy, not about the row.
                vrows23 = [r for g23 in (out23["verdict"].get("games") or [])
                           for r in (g23.get("rows") or [])
                           if g23.get("game") == "MIN @ ATL" and r.get("market") == MARKET_SPREAD]
                for r23 in vrows23:
                    for name in PROHIBITED_DETAIL_FIELDS:
                        if (r23.get("detail") or {}).get(name) is not None:
                            f.append("S23 the serialised verdict republishes detail.%s" % name)
                if out23["board"]["board_invariants"].get("generated_by") != MODULE_ID:
                    f.append("S23 the enforced board is stamped %r, not %r"
                             % (out23["board"]["board_invariants"].get("generated_by"), MODULE_ID))
            # The object three sibling modules receive, not only the serialised copy.
            rv23 = check_row(spread23[0], game=dict(spread23[0], markets=[spread23[0]],
                                                    event_id="synthetic:s23", game="MIN @ ATL"),
                             register=reg)
            for name in PROHIBITED_DETAIL_FIELDS:
                if rv23.detail.get(name) is not None:
                    f.append("S23 check_row's own verdict detail carries %s=%r on a row it "
                             "refused for a missing price" % (name, rv23.detail.get(name)))
            # And the evidence for the codes SURVIVES: a scan that empties the diagnosis is not a
            # stricter fix, it is a fix that destroys the reason the row was refused.
            if rv23.detail.get("no_vig_pct") != 50.0 or rv23.detail.get("edge_pp_recomputed") \
                    != 14.2 or rv23.detail.get("edge_bearing") is not True:
                f.append("S23 the refusal took the EVIDENCE with it: no_vig_pct %r, "
                         "edge_pp_recomputed %r, edge_bearing %r — the assumed base and this "
                         "module's own recomputation are why the row was refused"
                         % (rv23.detail.get("no_vig_pct"), rv23.detail.get("edge_pp_recomputed"),
                            rv23.detail.get("edge_bearing")))
    except Exception as e:
        f.append("S23 the recursive prohibited-figure scan raised %r" % (e,))

    # ---- S24  A MALFORMED ROW FAILS THE BOARD; IT DOES NOT MAKE IT CLEAN (cluster I, one down) -
    # EXECUTED in the 2026-08-30 re-attack: the acceptance board with every dict row wrapped in a
    # one-element list reported ROWS_CHECKED "0/0", GAMES_CHECKED "19/19", clean=True and
    # reason_totals {}, while enforce() passed all 57 rows through byte-identical.
    listed24 = copy.deepcopy(json.load(open(CANONICAL_BOARD_PATH)))
    for g24 in listed24["games"]:
        g24["markets"] = [[r] for r in g24["markets"]]
    bare24 = {"games": [_mkgame("SYA @ SYH", ["SPREAD_RL"], event_id="synthetic:bare-row")]}
    for label24, board24 in (("every row wrapped in a one-element list", listed24),
                             ("a market row that is a bare string", bare24)):
        try:
            v24 = check_board(board24, register=reg)
            f.append("S24 %s: check_board reported clean=%r with ROWS_CHECKED %r and %d reason "
                     "totals instead of refusing. A board whose rows cannot be checked is not a "
                     "board that passed."
                     % (label24, v24.clean, v24.counters.get("ROWS_CHECKED"),
                        len(v24.reason_totals)))
        except BoardInvariantsError:
            pass
        except Exception as e:
            f.append("S24 %s: check_board raised %s, not BoardInvariantsError"
                     % (label24, type(e).__name__))
        try:
            enforce(board24, register=reg)
            f.append("S24 %s: enforce() ran on a board whose rows it could not check, and every "
                     "laundered value went out with it" % label24)
        except BoardInvariantsError:
            pass
        except Exception as e:
            f.append("S24 %s: enforce raised %s, not BoardInvariantsError"
                     % (label24, type(e).__name__))

    # ---- S25  ROWS_CHECKED COUNTS THE ROWS THAT WERE SUPPLIED ---------------------------------
    # "%d/%d" % (n_rows, n_rows) is a counter that cannot report a shortfall, because both sides
    # of it are the count of rows that survived. The denominator is the published list's length.
    try:
        g25 = _mkgame("SYA @ SYH", [_mkrow(MARKET_ML, selection="SYH", price=-110)],
                      event_id="synthetic:counter")
        gv25 = check_game(g25, availability_state="AVAILABLE", register=reg)
        if gv25.rows_supplied != 1:
            f.append("S25 check_game recorded %r supplied rows for a one-row game"
                     % gv25.rows_supplied)
        short25 = GameVerdict(gv25.event_id, gv25.game, gv25.decision_in, gv25.rows,
                              dict(gv25.detail), rows_supplied=3)
        bv25 = BoardVerdict("synthetic:short-rows", [short25], reg)
        if bv25.counters.get("ROWS_CHECKED") != "1/3":
            f.append("S25 ROWS_CHECKED reads %r where one row of three supplied was checked; a "
                     "denominator that IS the numerator can never show a gap"
                     % bv25.counters.get("ROWS_CHECKED"))
        if bv25.counters.get("ROWS_NOT_CHECKED") != 2:
            f.append("S25 ROWS_NOT_CHECKED is %r, expected 2"
                     % bv25.counters.get("ROWS_NOT_CHECKED"))
        if bv25.clean:
            f.append("S25 a board with two unchecked rows reported CLEAN — 0/0 with no findings "
                     "is exactly how the re-attack got a laundered board past this gate")
        if check_board({"games": [g25]}, register=reg).counters.get("ROWS_CHECKED") != "1/1":
            f.append("S25 the counter stopped agreeing with itself on a board that IS fully "
                     "checked, so the denominator is not the supplied count")
    except Exception as e:
        f.append("S25 the supplied-rows counter fixture raised %r" % (e,))

    # ---- S26  THE R3 BASELINE IS TAKEN BEFORE THE CHECK RUNS ----------------------------------
    # load_board() hands back the CALLER'S dict by reference, check_board() then runs on that
    # object, and the baseline used to be hashed afterwards — so a mutation made by the check was
    # folded into the "before" and INPUT_UNCHANGED could not see it. The proof has to span the
    # window it claims to cover.
    _g26 = globals()
    _real_check_board = _g26["check_board"]

    def _stamping_check_board(board_json, _real=_real_check_board, **kw):
        v = _real(board_json, **kw)
        if isinstance(board_json, dict):
            board_json["_stamped_by_check_board"] = True
        return v

    board26 = _mk_one_game_board("synthetic:board-26", "SYA @ SYH")
    _g26["check_board"] = _stamping_check_board
    try:
        enforce(board26, register=reg)
        f.append("S26 check_board stamped a key on the board it was handed and enforce()'s R3 "
                 "self-proof did not notice: the baseline is hashed AFTER the check runs, so the "
                 "window the hash proves is not the window it claims")
    except BoardInvariantsError:
        pass
    except Exception as e:
        f.append("S26 the R3 baseline fixture raised %s, not BoardInvariantsError"
                 % type(e).__name__)
    finally:
        _g26["check_board"] = _real_check_board

    # ---- S27  THE MODULE NAMES ITSELF, AND EVERY MUTANT NAMES ITS FIXTURE ---------------------
    # healthcheck checks that a selftest banner names its own file (the 2026-08-25 incident in
    # which one module was overwritten by another and every gate stayed green), and MODULE_ID is
    # stamped into every enforced board as generated_by. The 8/30 re-attack mutated it to
    # "not_board_invariants" and reported SURVIVED.
    if MODULE_ID != "board_invariants":
        f.append("S27 MODULE_ID is %r; this file is harness/board_invariants.py and the banner, "
                 "the enforced board's generated_by and healthcheck's identity check all read it"
                 % (MODULE_ID,))
    unmarked27 = [e[0][:60] for e in MUTANTS if len(e) < 4 or not e[3]]
    if unmarked27:
        f.append("S27 %d mutant(s) declare no owning fixture, so a kill could be credited to "
                 "collateral damage in an unrelated one (cluster O): %s"
                 % (len(unmarked27), unmarked27[:3]))

    # ---- S14  BOARD SHAPE IS DECLARED, NEVER GUESSED -------------------------------------------
    for bad in ({}, {"games": "nope"}, {"games": [1]}):
        try:
            check_board(bad)
            f.append("S14 a board with no usable games list was checked anyway: %r" % (bad,))
        except BoardInvariantsError:
            pass
        except Exception as e:
            f.append("S14 bad board raised %s, not BoardInvariantsError" % type(e).__name__)

    # ---- S15  COUNTERS ARE GENERATED ------------------------------------------------------------
    if board_v is not None:
        c = board_v.counters
        if c["ROWS_CHECKED"] != "57/57" or c["GAMES_CHECKED"] != "19/19":
            f.append("S15 counters over the frozen card are %r; the card holds 19 games x 3"
                     % {k: c[k] for k in ("ROWS_CHECKED", "GAMES_CHECKED")})
        if c["CONVERGENCE_CHECKS_RUN"] != "1/19":
            f.append("S15 convergence ran on %s games; only MIN@ATL publishes both arms"
                     % c["CONVERGENCE_CHECKS_RUN"])
        if c["ROWS_WITH_EDGE_ON_NULL_PRICE"] != 1 or c["ROWS_WITH_NULL_PRICE"] != 39:
            f.append("S15 null-price counters are %r"
                     % {k: c[k] for k in ("ROWS_WITH_NULL_PRICE",
                                          "ROWS_WITH_EDGE_ON_NULL_PRICE")})
        if board_v.clean:
            f.append("S15 the 8/30 card was reported clean")
        if board_v.sigma_register.get("record_sha256") != reg.get("record_sha256"):
            f.append("S15 the verdict does not carry the register's own content hash")

    # ---- S16  THE VOCABULARY IS SHARED, NOT FORKED ---------------------------------------------
    pairs = [(REASON_MISSING_MARKET_PRICE, sa.BOARD_REASON_MISSING_MARKET_PRICE),
             (REASON_AVAILABILITY_UNKNOWN, sa.BOARD_REASON_AVAILABILITY_UNKNOWN),
             (REASON_MODEL_CONVERGENCE_FAIL, sa.BOARD_REASON_MODEL_CONVERGENCE_FAIL),
             (REASON_ASSUMED_NO_VIG, sa.BOARD_REASON_ASSUMED_NO_VIG),
             (DECISION_PASS, sa.DECISION_PASS), (DECISION_LEAN, sa.DECISION_LEAN),
             (DECISION_PASS_DATA_QUALITY, sa.DECISION_PASS_DATA_QUALITY),
             (DECISION_CONVERGENCE_FAIL, sa.DECISION_CONVERGENCE_FAIL),
             (AVAILABILITY_UNKNOWN, sa.AVAILABILITY_UNKNOWN)]
    for mine, theirs in pairs:
        if mine != theirs:
            f.append("S16 vocabulary forked: %r vs score_admission %r" % (mine, theirs))
    if DIRECTIVE_NAME_ALIASES.get("ASSUMED_NO_VIG_PRICE") != REASON_ASSUMED_NO_VIG:
        f.append("S16 the directive's prose name does not resolve to the emitted code")
    if BOARD_REASON_ORDER[:3] != tuple(sa.MIN_ATL_REQUIRED_ROW["reason_codes"]):
        f.append("S16 emission order no longer matches MIN_ATL_REQUIRED_ROW: %s vs %s"
                 % (list(BOARD_REASON_ORDER[:3]), sa.MIN_ATL_REQUIRED_ROW["reason_codes"]))

    # ---- S17  EVERY CODE HAS A MEANING, AND EVERY CODE HAS FIRED -------------------------------
    # No exemption list: a code that cannot be produced should be deleted, not excused.
    declared = {v for k, v in sorted(globals().items())
                if k.startswith("REASON_") and isinstance(v, str)}
    for code in sorted(declared):
        if code not in REASON_MEANING:
            f.append("S17 %s has no REASON_MEANING entry" % code)
        if code not in BOARD_REASON_ORDER:
            f.append("S17 %s is not in BOARD_REASON_ORDER" % code)
        if code not in SUPPRESSING_REASONS and code not in WARNING_REASONS:
            f.append("S17 %s is neither suppressing nor a warning" % code)
    uncovered = sorted(declared - seen)
    if uncovered:
        f.append("S17 reason codes this selftest never produces: %s" % uncovered)

    print(f"{MODULE_ID} selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  FAIL:", x)
    return not f


# ---------------------------------------------------------------------------------------------
# 12. MUTATION SUITE.  A counter that cannot fail is not a check.
#     Each entry names the DEFECT RESTORED, not a test. Every one must be KILLED by selftest().
# ---------------------------------------------------------------------------------------------

#: Every entry is (DEFECT RESTORED, old, new, MARKER). The marker is the SELFTEST FIXTURE that
#: owns the guard the mutation removes, and a kill requires THAT fixture to fire — cluster O,
#: round two: this runner used to credit a kill to any named failure, so a mutant dying on an
#: unrelated protection's assertion was tallied as its own kill. An exception CLASS may stand in
#: the same slot for a mutant whose correct behaviour is to raise.
MUTANTS = [
    ("the null-price guard is removed: an edge may again be published where no price was captured",
     "        codes.append(REASON_MISSING_MARKET_PRICE)",
     "        pass",
     "S12"),
    ("an assumed no-vig is accepted, so 50.0 standing in for a price stops being a finding",
     "        codes.append(REASON_ASSUMED_NO_VIG)",
     "        pass",
     "S12"),
    ("the two implied margins are compared with a tolerance nothing can exceed",
     "CONVERGENCE_MARGIN_TOLERANCE_POINTS = 1.0",
     "CONVERGENCE_MARGIN_TOLERANCE_POINTS = 1e9",
     "S5"),
    ("a LEAN survives every suppressing code, which is the 8/30 board exactly",
     "    if any(c in SUPPRESSING_REASONS for c in codes) and decision_in in PLAY_DECISIONS:",
     "    if False:",
     "S3"),
    ("two arms disagreeing about the SIGN of the projected margin stop counting as incompatible",
     "                and min(abs(mu_ml), abs(aligned)) >= CONVERGENCE_SIGN_MATERIALITY_POINTS)",
     "                and False)",
     "S4"),
    ("the two arms are compared without aligning the side, so agreement reads as contradiction",
     "    aligned = mu_sp if sp_team == ml_team else -mu_sp",
     "    aligned = mu_sp",
     "S6"),
    ("the convergence finding attaches to the spread arm only, so the ML arm looks innocent",
     "    if market in CONVERGENCE_MARKETS:",
     "    if market == MARKET_SPREAD:",
     "S3"),
    ("the declared sigma is no longer read from the row's own note, so the contradiction the "
     "8/30 card documents becomes invisible",
     '                    out[name] = (v, "note:%s" % m.group(0))',
     "                    pass",
     "S3"),
    ("two different sigmas in one game stop being a refusal",
     "        codes.append(REASON_SIGMA_DISAGREEMENT)",
     "        pass",
     "S9"),
    ("an unverifiable coherence claim stops suppressing, so a LEAN publishes on an unchecked one",
     "    REASON_CONVERGENCE_UNVERIFIABLE,\n})",
     "})",
     "S8"),
    ("STALE and CAP features stop blocking a play",
     '    if play_bearing and dq.get("status") in SUPPRESSING_DQ_STATUSES:',
     "    if False:",
     "S11"),
    ("unresolved availability reads as AVAILABLE, so silence answers the question",
     "        return AVAILABILITY_UNKNOWN, AVAILABILITY_NOT_SUPPLIED",
     '        return "AVAILABLE", AVAILABILITY_RESOLVED',
     "S10"),
    ("a stale availability observation still counts as an answer (owner fixture 10, restored)",
     "            if age_h > limit:",
     "            if False:",
     "S10"),
    ("every sigma counts as measured, so 13.97 stops being a registered tolerance",
     "    return sigma_kind(value, register) == SIGMA_KIND_MEASURED",
     "    return True",
     "S2"),
    ("a missing sigma register stops being a named refusal",
     "    if not os.path.exists(p):",
     "    if False:",
     "S1"),
    ("enforce() edits the board it was handed instead of a copy (R3)",
     "    new = copy.deepcopy(original)",
     "    new = original",
     "S13"),
    ("edge_pp is no longer recomputed from the fields beside it",
     "            warnings.append(REASON_EDGE_NOT_REPRODUCIBLE)",
     "            pass",
     "S12"),
    ("a no-vig published from a one-sided price stops being recorded",
     "        warnings.append(REASON_NO_VIG_ONE_SIDED)",
     "        pass",
     "S12"),
    ("the emission order stops matching the owner's required row",
     "    REASON_MISSING_MARKET_PRICE,\n    REASON_AVAILABILITY_UNKNOWN,",
     "    REASON_AVAILABILITY_UNKNOWN,\n    REASON_MISSING_MARKET_PRICE,",
     "S16"),

    # ---- the five from the 2026-08-30 adversarial review ------------------------------------
    ("cluster G: the suppression is computed and then DISCARDED on the write path, so the "
     "enforced copy publishes edge_pp 14.3, usable_edge_pp 6.9 and the assumed 50.0 again",
     "    removed = []\n    for field, code in targets:",
     "    return []\n    for field, code in targets:",
     "S18"),
    ("cluster H: row verdicts are keyed by market NAME again, so a game with two rows of one "
     "market applies both verdicts to the last row",
     "            row = _bind_row_verdict(rv, markets, gv)",
     '            row = {r.get("market"): r for r in markets'
     " if isinstance(r, dict)}.get(rv.market)",
     "S19"),
    ("cluster I: _markets_of answers [] for a game whose rows are not under 'markets', so the "
     "board is reported CLEAN because nothing was checked",
     "    if not isinstance(m, list):",
     "    if not isinstance(m, list):\n        return []\n    if False:",
     "S20"),
    ("the game-identity assertion is removed, so a verdict computed on one board may be applied "
     "to a different board by position (owner regression fixture 7)",
     '    if (gv.event_id, gv.game) != (game.get("event_id"), game.get("game")):',
     "    if False:",
     "S21"),
    ("the row-identity assertion is removed, so a verdict is applied to whatever row now sits at "
     "that index",
     "    if have != want:",
     "    if False:",
     "S21"),
    ("the verdict/board length check is removed, so a short verdict silently leaves the games "
     "after it unenforced",
     "    if len(v.games) != len(games):",
     "    if False:",
     "S21"),
    ("enforce() reads the path a SECOND time inside check_board and pairs the verdicts from read "
     "#1 onto read #2",
     "        original, availability=availability, sigma=sigma, register=register,",
     "        board_json, availability=availability, sigma=sigma, register=register,",
     "S22"),

    # ---- the four from the 2026-08-30 RE-ATTACK (round two) ----------------------------------
    ("P0-C, cluster G MOVED NOT REMOVED: the prohibited figure is republished in the verdict's "
     "own detail block, so edge_pp 14.3 and usable_edge_pp 6.9 come back as live values at "
     "row['board_invariants']['detail'] while probabilities.edge_pp reads null",
     "    prohibiting = [c for c in _order_codes(codes) if c in EDGE_PROHIBITING_REASONS]",
     "    prohibiting = []",
     "S23"),
    ("P0-D1: a non-mapping market row is silently SKIPPED again, so the acceptance board with "
     "every row wrapped in a list reports clean with nothing checked",
     "    markets = _markets_of(game)\n    rows = []\n    for i, r in enumerate(markets):\n"
     "        if not isinstance(r, dict):",
     "    markets = _markets_of(game)\n    rows = []\n    for i, r in enumerate(markets):\n"
     "        if not isinstance(r, dict):\n            continue\n        if False:",
     "S24"),
    ("P0-D2: ROWS_CHECKED goes back to '%d/%d' % (n_rows, n_rows), a counter whose denominator "
     "is its own numerator and which therefore cannot report a shortfall",
     '            "ROWS_CHECKED": "%d/%d" % (n_rows, n_supplied),',
     '            "ROWS_CHECKED": "%d/%d" % (n_rows, n_rows),',
     "S25"),
    ("P0-D3: a board with unchecked rows is CLEAN again, so 0 findings out of 0 rows checked "
     "reads as a pass",
     '        if self.counters.get("ROWS_NOT_CHECKED"):',
     "        if False:",
     "S25"),
    ("P0-D4: the R3 baseline is hashed AFTER check_board runs, so any mutation the check makes "
     "to the caller's object is folded into the 'before' and INPUT_UNCHANGED cannot see it",
     "    before = _canonical_hash(original)                      # hazard, not the label it "
     "preserved.\n    v = verdict if verdict is not None else check_board(\n"
     "        original, availability=availability, sigma=sigma, register=register,\n"
     "        source=board_json if isinstance(board_json, str) else None)",
     "    v = verdict if verdict is not None else check_board(\n"
     "        original, availability=availability, sigma=sigma, register=register,\n"
     "        source=board_json if isinstance(board_json, str) else None)\n"
     "    before = _canonical_hash(original)",
     "S26"),
]

#: CLUSTER O's own check, matching score_admission's. This mutation is NOT a defect and is NOT in
#: MUTANTS: it is a canary that must come back ERRORED and never KILLED. A suite that counts a
#: crash as a kill reports a perfect score while proving nothing, which is what this file did once
#: already — so the classifier is tested rather than trusted. It targets the MODULE_ID line
#: because the re-attack mutated exactly that line and reported SURVIVED.
ERROR_CANARY = ("the module raises at import, before any fixture runs",
                'MODULE_ID = "board_invariants"',
                'MODULE_ID = "board_invariants" + _this_name_does_not_exist')


#: Cluster O, adversarial review 2026-08-30, and it applies to every file in this layer: the old
#: suite counted ANY exception as a kill. A mutant that dies at import, or one that turns a
#: fixture into an IndexError, proves only that the file crashed — it does not prove the fixture
#: noticed the defect. score_admission printed 12/12 KILLED that way while every mutant died of an
#: AttributeError before a single fixture ran. So:
#:
#:   KILLED    a NAMED selftest assertion failed (or a specifically expected exception type was
#:             raised), and the name of that assertion is printed as the evidence.
#:   ERRORED   anything else that went wrong — import failure, an unexpected exception type, a
#:             selftest that returned False without naming anything. Reported SEPARATELY and NOT
#:             counted as a kill.
#:   SURVIVED  the defect was restored and the selftest still passed.
#:   MISDIRECTED  a named failure fired, but not the one the entry DECLARES. The mutant died of
#:             collateral damage in a fixture that watches something else, so it proves nothing
#:             about the guard it removed. Cluster O, round two: this runner credited a kill to
#:             ANY named failure and had no marker at all, while score_admission's had required
#:             the declared marker since round one.
MUTANT_KILLED = "KILLED"
MUTANT_ERRORED = "ERRORED"
MUTANT_SURVIVED = "SURVIVED"
MUTANT_UNAPPLIED = "UNAPPLIED"
MUTANT_SELF_TARGETED = "SELF_TARGETED"
MUTANT_MISDIRECTED = "MISDIRECTED"


def _marker_matches(failure, marker):
    """Does this named failure come from the fixture the mutant DECLARES?

    An S-number matches only as the failure's leading token, so "S1" cannot be credited to a
    failure from S18 — a prefix collision would make the misdirection check decorative, which is
    the same class of defect as the tally parser that read "10 survived" as zero.
    """
    if " " in marker:
        return marker in failure
    return failure.split(None, 1)[:1] == [marker]


def _mutant_outcome(src, old, new, expectation=None):
    """(outcome, evidence) for one mutation. See the cluster O note above for the vocabulary.

    `expectation` is the entry's fourth element: the marker of the fixture that owns the guard,
    or an exception CLASS for a mutant whose correct behaviour is to raise.
    """
    import io as _io, contextlib as _cl
    wants_exception = isinstance(expectation, type) and issubclass(expectation, BaseException)
    ns = {"__file__": os.path.abspath(__file__), "__name__": "mutant"}
    buf = _io.StringIO()
    try:
        with _cl.redirect_stdout(buf):
            exec(compile(src.replace(old, new, 1), "<mutant>", "exec"), ns)
    except Exception as e:
        if wants_exception and isinstance(e, expectation):
            return MUTANT_KILLED, "raised the expected %s at import" % expectation.__name__
        return MUTANT_ERRORED, "died at import: %s: %s" % (type(e).__name__, e)
    fn = ns.get("selftest")
    if not callable(fn):
        return MUTANT_ERRORED, "the mutated module exposes no selftest()"
    buf = _io.StringIO()
    try:
        with _cl.redirect_stdout(buf):
            ok = fn()
    except Exception as e:
        if wants_exception and isinstance(e, expectation):
            return MUTANT_KILLED, "raised the expected %s: %s" % (expectation.__name__, e)
        return MUTANT_ERRORED, ("selftest raised %s (%s) instead of failing a named assertion"
                                % (type(e).__name__, e))
    named = [ln.strip()[5:].strip() for ln in buf.getvalue().splitlines()
             if ln.strip().startswith("FAIL:")]
    if ok:
        return MUTANT_SURVIVED, "the defect was restored and every fixture still passed"
    if not named:
        return MUTANT_ERRORED, "selftest returned False without naming a failed assertion"
    if wants_exception:
        return MUTANT_ERRORED, ("expected %s, got %d named failure(s)"
                                % (expectation.__name__, len(named)))
    if expectation is None:
        return MUTANT_MISDIRECTED, ("killed by %r, but the entry names no fixture, so nothing "
                                    "compares the failure to the guard this mutant removes"
                                    % (named[0][:90],))
    if not any(_marker_matches(x, expectation) for x in named):
        return MUTANT_MISDIRECTED, ("killed by %r, but no %s failure fired — the guard this "
                                    "mutant removes is watched by a DIFFERENT fixture than the "
                                    "one it claims" % (named[0][:90], expectation))
    return MUTANT_KILLED, [x for x in named if _marker_matches(x, expectation)][0]


def mutation_suite():
    src = open(os.path.abspath(__file__)).read()
    # BASELINE FIRST. A failing selftest makes every mutant look killed, so a broken fixture
    # reports a perfect score. (module_manifest printed 11/11 that way on 2026-08-25.)
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        _base = selftest()
    if not _base:
        print("  BASELINE_FAILING  the unmutated selftest does not pass; every 'kill' below is "
              "meaningless until it does")
        print(_b.getvalue().strip())
        return False
    # a mutant whose pattern occurs only inside the MUTANTS literal edits its OWN definition,
    # applies cleanly, changes no behaviour and reports SURVIVED.
    body = src[:src.index("MUTANTS = [")]
    tally = {MUTANT_KILLED: 0, MUTANT_ERRORED: 0, MUTANT_SURVIVED: 0,
             MUTANT_UNAPPLIED: 0, MUTANT_SELF_TARGETED: 0, MUTANT_MISDIRECTED: 0}
    for entry in MUTANTS:
        name, old, new = entry[0], entry[1], entry[2]
        expectation = entry[3] if len(entry) > 3 else None
        if old not in src:
            tally[MUTANT_UNAPPLIED] += 1
            print("  UNAPPLIED      " + name + ": pattern not found")
            continue
        if old not in body:
            tally[MUTANT_SELF_TARGETED] += 1
            print("  SELF_TARGETED  " + name + ": pattern occurs only inside the MUTANTS list")
            continue
        outcome, evidence = _mutant_outcome(src, old, new, expectation)
        tally[outcome] += 1
        print("  %-14s %s\n                   <- %s" % (outcome, name, evidence))

    # CLUSTER O's classifier, TESTED rather than trusted: a mutation that dies at import must be
    # reported as an ERROR and must never reach the kill tally.
    canary_name, canary_old, canary_new = ERROR_CANARY
    canary_outcome, canary_evidence = _mutant_outcome(src, canary_old, canary_new)
    canary_ok = canary_outcome == MUTANT_ERRORED
    print("  %-14s CANARY %s\n                   <- %s"
          % ("OK" if canary_ok else "BROKEN", canary_name, canary_evidence))
    if not canary_ok:
        print("  A SUITE THAT CALLS AN IMPORT CRASH A KILL COUNTS CRASHES AS PROOF: the canary "
              "was classified %s." % canary_outcome)

    killed, errored, survived = (tally[MUTANT_KILLED], tally[MUTANT_ERRORED],
                                 tally[MUTANT_SURVIVED])
    if errored:
        print("  ERRORS ARE NOT KILLS. A mutant that crashes proves the file broke, not that a "
              "fixture noticed the defect.")
    if survived:
        print("  SURVIVORS MEAN DECORATIVE FIXTURES.")
    if tally[MUTANT_MISDIRECTED]:
        print("  MISDIRECTED IS NOT A KILL. The mutant died in a fixture that watches something "
              "else, so nothing here proves the guard it removed is guarded.")
    # The tally is the LAST line: healthcheck parses it (and once read '10 survived' as zero).
    print("board_invariants mutation suite: %d killed, %d errored, %d survived (of %d; %d "
          "unapplied, %d self-targeted, %d misdirected, canary %s)"
          % (killed, errored, survived, len(MUTANTS), tally[MUTANT_UNAPPLIED],
             tally[MUTANT_SELF_TARGETED], tally[MUTANT_MISDIRECTED],
             "OK" if canary_ok else "BROKEN"))
    return killed == len(MUTANTS) and canary_ok


def gate():
    """Healthcheck entry point: the fixtures hold AND the mutants die."""
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        ok_self = selftest()
        ok_mut = mutation_suite()
    print("board invariants gate: %s (selftest %s, mutants %s)"
          % ("PASS" if (ok_self and ok_mut) else "FAIL",
             "OK" if ok_self else "FAIL", "OK" if ok_mut else "FAIL"))
    # The mutation tally is printed even on PASS. "the mutants died" is a claim; "N killed, M
    # errored, K survived" is the number that says what died and how (cluster O).
    for line in _b.getvalue().splitlines():
        if line.startswith("board_invariants mutation suite:"):
            print("  " + line)
    if not (ok_self and ok_mut):
        print(_b.getvalue().strip())
    return 0 if (ok_self and ok_mut) else 1


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if "--gate" in sys.argv:
        sys.exit(gate())
    if "--acceptance" in sys.argv:
        sys.exit(acceptance_report())
    print(__doc__)
