"""Synthetic engineering fixtures only; no fitted sports parameters or validity claim."""
import copy
import unittest
from models.nba import efficiency_monte_carlo_v1 as original
from models.nba import efficiency_monte_carlo_shadow_v1_1 as fixed

class DirectionContract(unittest.TestCase):
    def setUp(self):
        self.s = dict(event_id='SYNTHETIC',home_team='H',away_team='A',home_adj_ortg=100.,away_adj_ortg=100.,home_adj_drtg=100.,away_adj_drtg=100.,home_pace=100.,away_pace=100.,home_availability_epm_per100=0.,away_availability_epm_per100=0.,defensive_rating_semantics='POINTS_ALLOWED_PER_100_POSSESSIONS')
        self.c = dict(fit_required=False,parameters=dict(league_ortg=100.,home_court_points_per100=0.,pace_sd=1.,shared_eff_sd=1.,team_eff_sd=1.,margin_logistic_scale=10.))
    def test_original_regression_demonstrated(self):
        lo=original.run(self.s,self.c,50000)
        self.s['away_adj_drtg']=110.
        self.assertLess(original.run(self.s,self.c,50000)['model_p'],lo['model_p'])
    def test_worse_away_defense_increases_home_analytic_probability(self):
        lo=fixed.run(self.s,self.c,50000)
        self.s['away_adj_drtg']=110.
        hi=fixed.run(self.s,self.c,50000)
        self.assertGreater(hi['model_p'],lo['model_p'])
        self.assertGreater(hi['home_score_mean'],lo['home_score_mean'])
    def test_worse_home_defense_decreases_home_analytic_probability(self):
        lo=fixed.run(self.s,self.c,50000)
        self.s['home_adj_drtg']=110.
        self.assertLess(fixed.run(self.s,self.c,50000)['model_p'],lo['model_p'])
    def test_unknown_units_fail_closed(self):
        del self.s['defensive_rating_semantics']
        with self.assertRaisesRegex(ValueError,'SEMANTICS_REQUIRED'):fixed.run(self.s,self.c,50000)
    def test_unfitted_state_still_blocked(self):
        self.c['fit_required']=True
        with self.assertRaisesRegex(ValueError,'ESTIMATION_REQUIRED'):fixed.run(self.s,self.c,50000)
    def test_missing_availability_still_blocked(self):
        del self.s['home_availability_epm_per100']
        with self.assertRaisesRegex(ValueError,'INPUTS_INCOMPLETE'):fixed.run(self.s,self.c,50000)
    def test_reproducible_and_distinct_identity(self):
        one=fixed.run(self.s,self.c,50000)
        self.assertEqual(one,fixed.run(self.s,self.c,50000))
        self.assertNotEqual(one['model_id'],original.ENGINE_ID)
        self.assertFalse(one['provenance']['action_authority'])
    def test_score_mean_arithmetic(self):
        out=fixed.run(self.s,self.c,50000)
        self.assertAlmostEqual(out['projected_margin'],out['home_score_mean']-out['away_score_mean'])
        self.assertAlmostEqual(out['projected_total'],out['home_score_mean']+out['away_score_mean'])


class ShadowCliContract(unittest.TestCase):
    def setUp(self):
        DirectionContract.setUp(self)
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.snapshot = self.root / 'snapshot.json'
        self.state = self.root / 'state.json'
        self.output = self.root / 'output.json'

    def invoke(self, extra=(), allow=True):
        import json, subprocess, sys
        from pathlib import Path
        self.snapshot.write_text(json.dumps(self.s))
        self.state.write_text(json.dumps(self.c))
        args = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/run_nba_efficiency_shadow.py'), '--snapshot', str(self.snapshot), '--model-state', str(self.state), '--output', str(self.output)]
        if allow: args += ['--allow-research']
        return subprocess.run(args + list(extra), text=True, capture_output=True)

    def test_cli_requires_opt_in(self):
        result = self.invoke(allow=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_cli_default_and_output_immutability(self):
        import json
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        before = self.output.read_bytes()
        report = json.loads(before)
        self.assertEqual(report['result']['simulation']['count'], 100000)
        self.assertTrue(report['research_only'])
        self.assertFalse(report['canonical_eligible'])
        self.assertFalse(report['action_authority'])
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(before, self.output.read_bytes())

    def test_cli_rejects_unfitted_state(self):
        self.c['fit_required'] = True
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_cli_rejects_unknown_units(self):
        self.s['defensive_rating_semantics'] = 'UNKNOWN'
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_selected_adapter_is_unchanged_initial_baseline(self):
        from pipelines.cards.adapters import nba
        import inspect
        self.assertNotIn('efficiency_monte_carlo_shadow', inspect.getsource(nba))
        self.assertIn('models.current', inspect.getsource(nba))

if __name__=='__main__':unittest.main(verbosity=2)
