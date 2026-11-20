"""Personnel credit must match the exact model, event, source time and simulation inputs."""

from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase

from research.personnel_mlb import MODEL_ID, PITCHER_CODE, SOURCE, pitcher_inputs
from sports.rosters import digest


class PitcherEvidence(TestCase):
    def setUp(self):
        self.cutoff = '2026-09-22T21:39:00Z'
        self.event = {'event_id':'MLB:123', 'slate_date':'2026-09-22', 'start_time_utc':'2026-09-22T23:05:00Z',
                      'away_team':'TB', 'home_team':'NYY', 'away_pitcher_id':1, 'home_pitcher_id':2,
                      'away_starter':'Test Away', 'home_starter':'Test Home', 'park_factor':1.1}
        profile = {'era':3.75, 'gs':1, 'k':20, 'bb':7, 'observed_game_ids':['111']}
        urls = [SOURCE+'schedule?sportId=1&date=2026-09-22&hydrate=probablePitcher,linescore,venue']
        urls += [f'{SOURCE}people/{pid}/stats?stats=gameLog&group=pitching&season=2026' for pid in (1,2)]
        self.package = {'schema':'sports.current_research_package.v1', 'league':'mlb', 'model_id':MODEL_ID,
                        'action_authority':False, 'code_pins':dict(PITCHER_CODE), 'ttl_hours':6,
                        'captured_at_utc':self.cutoff, 'training_cutoff_utc':self.cutoff,
                        'source_fetches':[{'source':url, 'sha256':'a'*64, 'fetched_at_utc':self.cutoff} for url in urls],
                        'data_grade':'OFFICIAL_SEASON_CENSUS_AND_CURRENT_PITCHER_LOGS', 'events':[deepcopy(self.event)],
                        'starter_state':{'1':dict(profile), '2':dict(profile, era=4.22)}, 'team_state':{'TB':{}, 'NYY':{}}}

    def bind(self):
        p = self.package
        p['model_sha256'] = digest({'pins':p['code_pins'], 'teams':p['team_state'], 'starters':p['starter_state']})
        self.evidence = SimpleNamespace(mlb_package=p, mlb_package_sha256=digest(p))
        e = p['events'][0]
        snap = {'sp_away':p['starter_state'][str(e['away_pitcher_id'])], 'sp_home':p['starter_state'][str(e['home_pitcher_id'])],
                'away_form':p['team_state']['TB'], 'home_form':p['team_state']['NYY'], 'park_factor':e['park_factor'],
                'event_id':e['event_id'], 'package_sha256':self.evidence.mlb_package_sha256,
                'cutoff':self.cutoff, 'model_id':MODEL_ID, 'n':1000}
        h = digest(snap)
        self.forecast = {'model_id':MODEL_ID, 'action_authority':False, 'model_input_snapshot':deepcopy(snap),
                         'input_snapshot_hash':h, 'model_state_config_hash':p['model_sha256'],
                         'simulation':{'count':1000, 'seed':int(h[:16],16)},
                         'diagnostics':{'starter_status':'OFFICIAL_PROBABLE_NOT_CONFIRMED'}}

    def roles(self):
        return pitcher_inputs(self.event, self.cutoff, self.forecast, self.evidence)

    def test_known_starters(self):
        self.bind()
        self.assertEqual({t:r['player_id'] for t,r in self.roles().items()}, {'TB':'1','NYY':'2'})
        self.assertEqual(self.roles()['NYY']['assignment_status'],'OFFICIAL_PROBABLE_NOT_CONFIRMED')

    def test_unknown_profile_does_not_erase_opponent(self):
        self.package['starter_state']['1'] = {'treatment':'FROZEN_V13_LEAGUE_PRIOR_UNKNOWN_STARTER'}
        self.bind()
        self.assertEqual(set(self.roles()), {'NYY'})

    def test_wrong_hand_and_incoming_source(self):
        self.bind()
        self.forecast['model_input_snapshot']['sp_away'] = self.forecast['model_input_snapshot']['sp_home']
        self.assertFalse(self.roles())
        self.package['source_fetches'][0]['fetched_at_utc'] = '2026-09-22T21:40:00Z'
        self.bind()
        self.assertFalse(self.roles())

    def test_cross_event_clock_and_fingerprint(self):
        self.bind()
        for field, value in [('start_time_utc',self.cutoff), ('event_id','MLB:999'), ('home_pitcher_id',1), ('home_team','BOS')]:
            with self.subTest(field=field):
                self.assertFalse(pitcher_inputs(dict(self.event, **{field:value}), self.cutoff, self.forecast, self.evidence))
        self.evidence.mlb_package_sha256 = 'b'*64
        self.assertFalse(self.roles())
        self.package['code_pins']['models/current/mlb.py'] = 'b'*64
        self.bind()
        self.assertFalse(self.roles())

    def test_missing_card_or_unrelated_model(self):
        self.bind()
        for row in (None, {}, dict(self.forecast,model_id='mlb.postseason.v13')):
            self.assertFalse(pitcher_inputs(self.event,self.cutoff,row,self.evidence))
