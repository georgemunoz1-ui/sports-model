from __future__ import annotations
import json
from pathlib import Path
from research.adapters.base import sha256_file


def write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def write_jsonl(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, sort_keys=True, separators=(",", ":")) + "\n" for x in rows), encoding="utf-8")
    return path


def write_manifest(path: Path, artifact_specs) -> Path:
    artifacts=[]
    for spec in artifact_specs:
        art=Path(spec["absolute_path"]); entry={k:v for k,v in spec.items() if k!="absolute_path"}
        entry["path"]=str(art.relative_to(path.parent)); entry["sha256"]=sha256_file(art); artifacts.append(entry)
    return write_json(path,{"schema_version":"frozen_evaluation_manifest.v1","artifacts":artifacts})
