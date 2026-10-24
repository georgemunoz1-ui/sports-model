"""Synthetic failure fixtures. Do not report these as predictive validation."""
import copy,datetime as dt,json,tempfile,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from research.cfb_lineage.core import *
from research.cfb_lineage.registry import *
from research.cfb_lineage.catalogue import definitions
from research.cfb_lineage.schemas import SCHEMAS,validate

class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
        self.before=(utc(now())-dt.timedelta(days=2)).isoformat()
        self.games=[dict(event_id='cfb_test_'+str(i),season=2026,week=1,home_id='H'+str(i),away_id='A'+str(i),kickoff=self.before,
            neutral_site=False,home_division='FBS',away_division='FBS',status='FINAL',home_score=21,away_score=14) for i in range(2)]
        self.rows=[]
        for g in self.games:
            for j in range(2):
                self.rows.append(dict(event_id=g['event_id'],play_id=str(j),sequence=j,season=2026,week=1,home_id=g['home_id'],away_id=g['away_id'],
                    posteam=g['home_id'] if j==0 else g['away_id'],defteam=g['away_id'] if j==0 else g['home_id'],eligible=True,
                    dropback=True,player_id='QB'+g['home_id'] if j==0 else 'QB'+g['away_id'],epa=1. if j==0 else -.5,
                    home_score=21,away_score=14,available_at=self.before))
        self.schedule=self.enroll(self.games,'week1');self.pbp=self.data(self.rows);self.parent=seed_state(self.store,'fixture',2026)
    def data(self,rows,family='cfb_fixture_pbp'):
        raw=self.store.source(canonical(rows),family,'fixture://synthetic',scope='SYNTHETIC_TEST')
        return self.store.dataset(rows,raw,family,'synthetic-adapter-v1')
    def enroll(self,games,key):
        d=self.data(games,'cfb_fixture_schedule');return publish_schedule(self.store,d,key,expected_scope='FBS_VS_FBS')
    def update(self,**kw):
        args=dict(parent_hash=self.parent,registry_id='week1',requested_ids=[r['event_id'] for r in self.games],pbp_hash=self.pbp,cutoff=now())
        args.update(kw);return update_week(self.store,**args)

class GraphTests(Fixture):
    def test_raw_bytes_are_hash_verified(self):
        raw=self.store.source(b'abc','cfb_fixture','fixture://raw',scope='SYNTHETIC_TEST');n=self.store.node(raw)
        (self.store.objects/n['payload']['raw_hash']).write_bytes(b'bad')
        with self.assertRaisesRegex(GateError,'HASH_MISMATCH'):self.store.verify(raw)
    def test_missing_parent_refused(self):
        with self.assertRaisesRegex(GateError,'MISSING_ARTIFACT'):self.store.put('x',{}, {'source':'a'*64})
    def test_cross_sport_parent_refused(self):
        bad=self.store.blob(canonical({'sport':'NFL','kind':'model','parents':{},'payload':{}}))
        with self.assertRaisesRegex(GateError,'CROSS_SPORT'):self.store.put('model',{}, {'x':bad})
    def test_semantic_identifier_cannot_be_rewritten(self):
        a=self.store.put('x',{'value':1});b=self.store.put('x',{'value':2});self.store.bind('x',a)
        with self.assertRaisesRegex(GateError,'IDENTIFIER_CONFLICT'):self.store.bind('x',b)
    def test_same_binding_is_idempotent(self):
        a=self.store.put('x',{});self.store.bind('x',a);self.store.bind('x',a);self.assertEqual(self.store.resolve('x'),a)
    def test_blob_hash_path_traversal_refused(self):
        with self.assertRaisesRegex(GateError,'INVALID_ARTIFACT'):self.store.bytes('../bad')
    def test_descendant_verifies_all_ancestors(self):
        r=self.update();proof=self.store.verify(r['child_state_hash']);self.assertGreaterEqual(proof['node_count'],6)
    def test_failed_validation_never_changes_head(self):
        p=self.store.put('canonical_dataset',{'rows':[],'available_at':self.before,'source_family':'cfb_fixture_pbp'})
        with self.assertRaises(GateError):self.update(pbp_hash=p)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT hash FROM heads').fetchone()[0],self.parent)

class TransitionTests(Fixture):
    def test_normal_complete_week_publishes(self):
        r=self.update();s=self.store.node(r['child_state_hash'])['payload'];self.assertEqual(s['completed_week'],1);self.assertEqual(len(s['processed_games']),2)
    def test_truncated_schedule_rejected(self):
        with self.assertRaisesRegex(GateError,'COVERAGE_MISMATCH'):self.update(requested_ids=[self.games[0]['event_id']])
    def test_publisher_cannot_truncate_raw_census(self):
        raw=self.store.source(canonical(self.games),'cfb_fixture_schedule','fixture://census',scope='SYNTHETIC_TEST')
        d=self.store.dataset(self.games[:1],raw,'cfb_fixture_schedule','x')
        with self.assertRaisesRegex(GateError,'RAW_CENSUS'):publish_schedule(self.store,d,'truncated',expected_scope='FBS_VS_FBS')
    def test_incomplete_week_withheld_not_released(self):
        g=copy.deepcopy(self.games);g[1]['status']='PENDING';g[1]['home_score']=g[1]['away_score']=None;self.enroll(g,'pending')
        r=self.update(registry_id='pending');self.assertEqual(r['status'],'WITHHELD');self.assertFalse(r['state_published'])
    def test_postponed_week_withheld(self):
        g=copy.deepcopy(self.games);g[1]['status']='POSTPONED';self.enroll(g,'pending');self.assertEqual(self.update(registry_id='pending')['status'],'WITHHELD')
    def test_unregistered_schedule_refused(self):
        with self.assertRaisesRegex(GateError,'UNREGISTERED'):self.update(registry_id='absent')
    def test_duplicate_request_ids_refused(self):
        with self.assertRaisesRegex(GateError,'COVERAGE'):self.update(requested_ids=[self.games[0]['event_id']]*2)
    def test_out_of_week_game_rejected_before_aggregate(self):
        p=copy.deepcopy(self.rows);p.append({**p[0],'event_id':'unexpected'})
        with self.assertRaisesRegex(GateError,'OUT_OF_SCOPE'):self.update(pbp_hash=self.data(p))
    def test_pbp_week_mismatch(self):
        p=copy.deepcopy(self.rows);p[0]['week']=2
        with self.assertRaisesRegex(GateError,'WEEK_BINDING'):self.update(pbp_hash=self.data(p))
    def test_duplicate_play(self):
        with self.assertRaisesRegex(GateError,'DUPLICATE_PLAY'):self.update(pbp_hash=self.data(self.rows+self.rows[:1]))
    def test_duplicate_sequence(self):
        p=copy.deepcopy(self.rows);p[1]['sequence']=0
        with self.assertRaisesRegex(GateError,'SEQUENCE'):self.update(pbp_hash=self.data(p))
    def test_future_row_rejected(self):
        p=copy.deepcopy(self.rows);p[0]['available_at']='2099-01-01T00:00:00Z'
        with self.assertRaisesRegex(GateError,'AFTER_CUTOFF'):self.update(pbp_hash=self.data(p))
    def test_final_score_mismatch(self):
        p=copy.deepcopy(self.rows);p[1]['home_score']=20
        with self.assertRaisesRegex(GateError,'SCORE_MISMATCH'):self.update(pbp_hash=self.data(p))
    def test_home_away_mismatch(self):
        p=copy.deepcopy(self.rows);p[0]['home_id']='wrong'
        with self.assertRaisesRegex(GateError,'TEAM_BINDING'):self.update(pbp_hash=self.data(p))
    def test_missing_game(self):
        with self.assertRaisesRegex(GateError,'MISSING_COMPLETED'):self.update(pbp_hash=self.data(self.rows[:2]))
    def test_exact_transition_replay_noop(self):
        a=self.update();b=self.update();self.assertEqual(a['child_state_hash'],b['child_state_hash']);self.assertEqual(b['status'],'REPLAY_NOOP')
    def test_repeat_game_against_child_rejected(self):
        a=self.update()
        with self.assertRaisesRegex(GateError,'DUPLICATE_GAME_STATE'):self.update(parent_hash=a['child_state_hash'])
    def test_revision_against_child_rejected(self):
        a=self.update();r=copy.deepcopy(self.rows);r[0]['epa']=9
        with self.assertRaisesRegex(GateError,'SOURCE_REVISION'):self.update(parent_hash=a['child_state_hash'],pbp_hash=self.data(r))
    def test_receipt_time_not_new_evidence(self):
        a=self.update();r=copy.deepcopy(self.rows)
        for x in r:x['available_at']=now()
        b=self.update(pbp_hash=self.data(r));self.assertEqual(a['child_state_hash'],b['child_state_hash'])
    def test_concurrent_identical_transition_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:r=list(pool.map(lambda _:self.update(),range(4)))
        self.assertEqual(sum(x['state_published'] for x in r),1);self.assertEqual(len({x['child_state_hash'] for x in r}),1)
    def test_generic_second_week_team_and_qb_chain(self):
        one=self.update();g=copy.deepcopy(self.games);p=copy.deepcopy(self.rows)
        for x in g:x['week']=2;x['event_id']+='w2'
        for x in p:x['week']=2;x['event_id']+='w2'
        self.enroll(g,'week2');two=self.update(parent_hash=one['child_state_hash'],registry_id='week2',requested_ids=[x['event_id'] for x in g],pbp_hash=self.data(p))
        s=self.store.node(two['child_state_hash'])['payload'];self.assertEqual(s['completed_week'],2);self.assertEqual(s['qbs']['QBH0']['epa_sum'],2.);self.assertEqual(len(s['processed_player_games']),8)
    def test_fcs_not_silently_pooled(self):
        g=copy.deepcopy(self.games);g[0]['away_division']='FCS'
        with self.assertRaisesRegex(GateError,'BRIDGE'):self.enroll(g,'cross')
    def test_qb_missing_id_refused(self):
        p=copy.deepcopy(self.rows);p[0]['player_id']=None
        with self.assertRaisesRegex(GateError,'QB_ID'):self.update(pbp_hash=self.data(p))
    def test_nonfinite_epa_refused(self):
        p=copy.deepcopy(self.rows);p[0]['epa']=float('inf')
        with self.assertRaises(ValueError):self.data(p)
    def test_missing_epa_not_zero_observation(self):
        p=copy.deepcopy(self.rows);p[0]['epa']=None;r=self.update(pbp_hash=self.data(p));s=self.store.node(r['child_state_hash'])['payload']
        self.assertEqual(s['teams']['H0']['off_n'],0);self.assertEqual(s['qbs']['QBH0']['observed_dropbacks'],0)
    def test_new_family_requires_new_lineage(self):
        one=self.update();g=copy.deepcopy(self.games);p=copy.deepcopy(self.rows)
        for x in g:x['week']=2;x['event_id']+='w2'
        for x in p:x['week']=2;x['event_id']+='w2'
        self.enroll(g,'week2')
        with self.assertRaisesRegex(GateError,'FAMILY_CHANGED'):self.update(parent_hash=one['child_state_hash'],registry_id='week2',requested_ids=[x['event_id'] for x in g],pbp_hash=self.data(p,'espn_cfb_pbp'))

class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.d=definitions()[10];t=(utc(now())-dt.timedelta(hours=1)).isoformat()
        self.source={'source_family':self.d['source_family'],'raw_hash':'a'*64,'available_at':t,'retrieved_at':t,'upstream_model_hash':'b'*64}
        self.row={'feature_id':self.d['feature_id'],'feature_definition_hash':self.d['definition_hash'],'transform_version':self.d['transform_version'],
          'source_content_hash':'a'*64,'forecast_cutoff':now(),'available_at':t,'source_max_event_time':t,'home_away':'HOME','team_id':'H','opponent_team_id':'A',
          'is_missing':False,'missingness_reason':None,'feature_value_raw':.1,'feature_value_model':.1,'numerator':2.,'denominator':20.,'upstream_model_hash':'b'*64}
    def check(self,**kw):return validate_observation(self.d,self.row,self.source,self.row['forecast_cutoff'],**kw)
    def test_definition_count_and_unique(self):self.assertEqual(len(definitions()),38);self.assertEqual(len({d['feature_id'] for d in definitions()}),38)
    def test_no_candidate_auto_active(self):self.assertTrue(all(d['status']=='REGISTERED' for d in definitions()))
    def test_valid_observation(self):self.check(upstream_model_required=True)
    def test_late_source_not_imputed(self):
        self.row['available_at']='2099-01-01T00:00:00Z';self.row['is_missing']=True;self.row['feature_value_raw']=None
        with self.assertRaisesRegex(GateError,'AFTER_CUTOFF'):self.check()
    def test_definition_version_tampering(self):
        self.d['unit']='PERCENT'
        with self.assertRaisesRegex(GateError,'DEFINITION_HASH'):self.check()
    def test_family_substitution_rejected(self):
        self.source['source_family']='espn_cfb_pbp'
        with self.assertRaisesRegex(GateError,'FAMILY'):self.check()
    def test_zero_denominator(self):
        self.row['denominator']=0
        with self.assertRaisesRegex(GateError,'DENOMINATOR'):self.check()
    def test_inconsistent_rate(self):
        self.row['numerator']=3
        with self.assertRaisesRegex(GateError,'NUMERATOR'):self.check()
    def test_missing_model_generation(self):
        self.row.pop('upstream_model_hash')
        with self.assertRaisesRegex(GateError,'GENERATION'):self.check(upstream_model_required=True)
    def test_silent_imputation_rejected(self):
        self.row.update(is_missing=True,feature_value_raw=None,missingness_reason='missing',feature_value_model=0)
        with self.assertRaisesRegex(GateError,'IMPUTATION'):self.check()
    def test_unit_fraction_not_percent(self):
        self.d=definitions()[12];self.row.update(feature_id=self.d['feature_id'],feature_definition_hash=self.d['definition_hash'],transform_version=self.d['transform_version'],feature_value_raw=65.,feature_value_model=65.)
        with self.assertRaisesRegex(GateError,'UNIT'):self.check()
    def test_no_force_active_from_coefficient(self):
        self.assertFalse(active_eligible({'validation_status':'PASS','as_of_eligible':True,'is_missing':False},{'path_status':'FITTED','member_weight':1},{'decision':'SHADOW'}))
    def test_defensive_allowed_sign_monotone(self):
        old=matchup_epa_score(.2,.1,.1,.1);self.assertGreater(matchup_epa_score(.2,.3,.1,.1),old);self.assertLess(matchup_epa_score(.2,.1,.1,.3),old)
    def test_elo_week_query_retained(self):self.assertEqual(rating_request('elo',2026,2)['query']['week'],2)
    def test_srs_week_query_not_invented(self):
        with self.assertRaisesRegex(GateError,'NO_WEEK_QUERY'):rating_request('srs',2026,2)
    def test_market_feature_rejected(self):
        d=dict(self.d);d['source_columns']=['vegas_wp']
        with self.assertRaisesRegex(GateError,'MARKET'):seal_definition(d)
    def test_nfl_definition_rejected(self):
        d=dict(self.d);d['sport']='NFL'
        with self.assertRaisesRegex(GateError,'CROSS_SPORT'):seal_definition(d)
    def test_ten_contracts_syntax_valid(self):
        from jsonschema import Draft202012Validator
        self.assertEqual(len(SCHEMAS),10)
        for s in SCHEMAS.values():Draft202012Validator.check_schema(s)
    def test_unknown_contract_rejected(self):
        with self.assertRaisesRegex(GateError,'UNKNOWN'):validate('bogus',{})
    def test_contract_wrong_sport_rejected(self):
        from jsonschema import ValidationError
        with self.assertRaises(ValidationError):validate('cfb_schedule_contract_v1',{'sport':'NFL','schema_version':1})

if __name__=='__main__':unittest.main()
