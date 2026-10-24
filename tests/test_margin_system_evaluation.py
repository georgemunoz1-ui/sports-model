import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from models.common import discrete_research as D
from research.evaluate_margin_system import evaluate, main, score_row


def row(model="baseline", event=0, masses=(.2, .3, .5), observed=1):
    start = dt.datetime(2025, 1, 1, 20, tzinfo=dt.timezone.utc) + dt.timedelta(days=event*7)
    provenance = {"event_id": str(event), "cutoff": (start-dt.timedelta(hours=1)).isoformat(),
        "parent_model_id": "parent.v1", "parent_forecast_sha256": D.digest({"event": event}),
        "information_set": "TEST_ONLY", "market_input": False,
        "artifact_existed_at_forecast_cutoff": False}
    return {"distribution": D.make_distribution([-1, 0, 1], masses, league="mls",
        product="margin", settlement="REGULATION_90_STOPPAGE", model_id=model, provenance=provenance),
        "observed": observed, "start_time_utc": start.isoformat(),
        "parent_fit_cutoff": "2024-01-01T00:00:00Z",
        "result_available_at": (start+dt.timedelta(hours=3)).isoformat(),
        "result_source_sha256": "a"*64,
        "contracts": [{"line": 0, "side": "HOME"}, {"line": -.25, "side": "HOME"}]}


def alter_provenance(r, **changes):
    d = r["distribution"]
    d["provenance"].update(changes)
    d["distribution_sha256"] = D.digest({k: v for k, v in d.items() if k != "distribution_sha256"})


class MarginEvaluationTests(unittest.TestCase):
    def test_exact_distribution_metrics(self):
        score = score_row(row())
        self.assertAlmostEqual(score["mean"], .3)
        self.assertAlmostEqual(score["absolute_error"], .7)
        self.assertAlmostEqual(score["crps"], .29)
        self.assertAlmostEqual(score["squared_error"], .49)
        self.assertEqual(score["intervals"]["0.9"]["width"], 2)

    def test_zero_support_is_infinite_not_clipped(self):
        r = row(masses=(.5, .5, 0))
        report = evaluate([r])
        score = report["summaries_all_available"]["baseline"]["distribution_log_score"]
        self.assertEqual(score["zero_probability_outcomes"], 1)
        self.assertEqual(score["status"], "INFINITE_ZERO_SUPPORT")
        self.assertIsNone(score["mean"])
        json.dumps(report, allow_nan=False)

    def test_pairing_bootstrap_reproducible_and_no_promotion(self):
        rows = [row(mid, i, (.2, .3, .5) if mid == "baseline" else (.1, .2, .7))
                for i in range(8) for mid in ("baseline", "challenger")]
        a = evaluate(rows, baseline_id="baseline", challenger_id="challenger", bootstrap=100)
        b = evaluate(rows, baseline_id="baseline", challenger_id="challenger", bootstrap=100)
        self.assertEqual(a, b)
        self.assertEqual(a["paired"]["matched_event_n"], 8)
        delta = a["paired"]["deltas_challenger_minus_baseline"]["crps"]
        self.assertEqual(delta["status"], "AVAILABLE")
        self.assertLess(delta["delta"], 0)
        self.assertFalse(a["promotion_authority"])

    def test_future_parent_and_post_start_forecast_rejected(self):
        r = row()
        r["parent_fit_cutoff"] = "2026-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "CHRONOLOGY"):
            evaluate([r])
        r = row()
        alter_provenance(r, cutoff=r["start_time_utc"])
        with self.assertRaisesRegex(ValueError, "CHRONOLOGY"):
            evaluate([r])

    def test_future_distribution_fit_rejected(self):
        r = row()
        r["distribution_fit_cutoff"] = "2026-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "FUTURE_DISTRIBUTION"):
            evaluate([r])

    def test_duplicate_event_model_rejected(self):
        r = row()
        with self.assertRaisesRegex(ValueError, "DUPLICATE_EVENT"):
            evaluate([r, copy.deepcopy(r)])

    def test_different_parent_hash_rejected(self):
        a, b = row(), row("challenger")
        alter_provenance(b, parent_forecast_sha256="b"*64)
        with self.assertRaisesRegex(ValueError, "PAIRED_PARENT_FORECAST"):
            evaluate([a, b], baseline_id="baseline", challenger_id="challenger")

    def test_result_mismatch_rejected(self):
        a, b = row(), row("challenger", observed=-1)
        with self.assertRaisesRegex(ValueError, "RESULT_BINDING"):
            evaluate([a, b], baseline_id="baseline", challenger_id="challenger")

    def test_cutoff_mismatch_visible_unmatched(self):
        a, b = row(), row("challenger")
        alter_provenance(b, cutoff="2025-01-01T18:00:00Z")
        report = evaluate([a, b], baseline_id="baseline", challenger_id="challenger")
        self.assertEqual(report["paired"]["matched_event_n"], 0)
        self.assertEqual(report["paired"]["unmatched_forecasts"]["baseline"][0]["reason"], "CUTOFF_MISMATCH")

    def test_unmatched_event_coverage_visible(self):
        report = evaluate([row(), row("challenger"), row(event=1)],
                          baseline_id="baseline", challenger_id="challenger")
        self.assertEqual(report["paired"]["paired_coverage"]["baseline"], .5)
        self.assertEqual(report["paired"]["unmatched_contract_n"]["baseline"], 2)

    def test_scope_parent_or_market_role_mismatch_rejected(self):
        for changes in ({"parent_model_id": "other"}, {"market_input": True},
                        {"information_set": "other"}):
            a, b = row(), row("challenger")
            alter_provenance(b, **changes)
            with self.assertRaisesRegex(ValueError, "SEPARATE_LEAGUE"):
                evaluate([a, b], baseline_id="baseline", challenger_id="challenger")

    def test_mixed_sports_never_pool(self):
        a, b = row(), row("challenger")
        b["distribution"] = D.make_distribution([-1, 1], [.4, .6], league="nba",
            product="margin", settlement="FULL_GAME_OT", model_id="challenger",
            provenance=b["distribution"]["provenance"])
        with self.assertRaisesRegex(ValueError, "SEPARATE_LEAGUE"):
            evaluate([a, b], baseline_id="baseline", challenger_id="challenger")

    def test_parent_fit_cutoff_mismatch_rejected(self):
        a, b = row(), row("challenger")
        b["parent_fit_cutoff"] = "2024-01-02T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "PAIRED_PARENT_FIT"):
            evaluate([a, b], baseline_id="baseline", challenger_id="challenger")

    def test_nonfinite_inputs_and_tampered_mass_rejected(self):
        r = row()
        r["observed"] = float("nan")
        with self.assertRaisesRegex(ValueError, "FINITE_NUMBER"):
            evaluate([r])
        r = row()
        r["distribution"]["masses"][0] += .01
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
            evaluate([r])

    def test_duplicate_contract_rejected(self):
        r = row()
        r["contracts"].append(dict(r["contracts"][0]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_CONTRACT"):
            evaluate([r])

    def test_explicit_contract_metadata_cannot_contradict_distribution(self):
        for key, value in (("settlement", "WRONG"), ("event_id", "other"),
                           ("product", "total"), ("orientation", "AWAY_MINUS_HOME"),
                           ("period", "FIRST_HALF"), ("line_orientation", "AWAY_HANDICAP")):
            r = row()
            r["contracts"][0][key] = value
            with self.assertRaisesRegex(ValueError, "CONTRACT_(TARGET_METADATA|PERIOD)_MISMATCH"):
                score_row(r)

    def test_explicit_distribution_orientation_rejected(self):
        r = row()
        alter_provenance(r, orientation="AWAY_MINUS_HOME")
        with self.assertRaisesRegex(ValueError, "DISTRIBUTION_ORIENTATION"):
            score_row(r)

    def test_quarter_line_push_is_half_loss(self):
        r = row(observed=0)
        report = evaluate([r])
        c = report["summaries_all_available"]["baseline"]["contracts"]
        self.assertEqual(c["outcome_counts"]["push"], 1)
        self.assertEqual(c["outcome_counts"]["half_loss"], 1)
        self.assertEqual(sum(x["n"] for x in c["push"]["reliability"]), 2)

    def test_observed_market_quote_required(self):
        r = row()
        r["contracts"][0]["line_role"] = "OBSERVED_MARKET"
        with self.assertRaisesRegex(ValueError, "REQUIRES_QUOTE"):
            evaluate([r])

    def test_future_quote_rejected(self):
        r = row()
        r["contracts"][0]["quote"] = {"book": "test", "source_sha256": "b"*64,
            "observed_at_utc": "2025-01-01T19:30:00Z", "retrieved_at_utc": "2025-01-01T19:31:00Z",
            "event_id": "0", "settlement": "REGULATION_90_STOPPAGE", "line": 0, "side": "HOME"}
        with self.assertRaisesRegex(ValueError, "QUOTE_CHRONOLOGY"):
            evaluate([r])

    def test_different_contract_lines_do_not_pair(self):
        a, b = row(), row("challenger")
        b["contracts"] = [{"line": 1.5, "side": "HOME"}]
        report = evaluate([a, b], baseline_id="baseline", challenger_id="challenger")
        self.assertEqual(report["paired"]["matched_contract_n"], 0)
        self.assertEqual(report["paired"]["unmatched_contract_n"], {"baseline": 2, "challenger": 1})

    def test_cli_new_file_only(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp)/"rows.json", Path(temp)/"report.json"
            source.write_text(json.dumps([row()]))
            args = ["--rows", str(source), "--output", str(output)]
            self.assertEqual(main(args), 0)
            with self.assertRaises(FileExistsError):
                main(args)


if __name__ == "__main__":
    unittest.main()
