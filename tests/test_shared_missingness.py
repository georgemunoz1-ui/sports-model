"""Run actual sport transforms on labelled inputs and verify the diagnostic/promotion boundary."""
import copy
import hashlib
import importlib
import json

import pytest

from pipelines.cards.missingness import verify_audit
from pipelines.cards.shared_missingness import (
    attach_shared_audit, binding, check_source_inputs, load_parent, training_support,
)
from scripts.generate_card_force import normalize
from test_blind_conformance import synthetic_nba_package

CUTOFF="2026-10-23T23:00:00+00:00"


@pytest.mark.parametrize("league",["nba","nhl","mls"])
def test_native_missing_history_probe_and_paired_refresh(tmp_path,monkeypatch,league):
    event,pack=synthetic_nba_package(league)
    adapter=importlib.import_module("pipelines.cards.adapters."+league)
    monkeypatch.setenv("SPORTS_INITIAL_BASELINES","1")
    def execute(name,package,previous=None):
        ctx={"package":package,"package_sha256":"synthetic","cutoff":CUTOFF}
        monkeypatch.setenv("SPORTS_RESEARCH_DRAW_OUTPUT",str(tmp_path/name))
        raw=adapter.forecast_event(event,ctx,177)
        row=normalize(event,raw)
        original=copy.deepcopy(row)
        attach_shared_audit(league,row,event,ctx,CUTOFF,previous)
        assert {k:v for k,v in row.items() if k!="missingness_audit"}==original
        assert verify_audit(row["missingness_audit"],**binding(row,league,CUTOFF))
        return row
    cold=copy.deepcopy(pack);del cold['team_state']['H']
    old=execute("cold",cold)
    new=execute("warm",pack,old)
    details=new["missingness_audit"]["details"]
    assert details["status"]=="FITTED_HEADS_REPLAYED"
    assert details["refresh"]["status"]=="PAIRED_DIAGNOSTIC"
    for v in details["linear_heads"].values():
        assert v["features"]["home_cold"]["state"]=="HISTORY_SUPPORT_INDICATOR"
    for h in details["refresh"]["heads"].values():
        assert h["missingness_indicator"]==pytest.approx(-.001)
    old_heads=old["missingness_audit"]["details"]["linear_heads"]
    assert all(head["features"]["home_rest"]["state"]=="IMPUTED_14_DAY_REST" for head in old_heads.values())
    reordered=copy.deepcopy(pack)
    reordered["team_state"]=dict(reversed(list(pack["team_state"].items())))
    reordered["source_fetches"][0]["source"]="https://example.invalid/test"
    same=execute("reordered",reordered)
    assert same["missingness_audit"]["details"]["linear_heads"]==details["linear_heads"]
    for field in ("model_input_snapshot","diagnostics","simulation","numerical_identity","grading"):
        corrupt=copy.deepcopy(new)
        corrupt[field]={"unrelated":True}
        assert not verify_audit(corrupt["missingness_audit"],**binding(corrupt,league,CUTOFF))


@pytest.mark.parametrize("pack",[
    {"consumed_game_ids":[4,"4"]},
    {"source_fetches":[{"ok":False}]},
    {"source_fetches":[{"status":503}]},
    {"source_fetches":[{"status":"TIMEOUT"}]},
    {"league":"wnba","team_state":[{"season":2026,"team":"SEA"}]*2},
])
def test_bad_captures_fail_before_any_numeric_fallback(pack):
    with pytest.raises(ValueError):
        check_source_inputs(pack)


def test_historical_support_preserves_counts_including_zero():
    support=training_support(["form","home_cold"],[(2025,[None,1]),(2025,[0,0]),(2026,[float("nan"),1])])
    assert support["by_season"]["2025"]==dict(rows=2,missing={"form":1,"home_cold":0},cold_indicators={"home_cold":1})
    assert support["by_season"]["2026"]["missing"]["form"]==1


def test_earlier_parent_requires_hash_chronology_and_a_verified_receipt(tmp_path):
    card={"league":"NBA","as_of_utc":CUTOFF,"generated_at_utc":CUTOFF,"forecasts":[{"event_id":"x","forecast_status":"BLOCKED","refusal_reason":"MISSING_PACKAGE"}]}
    f=tmp_path/"p";f.write_text(json.dumps(card));h=hashlib.sha256(f.read_bytes()).hexdigest()
    for digest,cutoff in [("f"*64,CUTOFF),(h,"2026-10-23T22:00Z")]:
        with pytest.raises(ValueError):
            load_parent(f,digest,"nba",cutoff)
    assert load_parent(f,h,"nba",CUTOFF)["x"]=={"refusal_reason":"PREVIOUS_RECEIPT_UNVERIFIED"}
