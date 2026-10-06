import copy,json,tempfile,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from research import mlb_postseason_context as C
from scripts.recovery_capture import write_once
from scripts.evaluate_mlb_postseason_context import initial_order,metric,bootstrap


def player(pid=1,outs=15):
    stat={'inningsPitched':str(outs//3)+'.'+str(outs%3),'outs':outs,'earnedRuns':2,'battersFaced':22,'strikeOuts':5,'baseOnBalls':2,'gamesStarted':1,'numberOfPitches':80}
    return {'id':pid,'stats':[{'group':{'displayName':'pitching'},'type':{'displayName':'gameLog'},'splits':[{'player':{'id':pid},'gameType':'R','date':'2025-09-28','game':{'gamePk':1},'stat':stat}]}]}


def context():
    return {s:{'workload':{'mean':5.4,'sd':1.3,'cap':8},'bulk':None,'lineup':{'factor':1},'bullpen':{'rate':4.2}} for s in ('home','away')}


def event():
    e={'game_type':'D','slate_date':'2025-10-06','through_date':'2025-10-05','home_team':'H','away_team':'A','park_factor':1}
    for s in ('home','away'):e[s+'_form']={'rf':4.45,'ra':4.45,'games':162};e['sp_'+s]={'era':4.2,'gs':30,'k':22,'bb':8.5,'observed_game_ids':['1']}
    return e


class ContextTests(unittest.TestCase):
    def test_prior_date_filter_and_out_accounting(self):
        p=player(1,14);future=copy.deepcopy(p['stats'][0]['splits'][0]);future['date']='2025-10-06';future['game']['gamePk']=2;p['stats'][0]['splits'].append(future)
        self.assertEqual(len(C.pitching(p,'2025-10-06')),1)
        self.assertAlmostEqual(C.workload(p,'2025-10-06')['mean'],(14/3+3*5.4)/4)
        p['stats'][0]['splits'][0]['stat']['inningsPitched']='4.3'
        with self.assertRaises(ValueError):C.pitching(p,'2025-10-06')
    def test_duplicate_or_wrong_player_rejected(self):
        p=player();p['stats'][0]['splits']*=2
        with self.assertRaises(ValueError):C.pitching(p,'2025-10-06')
        p=player();p['stats'][0]['splits'][0]['player']['id']=2
        with self.assertRaises(ValueError):C.pitching(p,'2025-10-06')
    def test_opener_requires_bulk_and_cap_units(self):
        p=player()
        with self.assertRaises(ValueError):C.workload(p,'2025-10-06',{'role':'OPENER','expected_innings':1})
        w=C.workload(p,'2025-10-06',{'role':'STARTER','pitch_cap':40});self.assertEqual(w['cap'],2.5)
    def test_missing_and_unavailable_lineup(self):
        with self.assertRaises(ValueError):C.lineup_factor([],{'roster':[]},{},'2025-10-06',set())
        roster={'roster':[{'person':{'id':i},'status':{'code':'A'}} for i in range(9)]}
        with self.assertRaises(ValueError):C.lineup_factor(list(range(9)),roster,{},'2025-10-06',{1})
    def test_initial_order_excludes_substitutes(self):
        b={'players':{'a':{'person':{'id':1},'battingOrder':'100'},'b':{'person':{'id':2},'battingOrder':'101'}}}
        self.assertEqual(initial_order(b),[1])
    def test_bullpen_fatigue_and_ineligible_exclusion(self):
        a,b=player(1),player(2)
        for p in (a,b):p['stats'][0]['splits'][0]['stat']['gamesStarted']=0
        a['stats'][0]['splits'][0]['date']='2025-10-05'
        roster={'roster':[{'person':{'id':i},'status':{'code':'A'},'position':{'abbreviation':'P'}} for i in (1,2)]}
        z=C.bullpen(roster,{1:a,2:b},'2025-10-06',3,set());self.assertLess(z['members'][0]['weight'],z['members'][1]['weight'])
        self.assertEqual([x['id'] for x in C.bullpen(roster,{1:a,2:b},'2025-10-06',3,{1})['members']],[2])
    def test_replay_and_independent_arm_effects(self):
        e=event();c=context();r,d=C.simulate(e,c,3,100000,42);rr,dd=C.simulate(e,c,3,100000,42);self.assertEqual(r,rr)
        for k in d:self.assertTrue(np.array_equal(d[k],dd[k]))
        c['home']['lineup']['factor']=1.2;better,_=C.simulate(e,c,3,100000,42);self.assertGreater(better['home_win_probability'],r['home_win_probability'])
        c=context();c['home']['bullpen']['rate']=8;bad,_=C.simulate(e,c,3,100000,42);self.assertLess(bad['home_win_probability'],r['home_win_probability'])
    def test_stage_missingness_is_not_neutral_fallback(self):
        c=context();c['home']['lineup']=None
        C.simulate(event(),c,1,100,7)
        with self.assertRaises(TypeError):C.simulate(event(),c,2,100,7)
    def test_invalid_numeric_and_unsupported_arm(self):
        for x in (True,float('nan'),float('inf')):
            with self.assertRaises(ValueError):C.number(x)
        with self.assertRaises(ValueError):C.simulate(event(),context(),99,100,1)
    def test_calibration_identity_and_draws(self):
        self.assertAlmostEqual(C.calibrate(.7,1),.7);self.assertLess(C.calibrate(.7,.5),.7)
        r,d=C.simulate(event(),context(),4,100000,7,.5);self.assertIn('home_win_calibrated',d);self.assertEqual(r['model_id'],C.ARMS[4]);self.assertIsNone(r['score_total_runline_outputs'])
    def test_atomic_duplicate_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'raw';body=b'x'*1000000
            with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:write_once(path,body),range(20)))
            self.assertEqual(path.read_bytes(),body)
            with self.assertRaises(RuntimeError):write_once(path,b'changed')
            self.assertEqual(path.read_bytes(),body)
    def test_scoring_and_paired_identity(self):
        rows=[{'a':.8,'b':.8,'home_win':1,'series_id':'s1'},{'a':.2,'b':.2,'home_win':0,'series_id':'s2'}]
        self.assertAlmostEqual(metric(rows,'a')['binary_brier'],.04)
        self.assertEqual(bootstrap(rows,'a','b',20)['ci95'],[0,0])

if __name__=='__main__':unittest.main()
