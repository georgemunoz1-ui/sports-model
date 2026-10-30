"""Optional research sidecars; baseline forecasts are never replaced.

These adapters run after the parent card has been written. Missing inputs or a
failed extension leave that parent available and return an incomplete status.
The extension's own report describes capture, numerical use and eligibility.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path


EXTENSIONS = {
    "nba_personnel": ("NBA", "research.efficiency.nba_personnel_runner"),
    "nhl_context": ("NHL", "research.nhl_context"),
}


def run_extension(name, card_path, config_path, output):
    """Dispatch a named extension and retain a refusal without editing parent."""
    if name not in EXTENSIONS:
        raise ValueError("UNKNOWN_RESEARCH_EXTENSION")
    league, module_name = EXTENSIONS[name]
    card_path, output = Path(card_path), Path(output)
    if output.exists():
        raise FileExistsError("RESEARCH_EXTENSION_OUTPUT_ALREADY_EXISTS")
    parent_bytes = card_path.read_bytes()
    try:
        card = json.loads(parent_bytes)
        if card.get("league", "").upper() != league:
            raise ValueError("RESEARCH_EXTENSION_LEAGUE_MISMATCH")
        module = importlib.import_module(module_name)
        report = module.shadow_from_card(card_path, Path(config_path), output)
        if not isinstance(report, dict):
            raise ValueError("RESEARCH_EXTENSION_REPORT_REQUIRED")
        coverage = report.get("coverage")
        if not isinstance(coverage, list) or not coverage:
            raise ValueError("RESEARCH_EXTENSION_COVERAGE_REQUIRED")
        incomplete = any(row.get("status") not in {"COMPLETED", "SHADOW_LOGGED"}
                         or row.get("input_eligibility") == "BLOCKED"
                         for row in coverage)
        return {"extension": name, "run_id": report.get("run_id"),
                "coverage": coverage, "incomplete": incomplete,
                "canonical_prospective_eligible": False, "action_authority": False}
    except (ValueError, KeyError, TypeError, OSError) as exc:
        output.mkdir(parents=True, exist_ok=True)
        failure = {"extension": name, "status": "BLOCKED", "reason": str(exc),
                   "incomplete": True, "canonical_prospective_eligible": False,
                   "action_authority": False}
        with (output / "extension_failure.json").open("x") as handle:
            json.dump(failure, handle, indent=2, allow_nan=False)
            handle.write("\n")
        return failure
    finally:
        if card_path.read_bytes() != parent_bytes:
            raise RuntimeError("RESEARCH_EXTENSION_MUTATED_PARENT_CARD")
