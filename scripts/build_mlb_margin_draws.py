#!/usr/bin/env python3
"""Build MLB qualifying-OOF margin draw artifacts by replaying the V13.1
Gamma-Poisson Monte Carlo harness with per-game draw retention.

Research-only. action_authority=False. No market data is read: the harness
market loader (results.csv, contaminated close_ml_* columns) is stubbed to {}
before any harness code executes.

Fail-closed SCREAMING_SNAKE error codes via OofBuildError.code.
Artifacts are hash-pinned, append-only, and wall-clock-free (deterministic
npz writer; manifest carries content hashes only).

Engine: mlb.v13_1.gamma_poisson_monte_carlo.v1 / 1.0.2
Per-game seed: seed_base (default 722) + int(gamePk)  (order-invariant)
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import io
import json
import os
import sys
import zipfile
import contextlib
from datetime import date

import numpy as np

ENGINE_ID = "mlb.v13_1.gamma_poisson_monte_carlo.v1"
ENGINE_VERSION = "1.0.2"
DEFAULT_SEED = 722
DEFAULT_SIMS = 30000
MIN_DRAWS = 10000
FIXED_ZIP_DATETIME = (2026, 1, 1, 0, 0, 0)
RESEARCH_LABELS = {
    "research_only": True,
    "action_authority": False,
    "action_status": "SHADOW_ONLY",
    "market_data": "DISABLED_NO_MARKET_DATA",
}


class OofBuildError(Exception):
    """Fail-closed build error with a SCREAMING_SNAKE code."""

    def __init__(self, code: str, message: str, details=None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Deterministic npz writer (no wall-clock timestamps; sorted keys)
# ---------------------------------------------------------------------------

def npz_bytes_deterministic(arrays: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(arrays):
            arr = np.ascontiguousarray(arrays[name])
            ib = io.BytesIO()
            np.save(ib, arr, allow_pickle=False)
            zi = zipfile.ZipInfo(name + ".npy", date_time=FIXED_ZIP_DATETIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o600 << 16
            zf.writestr(zi, ib.getvalue())
    return buf.getvalue()


def append_only_write(path: str, data: bytes) -> str:
    """Append-only artifact write. Identical rewrite = no-op; differing
    rewrite of an existing artifact is an immutability violation."""
    if os.path.exists(path):
        existing = open(path, "rb").read()
        if existing == data:
            return "noop_identical"
        raise OofBuildError(
            "ARTIFACT_IMMUTABLE",
            f"refusing to overwrite differing artifact: {path}",
            {"path": path},
        )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return "written"


# ---------------------------------------------------------------------------
# Harness import + capture
# ---------------------------------------------------------------------------

def _assert_ast_complete(path: str):
    src = open(path, "r", encoding="utf-8").read()
    tree = ast.parse(src, filename=path)  # raises SyntaxError if truncated
    fns = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    for required in ("run", "v13_sim", "load_rows", "load_candidate_beta",
                     "load_market_by_gamepk"):
        if required not in fns:
            raise OofBuildError(
                "HARNESS_IMPORT_FAILED",
                f"harness missing required function {required}",
                {"path": path, "functions": fns},
            )


def import_harness(harness_path: str):
    if not os.path.exists(harness_path):
        raise OofBuildError(
            "HARNESS_IMPORT_FAILED", "harness file not found",
            {"path": harness_path})
    _assert_ast_complete(harness_path)
    sb = os.path.dirname(os.path.dirname(os.path.abspath(harness_path)))
    cwd0 = os.getcwd()
    spec = importlib.util.spec_from_file_location(
        "run_v13_historical", harness_path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # harness chdirs to its base on import
    except Exception as e:  # fail closed
        raise OofBuildError(
            "HARNESS_IMPORT_FAILED", f"harness import raised: {e!r}",
            {"path": harness_path}) from e
    finally:
        os.chdir(cwd0)
    # Absolutize the harness module-relative path globals so behavior does
    # not depend on the caller's cwd.
    mod.FEATURES = os.path.join(sb, "data/backfill/mlb/2026/features.csv")
    mod.CAND_CFG = os.path.join(sb, "data/mlb/ml_asof/p3_candidate_config.json")
    for attr in [k for k in vars(mod) if "PARK" in k.upper()]:
        setattr(mod, attr,
                os.path.join(sb, "data/backfill/mlb/2026/park_factors.json"))
    # NO MARKET DATA: stub the results.csv loader before any harness call.
    mod.load_market_by_gamepk = lambda: {}
    if not os.path.exists(mod.FEATURES):
        raise OofBuildError(
            "FEATURES_MISSING", "features.csv not found",
            {"path": mod.FEATURES})
    return mod, sb


def make_capture_hook(cap: dict):
    def hook(frame, event, arg):
        if event == "return" and frame.f_code.co_name == "v13_sim":
            L = frame.f_locals
            cap[int(L["seed"])] = (L["ra"].copy(), L["rh"].copy())
    return hook


# ---------------------------------------------------------------------------
# Actuals join (features.csv total/margin only; never close_ml_*)
# ---------------------------------------------------------------------------

def _pick(row: dict, *keys):
    for k in keys:
        v = row.get(k)
        if v is not None and v != "":
            return v
    return None


def derive_actuals(row: dict) -> dict:
    """Join actuals from harness feature rows (features.csv total/margin;
    NEVER results.csv close_ml_* columns). Harness load_rows() names them
    actual_total/actual_margin; raw CSV-shaped dicts use total/margin."""
    game_pk = str(row.get("gamePk"))
    total = _pick(row, "actual_total", "total")
    margin = _pick(row, "actual_margin", "margin")
    if total is None or margin is None:
        raise OofBuildError(
            "ACTUALS_MISSING", "missing total/margin for game",
            {"gamePk": game_pk})
    total = float(total)
    margin = float(margin)
    if abs((total + margin) % 2.0) > 1e-9:
        raise OofBuildError(
            "ACTUALS_PARITY_MISMATCH",
            "total+margin not even; cannot split runs",
            {"gamePk": game_pk, "total": total, "margin": margin})
    home = int(round((total + margin) / 2.0))
    away = int(round((total - margin) / 2.0))
    hw_raw = _pick(row, "home_win")
    if hw_raw is None:
        raise OofBuildError(
            "ACTUALS_MISSING", "missing home_win for game",
            {"gamePk": game_pk})
    home_win = int(float(hw_raw))
    if home_win != int(margin > 0):
        raise OofBuildError(
            "ACTUALS_SIGN_MISMATCH",
            "home_win disagrees with sign(margin)",
            {"gamePk": game_pk, "home_win": home_win, "margin": margin})
    return {"home_runs": home, "away_runs": away, "home_win": home_win,
            "total": int(round(total)), "margin": int(round(margin))}


# ---------------------------------------------------------------------------
# Draw validation
# ---------------------------------------------------------------------------

def validate_draws(ra, rh, expected_seed, game_pk, min_draws=MIN_DRAWS):
    for name, arr in (("away", ra), ("home", rh)):
        if not np.issubdtype(arr.dtype, np.integer):
            raise OofBuildError(
                "DRAWS_NOT_INTEGER", f"{name} draws not integer dtype",
                {"gamePk": game_pk, "dtype": str(arr.dtype)})
        if arr.shape[0] < min_draws:
            raise OofBuildError(
                "DRAWS_BELOW_FLOOR",
                f"{name} draws below floor {min_draws}",
                {"gamePk": game_pk, "n": int(arr.shape[0])})
    if ra.shape != rh.shape:
        raise OofBuildError(
            "DRAWS_CAPTURE_MISSING", "away/home draw length mismatch",
            {"gamePk": game_pk})
    # Seed correctness is enforced by the caller: draws are captured keyed by
    # per-game seed (seed_base + int(gamePk)) and looked up by that key.
    return True


# ---------------------------------------------------------------------------
# Replay with draw retention
# ---------------------------------------------------------------------------

def run_replay(mod, sims: int, seed_base: int, max_games, out_path: str):
    """Replay the harness exactly (same run() code path), capturing per-game
    (ra, rh) integer arrays keyed by per-game seed."""
    all_rows = mod.load_rows()
    if max_games:
        orig = mod.load_rows
        mod.load_rows = lambda: orig()[:max_games]
    cap = {}
    hook = make_capture_hook(cap)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sys.setprofile(hook)
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.run(sims, seed_base, out_path)
    finally:
        sys.setprofile(None)
        if max_games:
            mod.load_rows = orig
    rows = all_rows[:max_games] if max_games else all_rows
    return rows, cap, buf.getvalue()


def build_game_records(rows, cap, seed_base, sims, min_draws=MIN_DRAWS):
    games = []
    seen = set()
    for r in rows:
        game_pk = int(r["gamePk"])
        if game_pk in seen:
            raise OofBuildError(
                "DUPLICATE_GAME", "duplicate gamePk in features",
                {"gamePk": game_pk})
        seen.add(game_pk)
        expected_seed = seed_base + game_pk
        if expected_seed not in cap:
            raise OofBuildError(
                "DRAWS_CAPTURE_MISSING", "no captured draws for game seed",
                {"gamePk": game_pk, "expected_seed": expected_seed})
        ra, rh = cap[expected_seed]
        validate_draws(ra, rh, expected_seed, game_pk, min_draws)
        actuals = derive_actuals(r)
        f = r.get("f") or {}
        sp_matched = ((f.get("away_sp") or {}).get("era") is not None
                      and (f.get("home_sp") or {}).get("era") is not None)
        pred_margin = rh.astype(np.float64) - ra.astype(np.float64)
        games.append({
            "gamePk": game_pk,
            "date": r.get("date"),
            "away_team": r.get("away"),
            "home_team": r.get("home"),
            "seed": expected_seed,
            "n_sims": int(ra.shape[0]),
            "sims_requested": sims,
            "sp_matched": bool(sp_matched),
            "ra": ra.astype(np.int16),
            "rh": rh.astype(np.int16),
            "actual": actuals,
            "pred_margin_mean": float(pred_margin.mean()),
            "pred_total_mean": float((ra.astype(np.float64)
                                      + rh.astype(np.float64)).mean()),
        })
    return games


# ---------------------------------------------------------------------------
# Artifact emission
# ---------------------------------------------------------------------------

def game_npz_bytes(game: dict) -> bytes:
    return npz_bytes_deterministic({"away": game["ra"], "home": game["rh"]})


def write_game_artifacts(games, out_dir):
    """Write per-game npz artifacts append-only. Returns (files, statuses):
    `files` is content-only (manifest-safe, run-invariant); `statuses` is the
    volatile per-run write outcome (never embedded in the manifest)."""
    files = []
    statuses = []
    for g in games:
        path = os.path.join(out_dir, f"{g['gamePk']}.npz")
        data = game_npz_bytes(g)
        status = append_only_write(path, data)
        statuses.append({"file": os.path.basename(path), "status": status})
        files.append({
            "file": os.path.basename(path),
            "gamePk": g["gamePk"],
            "sha256": sha256_bytes(data),
            "bytes": len(data),
            "n_sims": g["n_sims"],
            "seed": g["seed"],
        })
    return files, statuses


def iso_week(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def summarize(games):
    pred = np.array([g["pred_margin_mean"] for g in games])
    act = np.array([float(g["actual"]["margin"]) for g in games])
    resid = act - pred
    weekly = {}
    for g, r in zip(games, resid):
        wk = iso_week(g["date"])
        b = weekly.setdefault(wk, {"n": 0, "resid": []})
        b["n"] += 1
        b["resid"].append(float(r))
    weekly_out = {wk: {"n": b["n"],
                       "mae": float(np.mean(np.abs(b["resid"]))),
                       "rmse": float(np.sqrt(np.mean(np.square(b["resid"])))),
                       "bias": float(np.mean(b["resid"]))}
                  for wk, b in sorted(weekly.items())}
    return {
        "n_games": len(games),
        "residual": {
            "mae": float(np.mean(np.abs(resid))),
            "rmse": float(np.sqrt(np.mean(resid ** 2))),
            "bias": float(resid.mean()),
            "std": float(resid.std(ddof=1)) if len(resid) > 1 else None,
        },
        "weekly": weekly_out,
    }


def estimate_oof_sigma(games, margin_layer_path, window):
    """Overall OOF margin sigma via models.common.margins.sigma.estimate_sigma.
    On small subsets (SIGMA_MIN_SUPPORT), record sigma=null with flag."""
    if margin_layer_path not in sys.path:
        sys.path.insert(0, margin_layer_path)
    try:
        from models.common.margins.sigma import estimate_sigma
    except Exception as e:
        raise OofBuildError(
            "MARGIN_LAYER_IMPORT_FAILED",
            f"could not import margin sigma layer: {e!r}",
            {"margin_layer_path": margin_layer_path}) from e
    pred = np.array([g["pred_margin_mean"] for g in games])
    act = np.array([float(g["actual"]["margin"]) for g in games])
    prov = {"sport": "mlb", "oof": True,
            "window_start": window["start"], "window_end": window["end"]}
    try:
        res = estimate_sigma(pred, act, group_by=None, min_n=200,
                             label_in_sample=False, provenance=prov)
    except Exception as e:
        code = getattr(e, "code", "") or str(e) or e.__class__.__name__
        if "SIGMA_MIN_SUPPORT" in str(code):
            return {"sigma": None, "status": "SIGMA_MIN_SUPPORT",
                    "n": int(len(games))}
        raise
    if not isinstance(res, dict) or "sigma" not in res:
        raise OofBuildError(
            "MARGIN_LAYER_IMPORT_FAILED",
            "estimate_sigma returned unexpected shape",
            {"returned_type": type(res).__name__})
    return {"sigma": float(res["sigma"]), "mean_bias": res.get("mean_bias"),
            "n": res.get("n"), "min_n": res.get("min_n"),
            "sport": res.get("sport"), "status": "ok"}


# ---------------------------------------------------------------------------
# Selftest: deterministic redraws must be byte-identical
# ---------------------------------------------------------------------------

def run_selftest(mod, seed_base, sims=10000, n_games=3):
    rows = mod.load_rows()[:n_games]
    orig = mod.load_rows
    mod.load_rows = lambda: rows
    try:
        draws = []
        for _ in range(2):
            cap = {}
            hook = make_capture_hook(cap)
            sys.setprofile(hook)
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.run(sims, seed_base,
                            os.devnull if os.name != "nt" else "NUL")
            finally:
                sys.setprofile(None)
            draws.append(cap)
    finally:
        mod.load_rows = orig
    checked = []
    for r in rows:
        s = seed_base + int(r["gamePk"])
        a = np.concatenate([draws[0][s][0], draws[0][s][1]])
        b = np.concatenate([draws[1][s][0], draws[1][s][1]])
        if not np.array_equal(a, b):
            raise OofBuildError(
                "SELFTEST_MISMATCH", "redraw not deterministic",
                {"gamePk": int(r["gamePk"]), "seed": s})
        b0 = npz_bytes_deterministic({"away": draws[0][s][0].astype(np.int16),
                                      "home": draws[0][s][1].astype(np.int16)})
        b1 = npz_bytes_deterministic({"away": draws[1][s][0].astype(np.int16),
                                      "home": draws[1][s][1].astype(np.int16)})
        if b0 != b1:
            raise OofBuildError(
                "SELFTEST_MISMATCH", "npz bytes not deterministic",
                {"gamePk": int(r["gamePk"])})
        checked.append(int(r["gamePk"]))
    return {"status": "PASS", "games_checked": checked, "sims": sims}


# ---------------------------------------------------------------------------
# Manifest + provenance
# ---------------------------------------------------------------------------

def build_manifest(games, files, seed_base, sims, features_sha, config_sha,
                   harness_sha, sigma_info, summary, subset_label=None):
    dates = sorted(g["date"] for g in games)
    window = {"start": dates[0], "end": dates[-1]}
    manifest = {
        "artifact": "mlb_margin_draws_v1",
        "sport": "mlb",
        "engine": {"source_id": ENGINE_ID, "version": ENGINE_VERSION,
                   "run_key": f"oof-{window['start']}-{window['end']}"
                              f"-sims{sims}-seed{seed_base}"},
        "provenance": {
            "sport": "mlb",
            "oof": True,
            "window_start": window["start"],
            "window_end": window["end"],
            "seed_base": seed_base,
            "seed_rule": "seed_base + int(gamePk)",
            "sims_per_game": sims,
            "min_draws_floor": MIN_DRAWS,
            "features_file": {
                "path": "data/backfill/mlb/2026/features.csv",
                "sha256": features_sha},
            "config_file": {
                "path": "data/mlb/ml_asof/p3_candidate_config.json",
                "sha256": config_sha},
            "harness": {"path": "harness/run_v13_historical.py",
                        "sha256": harness_sha},
            "actuals_source": "features.csv total/margin (never close_ml_*)",
            "actuals_derivation": "home=(total+margin)/2, away=(total-margin)/2;"
                                  " sign validated vs home_win",
            **RESEARCH_LABELS,
        },
        "n_games": len(games),
        "games": [{
            "gamePk": g["gamePk"], "date": g["date"],
            "away_team": g["away_team"], "home_team": g["home_team"],
            "seed": g["seed"], "n_sims": g["n_sims"],
            "sp_matched": g["sp_matched"],
            "pred_margin_mean": round(g["pred_margin_mean"], 6),
            "pred_total_mean": round(g["pred_total_mean"], 6),
            "actual_margin": g["actual"]["margin"],
            "actual_total": g["actual"]["total"],
            "residual": round(g["actual"]["margin"]
                              - g["pred_margin_mean"], 6),
        } for g in games],
        "files": files,
        "summary": summary,
        "oof_sigma": sigma_info,
    }
    if subset_label:
        manifest["subset_label"] = subset_label
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sims-per-game", type=int, default=DEFAULT_SIMS)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--max-games", type=int, default=None)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--harness-path",
                   default="harness/run_v13_historical.py")
    p.add_argument("--margin-layer-path",
                   default=".")
    p.add_argument("--out-dir",
                   default="data/mlb/margin_draws_v1")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.sims_per_game < MIN_DRAWS:
        raise OofBuildError(
            "DRAWS_BELOW_FLOOR",
            f"--sims-per-game {args.sims_per_game} below floor {MIN_DRAWS}")
    mod, sb = import_harness(args.harness_path)

    features_sha = sha256_file(mod.FEATURES)
    config_sha = sha256_file(mod.CAND_CFG)
    if not config_sha.startswith("eede422d"):
        raise OofBuildError(
            "CONFIG_HASH_DRIFT", "candidate config sha256 drifted from pin",
            {"expected_prefix": "eede422d", "actual": config_sha})
    harness_sha = sha256_file(args.harness_path)

    if args.selftest:
        res = run_selftest(mod, args.seed)
        print(canonical_json({"selftest": res}))
        return 0

    # Harness replay stdout JSONL contains wall-clock `built_utc` stamps, so
    # it is a DIAGNOSTIC and must live in scratch, never in the artifact dir.
    replay_jsonl = os.path.join(sb, "mlb_margin_draws_v1_replay_stdout.jsonl")
    rows, cap, harness_stdout = run_replay(
        mod, args.sims_per_game, args.seed, args.max_games, replay_jsonl)
    games = build_game_records(rows, cap, args.seed, args.sims_per_game)
    files, statuses = write_game_artifacts(games, args.out_dir)
    n_written = sum(1 for s in statuses if s["status"] == "written")
    n_noop = sum(1 for s in statuses if s["status"] == "noop_identical")
    summary = summarize(games)
    dates = sorted(g["date"] for g in games)
    window = {"start": dates[0], "end": dates[-1]}
    sigma_info = estimate_oof_sigma(games, args.margin_layer_path, window)
    subset_label = None
    full = len(mod.load_rows())
    if len(games) < full:
        subset_label = "SUBSET_VERIFICATION_NOT_FULL_REPLAY"
    manifest = build_manifest(games, files, args.seed, args.sims_per_game,
                              features_sha, config_sha, harness_sha,
                              sigma_info, summary, subset_label)
    mbytes = (canonical_json(manifest) + "\n").encode()
    append_only_write(os.path.join(args.out_dir, "manifest.json"), mbytes)
    print(canonical_json({
        "status": "ok",
        "n_games": len(games),
        "sims_per_game": args.sims_per_game,
        "files_written": n_written,
        "files_noop_identical": n_noop,
        "subset_label": subset_label,
        "window": window,
        "oof_sigma": sigma_info,
        "summary_residual": summary["residual"],
        "out_dir": args.out_dir,
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OofBuildError as e:
        print(canonical_json({"error": e.code, "message": e.message,
                              "details": e.details}), file=sys.stderr)
        sys.exit(2)
