import copy
import json
from pathlib import Path
import unittest
from research.nov11_cross_model.model_disposition_review import (validate_dispositions,read_manifest,DispositionError)

MANIFEST=Path(__file__).resolve().parents[1]/"data/research/nov11_cross_model_dispositions_v1.json"

class ModelDispositionTests(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(MANIFEST.read_text())

    def test_all_eight_leagues_ready_for_review_not_refitting(self):
        got=read_manifest(MANIFEST)
        self.assertEqual(got["model_families"],8)
        self.assertEqual(got["model_numerical_updates"],0)
        self.assertEqual(got["status"],"VALID_RESEARCH_ONLY_WITH_NAMED_BLOCKERS")
        self.assertFalse(got["production_authority"])

    def test_league_missing_refused(self):
        del self.data["leagues"]["WNBA"]
        with self.assertRaisesRegex(DispositionError,"eight league"):
            validate_dispositions(self.data)

    def test_bad_code_ref_refused(self):
        self.data["leagues"]["NFL"]["parent_code_commit"]="abc"
        with self.assertRaisesRegex(DispositionError,"exact code"):
            validate_dispositions(self.data)

    def test_model_update_or_silent_unblock_refused(self):
        self.data["leagues"]["CBB"]["numerical_update_executed"]=True
        with self.assertRaisesRegex(DispositionError,"refit"):
            validate_dispositions(self.data)
        self.data=json.loads(MANIFEST.read_text())
        self.data["leagues"]["NBA"]["model_disposition"]="MODEL_PROMOTED"
        with self.assertRaisesRegex(DispositionError,"must name blocker"):
            validate_dispositions(self.data)

    def test_imagined_authority_and_receipts_refused(self):
        self.data["shared_evaluator"]["wagering_authorized"]=True
        with self.assertRaisesRegex(DispositionError,"wagering_authorized"):
            validate_dispositions(self.data)
        self.data=json.loads(MANIFEST.read_text())
        self.data["leagues"]["NHL"]["registration_receipt_verified"]=True
        with self.assertRaisesRegex(DispositionError,"do not invent"):
            validate_dispositions(self.data)

    def test_unpinned_model_state_must_be_explicit(self):
        self.data["leagues"]["MLS"]["blockers"]=[]
        with self.assertRaisesRegex(DispositionError,"blocker accounting"):
            validate_dispositions(self.data)

    def test_precise_sha256_checks(self):
        self.data["leagues"]["NFL"]["parent_input_manifest_sha256"]="not-a-sha"
        with self.assertRaisesRegex(DispositionError,"malformed"):
            validate_dispositions(self.data)

if __name__=="__main__": unittest.main()
