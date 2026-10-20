#!/usr/bin/env python3
"""Build the WNBA qualifying-OOF margin fitting artifacts (RESEARCH-ONLY).

Parent model: wnba.rs.ff7_logit_ridge.v1_0.shadow (harness/wnba_model_v1.py — imported, never
copied or modified). This script re-runs the committed pipeline over the committed staged bytes:

    build_games()  ->  official-plus-one pool (cutoff 2026-07-22, ET dates)
    + EXTENSION_ESPN/ext_2026.json (strictly after the cutoff, single-family grade)
    -> make_rows() -> walk_forward()   (expanding, date-ordered, burn-in 300,
                                        fold-local standardization, b2b_edge raw)

and RETAINS what evaluate() always discarded: per-game (date, m_pred, m_act). From the retained
bank it emits two append-only, hash-pinned, research-only artifacts:

    data/wnba/model/wnba_margin_oof_residuals_v1.json   per-row bank + provenance + sigma
    data/wnba/model/wnba_margin_ridge_head_v1.json      bmar repack for the margin adapter

SIGN CONVENTION (explicit, recorded in the manifest). The legacy bank
data/wnba/model/wnba_margin_residuals_2026-08-29.npy stored residuals as (pred - actual).
models/common/margins/sigma.py defines residual = (actual - pred). This script standardizes on
(actual - pred) everywhere; the legacy bank, when used, is multiplied by -1. The conversion is
recorded verbatim in the manifest's sign_convention block.

REPRODUCTION CHECK (fail-closed). The retained bank must reproduce the externally verified
legacy measurement (data/wnba/model/wnba_margin_sd_measurement.json, record
WNBA-MARGIN-SD-2026-08-29): n == 1721, |MAE - 9.881| < 0.01, |sd - 12.5523| < 0.01 (sd is
population std, ddof=0; sign-invariant). Any mismatch raises OOF_REPRODUCTION_MISMATCH and
NOTHING is written — the new artifact must be a faithful re-wrap of the verified run, never a
silently different fit. If the legacy .npy is present, an elementwise check (after the sign
conversion above) is applied in addition.

GOVERNANCE. research_only=true / action_authority=false on every artifact. No market data is
read; nothing here prices, quotes, or recommends anything. Failures are SCREAMING_SNAKE error
codes carried on OofBuildError.code.

SANDBOX NOTE. Data loading (parquet staging reads) is isolated in load_games(); everything
downstream operates on plain row dicts and is exercised by tests with synthetic fixtures.
--selftest runs a synthetic mini-league end-to-end (chronology + determinism) without parquet.

Usage (from repo root):
    python3 scripts/build_wnba_margin_oof.py --selftest
    python3 scripts/build_wnba_margin_oof.py            # real regeneration (needs pyarrow)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np

# ---------------------------------------------------------------------------
# Error codes (stable strings, carried on OofBuildError.code)
# ---------------------------------------------------------------------------
OOF_PIPELINE_IMPORT_FAILED = "OOF_PIPELINE_IMPORT_FAILED"
OOF_MARGIN_LAYER_IMPORT_FAILED = "OOF_MARGIN_LAYER_IMPORT_FAILED"
OOF_DATA_LOAD_FAILED = "OOF_DATA_LOAD_FAILED"
OOF_EXTENSION_INVALID = "OOF_EXTENSION_INVALID"
OOF_DUPLICATE_GAME_CONTENT = "OOF_DUPLICATE_GAME_CONTENT"
OOF_BANK_EMPTY = "OOF_BANK_EMPTY"
OOF_CHRONOLOGY_VIOLATION = "OOF_CHRONOLOGY_VIOLATION"
OOF_REPRODUCTION_MISMATCH = "OOF_REPRODUCTION_MISMATCH"
OOF_HEAD_SCHEMA_MISMATCH = "OOF_HEAD_SCHEMA_MISMATCH"
OOF_HEAD_NUMERIC_MISMATCH = "OOF_HEAD_NUMERIC_MISMATCH"
OOF_WINDOW_INVALID = "OOF_WINDOW_INVALID"
OOF_ARTIFACT_IMMUTABLE = "OOF_ARTIFACT_IMMUTABLE"

MODEL_ID = "wnba.rs.ff7_logit_ridge.v1_0.shadow"
SPORT = "wnba"
DATE_TIMEZONE = "America/New_York"  # pool/feature dates are ET calendar dates (harness rule)

# Frozen feature order (mirror of harness/wnba_model_v1.FEATS; asserted equal at runtime when
# the harness is importable — drift here is a schema incident, not a reorder).
FROZEN_FEATURES = ["net_rtg_edge", "efg_edge", "tov_edge", "orb_edge", "ftr_edge",
                   "rest_edge", "b2b_edge"]
N_CONT = 6  # first 6 features are standardized; b2b_edge (index 6) NEVER is

# Legacy externally verified measurement (data/wnba/model/wnba_margin_sd_measurement.json,
# record WNBA-MARGIN-SD-2026-08-29). The retained bank must reproduce these numbers.
LEGACY_REFERENCE = {
    "source_file": "data/wnba/model/wnba_margin_sd_measurement.json",
    "record_id": "WNBA-MARGIN-SD-2026-08-29",
    "record_sha256": "94a69c61d602b7b1b98d53327a1fb8a4a3112170735196c2f3319324cd783a8d",
    "n": 1721,
    "mae": 9.881,
    "sd": 12.5523,
    "tolerance": 0.01,
    "residual_sign": "pred_minus_actual",
}

SIGN_CONVENTION = {
    "emitted": "actual_minus_pred",
    "legacy_bank": "pred_minus_actual",
    "conversion": "emitted_residual = -1 * legacy_residual (elementwise); MAE and sd are "
                  "sign-invariant, mean bias flips sign",
    "canonical_definition": "models/common/margins/sigma.py: residual = actual - pred",
}

LIMITATIONS = [
    "RESEARCH_ONLY_NO_ACTION_AUTHORITY",
    "SIGMA_AND_HEAD_ARE_MODEL_DEPENDENT",
    "DISTRIBUTION_INPUT_NOT_A_PRICE",
]

DEFAULT_OUT_DIR = "data/wnba/model"
DEFAULT_STAGE_DIR = "data/wnba/source/staging"
DEFAULT_EXT = "data/wnba/source/staging/EXTENSION_ESPN/ext_2026.json"
DEFAULT_LEGACY_NPY = "data/wnba/model/wnba_margin_residuals_2026-08-29.npy"
OOF_ARTIFACT = "wnba_margin_oof_residuals_v1.json"
HEAD_ARTIFACT = "wnba_margin_ridge_head_v1.json"


class OofBuildError(RuntimeError):
    """Fail-closed build failure with a stable machine-readable ``.code``."""

    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__(f"{self.code}: {message}")


# ---------------------------------------------------------------------------
# Canonical JSON / hashing (same canonical form as models/common/margins/emit.py)
# ---------------------------------------------------------------------------
def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_obj(obj) -> str:
    return sha256_text(canonical_json(obj))


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
# Margin layer import (models.common.margins.sigma — chronological OOF sigma)
# ---------------------------------------------------------------------------
def import_margin_layer(repo_root: str, margin_layer_path: str | None = None):
    """Import estimate_sigma; search repo root, then MARGIN_LAYER_PATH/env, then sibling path."""
    candidates = [p for p in (
        repo_root,
        margin_layer_path,
        os.environ.get("MARGIN_LAYER_PATH"),
    ) if p]
    for cand in candidates:
        if cand not in sys.path:
            sys.path.insert(0, cand)
        try:
            from models.common.margins.sigma import estimate_sigma
            return estimate_sigma
        except ImportError:
            continue
    raise OofBuildError(
        OOF_MARGIN_LAYER_IMPORT_FAILED,
        "models.common.margins.sigma is not importable from the repo root or "
        "MARGIN_LAYER_PATH; the margin layer (feature/margin-distribution-system) is required",
    )


# ---------------------------------------------------------------------------
# Harness import + DATA LOADING (the ONLY parquet-touching section; isolated by design)
# ---------------------------------------------------------------------------
def import_harness(repo_root: str):
    """Import harness/wnba_model_v1.py (+ wnba_refresh_espn for the extension contract).

    Never copied, never modified. wnba_model_v1 imports pyarrow at module load, so this fails
    closed with OOF_PIPELINE_IMPORT_FAILED in environments without pyarrow."""
    harness_dir = os.path.join(repo_root, "harness")
    if not os.path.isdir(harness_dir):
        raise OofBuildError(OOF_PIPELINE_IMPORT_FAILED,
                            f"no harness/ directory under repo root {repo_root}")
    if harness_dir not in sys.path:
        sys.path.insert(0, harness_dir)
    try:
        import wnba_model_v1 as W
        import wnba_refresh_espn as R
    except Exception as exc:  # pyarrow missing, staging missing, etc.
        raise OofBuildError(
            OOF_PIPELINE_IMPORT_FAILED,
            f"harness import failed: {exc!r} (the real regeneration requires pyarrow and the "
            "committed staged bytes; run inside the sports-model environment)",
        ) from exc
    if list(W.FEATS) != FROZEN_FEATURES or int(W.CONT) != N_CONT:
        raise OofBuildError(
            OOF_HEAD_SCHEMA_MISMATCH,
            f"harness FEATS/CONT drifted from the frozen mirror: {W.FEATS} CONT={W.CONT}",
        )
    return W, R


def load_games(W, R, stage_dir: str, ext_path: str):
    """Committed-data game pool: official-plus-one base (<= cutoff) + ESPN extension.

    This is the small, isolated data-loading function. Everything downstream consumes plain
    game dicts, so tests never touch parquet. Returns (combined_games, extension_artifact)."""
    stage_dir = os.path.abspath(stage_dir)
    ext_path = os.path.abspath(ext_path)
    try:
        W.STAGE = stage_dir  # harness resolves staging paths through this module global
        base = W.build_games()
    except OofBuildError:
        raise
    except Exception as exc:
        raise OofBuildError(OOF_DATA_LOAD_FAILED,
                            f"build_games() over staged parquet failed: {exc!r}") from exc
    base = [g for g in base if g["date"] <= R.CUTOFF or g["season"] < 2026]
    if not os.path.exists(ext_path):
        raise OofBuildError(OOF_DATA_LOAD_FAILED,
                            f"extension artifact not found at {ext_path}")
    try:
        art = json.load(open(ext_path))
    except Exception as exc:
        raise OofBuildError(OOF_EXTENSION_INVALID,
                            f"extension artifact is not valid JSON: {exc!r}") from exc
    if art.get("schema") != "ops.espn_extension.v1" or not art.get("games"):
        raise OofBuildError(OOF_EXTENSION_INVALID,
                            "extension artifact must be schema ops.espn_extension.v1 with games")
    if any(g["date"] <= art.get("cutoff_exclusive", R.CUTOFF) for g in art["games"]):
        raise OofBuildError(OOF_EXTENSION_INVALID,
                            "extension games must be strictly after the base-pool cutoff")
    ext = [{k: g[k] for k in ("date", "season", "gid", "home", "away", "hpts", "apts",
                              "H", "A", "et_date", "utc_instant")}
           for g in art["games"]]
    combined = base + ext
    dups = R.duplicate_content_violations(combined)
    if dups:
        raise OofBuildError(
            OOF_DUPLICATE_GAME_CONTENT,
            "duplicate game content across base/extension id spaces: "
            + "; ".join(f"{k} ({a} vs {b})" for k, a, b in dups[:5]),
        )
    combined.sort(key=lambda g: (g["date"], str(g["gid"])))
    return combined, art


# ---------------------------------------------------------------------------
# Retained bank: (date, m_pred, m_act) -> rows with residual = actual - pred
# ---------------------------------------------------------------------------
def retained_bank(walk_forward_out: dict):
    """Extract the retained per-game margin bank from harness walk_forward() output.

    Enforces chronological order (non-decreasing date) fail-closed: a sigma over a
    non-chronological 'OOF' bank is not an OOF measurement."""
    d = list(walk_forward_out["d"])
    m_pred = [float(v) for v in walk_forward_out["m_pred"]]
    m_act = [float(v) for v in walk_forward_out["m_act"]]
    if not (len(d) == len(m_pred) == len(m_act)):
        raise OofBuildError(OOF_BANK_EMPTY,
                            "walk_forward output d/m_pred/m_act length mismatch or empty")
    if not d:
        raise OofBuildError(OOF_BANK_EMPTY, "walk_forward retained zero scored games")
    for a, b in zip(d, d[1:]):
        if b < a:
            raise OofBuildError(
                OOF_CHRONOLOGY_VIOLATION,
                f"retained bank is not chronological: {b} follows {a}",
            )
    rows = []
    for dd, p, a in zip(d, m_pred, m_act):
        if not (np.isfinite(p) and np.isfinite(a)):
            raise OofBuildError(OOF_BANK_EMPTY, f"non-finite pred/actual on {dd}")
        rows.append({"date": str(dd), "pred": p, "actual": a, "residual": a - p})
    return rows


def bank_stats(rows):
    """n / MAE / population sd (ddof=0, matching the legacy sd_measured) of the retained bank."""
    resid = np.array([r["residual"] for r in rows], dtype=np.float64)
    return {"n": int(resid.size),
            "mae": float(np.mean(np.abs(resid))),
            "sd": float(resid.std(ddof=0)),
            "mean_bias": float(resid.mean())}


def convert_legacy_residuals(legacy_pred_minus_actual) -> np.ndarray:
    """Legacy .npy is (pred - actual); the canonical convention is (actual - pred)."""
    legacy = np.asarray(legacy_pred_minus_actual, dtype=np.float64).ravel()
    if not np.all(np.isfinite(legacy)):
        raise OofBuildError(OOF_REPRODUCTION_MISMATCH,
                            "legacy residual bank contains non-finite values")
    return -1.0 * legacy


def reproduction_check(rows, reference=None, legacy_residuals_pred_minus_actual=None):
    """Fail-closed check that the recomputed bank reproduces the verified legacy measurement.

    Raises OOF_REPRODUCTION_MISMATCH on any deviation; returns the report dict on success."""
    reference = reference or LEGACY_REFERENCE
    obs = bank_stats(rows)
    tol = float(reference["tolerance"])
    failures = []
    if obs["n"] != int(reference["n"]):
        failures.append(f"n {obs['n']} != {reference['n']}")
    if abs(obs["mae"] - float(reference["mae"])) >= tol:
        failures.append(f"MAE {obs['mae']:.4f} vs legacy {reference['mae']} (tol {tol})")
    if abs(obs["sd"] - float(reference["sd"])) >= tol:
        failures.append(f"sd {obs['sd']:.4f} vs legacy {reference['sd']} (tol {tol})")
    elementwise = None
    if legacy_residuals_pred_minus_actual is not None:
        legacy = convert_legacy_residuals(legacy_residuals_pred_minus_actual)
        ours = np.array([r["residual"] for r in rows], dtype=np.float64)
        elementwise = bool(legacy.shape == ours.shape and np.allclose(legacy, ours, atol=1e-9))
        if not elementwise:
            failures.append("elementwise mismatch vs legacy .npy after sign conversion "
                            "(residual = actual - pred = -1 * legacy)")
    report = {"reference": dict(reference), "observed": obs,
              "sign_convention": dict(SIGN_CONVENTION),
              "elementwise_vs_legacy_npy": elementwise, "passed": not failures}
    if failures:
        raise OofBuildError(OOF_REPRODUCTION_MISMATCH,
                            "retained bank does not reproduce the verified legacy measurement: "
                            + "; ".join(failures))
    return report


# ---------------------------------------------------------------------------
# Provenance + sigma
# ---------------------------------------------------------------------------
def build_provenance(rows, pool: dict | None = None) -> dict:
    if not rows:
        raise OofBuildError(OOF_BANK_EMPTY, "no retained rows for provenance")
    window_start, window_end = rows[0]["date"], rows[-1]["date"]  # chronology already enforced
    if not (window_start <= window_end):
        raise OofBuildError(OOF_WINDOW_INVALID, "window_start must be <= window_end")
    prov = {"sport": SPORT, "oof": True,
            "window_start": window_start, "window_end": window_end,
            "date_timezone": DATE_TIMEZONE,
            "method": "expanding date-ordered walk-forward (burn-in 300, fold-local "
                      "standardization); per-game m_pred/m_act retained from "
                      "harness/wnba_model_v1.walk_forward()",
            "residual_definition": "actual - pred (home-orientation margin)"}
    if pool:
        prov["pool"] = dict(pool)
    return prov


def run_estimate_sigma(estimate_sigma, rows, provenance, min_n: int = 200) -> dict:
    """Call models.common.margins.sigma.estimate_sigma and return its output VERBATIM."""
    pred = np.array([r["pred"] for r in rows], dtype=np.float64)
    actual = np.array([r["actual"] for r in rows], dtype=np.float64)
    prov = {"sport": provenance["sport"], "oof": True,
            "window_start": provenance["window_start"], "window_end": provenance["window_end"]}
    return estimate_sigma(pred, actual, min_n=min_n, provenance=prov)


def sigma_provenance_block(sigma_estimate: dict, provenance: dict) -> dict:
    """The adapter-facing sigma provenance: estimate output + OOF window evidence.

    Consumable verbatim by pipelines.margins._shared.require_sigma."""
    return {**sigma_estimate, "oof": True,
            "window_start": provenance["window_start"],
            "window_end": provenance["window_end"]}


# ---------------------------------------------------------------------------
# Ridge head repack (bmar + mu/sd -> adapter head dict)
# ---------------------------------------------------------------------------
def repack_ridge_head(fit_full_out: dict) -> dict:
    """Repack harness fit_full() into the adapter head format
    {impute, mean, scale, coefficient, intercept} (pipelines.margins._shared.margin_from_ridge_head).

    bmar is [intercept, coef_1..coef_7] in the frozen feature order, fit on features whose first
    6 columns were standardized with (mu, sd); b2b_edge (index 6) was never standardized, so its
    head entries are mean=0.0, scale=1.0 (raw passthrough)."""
    try:
        bmar = np.asarray(fit_full_out["bmar"], dtype=np.float64).ravel()
        mu = np.asarray(fit_full_out["mu"], dtype=np.float64).ravel()
        sd = np.asarray(fit_full_out["sd"], dtype=np.float64).ravel()
    except Exception as exc:
        raise OofBuildError(OOF_HEAD_SCHEMA_MISMATCH,
                            f"fit_full output lacks bmar/mu/sd arrays: {exc!r}") from exc
    if bmar.shape[0] != len(FROZEN_FEATURES) + 1:
        raise OofBuildError(OOF_HEAD_SCHEMA_MISMATCH,
                            f"bmar must have 1 + {len(FROZEN_FEATURES)} entries, "
                            f"got {bmar.shape[0]}")
    if mu.shape[0] != N_CONT or sd.shape[0] != N_CONT:
        raise OofBuildError(OOF_HEAD_SCHEMA_MISMATCH,
                            f"mu/sd must cover the {N_CONT} standardized features")
    if not np.all(np.isfinite(bmar)) or not np.all(np.isfinite(mu)) or not np.all(np.isfinite(sd)):
        raise OofBuildError(OOF_HEAD_SCHEMA_MISMATCH, "non-finite entries in bmar/mu/sd")
    head = {"impute": [0.0] * len(FROZEN_FEATURES),
            "mean": [float(v) for v in mu] + [0.0],
            "scale": [float(v) for v in sd] + [1.0],
            "coefficient": [float(v) for v in bmar[1:]],
            "intercept": float(bmar[0])}
    return head


def head_predict(head: dict, x_raw) -> float:
    """Reference application of the head (mirrors margin_from_ridge_head, no imputation path)."""
    x = np.asarray(x_raw, dtype=np.float64).ravel()
    mean = np.asarray(head["mean"], dtype=np.float64)
    scale = np.asarray(head["scale"], dtype=np.float64)
    coef = np.asarray(head["coefficient"], dtype=np.float64)
    if not (x.shape == mean.shape == scale.shape == coef.shape):
        raise OofBuildError(OOF_HEAD_SCHEMA_MISMATCH, "head/x shape mismatch")
    z = (x - mean) / scale
    return float(np.dot(z, coef) + float(head["intercept"]))


def verify_head_numeric(head: dict, fit_full_out: dict, x_rows, tol: float = 1e-9) -> float:
    """The repacked head must reproduce harness _ols_raw(bmar, standardized x) exactly."""
    bmar = np.asarray(fit_full_out["bmar"], dtype=np.float64).ravel()
    mu = np.asarray(fit_full_out["mu"], dtype=np.float64).ravel()
    sd = np.asarray(fit_full_out["sd"], dtype=np.float64).ravel()
    worst = 0.0
    for x in x_rows:
        xs = np.asarray(x, dtype=np.float64).ravel().copy()
        xs[:N_CONT] = (xs[:N_CONT] - mu) / sd
        ref = float(bmar[0] + np.dot(xs, bmar[1:]))
        got = head_predict(head, xs_to_raw(xs, mu, sd))
        worst = max(worst, abs(ref - got))
    if worst > tol:
        raise OofBuildError(OOF_HEAD_NUMERIC_MISMATCH,
                            f"repacked head deviates from bmar by {worst:.3e} > {tol}")
    return worst


def xs_to_raw(xs_standardized, mu, sd):
    raw = np.asarray(xs_standardized, dtype=np.float64).copy()
    raw[:N_CONT] = raw[:N_CONT] * np.asarray(sd) + np.asarray(mu)
    return raw


# ---------------------------------------------------------------------------
# Artifact assembly + append-only write
# ---------------------------------------------------------------------------
def build_oof_manifest(rows, provenance, reproduction_report, sigma_estimate,
                       pool: dict | None = None) -> dict:
    payload = {"rows": rows}
    manifest = {
        "schema": "wnba.margin_oof_residuals.v1",
        "record_id": "WNBA-MARGIN-OOF-RESIDUALS-V1",
        "research_only": True,
        "action_authority": False,
        "model_id": MODEL_ID,
        "created_by": "scripts/build_wnba_margin_oof.py",
        "sign_convention": dict(SIGN_CONVENTION),
        "provenance": dict(provenance),
        "reproduction_check": reproduction_report,
        "sigma_estimate": sigma_estimate,
        "sigma_provenance": sigma_provenance_block(sigma_estimate, provenance),
        "payload": payload,
        "payload_sha256": sha256_obj(payload),
        "limitations": list(LIMITATIONS),
    }
    return manifest


def build_head_artifact(head, sigma_estimate, provenance, oof_payload_sha256,
                        model_package_sha256=None, harness_sha256=None,
                        head_numeric_worst_dev: float | None = None) -> dict:
    return {
        "schema": "wnba.margin_ridge_head.v1",
        "record_id": "WNBA-MARGIN-RIDGE-HEAD-V1",
        "research_only": True,
        "action_authority": False,
        "model_id": MODEL_ID,
        "created_by": "scripts/build_wnba_margin_oof.py",
        "feature_names": list(FROZEN_FEATURES),
        "head": head,
        "head_sha256": sha256_obj(head),
        "standardization_note": "coefficient order follows feature_names exactly; the first "
                                f"{N_CONT} features are standardized with head.mean/head.scale; "
                                "b2b_edge (index 6) is never standardized, so its head entries "
                                "are mean=0.0, scale=1.0 (raw passthrough)",
        "imputation_note": "impute values are raw-feature 0.0 (no edge) applied before "
                           "standardization, per margin_from_ridge_head",
        "head_numeric_check_max_abs_dev": head_numeric_worst_dev,
        "sigma_estimate": sigma_estimate,
        "sigma_provenance": sigma_provenance_block(sigma_estimate, provenance),
        "oof_residuals_payload_sha256": oof_payload_sha256,
        "model_package_sha256": model_package_sha256,
        "model_package_sha256_note": None if model_package_sha256 else
            "no package.json is registered for this model; code identity is carried by "
            "harness_sha256 instead",
        "harness_sha256": harness_sha256,
        "limitations": list(LIMITATIONS),
    }


def write_append_only(path: str, text: str) -> str:
    """Append-only semantics: never mutate an existing artifact. Identical re-write is a no-op;
    different content at an existing path fails closed with OOF_ARTIFACT_IMMUTABLE."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if os.path.exists(path):
        with open(path) as fh:
            existing = fh.read()
        if existing == text:
            return "unchanged"
        raise OofBuildError(
            OOF_ARTIFACT_IMMUTABLE,
            f"{path} already exists with different content; artifacts are append-only — "
            "write a new versioned name instead of overwriting",
        )
    with open(path, "w") as fh:
        fh.write(text)
    return "written"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def build_and_emit(rows, fit_full_out, *, estimate_sigma, out_dir,
                   reference=None, legacy_residuals=None, provenance_pool=None,
                   model_package_sha256=None, harness_sha256=None, min_n: int = 200,
                   head_check_rows=None):
    """Pure downstream pipeline (no parquet): bank -> checks -> sigma -> artifacts."""
    report = reproduction_check(rows, reference=reference, legacy_residuals_pred_minus_actual=legacy_residuals)
    provenance = build_provenance(rows, pool=provenance_pool)
    sigma_estimate = run_estimate_sigma(estimate_sigma, rows, provenance, min_n=min_n)
    head = repack_ridge_head(fit_full_out)
    worst = None
    if head_check_rows:
        worst = verify_head_numeric(head, fit_full_out, head_check_rows)
    manifest = build_oof_manifest(rows, provenance, report, sigma_estimate)
    head_artifact = build_head_artifact(
        head, sigma_estimate, provenance, manifest["payload_sha256"],
        model_package_sha256=model_package_sha256, harness_sha256=harness_sha256,
        head_numeric_worst_dev=worst)
    oof_path = os.path.join(out_dir, OOF_ARTIFACT)
    head_path = os.path.join(out_dir, HEAD_ARTIFACT)
    oof_status = write_append_only(oof_path, json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    head_status = write_append_only(head_path, json.dumps(head_artifact, indent=1, sort_keys=True) + "\n")
    return {"oof_path": oof_path, "head_path": head_path,
            "oof_status": oof_status, "head_status": head_status,
            "manifest": manifest, "head_artifact": head_artifact}


def find_model_package_sha256(repo_root: str, explicit: str | None = None):
    """model_sha256 linkage if a package.json is registered for this model (else None)."""
    candidates = []
    if explicit:
        candidates.append(explicit)
    mdir = os.path.join(repo_root, "models", "wnba")
    if os.path.isdir(mdir):
        for root, _dirs, files in os.walk(mdir):
            if "package.json" in files:
                candidates.append(os.path.join(root, "package.json"))
    for cand in candidates:
        if os.path.exists(cand):
            return sha256_file(cand)
    return None


def real_run(args) -> dict:
    repo_root = os.path.abspath(args.repo_root)
    estimate_sigma = import_margin_layer(repo_root, args.margin_layer_path)
    W, R = import_harness(repo_root)
    games, art = load_games(W, R, args.stage_dir, args.ext)
    rows_all, _ts, _lg = W.make_rows(games)
    out = W.walk_forward(rows_all)
    bank = retained_bank(out)
    legacy = None
    legacy_path = os.path.abspath(args.legacy_npy)
    if os.path.exists(legacy_path):
        legacy = np.load(legacy_path)
    fit = W.fit_full(rows_all)
    pool = {"base_games": len([g for g in games if g.get("season", 2026) < 2026
                             or g["date"] <= R.CUTOFF]),
            "extension_games": len(art["games"]),
            "extension_sha256": sha256_file(os.path.abspath(args.ext)),
            "model_rows": len(rows_all),
            "extension_provenance": art.get("provenance")}
    check_rows = [np.asarray(r["x"], dtype=np.float64) for r in rows_all[:25]]
    return build_and_emit(
        bank, fit, estimate_sigma=estimate_sigma, out_dir=args.out_dir,
        legacy_residuals=legacy, provenance_pool=pool,
        model_package_sha256=find_model_package_sha256(repo_root, args.package_json),
        harness_sha256=sha256_file(os.path.join(repo_root, "harness", "wnba_model_v1.py")),
        min_n=args.min_n, head_check_rows=check_rows)


# ---------------------------------------------------------------------------
# --selftest: synthetic mini-league end-to-end (chronology + determinism), no parquet
# ---------------------------------------------------------------------------
def synthetic_walk_forward_out(n: int = 320, seed: int = 7) -> dict:
    """Synthetic retained bank: dates ascending, a planted linear margin + noise.

    Stands in for harness walk_forward() output so the full downstream pipeline is exercised
    without the staged bytes. n >= 300 keeps the default sigma min_n=200 satisfiable."""
    import datetime as dt
    rng = np.random.default_rng(seed)
    n_dates = 160
    day0 = dt.date(2026, 5, 1)
    dates = sorted((day0 + dt.timedelta(days=i % n_dates)).isoformat() for i in range(n))
    true_margin = 2.5 + rng.normal(0.0, 6.0, n)
    resid = rng.normal(0.0, 11.0, n)
    m_pred = true_margin
    m_act = true_margin + resid
    return {"d": dates, "m_pred": list(m_pred), "m_act": list(m_act)}


def synthetic_fit_full(seed: int = 11) -> dict:
    rng = np.random.default_rng(seed)
    return {"mu": rng.normal(0, 0.5, N_CONT),
            "sd": np.abs(rng.normal(1.0, 0.2, N_CONT)) + 0.1,
            "bmar": np.concatenate([[2.5], rng.normal(0, 1.5, len(FROZEN_FEATURES))])}


def selftest(margin_layer_path: str | None = None, out_dir: str | None = None) -> bool:
    import tempfile
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    estimate_sigma = None
    try:
        estimate_sigma = import_margin_layer(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), margin_layer_path)
    except OofBuildError as exc:
        fails.append(f"margin layer unavailable in selftest: {exc}")

    # 1. synthetic bank -> downstream pipeline, twice: determinism + append-only no-op
    out = synthetic_walk_forward_out()
    rows = retained_bank(out)
    check(len(rows) == len(out["d"]) and rows[0]["date"] <= rows[-1]["date"],
          "synthetic bank not retained in chronological order")
    fit = synthetic_fit_full()
    rng = np.random.default_rng(21)
    check_rows = [rng.normal(0, 1, len(FROZEN_FEATURES)) for _ in range(50)]
    ref = dict(LEGACY_REFERENCE)
    stats = bank_stats(rows)
    ref.update({"n": stats["n"], "mae": stats["mae"], "sd": stats["sd"],
                "record_id": "SELFTEST-SYNTHETIC", "source_file": "(synthetic)",
                "record_sha256": "(synthetic)"})
    tmp = out_dir or tempfile.mkdtemp(prefix="wnba_oof_selftest_")
    try:
        if estimate_sigma is not None:
            r1 = build_and_emit(rows, fit, estimate_sigma=estimate_sigma, out_dir=tmp,
                                reference=ref, head_check_rows=check_rows)
            r2 = build_and_emit(rows, fit, estimate_sigma=estimate_sigma, out_dir=tmp,
                                reference=ref, head_check_rows=check_rows)
            check(r1["oof_status"] == "written" and r2["oof_status"] == "unchanged",
                  "append-only re-run must be an identical no-op")
            check(r1["manifest"]["payload_sha256"] == r2["manifest"]["payload_sha256"],
                  "payload hash not deterministic across runs")
            check(r1["manifest"]["research_only"] is True
                  and r1["manifest"]["action_authority"] is False
                  and r1["head_artifact"]["research_only"] is True
                  and r1["head_artifact"]["action_authority"] is False,
                  "research_only/action_authority labels missing")
            sp = r1["head_artifact"]["sigma_provenance"]
            check(sp.get("oof") is True and "window_start" in sp and "window_end" in sp
                  and sp.get("label_in_sample") is False and sp.get("sport") == SPORT,
                  "sigma_provenance block is not require_sigma-compatible")
    except OofBuildError as exc:
        fails.append(f"selftest build_and_emit failed: {exc}")

    # 2. chronology enforcement fails closed
    bad = {"d": ["2026-06-02", "2026-06-01"], "m_pred": [1.0, 2.0], "m_act": [2.0, 1.0]}
    try:
        retained_bank(bad)
        fails.append("chronology violation not caught")
    except OofBuildError as exc:
        check(exc.code == OOF_CHRONOLOGY_VIOLATION, f"wrong code: {exc.code}")

    # 3. reproduction check fails closed on tampered reference
    tampered = dict(ref); tampered["mae"] = float(ref["mae"]) + 1.0
    try:
        reproduction_check(rows, reference=tampered)
        fails.append("tampered MAE not caught")
    except OofBuildError as exc:
        check(exc.code == OOF_REPRODUCTION_MISMATCH, f"wrong code: {exc.code}")

    # 4. head repack: b2b passthrough + numeric equivalence with bmar
    head = repack_ridge_head(fit)
    check(head["mean"][6] == 0.0 and head["scale"][6] == 1.0,
          "b2b_edge head entries must be mean=0.0 scale=1.0")
    check(len(head["coefficient"]) == len(FROZEN_FEATURES), "coefficient length wrong")
    try:
        worst = verify_head_numeric(head, fit, check_rows)
        check(worst <= 1e-9, f"head numeric deviation {worst}")
    except OofBuildError as exc:
        fails.append(f"head numeric check failed: {exc}")

    print("build_wnba_margin_oof selftest:", "FAIL\n  " + "\n  ".join(fails) if fails else
          "PASS (synthetic mini-league: chronology, determinism, reproduction gate, head repack, "
          "sigma integration)")
    return not fails


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--stage-dir", default=DEFAULT_STAGE_DIR)
    ap.add_argument("--ext", default=DEFAULT_EXT)
    ap.add_argument("--legacy-npy", default=DEFAULT_LEGACY_NPY)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--package-json", default=None,
                    help="optional explicit model package.json for model_sha256 linkage")
    ap.add_argument("--margin-layer-path", default=None,
                    help="optional extra sys.path entry holding models/common/margins")
    ap.add_argument("--min-n", type=int, default=200)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return 0 if selftest(args.margin_layer_path) else 1
    try:
        res = real_run(args)
    except OofBuildError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"OOF residuals artifact: {res['oof_path']} ({res['oof_status']})")
    print(f"ridge head artifact:    {res['head_path']} ({res['head_status']})")
    sig = res["manifest"]["sigma_estimate"]
    print(f"sigma={sig['sigma']:.4f} mean_bias={sig['mean_bias']:+.4f} n={sig['n']} "
          f"window={res['manifest']['provenance']['window_start']}.."
          f"{res['manifest']['provenance']['window_end']} (OOF, research-only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
