"""Execute workflow shell blocks with fake processes, never model data or network."""
import os
from pathlib import Path
import re
import subprocess
import textwrap

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/standing-health-triage.yml"


def step(name):
    # Read the named top-level step without adding a YAML runtime dependency.
    text = WORKFLOW.read_text().split("      - name: " + name + "\n", 1)[1]
    return re.split(r"\n      - ", text, maxsplit=1)[0]


def shell(name):
    return textwrap.dedent(step(name).split("        run: |\n", 1)[1])


def execute(name, env):
    return subprocess.run(["bash", "-e", "-o", "pipefail", "-c", shell(name)],
                          env=dict(os.environ, **env), capture_output=True, text=True)


def evidence(tmp_path):
    target = tmp_path / "health-triage"
    target.mkdir()
    for name in ("triage", "health"):
        (target / f"{name}-exit-code.txt").write_text("0\n")
    gate = step("Enforce all results after evidence upload")
    phases = re.findall(r"^          ([A-Z_]+): \$\{\{ steps\.", gate, re.M)
    assert len(phases) == 12
    return target, dict(RUNNER_TEMP=str(tmp_path), **{p: "success" for p in phases})


def test_failed_triage_is_captured_before_independent_evidence(tmp_path):
    target, env = evidence(tmp_path)
    fake = tmp_path / "bin"
    fake.mkdir()
    python = fake / "python"
    python.write_text('#!/bin/sh\nprintf \'{"validation_errors":["overdue"]}\\n\'\nexit 1\n')
    python.chmod(0o755)
    env["PATH"] = str(fake) + os.pathsep + os.environ["PATH"]
    result = execute("Capture triage without skipping independent evidence", env)
    assert result.returncode == 0, result.stderr
    assert (target / "triage-exit-code.txt").read_text() == "1\n"
    assert '"overdue"' in (target / "triage.json").read_text()
    # Recovery and environment capture must run after a preceding failure too.
    for name in ("Recovery refusal checks", "Capture execution environment",
                 "Recover explicitly named candidate snapshot", "Verify restored bytes and parser schema"):
        assert "if: always()" in step(name)
    assert execute("Enforce all results after evidence upload", env).returncode == 1


@pytest.mark.parametrize("name,value", [
    ("triage", "1\n"), ("health", "1\n"), ("triage", "2\n"),
    ("health", ""), ("triage", None), ("health", None),
])
def test_final_gate_rejects_nonzero_or_missing_exit_evidence(tmp_path, name, value):
    target, env = evidence(tmp_path)
    path = target / f"{name}-exit-code.txt"
    if value is None:
        path.unlink()
    else:
        path.write_text(value)
    assert execute("Enforce all results after evidence upload", env).returncode == 1


@pytest.mark.parametrize("outcome", ["failure", "skipped", "cancelled", ""])
def test_final_gate_rejects_every_unsuccessful_phase(tmp_path, outcome):
    _, env = evidence(tmp_path)
    for phase in env.keys() - {"RUNNER_TEMP"}:
        assert execute("Enforce all results after evidence upload",
                       dict(env, **{phase: outcome})).returncode == 1, phase


def test_final_gate_all_success_and_evidence_upload_precedes_enforcement(tmp_path):
    _, env = evidence(tmp_path)
    assert execute("Enforce all results after evidence upload", env).returncode == 0
    text = WORKFLOW.read_text()
    assert text.index("name: pinned-pitch-recovery-candidate") < text.index("name: Enforce all results")
    assert "if: always()" in step("Enforce all results after evidence upload")
    assert "continue-on-error" not in text
