"""A5: two adapters each checked against hand-computed values, not each other."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from models.current.freshness import serving_candidate_features
from scripts.prepare_initial_baselines import operational_rest_training_example

FIXTURE = Path(__file__).parent/'fixtures/operational_rest_golden_vectors_v1.json'
VECTORS = json.loads(FIXTURE.read_text())['vectors']
SHA = 'a'*64


def inputs(vector):
    event = {'event_id':vector['league'].upper()+':golden-'+vector['id'],
             'home_id':'GOLDEN_HOME','away_id':'GOLDEN_AWAY',
             'start_time_utc':vector['target_start'],'neutral_site':False}
    state = {team:{'n':20,'for':3.0,'against':3.0} for team in ['GOLDEN_HOME','GOLDEN_AWAY']}
    records=[]
    if vector['previous_start'] is not None:
        records.append({'event_id':vector['league'].upper()+':golden-previous-'+vector['id'],
                        'home_id':'GOLDEN_HOME','away_id':'GOLDEN_AWAY',
                        'start_time_utc':vector['previous_start'],'status':'final',
                        'observed_at_utc':vector['observed'],'source_sha256':SHA})
    if vector.get('include_upcoming'):
        records.extend([{'event_id':event['event_id'],'home_id':'GOLDEN_HOME','away_id':'GOLDEN_AWAY',
                         'start_time_utc':vector['target_start'],'status':'nonfinal',
                         'observed_at_utc':vector['observed'],'source_sha256':SHA},
                        {'event_id':vector['league'].upper()+':golden-later','home_id':'GOLDEN_HOME','away_id':'GOLDEN_AWAY',
                         'start_time_utc':'2026-10-25T23:00:00Z','status':'nonfinal',
                         'observed_at_utc':vector['observed'],'source_sha256':SHA}])
    coverage=[{'team_id':team,'from_utc':'2026-10-01T00:00:00Z','through_utc':vector['observed'],
               'observed_at_utc':vector['observed'],'source_sha256':SHA,'complete':True,'population':'ALL_PLAYED_GAMES'}
              for team in ['GOLDEN_HOME','GOLDEN_AWAY']]
    return state,event,3.0,records,{'cutoff_utc':vector['cutoff'],'coverage':coverage}


class ProxyForbidden(dict):
    """Fails on a read even when a missing proxy could have been defaulted."""
    def __getitem__(self,key):
        if key in {'last','rest','home_rest','away_rest','rest_proxy','last_game_start_utc'}:
            raise AssertionError('LEGACY_PROXY_READ:'+key)
        return super().__getitem__(key)
    def get(self,key,default=None):
        if key in {'last','rest','home_rest','away_rest','rest_proxy','last_game_start_utc'}:
            raise AssertionError('LEGACY_PROXY_READ:'+key)
        return super().get(key,default)


class GoldenVectors(unittest.TestCase):
    def assert_oracle(self,result,vector):
        expected=vector['feature_days']
        self.assertEqual(result['candidate_ready'],expected is not None)
        if expected is None:
            self.assertIsNone(result['features'])
        else:
            for side in ['home','away']:
                self.assertAlmostEqual(result['features'][side+'_rest'],expected,places=13)
                self.assertAlmostEqual(result['rest_receipt']['per_side'][side]['rest_start_to_start_days'],vector['raw_days'],places=13)
            self.assertEqual(set(result['features']),{'home_for','home_against','away_for','away_against','home_rest','away_rest','home_cold','away_cold','neutral'})
        self.assertEqual(result['proxy_columns_used'],[])

    def test_training_adapter_against_hand_computed_oracle(self):
        for vector in VECTORS:
            with self.subTest(vector=vector['id']):
                state,event,prior,records,kwargs=inputs(vector)
                self.assert_oracle(operational_rest_training_example(state,event,prior,records,**kwargs),vector)

    def test_serving_adapter_against_hand_computed_oracle(self):
        for vector in VECTORS:
            with self.subTest(vector=vector['id']):
                state,event,prior,records,kwargs=inputs(vector)
                self.assert_oracle(serving_candidate_features(state,event,prior,records,**kwargs),vector)

    def test_schedule_perturbation_changes_each_adapter_by_hand_computed_quarter_day(self):
        vector=next(v for v in VECTORS if v['id']=='prior_night')
        for adapter in [operational_rest_training_example,serving_candidate_features]:
            with self.subTest(adapter=adapter.__name__):
                state,event,prior,records,kwargs=inputs(vector)
                old=adapter(state,event,prior,records,**kwargs)
                # Shift the actual prior start six hours earlier; form state unchanged.
                records[0]['start_time_utc']='2026-10-21T17:00:00Z'
                new=adapter(state,event,prior,records,**kwargs)
                self.assertEqual(old['features']['away_rest'],1.0)
                self.assertEqual(new['features']['away_rest'],1.25)
                for name in old['features']:
                    if name not in {'home_rest','away_rest'}:
                        self.assertEqual(old['features'][name],new['features'][name])

    def test_training_proxy_columns_absent_and_unread(self):
        self.check_proxy_absence(operational_rest_training_example)

    def test_serving_proxy_columns_absent_and_unread(self):
        self.check_proxy_absence(serving_candidate_features)

    def check_proxy_absence(self,adapter):
        vector=next(v for v in VECTORS if v['id']=='prior_night')
        state,event,prior,records,kwargs=inputs(vector)
        state={team:ProxyForbidden(values) for team,values in state.items()}
        with patch('models.current.baseline.feature',side_effect=AssertionError('LEGACY_FEATURE_BUILDER_USED')):
            result=adapter(state,event,prior,records,**kwargs)
        self.assert_oracle(result,vector)
        self.assertNotIn('rest_proxy',result['features'])
        self.assertNotIn('last',result['features'])

    def test_poisoned_embargo_proxy_cannot_change_either_candidate(self):
        vector=next(v for v in VECTORS if v['id']=='prior_night')
        for adapter in [operational_rest_training_example,serving_candidate_features]:
            state,event,prior,records,kwargs=inputs(vector)
            old=adapter(state,event,prior,records,**kwargs)
            poisoned=copy.deepcopy(state)
            for row in poisoned.values():row.update(last='2099-12-31T00:00:00Z',rest_proxy=-9999)
            new=adapter(poisoned,event,prior,records,**kwargs)
            self.assertEqual(old['features'],new['features'])


if __name__=='__main__':unittest.main()
