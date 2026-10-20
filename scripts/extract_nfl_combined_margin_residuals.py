"""Extract the COMBINED arm's margin residuals from model_packed.json.

models/nfl/contextual packs its artifacts as a GZIP_BASE64 wrapper whose
payload carries a top-level ``final_score_residuals`` pool: 1871 paired
[home_score_residual, away_score_residual] rows, one per OOF game
(seasons 2019-2025, per ``residual_seasons``). Per the model design and the
pipelines/margins/nfl.py adapter docstring, this joint final-score residual
pool is COMBINED-arm specific; the runtime reports score_simulation status
UNAVAILABLE_FOR_SELECTED_ARM for the other arms.

Derivation: margin residual = home_score_residual - away_score_residual
(same actual-minus-predicted convention as the margin head, since
M = home_score - away_score).

CRITICAL LIMITATION (carried in the artifact): these residuals are derived
from the paired final-score kernel, NOT from the combined arm's home_margin
ridge head. The artifact is labeled SCORE_PAIR_DERIVED_NOT_MARGIN_HEAD. It
satisfies pipelines/margins/nfl.py's pool/arm consistency check ONLY when the
selected arm is ``combined`` (pool_arm='combined'); with the current default
selection ``qb`` the adapter correctly fail-closes MARGIN_POOL_MODEL_MISMATCH
— that is intended behavior. The real fix for qb/base/availability/travel is
per-arm regeneration via scripts/build_nfl_margin_residuals.py once the
owner's recovered-root OOF frame is restored.

Fail-closed governance:
  * PACKED_MISSING           - input file not found.
  * PACKED_SCHEMA_INVALID    - wrapper/payload fields missing or malformed.
  * PAYLOAD_HASH_MISMATCH    - decoded payload sha256 != wrapper's pin.
  * RESIDUAL_LENGTH_MISMATCH - residuals and seasons disagree in length.
  * EMPIRICAL_MARGIN_MIN_SUPPORT - fewer than 200 derived residuals.

Artifact is deterministic (no wall-clock fields), append-only, research-only.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

SCHEMA = "nfl_combined_margin_residuals.v1"
EMPIRICAL_MARGIN_MIN_SUPPORT = 200  # mirrors models/common/margins/distribution.py
DEFAULT_PACKED = Path("data/nfl/contextual_v1/model_packed.json")
DEFAULT_OUT = Path("data/nfl/margin_residuals/nfl_combined_margin_residuals_v1.json")


class PackedExtractError(ValueError):
    """Fail-closed extraction error with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__(f"{self.code}: {message}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _array_sha(arr: np.ndarray) -> str:
    """Same convention as models/common/margins/distribution._array_sha."""
    arr = np.ascontiguousarray(np.asarray(arr, dtype=np.float64))
    return hashlib.sha256(arr.tobytes()).hexdigest()


def load_packed_payload(packed_path: Path) -> tuple[dict, str]:
    """Decode the GZIP_BASE64 wrapper; verify the embedded payload pin."""
    if not packed_path.is_file():
        raise PackedExtractError("PACKED_MISSING", f"no such file: {packed_path}")
    try:
        wrapper = json.loads(packed_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackedExtractError(
            "PACKED_SCHEMA_INVALID", f"unparsable wrapper: {exc}"
        ) from None
    if (
        not isinstance(wrapper, dict)
        or wrapper.get("encoding") != "GZIP_BASE64"
        or not isinstance(wrapper.get("payload"), str)
        or not isinstance(wrapper.get("sha256"), str)
    ):
        raise PackedExtractError(
            "PACKED_SCHEMA_INVALID",
            "expected {encoding: GZIP_BASE64, sha256, payload} wrapper",
        )
    try:
        raw = gzip.decompress(base64.b64decode(wrapper["payload"]))
    except Exception as exc:  # noqa: BLE001 - fail closed on any decode error
        raise PackedExtractError(
            "PACKED_SCHEMA_INVALID", f"payload decode failed: {exc}"
        ) from None
    digest = hashlib.sha256(raw).hexdigest()
    if digest != wrapper["sha256"].lower():
        raise PackedExtractError(
            "PAYLOAD_HASH_MISMATCH",
            f"decoded payload sha256 {digest} != wrapper pin {wrapper['sha256']}",
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PackedExtractError(
            "PACKED_SCHEMA_INVALID", f"payload JSON invalid: {exc}"
        ) from None
    return payload, digest


def extract_margin_residuals(payload: dict) -> dict:
    pairs = payload.get("final_score_residuals")
    seasons = payload.get("residual_seasons")
    if not isinstance(pairs, list) or not isinstance(seasons, list):
        raise PackedExtractError(
            "PACKED_SCHEMA_INVALID",
            "payload lacks final_score_residuals / residual_seasons lists",
        )
    if len(pairs) != len(seasons):
        raise PackedExtractError(
            "RESIDUAL_LENGTH_MISMATCH",
            f"{len(pairs)} residual pairs vs {len(seasons)} season labels",
        )
    try:
        arr = np.asarray(pairs, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise PackedExtractError(
            "PACKED_SCHEMA_INVALID", f"residual pairs not numeric: {exc}"
        ) from None
    if arr.ndim != 2 or arr.shape[1] != 2 or not np.all(np.isfinite(arr)):
        raise PackedExtractError(
            "PACKED_SCHEMA_INVALID", "final_score_residuals must be finite [n, 2]"
        )
    margin_resid = arr[:, 0] - arr[:, 1]  # home_res - away_res
    n = int(margin_resid.size)
    if n < EMPIRICAL_MARGIN_MIN_SUPPORT:
        raise PackedExtractError(
            "EMPIRICAL_MARGIN_MIN_SUPPORT",
            f"n={n} < {EMPIRICAL_MARGIN_MIN_SUPPORT} derived margin residuals",
        )
    seasons_i = [int(s) for s in seasons]
    xs = np.sort(margin_resid)
    sigma = float(np.std(margin_resid, ddof=1))
    return {
        "n": n,
        "mean": float(np.mean(margin_resid)),
        "sigma": sigma,
        "residuals_sorted": xs.tolist(),
        "residuals_sha256": _array_sha(xs),
        "min_season": min(seasons_i),
        "max_season": max(seasons_i),
        "season_counts": {str(s): seasons_i.count(s) for s in sorted(set(seasons_i))},
    }


def build_artifact(extracted: dict, source: dict) -> dict:
    return {
        "schema": SCHEMA,
        "research_only": True,
        "action_authority": False,
        "sport": "nfl",
        "arm": "combined",
        "model_id": "nfl.integrated_context.combined.v1.research",
        "n": extracted["n"],
        "mean": extracted["mean"],
        "sigma": extracted["sigma"],
        "residuals_sha256": extracted["residuals_sha256"],
        "residuals_sorted": extracted["residuals_sorted"],
        "residual_convention": "actual_minus_predicted",
        "derivation": "margin_residual = home_score_residual - away_score_residual",
        "season_counts": extracted["season_counts"],
        "provenance": {
            "sport": "nfl",
            "oof": True,
            "window_start": str(extracted["min_season"]),
            "window_end": str(extracted["max_season"]),
            "pool_arm": "combined",
            "n": extracted["n"],
            "sigma": extracted["sigma"],
            "source": "model_packed.final_score_residuals",
            "source_sha256": source["sha256"],
            "payload_sha256": source["payload_sha256"],
        },
        "limitations": [
            "SCORE_PAIR_DERIVED_NOT_MARGIN_HEAD",
            "SEASON_GRAIN_WINDOW_NO_WEEK_LABELS",
            "COMBINED_ARM_ONLY_ADAPTER_REJECTS_OTHER_SELECTED_ARMS",
        ],
    }


def write_artifact(artifact: dict, out_path: Path) -> str:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    out_path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _selftest() -> int:
    import tempfile

    rng = np.random.default_rng(20260914)
    pairs = rng.normal(0.0, 10.0, size=(400, 2)).tolist()
    seasons = [2019 + (i // 100) for i in range(400)]
    inner = json.dumps({"final_score_residuals": pairs, "residual_seasons": seasons}).encode()
    wrapper = {
        "encoding": "GZIP_BASE64",
        "sha256": hashlib.sha256(inner).hexdigest(),
        "payload": base64.b64encode(gzip.compress(inner)).decode(),
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        p = tmp / "model_packed.json"
        p.write_text(json.dumps(wrapper))
        payload, _ = load_packed_payload(p)
        ext = extract_margin_residuals(payload)
        expect = np.sort(np.asarray(pairs)[:, 0] - np.asarray(pairs)[:, 1])
        if not np.allclose(ext["residuals_sorted"], expect):
            print("SELFTEST FAILED: derivation mismatch")
            return 1
        art = build_artifact(ext, source={"sha256": "x", "payload_sha256": "y"})
        if art["provenance"]["pool_arm"] != "combined" or art["provenance"]["oof"] is not True:
            print("SELFTEST FAILED: provenance schema")
            return 1
        if "SCORE_PAIR_DERIVED_NOT_MARGIN_HEAD" not in art["limitations"]:
            print("SELFTEST FAILED: limitation label missing")
            return 1
        # corrupted payload pin must fail closed
        wrapper["sha256"] = "0" * 64
        p.write_text(json.dumps(wrapper))
        try:
            load_packed_payload(p)
        except PackedExtractError as exc:
            if exc.code != "PAYLOAD_HASH_MISMATCH":
                print(f"SELFTEST FAILED: wrong code {exc.code}")
                return 1
        else:
            print("SELFTEST FAILED: PAYLOAD_HASH_MISMATCH not raised")
            return 1
        # length mismatch must fail closed
        bad = json.dumps({"final_score_residuals": pairs, "residual_seasons": seasons[:-1]}).encode()
        wrapper2 = {
            "encoding": "GZIP_BASE64",
            "sha256": hashlib.sha256(bad).hexdigest(),
            "payload": base64.b64encode(gzip.compress(bad)).decode(),
        }
        p.write_text(json.dumps(wrapper2))
        payload2, _ = load_packed_payload(p)
        try:
            extract_margin_residuals(payload2)
        except PackedExtractError as exc:
            if exc.code != "RESIDUAL_LENGTH_MISMATCH":
                print(f"SELFTEST FAILED: wrong code {exc.code}")
                return 1
        else:
            print("SELFTEST FAILED: RESIDUAL_LENGTH_MISMATCH not raised")
            return 1
    print("SELFTEST OK: derivation, provenance, and fail-closed paths verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--packed", type=Path, default=DEFAULT_PACKED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()
    payload, payload_sha = load_packed_payload(args.packed)
    extracted = extract_margin_residuals(payload)
    artifact = build_artifact(
        extracted,
        source={"sha256": sha256_file(args.packed), "payload_sha256": payload_sha},
    )
    digest = write_artifact(artifact, args.out)
    print(f"wrote {args.out} (sha256 {digest})")
    print(f"n={extracted['n']} mean={extracted['mean']:+.4f} sigma={extracted['sigma']:.4f} "
          f"seasons {extracted['min_season']}-{extracted['max_season']}")
    print("LIMITATION: SCORE_PAIR_DERIVED_NOT_MARGIN_HEAD; pool_arm=combined only — "
          "adapter fail-closes MARGIN_POOL_MODEL_MISMATCH for any other selected arm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
