"""Synthetic software checks only: no result below is predictive validation."""
import copy
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from models.common import discrete_research as D
from models.common import discrete_calibration as C
from pipelines.cards.distribution_research import build, load_config, point, nfl_card
from research.evaluate_discrete_products import evaluate

H = "a" * 64
CUTOFF = "2026-10-01T00:00:00Z"
START = "2026-10-01T03:00:00Z"
FITTED = "2026-09-01T00:00:00Z"


def training(league="nfl", product="margin", settlement=None):
    settlement = settlement or next(iter(D.SETTLEMENTS[league]))
    rows = []
    for i in range(60):
        day = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i)
        predicted = 5. if product == "margin" else 20.
        rows.append({"event_id": f"train-{i}", "league": league, "product": product,
            "settlement": settlement, "parent_model_id": "parent.v1", "information_set": "PREGAME",
            "market_input": False, "forecast_sha256": H, "result_source_sha256": H,
            "prediction_kind": "CHRONOLOGICAL_OUT_OF_TIME", "parent_fit_cutoff": "2025-12-01T00:00:00Z",
            "forecast_cutoff": day.isoformat(), "start_time_utc": (day+dt.timedelta(hours=1)).isoformat(),
            "result_available_at": (day+dt.timedelta(hours=6)).isoformat(),
            "predicted_mean": predicted, "observed": predicted + [-3, -2, -1, 1, 2, 3][i % 6],
            "scale_features": {"pace": float(i % 10), "uncertainty": float(i % 2)}})
    return rows


def fitted(league="nfl", product="margin", **extra):
    settlement = next(iter(D.SETTLEMENTS[league]))
    return D.fit_residuals(training(league, product), league=league, product=product, settlement=settlement,
                           parent_model_id="parent.v1", fitted_at=FITTED, information_set="PREGAME", **extra)


def distribution(values=(-3, 0, 3, 7), weights=(.2, .1, .4, .3), mid="baseline", league="nfl", product="margin", eid="future"):
    return D.make_distribution(list(values), list(weights), league=league, product=product,
        settlement=next(iter(D.SETTLEMENTS[league])), model_id=mid,
        provenance={"event_id": eid, "cutoff": CUTOFF})


class SettlementTests(unittest.TestCase):
    def test_all_sport_profiles(self):
        for league, profiles in D.SETTLEMENTS.items():
            for settlement, ties in profiles.items():
                with self.subTest(league=league, settlement=settlement):
                    d = D.make_distribution([-3, 3, 7], [1, 2, 1], league=league, product="margin",
                                            settlement=settlement, model_id="fixture", provenance={})
                    p = D.price(d, -3, "HOME")
                    self.assertEqual(p, dict(win=.25, half_win=0., push=.5, half_loss=0., loss=.25))
                    self.assertEqual(D.price(d, -3, "AWAY"), p)
                    self.assertAlmostEqual(sum(D.price(d, -3.5, "HOME").values()), 1.)
                    self.assertEqual(D.price(d, -3.5, "HOME")["push"], 0.)
                    if not ties:
                        with self.assertRaises(ValueError):
                            D.make_distribution([0], [1], league=league, product="margin", settlement=settlement, model_id="fixture", provenance={})

    def test_monotone_and_complementary(self):
        d = distribution()
        probs = [D.price(d, float(h)/2, "HOME")["win"] for h in range(-20, 21)]
        self.assertEqual(probs, sorted(probs))
        for h in range(-10, 11):
            a, b = D.price(d, h, "HOME"), D.price(d, h, "AWAY")
            self.assertAlmostEqual(a["win"], b["loss"])
            self.assertAlmostEqual(a["push"], b["push"])

    def test_quarter_line_payoffs(self):
        d = distribution([0, 1], [.4, .6], league="mls")
        self.assertEqual(D.price(d, -.25, "HOME"), dict(win=.6, half_win=0., push=0., half_loss=.4, loss=0.))
        self.assertEqual(D.price(d, .25, "HOME"), dict(win=.6, half_win=.4, push=0., half_loss=0., loss=0.))
        t = distribution([2, 3], [.4, .6], league="mls", product="total")
        self.assertEqual(D.price(t, 2.25, "OVER")["half_loss"], .4)
        self.assertEqual(D.price(t, 2.25, "UNDER")["half_win"], .4)
        with self.assertRaises(ValueError):
            D.price(distribution(), -.25, "HOME")

    def test_invalid_support_mass_and_lines(self):
        for values, weights in [([True], [1]), ([.5], [1]), ([1], [-1]), ([1], [float("nan")]), ([], [])]:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    distribution(values, weights)
        for line in [True, float("inf"), 1.1]:
            with self.assertRaises(ValueError):
                D.price(distribution(), line, "HOME")
        for side in ["OVER", "home", ""]:
            with self.assertRaises(ValueError):
                D.price(distribution(), 0., side)
        bad = distribution(); bad["masses"][0] = .4
        with self.assertRaises(ValueError):
            D.validate(bad)

    def test_crps_matches_bruteforce(self):
        d = distribution(); x, p = D.validate(d)
        expected = np.sum(p*np.abs(x-2)) - .5*np.sum(p[:, None]*p[None, :]*np.abs(x[:, None]-x[None, :]))
        self.assertAlmostEqual(D.score(d, 2)["crps"], expected)
        self.assertTrue(D.score(d, 2)["zero_probability_outcome"])

    def test_simulation_replay_and_true_frequency(self):
        d = distribution()
        a, meta = D.simulate(d); b, again = D.simulate(d)
        self.assertTrue(np.array_equal(a, b)); self.assertEqual(meta, again)
        self.assertEqual(meta["count"], 100000)
        self.assertLess(abs(np.mean(a == 3)-.4), .008)
        for n in [True, 0, 1000001, 1.5]:
            with self.assertRaises(ValueError):
                D.simulate(d, draws=n)


class FitTests(unittest.TestCase):
    def test_both_methods_all_sports_products(self):
        for league in D.SETTLEMENTS:
            for product in ["margin", "total"]:
                for method in ["empirical", "conditional_scale"]:
                    with self.subTest(league=league, product=product, method=method):
                        m = fitted(league, product, method=method,
                                   scale_features=["pace", "uncertainty"] if method == "conditional_scale" else [])
                        d = D.predict(m, mean=5.25 if product == "margin" else 20.25, event_id="future", cutoff=CUTOFF,
                                      parent_model_id="parent.v1", information_set="PREGAME", parent_forecast_sha256=H,
                                      scale_features={"pace": 3., "uncertainty": 1.})
                        x, p = D.validate(d)
                        self.assertAlmostEqual(sum(p), 1.)
                        self.assertFalse(d["action_authority"])
                        self.assertFalse(d["provenance"]["joint_score_distribution"])

    def test_no_future_or_reused_events(self):
        m = fitted()
        args = dict(mean=5., event_id="future", cutoff=CUTOFF, parent_model_id="parent.v1", information_set="PREGAME", parent_forecast_sha256=H)
        for update in [{"cutoff": "2026-08-01T00:00:00Z"}, {"event_id": "train-1"}, {"parent_model_id": "wrong"}, {"information_set": "LIVE"}, {"mean": True}]:
            with self.assertRaises(ValueError):
                D.predict(m, **{**args, **update})
        bad = copy.deepcopy(m); bad["residuals"][0] += 1
        with self.assertRaises(ValueError):
            D.predict(bad, **args)

    def test_training_refusals(self):
        for field, value in [("forecast_cutoff", START), ("parent_fit_cutoff", START), ("result_available_at", START),
                             ("prediction_kind", "IN_SAMPLE"), ("settlement", "REGULATION"),
                             ("forecast_sha256", "missing"), ("market_input", True)]:
            r = training(); r[0][field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    D.fit_residuals(r, league="nfl", product="margin", settlement="FULL_GAME_OT_REGULAR", parent_model_id="parent.v1", fitted_at=FITTED, information_set="PREGAME")
        with self.assertRaises(ValueError):
            fitted(method="conditional_scale", scale_features=["closing_line"])

    def test_conditional_scale_changes_distribution(self):
        m = fitted(method="conditional_scale", scale_features=["pace", "uncertainty"])
        args = dict(mean=5., event_id="future", cutoff=CUTOFF, parent_model_id="parent.v1", information_set="PREGAME", parent_forecast_sha256=H)
        a = D.predict(m, scale_features={"pace": 0., "uncertainty": 0.}, **args)
        b = D.predict(m, scale_features={"pace": 9., "uncertainty": 1.}, **args)
        self.assertNotEqual(a["distribution_sha256"], b["distribution_sha256"])

    def test_market_informed_identity_is_explicit(self):
        r = training()
        for row in r:
            row["market_input"] = True
        for row in r:
            row["parent_model_id"] = "market.parent"
        m = D.fit_residuals(r, league="nfl", product="margin", settlement="FULL_GAME_OT_REGULAR", parent_model_id="market.parent", fitted_at=FITTED, information_set="PREGAME", market_input=True)
        self.assertTrue(m["market_input"])


class ScenarioCalibrationTests(unittest.TestCase):
    def test_mixture_and_bad_bindings(self):
        a, b = distribution([-3, 3], [.2, .8]), distribution([-3, 3], [.8, .2])
        scenarios = [{"scenario_id": "active", "weight": .75, "source_sha256": H, "observed_at_utc": CUTOFF, "retrieved_at_utc": CUTOFF, "distribution": a},
                     {"scenario_id": "out", "weight": .25, "source_sha256": H, "observed_at_utc": CUTOFF, "retrieved_at_utc": CUTOFF, "distribution": b}]
        d = D.mix(scenarios, cutoff=CUTOFF, model_id="mixture")
        self.assertAlmostEqual(D.price(d, 0., "HOME")["win"], .65)
        for field, value in [("weight", .4), ("observed_at_utc", START), ("scenario_id", "active")]:
            bad = copy.deepcopy(scenarios); bad[1][field] = value
            with self.assertRaises(ValueError):
                D.mix(bad, cutoff=CUTOFF, model_id="mixture")

    def test_calibration_fit_and_future_refusal(self):
        rows = []
        for i in range(40):
            rows.append({"distribution": distribution([-3, 3], [.2, .8], eid=f"c{i}"), "observed": -3 if i % 2 else 3,
                         "start_time_utc": START, "result_available_at": "2026-10-01T07:00:00Z", "result_source_sha256": H})
        m = C.fit(rows, fitted_at="2026-10-02T00:00:00Z")
        fresh = distribution([-3, 3], [.2, .8]); fresh["provenance"]["cutoff"] = "2026-10-03T00:00:00Z"
        fresh["distribution_sha256"] = D.digest({k:v for k,v in fresh.items() if k != "distribution_sha256"})
        d = C.apply(fresh, m)
        self.assertAlmostEqual(D.price(d, 0., "HOME")["win"], .5, places=3)
        with self.assertRaises(ValueError):
            C.apply(rows[0]["distribution"], m)
        with self.assertRaises(ValueError):
            C.apply(distribution([-3, 3], [.2, .8]), m)


class EvaluationTests(unittest.TestCase):
    def rows(self):
        result = []
        for i in range(12):
            for mid, p in [("baseline", .8), ("challenger", .6)]:
                result.append({"distribution": distribution([-3, 3], [1-p, p], mid=mid, eid=f"eval{i}"),
                    "contract": {"line": 0., "side": "HOME"}, "observed": 3 if i % 2 else -3,
                    "start_time_utc": START, "result_available_at": "2026-10-01T07:00:00Z",
                    "result_source_sha256": H, "block_id": str(i//2)})
        return result

    def test_paired_scores_and_duplicate_rejection(self):
        rows = self.rows(); r = evaluate(rows, baseline_id="baseline", challenger_id="challenger", bootstrap=100)
        self.assertEqual(r["matched_game_n"], 12)
        self.assertLess(r["paired_challenger_minus_baseline"]["brier_category_sum"]["delta"], 0)
        self.assertIsNotNone(r["paired_challenger_minus_baseline"]["brier_category_sum"]["ci95"])
        self.assertIsNone(r["summaries"]["baseline"]["mean_flat_stake_return"])
        with self.assertRaises(ValueError):
            evaluate(rows+[rows[0]], baseline_id="baseline", challenger_id="challenger", bootstrap=100)

    def test_result_mismatch_and_unmatched_visibility(self):
        rows = self.rows(); rows[1]["observed"] = 7
        with self.assertRaises(ValueError):
            evaluate(rows, baseline_id="baseline", challenger_id="challenger", bootstrap=100)
        r = evaluate(self.rows()[1:], baseline_id="baseline", challenger_id="challenger", bootstrap=100)
        self.assertEqual(r["unmatched_contract_n"]["challenger"], 1)

    def test_exact_quote_and_price_benchmark(self):
        rows = self.rows()
        for r in rows:
            r["contract"]["quote"] = {"event_id": r["distribution"]["provenance"]["event_id"], "line": 0., "side": "HOME",
                "settlement": "FULL_GAME_OT_REGULAR", "source_sha256": H, "book": "synthetic",
                "observed_at_utc": CUTOFF, "retrieved_at_utc": CUTOFF, "decimal_odds": 21/11, "opposing_decimal_odds": 21/11}
        report = evaluate(rows, baseline_id="baseline", challenger_id="challenger", bootstrap=100)
        self.assertEqual(report["summaries"]["baseline"]["market_nonpush_n"], 12)
        self.assertAlmostEqual(report["summaries"]["baseline"]["market_conditional_brier"], .25)
        rows[0]["contract"]["quote"]["observed_at_utc"] = START
        with self.assertRaises(ValueError):
            evaluate(rows, baseline_id="baseline", challenger_id="challenger", bootstrap=100)

    def test_alternate_lines_do_not_inflate_game_count(self):
        rows = self.rows(); extra = copy.deepcopy(rows)
        for r in extra:
            r["contract"]["line"] = .5
        report = evaluate(rows+extra, baseline_id="baseline", challenger_id="challenger", bootstrap=100)
        self.assertEqual(report["matched_contract_n"], 24)
        self.assertEqual(report["matched_game_n"], 12)
        self.assertEqual(report["paired_challenger_minus_baseline"]["brier_category_sum"]["game_n"], 12)


class CardTests(unittest.TestCase):
    def card(self, league):
        return {"league": league.upper(), "as_of_utc": CUTOFF, "generated_at_utc": "2026-10-01T00:01:00Z",
                "forecasts": [{"event_id": "future", "forecast_status": "FORECAST_GENERATED", "model_id": "parent.v1",
                    "home_team": "H", "away_team": "A", "start_time_utc": START, "model_winner": "A",
                    "input_snapshot_hash": H, "model_state_config_hash": H,
                    "diagnostics": {"home_margin": 5., "total": 20.}, "model_input_snapshot": {}, "warnings": ["SOURCE_LIMIT"]}]}

    def test_end_to_end_all_sports_with_retained_100k_draws(self):
        for league in D.SETTLEMENTS:
            with self.subTest(league=league), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); entries=[]
                for product in ["margin", "total"]:
                    raw = json.dumps(fitted(league, product)); (p/(product+".json")).write_text(raw)
                    entries.append({"path": product+".json", "sha256": hashlib.sha256(raw.encode()).hexdigest()})
                config = {"schema": "sports.distribution_card_config.research.v1", "information_set": "PREGAME", "action_authority": False,
                          "models": entries, "contracts": [{"event_id": "future", "product": "margin", "settlement": next(iter(D.SETTLEMENTS[league])),
                                                            "line": -3., "side": "HOME", "kind": "HYPOTHETICAL"}]}
                (p/"config.json").write_text(json.dumps(config)); original = self.card(league); before = D.digest(original)
                result = build(original, load_config(p/"config.json"), p/"out")
                self.assertEqual(before, D.digest(original)); self.assertEqual(len(result["results"]), 2)
                self.assertTrue(all(r["status"] == "COMPLETED" for r in result["coverage"]))
                for r in result["results"]:
                    f = p/"out"/r["simulation"]["file"]; a = np.load(f, allow_pickle=False)
                    self.assertEqual(len(a), 100000)
                    self.assertEqual(hashlib.sha256(a.tobytes()).hexdigest(), r["simulation"]["draw_sha256"])
                    self.assertEqual(hashlib.sha256(f.read_bytes()).hexdigest(), r["simulation"]["file_sha256"])
                again = build(original, load_config(p/"config.json"), p/"again")
                self.assertEqual(result["results"], again["results"])
                with self.assertRaises(FileExistsError):
                    build(original, load_config(p/"config.json"), p/"out")

    def test_orientation_and_nfl_independent_heads(self):
        row = self.card("nfl")["forecasts"][0]
        row["diagnostics"] = {"prediction": {"home_margin": -4., "total_points": 47.}}
        self.assertEqual(point(row, "margin"), -4.)
        self.assertEqual(point(row, "total"), 47.)
        row["diagnostics"] = {}; row["projected_margin"] = 4.
        with self.assertRaises(ValueError):
            point(row, "margin")
        row["projected_margin_orientation"] = "WINNER_MINUS_OPPONENT"
        self.assertEqual(point(row, "margin"), -4.)
        row.pop("projected_margin")
        with self.assertRaises(ValueError):
            point(row, "margin")

    def test_cli_help(self):
        root = Path(__file__).resolve().parents[1]
        r = subprocess.run([sys.executable, str(root/"scripts/cross_sport_distribution_research.py"), "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_nfl_bridge_preserves_parent_and_rejects_live(self):
        original = {"schema": "nfl.integrated_context_forecast.v1", "mode": "research_pregame", "event": {
            "event_id": "future", "start_time_utc": START, "home_team": "H", "away_team": "A"},
            "cutoff_utc": CUTOFF, "model_id": "parent.v1", "features": {"x": 1.},
            "model_artifact_sha256": H, "prediction": {"home_margin": 3., "total_points": 47.}, "market_input": False}
        before = copy.deepcopy(original)
        card = nfl_card(original, "2026-10-01T00:01:00Z")
        self.assertEqual(original, before)
        self.assertEqual(point(card["forecasts"][0], "margin"), 3.)
        with self.assertRaises(ValueError):
            nfl_card({**original, "mode": "live"}, CUTOFF)

    def test_missing_fit_and_head_are_visible_and_parent_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = self.card("cfb"); before = D.digest(card)
            cfg = {"config_file_sha256": H, "information_set": "PREGAME", "loaded_models": []}
            r = build(card, cfg, Path(tmp)/"one", simulations=100)
            self.assertEqual(r["coverage"][0]["status"], "FIT_REQUIRED")
            cfg["loaded_models"] = [{"model": fitted("cfb", "total"), "calibrator": None}]
            card["forecasts"][0]["diagnostics"].pop("total")
            r = build(card, cfg, Path(tmp)/"two", simulations=100)
            self.assertIn("POINT_HEAD_UNAVAILABLE", r["coverage"][0]["reason"])
            self.assertEqual(r["results"], [])

    def test_bad_event_does_not_stop_other_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = self.card("nfl"); bad = copy.deepcopy(card["forecasts"][0]); bad["event_id"] = "bad"
            bad["input_snapshot_hash"] = "bad-hash"; card["forecasts"].insert(0, bad)
            cfg = {"config_file_sha256": H, "information_set": "PREGAME", "loaded_models": [{"model": fitted(), "calibrator": None}]}
            r = build(card, cfg, Path(tmp)/"out", simulations=100)
            self.assertEqual([x["status"] for x in r["coverage"]], ["UNAVAILABLE", "COMPLETED"])

    def test_hash_substitution_and_market_role_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); (p/"model.json").write_text(json.dumps(fitted()))
            cfg = {"schema": "sports.distribution_card_config.research.v1", "action_authority": False,
                   "models": [{"path": "model.json", "sha256": H}], "information_set": "PREGAME"}
            (p/"config.json").write_text(json.dumps(cfg))
            with self.assertRaises(ValueError):
                load_config(p/"config.json")
            card = self.card("nfl"); card["forecasts"][0]["diagnostics"]["market_input"] = True
            r = build(card, {"config_file_sha256": H, "information_set": "PREGAME", "loaded_models": [{"model": fitted(), "calibrator": None}]}, p/"out", simulations=100)
            self.assertEqual(r["coverage"][0]["reason"], "PARENT_MARKET_ROLE_MISMATCH")

    def test_optional_failure_preserves_all_parent_card_files(self):
        from scripts import generate_card_force as G
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); card = self.card("nfl"); card["coverage_breach_event_ids"] = []
            for name, config in [("base", []), ("bad", ["--distribution-research-config", str(p/"missing.json")])]:
                args = ["generate_card_force", "--date", "2026-10-01", "--league", "nfl", "--output-dir", str(p/name)] + config
                with patch.object(sys, "argv", args), patch.object(G, "generate", return_value=card), patch.object(G, "render_md", return_value="fixture"), patch("builtins.print"):
                    with self.assertRaises(SystemExit) as exc:
                        G.main()
                    self.assertEqual(exc.exception.code, 2 if config else 0)
            for name in ["diagnostic_card.json", "diagnostic_card.md", "diagnostic_card.csv"]:
                self.assertEqual((p/"base"/name).read_bytes(), (p/"bad"/name).read_bytes())
            self.assertTrue((p/"bad/distribution_research_failure.json").exists())

    def test_cli_fit_and_immutable_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); payload = {"rows": training(), "league": "nfl", "product": "margin",
                "settlement": "FULL_GAME_OT_REGULAR", "parent_model_id": "parent.v1", "information_set": "PREGAME", "fitted_at": FITTED}
            (p/"input.json").write_text(json.dumps(payload))
            cmd = [sys.executable, str(Path(__file__).resolve().parents[1]/"scripts/cross_sport_distribution_research.py"), "fit", "--input", str(p/"input.json"), "--output", str(p/"fit.json")]
            r = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr); before = (p/"fit.json").read_bytes()
            self.assertIn("created_at_utc", json.loads(before))
            again = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0); self.assertEqual(before, (p/"fit.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
