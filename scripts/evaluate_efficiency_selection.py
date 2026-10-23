#!/usr/bin/env python3
"""Exercise frozen-grid forecaster/selector diagnostics on retained runner output."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.efficiency.selection_diagnostics import analyze
from research.efficiency.integrity import verify_component_receipt


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-count", type=int, default=2000)
    args = parser.parse_args()
    run = args.run.resolve(strict=True)
    protocol = read(args.protocol)
    report = read(run/"report.json")
    league = report["league"]
    history_path = Path(report["history"]["path"])
    if digest_file(history_path) != report["history"]["sha256"]:
        raise ValueError("BOUND_HISTORY_CHANGED")
    history = read(history_path)
    games = history["games"] if league == "cfb" else history["score_history"]
    event_lookup = {g.get("event_id", "CFB:"+str(g.get("game_id"))): g for g in games}
    population = read(run/"population.json")
    for item in population:
        event = event_lookup[item["event_id"]]
        start = event.get("start_time_utc", event.get("start_date"))
        parsed = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(timezone.utc)
        item["block_id"] = f"{event['season']}-W{event['week']:02d}" if league == "cfb" else f"{parsed.isocalendar().year}-W{parsed.isocalendar().week:02d}"
        home = event.get("home_score", event.get("home_points"))
        away = event.get("away_score", event.get("away_points"))
        item["actual_home_win"] = int(home > away) if home is not None and away is not None else None
    args.output.mkdir(parents=True, exist_ok=False)
    invocation = {"run_id": f"{league}-selection-evaluation-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
        "source_run_id": report["run_id"], "source_run": str(run), "protocol_sha256": digest_file(args.protocol),
        "command": [sys.executable, *sys.argv], "bootstrap_count": args.bootstrap_count,
        "code_sha256": {str(p.relative_to(ROOT)): digest_file(p) for p in [Path(__file__), ROOT/"research/efficiency/selection_diagnostics.py", ROOT/"research/efficiency/evaluation.py", ROOT/"research/efficiency/integrity.py", ROOT/"research/selection_evaluation.py"]},
        "started_at_utc": datetime.now(timezone.utc).isoformat()}
    write(args.output/"invocation.json", invocation)
    summaries, source_files = {}, {}
    for stage in ("efficiency", "joint"):
        path = run/stage
        if not (path/"predictions.json").exists():
            summaries[stage] = {"status": "BLOCKED", "dependency": read(path/"disposition.json")}
            continue
        for name in ("predictions.json", "excluded.json", "state.json", "receipt_index.json"):
            source_files[str(path/name)] = digest_file(path/name)
        rows, excluded, state = read(path/"predictions.json"), read(path/"excluded.json"), read(path/"state.json")
        evaluation_ids = {row["event_id"] for row in rows}
        if evaluation_ids & set(state["training_event_ids"]):
            raise ValueError("TRAINING_EVALUATION_EVENT_OVERLAP")
        receipt_index = {r["event_id"]: r["receipt_sha256"] for r in read(path/"receipt_index.json")}
        if set(receipt_index) != evaluation_ids:
            raise ValueError("RECEIPT_COVERAGE_MISMATCH")
        verified = []
        for row in rows:
            receipt_path = path/"receipts"/(row["event_id"].replace(":", "_")+".json")
            receipt = read(receipt_path)
            verify_component_receipt(receipt)
            if receipt["event_id"] != row["event_id"] or receipt["receipt_sha256"] != receipt_index[row["event_id"]]:
                raise ValueError("RECEIPT_IDENTITY_CONFLICT")
            if receipt["forecast"]["p_home"] != row["challenger"]["p_home"]:
                raise ValueError("SCORED_PROBABILITY_RECEIPT_CONFLICT")
            for name in ("training_max_start_utc", "training_max_label_available_at_utc", "training_max_available_at_utc"):
                if state.get(name) and datetime.fromisoformat(state[name].replace("Z", "+00:00")) >= datetime.fromisoformat(receipt["cutoff_utc"].replace("Z", "+00:00")):
                    raise ValueError("TRAINING_NOT_EARLIER_THAN_FORECAST")
            verified.append({"event_id": row["event_id"], "receipt_sha256": receipt["receipt_sha256"]})
        diagnostics = analyze(rows, population, excluded, league=league,
                              discovery_ids=protocol["discovery_events_excluded"], bootstrap_count=args.bootstrap_count)
        diagnostics["receipt_verification"] = {"count": len(verified), "all_internal_hashes_and_chronology_verified": True,
            "verification_scope": "Internal receipt constraints and training cutoff comparisons; source extraction and feature reconstruction require separate audit",
            "historical_source_availability_authenticated": False,
            "training_max_available_at_missing": state.get("training_max_available_at_utc", state.get("training_max_label_available_at_utc")) is None}
        write(args.output/(stage+".json"), diagnostics)
        write(args.output/(stage+"-receipt-verification.json"), verified)
        summaries[stage] = {"status": "COMPLETED", "n_population": diagnostics["n_population"],
            "n_common_forecasts": diagnostics["n_common_forecasts"], "n_excluded": diagnostics["n_excluded"],
            "n_receipts_verified": len(verified), "operational_selected": diagnostics["operational_eligibility"]["n_selected"],
            "winner": diagnostics["forecast_metrics"]["products"]["winner"],
            "selector_curves": {arm: diagnostics["selectors"][arm]["curve"] for arm in ("baseline", "challenger")}}
        print(json.dumps({"stage": stage, "n": len(rows), "receipts_verified": len(verified)}), flush=True)
    if any(digest_file(Path(path)) != sha for path, sha in source_files.items()):
        raise ValueError("RAW_RESEARCH_OUTPUT_MUTATED")
    completed = {**invocation, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                 "stages": summaries, "raw_source_files_unchanged": source_files,
                 "confirmation_claim": False, "promotion": False, "wagering_authority": "OFF"}
    write(args.output/"report.json", completed)
    write(args.output/"manifest.json", {p.name: digest_file(p) for p in sorted(args.output.iterdir()) if p.is_file()})
    print(json.dumps({"run_id": completed["run_id"], "stages": {s: {k: v.get(k) for k in ("status", "n_population", "n_common_forecasts", "n_receipts_verified", "operational_selected")} for s, v in summaries.items()}}))


if __name__ == "__main__":
    main()
