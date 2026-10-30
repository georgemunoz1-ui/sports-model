"""Executed, independent efficiency experiments and real-card SHADOW sidecars.

Historical fits are explicitly reconstructed controls, never replacements for
the saved incumbent fits. SHADOW receipts are local research records; canonical
registration, publication and wagering permissions are not granted here.
"""
from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "efficiency-experiment-execution.v1"


def stamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc(value):
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("AWARE_TIMESTAMP_REQUIRED")
    return d.astimezone(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def read_bound(reference, base):
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise ValueError("EXACT_PATH_AND_SHA256_REFERENCE_REQUIRED")
    p = (Path(base) / reference["path"]).resolve(strict=True)
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("INPUT_HASH_MISMATCH:" + str(p))
    return json.loads(raw), p


def backend(league):
    if league not in {"cfb", "nba"}:
        raise ValueError("EFFICIENCY_LEAGUE_UNSUPPORTED")
    return importlib.import_module("models.experiments." + league + "_efficiency")


def targets(example):
    return example.get("targets", example.get("target"))


def reasons(example):
    return example.get("exclusion_reasons", example.get("reasons", []))


def prepare(league, history, *, future_events=None, cutoff=None):
    module = backend(league)
    if league == "nba":
        rows = copy.deepcopy(history["history"])
        for event in future_events or []:
            event = copy.deepcopy(event)
            event["final"] = False
            event["forecast_cutoff_utc"] = cutoff
            rows.append(event)
        return module.prepare_examples(rows)
    packet = copy.deepcopy(history)
    if future_events is not None:
        ids = {e["event_id"] for e in future_events}
        packet["games"] = [e for e in packet["games"] if e.get("completed") or e.get("event_id", "CFB:" + str(e.get("game_id"))) in ids]
        overlays = {e["event_id"]: e for e in future_events if "personnel_evidence" in e}
        if len(overlays) != sum("personnel_evidence" in e for e in future_events):
            raise ValueError("CFB_PERSONNEL_DUPLICATE_FUTURE_EVENT")
        known_ids = {e.get("event_id", "CFB:" + str(e.get("game_id"))) for e in packet["games"]}
        if set(overlays) - known_ids:
            raise ValueError("CFB_PERSONNEL_FUTURE_EVENT_NOT_IN_HISTORY")
        for event in packet["games"]:
            event_id = event.get("event_id", "CFB:" + str(event.get("game_id")))
            if event_id not in overlays:
                continue
            current, incoming = module.canonical_game(event), module.canonical_game(overlays[event_id])
            keys = ("event_id", "home_id", "away_id", "home_team", "away_team", "start_time_utc", "season", "week")
            if any(current[key] != incoming[key] for key in keys):
                raise ValueError("CFB_PERSONNEL_FUTURE_EVENT_IDENTITY_CONFLICT")
            if "personnel_evidence" in event and event["personnel_evidence"] != incoming["personnel_evidence"]:
                raise ValueError("CFB_PERSONNEL_FUTURE_EVIDENCE_CONFLICT")
            event["personnel_evidence"] = copy.deepcopy(incoming["personnel_evidence"])
    return module.prepare_examples(packet)


def fit_stage(module, league, training, stage):
    if stage == "personnel_v2" and league != "cfb":
        raise ValueError("PERSONNEL_V2_STAGE_CFB_ONLY")
    if league == "nba":
        return module.fit(training, {"stage": stage})
    if stage == "efficiency":
        return module.fit(training)
    if stage == "joint":
        if any(e["season"] > 2024 for e in training):
            raise ValueError("CFB_JOINT_FUTURE_TRAINING_SEASON")
        # The separately identified joint stage already specifies a 2023
        # mean-model fit and 2024 out-of-sample residual calibration.
        # Dispatch both populations explicitly; never calibrate on test rows.
        return module.fit_joint([e for e in training if e["season"] <= 2023],
                                [e for e in training if e["season"] == 2024])
    function = getattr(module, "fit_" + stage, None)
    if function is None:
        raise ValueError("CFB_" + stage.upper() + "_STAGE_NOT_FITTED")
    return function(training)


def predict_stage(module, league, fitted, example, simulations=0):
    if league == "nba":
        return module.predict(fitted, example, simulations=simulations)
    if fitted.get("stage_id") == "joint_distribution":
        forecast = module.predict_joint(fitted, example)
        if simulations:
            seed = int(digest({"model_id": fitted["model_id"],
                               "state_sha256": fitted["state_sha256"],
                               "event_id": example["event_id"],
                               "features": example["features"],
                               "n": simulations})[:16], 16)
            draws, receipt = module.simulate_joint(fitted, example, n=simulations, seed=seed)
            forecast["joint_draws"] = draws
            forecast["simulation"] = {**receipt, "n": receipt["count"],
                                      "p_home": receipt["home_win_probability"]}
        return forecast
    if fitted.get("stage_id") in {"joint", "joint_score", "personnel"}:
        function = getattr(module, "predict_" + fitted["stage_id"], None)
        if function is not None:
            return function(fitted, example, simulations=simulations) if "joint" in fitted["stage_id"] else function(fitted, example)
    return module.predict(fitted, example)


def sanitize_forecast(value):
    return {k: v for k, v in value.items() if k not in {"joint_draws"}}


def sources_for(example, history, fitted):
    rows = list(example.get("sources", example.get("source_bindings", [])))
    if fitted.get("stage_id") == "personnel_v2":
        from models.experiments.cfb_personnel import sources
        rows += sources(example)
    rows += list(fitted.get("source_bindings", []))
    rows += list(history.get("schedule_sources", []))
    if not rows:
        rows = list(history.get("sources", []))
    unique = {}
    for row in rows:
        r = dict(row)
        r["source"] = r.get("source", r.get("url"))
        r["retrieved_at_utc"] = r.get("retrieved_at_utc", r.get("fetched_at_utc"))
        # Raw bytes are verified once by verify_sources before a run. Per-event
        # receipts reference that run evidence, avoiding repeated archive reads.
        if fitted.get("stage_id") != "personnel_v2":
            r.pop("path", None)
        unique[r["sha256"]] = r
    return list(unique.values())


def verify_sources(history):
    rows = list(history.get("sources", []))
    rows += list(history.get("schedule_sources", []))
    if not rows:
        if isinstance(history.get("history"), list):
            rows = [s for g in history["history"] for s in g.get("sources", [])]
    if isinstance(history.get("team_games"), list):
        rows += [g["source"] for g in history["team_games"] if g.get("source")]
    checked = {}
    for source in rows:
        sha = source["sha256"]
        if sha in checked:
            continue
        result = {"source": source.get("source", source.get("url")), "sha256": sha,
                  "retrieved_at_utc": source.get("retrieved_at_utc", source.get("fetched_at_utc")), "bytes_verified": False}
        if source.get("path"):
            if file_hash(source["path"]) != sha:
                raise ValueError("SOURCE_BYTES_HASH_MISMATCH")
            result["bytes_verified"] = True
        checked[sha] = result
    if not checked:
        raise ValueError("SOURCE_CENSUS_REQUIRED")
    return list(checked.values())


def code_snapshot(league):
    names = ["research/efficiency/runner.py", "research/efficiency/integrity.py", "research/efficiency/evaluation.py",
             "models/experiments/" + league + "_efficiency.py", "models/current/linear.py"]
    names += ["harness/cfb_v1_port.py", "models/current/cfb.py", "models/experiments/cfb_personnel.py"] if league == "cfb" else ["models/current/baseline.py", "scripts/prepare_initial_baselines.py"]
    return {name: file_hash(ROOT / name) for name in names}


def component_receipt(league, stage, example, fitted, forecast, history, *, mode, cutoff=None):
    from research.efficiency.integrity import build_component_receipt
    event = example["event"]
    start = event["start_time_utc"]
    if league == "nba":
        # NBA constructs the actual prestart cutoff before every vector. A
        # receipt must bind that cutoff, never rewrite an already used cutoff
        # across a UTC-day boundary after prediction.
        feature_cutoff = example["cutoff_utc"]
        if (utc(feature_cutoff) != backend(league).forecast_cutoff(event)
                or (cutoff is not None and utc(cutoff) != utc(feature_cutoff))):
            raise ValueError("NBA_FEATURE_RECEIPT_CUTOFF_MISMATCH")
        cutoff = feature_cutoff
    elif cutoff is None:
        cutoff = example.get("cutoff_utc", event.get("forecast_cutoff_utc", start))
        if utc(cutoff) >= utc(start):
            cutoff = (utc(start) - timedelta(microseconds=1)).isoformat()
    pure_event = {k: event[k] for k in ("event_id", "home_id", "away_id", "home_team", "away_team", "start_time_utc", "season", "week", "neutral_site") if k in event}
    if league == "nba":
        pure_event["forecast_cutoff_utc"] = cutoff
    inputs = {"event": pure_event, "features": example["features"],
              "history_event_ids": example.get("history_event_ids", []),
              "component_state_sha256": example.get("component_state_sha256")}
    if league == "cfb" and fitted.get("stage_id") == "personnel_v2":
        inputs.update(personnel_evidence=example["personnel_evidence"],
                      personnel_schedule_coverage=example["personnel_schedule_coverage"],
                      consumed_personnel_features=forecast["personnel_consumption"]["feature_values"])
    components = forecast.get("components", {})
    if not components:
        components = {k: v for k, v in example["features"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    # Null unsupported output heads remain explicit in saved forecasts; the
    # receipt's numeric output validator receives only fitted heads.
    numeric_forecast = {k: v for k, v in sanitize_forecast(forecast).items() if v is not None}
    files = [ROOT / "models/experiments" / (league + "_efficiency.py"), Path(__file__), ROOT / "research/efficiency/integrity.py"]
    files += [ROOT / p for p in (["harness/cfb_v1_port.py", "models/current/cfb.py", "models/current/linear.py"] if league == "cfb" else ["models/current/baseline.py", "scripts/prepare_initial_baselines.py", "models/current/linear.py"])]
    if league == "cfb" and fitted.get("stage_id") == "personnel_v2":
        files.append(ROOT / "models/experiments/cfb_personnel.py")
    return build_component_receipt(model_id=forecast["model_id"], stage_id=stage,
        event_id=example["event_id"], cutoff_utc=cutoff, start_utc=start,
        inputs=inputs, state=fitted, config=fitted.get("config", {}), code_files=files,
        sources=sources_for(example, history, fitted), components=components,
        forecast=numeric_forecast, mode=mode,
        simulation=forecast.get("receipt_simulation"),
        parent_model_id=fitted.get("parent_model_id"),
        history_max_event_time_utc=example.get("history_max_event_time_utc"),
        input_max_available_at_utc=example.get("history_max_available_at_utc"))


def experiment(league, history_path, output, *, stages=("efficiency", "personnel", "joint"), bootstrap_count=2000):
    from research.efficiency.evaluation import evaluate
    module = backend(league)
    history_path, output = Path(history_path).resolve(strict=True), Path(output)
    raw = history_path.read_bytes()
    history = json.loads(raw)
    output.mkdir(parents=True, exist_ok=False)
    run_id = f"{league}-efficiency-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    protocol = ROOT / "docs/research/efficiency_2026_10_23/protocol.json"
    invocation = {"schema": SCHEMA, "run_id": run_id, "league": league, "created_at_utc": stamp(),
                  "mode": "HISTORICAL_REPLAY", "evidence_scope": "RETROSPECTIVE_RECONSTRUCTED_EXPLORATORY",
                  "history": {"path": str(history_path), "sha256": hashlib.sha256(raw).hexdigest()},
                  "protocol_sha256": file_hash(protocol), "code_sha256": code_snapshot(league),
                  "stages": list(stages), "action_authority": False}
    write(output / "invocation.json", invocation)
    source_checks = verify_sources(history)
    write(output / "source_verification.json", source_checks)
    examples = prepare(league, history)
    training = [e for e in examples if e["season"] <= 2024 and targets(e) is not None]
    population = [e for e in examples if e["season"] in {2025, 2026} and targets(e) is not None]
    if league == "nba":
        known = {e["event_id"] for e in population}
        excluded = {e["event_id"]: e.get("reason", "BOX_SOURCE_ABSENT") for e in history.get("excluded", [])}
        for event in history["score_history"]:
            if event["season"] not in {2025, 2026} or event["event_id"] in known:
                continue
            hs, aws = event["home_score"], event["away_score"]
            population.append({"event_id": event["event_id"], "event": event, "season": event["season"],
                               "eligible": False, "exclusion_reasons": [excluded.get(event["event_id"], "BOX_SOURCE_ABSENT")],
                               "targets": {"home_win": int(hs > aws), "home_margin": hs - aws, "total": hs + aws}})
            known.add(event["event_id"])
    control = module.fit_control(training) if league == "cfb" else module.prepare_baseline_control(history["score_history"], training_end_season=2024, align_forecast_cutoff=True)
    write(output / "control.json", control)
    matched_control = module.fit_matched_control(training) if league == "cfb" else None
    if matched_control is not None:
        write(output / "matched_population_control.json", matched_control)
    write(output / "population.json", [{"event_id": e["event_id"], "season": e["season"], "eligible": e["eligible"], "reasons": reasons(e)} for e in population])
    census = {"prepared_examples": len(examples), "training_candidate_events": len(training),
              "evaluation_population": len(population), "eligible_evaluation_events": sum(e["eligible"] for e in population),
              "excluded_reasons": dict(Counter(reason for e in population for reason in reasons(e))),
              "source_exclusions": history.get("excluded", []),
              "player_reconciliation_issues": history.get("player_reconciliation_issues", [])}
    stage_reports = {}
    for stage in stages:
        stage_out = output / stage
        stage_out.mkdir()
        try:
            fitted = fit_stage(module, league, training, stage)
        except (ValueError, KeyError, TypeError) as exc:
            stage_reports[stage] = {"status": "BLOCKED", "reason": str(exc), "n_predictions": 0}
            write(stage_out / "disposition.json", stage_reports[stage])
            continue
        write(stage_out / "state.json", fitted)
        rows, failed, matched_rows, matched_failures = [], [], [], []
        receipt_index = []
        for example in population:
            if not example["eligible"]:
                failed.append({"event_id": example["event_id"], "reasons": reasons(example)})
                continue
            try:
                pred = predict_stage(module, league, fitted, example)
                baseline = module.predict(control, example) if league == "cfb" else module.predict_baseline(control, example["event"])
                receipt = component_receipt(league, stage, example, fitted, pred, history, mode="HISTORICAL_REPLAY")
                event_key = example["event_id"].replace(":", "_")
                write(stage_out / "receipts" / (event_key + ".json"), receipt)
                receipt_index.append({"event_id": example["event_id"], "receipt_sha256": receipt["receipt_sha256"]})
                target = targets(example)
                d = utc(example["event"]["start_time_utc"])
                block = f"{example['season']}-W{example['week']:02d}" if league == "cfb" else f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
                rows.append({"event_id": example["event_id"], "season": example["season"], "block_id": block,
                             "start_time_utc": example["event"]["start_time_utc"],
                             "actual_home_win": target["home_win"], "actual_home_margin": target["home_margin"], "actual_total": target["total"],
                             "baseline": sanitize_forecast(baseline), "challenger": sanitize_forecast(pred)})
                if matched_control is not None and stage == "efficiency":
                    try:
                        matched_rows.append({**rows[-1], "baseline": sanitize_forecast(module.predict(matched_control, example))})
                    except (ValueError, KeyError, TypeError) as exc:
                        matched_failures.append({"event_id": example["event_id"], "reasons": [str(exc)]})
            except (ValueError, KeyError, TypeError) as exc:
                failed.append({"event_id": example["event_id"], "reasons": [str(exc)]})
        write(stage_out / "predictions.json", rows)
        write(stage_out / "excluded.json", failed)
        write(stage_out / "receipt_index.json", receipt_index)
        metrics = evaluate(rows, bootstrap_count=bootstrap_count, seed=2302026)
        write(stage_out / "evaluation.json", metrics)
        stage_reports[stage] = {"status": "COMPLETED" if rows else "BLOCKED", "model_id": fitted["model_id"],
                                "n_predictions": len(rows), "n_excluded": len(failed), "metrics": metrics,
                                "state": {"path": str((stage_out / "state.json").resolve()), "sha256": file_hash(stage_out / "state.json")}}
        if matched_control is not None and stage == "efficiency":
            write(stage_out / "matched_control_predictions.json", matched_rows)
            write(stage_out / "matched_control_excluded.json", matched_failures)
            matched_metrics = evaluate(matched_rows, bootstrap_count=bootstrap_count, seed=2302026)
            write(stage_out / "matched_control_evaluation.json", matched_metrics)
            stage_reports[stage]["matched_population_ablation"] = {
                "control_model_id": matched_control["model_id"], "n_predictions": len(matched_rows),
                "n_excluded": len(matched_failures),
                "metrics": matched_metrics,
                "scope": "same training and evaluation population; separately fitted incumbent features"}
    report = {**invocation, "completed_at_utc": stamp(), "coverage": census, "stages": stage_reports,
              "control_model_id": control["model_id"], "control_is_original_frozen_fit": False,
              "original_baselines_and_forecasts_modified": False, "predictive_validation": "UNVALIDATED",
              "canonical_prospective_eligible": False, "publication_allowed": False, "action_authority": False}
    if code_snapshot(league) != invocation["code_sha256"] or file_hash(history_path) != invocation["history"]["sha256"]:
        raise ValueError("CODE_OR_HISTORY_CHANGED_DURING_EXECUTION")
    write(output / "report.json", report)
    return report


def shadow_from_card(card_path, config_path, output, *, simulations=100000):
    """Called by the existing shared card CLI; writes only a separate directory."""
    from research.efficiency.integrity import write_shadow_receipt
    card_path, config_path = Path(card_path).resolve(strict=True), Path(config_path).resolve(strict=True)
    card_raw, config_raw = card_path.read_bytes(), config_path.read_bytes()
    card, config = json.loads(card_raw), json.loads(config_raw)
    if config.get("schema") != "efficiency-shadow-sidecar.v1":
        raise ValueError("EFFICIENCY_SHADOW_CONFIG_SCHEMA")
    league = config["league"]
    if card.get("league", "").lower() != league:
        raise ValueError("PARENT_CARD_LEAGUE_CONFLICT")
    module = backend(league)
    history, history_path = read_bound(config["history"], config_path.parent)
    source_checks = verify_sources(history)
    code_at_start = code_snapshot(league)
    cutoff = card.get("as_of_utc", card.get("requested_as_of_utc"))
    if cutoff is None:
        cutoff = card.get("pit", {}).get("requested_as_of_utc")
    if cutoff is None:
        raise ValueError("PARENT_CARD_CUTOFF_REQUIRED")
    event_lookup = {e["event_id"]: e for e in history.get("future_events", [])}
    if league == "cfb":
        event_lookup = {e.get("event_id", "CFB:" + str(e["game_id"])): e for e in history["games"] if not e.get("completed")}
    forecasts = card["forecasts"]
    planned, coverage = [], []
    for parent in forecasts:
        eid = parent["event_id"]
        event = event_lookup.get(eid)
        if event is None:
            coverage.append({"event_id": eid, "status": "BLOCKED", "reason": "FUTURE_EVENT_SOURCE_ABSENT"})
            continue
        start = event.get("start_time_utc", event.get("start_date"))
        if utc(start) != utc(parent["start_time_utc"]) or any(event[s + "_team"] != parent[s + "_team"] for s in ("home", "away")):
            coverage.append({"event_id": eid, "status": "BLOCKED", "reason": "PARENT_CURRENT_EVENT_IDENTITY_CONFLICT"})
            continue
        planned.append(event)
    examples = {e["event_id"]: e for e in prepare(league, history, future_events=planned, cutoff=cutoff)}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(output / "source_verification.json", source_checks)
    run_id = f"{league}-shadow-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    if not config.get("shadow_store"):
        raise ValueError("SHARED_FIRST_FORECAST_SHADOW_STORE_REQUIRED")
    shadow_store = (config_path.parent / config["shadow_store"]).resolve()
    for stage, reference in config["states"].items():
        fitted, state_path = read_bound(reference, config_path.parent)
        for event in planned:
            eid = event.get("event_id", "CFB:" + str(event.get("game_id")))
            example = examples[eid]
            if not example["eligible"]:
                coverage.append({"event_id": eid, "stage": stage, "status": "BLOCKED", "reason": ";".join(reasons(example))})
                continue
            try:
                forecast = predict_stage(module, league, fitted, example, simulations=simulations if stage == "joint" else 0)
                draws = forecast.pop("joint_draws", None)
                if draws is None and simulations:
                    import numpy as np
                    seed = int(digest({"model_id": forecast["model_id"], "state_sha256": fitted.get("state_sha256"),
                                       "event_id": eid, "features": example["features"], "n": simulations})[:16], 16)
                    draws = np.random.default_rng(seed).binomial(1, forecast["p_home"], simulations).astype("<i8")
                    forecast["simulation"] = {"n": simulations, "seed": seed, "rng": "numpy.PCG64",
                                               "distribution_id": "binary_winner_bernoulli.v1", "p_home": float(draws.mean()),
                                               "draw_sha256": hashlib.sha256(draws.tobytes()).hexdigest(),
                                               "encoding": "little-endian int64 N home_win"}
                if draws is not None:
                    import numpy as np
                    draw_path = output / "draws" / stage / (eid.replace(":", "_") + ".npy")
                    draw_path.parent.mkdir(parents=True, exist_ok=True)
                    with draw_path.open("xb") as f:
                        np.save(f, draws, allow_pickle=False)
                    sim = forecast["simulation"]
                    forecast["receipt_simulation"] = {"count": sim["n"], "seed": sim["seed"], "rng": sim["rng"],
                        "distribution_id": sim["distribution_id"], "draws_sha256": sim["draw_sha256"],
                        "draws_encoding": sim["encoding"], "draws_path": str(draw_path.resolve()), "draws_file_sha256": file_hash(draw_path)}
                receipt = component_receipt(league, stage, example, fitted, forecast, history, mode="SHADOW", cutoff=cutoff)
                registration = write_shadow_receipt(receipt, shadow_store)
                coverage.append({"event_id": eid, "stage": stage, "status": "SHADOW_LOGGED", "model_id": forecast["model_id"],
                                 "forecast": sanitize_forecast(forecast), "receipt_sha256": receipt["receipt_sha256"], "registration": registration})
            except (ValueError, KeyError, TypeError) as exc:
                coverage.append({"event_id": eid, "stage": stage, "status": "BLOCKED", "reason": str(exc)})
    if card_path.read_bytes() != card_raw or config_path.read_bytes() != config_raw or code_snapshot(league) != code_at_start:
        raise ValueError("PARENT_OR_CONFIG_MUTATED")
    report = {"schema": SCHEMA, "run_id": run_id, "mode": "SHADOW", "created_at_utc": stamp(), "league": league,
              "parent_card_sha256": hashlib.sha256(card_raw).hexdigest(), "config_sha256": hashlib.sha256(config_raw).hexdigest(),
              "history_sha256": file_hash(history_path), "cutoff_utc": cutoff, "coverage": coverage,
              "code_sha256": code_at_start, "shared_shadow_store": str(shadow_store), "scoring_policy": "FIRST_PRESTART_EVENT_MODEL_STAGE",
              "logged_count": sum(r["status"] == "SHADOW_LOGGED" for r in coverage),
              "canonical_prospective_eligible": False, "external_timestamp_verified": False,
              "predictive_validation": "UNVALIDATED", "publication_allowed": False, "action_authority": False}
    write(output / "report.json", report)
    return report
