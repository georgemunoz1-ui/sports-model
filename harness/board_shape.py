"""Board-shape validator — the gate that makes every board machine-readable at one path.

Finding this closes: the CFB board (2026-08-29) parked its rows at board["rows"], the only board
not at board[sport]["rows"], so no cross-sport gate could read it; the NFL board moved its rows
between 8/27 (board["rows"]) and 8/28 (board["nfl"]["rows"]) — the shape changed between
consecutive days. Neither board declared the timezone of its slate_date/scheduled_date semantics,
and CFB rows carried no canonical id at all.

validate_board_shape is FAIL LOUD AND TOTAL: it never returns a partial verdict and never raises
on the first defect — it collects EVERY violation and raises one BoardShapeError listing all of
them, so a builder fix pass converges in one iteration instead of N.

This module is stdlib-only by design: it runs inside builders that import numpy/pandas/sklearn
and inside gates that must not.
"""
from __future__ import annotations

MODULE_ID = "board_shape"

import re

#: A canonical id is "<SPACE>:<value>" — an uppercase namespace, a colon, a non-empty value.
#: "DK_RELAY:north-carolina-at-tcu" and "ESPN_GAMEID:401873301" both conform; a bare integer or
#: an unnamespaced slug does not. Namespacing is what makes two id spaces unable to collide.
_NAMESPACED_ID = re.compile(r"^[A-Z][A-Z0-9_]*:\S+$")

#: Date fields a row may use to satisfy the "date fields present" requirement, in preference
#: order. scheduled_date is the slate-semantics date (interpreted in board["date_timezone"]);
#: start_utc / kickoff_utc are real instants. A row needs at least one of them, non-empty.
_ROW_DATE_FIELDS = ("scheduled_date", "start_utc", "kickoff_utc")

#: The contract, as a docstring-dict, so a gate or a reviewer can read the rule this module
#: enforces without reading code.
BOARD_SHAPE_CONTRACT = {
    "rows_path": (
        "rows live at board[sport]['rows'] and nowhere else. A top-level board['rows'] is a "
        "violation even if board[sport]['rows'] also exists — two row homes is how the 8/27 vs "
        "8/28 NFL shape drift happened."),
    "identity": (
        "every row carries canonical_id in namespaced '<SPACE>:<value>' form, OR an explicit "
        "id_status string explaining the absence (e.g. 'NOT_CAPTURED: <reason>'). R1: an id is "
        "never invented to satisfy this — absence is declared, not papered over."),
    "dates": (
        "board['date_timezone'] declares the timezone of slate_date / scheduled_date semantics "
        "(IANA name, e.g. 'America/New_York'), and every row carries at least one non-empty "
        "date field among scheduled_date / start_utc / kickoff_utc."),
    "failure_mode": (
        "validate_board_shape raises BoardShapeError listing EVERY violation found. It is called "
        "by the builder before any bytes are written; a nonconforming board never reaches disk."),
}


class BoardShapeError(ValueError):
    """Raised by validate_board_shape. .violations holds the full list of defect strings."""

    def __init__(self, violations):
        self.violations = list(violations)
        super().__init__(
            "BOARD_SHAPE_VIOLATION: %d defect(s)\n%s"
            % (len(self.violations),
               "\n".join("  - %s" % v for v in self.violations)))


def validate_board_shape(board, sport):
    """Validate `board` against BOARD_SHAPE_CONTRACT for `sport`. Returns True or raises.

    Every check runs; nothing short-circuits. Raises BoardShapeError with all violations.
    """
    violations = []

    if not isinstance(board, dict):
        raise BoardShapeError(["board is not a dict (got %s)" % type(board).__name__])

    # ---- rows path -------------------------------------------------------------
    section = board.get(sport)
    rows = None
    if not isinstance(section, dict) or "rows" not in section:
        violations.append(
            "rows missing at board[%r]['rows']" % sport)
    else:
        rows = section["rows"]
        if not isinstance(rows, list):
            violations.append(
                "board[%r]['rows'] is %s, not a list" % (sport, type(rows).__name__))
            rows = None
    if "rows" in board:
        violations.append(
            "top-level board['rows'] present — rows must live only at board[%r]['rows']" % sport)

    # ---- date_timezone declaration ---------------------------------------------
    tz = board.get("date_timezone")
    if not tz or not isinstance(tz, str):
        violations.append(
            "board['date_timezone'] missing — the timezone of slate_date/scheduled_date "
            "semantics must be declared (IANA name, e.g. 'America/New_York')")

    # ---- per-row checks ----------------------------------------------------------
    if isinstance(rows, list):
        for i, row in enumerate(rows):
            label = "row %d (%s)" % (i, row.get("game", "?")) if isinstance(row, dict) \
                else "row %d" % i
            if not isinstance(row, dict):
                violations.append("%s is not a dict" % label)
                continue
            cid = row.get("canonical_id")
            if cid is None:
                if not row.get("id_status"):
                    violations.append(
                        "%s: no canonical_id and no id_status explaining its absence (R1: "
                        "absence must be declared, never filled with an invented id)" % label)
            elif not _NAMESPACED_ID.match(str(cid)):
                violations.append(
                    "%s: canonical_id %r is not namespaced '<SPACE>:<value>'" % (label, cid))
            if not any(row.get(f) for f in _ROW_DATE_FIELDS):
                violations.append(
                    "%s: no date field — need a non-empty scheduled_date, start_utc or "
                    "kickoff_utc" % label)

    if violations:
        raise BoardShapeError(violations)
    return True



# ====================================================================== selftest

def _ok_board():
    return {"sport": "cfb", "slate_date": "2026-08-29",
            "date_timezone": "America/New_York",
            "cfb": {"rows": [{"game": "cfb:UNC@TCU", "canonical_id": "DK_RELAY:unc-at-tcu",
                              "id_space": "DK_RELAY", "id_grade": "RELAYED_NOT_CAPTURED",
                              "scheduled_date": "2026-08-29"}]}}


def selftest():
    """Fixtures only. The frozen 2026-08-2x boards predate this contract and are NOT asserted
    against it — R3 means they keep their published shape and would fail by design."""
    f = []

    try:
        validate_board_shape(_ok_board(), "cfb")
    except BoardShapeError as e:
        f.append(f"S1: a conforming board was rejected: {e}")

    # S2 — the CFB defect: rows at top level instead of board[sport]['rows'].
    b = _ok_board(); b["rows"] = b["cfb"]["rows"]; del b["cfb"]
    try:
        validate_board_shape(b, "cfb")
        f.append("S2: top-level rows accepted — this is the shape no gate in the repo can read")
    except BoardShapeError:
        pass

    # S3 — rows in BOTH places (the NFL 8/27->8/28 drift shape) must also refuse.
    b3 = _ok_board(); b3["rows"] = []
    try:
        validate_board_shape(b3, "cfb")
        f.append("S3: a board carrying rows in both places was accepted")
    except BoardShapeError:
        pass

    # S4 — an undeclared timezone refuses. Every date on a board is ambiguous without it, which
    #      is the root of 18 of the 26 audit findings.
    b4 = _ok_board(); del b4["date_timezone"]
    try:
        validate_board_shape(b4, "cfb")
        f.append("S4: a board with no date_timezone declaration was accepted")
    except BoardShapeError:
        pass

    # S5 — all violations are reported at once, not one per run.
    b5 = {"sport": "cfb", "rows": []}
    try:
        validate_board_shape(b5, "cfb")
        f.append("S5: a board with several violations was accepted")
    except BoardShapeError as e:
        if len(getattr(e, "violations", getattr(e, "args", [[]])[0]) or []) < 2:
            f.append("S5: only one violation reported; the validator must not short-circuit")

    print(f"{MODULE_ID} selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  !", x)
    return 0 if not f else 1


if __name__ == "__main__":
    import json
    import sys
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    board = json.load(open(sys.argv[1]))
    sport = sys.argv[2] if len(sys.argv) > 2 else board.get("sport")
    validate_board_shape(board, sport)
    print("OK: board[%r]['rows'] conforms to BOARD_SHAPE_CONTRACT" % sport)
