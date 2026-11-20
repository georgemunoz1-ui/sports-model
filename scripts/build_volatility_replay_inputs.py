#!/usr/bin/env python3
"""Build disclosed retrospective joint-score inputs and diagnostic matrix fits.

Only NBA/NHL/MLS replay cohorts with matching product rows are supported. The
simulated timestamps are retained as labels, never represented as captures.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.common import discrete_research as D
from models.common import volatility_matrix_v1 as V

LEAGUES = {"nba", "nhl", "mls"}
TIMING = "SIMULATED_START_MINUS_1H_AND_START_PLUS_48H_NOT_CAPTURE"
CAPTURE = "RETROSPECTIVE_RECONSTRUCTION"
IDENTITY_FIELDS = ("league", "settlement", "parent_model_id", "information_set",
                   "market_input", "prediction_kind", "result_source_sha256",
                   "parent_fit_cutoff", "forecast_cutoff", "start_time_utc",
                   "result_available_at", "source_capture_kind", "timestamp_basis",
                   "historical_availability_proven")


def _read(path):
    raw = path.read_bytes()
    with gzip.GzipFile(fileobj=__import__("io").BytesIO(raw), mode="rb") as handle:
        payload = json.load(handle)
    rows = payload["residual"]
    return rows, hashlib.sha256(raw).hexdigest()


def _score(total, margin):
    home, away = (total + margin) / 2.0, (total - margin) / 2.0
    if min(D.finite(home), D.finite(away)) < 0:
        raise ValueError("NEGATIVE_DERIVED_SCORE")
    return home, away


def build_rows(input_root, league):
    if league not in LEAGUES:
        raise ValueError("REPLAY_CONVERTER_LEAGUE_UNSUPPORTED")
    directory = Path(input_root) / league
    margin, margin_hash = _read(directory / "margin_cohort.json.gz")
    total, total_hash = _read(directory / "total_cohort.json.gz")
    for rows, product in ((margin, "margin"), (total, "total")):
        if len(rows) < 30 or any(r.get("product") != product for r in rows):
            raise ValueError("REPLAY_COHORT_INVALID")
        ids = [r["event_id"] for r in rows]
        if len(set(ids)) != len(ids):
            raise ValueError("DUPLICATE_TRAINING_EVENT")
    totals = {r["event_id"]: r for r in total}
    if set(totals) != {r["event_id"] for r in margin}:
        raise ValueError("PRODUCT_EVENT_SET_MISMATCH")
    output = []
    for m in margin:
        t = totals[m["event_id"]]
        if any(m.get(k) != t.get(k) for k in IDENTITY_FIELDS):
            raise ValueError("PRODUCT_ROW_IDENTITY_MISMATCH")
        if m.get("source_capture_kind") != CAPTURE or m.get("timestamp_basis") != TIMING:
            raise ValueError("REPLAY_TIMING_LABEL_MISMATCH")
        if m.get("historical_availability_proven") is not False:
            raise ValueError("RETROSPECTIVE_AVAILABILITY_MUST_REMAIN_FALSE")
        predicted_home, predicted_away = _score(D.finite(t["predicted_mean"]), D.finite(m["predicted_mean"]))
        actual_home_float, actual_away_float = _score(D.finite(t["observed"]), D.finite(m["observed"]))
        if actual_home_float != round(actual_home_float) or actual_away_float != round(actual_away_float):
            raise ValueError("DERIVED_SCORE_PARITY_MISMATCH")
        actual_home, actual_away = int(actual_home_float), int(actual_away_float)
        V._check_final(actual_home, actual_away, m["league"], m["settlement"])
        composite = D.digest({
            "derivation": "COMPOSITE_MARGIN_TOTAL_FORECAST_HASH_HOME_MINUS_AWAY_V1",
            "event_id": m["event_id"], "margin_forecast_sha256": m["forecast_sha256"],
            "total_forecast_sha256": t["forecast_sha256"], "orientation": "HOME_MINUS_AWAY"})
        output.append({
            "event_id": m["event_id"], "league": m["league"], "settlement": m["settlement"],
            "parent_model_id": m["parent_model_id"], "information_set": m["information_set"],
            "market_input": m["market_input"], "prediction_kind": m["prediction_kind"],
            "forecast_sha256": composite, "result_source_sha256": m["result_source_sha256"],
            "parent_fit_cutoff": m["parent_fit_cutoff"], "forecast_cutoff": m["forecast_cutoff"],
            "start_time_utc": m["start_time_utc"], "result_available_at": m["result_available_at"],
            "predicted_home": predicted_home, "predicted_away": predicted_away,
            "actual_home": actual_home, "actual_away": actual_away,
            "scale_features": {"predicted_total": D.finite(t["predicted_mean"]),
                               "absolute_parent_margin": abs(D.finite(m["predicted_mean"]))},
            "source_capture_kind": CAPTURE, "timestamp_basis": TIMING,
            "historical_availability_proven": False,
            "forecast_hash_derivation": "COMPOSITE_MARGIN_TOTAL_FORECAST_HASH_HOME_MINUS_AWAY_V1"})
    output.sort(key=lambda r: (D.stamp(r["forecast_cutoff"]), r["event_id"]))
    provenance = {"source_capture_kind": CAPTURE, "timestamp_basis": TIMING,
                  "historical_availability_proven": False,
                  "forecast_hash_derivation": "COMPOSITE_MARGIN_TOTAL_FORECAST_HASH_HOME_MINUS_AWAY_V1",
                  "score_derivation": "HOME_EQUALS_TOTAL_PLUS_MARGIN_OVER_TWO_AWAY_EQUALS_TOTAL_MINUS_MARGIN_OVER_TWO",
                  "source_files": {"margin_cohort.json.gz": margin_hash,
                                   "total_cohort.json.gz": total_hash},
                  "source_row_count": len(output),
                  "prospective_evidence": False}
    return output, provenance


def _write_json(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def run(league, input_root, output_root, fitted_at, methods=("empirical", "ledoit_wolf")):
    rows, provenance = build_rows(input_root, league)
    output = Path(output_root) / league
    output.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with (output / "joint_input_rows.json.gz").open("xb") as raw:
        with gzip.GzipFile(filename="joint_input_rows.json", mode="wb", fileobj=raw, mtime=0) as handle:
            handle.write(encoded)
    artifacts = []
    for method in methods:
        model = V.fit(rows, league=league, settlement=rows[0]["settlement"],
                      parent_model_id=rows[0]["parent_model_id"],
                      information_set=rows[0]["information_set"], fitted_at=fitted_at,
                      method=method, source_provenance=provenance)
        path = output / f"{method}.json"
        _write_json(path, model)
        artifacts.append({"method": method, "path": str(path), "model_id": model["model_id"],
                          "artifact_sha256": model["artifact_sha256"],
                          "volatility": V.volatility(model)})
    summary = {"schema": "sports.volatility_matrix_replay_fit.research.v1", "league": league,
               "fitted_at": fitted_at, "training_n": len(rows), "source_provenance": provenance,
               "joint_input_rows_sha256": hashlib.sha256(encoded).hexdigest(),
               "artifacts": artifacts, "status": "FITTED_RESEARCH_NOT_VALIDATED",
               "prospective_grade_eligible": False, "action_authority": False}
    summary["artifact_sha256"] = D.digest(summary)
    _write_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True, choices=sorted(LEAGUES))
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--fitted-at", required=True)
    parser.add_argument("--methods", nargs="+", default=["empirical", "ledoit_wolf"],
                        choices=["empirical", "ledoit_wolf"])
    args = parser.parse_args()
    result = run(args.league, args.input_root, args.output_root, args.fitted_at, tuple(args.methods))
    print(json.dumps({"league": args.league, "training_n": result["training_n"],
                      "status": result["status"], "artifacts": result["artifacts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
