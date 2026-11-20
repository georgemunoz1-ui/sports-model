import copy
import datetime as dt
from scripts.mlb_research_review import blockers

NOW=dt.datetime(2026,9,23,20,tzinfo=dt.timezone.utc)
EVENT={'event_id':'MLB:42','start_time_utc':'2026-09-23T23:00:00Z','away_pitcher_id':1,'home_pitcher_id':2}
FEED={'gamePk':42,'gameData':{'status':{'abstractGameState':'Preview'},'datetime':{'dateTime':EVENT['start_time_utc']},'probablePitchers':{'away':{'id':1},'home':{'id':2}}}}
PACKAGE={'starter_state':{'1':{'era':3},'2':{'era':4}}}

def test_changed_starter_cannot_reuse_old_features():
    f=copy.deepcopy(FEED); f['gameData']['probablePitchers']['away']['id']=3
    assert 'AWAY_STARTER_CHANGED' in blockers(EVENT,f,PACKAGE,NOW)

def test_unknown_prior_is_not_approved_starter_input():
    e=dict(EVENT,away_pitcher_id='unknown:42:away')
    assert 'AWAY_STARTER_UNKNOWN' in blockers(e,FEED,PACKAGE,NOW)

def test_clock_and_provider_each_refuse_started_game():
    assert 'POST_START_OR_NOT_PREVIEW' in blockers(EVENT,FEED,PACKAGE,NOW+dt.timedelta(hours=4))
    f=copy.deepcopy(FEED); f['gameData']['status']['abstractGameState']='Live'
    assert 'POST_START_OR_NOT_PREVIEW' in blockers(EVENT,f,PACKAGE,NOW)

def test_corrected_start_time_requires_new_package():
    f=copy.deepcopy(FEED);f['gameData']['datetime']['dateTime']='2026-09-23T22:00:00Z'
    assert 'START_TIME_CHANGED' in blockers(EVENT,f,PACKAGE,NOW)

def test_known_profile_is_required_even_with_matching_probable():
    assert 'AWAY_OBSERVED_STARTER_PROFILE_MISSING' in blockers(EVENT,FEED,{'starter_state':{'2':{}}},NOW)
    assert blockers(EVENT,FEED,PACKAGE,NOW)==[]
