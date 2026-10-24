import copy
import numpy as np
import pandas as pd
import pytest
from models.cfb.joint_empirical_v1 import fit, distribution, summarize, simulate


def frame():
    return pd.DataFrame({'game_id': ['1','2','3','4'], 'kick': ['2020-01-01']*4,
                         'home_division': ['fbs']*4, 'away_division': ['fbs']*4,
                         'home_points': [21,24,14,28], 'away_points': [14,21,21,14],
                         'strength': [0.,1.,2.,3.]})


def test_coherent_score_products_and_push():
    s = np.array([[21,14],[24,21],[14,21],[28,14]])
    r = summarize(s, -7, 35)
    assert sum(r[k] for k in ['home_win','away_win','tie']) == 1
    assert r['home_margin'] == r['home_score']-r['away_score']
    assert r['total'] == r['home_score']+r['away_score']
    assert r['home_cover'] == {'win': .25, 'push': .25, 'loss': .5}
    assert r['over'] == {'win': .5, 'push': .5, 'loss': 0}
    assert summarize(s,-7.5)['home_cover']['push'] == 0


def test_deterministic_draws_and_hash():
    s = np.array([[21,14],[24,21],[14,21],[28,14]])
    a, ma = simulate(s,'frozen'); b, mb = simulate(s,'frozen')
    assert np.array_equal(a,b) and ma == mb
    assert len(a) == 100000
    assert set(map(tuple,a)) <= set(map(tuple,s))
    assert abs(summarize(a)['home_win']-.75) < .005


def test_fit_and_corruption():
    state=fit(frame(),['strength'],'2021-01-01T00:00:00Z',2)
    s,meta=distribution(state,[1.])
    assert len(s)==2 and len(meta['neighbour_event_ids'])==2
    state['scores'][0][0]+=1
    with pytest.raises(ValueError,match='STATE_HASH'): distribution(state,[1.])


@pytest.mark.parametrize('change,error', [('division','FBS_ONLY'),('duplicate','DUPLICATE'),('future','FUTURE'),('tie','TIED'),('negative','INVALID')])
def test_refuse_bad_training(change,error):
    d=frame()
    if change=='division': d.loc[0,'home_division']='fcs'
    if change=='duplicate': d.loc[1,'game_id']='1'
    if change=='future': d.loc[0,'kick']='2022-01-01'
    if change=='tie': d.loc[0,'home_points']=14
    if change=='negative': d.loc[0,'away_points']=-1
    with pytest.raises(ValueError,match=error):fit(d,['strength'],'2021-01-01T00:00:00Z',2)


@pytest.mark.parametrize('line',[float('nan'),float('inf'),7.25,True])
def test_invalid_line(line):
    with pytest.raises(ValueError):summarize(np.array([[21,14]]),line)


def test_market_firewall():
    d=frame();d['market_odds']=0
    with pytest.raises(ValueError,match='FIREWALL'):fit(d,['market_odds'],'2021-01-01T00:00:00Z',2)


def test_timezone_required():
    with pytest.raises(ValueError,match='TIMEZONE'):fit(frame(),['strength'],'2021-01-01',2)


def test_unknown_availability_is_not_healthy():
    from scripts.capture_cfb_context_review import extract
    event={'event_id':'CFB:1','start_time_utc':'2026-10-03T23:30:00Z'}
    receipt={'status':'CAPTURED','retrieved_at_utc':'2026-10-03T23:00:00Z','raw_sha256':'example','url':'https://example.org'}
    r=extract(event,receipt,{'header':{'id':'1'},'gameInfo':{'weather':{'temperature':98}}})
    assert r['player_availability']['state']=='ACQUIRE_REQUIRED'
    assert r['weather']['consumed'] is False
    assert r['weather']['units']=='PROVIDER_UNITS_UNVERIFIED'


def test_context_wrong_event_and_late_capture():
    from scripts.capture_cfb_context_review import extract
    event={'event_id':'CFB:1','start_time_utc':'2026-10-03T23:30:00Z'}
    receipt={'status':'CAPTURED','retrieved_at_utc':'2026-10-03T23:45:00Z','raw_sha256':'example','url':'https://example.org'}
    with pytest.raises(ValueError,match='EVENT_MISMATCH'):extract(event,receipt,{'header':{'id':'2'}})
    assert extract(event,receipt,{'header':{'id':'1'}})['pre_start_capture'] is False
