#!/usr/bin/env python3
"""Read sealed research inputs and emit immutable, non-authoritative decisions."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from pipelines.cards.research_selection import (  # noqa: E402
    ResearchSelectionError, content_hash, select_research, verify_selection_record,
)
from research.validation_registry import (  # noqa: E402
    ArtifactStore, Ed25519Verifier, RegistryError, ValidationRegistry,
)


class InputError(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def exact_keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise InputError("INVALID_OBJECT_KEYS:" + ",".join(sorted(required)))


def timestamp(value):
    if not isinstance(value, str):
        raise InputError("INVALID_UTC_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputError("INVALID_UTC_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise InputError("UTC_TIMESTAMP_REQUIRED")
    return parsed


class Sources:
    """Keep byte receipts and reject a source changing during this execution."""

    def __init__(self):
        self.receipts = {}

    def read(self, path, role):
        path = Path(path).resolve(strict=True)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        previous = self.receipts.get(str(path))
        if previous is not None and previous["sha256"] != digest:
            raise InputError("SOURCE_CHANGED_DURING_EXECUTION:" + str(path))
        receipt = previous or {"path": str(path), "sha256": digest, "byte_count": len(raw), "roles": []}
        if role not in receipt["roles"]:
            receipt["roles"].append(role)
            receipt["roles"].sort()
        self.receipts[str(path)] = receipt
        return raw

    def json(self, path, role):
        def nonfinite(value):
            raise InputError("NONFINITE_JSON:" + value)
        return json.loads(self.read(path, role), object_pairs_hook=unique_object, parse_constant=nonfinite)

    def verify(self):
        for path, receipt in self.receipts.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != receipt["sha256"]:
                raise InputError("SOURCE_CHANGED_DURING_EXECUTION:" + path)

    def list(self):
        return [self.receipts[path] for path in sorted(self.receipts)]


class ReadOnlyReceiptStore(ArtifactStore):
    def __init__(self, root, sources):
        super().__init__(root)
        self.sources = sources

    def read(self, artifact_id):
        value = super().read(artifact_id)
        receipt_value = self.sources.json(self.root / (artifact_id + ".json"), "registry_artifact")
        if receipt_value != value or content_hash(receipt_value) != artifact_id:
            raise RegistryError("ARTIFACT_CHANGED_DURING_EXECUTION")
        return value

    def put(self, artifact):
        raise RegistryError("READ_ONLY_REGISTRY")


def reference(base, value):
    if not isinstance(value, str) or not value.strip():
        raise InputError("NONEMPTY_FILE_REFERENCE_REQUIRED")
    return base / value


def identifiers(value):
    if not isinstance(value, list) or any(not isinstance(x, str) or re.fullmatch(r"[0-9a-f]{64}", x) is None for x in value):
        raise InputError("INVALID_REGISTRY_IDS")
    if len(set(value)) != len(value):
        raise InputError("DUPLICATE_REGISTRY_ID")
    return value


def make_registry(args, manifest, sources):
    specified = (args.registry_store is not None, args.trust_file is not None, "registry" in manifest)
    if not any(specified):
        return None
    if not all(specified):
        raise InputError("REGISTRY_REQUIRES_STORE_TRUST_FILE_AND_MANIFEST_IDS")
    registry_spec = manifest["registry"]
    exact_keys(registry_spec, {"record_ids", "revocation_ids"})
    records = identifiers(registry_spec["record_ids"])
    revocations = identifiers(registry_spec["revocation_ids"])
    store_path = Path(args.registry_store).resolve(strict=True)
    if not store_path.is_dir():
        raise InputError("REGISTRY_STORE_MUST_BE_EXISTING_DIRECTORY")
    trust = sources.json(args.trust_file, "explicit_trust_configuration")
    exact_keys(trust, {"schema", "public_keys_b64"})
    if trust["schema"] != "research-validation-trust-v1" or not isinstance(trust["public_keys_b64"], dict):
        raise InputError("INVALID_TRUST_SCHEMA")
    keys = {}
    for signer, encoded in trust["public_keys_b64"].items():
        if not signer.strip() or not isinstance(encoded, str):
            raise InputError("INVALID_TRUSTED_PUBLIC_KEY")
        try:
            key = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise InputError("INVALID_TRUSTED_PUBLIC_KEY") from exc
        if len(key) != 32:
            raise InputError("INVALID_TRUSTED_PUBLIC_KEY_LENGTH")
        keys[signer] = key
    return ValidationRegistry(ReadOnlyReceiptStore(store_path, sources), records,
                              Ed25519Verifier(keys), revocation_ids=revocations)


def parser():
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Manifest schema (all file references relative to the manifest):
  {"schema":"research-selection-manifest-v1","entries":[
    {"entry_id":"example","forecast":"sealed-forecast.json",
     "config":"selector-config.json","quality_receipt":"quality.json",
     "price":"price.json","components":["sealed-sibling.json"]}
  ]}
Only entry_id, forecast and config are mandatory within each entry. Optional
quality_receipt/price may be null; components defaults to []. Forecasts and
quality receipts must already be sealed by the research_selection API. Config
is the explicit research-selector-config-v1 payload, not its artifact wrapper.
No legacy probability orientation, line or settlement convention is inferred.

For registry verification also supply manifest registry:{"record_ids":[...],
"revocation_ids":[...]} and both registry flags. The separate trust JSON is
{"schema":"research-validation-trust-v1","public_keys_b64":{"signer":
"base64 raw 32-byte Ed25519 public key"}}. No keys are trusted by default.
User-supplied trust is not evidence of independent scientific certification.

Outputs: decisions.json and execution_receipt.json, in a NEW directory only.
Missing qualification produces BLOCKED records and exit 0; malformed inputs
produce exit 2. Inputs and registry are read-only. Every output remains SHADOW,
publication/action authority false and wagering OFF. A historical decision
timestamp is explicitly a retrospective diagnostic, never backdated execution.
""")
    result.add_argument("--manifest", required=True, help="Strict JSON manifest path.")
    result.add_argument("--output-dir", required=True, help="New output directory; its parent must exist.")
    result.add_argument("--decision-at-utc", help="Optional historical UTC reference cutoff; marks replay, actual execution time is retained.")
    result.add_argument("--registry-store", help="Existing local content-addressed registry directory (read-only).")
    result.add_argument("--trust-file", help="Explicit trusted public keys, separate from registry artifacts.")
    return result


def execute(args):
    executed = datetime.now(timezone.utc)
    created = executed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    decision_at = args.decision_at_utc or created
    if timestamp(decision_at) > executed:
        raise InputError("FUTURE_DECISION_TIMESTAMP")
    output = Path(args.output_dir).absolute()
    if output.exists() or output.is_symlink():
        raise InputError("OUTPUT_DIRECTORY_ALREADY_EXISTS")
    if not output.parent.is_dir():
        raise InputError("OUTPUT_PARENT_MUST_EXIST")
    sources = Sources()
    for module in (Path(__file__), ROOT / "pipelines/cards/research_selection.py", ROOT / "research/validation_registry.py"):
        sources.read(module, "implementation_source")
    manifest_path = Path(args.manifest).resolve(strict=True)
    manifest = sources.json(manifest_path, "source_manifest")
    exact_keys(manifest, {"schema", "entries"}, {"registry"})
    if manifest["schema"] != "research-selection-manifest-v1" or not isinstance(manifest["entries"], list) or not manifest["entries"]:
        raise InputError("INVALID_OR_EMPTY_MANIFEST")
    registry = make_registry(args, manifest, sources)
    decisions, entry_receipts, entry_ids = [], [], set()
    for entry in manifest["entries"]:
        exact_keys(entry, {"entry_id", "forecast", "config"}, {"quality_receipt", "price", "components"})
        entry_id = entry["entry_id"]
        if not isinstance(entry_id, str) or not entry_id.strip() or entry_id in entry_ids:
            raise InputError("INVALID_OR_DUPLICATE_ENTRY_ID")
        entry_ids.add(entry_id)
        def load(name):
            return sources.json(reference(manifest_path.parent, entry[name]), name)
        forecast, config = load("forecast"), load("config")
        quality = load("quality_receipt") if entry.get("quality_receipt") is not None else None
        price = load("price") if entry.get("price") is not None else None
        component_refs = entry.get("components", [])
        if not isinstance(component_refs, list):
            raise InputError("COMPONENTS_MUST_BE_FILE_REFERENCE_LIST")
        components = [sources.json(reference(manifest_path.parent, value), "component_forecast") for value in component_refs]
        decision = select_research(forecast, config, decision_at_utc=decision_at,
                                   registry=registry, price=price, quality_receipt=quality,
                                   components=components,
                                   replay_at_utc=created if args.decision_at_utc else None)
        verify_selection_record(decision)
        decisions.append(decision)
        entry_receipts.append({"entry_id": entry_id, "decision_id": decision["decision_id"],
                               "price_diagnostics_id": decision["price_diagnostics_id"]})
    sources.verify()
    manifest_hash = sources.receipts[str(manifest_path)]["sha256"]
    board = {"schema": "research-selection-board-v1", "created_at_utc": created,
             "source_manifest_id": content_hash(manifest), "source_manifest_sha256": manifest_hash,
             "source_receipts": sources.list(), "entry_receipts": entry_receipts,
             "execution_mode": "RETROSPECTIVE_DIAGNOSTIC" if args.decision_at_utc else "UNREGISTERED_RESEARCH",
             "publication_allowed": False, "official_release": False, "action_authority": False,
             "wagering_status": "OFF", "decisions": decisions}
    raw_board = (json.dumps(board, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    receipt = {"schema": "research-selection-execution-v1", "created_at_utc": created,
               "source_manifest_id": board["source_manifest_id"], "source_manifest_sha256": manifest_hash,
               "source_receipts": sources.list(), "python_version": sys.version,
               "outputs": [{"path": "decisions.json", "sha256": hashlib.sha256(raw_board).hexdigest(), "byte_count": len(raw_board)}],
               "publication_allowed": False, "action_authority": False, "wagering_status": "OFF"}
    receipt["receipt_id"] = content_hash(receipt)
    raw_receipt = (json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    output.mkdir(exist_ok=False)
    for name, raw in (("decisions.json", raw_board), ("execution_receipt.json", raw_receipt)):
        with (output / name).open("xb") as stream:
            stream.write(raw)
    return {"output_dir": str(output), "decision_count": len(decisions),
            "decision_classes": dict(Counter(x["decision_class"] for x in decisions)), "wagering_status": "OFF"}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        summary = execute(args)
    except (InputError, ResearchSelectionError, RegistryError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc), "publication_allowed": False, "wagering_status": "OFF"}), file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
