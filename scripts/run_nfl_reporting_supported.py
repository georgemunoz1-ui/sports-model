#!/usr/bin/env python3
"""Explicit additive NFL reporting-supported research runner; no promotion.

Uses the existing source-bound native package and selected-QB default. The
frozen integrated runner, adapters and numerical identity source remain intact.
Replay and pre-start local execution have distinct receipts; neither is a
canonical registration or an authorization to publish/wager.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models.nfl.contextual.recovered_inference import digest, utc
from models.nfl.contextual.runtime_reporting_support_v1 import PROCEDURE_ID, run
from pipelines.cards.adapters import nfl
from pipelines.cards.nfl_flip_integration import attach_diagnostic


def _write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _persist(output, event_id, bundle, winner, scores, package, replay):
    """Stage the complete event artifact before exposing its final directory."""
    import numpy as np
    if event_id in {".", ".."} or Path(event_id).name != event_id:
        raise ValueError("INVALID_EVENT_OUTPUT_KEY")
    final = output / event_id
    if final.exists():
        raise ValueError("IMMUTABLE_EVENT_OUTPUT_EXISTS")
    now = dt.datetime.now(dt.timezone.utc)
    if utc(bundle["cutoff_utc"]) > now:
        raise ValueError("FUTURE_INFORMATION_CUTOFF_AT_WRITE")
    if not replay and now >= utc(bundle["event"]["start_time_utc"]):
        raise ValueError("START_CROSSED_BEFORE_PERSISTENCE")
    from models.nfl.contextual.capabilities import validate_report
    validate_report(bundle["capability_report"])
    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=output))
    try:
        _write(stage / "forecast.json", bundle)
        np.save(stage / "winner_draws.npy", winner, allow_pickle=False)
        if scores is not None:
            np.save(stage / "score_draws.npy", scores, allow_pickle=False)
        receipt = {
            "schema": "nfl.reporting_supported_execution.v1",
            "execution_mode": "RETROSPECTIVE_DIAGNOSTIC" if replay else "PRESTART_RESEARCH_EXECUTION",
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "information_cutoff_utc": bundle["cutoff_utc"],
            "forecast_identity": bundle["identity"],
            "execution_identity": bundle["execution_identity"],
            "runtime_procedure_id": PROCEDURE_ID,
            "source_package_sha256": digest(package),
            "entrypoint_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "forecast_sha256": hashlib.sha256((stage / "forecast.json").read_bytes()).hexdigest(),
            "prospective_registration_verified": False,
            "canonical_prospective_eligible": False, "publication_allowed": False,
            "action_authority": False, "wagering_status": "OFF",
        }
        _write(stage / "execution_receipt.json", receipt)
        _write(stage / "manifest.json", {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(stage.iterdir()) if p.is_file()})
        if not replay and dt.datetime.now(dt.timezone.utc) >= utc(bundle["event"]["start_time_utc"]):
            raise ValueError("START_CROSSED_BEFORE_PERSISTENCE")
        if final.exists():
            raise ValueError("IMMUTABLE_EVENT_OUTPUT_EXISTS")
        os.rename(stage, final)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return final


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--simulations", type=int, default=100000)
    parser.add_argument("--model-id")
    parser.add_argument("--event-id")
    parser.add_argument("--mode", choices=["research_pregame"], default="research_pregame")
    parser.add_argument("--weekly-state-store", type=Path)
    parser.add_argument("--weekly-state-id")
    parser.add_argument("--replay-cutoff-utc", help="Retained-input execution now; never pregame registration")
    args = parser.parse_args(argv)
    for name in ("model_id", "event_id", "replay_cutoff_utc", "weekly_state_id"):
        value = getattr(args, name)
        if value is not None and (not value.strip() or value != value.strip()):
            parser.error("EMPTY_OR_PADDED_EXPLICIT_ARGUMENT:" + name)
    if bool(args.weekly_state_store) != bool(args.weekly_state_id):
        parser.error("Both weekly-state store and ID are required")
    if not 1 <= args.simulations <= 1000000:
        parser.error("DRAW_COUNT_RANGE")
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = args.replay_cutoff_utc if args.replay_cutoff_utc is not None else now.isoformat()
    if utc(cutoff) > now:
        parser.error("Replay cutoff must not be in the future")
    # Read one native package snapshot, then derive its schedule from that same
    # object. The immutable adapter verifies model/schema/package bindings.
    context = nfl.build_context([], cutoff)
    package = context["package"]
    if args.date not in package["covered_dates"]:
        raise ValueError("NFL_DATE_NOT_CAPTURED:" + args.date)
    if utc(package["captured_at_utc"]) > utc(cutoff):
        raise ValueError("SCHEDULE_AFTER_CUTOFF")
    events = [e for e in package["events"] if e["gameday"] == args.date]
    if args.event_id:
        events = [e for e in events if e["event_id"] == args.event_id]
        if not events:
            raise ValueError("EVENT_NOT_IN_CAPTURED_SCHEDULE")
    if len({e["event_id"] for e in events}) != len(events):
        raise ValueError("DUPLICATE_EVENT_ID")
    default = json.loads((nfl.DATA / "runtime.json").read_text())["default_research_model"]
    if args.output.exists():
        raise ValueError("IMMUTABLE_RUN_OUTPUT_EXISTS")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="." + args.output.name + ".stage-",
                                    dir=args.output.parent))
    try:
        return _execute(args, cutoff, context, package, events, default, staging)
    except BaseException as exc:
        # Preserve any already frozen event artifacts for inspection. The final
        # output name remains unused, so a retry does not overwrite those bytes.
        failure = {"status": "INCOMPLETE_UNPUBLISHED_RUN", "reason": str(exc),
                   "retained_staging_directory": str(staging),
                   "requested_output": str(args.output), "action_authority": False}
        try:
            _write(staging / "incomplete_run.json", failure)
        except OSError:
            pass
        print(json.dumps(failure), file=sys.stderr)
        raise


def _execute(args, cutoff, context, package, events, default, staging):
    rows = []
    for event in events:
        row = {"event_id": event["event_id"],
               "selected_model_id": args.model_id if args.model_id is not None else default,
               "status": "FAILED", "reason": None, "forecast_directory": None,
               "forecast_identity": None}
        try:
            if utc(cutoff) >= utc(event["start_time_utc"]):
                row.update(status="POST_START", reason="NOT_PREGAME")
                continue
            packet = package["event_inputs"][event["event_id"]]
            if args.weekly_state_store:
                from models.nfl.contextual.weekly_state import bind_packet
                packet = bind_packet(packet, context["model"], event, cutoff,
                                     args.weekly_state_store, args.weekly_state_id)
            from models.nfl.contextual.week2 import applies, policy
            selected = (args.model_id if args.model_id is not None else
                        (policy()["default_reference_model"] if applies(packet["base"], event) else default))
            row["selected_model_id"] = selected
            bundle, winner, scores = run(
                context["model"], context["recovered"], packet["base"], packet["context"],
                event, cutoff, args.simulations, model_id=selected)
            bundle = attach_diagnostic(bundle, context["model"])
            path = _persist(staging, event["event_id"], bundle, winner, scores,
                            package, args.replay_cutoff_utc is not None)
            row.update(status="COMPLETED", forecast_directory=path.name,
                       forecast_identity=bundle["identity"])
        except (ValueError, KeyError, TypeError, OSError) as exc:
            reason = str(exc)
            row.update(status="REFUSED" if reason.startswith("REFUSE_") else "FAILED",
                       reason=reason)
        finally:
            rows.append(row)
    counts = {status: sum(row["status"] == status for row in rows)
              for status in ("COMPLETED", "REFUSED", "POST_START", "FAILED")}
    coverage = {
        "schema": "nfl.reporting_supported_coverage.v1", "runtime_procedure_id": PROCEDURE_ID,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "cutoff_utc": cutoff,
        "execution_mode": "RETROSPECTIVE_DIAGNOSTIC" if args.replay_cutoff_utc is not None else "PRESTART_RESEARCH_EXECUTION",
        "date": args.date, "source_package_sha256": digest(package),
        "events": rows, "counts": counts, "action_authority": False,
        "canonical_prospective_eligible": False,
    }
    _write(staging / "coverage.json", coverage)
    if args.output.exists():
        raise ValueError("IMMUTABLE_RUN_OUTPUT_EXISTS")
    os.rename(staging, args.output)
    print(json.dumps(coverage, indent=2, allow_nan=False))
    return 2 if any(row["status"] != "COMPLETED" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
