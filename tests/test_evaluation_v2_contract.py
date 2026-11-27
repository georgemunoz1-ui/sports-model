"""Synthetic contract checks; these are not sporting evidence."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema.exceptions import ValidationError
from research.evaluation_v2_contract import SCHEMA, pair_population, validate_row


def row(league="NFL"):
    return {
        "schema_version": "evaluation_row.v2", "league": league, "season": "2026",
        "event_id": league + ":fixture", "model_id": "synthetic.control",
        "arm_id": "A", "procedure_id": "fixture-only", "fitted_state_hash": "a" * 64,
        "forecast_output_hash": "b" * 64,
        "forecast_cutoff_utc": "2026-11-27T12:00:00Z",
        "training_cutoff_utc": "2026-11-26T12:00:00Z",
        "scheduled_start_utc": "2026-11-27T18:00:00Z", "graded_at_utc": "2026-11-28T00:00:00Z",
        "target": {"family": "WINNER", "period": "FULL_GAME", "side": "NONE",
                   "line": None, "settlement_rule": "FIXTURE_ONLY"},
        "forecast_status": "GENERATED", "outcome_status": "DECISIVE", "outcome_value": "HOME",
        "probability_basis": "BINARY_HA", "probabilities": {"HOME": .6, "AWAY": .4},
        "distribution": None, "evidence_scope": "LOCAL_DIAGNOSTIC", "reason_code": None,
        "incumbent_reference_id": None, "expanding_prior_reference_id": None,
        "action_authority": False, "grade_record_hash": "c" * 64,
        "registration_receipt_sha256": None, "actuals": {"home_score": 2, "away_score": 1},
        "point_predictions": {},
    }


class EvaluationV2ContractTests(unittest.TestCase):
    def test_all_eight_league_labels(self):
        self.assertEqual(len(SCHEMA["properties"]["league"]["enum"]), 8)
        for league in SCHEMA["properties"]["league"]["enum"]:
            with self.subTest(league=league):
                validate_row(row(league))

    def test_invalid_probabilities(self):
        for probabilities in ({"HOME": .6, "AWAY": .5}, {"HOME": .6, "DRAW": .4},
                              {"HOME": float("nan"), "AWAY": .4}):
            with self.subTest(probabilities=probabilities), self.assertRaises(ValueError):
                validate_row(dict(row(), probabilities=probabilities))

    def test_poststart_and_training_leakage(self):
        for updates in ({"forecast_cutoff_utc": row()["scheduled_start_utc"]},
                        {"training_cutoff_utc": "2026-11-27T13:00:00Z"}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                validate_row(dict(row(), **updates))

    def test_action_true_is_invalid(self):
        with self.assertRaises(ValidationError):
            validate_row(dict(row(), action_authority=True))

    def test_remote_claim_refused(self):
        with self.assertRaisesRegex(ValueError, "CANONICAL_ATTESTATION"):
            validate_row(dict(row(), evidence_scope="REMOTE_DURABLE_PROSPECTIVE",
                              registration_receipt_sha256="e" * 64))

    def test_push_preserved(self):
        p = row()
        p.update(probability_basis="SETTLEMENT_3", probabilities={"WIN": .4, "PUSH": .2, "LOSS": .4},
                 outcome_status="PUSH", outcome_value="PUSH")
        p["target"].update(family="SPREAD", side="HOME", line=-1)
        validate_row(p)
        self.assertEqual(len(pair_population([p], [copy.deepcopy(p)])), 1)

    def test_blocked_record_preserves_outcome(self):
        p = row()
        q = dict(p, forecast_status="BLOCKED", reason_code="MISSING_SOURCE",
                 fitted_state_hash=None, forecast_output_hash=None,
                 probability_basis=None, probabilities=None)
        self.assertEqual(pair_population([p], [q])[0][1]["forecast_status"], "BLOCKED")
        with self.assertRaises(ValueError):
            validate_row(dict(q, probabilities=p["probabilities"]))

    def test_void_and_unresolved(self):
        v = dict(row(), outcome_status="VOID", outcome_value=None, actuals={})
        validate_row(v)
        u = dict(row(), outcome_status="UNRESOLVED", outcome_value=None,
                 grade_record_hash=None, graded_at_utc=None, actuals={})
        validate_row(u)
        with self.assertRaises(ValueError):
            validate_row(dict(u, outcome_value="HOME"))

    def test_pairing_fails_without_population_or_matching_outcome(self):
        p = row()
        with self.assertRaisesRegex(ValueError, "PAIR_POPULATION"):
            pair_population([p], [])
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            pair_population([p, p], [p])
        with self.assertRaisesRegex(ValueError, "PAIR_OUTCOME"):
            pair_population([p], [dict(p, outcome_value="AWAY")])
        with self.assertRaisesRegex(ValueError, "PAIR_CUTOFF"):
            pair_population([p], [dict(p, forecast_cutoff_utc="2026-11-27T12:01:00Z")])

    def test_distribution_readback_and_tamper(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "draws.json"
            path.write_bytes(b"[1,0,1]")
            d = {"kind": "WINNER_DRAWS", "path": path.name,
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            p = dict(row(), distribution=d)
            validate_row(p, artifact_root=temp)
            path.write_bytes(b"[0,0,0]")
            with self.assertRaisesRegex(ValueError, "DISTRIBUTION_HASH"):
                validate_row(p, artifact_root=temp)
            with self.assertRaisesRegex(ValueError, "PATH_OUTSIDE"):
                validate_row(dict(p, distribution=dict(d, path="../draws.json")), artifact_root=temp)

    def test_inventory_is_source_only(self):
        root = Path(__file__).resolve().parents[1]
        p = root / "docs/research/p0_native_features_20261127/native_feature_inventory.v1.json"
        inv = json.loads(p.read_text(encoding="utf-8"))
        keys = {(r["league"], r["arm_id"], r["feature_name"]) for r in inv["rows"]}
        self.assertEqual(len(inv["rows"]), len(keys))
        self.assertEqual({r["league"] for r in inv["rows"]}, set(SCHEMA["properties"]["league"]["enum"]))
        for r in inv["rows"]:
            self.assertIsNone(r["event_evidence"])
            self.assertIn(r["source"], inv["sources"])
            for stage in ("acquired", "admitted", "consumed", "validated"):
                self.assertEqual(r["lifecycle"][stage], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
