"""Source semantics and leakage tests; synthetic games are not backtest evidence."""
import copy
import hashlib
import json
import unittest
from pathlib import Path
import tempfile

from models.current.freshness import (operational_rest, rebuild_candidate_features,
    state_freshness_receipt, normalize_captured_schedule)
from models.current.baseline import feature
from scripts.prepare_initial_baselines import causal_rows

SHA = 'a' * 64
CUTOFF = '2026-10-22T06:31:00+00:00'
EVENT = {'event_id': 'NHL:401892556', 'home_id': 'PIT', 'away_id': 'FLA',
         'start_time_utc': '2026-10-22T23:00:00+00:00', 'neutral_site': False}


def history(eid='synthetic:previous-night', start='2026-10-21T23:00:00+00:00', **changes):
    row = {'event_id': eid, 'home_id': 'OTT', 'away_id': 'FLA', 'start_time_utc': start,
           'neutral_site': False, 'status': 'final', 'observed_at_utc': '2026-10-22T06:30:00+00:00', 'source_sha256': SHA}
    row.update(changes)
    return row


def coverage(team):
    return {'team_id': team, 'from_utc': '2026-10-01T00:00:00+00:00',
            'through_utc': '2026-10-22T06:30:00+00:00', 'observed_at_utc': '2026-10-22T06:30:00+00:00',
            'source_sha256': SHA, 'complete': True, 'population': 'ALL_PLAYED_GAMES'}


class FreshnessTests(unittest.TestCase):
    def test_pinned_frozen_excerpt_has_the_reported_input_defects(self):
        path = Path(__file__).parent/'fixtures/frozen_20261022_freshness_excerpt.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         '3320f2f86580d561c7796915e34a9b32cc8dc32493657771ae5cf2548b346c92')
        frozen = json.loads(path.read_text())
        self.assertEqual(frozen['parent_sha256'], '06af78e016a4eb152d259a53efbcf9192ca1d5bf60c8eac15fa0f912e0d4754e')
        events = {r['event_id']: r for r in frozen['events']}
        self.assertAlmostEqual(events['NHL:401892556']['model_input_snapshot']['away_rest'], 5.041666666666667)
        nba = next(r for r in frozen['sources'] if r['league'] == 'nba')
        self.assertEqual(nba['latest_consumed_game_start_utc'], '2026-04-13T00:30:00+00:00')
        self.assertTrue(nba['latest_capture'].startswith('2026-10-22'))

    def rest(self, rows, receipts=None, **kw):
        return operational_rest(EVENT, rows, cutoff_utc=CUTOFF,
                                coverage=[coverage('FLA')] if receipts is None else receipts, **kw)

    def test_previous_night_operational_rest_not_embargoed(self):
        state = {'FLA': {'n': 12, 'for': 3., 'against': 3., 'last': '2026-10-17T22:00:00+00:00'},
                 'PIT': {'n': 12, 'for': 3., 'against': 3., 'last': '2026-10-20T01:00:00+00:00'}}
        unchanged = copy.deepcopy(state)
        rows = [history(), history('synthetic:pit', '2026-10-20T01:00:00+00:00', home_id='PIT', away_id='BOS')]
        built = rebuild_candidate_features(state, EVENT, 3., rows, cutoff_utc=CUTOFF,
                                           coverage=[coverage('FLA'), coverage('PIT')])
        self.assertTrue(built['candidate_ready'])
        self.assertAlmostEqual(built['legacy_features']['away_rest'], 5.041666666666667)
        self.assertEqual(built['candidate_features']['away_rest'], 1.)
        for name, value in built['legacy_features'].items():
            if name != 'away_rest':
                self.assertEqual(built['candidate_features'][name], value)
        self.assertEqual(state, unchanged)
        self.assertEqual(built['adoption_status'], 'REFIT_AND_CHRONOLOGICAL_EVALUATION_REQUIRED')

    def test_legacy_training_also_uses_embargo_proxy(self):
        games = [history('synthetic:oct17', '2026-10-17T22:00:00+00:00', home_score=5, away_score=1),
                 history(home_score=5, away_score=1)]
        _, state, used = causal_rows(games, 3., CUTOFF)
        self.assertEqual(used, ['synthetic:oct17'])
        self.assertAlmostEqual(feature(state, EVENT, 3.)['away_rest'], 5.041666666666667)

    def test_unknown_coverage_cannot_emit_rest(self):
        row = self.rest([history()], receipts=[])['per_side']['away']
        self.assertIsNone(row['candidate_feature_value'])
        self.assertIn('AS_OF_HISTORY_COVERAGE_UNPROVEN', row['blocking_reasons'])

    def test_post_cutoff_capture_cannot_backdate_final(self):
        row = self.rest([history(observed_at_utc='2026-10-22T06:32:00+00:00')])
        self.assertEqual(row['exclusions'], {'NOT_AVAILABLE_PREFORECAST': 1})
        self.assertIsNone(row['per_side']['away']['candidate_feature_value'])

    def test_current_and_nonfinal_excluded(self):
        rows = [history(eid=EVENT['event_id']), history('synthetic:cancel', status='canceled')]
        out = self.rest(rows)
        self.assertEqual(out['exclusions'], {'CURRENT_EVENT_EXCLUDED': 1, 'NONFINAL_EXCLUDED': 1})

    def test_invalid_and_conflicting_identity_fail_closed(self):
        for rows in ([history(source_sha256='bad')],
                     [history(), history(start_time_utc='2026-10-21T22:00:00+00:00')]):
            self.assertIn('HISTORY_INTEGRITY_UNPROVEN', self.rest(rows)['per_side']['away']['blocking_reasons'])

    def test_offsets_compare_instants_and_units_are_hours(self):
        out = self.rest([history(start_time_utc='2026-10-21T19:00:00-04:00')])
        self.assertEqual(out['per_side']['away']['rest_start_to_start_days'], 1.)
        self.assertEqual(out['units'], 'start_to_start_days_24h')

    def test_completion_after_observation_is_invalid(self):
        row = self.rest([history(completed_at_utc='2026-10-22T06:31:00+00:00')])
        self.assertIsNone(row['per_side']['away']['candidate_feature_value'])

    def test_naive_and_bad_policy_rejected(self):
        with self.assertRaises(ValueError):
            operational_rest(EVENT, [], cutoff_utc='2026-10-22T06:31:00')
        for value in [True, float('nan'), float('inf'), -1, 0]:
            with self.assertRaises(ValueError):
                self.rest([], max_capture_age_hours=value)

    def test_stale_and_unbound_coverage_is_unknown(self):
        for edits in ({'through_utc': '2026-10-21T00:00:00+00:00'}, {'source_sha256': 'b' * 64}, {'complete': 1}, {'population': 'REGULAR_SEASON_ONLY'}, {'observed_at_utc': CUTOFF}):
            receipt = coverage('FLA'); receipt.update(edits)
            self.assertEqual(self.rest([history()], [receipt])['per_side']['away']['status'], 'UNKNOWN')

    def test_duplicate_copies_use_earliest_known_observation(self):
        out = self.rest([history(), history(observed_at_utc='2026-10-22T06:30:30+00:00')])
        self.assertEqual(out['per_side']['away']['status'], 'KNOWN')

    def test_raw_capture_binding_and_forfeit_exclusion(self):
        e = {'id': '1', 'date': '2026-10-21T23:00:00Z', 'competitions': [
            {'competitors': [{'homeAway': 'home', 'team': {'id': 'OTT'}}, {'homeAway': 'away', 'team': {'id': 'FLA'}}],
             'status': {'type': {'completed': True, 'state': 'post', 'name': 'STATUS_FINAL_FORFEIT'}}}]}
        raw = json.dumps({'events': [e]}).encode(); sha = hashlib.sha256(raw).hexdigest()
        rows = normalize_captured_schedule(raw, league='nhl', captured_at_utc=CUTOFF, source_sha256=sha)
        self.assertEqual(rows[0]['status'], 'nonfinal')
        with self.assertRaises(ValueError):
            normalize_captured_schedule(raw+b' ', league='nhl', captured_at_utc=CUTOFF, source_sha256=sha)

    def test_april_state_not_fresh_from_october_capture(self):
        package = {'model_id': 'nba.initial_causal_score.research.v1', 'training_cutoff_utc': CUTOFF,
                   'captured_at_utc': CUTOFF, 'team_state': {'PIT': {'last': '2026-04-13T00:30:00Z'},
                                                         'FLA': {'last': '2026-04-13T00:30:00Z'}}}
        out = state_freshness_receipt(package, EVENT, {'home_rest': 14., 'away_rest': 14.},
                                      cutoff_utc=CUTOFF, max_state_age_hours=72)
        self.assertGreater(out['per_side']['home']['state_age_at_cutoff_hours'], 4000)
        self.assertIn('HOME:CONSUMED_STATE_OLDER_THAN_POLICY', out['blocking_reasons'])
        self.assertTrue(out['per_side']['home']['feature_matches_consumed_state'])

    def test_unknown_imputation_and_future_fit_disclosed(self):
        out = state_freshness_receipt({'training_cutoff_utc': '2026-10-23T00:00:00Z'}, EVENT,
                                      {'home_rest': 14., 'away_rest': 14.}, cutoff_utc=CUTOFF)
        self.assertTrue(out['per_side']['home']['imputed'])
        self.assertIn('FIT_NOT_AVAILABLE_PREFORECAST', out['blocking_reasons'])

    def test_nonfinite_and_bool_feature_not_a_verified_number(self):
        for value in [True, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                state_freshness_receipt({}, EVENT, {'home_rest': value, 'away_rest': 14.}, cutoff_utc=CUTOFF)


class RestCandidateCliTests(unittest.TestCase):
    def fixture(self, root):
        from models.current.baseline import FEATURES, IDS
        from models.nfl.contextual.recovered_inference import digest
        repo = Path(__file__).resolve().parents[1]
        target = {**EVENT, 'event_id': 'NHL:synthetic-target'}
        event = {'id': 'synthetic-previous', 'date': '2026-10-21T23:00:00Z', 'competitions': [
            {'competitors': [{'homeAway': 'home', 'team': {'id': 'PIT'}}, {'homeAway': 'away', 'team': {'id': 'FLA'}}],
             'status': {'type': {'completed': True, 'state': 'post', 'name': 'STATUS_FINAL'}}}]}
        future = copy.deepcopy(event); future['id']='synthetic-target';future['date']=EVENT['start_time_utc']
        future['competitions'][0]['status']['type']={'completed':False,'state':'pre','name':'STATUS_SCHEDULED'}
        raw=json.dumps({'events':[event,future]}).encode();sha=hashlib.sha256(raw).hexdigest()
        (root/'raw.json').write_bytes(raw)
        package={'schema':'sports.current_research_package.v1','league':'nhl','model_id':IDS['nhl'],
                 'action_authority':False,'feature_names':FEATURES,'fitted_model':{},'prior':3.,'events':[target],
                 'team_state':{team:{'n':12,'for':3.,'against':3.,'last':'2026-10-17T22:00:00Z'} for team in ['PIT','FLA']},
                 'captured_at_utc':CUTOFF,'training_cutoff_utc':CUTOFF,
                 'source_fetches':[{'fetched_at_utc':CUTOFF}],
                 'code_pins':{name:hashlib.sha256((repo/name).read_bytes()).hexdigest() for name in [
                     'models/current/common.py','models/current/baseline.py','models/current/linear.py','pipelines/cards/adapters/nhl.py']}}
        package['model_sha256']=digest({'model':{},'state':package['team_state'],'prior':3.})
        (root/'package.json').write_text(json.dumps(package))
        packet={'schema':'sports.operational_rest_history.v1','league':'nhl',
                'sources':[{'raw_path':'raw.json','source_sha256':sha,'captured_at_utc':'2026-10-22T06:30:00+00:00'}],
                'coverage':[{**coverage(team),'source_sha256':sha} for team in ['PIT','FLA']]}
        (root/'history.json').write_text(json.dumps(packet))
        return target,packet

    def test_actual_cli_build_is_immutable_and_never_forecasts(self):
        from scripts.build_operational_rest_candidate import build
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target,_=self.fixture(root)
            out=build(root/'package.json',root/'history.json',target['event_id'],CUTOFF,root/'out')
            self.assertTrue(out['candidate_ready'])
            self.assertEqual(out['candidate_features']['away_rest'],1.)
            self.assertFalse(out['forecast_generated'])
            self.assertTrue((root/'out/manifest.json').is_file())
            with self.assertRaises(FileExistsError):
                build(root/'package.json',root/'history.json',target['event_id'],CUTOFF,root/'out')

    def test_cli_rejects_source_tampering(self):
        from scripts.build_operational_rest_candidate import build
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target,_=self.fixture(root)
            (root/'raw.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'DIGEST_MISMATCH'):
                build(root/'package.json',root/'history.json',target['event_id'],CUTOFF,root/'out')

    def test_cli_rejects_path_escape(self):
        from scripts.build_operational_rest_candidate import build
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target,packet=self.fixture(root)
            packet['sources'][0]['raw_path']='../escape.json'
            (root/'history.json').write_text(json.dumps(packet))
            with self.assertRaisesRegex(ValueError,'PATH_ESCAPE'):
                build(root/'package.json',root/'history.json',target['event_id'],CUTOFF,root/'out')


if __name__ == '__main__':
    unittest.main()
