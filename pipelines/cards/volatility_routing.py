"""Explicit joint-research routing receipts; no automatic fallback or promotion.

The numerical PR105 adapter and fitted bytes remain unchanged. A config may
explicitly pin a separate compatible parent card; it must cover exactly the
same event identities and starts as the displayed card. That parent retains its
own model identity and chronology instead of masquerading as the winner head.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from models.common import discrete_research as D
from pipelines.cards import volatility_research as V

ROUTE = "JOINT_VOLATILITY_RESEARCH_V1"
CODE_FILES = (
    "scripts/generate_card_force.py", "scripts/cross_sport_volatility_research.py",
    "scripts/run_volatility_card_receipted.py",
    "pipelines/cards/volatility_routing.py", "pipelines/cards/volatility_research.py",
    "pipelines/cards/distribution_research.py", "models/common/volatility_matrix_v1.py",
    "models/common/discrete_research.py",
)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


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
    rows = card["forecasts"]
    ids = [r["event_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_PARENT_EVENT")
    return {r["event_id"]: D.stamp(r["start_time_utc"]).isoformat() for r in rows}


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
    receipt = {"schema": "sports.volatility_route_receipt.research.v1",
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
        card = json.loads(card_path.read_text())
        _event_bindings(card)
        tracked[str(config_path)] = file_hash(config_path)
        receipt["input_files"] = dict(tracked)
        config = V.load_config(config_path)
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
            parent = json.loads(parent_path.read_text())
            if parent["league"].lower() != card["league"].lower():
                raise ValueError("EXPLICIT_PARENT_LEAGUE_MISMATCH")
            if _event_bindings(parent) != _event_bindings(card):
                raise ValueError("EXPLICIT_PARENT_EVENT_SET_OR_START_MISMATCH")
            if parent.get("card_date") != card.get("card_date"):
                raise ValueError("EXPLICIT_PARENT_DATE_MISMATCH")
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
        if card:
            receipt["coverage"] = [{"event_id": r["event_id"], "status": "UNAVAILABLE",
                                    "reason": str(exc)} for r in card.get("forecasts", [])]
            receipt["per_market_availability"] = [
                {"event_id": r["event_id"], "product": product, "status": "UNAVAILABLE",
                 "reason": str(exc)} for r in card.get("forecasts", [])
                for product in ("winner", "margin", "total")]
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
    if card:
        displayed = dict(card)
        displayed["research_routes"] = dict(card.get("research_routes") or {})
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
