"""Independent adversarial checks; all fixtures are synthetic TEST_ONLY evidence."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from research.efficiency import integrity as I
from research.validation_registry import content_id


@pytest.fixture
def receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_now", lambda: datetime(2030, 1, 1, 12, tzinfo=timezone.utc))
    source = tmp_path / "synthetic-source.json"
    source.write_text('{"TEST_ONLY":true,"pace":100}')
    import hashlib
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return I.build_component_receipt(
        model_id="TEST_ONLY.nba.efficiency.v1", stage_id="efficiency",
        event_id="TEST_ONLY:event", cutoff_utc="2030-01-01T11:59:00Z",
        start_utc="2030-01-01T13:00:00Z", inputs={"pace":100.0},
        state={"TEST_ONLY":True,"coefficient":1.0}, config={"alpha":1.0},
        code_files=[Path(I.__file__)],
        sources=[{"source":"TEST_ONLY", "sha256":digest, "path":str(source),
                  "retrieved_at_utc":"2030-01-01T11:58:00Z"}],
        components={"pace":{"value":100.0,"unit":"possessions", "input_paths":["pace"]}},
        forecast={"p_home":0.6,"home_margin":3.0,"total":200.0}, mode="SHADOW",
        history_max_event_time_utc="2029-12-30T00:00:00Z")


def reseal(value):
    value=deepcopy(value)
    value["receipt_sha256"]=content_id({k:v for k,v in value.items() if k!="receipt_sha256"})
    return value


@pytest.mark.parametrize("field,value",[
    ("history_max_event_time_utc","2030-01-01T12:30:00Z"),
    ("input_max_available_at_utc","2030-01-01T12:30:00Z"),
    ("cutoff_utc","2030-01-01T12:30:00Z"),
    ("inference_trace_sha256","a"*64),
    ("canonical_prospective_eligible",True),
    ("external_timestamp_verified",True),
])
def test_resealed_receipt_does_not_authorize_invalid_semantics(receipt,tmp_path,field,value):
    receipt[field]=value
    with pytest.raises((I.IntegrityError,ValueError)):
        I.write_shadow_receipt(reseal(receipt),tmp_path/"shadow")
    assert not list((tmp_path/"shadow").glob("registrations/*.json"))


@pytest.mark.parametrize("field,value",[
    ("max_available_at_utc","2030-01-01T12:30:00Z"),
    ("source_sha256",["a"*64]),
    ("input_paths",["missing.path"]),
    ("input_snapshot_sha256","a"*64),
    ("fitted_state_sha256","a"*64),
    ("value",True),
])
def test_resealed_component_cannot_bypass_inference_binding(receipt,tmp_path,field,value):
    receipt["components"]["pace"][field]=value
    with pytest.raises((I.IntegrityError,ValueError)):
        I.write_shadow_receipt(reseal(receipt),tmp_path/"shadow")
    assert not list((tmp_path/"shadow").glob("registrations/*.json"))


def test_changed_raw_source_rejected_before_registration(receipt,tmp_path):
    Path(receipt["sources"][0]["path"]).write_text('{"TEST_ONLY":true,"pace":101}')
    with pytest.raises(I.IntegrityError,match="SOURCE_BYTES_HASH_MISMATCH"):
        I.write_shadow_receipt(receipt,tmp_path/"shadow")
    assert not list((tmp_path/"shadow").glob("registrations/*.json"))


def test_registration_rechecks_actual_clock(receipt,tmp_path,monkeypatch):
    monkeypatch.setattr(I,"_now",lambda:datetime(2030,1,1,13,tzinfo=timezone.utc))
    with pytest.raises(I.IntegrityError):
        I.write_shadow_receipt(receipt,tmp_path/"shadow")
    assert not list((tmp_path/"shadow").glob("registrations/*.json"))


def test_second_shadow_write_keeps_original_bytes(receipt,tmp_path):
    root=tmp_path/"shadow"
    reg=I.write_shadow_receipt(receipt,root)
    before={str(p):p.read_bytes() for p in root.rglob("*.json")}
    with pytest.raises(I.IntegrityError,match="SHADOW_ALREADY_REGISTERED"):
        I.write_shadow_receipt(receipt,root)
    assert {str(p):p.read_bytes() for p in root.rglob("*.json")}==before
    assert reg["canonical_prospective_eligible"] is False
    assert reg["external_timestamp_verified"] is False


@pytest.mark.parametrize("directory",["registrations","components"])
def test_shadow_descendant_symlink_cannot_redirect_writes(receipt,tmp_path,directory):
    root=tmp_path/"shadow"; root.mkdir()
    outside=tmp_path/"outside";outside.mkdir()
    (root/directory).symlink_to(outside,target_is_directory=True)
    with pytest.raises((I.IntegrityError,ValueError)):
        I.write_shadow_receipt(receipt,root)
    assert not list(outside.iterdir())


def test_identity_conflict_does_not_prefer_an_available_provider_id():
    participants=[{"id":"1","name":"New Mexico State","verified_aliases":["Aggies"]},
                  {"id":"2","name":"Utah State","verified_aliases":["Aggies"]}]
    result=I.resolve_event_identity(provider_id="1",name="Aggies",participants=participants)
    assert result["status"]=="QUARANTINED"
    assert result["resolved_id"] is None


def test_null_participant_id_is_missing_not_string_none():
    participants=[{"id":None,"name":"One"},{"id":"2","name":"Two"}]
    result=I.resolve_event_identity(provider_id=None,name="One",participants=participants)
    assert result["status"]=="QUARANTINED"
    assert result["resolved_id"] is None


def test_contradictory_sources_are_order_invariant():
    a={"event_id":"TEST_ONLY:e","team_id":"1","points":84}
    b={"event_id":"TEST_ONLY:e","team_id":"1","points":79}
    first=I.reconcile_sources([a,b]); second=I.reconcile_sources([b,a])
    assert first["status"]==second["status"]=="QUARANTINED"
    assert first["issues"]==second["issues"]
    assert first["selected_source"] is None


def test_zero_denominator_is_not_zero_performance():
    result=I.reconcile_rate(0,0)
    assert result["status"]=="QUARANTINED"
    assert result["rate"] is None


def nba_synthetic_history(n=45):
    """Hand-constructed fixtures only, never included in any empirical report."""
    from datetime import timedelta
    start=datetime(2023,1,1,20,tzinfo=timezone.utc)
    high={"fgm":40,"fga":90,"fg3m":10,"fg3a":30,"ftm":20,"fta":25,"orb":10,"drb":30,"tov":12}
    low={"fgm":39,"fga":91,"fg3m":9,"fg3a":31,"ftm":16,"fta":20,"orb":11,"drb":29,"tov":14}
    source={"source":"TEST_ONLY", "sha256":"a"*64,"retrieved_at_utc":"2026-01-01T00:00:00Z"}
    result=[]
    for index in range(n):
        h,a=(high,low) if index%2 else (low,high)
        result.append({"event_id":f"TEST_ONLY:{index}","start_time_utc":(start+timedelta(days=3*index)).isoformat(),
                       "season":2023,"home_id":"1","away_id":"2","home_team":"One","away_team":"Two",
                       "home_score":2*h["fgm"]+h["fg3m"]+h["ftm"],
                       "away_score":2*a["fgm"]+a["fg3m"]+a["ftm"],
                       "home_stats":deepcopy(h),"away_stats":deepcopy(a),"neutral_site":False,
                       "final":True,"sources":[deepcopy(source)]})
    return result


@pytest.fixture
def nba_fit():
    from models.experiments import nba_efficiency as N
    rows=N.prepare_examples(nba_synthetic_history())
    return N,rows,N.fit(rows[:-3])


def test_nba_predict_rejects_training_event(nba_fit):
    N,rows,state=nba_fit
    with pytest.raises(ValueError):
        N.predict(state,rows[-4])


def test_nba_predict_rejects_state_fitted_after_cutoff(nba_fit):
    N,rows,state=nba_fit
    target=deepcopy(rows[-1])
    target["event"]["forecast_cutoff_utc"]="2022-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        N.predict(state,target)


def test_nba_predict_rejects_changed_feature_procedure(nba_fit):
    N,rows,state=nba_fit
    target=deepcopy(rows[-1])
    target["feature_config"]["ewma_old_weight"]=0.1
    with pytest.raises(ValueError):
        N.predict(state,target)


def test_nba_predict_rejects_mutated_fitted_state(nba_fit):
    N,rows,state=nba_fit
    state=deepcopy(state)
    state["heads"]["possessions"]["intercept"]+=5
    with pytest.raises(ValueError):
        N.predict(state,rows[-1])


def test_nba_current_target_changes_do_not_change_pregame_features():
    from models.experiments import nba_efficiency as N
    games=nba_synthetic_history()
    original=N.prepare_examples(games)[-1]
    target=games[-1]
    target["home_stats"]["ftm"]+=1
    target["home_stats"]["fta"]+=1
    target["home_score"]+=1
    changed=N.prepare_examples(games)[-1]
    assert original["features"]==changed["features"]
    assert original["history_event_ids"]==changed["history_event_ids"]
    assert target["event_id"] not in changed["history_event_ids"]


def test_nba_later_event_cannot_reuse_state_after_earlier_custom_cutoff():
    from models.experiments import nba_efficiency as N
    history=nba_synthetic_history()
    last=history[-1]
    last["forecast_cutoff_utc"]=history[8]["start_time_utc"]
    try:
        row=N.prepare_examples(history)[-1]
    except ValueError:
        return  # Rejecting a nonmonotone cutoff is an acceptable contract.
    seen={r["event_id"]:r for r in history}
    cutoff=datetime.fromisoformat(last["forecast_cutoff_utc"])
    assert all(datetime.fromisoformat(seen[e]["start_time_utc"])<cutoff for e in row["history_event_ids"])


def cfb_synthetic_game():
    return {"game_id":"123","home_team":"One","away_team":"Two","home_id":"1","away_id":"2",
            "start_time_utc":"2024-09-08T18:00:00Z","season":2024,"week":2,"neutral_site":False,
            "conference_game":False,"completed":True,"home_points":21,"away_points":17,
            "home_division":"fbs","away_division":"fbs"}


@pytest.mark.parametrize("key,value",[("game_id",None),("game_id",True),("home_id",True),("away_id",float("nan"))])
def test_cfb_missing_or_boolean_identity_cannot_be_stringified(key,value):
    from models.experiments import cfb_efficiency as C
    row=cfb_synthetic_game();row[key]=value
    with pytest.raises(ValueError):
        C.canonical_game(row)


def test_cfb_weekly_cutoff_is_strictly_before_earliest_game():
    from models.experiments import cfb_efficiency as C
    row=C.prepare_examples({"games":[cfb_synthetic_game()],"team_games":[]})[0]
    assert datetime.fromisoformat(row["cutoff_utc"]) < datetime.fromisoformat(row["start_time_utc"])
