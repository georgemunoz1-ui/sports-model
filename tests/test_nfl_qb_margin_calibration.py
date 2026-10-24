import copy
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from models.nfl.contextual import qb_margin as base, qb_margin_calibration as cal, research_board as rb, research_grading as rg
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest, predict


class CalibrationTests(unittest.TestCase):
    def history(self):
        return cal.fit_integer_history([{'game_id': f'2019_TEST_{i}', 'season': 2019, 'arm': 'qb',
            'home_margin': [-7, -3, 0, 3, 7][i % 5], 'pred_margin': float(i % 3)} for i in range(200)], before_season=2020)

    def parent(self):
        reference = load_artifact(base.ROOT/'data/nfl/contextual_v1/model_packed.json'); qb = reference['arms']['qb']
        features = {key: 0.0 for key in qb['feature_names']}
        return {'model_id': base.REFERENCE_ID, 'selected_arm': 'qb', 'mode': 'research_pregame',
            'market_input': False, 'action_authority': False, 'identity': 'SYNTHETIC_UNIT_TEST_NOT_REAL_FORECAST',
            'event': {'event_id': '2100_01_A_B', 'away_team': 'A', 'home_team': 'B', 'start_time_utc': '2100-01-01T00:00:00Z'},
            'cutoff_utc': '2026-01-01T00:00:00Z', 'features': features, 'winner_simulation': {},
            'prediction': predict(qb, features)['prediction'], 'model_artifact_sha256': digest(reference)}

    def test_fixed_integer_masses_and_side_swap(self):
        h = self.history(); s, w, ess = cal.integer_kernel(3.2, .6, h); rs, rw, _ = cal.integer_kernel(-3.2, .4, h)
        np.testing.assert_array_equal(s, -rs[::-1]); np.testing.assert_allclose(w, rw[::-1], atol=1e-15)
        self.assertEqual(set(s), {-7, -3, 0, 3, 7})
        self.assertAlmostEqual(base.summarize(s, w)['p_home_non_tie'], .6)
        self.assertGreater(min(ess.values()), 100)
        self.assertGreater(base.price(s, w, 3)['push'], 0)

    def test_optimizer_global_crps_minimum_and_chronology(self):
        s0, w0, s1, w1 = [-7, 0, 3], [.3, .2, .5], [-3, 0, 7], [.5, .2, .3]
        terms = []
        from scripts.fit_nfl_qb_margin import crps
        for i, actual in enumerate([-7, -3, -3, 0, 3, 7, 10]):
            g, h = cal.quadratic_terms(s0, w0, s1, w1, actual)
            terms.append({'game_id': str(i), 'season': 2020, 'gradient_half': g, 'curvature_half': h})
        alpha = cal.optimize_alpha(terms, before_season=2021)['alpha']
        def loss(a):
            s, w = cal.blend(s0, w0, s1, w1, a)
            return sum(crps(s, w, y) for y in [-7, -3, -3, 0, 3, 7, 10])
        self.assertLessEqual(loss(alpha), min(loss(a) for a in np.linspace(0, 1, 1001))+1e-12)
        for bad in [terms+[terms[0]], [dict(terms[0], season=2021)], []]:
            with self.assertRaises(ValueError): cal.optimize_alpha(bad, before_season=2021)
        for a in [-.1, 1.1, float('nan'), True]:
            with self.assertRaises(ValueError): cal.blend(s0, w0, s1, w1, a)

    def test_registered_chronology_and_no_promotion(self):
        model, report = cal.load_registered()
        self.assertEqual(model['integer_history']['count'], 1871)
        self.assertEqual(model['calibration']['games'], 1615)
        self.assertEqual(report['metrics']['games'], 1087)
        for year, fit in report['outer_calibrations'].items(): self.assertLess(fit['max_season'], int(year))
        self.assertFalse(report['production_promotion']); self.assertFalse(model['market_input'])
        self.assertFalse(model['action_authority'])

    def test_market_display_never_changes_frozen_model_draws(self):
        parent = self.parent(); f, d = cal.build(parent, n=3000); before = digest(f); raw = d.copy()
        absent = rb.board(parent, f, d)
        self.assertTrue(absent['market_overlay']['display_enabled']); self.assertIn('UNAVAILABLE', absent['market_overlay']['status'])
        market = {'event_id': parent['event']['event_id'], 'source_type': 'USER_SUPPLIED_MARKET_SNAPSHOT',
            'source': 'SYNTHETIC_TEST', 'raw_sha256': ['0'*64], 'captured_at_utc': None,
            'spreads': [{'home_handicap': 3.5, 'home_american_odds': -108, 'away_american_odds': -112}]}
        b = rb.board(parent, f, d, market=market)
        self.assertEqual(b['market_overlay']['status'], 'SNAPSHOT_TIME_UNKNOWN')
        r = b['spread_rows'][0]; self.assertAlmostEqual(r['break_even_probability'], 108/208)
        self.assertAlmostEqual(r['sim_cover_probability'], np.mean(d.astype(float)+3.5 > 0))
        self.assertEqual(digest(f), before); np.testing.assert_array_equal(d, raw)
        tampered = d.copy(); tampered[0] += 1
        with self.assertRaisesRegex(ValueError, 'DRAW_BINDING'): rb.board(parent, f, tampered)
        bad = copy.deepcopy(market); bad['event_id'] = 'OTHER'
        with self.assertRaisesRegex(ValueError, 'EVENT'): rb.board(parent, f, d, market=bad)
        self.assertIsNone(rb.board(parent, home_handicaps=[3.5])['spread_rows'][0]['model_cover_probability'])

    def test_append_only_grading_sources_retries_conflicts_and_scenarios(self):
        parent = self.parent(); f, d = cal.build(parent, n=3000)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); folder = root/'forecast'; store = root/'ledger'; cal.persist(folder, f, d)
            kwargs = {'quarterback_conditions': {'A': '00-A', 'B': '00-B'}, 'home_handicaps': [3.5, 3]}
            rg.register(store, folder, parent, **kwargs); head = rg._head(store)
            self.assertEqual(rg.register(store, folder, parent, **kwargs)['status'], 'ALREADY_RECORDED')
            self.assertEqual(head, rg._head(store)); self.assertEqual(rg.status(store)['pending_forecasts'], 1)
            with self.assertRaisesRegex(ValueError, 'NOT_STARTED'):
                rg.grade_event(store, '2100_01_A_B', b'', {}, b'', {})
            other_parent = copy.deepcopy(parent); other_parent['identity'] = 'SECOND_SYNTHETIC_QB_SCENARIO'
            other_f, other_d = cal.build(other_parent, n=3000); other_folder = root/'other'
            cal.persist(other_folder, other_f, other_d)
            rg.register(store, other_folder, other_parent, quarterback_conditions={'A': '00-A', 'B': '00-X'}, home_handicaps=[3.5])
            raw = b'game_id,home_team,away_team,home_score,away_score,home_qb_id,away_qb_id\n2100_01_A_B,B,A,20,23,00-B,00-A\n'
            official = {'header': {'id': '1', 'competitions': [{'date': '2100-01-01T00:00:00Z',
                'status': {'type': {'completed': True, 'state': 'post'}}, 'competitors': [
                    {'homeAway': 'home', 'team': {'abbreviation': 'B'}, 'score': '20'},
                    {'homeAway': 'away', 'team': {'abbreviation': 'A'}, 'score': '23'}]}]}}
            official_raw = json.dumps(official).encode()
            receipt = lambda raw, url: {'sha256': hashlib.sha256(raw).hexdigest(), 'source_url': url, 'retrieved_at_utc': '2100-01-02T00:00:00Z'}
            sr = receipt(raw, rg.SCHEDULE_URL); er = receipt(official_raw, 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=1')
            class Future(dt.datetime):
                @classmethod
                def now(cls, tz=None): return cls(2100, 1, 3, tzinfo=dt.timezone.utc)
            with patch.object(rg.dt, 'datetime', Future):
                broken = dict(sr, sha256='0'*64)
                before = {str(p): p.read_bytes() for p in store.rglob('*') if p.is_file()}
                with self.assertRaisesRegex(ValueError, 'HASH'): rg.grade_event(store, '2100_01_A_B', raw, broken, official_raw, er)
                self.assertEqual(before, {str(p): p.read_bytes() for p in store.rglob('*') if p.is_file()})
                rg.grade_event(store, '2100_01_A_B', raw, sr, official_raw, er)
                grades = [r['payload'] for r in rg.records(store) if r['kind'] == 'GRADE']
                self.assertEqual(sum(g['scenario_matches_actual'] for g in grades), 1)
                self.assertIn('COUNTERFACTUAL_QB_EXCLUDED_FROM_MATCHED_COHORT', {g['cohort'] for g in grades})
                grade = next(g for g in grades if g['scenario_matches_actual'])
                settled = {r['home_handicap']: r['outcome'] for r in grade['contracts']}
                self.assertEqual(settled[3.5], 'cover'); self.assertEqual(settled[3], 'push')
                self.assertFalse(grade['weekly_state_advanced']); self.assertFalse(grade['canonical_grade'])
                after = {str(p): p.read_bytes() for p in store.rglob('*') if p.is_file()}
                self.assertEqual(rg.grade_event(store, '2100_01_A_B', raw, sr, official_raw, er)['status'], 'ALREADY_RECORDED')
                changed_raw = raw.replace(b',20,23,', b',21,23,'); changed = copy.deepcopy(official)
                changed['header']['competitions'][0]['competitors'][0]['score'] = '21'; changed_official = json.dumps(changed).encode()
                with self.assertRaisesRegex(ValueError, 'CONFLICT'):
                    rg.grade_event(store, '2100_01_A_B', changed_raw, receipt(changed_raw, sr['source_url']), changed_official, receipt(changed_official, er['source_url']))
                self.assertEqual(after, {str(p): p.read_bytes() for p in store.rglob('*') if p.is_file()})
            old_object = store/'objects'/f'{head}.json'; old_object.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'HASH'): rg.status(store)


if __name__ == '__main__': unittest.main()
