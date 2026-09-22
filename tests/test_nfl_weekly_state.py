"""Synthetic acceptance: real fitted QB runtime, fabricated observations, no live state."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from models.nfl.contextual import weekly_state as ws
from models.nfl.contextual import base_features as bf
from models.nfl.contextual.assimilation import advance_states, serialize_states
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest
from models.nfl.contextual.runtime import run, live_features
from pipelines.cards.adapters import nfl

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'data/nfl/contextual_v1'
STAMP = '2026-09-21T23:00:00Z'
TEAMS = 'KC DEN BUF DET ARI ATL BAL CAR CHI CIN CLE DAL GB HOU IND JAX LAC LA LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS'.split()


def source(frame, schedule=False):
    text = frame.to_csv(index=False)
    return {'text': text, 'receipt': {'sha256': hashlib.sha256(text.encode()).hexdigest(),
        'retrieved_at_utc': STAMP, 'source_url': ws.SCHEDULE_URL if schedule else
        'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2026.csv'}}


def fixture():
    games=[]; plays=[]
    for week in range(1,19):
        for pair in range(16):
            if (week==17 and pair==0) or (week==18 and pair!=0): continue
            home,away=TEAMS[pair*2:pair*2+2]
            g={'game_id':f'2026_{week:02d}_{away}_{home}','season':2026,'week':week,'game_type':'REG',
               'home_team':home,'away_team':away,'home_score':7,'away_score':3,
               'home_qb_id':'test-'+home,'away_qb_id':'test-'+away,'gameday':'2026-09-27','gametime':'13:00',
               'home_rest':7,'away_rest':7,'roof':'outdoors','location':'Home','temp':50,'wind':5}
            games.append(g)
            if week>3: continue
            for i,q,clock,h,a,off,epa in [(1,1,600,0,0,home,2+week),(2,2,0,7,0,away,-1),(3,3,900,7,0,home,1),(4,4,0,7,3,away,-2)]:
                plays.append({**{k:g[k] for k in ['game_id','season','week','home_team','away_team']},
                    'play_id':i,'qtr':q,'quarter_seconds_remaining':clock,'game_seconds_remaining':(4-q)*900+clock,
                    'total_home_score':h,'total_away_score':a,'down':1,'play_type':'pass','qb_kneel':0,'qb_spike':0,
                    'no_play':0,'wp':.5,'posteam':off,'defteam':away if off==home else home,'epa':epa,
                    'success':int(epa>0),'yards_gained':10 if epa>0 else 0,'sack':0,'interception':0,'fumble_lost':0,
                    'season_type':'REG','qb_dropback':1,'passer_player_id':'test-'+off})
    return pd.DataFrame(games), pd.DataFrame(plays)


class Weekly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=load_artifact(DATA/'model_packed.json')
        cls.recovered=json.loads((DATA/'recovered_parameters.json').read_text())
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Path(self.temp.name)/'state';self.games,self.pbp=fixture()
        states=serialize_states({t:bf.TeamState() for t in TEAMS})
        seed={'schema':'nfl.reconstructed_week_start_state.v1','season':2026,'week':1,'states':states,
              'state_sha256':digest(states),'base_feature_code_sha256':ws.code_identity()['base_features.py'],
              'source_receipts':[{'source':'SYNTHETIC_TEST_ONLY_NOT_HISTORICAL_RECONSTRUCTION'}]}
        self.schedule=source(self.games,True);self.raw=source(self.pbp)
        self.seed=ws.initialize(self.store,seed,self.schedule,self.model,STAMP)
        self.pin=patch.dict(os.environ,{'NFL_WEEKLY_STATE_SEED_SHA256':self.seed});self.pin.start();self.addCleanup(self.pin.stop)
    def advance(self,parent=None,week=1,schedule=None,raw=None):
        return ws.advance(self.store,parent or self.seed,self.seed,self.model,schedule or self.schedule,raw or self.raw,week,STAMP)
    def load(self,key):return ws.load_verified(self.store,key,self.model,STAMP,self.seed)
    def unchanged_on_error(self, pattern, **kw):
        before={p.name:p.read_bytes() for p in (self.store/'objects').iterdir()};head=(self.store/'HEAD').read_bytes()
        with self.assertRaisesRegex(ValueError,pattern):self.advance(**kw)
        self.assertEqual(head,(self.store/'HEAD').read_bytes());self.assertEqual(before,{p.name:p.read_bytes() for p in (self.store/'objects').iterdir()})
    def test_full_season_pbp_equals_week_only_and_only_scheduled_teams_change(self):
        states={t:bf.TeamState() for t in TEAMS};g=self.games[self.games.week==1]
        a,_=advance_states(states,g,self.pbp);b,_=advance_states(states,g,self.pbp[self.pbp.week==1])
        self.assertEqual(serialize_states(a),serialize_states(b))
        one=g.iloc[:1];a,_=advance_states(states,one,self.pbp)
        self.assertEqual({t for t in states if states[t]!=a[t]}, {'KC','DEN'})
        key=self.advance();self.assertEqual(self.load(key)['team_state'],serialize_states(b))
    def test_truncated_schedule_rejected(self):
        self.unchanged_on_error('FULL_SEASON_SCHEDULE',schedule=source(self.games.iloc[:1],True))
    def test_pending_last_game_rejected(self):
        g=self.games.copy();g.loc[g.game_id=='2026_01_WAS_TEN',['home_score','away_score']]=None
        self.unchanged_on_error('WEEK_INCOMPLETE',schedule=source(g,True))
    def test_identical_retry_noop_and_conflicting_retry_rejected(self):
        key=self.advance();files={p.name:p.read_bytes() for p in (self.store/'objects').iterdir()}
        self.assertEqual(self.advance(),key);self.assertEqual(files,{p.name:p.read_bytes() for p in (self.store/'objects').iterdir()})
        p=self.pbp.copy();p.loc[0,'epa']=77
        self.unchanged_on_error('CONFLICTING_REPLAY',raw=source(p))
        self.unchanged_on_error('NONCONTIGUOUS',parent=key,week=1)
    def test_gap_and_schedule_revision_refused(self):
        self.unchanged_on_error('NONCONTIGUOUS',week=2)
        g=self.games.copy();mask=g.home_team.isin(['KC','BUF']);g.loc[mask,'home_team']=g.loc[mask,'home_team'].map({'KC':'BUF','BUF':'KC'})
        g['game_id']=g.apply(lambda r:f'2026_{r.week:02d}_{r.away_team}_{r.home_team}',axis=1)
        self.unchanged_on_error('SCHEDULE_REVISION',schedule=source(g,True))
    def test_duplicate_missing_nonfinite_pbp_refused(self):
        for p in [pd.concat([self.pbp,self.pbp.iloc[:1]]),self.pbp[self.pbp.game_id!='2026_01_DEN_KC']]:
            self.unchanged_on_error('WEEK_INCOMPLETE',raw=source(p))
        p=self.pbp.copy();p['epa']=p.epa.astype(float);p.loc[0,'epa']=float('inf')
        self.unchanged_on_error('QB_METRICS',raw=source(p))
    def test_late_source_missing_qb_terminal_and_tamper(self):
        s=copy.deepcopy(self.raw);s['receipt']['available_at_utc']='2026-09-22T00:00:00Z'
        self.unchanged_on_error('SOURCE_AFTER_CUTOFF',raw=s)
        self.unchanged_on_error('QB_COLUMNS',raw=source(self.pbp.drop(columns=['qb_dropback'])))
        p=self.pbp.copy();p.loc[(p.week==1)&(p.qtr==4),'game_seconds_remaining']=10
        self.unchanged_on_error('TERMINAL',raw=source(p))
        s=copy.deepcopy(self.raw);s['text']+='x';self.unchanged_on_error('SOURCE_HASH',raw=s)
    def test_qb_retention_once_and_week3_week4_chain(self):
        a=self.advance();b=self.advance(a,2);c=self.advance(b,3)
        before=ws.prior(self.model,2026);state=self.load(c)
        q=next(iter(before['qb_ratings']));self.assertEqual(state['qb_state']['qb_ratings'][q],before['qb_ratings'][q])
        self.assertEqual(state['qb_state']['qb_ratings']['test-KC']['n'],6)
        self.assertEqual(state['completed_week'],3);self.assertEqual(len(state['consumed_game_ids']),48)
        for t in TEAMS:self.assertEqual(state['team_state'][t]['weeks_observed'],3)
    def test_bad_pin_model_and_hashed_state_tamper_refused(self):
        key=self.advance()
        with self.assertRaisesRegex(ValueError,'TRUSTED_SEED'):ws.load_verified(self.store,key,self.model,STAMP,'0'*64)
        model=copy.deepcopy(self.model);model['state']['roles']={}
        with self.assertRaisesRegex(ValueError,'MODEL_BINDING'):ws.load_verified(self.store,key,model,STAMP,self.seed)
        n=ws._get(self.store,key);n['team_state']['KC']['off_epa']+=1;bad=ws._put(self.store,n)
        with self.assertRaisesRegex(ValueError,'REPLAY_MISMATCH'):self.load(bad)
    def test_concurrent_duplicate_publish_and_failed_commit(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids=list(pool.map(lambda _:self.advance(),range(2)))
        self.assertEqual(ids[0],ids[1])
        head=(self.store/'HEAD').read_bytes()
        with patch.object(ws,'_publish',side_effect=OSError('injected crash')):
            with self.assertRaisesRegex(OSError,'injected'):self.advance(ids[0],2)
        self.assertEqual(head,(self.store/'HEAD').read_bytes())
        tip=self.advance(ids[0],2);self.assertEqual(self.load(tip)['completed_week'],2)
    def test_prior_final_correction_refused(self):
        first=self.advance();g=self.games.copy();g.loc[g.game_id=='2026_01_DEN_KC','home_score']=10
        self.unchanged_on_error('CONSUMED_FINAL_REVISION',parent=first,week=2,schedule=source(g,True))
    def test_overtime_terminal_marker_preserves_support(self):
        p=self.pbp.copy();mask=(p.game_id=='2026_01_DEN_KC')&(p.qtr==4)
        p.loc[mask,'qtr']=5;p.loc[mask,'game_seconds_remaining']=94;p.loc[mask,'desc']='END GAME'
        self.assertEqual(self.load(self.advance(raw=source(p)))['completed_week'],1)
    def test_integrated_cli_explicit_state_binding(self):
        import subprocess,sys
        a=self.advance();b=self.advance(a,2);base,c,e=self.event_packet(b)
        package={'covered_dates':[e['gameday']],'captured_at_utc':STAMP,'events':[e],
                 'model_path':str(DATA/'model_packed.json'),'model_digest':digest(self.model),
                 'recovered_parameters_path':str(DATA/'recovered_parameters.json'),
                 'event_inputs':{e['event_id']:{'base':base,'context':c}},'source_fetches':[]}
        path=Path(self.temp.name)/'event.json';path.write_text(json.dumps(package,allow_nan=False))
        output=Path(self.temp.name)/'forecast'
        env={**os.environ,'NFL_CONTEXT_PACKAGE':str(path)}
        # Freeze only the subprocess clock: fixed historical fixtures must not
        # expire when CI runs after their synthetic kickoff. No model is mocked.
        runner="import datetime,runpy; from unittest.mock import patch\nclass Clock(datetime.datetime):\n @classmethod\n def now(cls,tz=None):\n  value=cls(2026,9,22,tzinfo=datetime.timezone.utc)\n  return value.astimezone(tz) if tz else value.replace(tzinfo=None)\nwith patch('datetime.datetime',Clock):\n runpy.run_path("+repr(str(ROOT/'scripts/run_nfl_integrated.py'))+",run_name='__main__')"
        r=subprocess.run([sys.executable,'-c',runner,'--date',e['gameday'],
                          '--output',str(output),'--simulations','1000','--weekly-state-store',str(self.store),
                          '--weekly-state-id',b],env=env,text=True,capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr)
        result=json.loads((output/e['event_id']/'forecast.json').read_text())
        self.assertEqual(result['selected_arm'],'qb');self.assertEqual(result['assimilation']['state_id'],b)
        self.assertFalse(result['action_authority'])
    def test_bye_teams_unchanged(self):
        # A supported bye week has no hardcoded 16-game requirement.
        seed=ws._get(self.store,self.seed);parent=copy.deepcopy(seed);parent['completed_week']=16
        parent['consumed_game_ids']=self.games[self.games.week<=16].game_id.tolist()
        g=self.games[self.games.week==17];p=self.pbp[self.pbp.week==1].copy();p['week']=17;p['game_id']=p.game_id.str.replace('_01_','_17_');p=p[p.game_id.isin(g.game_id)]
        result=ws._reduce(parent,seed,self.schedule,source(p),17,STAMP)
        self.assertEqual(result['team_state']['KC'],parent['team_state']['KC'])
        self.assertEqual(result['team_state']['DEN'],parent['team_state']['DEN'])
    def event_packet(self,key,week=3):
        state=self.load(key);g=self.games[(self.games.week==week)&(self.games.home_team=='KC')].iloc[0].to_dict()
        g['home_score']=None;g['away_score']=None
        base=bf._feature_row(pd.Series(g),bf.TeamState(**state['team_state']['KC']),bf.TeamState(**state['team_state']['DEN']))
        base={k:None if pd.isna(v) else v for k,v in base.items()}
        event={'event_id':g['game_id'],'home_team':'KC','away_team':'DEN','gameday':'2026-09-27','gametime':'13:00','location':'Home','start_time_utc':'2026-09-27T17:00:00Z'}
        context={'weekly_state':{'store':str(self.store),'state_id':key},'personnel':{'source':'synthetic','source_sha256':'test','retrieved_at_utc':STAMP,'available_by_utc':STAMP,'event_id':g['game_id'],
                  'state':{'quarterbacks':{'KC':{'id':'test-KC'},'DEN':{'id':'test-DEN'}},'injury_observations':[]}}}
        return base,context,event
    def test_selected_qb_canonical_adapter_consumes_state_and_100k_replays(self):
        a=self.advance();b=self.advance(a,2);base,c,e=self.event_packet(b)
        ctx={'model':self.model,'recovered':self.recovered,'cutoff':STAMP,'package':{'event_inputs':{e['event_id']:{'base':base,'context':c}},'source_fetches':[]}}
        out=nfl.forecast_event(e,ctx,100000);again=nfl.forecast_event(e,ctx,100000)
        r=out['diagnostics'];self.assertEqual(r['selected_arm'],'qb');self.assertEqual(r['winner_simulation'],again['diagnostics']['winner_simulation'])
        self.assertEqual(r['winner_simulation']['count'],100000);self.assertEqual(r['assimilation']['state_id'],b)
        self.assertFalse(r['action_authority']);self.assertEqual(r['prediction'],r['arms']['qb']['prediction'])
        self.assertEqual(r['assimilation']['qb_state_sha256'],digest(self.load(b)['qb_state']))
        wrong=copy.deepcopy(base);wrong['epa_matchup_edge']+=1
        with self.assertRaisesRegex(ValueError,'NOT_ACTIVE_IN_RUN'):run(self.model,self.recovered,wrong,c,e,STAMP,100)
        c['weekly_state']['state_id']=a
        with self.assertRaisesRegex(ValueError,'WRONG_WEEK'):live_features(self.model,self.recovered,base,c,e,STAMP)
        with self.assertRaisesRegex(ValueError,'WEEKLY_STATE_EVIDENCE'):run(self.model,self.recovered,base,{},e,STAMP,100)

if __name__=='__main__':unittest.main()
