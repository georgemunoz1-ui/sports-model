"""Independent semantic fixtures; synthetic inputs do not validate forecasts."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from models.common.discrete_research import digest
from models.current.baseline import FEATURES, IDS
from models.nhl.context_controls import goalie_context, load_goalie_reports, settlement_scores
from research.nhl_context import shadow_from_card, ROOT

CUTOFF = '2026-10-30T18:00:00Z'
EVENT = {'event_id': 'NHL:fixture', 'home_id': 'home', 'away_id': 'away',
         'home_team': 'Home', 'away_team': 'Away', 'start_time_utc': '2026-10-30T23:00:00Z',
         'neutral_site': False}


def goalie(team='home', status='PROJECTED', player='g1'):
    return dict(event_id=EVENT['event_id'], team_id=team, player_id=player, status=status,
                observed_at_utc='2026-10-30T17:00:00Z', retrieved_at_utc='2026-10-30T17:05:00Z',
                source_url='https://example.test/fixture', source_sha256='a'*64,
                source_record_binding='VERIFIED_RAW_NORMALIZED_RECORD')


class GoalieTests(unittest.TestCase):
    def test_missing_stays_unknown_without_probability(self):
        result = goalie_context(EVENT, [], cutoff_utc=CUTOFF)
        for side in result['per_side'].values():
            self.assertEqual(side['status'], 'UNKNOWN')
            self.assertIsNone(side['player_id'])
            self.assertIsNone(side['scenario_weights'])
        self.assertFalse(result['numerically_used'])

    def test_projection_never_becomes_confirmation(self):
        r = goalie_context(EVENT, [goalie()], cutoff_utc=CUTOFF)
        self.assertEqual(r['per_side']['home']['status'], 'PROJECTED')
        self.assertFalse(r['per_side']['home']['adjustment_applied'])

    def test_explicit_confirmation_same_player(self):
        r = goalie_context(EVENT, [goalie(), goalie(status='CONFIRMED')], cutoff_utc=CUTOFF)
        self.assertEqual(r['per_side']['home']['status'], 'CONFIRMED')
        self.assertEqual(r['personnel_transform'], 'FITTED_TRANSFORM_REQUIRED')

    def test_conflicting_player_reports_not_latest_wins(self):
        b = goalie(status='CONFIRMED', player='g2')
        b['observed_at_utc'] = '2026-10-30T17:03:00Z'
        r = goalie_context(EVENT, [goalie(), b], cutoff_utc=CUTOFF)
        self.assertEqual(r['per_side']['home']['status'], 'UNKNOWN')
        self.assertIsNone(r['per_side']['home']['player_id'])
        self.assertIn('CONFLICTING_GOALIE_REPORTS', r['per_side']['home']['blocking_reasons'])

    def test_invalid_source_or_identity_refused(self):
        bad_fields = [('status', 'confirmed'), ('status', True), ('team_id', 'wrong'),
                      ('event_id', 'NHL:other'), ('player_id', ''), ('source_sha256', 'x'),
                      ('source_record_binding', 'PASS'), ('retrieved_at_utc', '2026-10-30T19:00:00Z'),
                      ('observed_at_utc', '2026-10-30T18:01:00Z'), ('observed_at_utc', '2026-10-30T17:00:00')]
        for key, value in bad_fields:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                r = goalie(); r[key] = value
                goalie_context(EVENT, [r], cutoff_utc=CUTOFF)
        with self.assertRaises(ValueError):
            goalie_context(EVENT, [goalie(status='UNKNOWN')], cutoff_utc=CUTOFF)

    def test_refetched_old_report_does_not_restore_freshness(self):
        r = goalie(status="CONFIRMED"); r["observed_at_utc"] = "2026-10-28T17:00:00Z"
        result = goalie_context(EVENT, [r], cutoff_utc=CUTOFF)
        self.assertEqual(result["per_side"]["home"]["status"], "UNKNOWN")
        self.assertIn("GOALIE_REPORT_STALE", result["per_side"]["home"]["blocking_reasons"])
        for age in [True, 0, -1, float("inf")]:
            with self.assertRaises(ValueError):
                goalie_context(EVENT, [], cutoff_utc=CUTOFF, max_age_hours=age)

    def test_raw_record_binding_not_packet_claim(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            row = {k: v for k, v in goalie().items() if k in {'event_id','team_id','player_id','status','observed_at_utc'}}
            raw = json.dumps({'schema':'sports.nhl_goalie_normalized_source.v1','reports':[row]}).encode()
            (root/'source.json').write_bytes(raw)
            receipt = {'raw_path':'source.json','source_sha256':hashlib.sha256(raw).hexdigest(),
                       'source_url':'https://example.test/fixture','retrieved_at_utc':'2026-10-30T17:05:00Z',
                       'status':'CONFIRMED'}  # untrusted packet value must not override raw
            packet = {'schema':'sports.nhl_goalie_capture.v1','sources':[receipt]}
            (root/'packet.json').write_text(json.dumps(packet))
            reports = load_goalie_reports(root/'packet.json')
            self.assertEqual(reports[0]['status'],'PROJECTED')
            (root/'source.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'DIGEST'):
                load_goalie_reports(root/'packet.json')


class SettlementTests(unittest.TestCase):
    def record(self, mode, reg, final):
        return dict(event_id='NHL:fixture', status='FINAL', finish_type=mode,
                    regulation_home=reg[0], regulation_away=reg[1], final_home=final[0], final_away=final[1])

    def test_regulation_ot_and_shootout_hand_calculated(self):
        fixtures = [('REGULATION',(4,1),(4,1),3,5), ('OVERTIME',(2,2),(2,3),-1,5),
                    ('SHOOTOUT',(0,0),(1,0),1,1), ('SHOOTOUT',(3,3),(3,4),-1,7)]
        for mode, reg, final, margin, total in fixtures:
            with self.subTest(mode=mode, final=final):
                r = self.record(mode,reg,final)
                full=settlement_scores(r,settlement='FULL_GAME_OT_SO_PLUS_ONE')
                regulation=settlement_scores(r,settlement='REGULATION')
                self.assertEqual((full['home_margin'],full['total']),(margin,total))
                self.assertEqual((regulation['home_margin'],regulation['total']),(reg[0]-reg[1],sum(reg)))
                self.assertFalse(full['overtime_model_validated'])

    def test_aggregate_shootout_goals_and_final_ties_refused(self):
        for mode, reg, final in [('SHOOTOUT',(2,2),(5,3)), ('OVERTIME',(2,1),(3,1)),
                                 ('OVERTIME',(2,2),(2,2)), ('REGULATION',(3,2),(4,2))]:
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                settlement_scores(self.record(mode,reg,final),settlement='FULL_GAME_OT_SO_PLUS_ONE')

    def test_bad_score_types_and_unknown_rules_refused(self):
        for bad in [True, float('nan'), float('inf'), -1, 1.5, '2', None]:
            r = self.record('OVERTIME',(2,2),(3,2));r['final_home']=bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                settlement_scores(r,settlement='FULL_GAME_OT_SO_PLUS_ONE')
        with self.assertRaises(ValueError):
            settlement_scores(self.record('OVERTIME',(2,2),(3,2)),settlement='ANY_FULL_GAME')


class IntegrationTests(unittest.TestCase):
    def fixture(self, root):
        package = dict(schema='sports.current_research_package.v1',league='nhl',model_id=IDS['nhl'],
                       action_authority=False,feature_names=FEATURES,events=[EVENT],fitted_model={},
                       team_state={},prior=3.,captured_at_utc=CUTOFF,training_cutoff_utc=CUTOFF,
                       source_fetches=[{'fetched_at_utc':CUTOFF}])
        package['model_sha256']=digest({'model':{},'state':{},'prior':3.})
        package['code_pins']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                             ['models/current/common.py','models/current/linear.py','models/current/baseline.py','pipelines/cards/adapters/nhl.py']}
        (root/'package.json').write_text(json.dumps(package))
        card={'league':'NHL','as_of_utc':CUTOFF,'generated_at_utc':CUTOFF,'forecasts':[
            {**EVENT,'forecast_status':'FORECAST_GENERATED','model_id':IDS['nhl'],'model_state_config_hash':package['model_sha256']} ]}
        (root/'card.json').write_text(json.dumps(card))
        config={'schema':'sports.nhl_context_config.v1','action_authority':False,'package':{
            'path':'package.json','sha256':hashlib.sha256((root/'package.json').read_bytes()).hexdigest()}}
        (root/'config.json').write_text(json.dumps(config))

    def test_sidecar_immutable_and_unknown_without_fitted_adjustment(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            before=(root/'card.json').read_bytes()
            r=shadow_from_card(root/'card.json',root/'config.json',root/'out')
            self.assertEqual((root/'card.json').read_bytes(),before)
            self.assertEqual(r['coverage'][0]['status'],'COMPLETED')
            self.assertEqual(r['coverage'][0]['input_eligibility'],'BLOCKED')
            self.assertFalse(r['forecast_generated'])
            self.assertEqual(r['contexts'][0]['model_usage'],'NOT_USED_BY_PARENT_FORECAST')
            self.assertEqual(r['WAGERING_AUTHORITY'],'OFF')
            with self.assertRaises(FileExistsError):
                shadow_from_card(root/'card.json',root/'config.json',root/'out')

    def test_mismatched_parent_state_is_blocked_per_event(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            card=json.loads((root/'card.json').read_text());card['forecasts'][0]['model_state_config_hash']='b'*64
            (root/'card.json').write_text(json.dumps(card))
            r=shadow_from_card(root/'card.json',root/'config.json',root/'out')
            self.assertEqual(r['coverage'][0]['status'],'BLOCKED')
            self.assertEqual(r['contexts'],[])


if __name__ == '__main__':unittest.main()
