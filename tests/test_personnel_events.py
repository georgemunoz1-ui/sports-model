"""Retained snapshots distinguish an official personnel report from a model input."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from models.nfl.contextual.features import qb_features
from research.personnel_events import NFL_SOURCE, ROLES, _Evidence, load_observations, review_fixture
from sports.rosters import digest


START = '2026-11-15T18:00:00Z'
CUTOFF = '2026-11-15T12:00:00Z'
PUBLISHED = '2026-11-14T18:00:00Z'
LATE = '2026-11-15T15:00:00Z'
MODEL = 'nfl.integrated_context.qb.v1.research'
EVENT = dict(event_id='2026_10_MIN_GB', away_team='MIN', home_team='GB', start_time_utc=START)


class SourceEvidence(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def manifest(self, quote, *, status='STARTING', url='https://vikings.com/news/game', published=PUBLISHED,
                 acquired=LATE, context='Week 10 at Packers', original=PUBLISHED,
                 league='NFL', team='MIN', event_id=EVENT['event_id'], prior=None, prior_event=None):
        article = {'@type':'NewsArticle', 'url':url, 'datePublished':original}
        raw = f'<script type="application/ld+json">{json.dumps(article)}</script><p>{quote}</p><p>{context}</p>'.encode()
        body_hash = hashlib.sha256(raw).hexdigest()
        source = {'path':'article.html', 'sha256':body_hash, 'url':url, 'published_at_utc':published,
                  'retrieved_at_utc':acquired, 'excerpt':quote, 'context_excerpt':context}
        row = dict(league=league, event_id=event_id, team_id=team, player_name='Alex Smith', player_id='1',
                   role=ROLES[league][0], status=status, source=source, prior_team_id=prior, prior_team_event_id=prior_event)
        (self.root / 'article.html').write_bytes(raw)
        (self.root / 'article.json').write_text(json.dumps(dict(sha256=body_hash,url=url,acquired_at_utc=acquired)))
        path = self.root / 'review.json'
        path.write_text(json.dumps(dict(schema='sports.personnel_review_inputs.v1',reports=[row])))
        return path

    def result(self, quote, **kwargs):
        manifest = self.manifest(quote, **kwargs)
        return review_fixture('NFL', EVENT, CUTOFF, forecast={}, observations=load_observations(manifest))

    def test_status_does_not_bind_player_to_model(self):
        report = self.result('Alex Smith will start.')
        self.assertTrue(report['review_required'])
        self.assertEqual(report['roles'], [])
        row, = report['observations']
        self.assertEqual(row['comparison'],'MODEL_USE_UNVERIFIED')
        self.assertEqual(row['timing'],'KNOWN_TO_REVIEW_ONLY')
        self.assertTrue(row['published_time_verified'])
        self.assertFalse(report['action_authority'])

    def test_wrong_origin_fixture_or_subject(self):
        cases = [
            ('Alex Smith will start.', {'url':'https://vikings.com.example.org/news/game'}, 'REPORT_UNVERIFIED'),
            ('Alex Smith will start.', {'context':'Week 9 at Packers'},'FIXTURE_CONTEXT_UNVERIFIED'),
            ('Alex Smith will start.', {'context':'Week 10 at Texans'},'FIXTURE_CONTEXT_UNVERIFIED'),
            ('Alex Smith will start.', {'context':'Week 10 at Packers', 'url':'https://nfl.com/news/game'},'FIXTURE_CONTEXT_UNVERIFIED'),
            ('Alex Smith will not start. Another player will start.', {}, 'REPORT_UNVERIFIED'),
            ('Alex Smith says Ben Jones is out.', {'status':'OUT'}, 'REPORT_UNVERIFIED'),
            ('Alex Smith is not ruled out.', {'status':'OUT'}, 'REPORT_UNVERIFIED'),
            ('Alex Smith may start.', {}, 'REPORT_UNVERIFIED'),
            ('Coach mentioned Alex Smith but Ben Jones will start.', {}, 'REPORT_UNVERIFIED'),
        ]
        for quote, overrides, comparison in cases:
            with self.subTest(quote=quote, overrides=overrides):
                self.assertEqual(self.result(quote, **overrides)['observations'][0]['comparison'], comparison)

    def test_publication_or_source_bytes_cannot_be_silently_backdated(self):
        path = self.manifest('Alex Smith will start.', published='2026-11-13T11:00:00Z')
        with self.assertRaisesRegex(ValueError,'PUBLISHED_TIME_MISMATCH'):
            load_observations(path)
        path = self.manifest('Alex Smith will start.')
        (self.root / 'article.html').write_text('changed')
        with self.assertRaisesRegex(ValueError,'SOURCE_HASH'):
            load_observations(path)

    def test_transfer_routes_only_to_explicit_previous_fixture(self):
        path = self.manifest('Vikings acquired Alex Smith from the Raiders.',status='TRADED',prior='LV',
                             prior_event='2026_10_SEA_LV')
        reports = load_observations(path)
        previous = dict(EVENT,event_id='2026_10_SEA_LV',away_team='SEA',home_team='LV')
        outcome = review_fixture('NFL',previous,CUTOFF,forecast={},observations=reports)
        self.assertEqual(outcome['observations'][0]['comparison'],'PRIOR_TEAM_DEPARTURE')
        self.assertTrue(outcome['review_required'])

    def test_each_sport_surfaces_material_unknown_and_preserves_empty_coverage(self):
        domains = ['nfl.com','ncaa.org','nba.com','wnba.com','ncaa.com','nhl.com','mlb.com','mlssoccer.com']
        for league, domain in zip(ROLES, domains):
            with self.subTest(league=league):
                event = dict(EVENT, away_team='Away',home_team='Home',event_id='game')
                evidence = load_observations(self.manifest('Alex Smith is out.', status='OUT',team='Away',
                    league=league, url=f'https://www.{domain}/news/game', event_id='game', context='Sunday fixture Away at Home'))
                result = review_fixture(league,event,CUTOFF,forecast={},observations=evidence)
                self.assertTrue(result['review_required'])
                self.assertEqual(result['observations'][0]['comparison'],'MODEL_USE_UNVERIFIED')
                self.assertEqual(review_fixture(league,event,CUTOFF,forecast={})['status'],'UNVERIFIED')
                self.assertEqual(review_fixture(league,event,None)['status'],'NO_FROZEN_FORECAST')


class FrozenQuarterbackEvidence(TestCase):
    def setUp(self):
        game = dict(away_qb_id='1',away_qb_name='Alex Smith',home_qb_id='2',home_qb_name='James Brown',
                    away_team='MIN',home_team='GB',season='2026')
        previous = dict(game, away_team='LV',home_team='GB')
        state = {'qb_state':{'qb_ratings':{'1':{'n':20,'sum':40}},'last_qb':{'MIN':'9','GB':'2'}},
                 'schedule_source':{'receipt':{'source_url':NFL_SOURCE,'retrieved_at_utc':PUBLISHED,'sha256':'schedule'}},
                 'cutoff_utc':CUTOFF,'consumed_game_ids':['prior'],'model_sha256':'model'}
        self.evidence = _Evidence((),{EVENT['event_id']:game,'prior':previous},'schedule',state,'state')
        features = qb_features(game,state['qb_state']['qb_ratings'],state['qb_state']['last_qb'])
        rows = [dict(feature=k, raw_value=v, active_in_run=True,
                     lineage=dict(feature_value_sha256=digest(v),source_sha256='schedule',model_artifact_sha256='model'))
                for k, v in features.items()]
        identity = dict(cutoff_utc=CUTOFF,event_id=EVENT['event_id'],model_id=MODEL,feature_sha256=digest(features))
        self.trace = dict(schema='nfl.integrated_context_forecast.v1',selected_arm='qb',model_id=MODEL,event=EVENT,
                cutoff_utc=CUTOFF,capability_report=dict(event_id=EVENT['event_id'],cutoff_utc=CUTOFF,model_id=MODEL,rows=rows),
                assimilation=dict(schedule_sha256='schedule',state_id='state',qb_state_sha256=digest(state['qb_state'])),
                model_artifact_sha256='model',features=dict(features,inactive=5),
                identity=digest(identity),numerical_identity=dict(identity,identity_sha256=digest(identity)))

    def test_exact_selected_vector_and_consumed_team_history(self):
        before = deepcopy(self.trace)
        roles = review_fixture('NFL',EVENT,CUTOFF,forecast=self.trace,observations=self.evidence)['roles']
        away = next(r for r in roles if r['team_id']=='MIN')
        self.assertEqual(away['player_name'],'Alex Smith')
        self.assertEqual(away['same_team_schedule_starts'],0)
        self.assertEqual(away['prior_clubs_in_consumed_season'],['LV'])
        self.assertTrue(away['changed_from_previous_starter'])
        self.assertEqual(before,self.trace)
        self.trace['features']['qb_quality_diff'] = 10
        self.assertEqual(review_fixture('NFL',EVENT,CUTOFF,forecast=self.trace,observations=self.evidence)['roles'],[])

    def test_shared_forecast_must_bind_same_snapshot(self):
        wrapper = dict(event_id=EVENT['event_id'],model_id=MODEL,input_snapshot_hash=digest(self.trace['features']),
                       model_state_config_hash='model',diagnostics=self.trace)
        self.assertEqual(len(review_fixture('NFL',EVENT,CUTOFF,forecast=wrapper,observations=self.evidence)['roles']),2)
        wrapper['input_snapshot_hash'] = 'other'
        self.assertEqual(review_fixture('NFL',EVENT,CUTOFF,forecast=wrapper,observations=self.evidence)['roles'],[])
