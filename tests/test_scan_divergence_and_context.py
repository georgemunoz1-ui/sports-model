import copy
import json
import hashlib
import pytest
from scripts import scan_divergence_and_context as s
from scripts import cbb_market_and_grades as n

def row(**kw):
    r=dict(event_id="CBB:synthetic",league="CBB",product="total",side="over",line=140.5,
           point_total=148.88,period="FULL_GAME",settlement_scope=s.SETTLEMENT,p=.7062,market=.5152,
           pregame_cutoff_utc="2026-12-01T20:00:00Z")
    r.update(kw)
    for k in ("event_id","product","side","line","period","settlement_scope"):
        r["market_"+k]=r[k]
    return r

def codes(alerts): return {a.alert_code for a in alerts}

def test_divergence():
    assert codes(s.scan_contract(row()))=={"MARKET_PROB_DIVERGENCE","TOTAL_LINE_DIVERGENCE"}

@pytest.mark.parametrize("p",[float("nan"),float("inf"),True,-.01,1.01,None])
def test_invalid_p(p):
    assert codes(s.scan_contract(row(p=p)))=={"INVALID_OR_MISSING_NATIVE_PROBABILITY"}

@pytest.mark.parametrize("field",["event_id","product","side","period","settlement_scope","line"])
def test_required_match(field):
    r=row();del r["market_"+field]
    assert "CONTRACT_IDENTITY_MISSING" in codes(s.scan_contract(r))
    r["market_"+field]="wrong"
    assert "CONTRACT_MISMATCH" in codes(s.scan_contract(r))
    assert "MARKET_PROB_DIVERGENCE" not in codes(s.scan_contract(r))

def test_exact_threshold():
    assert not s.scan_contract(row(p=.58,market=.5,point_total=145.5))

def test_invalid_line_and_point():
    assert "CONTRACT_LINE_INVALID" in codes(s.scan_contract(row(line=True)))
    assert "POINT_TOTAL_INVALID" in codes(s.scan_contract(row(point_total="148")))

def test_untrusted_venue():
    r=row();ctx={"event_id":r["event_id"],"receipt_sha256":"a"*64,
        "retrieved_at_utc":"2026-12-01T19:00Z","pregame_cutoff_utc":r["pregame_cutoff_utc"],
        "orientation_reversed":True,"neutral_venue_verified":True,"venue_source_sha256":"b"*64}
    assert {"UNAUTHENTICATED_CONTEXT_RECEIPT","CBB_UNVERIFIED_NEUTRAL_REVERSAL"}<=codes(s.scan_event_row(r,ctx))

@pytest.mark.parametrize("seen",["2026-12-01T19:00","2026-12-01T20:00Z","2026-12-01T10:00Z"])
def test_context_clock(seen):
    r=row();ctx={"event_id":r["event_id"],"retrieved_at_utc":seen,"pregame_cutoff_utc":r["pregame_cutoff_utc"]}
    assert "STALE_OR_POST_CUTOFF_RECEIPT" in codes(s.scan_event_row(r,ctx))

def test_weather_unknown_and_unverified_consumption():
    r=row(league="NFL")
    a=codes(s.scan_event_row(r,{"roof":"bogus","temperature_status":"WEATHER_IMPUTED",
        "wind_status":"WEATHER_OBSERVED_CONSUMED","precipitation_status":"bogus"}))
    assert {"NFL_ROOF_UNKNOWN","NFL_TEMPERATURE_WEATHER_IMPUTED","NFL_WIND_CONSUMPTION_UNVERIFIED",
            "NFL_PRECIPITATION_STATUS_MISSING_OR_UNKNOWN"}<=a

def dump(p,obj):
    raw=json.dumps(obj,allow_nan=False).encode();p.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()

@pytest.fixture
def bundle(tmp_path):
    start="2020-01-02T00:00Z";seen="2020-01-01T17:59Z"
    fc=dict(event_id="CBB:7",forecast_status="FORECAST_GENERATED",start_time_utc=start,
            model_input_snapshot={"h":"1","a":"2","neutral":False},settlement=s.SETTLEMENT,
            p_home_win=.7,total=148.88,distributions={"total":{"support":[140,150],"masses":[.2,.8]}})
    card=dict(schema="sports.cbb.shadow_card.v1",league="CBB",market_input=False,action_authority=False,
        date="2020-01-01",as_of_utc="2020-01-01T18:00Z",generated_at_utc="2020-01-01T18:01Z",
        scheduled=2,forecast_count=1,forecasts=[fc,{"event_id":"CBB:8","forecast_status":"UNAVAILABLE","reason":"OUTSIDE_VERIFIED_D1_PAIR"}])
    comp={"id":"7","date":start,"status":{"type":{"state":"pre"}},"competitors":[
        {"id":"1","homeAway":"home"},{"id":"2","homeAway":"away"}]}
    raw={"header":{"id":"7","competitions":[comp]},"pickcenter":[{"provider":{"name":"Draft Kings","id":100},
        "total":{"over":{"close":{"line":"o140.5","odds":"-110"}},"under":{"close":{"line":"u140.5","odds":"-110"}}}}]}
    (tmp_path/"raw").mkdir()
    raw_sha=dump(tmp_path/"raw"/"summary.json",raw);url=n.ESPN+"summary?event=7"
    man_sha=dump(tmp_path/"manifest.json",{"date":"20200101","sources":[{"url":url,"file":"raw/summary.json","sha256":raw_sha,"retrieved_at_utc":seen}]})
    card_sha=dump(tmp_path/"card.json",card)
    market=dict(schema="sports.cbb.market.shadow.v1",date=card["date"],action_authority=False,
        frozen_parent_sha256=card_sha,created_at_utc="2020-01-01T18:02Z",rows=[dict(
        event_id="CBB:7",book="DraftKings",settlement=s.SETTLEMENT,status="DIAGNOSTIC_RETRIEVAL_TIME_ONLY",
        source_sha256=raw_sha,source_url=url,quote_retrieved_at_utc=seen,contracts=n.market_rows(raw,fc))])
    market_sha=dump(tmp_path/"market.json",market)
    return [tmp_path/"card.json",card_sha,tmp_path/"market.json",market_sha,tmp_path,man_sha],market

def test_native_replay_and_coverage(bundle):
    args,_=bundle;before=[p.read_bytes() for p in (args[0],args[2])]
    out=s.scan_frozen_cbb(*args)
    assert out["scheduled"]==2 and out["contracts_scanned"]==2
    assert not out["official_ledger_admitted"] and not out["action_authority"]
    assert "MARKET_PROB_DIVERGENCE" in {a["alert_code"] for a in out["rows"][0]["alerts"]}
    assert "CONTEXT_RECEIPT_MISSING" in {a["alert_code"] for a in out["rows"][0]["alerts"]}
    assert out["rows"][1]["alerts"][0]["alert_code"]=="FORECAST_MISSING"
    assert before==[p.read_bytes() for p in (args[0],args[2])]

def test_native_tampered_contract_even_with_repin(bundle):
    args,market=bundle;market["rows"][0]["contracts"][0]["win"]=.99
    args[3]=dump(args[2],market)
    out=s.scan_frozen_cbb(*args)
    assert out["contracts_scanned"]==0
    assert "EXACT_CONTRACT_REPLAY_MISMATCH" in str(out)

def test_native_tampered_raw(bundle):
    args,_=bundle;(args[4]/"raw"/"summary.json").write_text("{}")
    out=s.scan_frozen_cbb(*args)
    assert out["contracts_scanned"]==0
    assert "SHA-256 mismatch" in str(out)

def test_push_aware_reference():
    fc=dict(event_id="CBB:7",total=140,settlement=s.SETTLEMENT)
    pair=[dict(product="total",side="over",line=140,american_price=-110,win=.6,push=.2,loss=.2),
          dict(product="total",side="under",line=140,american_price=-110,win=.2,push=.2,loss=.6)]
    assert list(s._contract_rows(fc,pair))[0]["p"]==pytest.approx(.75)
