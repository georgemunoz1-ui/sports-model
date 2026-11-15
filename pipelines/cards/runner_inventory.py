"""Discover operator entry points without executing them.

This is a coverage guard, not a statistical or runtime-audit attestation.  A new
CLI cannot escape review merely by avoiding a ``scripts/run_`` filename.  The
checked-in registry distinguishes audited operators, unaudited diagnostics,
historical programs, and non-forecast operations.  Separate branches are not
certified by their presence in this checkout's inventory.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
import tomllib

import yaml

ROOTS = ("scripts", "models", "research", "sportsim", "pipelines")
ROLES = {"audited_forecast", "unaudited_diagnostic", "historical_research",
         "acquisition", "state_preparation", "grading_registration", "review",
         "operations", "test_tool", "frozen_legacy"}
EXTERNAL_MODULES = {"pip", "pytest", "unittest", "compileall", "py_compile", "venv"}
PYTHON_COMMAND = re.compile(
    r"(?<![\w.-])python(?:\d+(?:\.\d+)?)?\s+(?:(?:-[uBEsIOq])\s+)*"
    r"(?:-m\s+([A-Za-z_]\w*(?:\.\w+)*)|([\w./-]+\.py))"
)
INLINE_PYTHON = re.compile(r"(?<![\w.-])python(?:\d+(?:\.\d+)?)?\s+(?:(?:-[uBEsIOq])\s+)*(?:-\s*<<|-c(?:\s|$))")


def _is_test(path):
    return any(part == "tests" or part.startswith("test_") for part in path.parts)


def _executable(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if (any(isinstance(x, ast.Name) and x.id == "__name__" for x in operands)
                    and any(isinstance(x, ast.Constant) and x.value == "__main__" for x in operands)):
                return True
    # Some old one-shot commands parse their arguments at module scope.
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr in {"parse_args", "parse_known_args"}
               for node in ast.walk(statement)):
            return True
    return False


def _module_path(root, module):
    path = Path(*module.split("."))
    for candidate in (path.with_suffix(".py"), path / "__main__.py"):
        if (root / candidate).is_file():
            return candidate.as_posix()
    return None


def discover(root):
    """Return paths -> discovery origins; no imports of forecast code occur."""
    root = Path(root).resolve()
    found = {}

    def add(path, origin):
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("ENTRYPOINT_TARGET_UNRESOLVED:" + str(path))
        relative = resolved.relative_to(root).as_posix()
        found.setdefault(relative, set()).add(origin)

    for directory in ROOTS:
        for path in sorted((root / directory).rglob("*.py")):
            relative = path.relative_to(root)
            if _is_test(relative) or "__pycache__" in relative.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
            if _executable(tree):
                add(relative, "python_entrypoint")

    project = root / "pyproject.toml"
    if project.is_file():
        config = tomllib.loads(project.read_text(encoding="utf-8"))
        for group in ("scripts", "gui-scripts"):
            for command, target in config.get("project", {}).get(group, {}).items():
                module = target.split(":", 1)[0]
                path = _module_path(root, module)
                if path is None:
                    raise ValueError("CONSOLE_ENTRYPOINT_UNRESOLVED:" + command)
                add(path, "console:" + command)

    for path in sorted((root / ".github/workflows").glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        defaults = workflow.get("defaults", {}).get("run", {})
        for job in workflow.get("jobs", {}).values():
            job_defaults = {**defaults, **job.get("defaults", {}).get("run", {})}
            for step in job.get("steps", []):
                command = step.get("run")
                if not isinstance(command, str):
                    continue
                working = step.get("working-directory", job_defaults.get("working-directory", "."))
                for match in PYTHON_COMMAND.finditer(command):
                    module, script = match.groups()
                    if module:
                        if module in EXTERNAL_MODULES:
                            continue
                        target = _module_path(root, module)
                        if target is None:
                            raise ValueError("WORKFLOW_MODULE_UNRESOLVED:" + module)
                    else:
                        target = (Path(working) / script).as_posix()
                    add(target, "workflow:" + path.relative_to(root).as_posix())
    return {path: sorted(origins) for path, origins in sorted(found.items())}


def inline_workflows(root):
    """Bind manually reviewed inline Python so new code cannot evade path census."""
    root = Path(root)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / ".github/workflows").glob("*.y*ml"))
            if INLINE_PYTHON.search(path.read_text(encoding="utf-8"))}


def validate(root, registry):
    """Fail for new, removed, malformed, or deceptively classified entry points."""
    root = Path(root)
    if registry.get("schema") != "sports.missingness_entrypoints.v1":
        raise ValueError("ENTRYPOINT_REGISTRY_SCHEMA")
    inline = inline_workflows(root)
    reviewed_inline = registry.get("inline_workflow_reviews", {})
    if set(inline) != set(reviewed_inline) or any(
            reviewed_inline[path].get("source_sha256") != digest
            or not reviewed_inline[path].get("reason") for path, digest in inline.items()):
        raise ValueError("INLINE_WORKFLOW_REVIEW_REQUIRED")
    discovered = discover(root)
    records = registry.get("entrypoints")
    if not isinstance(records, dict):
        raise ValueError("ENTRYPOINT_REGISTRY_RECORDS")
    missing, removed = set(discovered) - set(records), set(records) - set(discovered)
    if missing or removed:
        raise ValueError("ENTRYPOINT_INVENTORY_DRIFT:" + json.dumps(
            {"unclassified": sorted(missing), "no_longer_discovered": sorted(removed)}, sort_keys=True))
    unaudited = []
    for path, record in records.items():
        if (record.get("role") not in ROLES or not isinstance(record.get("reason"), str)
                or not record["reason"].strip() or record.get("official_release_eligible") is not False):
            raise ValueError("ENTRYPOINT_CLASSIFICATION_INVALID:" + path)
        if record["role"] == "audited_forecast":
            boundaries = record.get("audit_boundaries")
            checks = record.get("invocation_tests")
            if not boundaries or not checks:
                raise ValueError("ENTRYPOINT_INVOCATION_EVIDENCE_REQUIRED:" + path)
            for boundary in boundaries:
                module_path, separator, symbol = boundary.partition(":")
                if not separator or not symbol or not (root / module_path).is_file():
                    raise ValueError("ENTRYPOINT_AUDIT_BOUNDARY_INVALID:" + path)
                tree = ast.parse((root / module_path).read_text(encoding="utf-8"))
                if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == symbol
                           for n in ast.walk(tree)):
                    raise ValueError("ENTRYPOINT_AUDIT_SYMBOL_MISSING:" + boundary)
            for check in checks:
                if not (root / check.split("::", 1)[0]).is_file():
                    raise ValueError("ENTRYPOINT_INVOCATION_TEST_MISSING:" + path)
        if record["role"] == "frozen_legacy":
            if not record.get("source_sha256") or not record.get("successor"):
                raise ValueError("FROZEN_ENTRYPOINT_EVIDENCE_REQUIRED:" + path)
            if hashlib.sha256((root / path).read_bytes()).hexdigest() != record["source_sha256"]:
                raise ValueError("FROZEN_ENTRYPOINT_SOURCE_CHANGED:" + path)
        if record["role"] == "unaudited_diagnostic":
            if not record.get("gap"):
                raise ValueError("UNAUDITED_ENTRYPOINT_GAP_REQUIRED:" + path)
            unaudited.append(path)
    return {"schema": registry["schema"], "inventory_status": "PASS",
            "entrypoint_count": len(discovered), "discovery": discovered,
            "unaudited_diagnostic_entrypoints": sorted(unaudited),
            "classified_forecast_routes_have_declared_audit_boundary": not unaudited,
            "runtime_invocation_verified_by_inventory": False,
            "statistical_approval": "NOT_ASSESSED", "official_release_eligible": False}
