"""Synthetic parity/refusal tests for post-start diagnostics; no live forecasts."""
import copy
import hashlib
import json
import unittest
import numpy as np
import test_nfl_weekly_state as fixtures
STAMP=fixtures.STAMP
from models.nfl.contextual.reconstruction import run_qb
from models.nfl.contextual.runtime import run


class Reconstruction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.Weekly.setUpClass()

    def setUp(self):
        self.h=fixtures.Weekly(); self.h.setUp(); self.addCleanup(self.h.doCleanups)
        h=self.h
        h.games['espn']=123
        h.games['temp']=None; h.games['wind']=None  # no realized weather in archived prestart test
        for side in ('home','away'):
            h.games[side+'_qb_name']='Test '+h.games[side+'_team']
        h.schedule=fixtures.source(h.games,True)
        a=h.advance(); b=h.advance(a,2)
        self.base,self.context,self.event=h.event_packet(b)
        j={'header':{'id':'123','competitions':[{'date':self.event['start_time_utc'],
            'status':{'type':{'completed':False}},'competitors':[
            {'homeAway':s,'team':{'abbreviation':self.event[s+'_team']}} for s in ('home','away')]}]},
            'article':{'story':'<a href="https://example.com/id/1/qb">Test KC</a> and <a href="https://example.com/id/2/qb">Test DEN</a>'}}
        raw=json.dumps(j); receipt={'sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'source_url':'https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=123','retrieved_at_utc':STAMP}
        self.personnel={'text':raw,'receipt':receipt}
        p=self.context['personnel'];p.update(source=receipt['source_url'],source_sha256=receipt['sha256'])
        for team,provider in [('KC','1'),('DEN','2')]:
            p['state']['quarterbacks'][team].update(name='Test '+team,espn_id=provider)
        r=h.schedule['receipt']
        self.context['rest']={'source':r['source_url'],'source_sha256':r['sha256'],
            'retrieved_at_utc':STAMP,'available_by_utc':STAMP,'event_id':self.event['event_id'],
            'home_rest':7,'away_rest':7,'definition':'SYNTHETIC'}

    def reconstruct(self,**kw):
        return run_qb(self.h.model,self.h.recovered,kw.get('base',self.base),
            kw.get('context',self.context),self.event,kw.get('cutoff',STAMP),
            seed_id=self.h.seed,personnel_source=kw.get('personnel',self.personnel))

    def test_exact_registered_head_feature_parity_and_replay(self):
        live,_,_=run(self.h.model,self.h.recovered,self.base,self.context,self.event,STAMP,
                     model_id='nfl.integrated_context.qb.v1.research')
        r,a=self.reconstruct(); again,b=self.reconstruct()
        self.assertEqual(r['prediction'],live['prediction'])
        self.assertEqual(r['features'],{k:live['features'][k] for k in r['features']})
        self.assertEqual(r['identity'],again['identity']);self.assertTrue(np.array_equal(a,b))
        self.assertEqual(len(a),100000);self.assertFalse(r['canonical_prospective_eligible'])
        self.assertFalse(r['action_authority']);self.assertEqual(r['disposition'],'POST_START_RESEARCH_RECONSTRUCTION')

    def test_source_hash_and_cutoff_refused(self):
        p=copy.deepcopy(self.personnel);p['text']+=' '
        with self.assertRaisesRegex(ValueError,'SOURCE_HASH'):self.reconstruct(personnel=p)
        p=copy.deepcopy(self.personnel);p['receipt']['retrieved_at_utc']='2026-09-22T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'SOURCE_AFTER_INFORMATION'):self.reconstruct(personnel=p)
        with self.assertRaisesRegex(ValueError,'CUTOFF_NOT_PRESTART'):
            self.reconstruct(cutoff='2026-09-27T18:00:00Z')

    def test_rest_base_and_qb_tamper_refused(self):
        c=copy.deepcopy(self.context);c['rest']['home_rest']=8
        with self.assertRaisesRegex(ValueError,'REST_BINDING'):self.reconstruct(context=c)
        base=copy.deepcopy(self.base);base['temperature_f']=90
        with self.assertRaisesRegex(ValueError,'BASE_BINDING'):self.reconstruct(base=base)
        c=copy.deepcopy(self.context);c['personnel']['state']['quarterbacks']['KC']['espn_id']='2'
        with self.assertRaisesRegex(ValueError,'QB_CROSSWALK'):self.reconstruct(context=c)

    def test_target_outcomes_and_extra_context_refused(self):
        base=copy.deepcopy(self.base);base['home_score']=99
        with self.assertRaisesRegex(ValueError,'OUTCOME_FORBIDDEN'):self.reconstruct(base=base)
        c=copy.deepcopy(self.context);c['weather']={}
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_CONTEXT'):self.reconstruct(context=c)


if __name__=='__main__':unittest.main()
