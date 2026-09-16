import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def load(path):
    spec=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
class ModelTests(unittest.TestCase):
    def test_wnba_both_defense_paths(self):
        m=load(ROOT/'models/wnba/efficiency_monte_carlo_v1_1.py')
        baseline=dict(event_id='fixture',home_team='H',away_team='A',home_ortg=103,away_ortg=103,home_drtg=103,away_drtg=103,home_pace=80,away_pace=80)
        grid=[90,95,100,103,108,115]
        for key,sign in [('away_drtg',1),('home_drtg',-1)]:
            outputs=[m.run(dict(baseline,**{key:v}),{},50000) for v in grid]
            margins=[o['analytic_margin'] for o in outputs]
            self.assertTrue(all(sign*(b-a)>0 for a,b in zip(margins,margins[1:])))
            self.assertAlmostEqual(abs(margins[-1]-margins[0]),20)
            self.assertTrue(all(o['action_authority'] is False for o in outputs))
    def test_mlb_missing_required_input_prevents_engine(self):
        # Import the adapter with an engine sentinel: no simulation may happen on rejected inputs.
        fake=types.ModuleType('models.mlb.monte_carlo_v1')
        def forbidden(*args): raise AssertionError('ENGINE_CALLED_WITH_MISSING_INPUTS')
        fake.run=forbidden
        with patch.dict(sys.modules,{'models.mlb.monte_carlo_v1':fake}):
            m=load(ROOT/'pipelines/cards/adapters/mlb_gamma_poisson_research.py')
        m._pitcher=lambda *args:None
        event=dict(event_id='x',away_team_id=1,home_team_id=2)
        context=dict(standings={},overrides={},pit_provenance={})
        with self.assertRaisesRegex(RuntimeError,'REQUIRED_STARTER_MISSING'):m.forecast_event(event,context)
if __name__=='__main__':unittest.main()
