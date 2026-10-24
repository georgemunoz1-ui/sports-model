"""Real-source acceptance tests. Three failures expose current architecture gaps.

Run only with pinned downloaded capture/frozen artifact directories. Outputs are
adversarial diagnostics, never production state. No function is patched/mocked.
"""
import datetime as dt,hashlib,json,os,unittest
from pathlib import Path
import pandas as pd
from models.nfl.contextual import assimilation as ass
from models.nfl.contextual.base_features import TeamState
from models.nfl.contextual.recovered_inference import digest
EVENT='2026_02_DET_BUF'
class LearningAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('NFL_LEARNING_CAPTURE') or not os.environ.get('NFL_LEARNING_FROZEN'):
            raise unittest.SkipTest('Pinned real-source artifact directories required; not a synthetic substitute')
        cls.capture=Path(os.environ['NFL_LEARNING_CAPTURE']);cls.frozen=Path(os.environ['NFL_LEARNING_FROZEN']);cls.output=Path(os.environ['NFL_LEARNING_OUTPUT']);cls.output.mkdir(parents=True,exist_ok=False)
        (cls.output/'SCOPE.txt').write_text('ADVERSARIAL ACCEPTANCE TEST OUTPUTS ONLY. DO NOT INSTALL AS MODEL STATE.\n')
        for root,manifest_name in [(cls.capture,'manifest.json'),(cls.frozen,'completed_manifest.json')]:
            manifest=json.loads((root/manifest_name).read_text())
            for rel,expected in manifest.items():
                p=(root/rel).resolve()
                if not p.is_relative_to(root.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError('INPUT_HASH_MISMATCH:'+rel)
        cls.source=cls.capture/'sources/play_by_play_2026.csv'
        cls.receipt=next(r for r in json.loads((cls.capture/'sources/receipt.json').read_text()) if r['filename']=='play_by_play_2026.csv')
        cls.pbp,_=ass.ingest_pbp_snapshot(cls.source,cls.receipt,cls.output/'snapshots')
        cls.games=pd.read_csv(cls.capture/'sources/games.csv',low_memory=False)
        cls.w1=cls.games[(cls.games.season==2026)&(cls.games.week==1)&(cls.games.game_type=='REG')].copy()
        cls.w2=cls.games[(cls.games.season==2026)&(cls.games.week==2)&(cls.games.game_type=='REG')].copy()
        cls.target=cls.w2[cls.w2.game_id==EVENT].copy();cls.ep=cls.pbp[cls.pbp.game_id==EVENT].copy()
        evidence=json.loads((cls.frozen/'context.json').read_text())['assimilation']
        cls.initial={t:TeamState(**s) for t,s in evidence['state_before'].items()};cls.prior={t:TeamState(**s) for t,s in evidence['state_after'].items()}
        cls.cutoff=dt.datetime.now(dt.timezone.utc).isoformat()
        cls.test_source=cls.output/'target_only.csv';cls.ep.to_csv(cls.test_source,index=False)
        cls.test_receipt={'source_url':'derived:adversarial-test:'+EVENT,'retrieved_at_utc':cls.receipt['retrieved_at_utc'],'sha256':hashlib.sha256(cls.test_source.read_bytes()).hexdigest(),'parent_raw_sha256':cls.receipt['sha256']}
    def run_check(self,name,schedule,prior,source=None,receipt=None):
        return ass.run_nfl_assimilation_check(path=source or self.source,receipt=receipt or self.receipt,schedule=schedule,cutoff=self.cutoff,archive=self.output/'snapshots',output=self.output/name,prior_states=prior)
    def test_complete_week2_schedule_does_not_release_while_pending(self):
        report=self.run_check('normal_full_week',self.w2,self.prior)
        self.assertEqual(len(self.w2),16);self.assertEqual(report['coverage']['reconciled_completed_games'],1)
        self.assertFalse(report['state_update_applied']);self.assertFalse((self.output/'normal_full_week/team_state.json').exists())
    def test_complete_week1_reconstruction_excludes_week2_plays(self):
        expected,_=ass.advance_states(self.initial,self.w1,self.pbp[self.pbp.game_id.isin(self.w1.game_id)])
        report=self.run_check('adversarial_cross_week',self.w1,self.initial)
        actual=json.loads((self.output/'adversarial_cross_week/team_state.json').read_text());expected=ass.serialize_states(expected)
        evidence={'full_schedule_games':len(self.w1),'extra_source_games':report['coverage']['unmatched_source_games'],'expected_state_sha256':digest(expected),'actual_state_sha256':digest(actual),'changed_teams':[t for t in expected if expected[t]!=actual[t]]}
        ass.write_once(self.output/'cross_week_finding.json',evidence)
        self.assertEqual(digest(actual),digest(expected),'Week2 rows changed a complete Week1 reconstruction: '+json.dumps(evidence))
    def test_truncated_authoritative_schedule_must_not_release(self):
        report=self.run_check('adversarial_truncated_schedule',self.target,self.prior,self.test_source,self.test_receipt)
        self.assertFalse(report['state_update_applied'],'Dropped 15 pending games; orchestrator incorrectly accepted one-game schedule as complete')
    def test_repeated_completed_game_must_be_rejected_or_noop(self):
        first,_=ass.advance_states(self.prior,self.target,self.ep)
        report=self.run_check('adversarial_repeat_same_game',self.target,first,self.test_source,self.test_receipt)
        self.assertTrue(not report['state_update_applied'] or report.get('state_before_sha256')==report.get('state_after_sha256'),'The same game updated state a second time instead of rejecting or returning the identical state')
if __name__=='__main__':unittest.main()
