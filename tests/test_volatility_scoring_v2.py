"""Synthetic scoring-contract regressions; no predictive qualification claims."""
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from models.common import discrete_research as D
from models.common import volatility_matrix_v1 as V
from models.common import volatility_scoring_v2 as S

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/cross_sport_volatility_research.py"


def distribution(event="event-1", *, wide=False, model_id="synthetic.true.v1"):
    h, a, p = ([8,12], [3,7], [.5,.5]) if wide else ([9,10,11], [4,5,6], [.25,.5,.25])
    return V.make_joint(h, a, p, league="mls", settlement="REGULATION_90_STOPPAGE",
        model_id=model_id, provenance={"event_id": event, "parent_forecast_sha256": "a"*64,
            "cutoff": "2026-01-01T00:00:00Z", "start_time_utc": "2026-01-01T03:00:00Z"})


RESULT = {"actual_home": 10, "actual_away": 5, "result_source_sha256": "b"*64,
          "result_available_at": "2026-01-01T05:00:00Z"}


def reseal(record):
    record.pop("artifact_sha256", None)
    record["artifact_sha256"] = D.digest(record)
    return record


def test_proper_score_counterexample_prefers_truth_and_preserves_legacy_result():
    truth, wrong = distribution(), distribution(wide=True)
    def expectation(fn, forecast):
        return sum(p * fn(forecast, h, a)["energy_score"]
                   for p,h,a in zip(truth["masses"], truth["home_scores"], truth["away_scores"]))
    assert expectation(V.energy_score, truth) == pytest.approx(.75)
    assert expectation(V.energy_score, wrong) == pytest.approx(2**-.5)
    assert expectation(S.energy_score, truth) == pytest.approx(.375 * 2**.5)
    assert expectation(S.energy_score, wrong) == pytest.approx(2**.5)
    assert expectation(S.energy_score, truth) < expectation(S.energy_score, wrong)


def test_unit_scale_shared_across_forecasts_and_sd_cannot_change_it(monkeypatch):
    truth, wrong = distribution(), distribution(wide=True)
    assert V.moments(truth)["home_score_sd"] != V.moments(wrong)["home_score_sd"]
    expected = S.energy_score(truth, 10, 5)
    # energy_score must not consult predictive moments to choose scale.
    monkeypatch.setattr(V, "moments", lambda _: (_ for _ in ()).throw(AssertionError("SD consulted")))
    observed = S.energy_score(truth, 10, 5)
    assert observed == expected
    assert observed["metric"] == S.energy_score(wrong, 10, 5)["metric"]
    assert observed["metric"]["component_scale"] == [1.0, 1.0]
    assert observed["metric"]["coordinate_order"] == ["home_score", "away_score"]
    contract = S.metric_contract()
    assert contract["scale_source_sha256"] == D.digest(contract["scale_source"])
    digest = contract.pop("metric_contract_sha256")
    assert D.digest(contract) == digest


def test_energy_matches_independent_double_sum():
    d = distribution()
    pairs = list(zip(d["home_scores"], d["away_scores"]))
    first = sum(p * np.hypot(h-12, a-8) for (h,a),p in zip(pairs,d["masses"]))
    second = sum(p*q*np.hypot(x[0]-y[0],x[1]-y[1])
                 for x,p in zip(pairs,d["masses"]) for y,q in zip(pairs,d["masses"]))
    assert S.energy_score(d, 12, 8)["energy_score"] == pytest.approx(first - .5*second)


def test_successor_record_and_aggregation_have_explicit_identity():
    records = [S.account_result(distribution(event), **RESULT) for event in ("one", "two")]
    result = S.evaluate(records, evaluated_at="2030-01-01T00:00:00Z")
    assert result["schema"] == S.EVALUATION_SCHEMA
    assert result["n"] == 2 and result["event_ids"] == ["one", "two"]
    assert result["metric"]["metric_id"] == S.METRIC_ID
    assert not result["legacy_values_included"]
    assert not result["action_authority"] and not result["predictive_validation_granted"]


@pytest.mark.parametrize("case", ["legacy", "metric", "scale", "coordinate_order", "source", "scorer", "scope", "duplicate"])
def test_aggregate_refuses_legacy_or_mixed_comparisons(case):
    records = [S.account_result(distribution(event), **RESULT) for event in ("one", "two")]
    if case == "legacy":
        records[1] = V.account_result(distribution("two"), **RESULT)
    elif case == "scope":
        records[1]["settlement"] = "REGULATION"
    elif case == "duplicate":
        records[1]["event_id"] = "one"
    elif case == "scorer":
        records[1]["joint_energy_score"]["scoring_code_sha256"] = "c"*64
    else:
        contract = records[1]["joint_energy_score"]["metric"]
        key, value = {"metric": ("metric_id", "legacy-normalized-v1"),
                      "scale": ("component_scale", [2.,2.]),
                      "coordinate_order": ("coordinate_order", ["away_score", "home_score"]),
                      "source": ("scale_source_sha256", "c"*64)}[case]
        contract[key] = value
    reseal(records[1])
    with pytest.raises(ValueError):
        S.evaluate(records, evaluated_at="2030-01-01T00:00:00Z")


def test_rescoring_is_separate_parent_bound_and_does_not_change_old_bytes(tmp_path):
    d = distribution()
    old = V.account_result(d, **RESULT)
    raw = json.dumps(old, sort_keys=True).encode()
    path = tmp_path / "original.json"
    path.write_bytes(raw)
    before = copy.deepcopy(d)
    successor = S.rescore_legacy(d, old)
    assert path.read_bytes() == raw and json.dumps(old, sort_keys=True).encode() == raw
    assert d == before
    assert successor["schema"] == S.RECORD_SCHEMA
    assert successor["derived_rescoring"]
    assert successor["rescoring_parent"]["artifact_sha256"] == old["artifact_sha256"]
    assert not successor["independent_event_evidence_added"]
    assert successor["joint_energy_score"] != old["joint_energy_score"]
    with pytest.raises(ValueError, match="PARENT_BINDING"):
        S.rescore_legacy(distribution("wrong-event"), old)
    tampered = copy.deepcopy(old)
    tampered["actual_home"] += 1
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        S.rescore_legacy(d, tampered)


def test_cli_defaults_to_v2_and_legacy_rescore_is_explicit(tmp_path):
    dist = tmp_path / "distribution.json"
    inputs = tmp_path / "result.json"
    dist.write_text(json.dumps(distribution()))
    inputs.write_text(json.dumps(RESULT))
    old_path, new_path, rescored = (tmp_path / p for p in ("old.json", "new.json", "rescored.json"))
    def run(*args):
        return subprocess.run([sys.executable,str(CLI),*map(str,args)], cwd=ROOT,
                              text=True,capture_output=True)
    assert run("grade-legacy-v1","--distribution",dist,"--input",inputs,"--output",old_path).returncode == 0
    assert run("grade","--distribution",dist,"--input",inputs,"--output",new_path).returncode == 0
    old_bytes = old_path.read_bytes()
    assert json.loads(new_path.read_text())["schema"] == S.RECORD_SCHEMA
    assert run("rescore-v2","--distribution",dist,"--legacy-record",old_path,"--output",rescored).returncode == 0
    assert old_path.read_bytes() == old_bytes
    assert json.loads(rescored.read_text())["derived_rescoring"]
    assert run("rescore-v2","--distribution",dist,"--legacy-record",old_path,"--output",rescored).returncode != 0
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"records":[str(old_path),str(new_path)],"evaluated_at":"2030-01-01T00:00:00Z"}))
    evaluation = tmp_path / "evaluation.json"
    refusal = run("evaluate","--input",plan,"--output",evaluation)
    assert refusal.returncode != 0 and "EXPLICIT_RESCORE" in refusal.stderr
    assert not evaluation.exists()


def test_historical_numerical_source_and_all_six_fit_bytes_unchanged():
    expected = {
        "models/common/volatility_matrix_v1.py":"86efa96c72b282ff80008f638a5df8cfb7e195a8d80ce54182ad566ae655aaeb",
        "data/research/volatility_matrix_replay_20261103/mls/empirical.json":"5755966de6bbb7bc5015a948a63b2683849a96ff7b9c2a5172e260190b38b8a0",
        "data/research/volatility_matrix_replay_20261103/mls/ledoit_wolf.json":"d8f2f1089a476da235fcc48100d982aef63fea221bc7282e4eca99a4c381590c",
        "data/research/volatility_matrix_replay_20261103/nba/empirical.json":"74f8a6ef36ba35c0ce8dd1d1420e696c9fc0a34d333850a2c237b5af4ddedae2",
        "data/research/volatility_matrix_replay_20261103/nba/ledoit_wolf.json":"666dcb017377b35ee0ae0f4c9f7aeab3a54b1c8cd7d7a0447f0f7f6bd6529326",
        "data/research/volatility_matrix_replay_20261103/nhl/empirical.json":"7cc668259d61681028e7c215168da609f210928afe61eb270873f73d1db85c26",
        "data/research/volatility_matrix_replay_20261103/nhl/ledoit_wolf.json":"403f56fadd525c94f76aa713a4ccac443330f94841f60bf57ddf534b413e4cb7",
    }
    for relative, sha in expected.items():
        raw = (ROOT / relative).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == sha
        if relative.endswith(".json"):
            V._validate_fit(json.loads(raw))
