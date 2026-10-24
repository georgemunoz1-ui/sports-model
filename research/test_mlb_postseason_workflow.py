import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

from scripts import mlb_postseason_workflow as W
from research.mlb_postseason_v1 import sha,stamp,save_once


def fixture(root):
    start=dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=2)
    day=start.astimezone(ZoneInfo('America/Los_Angeles')).date();prior=(day-dt.timedelta(days=1)).isoformat()
    def team(i,score=None):
        name='CHC' if i==0 else 'SD' if i==1 else 'TEST_'+str(i)
        t={'team':{'id':i,'name':name}}
        if score is not None:t['score']=score
        return t
    games=[{'gamePk':100+i,'gameType':'R','officialDate':prior,'gameDate':prior+'T12:00:00Z','status':{'abstractGameState':'Final','detailedState':'Final'},'teams':{'away':team(i*2,3),'home':team(i*2+1,4)}}for i in range(15)]
    today={'gamePk':999,'gameType':'F','officialDate':str(day),'gameDate':start.isoformat(),'status':{'abstractGameState':'Preview'},'teams':{'away':team(0),'home':team(1)}}
    for side,pid in [('away',1),('home',2)]:today['teams'][side]['probablePitcher']={'id':pid,'fullName':'Pitcher '+str(pid)}
    feed={'gamePk':999,'gameData':{'teams':{s:t['team']for s,t in today['teams'].items()},'probablePitchers':{s:t['probablePitcher']for s,t in today['teams'].items()}},'liveData':{'boxscore':{'teams':{'away':{},'home':{}}}}}
    payloads={'season':{'totalGames':15,'dates':[{'date':prior,'totalGames':15,'games':games}]},'today':{'totalGames':1,'dates':[{'date':str(day),'totalGames':1,'games':[today]}]},'gamefeed_999':feed}
    for pid in (1,2):
        payloads['pitcher_'+str(pid)]={'stats':[{'group':{'displayName':'pitching'},'type':{'displayName':'gameLog'},'splits':[{'player':{'id':pid},'gameType':'R','date':prior,'game':{'gamePk':100},'stat':{'inningsPitched':'6.0','outs':18,'earnedRuns':2,'strikeOuts':5,'baseOnBalls':2,'battersFaced':25,'gamesStarted':1}}]}]}
    receipts=[]
    for kind,data in payloads.items():
        f=root/'sources'/('raw/'+kind+'.json');save_once(f,data)
        url=f'https://statsapi.mlb.com/api/v1/people/{kind.split("_")[-1]}/stats'if kind.startswith('pitcher_')else 'https://statsapi.mlb.com/test'
        receipts.append({'kind':kind,'league':'mlb','status':'CAPTURED','url':url,'raw_path':'raw/'+kind+'.json','raw_sha256':sha(f),'retrieved_at_utc':stamp()})
    save_once(root/'sources/report.json',{'sources':receipts})
    with contextlib.redirect_stdout(io.StringIO()):W.prepare(root,str(day))
    c=W.ROOT/'research/registrations/mlb_postseason_v1.json'
    review={'reviewed_at_utc':stamp(),'package_sha256':sha(root/'package.json'),'contract_sha256':sha(c),'reviewed_event_ids':['MLB:999'],'decision':'ALLOW_LIMITED_FEATURE_RESEARCH_ONLY','evidence':{'scope':'SYNTHETIC TEST ONLY'},'action_authority':False}
    save_once(root/'review.json',review)
    return c,root/'review.json'


class WorkflowTests(unittest.TestCase):
    def test_source_rebuild_and_concurrent_idempotency(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);c,r=fixture(root)
            with ThreadPoolExecutor(max_workers=2)as ex:rows=list(ex.map(lambda _:W.run(root,c,r,root/'out'),range(2)))
            self.assertEqual(rows[0]['request_id'],rows[1]['request_id'])
            self.assertEqual(len(list((root/'out/runs').iterdir())),1)
            self.assertTrue(any(x.get('idempotent_lookup')for x in rows))
            self.assertTrue(W.verify_run(rows[0]['runs'][0]['path'])['exact_replay'])
    def test_forged_feature_with_rebound_review_fails(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);c,r=fixture(root);p=W.load(root/'package.json');p['events'][0]['home_form']['rf']=8
            (root/'package.json').write_text(json.dumps(p));review=W.load(r);review['package_sha256']=sha(root/'package.json');r.write_text(json.dumps(review))
            with self.assertRaisesRegex(ValueError,'SOURCE_FEATURE_REBUILD'):W.verify_package(root,c,r)
    def test_contract_review_mismatch_fails(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);c,r=fixture(root);j=W.load(r);j['contract_sha256']='wrong';r.write_text(json.dumps(j))
            with self.assertRaisesRegex(ValueError,'REVIEW_BINDING'):W.verify_package(root,c,r)
    def test_early_review_fails(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);c,r=fixture(root);j=W.load(r);j['reviewed_at_utc']='2000-01-01T00:00:00Z';r.write_text(json.dumps(j))
            with self.assertRaisesRegex(ValueError,'REVIEW_CHRONOLOGY'):W.verify_package(root,c,r)
    def test_corrupted_draw_refused(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);c,r=fixture(root);b=W.run(root,c,r,root/'out');out=Path(b['runs'][0]['path']);(out/'postseason_home_win.npy').write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError,'FROZEN_ARTIFACT'):W.verify_run(out)
    def test_grader_preserves_ineligible_flag(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);c,r=fixture(root);b=W.run(root,c,r,root/'out');f=root/'result.json'
            save_once(f,{'dates':[{'games':[{'gamePk':999,'status':{'abstractGameState':'Final'},'teams':{'home':{'team':{'name':'SD'},'score':4},'away':{'team':{'name':'CHC'},'score':3}}}]}]})
            save_once(root/'result-receipt.json',{'status':'CAPTURED','raw_sha256':sha(f)})
            g=W.grade([b['runs'][0]['path']],f,root/'result-receipt.json',root/'grade.json')
            self.assertEqual(g['rows'][0]['status'],'NOT_GRADE_ELIGIBLE');self.assertEqual(g['scored_forecasts'],0)

if __name__=='__main__':unittest.main()
