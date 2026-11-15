"""Retained-byte positive controls and rehashed semantic corruption probes."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

import numpy as np

from models.nfl.contextual.recovered_inference import digest
from research.validation_20261110 import cfb_source_check as check


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


class CfbSourceCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = tempfile.TemporaryDirectory()
        cls.fixture = Path(cls.original.name)
        with zipfile.ZipFile(Path(check.__file__).parent / "forward-bundle.zip") as archive:
            for name in archive.namelist():
                if name.startswith("cfb/") or name == "bundle-manifest.json":
                    archive.extract(name, cls.fixture)

    @classmethod
    def tearDownClass(cls):
        cls.original.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "bundle"
        shutil.copytree(self.fixture, self.root)
        self.inputs = Path(self.temporary.name) / "inputs"
        self.inputs.mkdir()
        shutil.copy2(Path(check.__file__).parent / "verification-inputs/cfb-package.json", self.inputs)
        self.card_path = self.root / "cfb/diagnostic_card.json"
        self.card = json.loads(self.card_path.read_bytes())

    def rehash(self):
        """Renew ordinary manifests so rejection depends on source semantics."""
        save(self.card_path, self.card)
        for directory in (self.root / "cfb/draws").glob("*.semantic-v2"):
            manifest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in directory.iterdir() if path.name != "manifest.json"}
            save(directory / "manifest.json", manifest)
        manifest_path = self.root / "bundle-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        for relative in manifest["files"]:
            path = self.root / relative
            if path.is_file():
                manifest["files"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        save(manifest_path, manifest)

    def verify(self):
        return check.verify_cfb(self.root, self.inputs)

    def test_authentic_heads_and_draws_with_independent_scalar_arithmetic(self):
        result = self.verify()
        self.assertEqual(result["analytic_heads_verified"], 6)
        self.assertEqual(result["retained_active_draws_verified"], 450000)
        self.assertEqual(result["new_draws_generated"], 0)
        package = json.loads((self.inputs / "cfb-package.json").read_bytes())
        for row, verified in zip(self.card["forecasts"], result["events"]):
            values = [row["model_input_snapshot"][name] for name in package["feature_names"]]
            for target, field in (("winner", "home_probability"), ("margin", "home_point_margin")):
                head = package["fitted_model"][target]
                z = head["intercept"] + math.fsum(
                    (((head["impute"][i] if value is None else value) - head["mean"][i])
                     / head["scale"][i]) * head["coefficient"][i] for i, value in enumerate(values))
                expected = 1 / (1 + math.exp(-z)) if target == "winner" else z
                self.assertAlmostEqual(verified[field], expected, places=12)

    def test_rehashed_row_mutations(self):
        original = copy.deepcopy(self.card)
        mutations = [
            ("home_team", "Wrong home"), ("away_team", "Wrong away"),
            ("event_id", "CFB:wrong"), ("start_time_utc", "2026-11-11T02:00:00+00:00"),
            ("projected_margin", 5.798437645985379), ("model_p", 0.8), ("analytic_p", 0.8),
            ("sim_p", 0.8), ("stochastic_sim_p", 0.8), ("model_winner", "Kent State"),
            ("input_snapshot_hash", "0" * 64), ("model_state_config_hash", "0" * 64),
            ("forecast_procedure_id", "wrong"), ("feature_procedure_id", "wrong"),
            ("calibration_procedure_id", "wrong"), ("projected_total", 40),
            ("action_authority", True), ("dose", 1),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                self.card = copy.deepcopy(original)
                self.card["forecasts"][0][field] = value
                self.rehash()
                with self.assertRaises(ValueError):
                    self.verify()

    def test_rehashed_diagnostic_and_grading_mutations(self):
        original = copy.deepcopy(self.card)
        for section, field in (("diagnostics", "home_win"), ("diagnostics", "home_margin"),
                               ("grading", "analytic_p_home"), ("grading", "stochastic_sim_p_home")):
            with self.subTest(section=section, field=field):
                self.card = copy.deepcopy(original)
                self.card["forecasts"][0][section][field] = 0.8
                self.rehash()
                with self.assertRaises(ValueError):
                    self.verify()

    def test_coherent_wrong_feature_and_hash(self):
        row = self.card["forecasts"][0]
        row["model_input_snapshot"]["rest_days_diff"] += 1
        row["input_snapshot_hash"] = digest(row["model_input_snapshot"])
        self.rehash()
        with self.assertRaisesRegex(ValueError, "native_features"):
            self.verify()

    def test_coherent_wrong_head_child(self):
        row = self.card["forecasts"][0]
        directory = self.root / "cfb/draws" / (row["event_id"].replace(":", "_") + ".semantic-v2")
        numeric_path = directory / "numeric_inputs.json"
        numeric = json.loads(numeric_path.read_bytes())
        numeric["fitted_state"]["margin"]["intercept"] += 1
        row["projected_margin"] += 1
        row["diagnostics"]["home_margin"] += 1
        numeric["numerical_identity"]["fitted_state_sha256"] = digest(numeric["fitted_state"])
        identity = numeric["numerical_identity"]
        identity["identity_sha256"] = digest({key: value for key, value in identity.items() if key != "identity_sha256"})
        row["numerical_identity"] = copy.deepcopy(identity)
        row["simulation"]["binary"]["seed"] = int(digest({"id": identity["identity_sha256"],
                                                           "kind": identity["engine"], "n": check.DRAW_COUNT})[:16], 16)
        save(numeric_path, numeric)
        self.rehash()
        with self.assertRaisesRegex(ValueError, "point_margin"):
            self.verify()

    def test_substituted_source_model_is_rejected_after_rehash(self):
        source_path = self.inputs / "cfb-package.json"
        package = json.loads(source_path.read_bytes())
        package["fitted_model"]["margin"]["intercept"] += 1
        package["model_sha256"] = digest({"model": package["fitted_model"], "state": package["team_state"],
                                          "parameters": package["parameters"]})
        save(source_path, package)
        self.card["package_binding"]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
        for row in self.card["forecasts"]:
            row["model_state_config_hash"] = package["model_sha256"]
        self.rehash()
        with self.assertRaisesRegex(ValueError, "source_package_version"):
            self.verify()

    def test_rehashed_active_draw_mutation(self):
        row = self.card["forecasts"][0]
        path = self.root / "cfb/draws" / (row["event_id"].replace(":", "_") + ".semantic-v2") / "winner_draws.npy"
        draws = np.load(path, allow_pickle=False)
        draws[0] = 1 - draws[0]
        np.save(path, draws, allow_pickle=False)
        raw_hash = hashlib.sha256(draws.tobytes()).hexdigest()
        row["simulation"]["binary"]["sha256"] = raw_hash
        row["simulation"]["binary"]["home_win_probability"] = float(draws.mean())
        row["simulation"]["draw_sha256"]["winner_draws"] = raw_hash
        row["sim_p"] = row["stochastic_sim_p"] = float(draws.mean())
        self.rehash()
        with self.assertRaisesRegex(ValueError, "active_draw_version"):
            self.verify()

    def test_omission_duplicate_and_cutoff(self):
        original = copy.deepcopy(self.card)
        for mutation in ("omission", "duplicate", "cutoff"):
            with self.subTest(mutation=mutation):
                self.card = copy.deepcopy(original)
                if mutation == "omission":
                    self.card["forecasts"].pop()
                elif mutation == "duplicate":
                    self.card["forecasts"][1] = copy.deepcopy(self.card["forecasts"][0])
                else:
                    self.card["as_of_utc"] = "2026-11-10T13:00:00+00:00"
                self.rehash()
                with self.assertRaises(ValueError):
                    self.verify()

    def test_missing_source(self):
        (self.inputs / "cfb-package.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()

    def test_reordering_and_display_path_are_numerically_invariant(self):
        self.card["forecasts"].reverse()
        self.card["forecasts"][0]["simulation"]["draw_directory"] = "/relocated/display/path"
        self.rehash()
        result = self.verify()
        self.assertEqual({row["event_id"] for row in result["events"]}, set(check.ACTIVE_DRAW_FILES))


if __name__ == "__main__":
    unittest.main()
