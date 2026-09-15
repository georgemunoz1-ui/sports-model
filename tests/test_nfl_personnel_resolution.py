import copy,json,unittest
from pathlib import Path
from models.nfl.contextual.personnel import final_availability,explain_roles
from models.nfl.contextual.recovered_inference import digest
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.runtime import live_features
R=Path(__file__).resolve().parents[1]
class PersonnelResolution(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.p=json.loads((R/'data/nfl/personnel_resolution_20260914/event_package.json').read_text())
  cls.e=cls.p['events'][0];cls.c=cls.p['event_inputs'][cls.e['event_id']]['context'];cls.s=cls.c['personnel']['state'];cls.cutoff=cls.p['captured_at_utc']
 def test_complete_lists_and_emergency_qbs(self):
  a=final_availability(self.s,self.e,self.cutoff)
  self.assertEqual(a['status'],'VERIFIED');self.assertEqual(len(a['players']),13)
  self.assertEqual(sum(x['emergency_third_qb'] for x in a['players']),2)
 def test_future_capture_refused(self):
  with self.assertRaisesRegex(ValueError,'AFTER_CUTOFF'):final_availability(self.s,self.e,'2026-09-14T20:06:54Z')
 def test_unsubstantiated_verified_label_refused(self):
  with self.assertRaisesRegex(ValueError,'EVIDENCE_REQUIRED'):final_availability({'final_inactives':'VERIFIED'},self.e,self.cutoff)
 def test_hash_and_team_coverage(self):
  s=copy.deepcopy(self.s);s['final_inactive_report']['teams'].pop('DEN')
  with self.assertRaisesRegex(ValueError,'TEAM_COVERAGE'):final_availability(s,self.e,self.cutoff)
  s=copy.deepcopy(self.s);s['final_inactive_report']['rows_sha256']='bad'
  with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):final_availability(s,self.e,self.cutoff)
 def test_inactive_expected_qb_blocks(self):
  s=copy.deepcopy(self.s);s['quarterbacks']['KC']['name']='Garrett Nussmeier'
  with self.assertRaisesRegex(ValueError,'EXPECTED_QB_INACTIVE'):final_availability(s,self.e,self.cutoff)
 def test_roles_disclosed_without_invented_weights(self):
  a=load_artifact(R/'data/nfl/contextual_v1/model_packed.json');r=json.loads((R/'data/nfl/contextual_v1/recovered_parameters.json').read_text())
  base=self.p['event_inputs'][self.e['event_id']]['base']
  features,audit=live_features(a,r,base,self.c,self.e,self.cutoff)
  unknown=[v for v in audit['personnel_absence_roles'] if v['prior_snap_share'] is None]
  self.assertEqual(len(unknown),5);self.assertEqual(features['out_role_unknown_count'],5)
  self.assertTrue(all('source_bound_disposition' in v for v in unknown))
  self.assertEqual(audit['final_inactives'],'VERIFIED')
  old=copy.deepcopy(self.c);old['personnel']['state'].pop('final_inactive_report');old['personnel']['state']['final_inactives']='PENDING'
  old_features,_=live_features(a,r,base,old,self.e,self.cutoff)
  self.assertEqual(features,old_features)
if __name__=='__main__':unittest.main()
