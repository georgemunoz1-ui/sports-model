#!/usr/bin/env python3
"""Execute a preregistered, source-bound QB margin study and deployment refit.

Historical timestamps describe reconstructed information sets. The later-season
evaluation is held out from this distribution fit, not from earlier research.
This command cannot promote a model or register a historical pregame forecast.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.common import discrete_research as D
from models.common import margin_challenger as M
from models.nfl.contextual.qb_margin_cohort import validate_cohort
from research.evaluate_margin_system import evaluate, score_row, _bootstrap

PARENT = "nfl.integrated_context.qb.v1.research"
SETTLEMENT = "FULL_GAME_OT_REGULAR"
INFORMATION_SET = "RECONSTRUCTED_QB_OOF_PRIOR_SEASON_FITS"
LINES = [-14., -10., -7.5, -7., -6.5, -3.5, -3., 0., 3., 3.5, 6.5, 7., 7.5, 10., 14.]
SCALE_FEATURES = ["absolute_parent_margin"]


def require(value, code):
    if not value:
        raise ValueError(code)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    body = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        body = gzip.decompress(body)
    def bad_constant(value):
        raise ValueError("NONFINITE_JSON:" + value)
    return json.loads(body, parse_constant=bad_constant)


def write(path, value):
    with Path(path).open("x") as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")


def write_gzip(path, value):
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with Path(path).open("xb") as f:
        f.write(gzip.compress(body, mtime=0))


def check_design(design):
    require(design["parent_model_id"] == PARENT, "EXACT_QB_PARENT_REQUIRED")
    require(design["information_set"] == INFORMATION_SET and design["settlement"] == SETTLEMENT,
            "STUDY_SCOPE_MISMATCH")
    require(design["training_seasons"] == [2019, 2020, 2021, 2022] and
            design["evaluation_seasons"] == [2023, 2024, 2025], "PREREGISTERED_SPLIT_REQUIRED")
    require(design["scale_features"] == SCALE_FEATURES, "PREREGISTERED_FEATURES_REQUIRED")
    require(design["home_handicaps"] == LINES, "PREREGISTERED_LINES_REQUIRED")
    bs = design["bootstrap"]
    require(bs["replicates"] == 2000 and bs["seed"] == 7192026 and bs["block_length"] == 4 and
            bs["unit"] == "week", "PREREGISTERED_BOOTSTRAP_REQUIRED")
    require(design["evaluation_fit_as_of_utc"] == "2023-07-01T00:00:00Z" and
            design["deployment_fit_as_of_utc"] == "2026-07-01T00:00:00Z", "PREREGISTERED_FIT_WINDOWS_REQUIRED")
    require(design.get("action_authority", False) is False and
            design.get("promotion_authority", False) is False, "RESEARCH_ONLY")


def split_rows(rows, design, *, check_counts=True):
    """Refuse mixed arms, fabricated split labels, duplicate events and leakage."""
    require(isinstance(rows, list) and bool(rows), "COHORT_ROWS_REQUIRED")
    seen = set()
    for row in rows:
        eid = D.identity(row["event_id"], "EVENT_ID")
        require(eid not in seen, "DUPLICATE_COHORT_EVENT")
        seen.add(eid)
        require(type(row["season"]) is int and row["season"] in range(2019, 2026), "SEASON_SCOPE_INVALID")
        require(row["league"] == "nfl" and row["product"] == "margin" and
                row["parent_model_id"] == PARENT and row["settlement"] == SETTLEMENT and
                row["information_set"] == INFORMATION_SET, "COHORT_SCOPE_MISMATCH")
        require(row["prediction_kind"] == "CHRONOLOGICAL_OUT_OF_TIME" and row["market_input"] is False,
                "COHORT_OUT_OF_TIME_REQUIRED")
        require(row.get("label_in_sample", False) is False and row.get("oof", True) is True,
                "CONTRADICTORY_OOF_EVIDENCE")
        require(row.get("historical_availability_proven") is False, "RECONSTRUCTED_HISTORY_LABEL_REQUIRED")
        require(set(row["scale_features"]) == set(SCALE_FEATURES) and
                math.isclose(D.finite(row["scale_features"][SCALE_FEATURES[0]]),
                             abs(D.finite(row["predicted_mean"])), rel_tol=0, abs_tol=1e-12),
                "SCALE_FEATURE_NOT_PARENT_DERIVED")
        D.source_hash(row["forecast_sha256"])
        D.source_hash(row["result_source_sha256"])
        require(D.finite(row["observed"]) == round(row["observed"]), "INTEGER_OBSERVED_MARGIN_REQUIRED")
        D.outcome(D.finite(row["observed"]), league="nfl", product="margin", settlement=SETTLEMENT,
                  line=0., side="HOME")
        require(D.stamp(row["parent_fit_cutoff"]) <= D.stamp(row["forecast_cutoff"]) <
                D.stamp(row["start_time_utc"]) <= D.stamp(row["result_available_at"]),
                "COHORT_CHRONOLOGY_INVALID")
    ordered = sorted(rows, key=lambda r: (D.stamp(r["forecast_cutoff"]), r["event_id"]))
    train = [r for r in ordered if r["season"] in design["training_seasons"]]
    later = [r for r in ordered if r["season"] in design["evaluation_seasons"]]
    require(bool(train) and bool(later), "BOTH_SPLITS_REQUIRED")
    require(max(D.stamp(r["result_available_at"]) for r in train) <
            D.stamp(design["evaluation_fit_as_of_utc"]) <=
            min(D.stamp(r["forecast_cutoff"]) for r in later), "EXTERNAL_SPLIT_LEAKAGE")
    require(max(D.stamp(r["result_available_at"]) for r in ordered) <
            D.stamp(design["deployment_fit_as_of_utc"]), "DEPLOYMENT_FIT_LEAKAGE")
    if check_counts:
        require((len(train), len(later), len(ordered)) == (1055, 816, 1871), "QUALIFIED_COHORT_COUNT_CHANGED")
    return train, later, ordered


def log_summary(values):
    zeros = sum(v is None for v in values)
    return {"mean": None if zeros else float(np.mean(values)) if values else None,
            "n": len(values), "zero_probability_outcomes": zeros,
            "status": "INFINITE_ZERO_SUPPORT" if zeros else "AVAILABLE" if values else "NO_ROWS"}


def conditional_nonpush(probabilities, actual):
    """Observed pushes are excluded; undefined non-push mass stays explicit."""
    if actual == "push":
        return None
    mass = probabilities["win"] + probabilities["loss"]
    if mass <= 0:
        return {"probability": None, "brier": None, "log_loss": None,
                "status": "ZERO_NONPUSH_SUPPORT"}
    p = probabilities["win"] / mass
    y = int(actual == "win")
    chosen = p if y else 1 - p
    return {"probability": p, "brier": (p - y) ** 2,
            "log_loss": -math.log(chosen) if chosen > 0 else None,
            "status": "AVAILABLE"}


def additional_diagnostics(rows, baseline_id, challenger_id, bootstrap):
    """Line diagnostics and conditional scores with equal-event paired bootstrap."""
    by_model = defaultdict(list)
    paired = defaultdict(dict)
    monotone_checks = []
    for row in rows:
        mid, eid = row["distribution"]["model_id"], row["distribution"]["provenance"]["event_id"]
        scored = score_row(row)
        items = sorted(scored["contracts"].values(), key=lambda c: c["line"])
        wins = np.asarray([c["probabilities"]["win"] for c in items])
        valid = bool(np.all(np.diff(wins) >= -1e-12))
        require(valid, "NONMONOTONE_COVER_LADDER")
        monotone_checks.append(valid)
        for item in items:
            item = dict(item)
            item.update(event_id=eid, start_time_utc=row["start_time_utc"], season=row["season"],
                        conditional_nonpush=conditional_nonpush(item["probabilities"], item["outcome"]))
            by_model[mid].append(item)
            paired[(eid, item["line"])][mid] = item
    summaries = {}
    for mid, items in by_model.items():
        lines = []
        for line in LINES:
            selected = [r for r in items if r["line"] == line]
            cond = [r["conditional_nonpush"] for r in selected if r["conditional_nonpush"] is not None]
            finite_brier = [r["brier"] for r in cond if r["brier"] is not None]
            lines.append({"home_handicap": line, "events": len(selected),
                "observed_cover_rate": float(np.mean([r["outcome"] == "win" for r in selected])),
                "predicted_cover_rate": float(np.mean([r["probabilities"]["win"] for r in selected])),
                "observed_push_rate": float(np.mean([r["outcome"] == "push" for r in selected])),
                "predicted_push_rate": float(np.mean([r["probabilities"]["push"] for r in selected])),
                "three_way_brier_category_sum": float(np.mean([r["brier_category_sum"] for r in selected])),
                "three_way_log_loss": log_summary([r["category_log_loss"] for r in selected]),
                "conditional_nonpush": {"events": len(cond), "excluded_pushes": len(selected) - len(cond),
                    "undefined_nonpush_mass": len(cond) - len(finite_brier),
                    "brier": float(np.mean(finite_brier)) if len(finite_brier) == len(cond) and cond else None,
                    "log_loss": log_summary([r["log_loss"] for r in cond]),
                    "probability_basis": "EXCLUDING_PUSHES"}})
        summaries[mid] = {"by_home_handicap": lines,
            "key_number_push_reliability": [r for r in lines if abs(r["home_handicap"]) in (3., 7.)]}
    metric_pairs = {"conditional_nonpush_brier": [], "conditional_nonpush_log_loss": []}
    for (eid, line), items in paired.items():
        require(set(items) == {baseline_id, challenger_id}, "ADDITIONAL_PAIR_MISMATCH")
        a, b = items[baseline_id], items[challenger_id]
        require(a["outcome"] == b["outcome"], "ADDITIONAL_OUTCOME_MISMATCH")
        if a["outcome"] == "push":
            continue
        for metric in ("brier", "log_loss"):
            metric_pairs["conditional_nonpush_" + metric].append((eid, a["start_time_utc"],
                a["conditional_nonpush"][metric], b["conditional_nonpush"][metric]))
    deltas = {k: _bootstrap(v, seed=bootstrap["seed"], draws=bootstrap["replicates"],
                           block_length=bootstrap["block_length"], block_unit=bootstrap["unit"])
              for k, v in metric_pairs.items()}
    return {"summaries": summaries, "paired_deltas_challenger_minus_baseline": deltas,
            "cover_ladder_monotonicity": {"checks": len(monotone_checks), "all_pass": all(monotone_checks)},
            "line_role": "FIXED_DIAGNOSTIC_GRID_NOT_OBSERVED_MARKET", "independent_sample_unit": "EVENT"}


def run(cohort_path, design_path, output, *, prereg_commit):
    require(re.fullmatch(r"[0-9a-f]{40}", prereg_commit) is not None, "PREREG_COMMIT_REQUIRED")
    output = Path(output)
    require(not output.exists(), "IMMUTABLE_OUTPUT_ALREADY_EXISTS")
    design, cohort = read(design_path), read(cohort_path)
    check_design(design)
    qualification = validate_cohort(cohort, cohort_path)
    rows = cohort["rows"] if isinstance(cohort, dict) else cohort
    train, later, all_rows = split_rows(rows, design)
    for path, expected in design.get("code_sha256", {}).items():
        require(sha(ROOT / path) == expected, "PREREG_CODE_DRIFT:" + path)
    # The design binds immutable original files. Cohort builder binds derived rows;
    # source hashes may be represented as records or a direct hash dictionary.
    source_hashes = cohort.get("source_sha256", {}) if isinstance(cohort, dict) else {}
    expected_sources = design.get("input_sha256", {})
    require(bool(expected_sources), "PREREG_SOURCE_HASHES_REQUIRED")
    actual_source_values = set(source_hashes.values()) if source_hashes else set()
    if not actual_source_values and isinstance(cohort, dict):
        actual_source_values = set(cohort.get("source_hashes", {}).values())
    require(set(expected_sources.values()) <= actual_source_values, "COHORT_SOURCE_BINDING_MISMATCH")
    output.mkdir(parents=True)
    write(output / "design.json", design)
    write(output / "source_validation.json", qualification)
    write(output / "execution_design_binding.json", {"created_at_utc": D.writer_clock(),
        "design_sha256": sha(design_path), "cohort_sha256": sha(cohort_path),
        "prereg_commit": prereg_commit, "source_sha256": source_hashes,
        "code_sha256": {str(p.relative_to(ROOT)): sha(p) for p in
            [Path(__file__), ROOT / 'models/nfl/contextual/qb_margin_cohort.py', ROOT / 'models/common/margin_challenger.py',
             ROOT / 'models/common/discrete_research.py', ROOT / 'research/evaluate_margin_system.py']},
        "source_validation_sha256": sha(output / "source_validation.json"),
        "training_n": len(train), "evaluation_n": len(later), "deployment_refit_n": len(all_rows)})
    scope = dict(league="nfl", settlement=SETTLEMENT, parent_model_id=PARENT, information_set=INFORMATION_SET)
    baseline = D.fit_residuals(train, product="margin", method="empirical",
                              fitted_at=design["evaluation_fit_as_of_utc"], **scope)
    write(output / "evaluation_baseline.json", baseline)
    candidate = M.fit(train, fitted_at=design["evaluation_fit_as_of_utc"],
                      scale_features=SCALE_FEATURES, **scope)
    write(output / "evaluation_challenger.json", candidate)
    print(json.dumps({"phase": "fit_complete_before_evaluation", "training_n": len(train),
                      "candidate": candidate["model_id"]}), flush=True)
    retained = []
    for i, row in enumerate(later):
        args = dict(mean=row["predicted_mean"], event_id=row["event_id"], cutoff=row["forecast_cutoff"],
                    parent_model_id=PARENT, information_set=INFORMATION_SET,
                    parent_forecast_sha256=row["forecast_sha256"])
        laws = [D.predict(baseline, **args), M.predict(candidate, start_time_utc=row["start_time_utc"],
                                                       scale_features=row["scale_features"], **args)]
        for law in laws:
            retained.append({**{k: row[k] for k in ("observed", "start_time_utc", "result_available_at",
                "result_source_sha256", "parent_fit_cutoff", "season")}, "distribution": law,
                "distribution_fit_cutoff": design["evaluation_fit_as_of_utc"],
                "contracts": [{"line": h, "side": "HOME", "line_role": "DIAGNOSTIC_GRID"} for h in LINES]})
        if (i + 1) % 100 == 0:
            print(json.dumps({"phase": "evaluation_distributions", "events": i + 1}), flush=True)
    write_gzip(output / "evaluation_rows.json.gz", retained)
    bs = design["bootstrap"]
    report = evaluate(retained, baseline_id=baseline["model_id"], challenger_id=candidate["model_id"],
                      bootstrap=bs["replicates"], seed=bs["seed"], block_length=bs["block_length"], block_unit=bs["unit"])
    write(output / "evaluation.json", report)
    extras = additional_diagnostics(retained, baseline["model_id"], candidate["model_id"], bs)
    write(output / "cover_diagnostics.json", extras)
    # Evaluation results are retained before the predeclared all-history refit.
    # No parameter or feature choice is conditioned on these external scores.
    deployment = M.fit(all_rows, fitted_at=design["deployment_fit_as_of_utc"], scale_features=SCALE_FEATURES, **scope)
    write(output / "deployment_model.json", deployment)
    delta = report["paired"]["deltas_challenger_minus_baseline"]["crps"]
    interval = delta["ci95"]
    diagnostic = "INCONCLUSIVE" if interval is None or interval[0] <= 0 <= interval[1] else (
        "FAVORABLE" if interval[1] < 0 else "UNFAVORABLE")
    candidate_summary = report["paired"]["summaries_matched"][candidate["model_id"]]
    screen_spec = design["historical_screen"]
    brier_delta = report["paired"]["deltas_challenger_minus_baseline"]["brier_category_sum"]["delta"]
    coverage95 = candidate_summary["prediction_intervals"]["0.95"]["coverage"]
    screen_checks = {
        "crps_delta": delta["delta"] <= screen_spec["crps_delta_max"],
        "crps_ci_upper": interval is not None and interval[1] < screen_spec["crps_ci_upper_max"],
        "three_way_brier_delta": brier_delta is not None and brier_delta <= screen_spec["three_way_brier_delta_max"],
        "coverage_95": screen_spec["coverage_95_min"] <= coverage95 <= screen_spec["coverage_95_max"],
        "zero_support_outcomes": candidate_summary["distribution_log_score"]["zero_probability_outcomes"] == screen_spec["zero_supported_outcomes"],
    }
    compact = {"schema": "nfl.qb_margin_evaluation.v1", "created_at_utc": D.writer_clock(),
        "model_artifact_sha256": deployment["artifact_sha256"], "deployment_model_id": deployment["model_id"],
        "evaluated_model_artifact_sha256": candidate["artifact_sha256"],
        "evaluated_model_id": candidate["model_id"], "baseline_model_id": baseline["model_id"],
        "parent_model_id": PARENT, "information_set": INFORMATION_SET, "settlement": SETTLEMENT,
        "status": "HOLD", "execution_status": "COMPLETED", "numerical_validity": "PASS",
        "predictive_validation": "HOLD", "publication_eligibility": "INELIGIBLE", "wagering_authority": "OFF",
        "action_authority": False, "prospective_grade_eligible": False, "market_input": False,
        "prereg_commit": prereg_commit, "design_sha256": sha(design_path), "cohort_sha256": sha(cohort_path),
        "evaluation_report_sha256": sha(output / "evaluation.json"),
        "cover_diagnostics_sha256": sha(output / "cover_diagnostics.json"),
        "evaluated_training_n": len(train), "evaluation_n": len(later), "deployment_training_n": len(all_rows),
        "training_seasons": design["training_seasons"], "evaluation_seasons": design["evaluation_seasons"],
        "deployment_seasons": sorted({r["season"] for r in all_rows}),
        "deployment_refit": {"policy": "SAME_PREREGISTERED_ALGORITHM_REFIT_ALL_QUALIFIED_HISTORY",
            "same_algorithm_and_feature_policy": True, "same_selected_numeric_parameters_required": False,
            "deployment_artifact_directly_evaluated": False,
            "evaluation_is_of_training_policy_and_prior_fitted_instance": True},
        "primary_metric": {"name": "CRPS", "paired_delta": delta, "historical_diagnostic": diagnostic},
        "historical_screen": {"status": "PASS" if all(screen_checks.values()) else "NOT_PASSED",
            "checks": screen_checks, "criteria": screen_spec, "grants_promotion": False},
        "historical_availability_proven": False, "untouched_holdout": False,
        "hold_reasons": ["REUSED_HISTORICAL_COHORT", "HISTORICAL_AVAILABILITY_RECONSTRUCTED",
                         "PROSPECTIVE_VALIDATION_REQUIRED", "DEPLOYMENT_REFIT_IS_DISTINCT_ARTIFACT"],
        "limitations": ["Parent margin fitting inherited exclusion of tied games through complete-target fitting; held-out tied outcomes are retained.",
                        "No market prices or historical market superiority test; fixed handicap grid is diagnostic.",
                        "An exact numerical replay does not establish probability calibration."]}
    write(output / "registration_evaluation.json", compact)
    write(output / "manifest.json", {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()})
    print(json.dumps({"phase": "completed", "output": str(output), "historical_diagnostic": diagnostic,
                      "crps_delta": delta, "deployment_model_id": deployment["model_id"], "status": "HOLD"}), flush=True)
    return compact


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cohort", type=Path, required=True)
    p.add_argument("--design", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--prereg-commit", required=True)
    a = p.parse_args(argv)
    return run(a.cohort, a.design, a.output, prereg_commit=a.prereg_commit)


if __name__ == "__main__":
    main()
