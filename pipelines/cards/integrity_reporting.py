"""Read-only card-face integrity disclosures, never validation or selection.

Consumes existing freshness/NFL capability receipts. Optional generic numerical
receipts use ``sports.numerical_consumption_receipt.v1`` and the same parent
bindings; a hash binds a reported trace but does not authenticate a source or
establish a causal effect. No prices, probability adjustments or default thresholds.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
from datetime import datetime, timezone

SCHEMA = "sports.card_integrity_report.v1"
REVIEW_CLASS = "NHL_ROAD_FAVORITE_SUB1_MARGIN_GOALIE_USE_UNPROVEN"
_METHODS = {"exact_centered_linear_term", "exact_weighted_ensemble_term",
            "exact_deterministic_counterfactual", "paired_monte_carlo_counterfactual"}


def _obj(value):
    return value if isinstance(value, dict) else {}


def _rows(value):
    return value if isinstance(value, list) else []


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, OverflowError):
        return None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _time(value):
    if not isinstance(value, str):
        raise ValueError("TIMESTAMP_REQUIRED")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return stamp.astimezone(timezone.utc)


def _same_time(a, b):
    try:
        return _time(a) == _time(b)
    except (TypeError, ValueError, OverflowError):
        return False


def _hash_bound(receipt):
    content = dict(receipt)
    expected = content.pop("receipt_sha256", None)
    try:
        return isinstance(expected, str) and expected == _digest(content)
    except (TypeError, ValueError, OverflowError):
        return False


def _parent_bound(receipt, row, cutoff, *, input_required=True):
    keys = ["event_id", "model_id", "model_state_config_hash"]
    if input_required:
        keys.append("input_snapshot_hash")
    return (all(row.get(k) is not None and receipt.get(k) == row[k] for k in keys)
            and _same_time(receipt.get("cutoff_utc"), cutoff))


def _freshness(row, cutoff):
    raw = _obj(_obj(row.get("diagnostics")).get("state_freshness_receipt"))
    result = {"status": "UNKNOWN", "per_side": {}, "reasons": [], "policy_max_age_hours": None}
    if not raw:
        result["reasons"] = ["CONSUMED_STATE_RECEIPT_ABSENT"]
        return result
    if (raw.get("schema") != "sports.state_freshness_receipt.v1" or not _hash_bound(raw)
            or not _parent_bound(raw, row, cutoff)):
        result["reasons"] = ["STATE_RECEIPT_INVALID_OR_PARENT_MISMATCH"]
        return result
    features = _obj(row.get("model_input_snapshot"))
    try:
        features_match = _digest(features) == row.get("input_snapshot_hash")
    except (TypeError, ValueError, OverflowError):
        features_match = False
    if not features_match:
        result["reasons"] = ["PARENT_FEATURE_HASH_MISMATCH"]
        return result
    result.update(status="RECEIPT_BOUND", policy_max_age_hours=raw.get("max_state_age_hours_policy"),
                  training_cutoff_utc=raw.get("training_cutoff_utc"), receipt_sha256=raw["receipt_sha256"])
    result["reasons"] = [str(v) for v in _rows(raw.get("blocking_reasons"))]
    for side in ("home", "away"):
        item = _obj(_obj(raw.get("per_side")).get(side))
        stamp = item.get("consumed_state_last_start_utc")
        age = _number(item.get("state_age_at_cutoff_hours"))
        try:
            expected_age = (_time(cutoff) - _time(stamp)).total_seconds() / 3600
            valid = age is not None and math.isclose(age, expected_age, abs_tol=1e-8, rel_tol=0)
        except (TypeError, ValueError, OverflowError):
            valid = False
        actual = _number(features.get(side + "_rest"))
        declared = _number(item.get("rest_feature_value"))
        used = actual is not None and declared == actual and item.get("feature_matches_consumed_state") is True
        result["per_side"][side] = {"team_id": item.get("team_id"),
            "consumed_state_last_start_utc": stamp if valid else None,
            "state_age_at_cutoff_hours": age if valid else None,
            "rest_feature_value": declared, "rest_feature_trace_bound": used,
            "rest_basis": item.get("rest_basis"), "imputed": item.get("imputed") is True,
            "reasons": [str(v) for v in _rows(item.get("blocking_reasons"))]}
        if not valid:
            result["reasons"].append(side.upper() + ":STATE_TIMESTAMP_UNKNOWN_OR_INVALID")
        if not used:
            result["reasons"].append(side.upper() + ":REST_CONSUMPTION_TRACE_UNPROVEN")
    return result


def _trace(item, row):
    """Check a reported numerical term against exact fitted/input identities."""
    feature = item.get("feature")
    values = _obj(row.get("model_input_snapshot"))
    lineage = _obj(item.get("lineage"))
    terms = _obj(item.get("contribution"))
    if (not isinstance(feature, str) or feature not in values
            or item.get("active_in_run") is not True or item.get("implemented") is not True
            or item.get("fitted_artifact_available") is not True or item.get("pregame_eligible") is not True
            or item.get("contribution_method") not in _METHODS
            or not terms or any(_number(v) is None for v in terms.values())
            or lineage.get("model_artifact_sha256") != row.get("model_state_config_hash")
            or not row.get("model_state_config_hash")
            or lineage.get("feature_value_sha256") != _digest(values[feature])):
        return None
    if item.get("contribution_method") == "paired_monte_carlo_counterfactual":
        u = _obj(item.get("uncertainty")); se = _obj(u.get("standard_error"))
        if (u.get("paired") is not True or type(u.get("n_draws")) is not int or u["n_draws"] < 2
                or u.get("estimator") != "mean_paired_outcome_difference"
                or u.get("uncertainty_scope") != "monte_carlo_only" or set(se) != set(terms)
                or any(_number(v) is None or v < 0 for v in se.values())):
            return None
    return {"feature": feature, "feature_group": item.get("feature_group", "UNKNOWN"),
            "method": item["contribution_method"], "contribution": dict(terms),
            "units": dict(_obj(item.get("contribution_units"))),
            "nonzero_reported_term": any(float(v) != 0 for v in terms.values()),
            "scope": "BOUND_REPORTED_NUMERICAL_TRACE_NOT_CAUSAL_EFFECT_OR_VALIDATION"}


def _consumption(row, cutoff, freshness):
    diag = _obj(row.get("diagnostics")); records = []; errors = []
    cap = _obj(diag.get("capability_report"))
    if cap:
        try:
            from models.nfl.contextual.capabilities import validate_report
            if (cap.get("schema") != "nfl.capabilities.v1" or cap.get("event_id") != row.get("event_id")
                    or cap.get("model_id") != row.get("model_id") or not _same_time(cap.get("cutoff_utc"), cutoff)):
                raise ValueError("CAPABILITY_PARENT_MISMATCH")
            validate_report(cap)
            records.extend(_rows(cap.get("rows")))
        except (KeyError, TypeError, ValueError, OSError, OverflowError):
            errors.append("CAPABILITY_REPORT_INVALID_OR_UNBOUND")
    generic = _obj(diag.get("numerical_consumption_receipt"))
    if generic:
        if (generic.get("schema") == "sports.numerical_consumption_receipt.v1" and _hash_bound(generic)
                and _parent_bound(generic, row, cutoff)):
            records.extend(_rows(generic.get("rows")))
        else:
            errors.append("NUMERICAL_RECEIPT_INVALID_OR_UNBOUND")
    traces = []
    try:
        feature_hash_matches = _digest(_obj(row.get("model_input_snapshot"))) == row.get("input_snapshot_hash")
    except (TypeError, ValueError):
        feature_hash_matches = False
    for record in records:
        trace = _trace(_obj(record), row) if feature_hash_matches else None
        if trace:
            traces.append(trace)
    rests = [side for side, r in freshness["per_side"].items() if r["rest_feature_trace_bound"]]
    bound = bool(row.get("model_input_snapshot"))
    return {"status": "NUMERICAL_TRACE_BOUND" if traces or rests else ("INPUT_PRESENT_USE_UNPROVEN" if bound else "UNKNOWN"),
            "traces": traces, "rest_feature_traces": rests, "reasons": errors,
            "goalie_numerical_trace_bound": any(t["feature_group"] in {"goalie", "goalie_identity", "goaltender"} for t in traces),
            "interpretation": "Input binding alone is not numerical consumption; reported terms are not causal effects or calibrated probabilities."}


def _margins(row, card, cutoff):
    diag = _obj(row.get("diagnostics")); head = _number(diag.get("home_margin")); source = "diagnostics.home_margin"
    if head is None:
        head = _number(_obj(diag.get("prediction")).get("home_margin")); source = "diagnostics.prediction.home_margin"
    if head is None and row.get("projected_margin_orientation") in {"HOME_MINUS_AWAY", "WINNER_MINUS_OPPONENT"}:
        value = _number(row.get("projected_margin"))
        if value is not None:
            if row["projected_margin_orientation"] == "HOME_MINUS_AWAY":
                head = value
            elif row.get("model_winner") in {row.get("home_team"), row.get("away_team")}:
                head = value if row["model_winner"] == row.get("home_team") else -value
        source = "explicit_projected_margin_orientation"
    siblings = []; reasons = []
    for key in ("joint_distribution", "score_simulation"):
        value = _number(_obj(diag.get(key)).get("mean_margin"))
        if value is not None:
            siblings.append({"mean_home_margin": value, "source": "diagnostics." + key,
                             "basis": "EXACT_REPORTED" if key == "joint_distribution" else "MONTE_CARLO_REPORTED"})
            break  # Exact measure takes precedence over its stochastic replay.
    child = _obj(card.get("distribution_research_report"))
    for result in _rows(child.get("results")):
        if not isinstance(result, dict) or result.get("event_id") != row.get("event_id"):
            continue
        distribution = _obj(result.get("distribution"))
        if distribution.get("product") != "margin":
            continue
        try:
            from models.common import discrete_research as D
            x, p = D.validate(distribution); provenance = _obj(distribution.get("provenance"))
            if (distribution.get("league") != str(row.get("league", card.get("league", ""))).lower()
                    or provenance.get("event_id") != row.get("event_id")
                    or provenance.get("parent_model_id") != row.get("model_id")
                    or provenance.get("parent_forecast_sha256") != D.digest(row)
                    or not _same_time(provenance.get("cutoff"), cutoff)):
                raise ValueError("SIBLING_PARENT_MISMATCH")
            siblings.append({"mean_home_margin": float(x @ p), "source": distribution["model_id"],
                             "basis": "EXACT_BOUND_PMF", "distribution_sha256": distribution["distribution_sha256"]})
        except (KeyError, TypeError, ValueError):
            reasons.append("SIBLING_DISTRIBUTION_INVALID_OR_UNBOUND")
    disagreement = head is not None and any(head * s["mean_home_margin"] < 0 for s in siblings)
    return {"orientation": "HOME_MINUS_AWAY", "head_home_margin": head,
            "head_source": source if head is not None else None, "sibling_distributions": siblings,
            "sign_disagreement": disagreement, "comparison_status": "SIGN_DISAGREEMENT" if disagreement else
            ("COMPARABLE" if head is not None and siblings else "UNKNOWN"), "reasons": reasons}


def integrity_report(card):
    """Build a diagnostic report without changing any field on the input card."""
    card = _obj(card); cutoff = card.get("as_of_utc"); events = []
    for raw in _rows(card.get("forecasts")):
        row = _obj(raw); freshness = _freshness(row, cutoff)
        consumption = _consumption(row, cutoff, freshness); margins = _margins(row, card, cutoff)
        flags = []
        if margins["sign_disagreement"]:
            flags.append("HEAD_DISTRIBUTION_SIGN_DISAGREEMENT")
        league = str(row.get("league", card.get("league", ""))).lower()
        p = _number(row.get("model_p")); mean = margins["head_home_margin"]
        if (league == "nhl" and row.get("away_team") is not None and row.get("model_winner") == row.get("away_team")
                and p is not None and .5 < p <= 1 and mean is not None and abs(mean) < 1
                and not consumption["goalie_numerical_trace_bound"]):
            flags.append(REVIEW_CLASS)
        events.append({"event_id": row.get("event_id"), "home_team": row.get("home_team"),
                       "away_team": row.get("away_team"), "forecast_status": row.get("forecast_status", "UNKNOWN"),
                       "state_freshness": freshness, "numerical_consumption": consumption,
                       "margins": margins, "review_flags": flags, "review_action": "REVIEW_ONLY_NO_AUTO_FADE"})
    return {"schema": SCHEMA, "status": "DIAGNOSTIC_NOT_CERTIFICATION", "events": events,
            "probabilities_modified": False, "selection_modified": False, "action_authority": False}


def _cell(value):
    return html.escape(str(value)).replace("|", "&#124;").replace("\n", " ").replace("\r", " ").replace("`", "&#96;")


def render_integrity_md(card):
    """Concise card-face table; unknown remains visible and is never called fresh."""
    report = integrity_report(card)
    lines = ["**Consumed-state and model integrity — diagnostic, not certification.**",
             "State age uses consumed results; a recent fetch is not a state refresh. Margins below are home minus away.", "",
             "| Game | Consumed state / age at cutoff | Numerical use | Margin head / sibling distribution | Review |",
             "|---|---|---|---|---|"]
    for event in report["events"]:
        f = event["state_freshness"]; c = event["numerical_consumption"]; m = event["margins"]
        state = []
        for side in ("away", "home"):
            entry = f["per_side"].get(side, {})
            stamp, age = entry.get("consumed_state_last_start_utc"), entry.get("state_age_at_cutoff_hours")
            state.append(f"{side}: {stamp} ({age:.1f}h)" if stamp is not None and age is not None else f"{side}: UNKNOWN")
        if f["reasons"]:
            state.append("; ".join(f["reasons"]))
        traces = c["traces"]
        use = c["status"]
        if c["rest_feature_traces"]:
            use += "; rest feature trace: " + ", ".join(c["rest_feature_traces"]) + " (effect size unmeasured)"
        if traces:
            names = sorted({t["feature_group"] for t in traces})
            use += f"; {len(traces)} reported terms: " + ", ".join(names)
        else:
            use += "; player/goalie effect not demonstrated"
        head = "UNKNOWN" if m["head_home_margin"] is None else f"{m['head_home_margin']:+.2f}"
        siblings = "; ".join(f"{s['mean_home_margin']:+.2f} ({s['source']})" for s in m["sibling_distributions"]) or "UNKNOWN"
        review = "; ".join(event["review_flags"] + m["reasons"] + c["reasons"]) or "No named flag established"
        lines.append("| " + " | ".join(_cell(x) for x in [f"{event['away_team']} @ {event['home_team']}",
            "; ".join(state), use, head + " / " + siblings, review]) + " |")
    if not report["events"]:
        lines.append("| No forecast rows | UNKNOWN | UNKNOWN | UNKNOWN / UNKNOWN | No review performed |")
    lines += ["", "Input binding alone does not prove numerical use. Review flags do not change forecasts, select a side, or establish calibration."]
    return "\n".join(lines)
