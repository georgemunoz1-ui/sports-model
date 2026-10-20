"""Test wiring: repo root + scripts/ on sys.path; margin layer fallback.

- repo root is inserted so models.common.margins / pipelines.margins import
  from the checkout (present on the margin-distribution-system branch and on
  main after merge).
- scripts/ is inserted so the fitting builders import without packaging.
- If the in-repo margin layer is absent (e.g., pre-merge main), fall back to
  MARGIN_SYSTEM_PATH (default /mnt/agents/output/margin-system).
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)

for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import models.common.margins.sigma  # noqa: F401
except ImportError:
    _MS = os.environ.get("MARGIN_SYSTEM_PATH", "/mnt/agents/output/margin-system")
    if os.path.isdir(_MS) and _MS not in sys.path:
        sys.path.insert(0, _MS)
