"""Cross-sport reader contract: model output is independent of market and action state.

A missing price removes EV. Missing conservative uncertainty removes authorization. Neither may
erase an already-generated model side. A refresh-pending model may be shown as preliminary when
its exact as-of state is disclosed; the later anchored refresh supersedes it append-only.
"""

MODULE_ID = "model_output_first_v1"

OUTPUT_AVAILABLE = {"FROZEN", "REPLACEMENT_ANCHORED", "PRELIMINARY_ASOF"}
BLOCKERS = {
    "NO_RETAINED_MARKET_ARTIFACT", "MARKET_PARTIAL", "PERSONNEL_UNVERIFIED",
    "UNCERTAINTY_UNAVAILABLE", "FEATURE_REFRESH_PENDING", "ACTION_BLOCKED",
}
NO_OUTPUT = {"NO_COMPETITION_ELIGIBLE_MODEL", "MODEL_LINEAGE_UNAVAILABLE"}


def validate_row(row):
    fails = []
    status = row.get("forecast_status")
    p = row.get("p_home")
    side = row.get("model_side")
    model_id = row.get("model_id")

    if status in OUTPUT_AVAILABLE:
        if not model_id:
            fails.append("AVAILABLE_OUTPUT_MISSING_MODEL_ID")
        if not isinstance(p, (int, float)) or not 0 < p < 1:
            fails.append("AVAILABLE_OUTPUT_MISSING_VALID_P_HOME")
        expected = row.get("home") if p >= 0.5 else row.get("away")
        if not side or side != expected:
            fails.append("MODEL_SIDE_NOT_DERIVED_FROM_P_HOME")
        if not row.get("forecast_as_of"):
            fails.append("AVAILABLE_OUTPUT_MISSING_AS_OF")
        if status == "PRELIMINARY_ASOF" and not row.get("supersession_rule"):
            fails.append("PRELIMINARY_OUTPUT_MISSING_SUPERSESSION_RULE")
    elif status in NO_OUTPUT:
        if p is not None or side is not None:
            fails.append("NO_OUTPUT_STATE_EMITS_FORECAST")
        if not row.get("scope_reason"):
            fails.append("NO_OUTPUT_STATE_MISSING_SCOPE_REASON")
    else:
        fails.append("UNKNOWN_FORECAST_STATUS")

    # These states affect market/action lanes only; they never justify blank model output.
    blockers = set(row.get("blockers", []))
    if blockers & BLOCKERS and status not in OUTPUT_AVAILABLE | NO_OUTPUT:
        fails.append("BLOCKER_SUPPRESSED_FORECAST_LANE")
    return fails


def validate_card(card):
    fails = []
    sections = card.get("reader_sections", [])
    if "model_output" not in sections:
        fails.append("READER_VIEW_MISSING_MODEL_OUTPUT_SECTION")
    elif "market" in sections and sections.index("model_output") > sections.index("market"):
        fails.append("MODEL_OUTPUT_MUST_PRECEDE_MARKET")
    for i, row in enumerate(card.get("rows", [])):
        fails += [f"row[{i}] {x}" for x in validate_row(row)]
    return fails


def selftest():
    base = {
        "game": "A@H", "away": "A", "home": "H", "model_id": "sport.model.v1",
        "forecast_status": "FROZEN", "forecast_as_of": "2026-08-27T09:00:00Z",
        "p_home": 0.54, "model_side": "H",
        "blockers": ["NO_RETAINED_MARKET_ARTIFACT", "UNCERTAINTY_UNAVAILABLE"],
    }
    card = {"reader_sections": ["model_output", "market", "action", "audit"], "rows": [base]}
    fails = validate_card(card)
    mutations = [
        ({**base, "model_side": None}, "AVAILABLE_OUTPUT_MISSING"),
        ({**base, "model_side": "A"}, "MODEL_SIDE_NOT_DERIVED"),
        ({**base, "forecast_status": "PRELIMINARY_ASOF"}, "SUPERSESSION"),
        ({**base, "forecast_status": "NO_COMPETITION_ELIGIBLE_MODEL",
          "p_home": None, "model_side": None}, "SCOPE_REASON"),
    ]
    for row, expected in mutations:
        got = validate_row(row)
        if not any(expected in x for x in got):
            fails.append(f"mutation not refused: {expected}")
    wrong_order = {"reader_sections": ["market", "model_output"], "rows": [base]}
    if "MODEL_OUTPUT_MUST_PRECEDE_MARKET" not in validate_card(wrong_order):
        fails.append("reader-order mutation not refused")
    print("model_output_first:", "FAIL " + "; ".join(fails) if fails else
          "PASS (forecast, market, action lanes separated; output-first order enforced)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
