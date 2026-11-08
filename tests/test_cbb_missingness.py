"""Exercise the CBB writer and independent reader, including refused peer rows."""
from copy import deepcopy
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from scripts import cbb_missingness as audit, cbb_shadow as m, verify_cbb_shadow as reader
from scripts.cbb_market_and_grades import load_audited_card

DAY = date(2026,11,8)
NOW = datetime(2026,11,8,13,tzinfo=timezone.utc)


def jsonfile(path,obj):
    path.write_text(json.dumps(obj,sort_keys=True))


def game(i, home, away, venue):
    return {"id":str(i),"h":home,"a":away,"hn":home,"an":away,"neutral":venue,"utc":(NOW+timedelta(hours=4)).isoformat(),
            "day":str(DAY),"season":2027,"d1":True,"type":2,"affiliation_resolution":"OBSERVED_BOTH",
            "status":"STATUS_SCHEDULED","issues":[] if venue is not None else ["VENUE_UNRESOLVED"]}


def population(monkeypatch,path):
    target=[game(5,"1","2",False),game(6,"9","2",False),game(7,"2","1",None)]
    games=[dict(id="old",season=2026,day="2026-02-20",h="1",a="2",utc="2026-02-20T19:00:00Z",neutral=True)]
    state={"1":np.array([2.,1.,6]),"2":np.array([1.,2.,9])}
    prior=(2.,143.)
    rec=dict(id="old",day="2026-02-20",margin=1.,total=145.,p_home=.6,
             actual_margin=1.,actual_total=145.,prior_margin=0.,prior_total=143.,prior_p_home=.5)
    errors=np.array([[-2.,-1.],[0.,-3.],[1.,4.]])
    monkeypatch.setattr(m,"now",lambda:NOW)
    monkeypatch.setattr(m,"load",lambda *_:(games,target,{"season":2027},{}))
    monkeypatch.setattr(m,"fit",lambda _:(state,prior,errors,[rec],2027))
    jsonfile(path / "manifest.json",{"test_fixture":"synthetic control"})


def test_source_failure_preserves_unknown_inventory(tmp_path):
    dst=tmp_path/"failed"
    with pytest.raises(FileNotFoundError):
        m.issue(tmp_path,DAY,dst)
    f=json.loads((dst/"missingness_failure.json").read_text())
    assert f["status"]=="BLOCKED" and f["scheduled"] is None
    assert f["observation_state"]=="ACQUISITION_FAILURE" and not (dst/"card.json").exists()


def test_missing_venue_parity():
    for missing in (None, "false", np.nan, 0, 1):
        assert m.venue(missing) is None
        with pytest.raises(ValueError,match="VENUE_UNRESOLVED"):
            m.project({},{"neutral":missing},(5.,145.))
    assert m.venue(False) is m.venue(np.bool_(False)) is False


def test_duplicate_manifest_refused_before_data_consumed(tmp_path):
    manifest={"date":str(DAY),"captured_at_utc":NOW.isoformat(),"season":2027}
    rows=[{"kind":"history","file":f"mbb_schedule_{n}.parquet"} for n in range(2022,2028)]
    rows += [{"kind":"scoreboard","file":(DAY+timedelta(days=n)).strftime("%Y%m%d")+".json"} for n in range(-4,2)]
    jsonfile(tmp_path/"manifest.json",dict(manifest,entries=rows+[rows[0]]))
    with pytest.raises(ValueError,match="DUPLICATE_OR_UNEXPECTED_SOURCE"):
        m.load(tmp_path,DAY,NOW)


def test_native_writer_reader_partial_scope_and_tampering(monkeypatch,tmp_path):
    population(monkeypatch,tmp_path)
    dst=tmp_path/"first"
    m.issue(tmp_path,DAY,dst)
    card_path=dst/"card.json"
    card=json.loads(card_path.read_text())
    assert [r.get("reason") for r in card["forecasts"]]==[None,"INSUFFICIENT_TEAM_HISTORY","VENUE_UNRESOLVED"]
    assert card["missingness_runtime_checks"]["status"]=="PASS"
    assert reader.verify(tmp_path,dst,m.sha(card_path.read_bytes()))["missingness_receipts_replayed"]==3
    assert load_audited_card(card_path,m.sha(card_path.read_bytes()))==card
    dst2=tmp_path/"refresh"
    m.issue(tmp_path,DAY,dst2,card_path,m.sha(card_path.read_bytes()))
    refreshed=dst2/"card.json"
    second=json.loads(refreshed.read_text()); diff=second["forecasts"][0]["missingness_audit"]["details"]["change"]
    assert diff["status"]=="PAIRED_SAME_PROCEDURE" and diff["sampling_error_delta"]==0
    assert diff["sporting_observations"]==diff["missingness_imputation"]=={"home_margin":0.,"total":0.}
    assert reader.verify(tmp_path,dst2,m.sha(refreshed.read_bytes()),card_path)["forecasts_replayed"]==1
    for field in ("missingness_audit","total"):
        forged=deepcopy(card)
        row=forged["forecasts"][0]
        if field=="total": row[field] += 5
        else: del row[field]
        with pytest.raises(ValueError,match="CBB_MISSINGNESS_READBACK"):
            audit.verify(forged)


def test_orientation_and_order_and_alias_invariance():
    raw={"id":"8","season":{"type":2,"year":2027},"competitions":[{
        "id":"8","date":NOW.isoformat(),"neutralSite":True,"status":{"type":{"name":"STATUS_SCHEDULED","completed":False}},
        "competitors":[{"id":str(i),"homeAway":side,"team":{"id":str(i),"displayName":"t"+str(i),"conferenceId":"2"}}
                       for i,side in ((1,"home"),(2,"away"))]}]}
    base=m.normalized(raw)
    raw["competitions"][0]["competitors"].reverse()
    assert base==m.normalized(raw)
    raw["competitions"][0]["competitors"][0]["team"]["displayName"]="approved display alias"
    changed=m.normalized(raw)
    state={"1":[2.,1.,8],"2":[1.,3.,9]}
    assert m.project(state,changed,[3.,143.])==m.project(state,base,[3.,143.])
    raw["competitions"][0]["competitors"].append(raw["competitions"][0]["competitors"][0])
    assert "TEAM_IDENTITY" in m.normalized(raw)["issues"]
