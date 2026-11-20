"""Independent extension failures must not erase or revise parent forecasts."""
import json
from types import SimpleNamespace

import pytest

from pipelines.cards import model_controls as M


def parent(tmp_path, league="NBA"):
    path = tmp_path / "card.json"
    path.write_text(json.dumps({"league": league, "forecasts": [{"model_p": .6}]}))
    return path, path.read_bytes()


def test_blocked_extension_retains_parent_and_refusal(tmp_path, monkeypatch):
    path, raw = parent(tmp_path)
    def blocked(*args):
        raise ValueError("PRE_CUTOFF_MINUTES_REQUIRED")
    monkeypatch.setattr(M.importlib, "import_module", lambda _: SimpleNamespace(shadow_from_card=blocked))
    report = M.run_extension("nba_personnel", path, tmp_path / "config", tmp_path / "extension")
    assert report["incomplete"] and report["reason"] == "PRE_CUTOFF_MINUTES_REQUIRED"
    assert not report["action_authority"] and path.read_bytes() == raw
    assert json.loads((tmp_path / "extension/extension_failure.json").read_text()) == report


def test_partial_extension_remains_incomplete(tmp_path, monkeypatch):
    path, raw = parent(tmp_path)
    def partial(*args):
        return {"run_id": "synthetic-only", "coverage": [
            {"event_id": "a", "status": "COMPLETED"},
            {"event_id": "b", "status": "BLOCKED"}]}
    monkeypatch.setattr(M.importlib, "import_module", lambda _: SimpleNamespace(shadow_from_card=partial))
    result = M.run_extension("nba_personnel", path, tmp_path / "config", tmp_path / "out")
    assert result["incomplete"] and len(result["coverage"]) == 2
    assert path.read_bytes() == raw


def test_wrong_league_refuses_before_loading_extension(tmp_path, monkeypatch):
    path, raw = parent(tmp_path, "CFB")
    def unexpected(*args):
        pytest.fail("wrong league must not execute adapter")
    monkeypatch.setattr(M.importlib, "import_module", unexpected)
    result = M.run_extension("nba_personnel", path, tmp_path / "config", tmp_path / "out")
    assert result["reason"] == "RESEARCH_EXTENSION_LEAGUE_MISMATCH"
    assert path.read_bytes() == raw


def test_existing_output_is_never_reused(tmp_path):
    path, _ = parent(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "evidence").write_text("preserved")
    with pytest.raises(FileExistsError):
        M.run_extension("nba_personnel", path, tmp_path / "config", out)
    assert (out / "evidence").read_text() == "preserved"


def test_completed_context_check_does_not_clear_missing_inputs(tmp_path, monkeypatch):
    path, raw = parent(tmp_path, "NHL")
    def complete_check(*args):
        return {"run_id": "synthetic-only", "coverage": [
            {"event_id": "a", "status": "COMPLETED", "input_eligibility": "BLOCKED"}]}
    monkeypatch.setattr(M.importlib, "import_module", lambda _: SimpleNamespace(shadow_from_card=complete_check))
    result = M.run_extension("nhl_context", path, tmp_path / "config", tmp_path / "out")
    assert result["incomplete"] and path.read_bytes() == raw


def test_parent_mutation_is_detected(tmp_path, monkeypatch):
    path, _ = parent(tmp_path)
    def mutated(*args):
        path.write_text("{}"); return {"coverage": [{"status": "COMPLETED"}]}
    monkeypatch.setattr(M.importlib, "import_module", lambda _: SimpleNamespace(shadow_from_card=mutated))
    with pytest.raises(RuntimeError, match="MUTATED_PARENT"):
        M.run_extension("nba_personnel", path, tmp_path / "config", tmp_path / "out")
