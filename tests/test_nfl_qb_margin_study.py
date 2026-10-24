"""Meaningful falsifications for the fixed QB margin study, not sports evidence."""
import copy
import datetime as dt
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from models.common import discrete_research as D

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_nfl_qb_margin_study.py"
spec = importlib.util.spec_from_file_location("nfl_qb_margin_study", SCRIPT)
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def design():
    return {"parent_model_id": S.PARENT, "information_set": S.INFORMATION_SET,
        "settlement": S.SETTLEMENT, "training_seasons": [2019, 2020, 2021, 2022],
        "evaluation_seasons": [2023, 2024, 2025], "scale_features": list(S.SCALE_FEATURES),
        "home_handicaps": list(S.LINES),
        "bootstrap": {"replicates": 2000, "seed": 7192026, "block_length": 4, "unit": "week"},
        "evaluation_fit_as_of_utc": "2023-07-01T00:00:00Z",
        "deployment_fit_as_of_utc": "2026-07-01T00:00:00Z"}


def row(year, index=0):
    start = dt.datetime(year, 9, 1, 20, tzinfo=dt.timezone.utc) + dt.timedelta(days=index)
    return {"event_id": f"{year}_01_A_B_{index}", "season": year, "week": 1,
        "league": "nfl", "product": "margin", "parent_model_id": S.PARENT,
        "information_set": S.INFORMATION_SET, "settlement": S.SETTLEMENT,
        "prediction_kind": "CHRONOLOGICAL_OUT_OF_TIME", "market_input": False,
        "oof": True, "label_in_sample": False, "historical_availability_proven": False,
        "predicted_mean": 4., "observed": 7., "scale_features": {"absolute_parent_margin": 4.},
        "forecast_sha256": D.digest({"event": year, "i": index}), "result_source_sha256": "a" * 64,
        "parent_fit_cutoff": f"{year}-07-01T00:00:00Z",
        "forecast_cutoff": (start - dt.timedelta(hours=1)).isoformat(),
        "start_time_utc": start.isoformat(), "result_available_at": (start + dt.timedelta(days=1)).isoformat()}


def evaluation_row(mid, year=2024, masses=(.2, .3, .5)):
    source = row(year)
    law = D.make_distribution([-7, 0, 7], masses, league="nfl", product="margin", settlement=S.SETTLEMENT,
        model_id=mid, provenance={"event_id": source["event_id"], "cutoff": source["forecast_cutoff"],
            "parent_model_id": S.PARENT, "information_set": S.INFORMATION_SET, "market_input": False,
            "parent_forecast_sha256": source["forecast_sha256"]})
    return {**source, "distribution": law,
            "contracts": [{"line": h, "side": "HOME", "line_role": "DIAGNOSTIC_GRID"} for h in S.LINES]}


class NFLMarginStudyTests(unittest.TestCase):
    def test_design_forbids_posthoc_split_grid_or_bootstrap(self):
        S.check_design(design())
        for mutate in (lambda d: d.update(training_seasons=[2019]),
                       lambda d: d.update(parent_model_id="nfl.integrated_context.combined.v1.research"),
                       lambda d: d.update(home_handicaps=[-7.5]),
                       lambda d: d["bootstrap"].update(seed=42),
                       lambda d: d.update(scale_features=["observed_margin"])):
            bad = design(); mutate(bad)
            with self.assertRaises(ValueError): S.check_design(bad)

    def test_split_rejects_duplicate_mixed_arm_and_fabricated_oof(self):
        rows = [row(2019), row(2022), row(2023), row(2025)]
        train, later, all_rows = S.split_rows(rows, design(), check_counts=False)
        self.assertEqual((len(train), len(later), len(all_rows)), (2, 2, 4))
        for mutate in (lambda r: r.append(copy.deepcopy(r[0])),
                       lambda r: r[0].update(parent_model_id="other"),
                       lambda r: r[0].update(oof=False),
                       lambda r: r[0].update(label_in_sample=True),
                       lambda r: r[0].update(season="2019"),
                       lambda r: r[0].update(historical_availability_proven=True),
                       lambda r: r[0].update(observed=1.5)):
            bad = copy.deepcopy(rows); mutate(bad)
            with self.assertRaises(ValueError): S.split_rows(bad, design(), check_counts=False)

    def test_split_rejects_train_label_leakage_and_observed_scale(self):
        rows = [row(2022), row(2023)]
        bad = copy.deepcopy(rows); bad[0]["result_available_at"] = "2023-08-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "SPLIT_LEAKAGE"):
            S.split_rows(bad, design(), check_counts=False)
        bad = copy.deepcopy(rows); bad[0]["scale_features"]["absolute_parent_margin"] = 7.
        with self.assertRaisesRegex(ValueError, "PARENT_DERIVED"):
            S.split_rows(bad, design(), check_counts=False)

    def test_conditional_nonpush_preserves_push_exclusion_and_zero_support(self):
        p = {"win": .4, "push": .2, "loss": .4}
        self.assertIsNone(S.conditional_nonpush(p, "push"))
        self.assertEqual(S.conditional_nonpush(p, "win")["probability"], .5)
        self.assertEqual(S.conditional_nonpush(p, "win")["brier"], .25)
        q = S.conditional_nonpush({"win": 0, "push": 1, "loss": 0}, "win")
        self.assertEqual(q["status"], "ZERO_NONPUSH_SUPPORT")
        self.assertIsNone(q["log_loss"])

    def test_line_diagnostics_use_same_event_and_correct_key_number_push(self):
        rows = [evaluation_row("a"), evaluation_row("b", masses=(.1, .2, .7))]
        result = S.additional_diagnostics(rows, "a", "b", design()["bootstrap"])
        self.assertTrue(result["cover_ladder_monotonicity"]["all_pass"])
        by_line = {r["home_handicap"]: r for r in result["summaries"]["a"]["by_home_handicap"]}
        self.assertEqual(by_line[-7.]["predicted_push_rate"], .5)
        self.assertEqual(by_line[-7.]["observed_push_rate"], 1.)
        self.assertEqual(by_line[-7.]["conditional_nonpush"]["excluded_pushes"], 1)
        self.assertEqual(by_line[-7.5]["predicted_push_rate"], 0.)
        self.assertEqual(result["paired_deltas_challenger_minus_baseline"]["conditional_nonpush_brier"]["event_n"], 1)

    def test_write_is_immutable_and_nonfinite_json_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "file.json"
            S.write(path, {"ok": True})
            with self.assertRaises(FileExistsError): S.write(path, {})
            path2 = Path(temp) / "bad.json"; path2.write_text('{"p": NaN}')
            with self.assertRaisesRegex(ValueError, "NONFINITE"):
                S.read(path2)

    def test_source_validation_failure_precedes_fit_and_output_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "study"
            with patch.object(S, "read", side_effect=[design(), {"rows": []}]), \
                    patch.object(S, "validate_cohort", side_effect=ValueError("SOURCE_ROW_MISMATCH")), \
                    patch.object(S.D, "fit_residuals") as baseline_fit, \
                    patch.object(S.M, "fit") as candidate_fit:
                with self.assertRaisesRegex(ValueError, "SOURCE_ROW_MISMATCH"):
                    S.run("cohort.json", "design.json", output, prereg_commit="a" * 40)
                baseline_fit.assert_not_called()
                candidate_fit.assert_not_called()
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
