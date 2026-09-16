import importlib.util
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
def module(path):
    spec=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
card=module(ROOT/'scripts/generate_card_force.py')
collector=module(ROOT/'scripts/recovery_capture.py')
class RecoveryTests(unittest.TestCase):
    def pit(self,stamp,cutoff='2026-09-05T09:00:00Z',created='2026-09-05T09:10:00Z'):
        return card.summarize_pit({'pit_provenance':{'source_fetches':[{'fetched_at_utc':stamp}]}},cutoff,created)
    def test_late_fetch_fails(self): self.assertEqual(self.pit('2026-09-05T09:00:01Z')['pit_gate'],'FAIL')
    def test_future_fails(self): self.assertEqual(self.pit('2099-01-01T00:00:00Z')['pit_gate'],'FAIL')
    def test_missing_fails(self): self.assertEqual(self.pit(None)['pit_gate'],'FAIL')
    def test_naive_timestamp_fails(self): self.assertEqual(self.pit('2026-09-05T08:00:00')['pit_gate'],'FAIL')
    def test_ordering_not_provenance(self): self.assertNotEqual(self.pit('2026-09-05T08:59:59Z')['pit_gate'],'PASS')
    def test_override_probabilities_rejected(self):
        for v in (1.5,-.1,float('nan'),float('inf')):
            for key in ('analytic_p','stochastic_sim_p'):
                with self.assertRaises(RuntimeError): card.normalize({},dict(model_p=.5,sim_p=.5,**{key:v}))
    def test_capture_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'raw.json';collector.write_once(p,b'original');collector.write_once(p,b'original')
            with self.assertRaises(RuntimeError): collector.write_once(p,b'changed')
            self.assertEqual(p.read_bytes(),b'original')
    def test_no_self_registration(self):
        c={'league':'MLB','generated_at_utc':'2026-09-05T09:10:00Z','pit_provenance':{'pit_status':'PIT_ALIGNED','max_source_timestamp_utc':'2026-09-05T08:59:00Z'},'forecasts':[{'forecast_status':'FORECAST_GENERATED','start_time_utc':'2026-09-05T20:00:00Z','analytic_p':.6,'stochastic_sim_p':.6,'home_team':'H','away_team':'A','model_winner':'H'}]}
        self.assertFalse(card.attach_grading(c)['forecasts'][0]['grading']['eligible_for_prospective_grading'])
if __name__=='__main__': unittest.main()
