"""Hash-pinned loader for the empirically fitted NFL key-number mass artifact.

Companion to scripts/fit_nfl_key_number_mass.py. The adapter
pipelines/margins/nfl.py keeps its NFL_KEY_NUMBER_MASS placeholder; callers
that want the fitted table load it through here and pass it as the explicit
``key_number_mass`` argument to nfl_cover. The adapter file itself is not
modified.

Fail-closed governance:
  * NFL_KEY_NUMBER_MASS_MISSING        - artifact file not found.
  * NFL_KEY_NUMBER_MASS_HASH_MISMATCH  - artifact bytes do not match the
    pinned sha256 (default) or a caller-supplied expected_sha256.
  * NFL_KEY_NUMBER_MASS_SCHEMA_INVALID - unparsable, wrong schema label, not
    research_only, non-symmetric, or any boost <= -1 (mirrors
    DISCRETE_FOOTBALL_NEGATIVE_MASS in models/common/margins/distribution.py).

The pinned digest covers nfl_key_number_mass_v1.json exactly as emitted by
the fitter. A refit on new data must ship as a NEW versioned artifact with a
NEW pin — never an in-place edit (append-only).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ARTIFACT_RELATIVE_PATH = Path("data/nfl/margin_fit/nfl_key_number_mass_v1.json")
# sha256 of data/nfl/margin_fit/nfl_key_number_mass_v1.json as fitted from
# data/nfl/source/2026-09-03_nflverse_regular_games.csv
# (source sha256 7ae62f72bd671365baeb214d06a4fc26353f10efc3e406544328660a8febf388,
#  n=6967 completed games, seasons 1999-2025).
PINNED_ARTIFACT_SHA256 = "e3e9a5ebeed379612f584dee447564824058ae0de9ace59127d566650ed8c859"
EXPECTED_SCHEMA = "nfl_key_number_mass.v1"


class KeyNumberMassError(ValueError):
    """Fail-closed loader error with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__(f"{self.code}: {message}")


def default_artifact_path() -> Path:
    """Repo-root-relative default: pipelines/margins/ -> repo root."""
    return Path(__file__).resolve().parents[2] / ARTIFACT_RELATIVE_PATH


def _validate(artifact: dict) -> dict:
    if not isinstance(artifact, dict) or artifact.get("schema") != EXPECTED_SCHEMA:
        raise KeyNumberMassError(
            "NFL_KEY_NUMBER_MASS_SCHEMA_INVALID",
            f"expected schema {EXPECTED_SCHEMA!r}, got {artifact.get('schema')!r}"
            if isinstance(artifact, dict)
            else "artifact is not a JSON object",
        )
    if artifact.get("research_only") is not True:
        raise KeyNumberMassError(
            "NFL_KEY_NUMBER_MASS_SCHEMA_INVALID",
            "artifact must carry research_only=true",
        )
    mass = artifact.get("key_number_mass")
    if not isinstance(mass, dict) or not mass:
        raise KeyNumberMassError(
            "NFL_KEY_NUMBER_MASS_SCHEMA_INVALID", "key_number_mass must be a non-empty object"
        )
    out = {}
    for raw_k, raw_v in mass.items():
        try:
            k = int(raw_k)
            v = float(raw_v)
        except (TypeError, ValueError):
            raise KeyNumberMassError(
                "NFL_KEY_NUMBER_MASS_SCHEMA_INVALID",
                f"non-numeric key/boost pair {raw_k!r}: {raw_v!r}",
            ) from None
        if v <= -1.0:
            raise KeyNumberMassError(
                "NFL_KEY_NUMBER_MASS_SCHEMA_INVALID",
                f"boost at {k} is {v} <= -1 (DISCRETE_FOOTBALL_NEGATIVE_MASS territory)",
            )
        out[k] = v
    for k, v in out.items():
        if k > 0 and out.get(-k) != v:
            raise KeyNumberMassError(
                "NFL_KEY_NUMBER_MASS_SCHEMA_INVALID",
                f"boost at +{k} and -{k} must be symmetric in this artifact",
            )
    return out


def load_nfl_key_number_mass(
    path: Path | str | None = None, *, expected_sha256: str | None = PINNED_ARTIFACT_SHA256
) -> dict:
    """Load the fitted key-number mass table as {signed int margin: boost}.

    Verifies the artifact file sha256 against the pin (pass
    expected_sha256=None only for tests with synthetic fixtures).
    """
    path = Path(path) if path is not None else default_artifact_path()
    if not path.is_file():
        raise KeyNumberMassError(
            "NFL_KEY_NUMBER_MASS_MISSING", f"artifact not found: {path}"
        )
    raw = path.read_bytes()
    if expected_sha256 is not None:
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected_sha256.lower():
            raise KeyNumberMassError(
                "NFL_KEY_NUMBER_MASS_HASH_MISMATCH",
                f"{path}: sha256 {digest} != pinned {expected_sha256.lower()}; "
                "refusing to load an unverified key-number mass artifact",
            )
    try:
        artifact = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KeyNumberMassError(
            "NFL_KEY_NUMBER_MASS_SCHEMA_INVALID", f"unparsable artifact: {exc}"
        ) from None
    return _validate(artifact)


__all__ = [
    "load_nfl_key_number_mass",
    "default_artifact_path",
    "KeyNumberMassError",
    "PINNED_ARTIFACT_SHA256",
    "ARTIFACT_RELATIVE_PATH",
]
