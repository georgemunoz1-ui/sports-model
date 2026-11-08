"""Explicit joint-research routing receipts; no automatic fallback or promotion.

The numerical PR105 adapter and fitted bytes remain unchanged. A config may
explicitly pin a separate compatible parent card; it must cover exactly the
same event identities and starts as the displayed card. That parent retains its
own model identity and chronology instead of masquerading as the winner head.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

from models.common import discrete_research as D
from models.common import volatility_matrix_v1 as M
from pipelines.cards import volatility_research as V
from pipelines.cards import derived_missingness as A

ROUTE = "JOINT_VOLATILITY_RESEARCH_BOUND_V2"
CONFIG_SCHEMA = "sports.volatility_route_config.research.v2"
PARENT_TARGET = "PAIRED_HOME_AWAY_FINAL_SCORES"
PARENT_ORIENTATION = "HOME_MINUS_AWAY"
CODE_FILES = (
    "scripts/generate_card_force.py", "scripts/cross_sport_volatility_research.py",
    "scripts/run_volatility_card_receipted.py",
    "pipelines/cards/volatility_routing.py", "pipelines/cards/volatility_research.py",
    "pipelines/cards/missingness.py", "pipelines/cards/derived_missingness.py",
    "pipelines/cards/distribution_research.py", "models/common/volatility_matrix_v1.py",
    "models/common/volatility_scoring_v2.py",
    "models/common/discrete_research.py",
)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def _load_json(raw):
    """Reject ambiguous identities and non-finite numbers before receipt output."""
    def constant(value):
        raise ValueError("NONFINITE_JSON_TOKEN:" + value)

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("NONFINITE_JSON_NUMBER:" + value)
        return result

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY:" + key)
            result[key] = value
        return result

    return json.loads(raw, parse_constant=constant, parse_float=number,
                      object_pairs_hook=unique_object)


def load_route_config(path):
    """Versioned routing contract; the frozen numerical adapter stays v1."""
    path = Path(path).resolve()
    raw = path.read_bytes()
    config = _load_json(raw)
    if config.get("schema") != CONFIG_SCHEMA:
        raise ValueError("ROUTE_CONFIG_V2_REQUIRED")
    if config.get("action_authority") is not False:
        raise ValueError("RESEARCH_ONLY_CONFIG")
    D.identity(config.get("information_set"), "INFORMATION_SET")
    config["config_file_sha256"] = hashlib.sha256(raw).hexdigest()
    config["loaded_models"] = []
    for entry in config["models"]:
        model_raw = (path.parent / entry["path"]).resolve().read_bytes()
        if hashlib.sha256(model_raw).hexdigest() != entry["sha256"]:
            raise ValueError("CONFIG_MODEL_FILE_HASH_MISMATCH")
        model = _load_json(model_raw)
        M._validate_fit(model)
        config["loaded_models"].append({"model": model})
    return config


def checkout_evidence(repo):
    def git(*args):
        try:
            return subprocess.check_output(["git", *args], cwd=repo, text=True,
                                           stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    return {"observed_checkout_sha": git("rev-parse", "HEAD"),
            "working_tree_status": git("status", "--porcelain=v1"),
            "working_tree_diff_sha256": D.digest(git("diff", "HEAD")),
            "code_file_sha256": {p: file_hash(Path(repo)/p) for p in CODE_FILES
                                 if (Path(repo)/p).is_file()}}


def _event_bindings(card):
    if not isinstance(card, dict):
        raise ValueError("CARD_OBJECT_REQUIRED")
    rows = card["forecasts"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("NONEMPTY_PARENT_EVENT_SET_REQUIRED")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("FORECAST_ROW_OBJECT_REQUIRED")
    ids = [D.identity(r.get("event_id"), "EVENT_ID") for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_PARENT_EVENT")
    bindings = {}
    for row in rows:
        event_id = D.identity(row["event_id"], "EVENT_ID")
        # Labels cannot substitute for canonical, ordered team identities. Old
        # cards without these fields need a separately issued bound successor;
        # this adapter never guesses identifiers or rewrites a frozen card.
        home = D.identity(row.get("home_id"), "CANONICAL_HOME_ID")
        away = D.identity(row.get("away_id"), "CANONICAL_AWAY_ID")
        if home == away:
            raise ValueError("PARENT_DISTINCT_CANONICAL_TEAMS_REQUIRED")
        if row.get("projected_margin_orientation") != PARENT_ORIENTATION:
            raise ValueError("PARENT_MARGIN_ORIENTATION_REQUIRED_HOME_MINUS_AWAY")
        if row.get("target") != PARENT_TARGET:
            raise ValueError("PARENT_TARGET_SCOPE_MISMATCH")
        bindings[event_id] = {
            "event_id_namespace": D.identity(row.get("event_id_namespace"), "EVENT_ID_NAMESPACE"),
            "start_time_utc": D.stamp(row["start_time_utc"]).isoformat(),
            "home_id": home, "away_id": away,
            "team_id_namespace": D.identity(row.get("team_id_namespace"), "TEAM_ID_NAMESPACE"),
            "settlement": D.identity(row.get("settlement"), "PARENT_SETTLEMENT"),
            "orientation": PARENT_ORIENTATION, "target": PARENT_TARGET,
            "information_set": D.identity(row.get("information_set"), "PARENT_INFORMATION_SET"),
        }
    return bindings


def _diagnostic_rows(card):
    """Malformed inputs still receive a diagnostic receipt, without invented IDs."""
    if not isinstance(card, dict):
        return []
    rows = card.get("forecasts")
    if not isinstance(rows, list):
        return [{}]
    return [row if isinstance(row, dict) else {} for row in rows]


def _validate_parent_scope(parent, config):
    """Check the original row's declared scope before any adapter/draw call.

    A matching config string or a retained file hash does not supply missing
    parent semantics. The frozen v1 fitter models paired final home/away scores;
    no winner-only, regulation/full-game or away-oriented reinterpretation is
    permitted here. This verifies consistency, not provider authentication.
    """
    league = parent["league"].lower()
    bindings = {}
    for row in parent["forecasts"]:
        model_id = D.identity(row.get("model_id"), "PARENT_MODEL_ID")
        D.source_hash(row.get("input_snapshot_hash"))
        D.source_hash(row.get("model_state_config_hash"))
        if row.get("projected_margin_orientation") != PARENT_ORIENTATION:
            raise ValueError("PARENT_MARGIN_ORIENTATION_REQUIRED_HOME_MINUS_AWAY")
        if row.get("target") != PARENT_TARGET:
            raise ValueError("PARENT_TARGET_SCOPE_MISMATCH")
        settlement = D.identity(row.get("settlement"), "PARENT_SETTLEMENT")
        information_set = D.identity(row.get("information_set"), "PARENT_INFORMATION_SET")
        if information_set != config["information_set"]:
            raise ValueError("PARENT_INFORMATION_SET_MISMATCH")
        matches = [entry["model"] for entry in config["loaded_models"]
                   if entry["model"]["league"] == league
                   and entry["model"]["parent_model_id"] == model_id]
        # Preserve the existing FIT_REQUIRED disposition when no fit is supplied.
        # An explicitly supplied incompatible fit must never masquerade as one.
        if config["loaded_models"] and not matches:
            raise ValueError("PARENT_MODEL_OR_LEAGUE_SCOPE_MISMATCH")
        if settlement not in M.SETTLEMENTS.get(league, {}):
            raise ValueError("PARENT_SETTLEMENT_SCOPE_MISMATCH")
        for model in matches:
            if settlement != model["settlement"]:
                raise ValueError("PARENT_SETTLEMENT_SCOPE_MISMATCH")
            if information_set != model["information_set"]:
                raise ValueError("PARENT_FIT_INFORMATION_SET_MISMATCH")
        bindings[row["event_id"]] = {
            **_event_bindings({"forecasts": [row]})[row["event_id"]],
            "parent_forecast_sha256": D.digest(row),
            "parent_model_id": model_id, "target": PARENT_TARGET,
            "orientation": PARENT_ORIENTATION, "information_set": information_set,
            "input_snapshot_hash": row["input_snapshot_hash"],
            "model_state_config_hash": row["model_state_config_hash"],
        }
    return bindings


def run_joint_route(card_path, config_path, output, *, simulations=100000, repo_root=None):
    """Invoke the requested route and write a receipt even on input refusal.

    Returns a receipt, not an eligibility verdict. Existing directories are
    refused; the original card and configs are never rewritten. A refused joint
    route cannot trigger an empirical fallback. Separately requested legacy
    research remains an independently identified product.
    """
    repo = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
    card_path, config_path, output = map(lambda p: Path(p).resolve(),
                                        (card_path, config_path, output))
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "sports.volatility_route_receipt.research.v2",
               "requested_route": ROUTE, "executed_route": None,
               "invoked_entrypoint": "pipelines.cards.volatility_research.build",
               "process_argv": list(sys.argv), "python_executable": sys.executable,
               "invocation_at_utc": D.writer_clock(), "completion_at_utc": None,
               "requested_simulations": simulations, "actual_joint_draws": 0,
               "adapter_invoked": False, "fallback_authorized": False,
               "fallback_executed": False, "fallback_reason": None,
               "status": "NOT_RUN", "reason": None, "coverage": [],
               "per_market_availability": [], "input_files": {}, "fit_artifacts": [],
               "output_hashes": {}, "action_authority": False,
               "prospective_grade_eligible": False,
               "predictive_validation": "NOT_ESTABLISHED", **checkout_evidence(repo)}
    card, report = None, None
    tracked = {}
    try:
        tracked[str(card_path)] = file_hash(card_path)
        card = _load_json(card_path.read_bytes())
        displayed_bindings = _event_bindings(card)
        tracked[str(config_path)] = file_hash(config_path)
        receipt["input_files"] = dict(tracked)
        config = load_route_config(config_path)
        model_ids = [e["model"]["model_id"] for e in config["loaded_models"]]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("DUPLICATE_CONFIG_MODEL")
        parent = card
        parent_path = card_path
        entry = config.get("parent_card")
        if entry is not None:
            parent_path = (config_path.parent / entry["path"]).resolve()
            observed = file_hash(parent_path)
            if observed != entry["sha256"]:
                raise ValueError("EXPLICIT_PARENT_FILE_HASH_MISMATCH")
            tracked[str(parent_path)] = observed
            parent = _load_json(parent_path.read_bytes())
            if parent["league"].lower() != card["league"].lower():
                raise ValueError("EXPLICIT_PARENT_LEAGUE_MISMATCH")
            parent_bindings = _event_bindings(parent)
            if parent_bindings.keys() != displayed_bindings.keys() or any(
                    parent_bindings[eid]["start_time_utc"] != displayed_bindings[eid]["start_time_utc"]
                    for eid in displayed_bindings):
                raise ValueError("EXPLICIT_PARENT_EVENT_SET_OR_START_MISMATCH")
            if parent_bindings != displayed_bindings:
                raise ValueError("EXPLICIT_PARENT_IDENTITY_OR_SCOPE_MISMATCH")
            if parent.get("card_date") != card.get("card_date"):
                raise ValueError("EXPLICIT_PARENT_DATE_MISMATCH")
        receipt["parent_identity_bindings"] = _validate_parent_scope(parent, config)
        receipt["displayed_card_file_sha256"] = tracked[str(card_path)]
        receipt["displayed_as_of_utc"] = card["as_of_utc"]
        receipt["displayed_generated_at_utc"] = card["generated_at_utc"]
        receipt["parent_as_of_utc"] = parent["as_of_utc"]
        receipt["parent_generated_at_utc"] = parent["generated_at_utc"]
        receipt["parent_card_file_sha256"] = file_hash(parent_path)
        receipt["explicit_separate_parent"] = entry is not None
        receipt["parent_model_ids"] = sorted({r.get("model_id", "UNKNOWN")
                                               for r in parent["forecasts"]})
        receipt["parent_forecast_sha256"] = {r["event_id"]: D.digest(r)
                                                for r in parent["forecasts"]}
        for spec, loaded in zip(config["models"], config["loaded_models"]):
            path = (config_path.parent / spec["path"]).resolve()
            tracked[str(path)] = file_hash(path)
            model = loaded["model"]
            receipt["fit_artifacts"].append({"file_sha256": tracked[str(path)],
                "artifact_sha256": model["artifact_sha256"], "model_id": model["model_id"],
                "parent_model_id": model["parent_model_id"], "settlement": model["settlement"],
                "fit_as_of_utc": model["fit_as_of_utc"], "created_at_utc": model["created_at_utc"]})
        receipt["adapter_invoked"] = True
        report = V.build(parent, config, output / "joint", simulations=simulations)
        receipt["coverage"] = report["coverage"]
        receipt["actual_joint_draws"] = sum(r["simulation"]["count"] for r in report["results"])
        if report["results"]:
            receipt["executed_route"] = ROUTE
        receipt["status"] = ("COMPLETED" if report["coverage"] and all(
            r["status"] == "COMPLETED" for r in report["coverage"])
            else "PARTIAL" if report["results"] else "BLOCKED")
        result_map = {(r["event_id"], r["distribution"]["model_id"]): r
                      for r in report["results"]}
        for item in report["coverage"]:
            result = result_map.get((item["event_id"], item.get("model_id")))
            for product in ("winner", "margin", "total"):
                supported = product == "winner" or product in V.CONTRACT_PRODUCTS[parent["league"].lower()]
                contracts = [] if not result else [c for c in result["contracts"] if c["product"] == product]
                available = result is not None and supported
                receipt["per_market_availability"].append({"event_id": item["event_id"],
                    "model_id": item.get("model_id"), "product": product,
                    "status": "DISTRIBUTION_ONLY_NO_QUOTE" if available and not contracts else
                              "COMPLETED" if available else "UNAVAILABLE",
                    "reason": None if available else item.get("reason", item["status"]) if supported else "UNSUPPORTED_PRODUCT",
                    "quoted_contract_count": len(contracts),
                    "timing": "POST_START" if item["event_id"] in report["post_start_event_ids"] else "PRE_START"})
    except Exception as exc:
        receipt["status"], receipt["reason"] = "BLOCKED", str(exc)
        if card is not None:
            receipt["coverage"] = [{"event_id": r.get("event_id"), "status": "UNAVAILABLE",
                                    "reason": str(exc)} for r in _diagnostic_rows(card)]
            receipt["per_market_availability"] = [
                {"event_id": r.get("event_id"), "product": product, "status": "UNAVAILABLE",
                 "reason": str(exc)} for r in _diagnostic_rows(card)
                for product in ("winner", "margin", "total")]
    for product_row in receipt["per_market_availability"]:
        event_id = product_row.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            receipt.update(status="BLOCKED", reason="JOINT_ROUTE_MISSING_EVENT_IDENTITY")
            continue
        # The requested route may fail before a model is admitted. Label the
        # route identity in this case; a rejected request has no fitted state.
        model_id = product_row.get("model_id") or ROUTE
        A.attach(product_row, (card or {}).get("league","unknown").lower(), event_id,
                 model_id, [product_row["product"]],
                 inputs={"route":ROUTE, "adapter_invoked":receipt["adapter_invoked"],
                         "status":product_row["status"], "parent_card_sha256":receipt.get("parent_card_file_sha256")},
                 method="Route availability, independently scoped to each derived product",
                 missing=[product_row["reason"]] if product_row.get("reason") else [])
    receipt["input_files"] = tracked
    receipt["input_files_unchanged"] = all(Path(p).is_file() and file_hash(p) == h
                                           for p, h in tracked.items())
    if not receipt["input_files_unchanged"]:
        receipt["status"], receipt["reason"] = "FAILED", "INPUT_CHANGED_DURING_EXECUTION"
    # Retain truthful accounting if an I/O failure interrupts the adapter after
    # it writes draws but before its final report. Such files are not forecasts.
    receipt["retained_pair_files"] = []
    for path in sorted((output / "joint").glob("*.npz")):
        try:
            with np.load(path, allow_pickle=False) as arrays:
                home, away = arrays["home"], arrays["away"]
                if home.ndim != 1 or home.shape != away.shape:
                    raise ValueError("INVALID_RETAINED_PAIR_SHAPE")
                receipt["retained_pair_files"].append({"file": str(path.relative_to(output)),
                    "count": len(home), "file_sha256": file_hash(path)})
        except Exception as exc:
            receipt["status"], receipt["reason"] = "FAILED", "PAIR_FILE_UNREADABLE:" + str(exc)
    retained_count = sum(p["count"] for p in receipt["retained_pair_files"])
    if retained_count != receipt["actual_joint_draws"]:
        receipt["actual_joint_draws"] = retained_count
        receipt["executed_route"] = ROUTE if retained_count else None
        receipt["status"], receipt["reason"] = "FAILED", "PARTIAL_UNRECONCILED_PAIR_OUTPUT"
    if isinstance(card, dict):
        displayed = dict(card)
        existing_routes = card.get("research_routes")
        displayed["research_routes"] = dict(existing_routes) if isinstance(existing_routes, dict) else {}
        displayed["research_routes"]["joint_volatility"] = {
            "requested_route": ROUTE, "executed_route": receipt["executed_route"],
            "status": receipt["status"], "reason": receipt["reason"],
            "actual_joint_draws": receipt["actual_joint_draws"],
            "parent_card_file_sha256": receipt.get("parent_card_file_sha256"),
            "explicit_separate_parent": receipt.get("explicit_separate_parent", False),
            "original_displayed_card_file_sha256": receipt.get("displayed_card_file_sha256"),
            "coverage": receipt["coverage"],
            "per_market_availability": receipt["per_market_availability"],
            "report": "joint/volatility_report.json" if report else None,
            "receipt": "route_receipt.json", "fallback_executed": False,
            "direct_winner_heads_unchanged": True, "action_authority": False}
        _write(output / "card_with_research_routes.json", displayed)
    receipt["completion_at_utc"] = D.writer_clock()
    receipt["output_hashes"] = {str(p.relative_to(output)): file_hash(p)
                                for p in sorted(output.rglob("*")) if p.is_file()}
    receipt["receipt_sha256"] = D.digest(receipt)
    _write(output / "route_receipt.json", receipt)
    saved = _load_json((output / "route_receipt.json").read_bytes())
    for item in saved["per_market_availability"]:
        if isinstance(item.get("event_id"), str) and item["event_id"].strip():
            A.check(item, (card or {}).get("league","unknown").lower(), item["event_id"],
                    item.get("model_id") or ROUTE, [item["product"]])
    return receipt


def render_route(receipt):
    lines = ["", "## Explicit joint-volatility research route", "",
             f"Requested: {receipt['requested_route']}; executed: {receipt['executed_route'] or 'NONE'}.",
             f"Status: {receipt['status']}; actual paired draws: {receipt['actual_joint_draws']}; fallback: NONE.",
             "", "| Event | Arm | Status | Reason |", "|---|---|---|---|"]
    for r in receipt["coverage"]:
        lines.append(f"| {r['event_id']} | {r.get('model_id', 'UNAVAILABLE')} | {r['status']} | {r.get('reason', '')} |")
    if receipt["reason"]:
        lines.append("\nRefusal: " + receipt["reason"])
    lines.append("\nSeparate research child; direct winner unchanged. Predictive validation NOT ESTABLISHED; action OFF.")
    return "\n".join(lines) + "\n"
