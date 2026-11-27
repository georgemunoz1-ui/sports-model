import copy
from datetime import datetime, timezone
import pytest
from scripts import capture_context_observations as c

def at(hour, minute=0):
    return datetime(2026,12,1,hour,minute,tzinfo=timezone.utc)

def receipt(url):
    return {"url":url,"status":"CAPTURED","requested_at_utc":at(16).isoformat(),
            "retrieved_at_utc":at(16,1).isoformat()}

@pytest.fixture
def nws():
    b={"league":"NFL","event_id":"NFL:synthetic","stadium_id":"stadium",
       "roof":"outdoor","latitude":42.0,"longitude":-78.0,"start_utc":at(20,15).isoformat()}
    p={"properties":{"gridId":"BUF","gridX":1,"gridY":2,
       "forecastHourly":c.NWS+"/gridpoints/BUF/1,2/forecast/hourly"}}
    f={"properties":{"updateTime":at(15).isoformat(),"generatedAt":at(16).isoformat(),
       "periods":[{"startTime":at(20).isoformat(),"endTime":at(21).isoformat(),
                   "temperature":5,"temperatureUnit":"C","windSpeed":"15 to 20 mph",
                   "probabilityOfPrecipitation":{"value":70}}]}}
    return b,p,f,[receipt(c.weather_points_url(b)),receipt(c.hourly_url(p))]

def test_nws_preserves_range_and_precip_probability(nws):
    x=c.extract_weather(*nws,at(16,2))
    assert x["temperature_f"]==41 and x["wind_mph_low"]==15 and x["wind_mph_high"]==20
    assert x["precipitation_probability_pct"]==70
    assert x["status"]=="OBSERVED_FORECAST_NOT_CONSUMED"

@pytest.mark.parametrize("mutation,error",[
    ("future","NWS_FORECAST_VINTAGE_INVALID"),("missing","NWS_PRECIP_PROBABILITY_MISSING"),
    ("duplicate","NWS_HOUR_NOT_UNIQUE_OR_MISSING"),("late","POST_OR_AT_START"),
    ("url","NWS_RECEIPT_BINDING_MISMATCH")])
def test_nws_refusals(nws,mutation,error):
    b,p,f,r=nws
    now=at(16,2)
    if mutation=="future":f["properties"]["generatedAt"]=at(17).isoformat()
    if mutation=="missing":f["properties"]["periods"][0]["probabilityOfPrecipitation"]["value"]=None
    if mutation=="duplicate":f["properties"]["periods"]*=2
    if mutation=="late":now=at(20,15)
    if mutation=="url":r[1]["url"]=c.NWS+"/gridpoints/BUF/2,2/forecast/hourly"
    with pytest.raises(ValueError,match=error):c.extract_weather(b,p,f,r,now)

@pytest.fixture
def sr():
    b={"league":"CBB","event_id":"CBB:synthetic","sr_team_ids":["a","b"],"sr_venue_id":"venue",
       "sr_game_id":"game","start_utc":at(20,15).isoformat(),"provider_schedule_date":"2026-12-01",
       "access_level":"trial"}
    g={"id":"game","home":{"id":"b"},"away":{"id":"a"},"venue":{"id":"venue","name":"Arena"},
       "status":"scheduled","neutral_site":True,"scheduled":at(20,14).isoformat()}
    return b,{"date":"2026-12-01","games":[g]},receipt(c.sr_url(b))

def test_sr_orientation_and_earliest_time(sr):
    x=c.extract_venue(*sr,at(16,2))
    assert x["earliest_observed_start_utc"]==at(20,14).isoformat()
    assert x["status"]=="VENUE_OBSERVED_PENDING_INDEPENDENCE_AND_MAPPER_REVIEW"

@pytest.mark.parametrize("mutation,error",[
    ("team","SR_TEAM_IDENTITY_MISMATCH"),("bool","SR_NOT_EXPLICITLY_SCHEDULED_NEUTRAL"),
    ("venue","SR_VENUE_IDENTITY_MISMATCH"),("duplicate","SR_EVENT_NOT_UNIQUE_OR_MISSING"),
    ("tip","SR_TIP_MISMATCH_OR_LATE"),("final","SR_NOT_EXPLICITLY_SCHEDULED_NEUTRAL")])
def test_sr_refusals(sr,mutation,error):
    b,d,r=sr;g=d["games"][0]
    if mutation=="team":g["away"]["id"]="c"
    if mutation=="bool":g["neutral_site"]="true"
    if mutation=="venue":g["venue"]["id"]="other"
    if mutation=="duplicate":d["games"]*=2
    if mutation=="tip":g["scheduled"]=at(20,13).isoformat()
    if mutation=="final":g["status"]="closed"
    with pytest.raises(ValueError,match=error):c.extract_venue(b,d,r,at(16,2))
