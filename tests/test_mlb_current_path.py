import csv
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from pipelines.mlb.current import assimilate
from pipelines.cards.adapters.mlb import capture_sim
from harness import run_v13_historical as V

class CurrentMLBTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.base=self.root/'base.csv';self.staged=self.root/'staged.json'
        with self.base.open('w') as f:
            w=csv.DictWriter(f,fieldnames=['game_id','date','status','result_status','source_tier','away','home','away_score','home_score']);w.writeheader();w.writerow(dict(game_id='old',date='2026-08-30',status='final',result_status='FINAL',source_tier='1',away='SEA',home='LAA',away_score=2,home_score=1))
        self.rows=[]
        for i in range(14):
            day=(dt.date(2026,8,31)+dt.timedelta(days=i)).isoformat()
            self.rows.append(dict(event_id=str(i),league='mlb',status='final',slate_date=day,start_utc=day+'T19:00:00Z',retrieved_at='2026-09-14T16:00:00Z',source_sha256='a'*64,away_code='SEA',home_code='LAA',away_score=5,home_score=3))
    def run_form(self):
        self.staged.write_text(json.dumps(self.rows));return assimilate(self.base,self.staged,'2026-09-14','2026-09-14T21:00:00Z')
    def test_assimilation_changes_feature_state_preserves_base(self):
        original=self.base.read_bytes();r=self.run_form();self.assertEqual(r['assimilated_rows'],14);self.assertEqual(r['through_date'],'2026-09-13');self.assertGreater(r['teams']['SEA']['rf'],r['before_teams']['SEA']['rf']);self.assertEqual(original,self.base.read_bytes())
    def test_missing_d1_refused(self):
        self.rows.pop()
        with self.assertRaisesRegex(ValueError,'FORM_DATE_HOLES'):self.run_form()
    def test_interior_hole_refused(self):
        self.rows.pop(7)
        with self.assertRaisesRegex(ValueError,'FORM_DATE_HOLES'):self.run_form()
    def test_duplicate_id_refused(self):
        self.rows.append(self.rows[-1].copy())
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):self.run_form()
    def test_duplicate_matchup_under_different_id_refused(self):
        self.rows.append(dict(self.rows[-1],event_id='different'))
        with self.assertRaisesRegex(ValueError,'DUPLICATE_STAGED_MATCHUP_START'):self.run_form()
    def test_doubleheader_retained(self):
        self.rows.append(dict(self.rows[-1],event_id='doubleheader2',start_utc='2026-09-13T23:00:00Z'))
        self.assertEqual(self.run_form()['assimilated_rows'],15)
    def test_future_retrieval_refused(self):
        self.rows[0]['retrieved_at']='2026-09-15T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'AFTER_CUTOFF'):self.run_form()
    def test_target_day_excluded(self):
        self.rows.append(dict(self.rows[-1],event_id='today',slate_date='2026-09-14',away_score=100));self.assertEqual(self.run_form()['assimilated_rows'],14)
    def test_score_tie_refused(self):
        self.rows[0]['away_score']=3
        with self.assertRaisesRegex(ValueError,'INVALID_FINAL'):self.run_form()
    def test_pinned_engine_capture_has_identical_outputs(self):
        sp=V._sp({});args=(sp,sp,4.3,4.5,4.7,4.0,1.0,1234,10000)
        direct=V.v13_sim(*args);got,arrays=capture_sim(V,*args)
        self.assertEqual(direct,got);self.assertEqual(len(arrays['hw']),10000);self.assertEqual(float(arrays['hw'].mean()),got['p_home'])
        _,again=capture_sim(V,*args)
        for k in arrays:self.assertTrue(np.array_equal(arrays[k],again[k]))

class CurrentMLBIntegrationTests(unittest.TestCase):
    def test_current_packet_reaches_forecast_and_retains_arrays(self):
        import os
        from unittest.mock import patch
        from pipelines.cards.adapters import mlb
        p=mlb._load();cutoff=(dt.datetime.fromisoformat(p['captured_at'])+dt.timedelta(seconds=1)).isoformat()
        events=mlb.load_schedule(p['slate_date'],cutoff);context=mlb.build_context(events,cutoff)
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,MLB_DRAW_OUTPUT=td):
            result=mlb.forecast_event(events[0],context,1000)
            self.assertEqual(result['diagnostics']['assimilated_results'],311)
            self.assertNotEqual(result['diagnostics']['assimilation_probability_change_pp'],0)
            self.assertFalse(result['diagnostics']['canonical_prospective_eligible'])
            self.assertEqual(len(np.load(Path(result['simulation']['draw_directory'])/'hw.npy')),1000)
            with self.assertRaises(FileExistsError):mlb.forecast_event(events[0],context,1000)
    def test_wrong_slate_and_expired_package_refused(self):
        from pipelines.cards.adapters import mlb
        with self.assertRaisesRegex(ValueError,'SLATE_NOT_ACQUIRED'):mlb.load_schedule('2026-09-15','2026-09-15T20:00:00Z')
        with self.assertRaisesRegex(ValueError,'PACKAGE_EXPIRED'):mlb.load_schedule('2026-09-14','2026-09-15T20:00:00Z')
    def test_generator_preserves_existing_output_directory(self):
        import subprocess,sys
        from pipelines.cards.adapters.mlb import ROOT
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'sentinel';f.write_text('original')
            r=subprocess.run([sys.executable,str(ROOT/'scripts/generate_card_force.py'),'--date','2026-09-14','--league','mlb','--output-dir',td],capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0);self.assertIn('FileExistsError',r.stderr);self.assertEqual(f.read_text(),'original')
