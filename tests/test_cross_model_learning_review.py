"""Zero external dependencies; exercises the opt-in cross-model research contract."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.cross_model_learning_review import (
    LEAGUES, ReviewError, audit_observation, cohort_summary, expected_return,
    paired_novig, personnel_asof, preferred_side, purchase_probability,
)


def row(**overrides):
    base = {
        "league": "CFB", "product": "MONEYLINE", "event_id": "CFB:20261111-BUF-BSU",
        "model_id": "cfb.incumbent.shadow", "arm_id": "winner.v1",
        "forecast_cutoff_utc": "2026-11-11T16:12:00Z",
        "start_time_utc": "2026-11-12T00:30:00Z",
        "protocol_registered_at_utc": None,
        "model_p_win": 0.673056, "model_p_push": 0.0,
        "sim_p_win": 0.6721, "simulation_draws": 100000,
        "quote": {"american": -122,"retrieved_at_utc":"2026-11-11T16:16:17Z",
                  "provider_asof_utc": None,"book":"DraftKings",
                  "market_key":"ML","period":"FULL_GAME_OT"},
        "observed_result": "WIN", "final_source_sha256": "source_digest_placeholder",
        "product_supported": True,
        "action_authority": False, "stake_units": 0,
        "personnel_source_consumed": False, "red_flags": [],
    }
    base.update(overrides)
    return base


class CrossModelReviewTests(unittest.TestCase):
    def test_eight_league_research_queues_and_no_action(self):
        self.assertEqual(len(LEAGUES), 8)
        for league in sorted(LEAGUES):
            r = row(league=league)
            if league == "MLS":
                r["draw_mode"] = "TWO_WAY_CONTRACT_EXPLICIT"
            result = audit_observation(r)
            self.assertEqual(result["decision"], "NO_PICK")
            self.assertEqual(result["official_stake_units"], 0)
            self.assertTrue(result["review_queue"])
            self.assertFalse(result["action_authority"])

    def test_moneyline_ev_hurdle_and_sim_gap(self):
        x = audit_observation(row())
        self.assertAlmostEqual(x["purchase_break_even"], 122/222)
        self.assertAlmostEqual(x["paper_ev_per_unit"],0.673056*(100/122)-0.326944)
        self.assertAlmostEqual(x["sim_minus_model_pp"],-0.0956)
        self.assertEqual(x["paired_market_no_vig_decisive"],None)

    def test_no_vig_not_the_purchase_hurdle(self):
        self.assertAlmostEqual(paired_novig(-122,+102),
            (122/222)/((122/222)+(100/202)))
        self.assertNotAlmostEqual(paired_novig(-122,+102),purchase_probability(-122))

    def test_pair_same_time_market_period_required(self):
        q={**row()["quote"],"event_id":row()["event_id"],"line":None,"side":"BUF"}
        p={**q,"american":102,"side":"BSU"}
        x=audit_observation(row(quote={**q,"matching_opposite":p}))
        self.assertIsNotNone(x["paired_market_no_vig_decisive"])
        self.assertAlmostEqual(x["paired_market_decisive_brier"],(x["paired_market_no_vig_decisive"]-1)**2)
        grouped=cohort_summary([row(quote={**q,"matching_opposite":p})])["groups"][0]
        self.assertEqual(grouped["market_paired_settled_count"],1)
        self.assertAlmostEqual(grouped["market_decisive_brier_on_market_pairs"],x["paired_market_decisive_brier"])
        with self.assertRaisesRegex(ReviewError,"exactly paired"):
            audit_observation(row(quote={**q,"matching_opposite":{**p,"retrieved_at_utc":"2026-11-11T16:20:00Z"}}))
        with self.assertRaisesRegex(ReviewError,"exactly paired"):
            audit_observation(row(quote={**q,"matching_opposite":{**p,"period":"REGULATION"}}))
        with self.assertRaisesRegex(ReviewError,"exactly paired"):
            audit_observation(row(quote={**q,"matching_opposite":{**p,"event_id":"WRONG_EVENT"}}))
        with self.assertRaisesRegex(ReviewError,"identical"):
            audit_observation(row(quote={**q,"matching_opposite":{**p,"line":5.5}}))
        with self.assertRaisesRegex(ReviewError,"exactly paired"):
            audit_observation(row(quote={**q,"matching_opposite":{**p,"side":"BUF"}}))

    def test_price_and_probability_non_finite_refused(self):
        for bad in [float("nan"), float("inf"),-0.001,1.001,True,"0.6"]:
            with self.subTest(bad=str(bad)):
                with self.assertRaises(ReviewError):
                    audit_observation(row(model_p_win=bad))
        for bad in [-99,0,99,100.5,True]:
            with self.subTest(price=bad):
                with self.assertRaises(ReviewError):
                    purchase_probability(bad)

    def test_unsupported_products_and_mls_binary_refusal(self):
        with self.assertRaisesRegex(ReviewError,"unsupported product"):
            audit_observation(row(product="ALTERNATE_F5"))
        with self.assertRaisesRegex(ReviewError,"1X2"):
            audit_observation(row(league="MLS"))
        with self.assertRaisesRegex(ReviewError,"three-way"):
            audit_observation(row(league="NBA",product="THREE_WAY"))

    def test_mls_threeway_scored_as_three_categories_not_binary(self):
        r=row(league="MLS",product="THREE_WAY",model_id="mls.dixoncoles.regulation",
              arm_id="threeway",selected_outcome="DRAW",
              three_way_probabilities={"HOME":0.5,"DRAW":0.3,"AWAY":0.2},
              observed_result="DRAW",model_p_win=None,quote=None)
        grade=audit_observation(r)
        self.assertIsNone(grade["binary_brier"])
        self.assertAlmostEqual(grade["three_way_brier"],0.5**2+(0.3-1)**2+0.2**2)
        summary=cohort_summary([r])
        self.assertEqual(summary["groups"][0]["wins"],1)
        self.assertIsNone(summary["groups"][0]["mean_binary_brier"])
        self.assertAlmostEqual(summary["groups"][0]["mean_three_way_brier"],0.78)

    def test_novig_not_inferred_from_unpaired_nhl_quote(self):
        x=audit_observation(row(league="NHL",product="PUCK_LINE",quote={**row()["quote"],"american":190}))
        self.assertIsNone(x["paired_market_no_vig_decisive"])
        self.assertIsNone(x["paired_market_decisive_brier"])

    def test_integer_spread_paired_decisive_vs_push_unconditional(self):
        q={**row()["quote"],"event_id":row()["event_id"],"market_key":"SPREAD",
           "line":-14,"side":"Toledo","american":-112}
        other={**q,"line":14,"side":"UMass","american":-108}
        obs=audit_observation(row(product="SPREAD",model_p_win=.6345,model_p_push=.019,
                                  quote={**q,"matching_opposite":other},observed_result="WIN"))
        self.assertAlmostEqual(obs["model_minus_market_decisive_pp"],
            100*((.6345/(1-.019))-paired_novig(-112,-108)))
        self.assertIsNone(obs["binary_brier"])
        self.assertIsNotNone(obs["conditional_decisive_brier"])
        self.assertIsNotNone(obs["settlement_three_class_brier"])
        with self.assertRaisesRegex(ReviewError,"complementary"):
            audit_observation(row(product="SPREAD",quote={**q,"matching_opposite":{**other,"line":13.5}}))

    def test_mls_pair_is_not_a_threeway_market(self):
        r=row(league="MLS",product="THREE_WAY",model_p_win=None,
              three_way_probabilities={"HOME":.5,"DRAW":.3,"AWAY":.2},
              selected_outcome="DRAW",observed_result="DRAW")
        q={**r["quote"],"event_id":r["event_id"],"side":"DRAW"}
        other={**q,"american":150,"side":"HOME"}
        with self.assertRaisesRegex(ReviewError,"all three market prices"):
            audit_observation({**r,"quote":{**q,"matching_opposite":other}})

    def test_mls_vector_sum_is_enforced(self):
        with self.assertRaisesRegex(ReviewError,"sum to one"):
            audit_observation(row(league="MLS",product="THREE_WAY",selected_outcome="HOME",
                                  three_way_probabilities={"HOME":0.6,"DRAW":0.3,"AWAY":0.2}))

    def test_integer_push_refund_is_not_a_win(self):
        r=row(product="SPREAD",model_p_win=.6345,model_p_push=.019,
              quote={**row()["quote"],"american":-112,"market_key":"SPREAD"},
              observed_result="PUSH")
        x=audit_observation(r)
        self.assertAlmostEqual(x["paper_ev_per_unit"],.6345*(100/112) - (1-.6345-.019))
        self.assertEqual(x["paper_realized_units"],0)
        self.assertIsNone(x["binary_brier"])
        self.assertIsNotNone(x["settlement_three_class_brier"])
        with self.assertRaisesRegex(ReviewError,"moneyline push"):
            audit_observation(row(observed_result="PUSH"))

    def test_negative_ev_can_still_win_not_qualified(self):
        x=audit_observation(row(model_p_win=.5,quote={**row()["quote"],"american":-600}))
        self.assertLess(x["paper_ev_per_unit"],0)
        self.assertEqual(x["decision"],"NO_PICK")
        self.assertFalse(x["action_authority"])

    def test_timing_quote_retrieval_after_cutoff_not_backdated(self):
        x=audit_observation(row())
        self.assertEqual(x["quote_status"],"POST_SEAL_COMPARISON_ONLY")
        q={**row()["quote"],"retrieved_at_utc":"2026-11-11T16:11:00Z",
           "provider_asof_utc":"2026-11-11T16:10:00Z"}
        x=audit_observation(row(quote=q))
        self.assertEqual(x["quote_status"],"AT_CUTOFF_SOURCE_DECLARED_UNVERIFIED")
        self.assertIn("QUOTE_NOT_INDEPENDENTLY_PROVEN_AT_CUTOFF",x["warnings"])

    def test_naive_and_late_frozen_cutoffs_rejected(self):
        with self.assertRaisesRegex(ReviewError,"offset"):
            audit_observation(row(forecast_cutoff_utc="2026-11-11T16:12:00"))
        with self.assertRaisesRegex(ReviewError,"must precede"):
            audit_observation(row(forecast_cutoff_utc="2026-11-12T00:30:00Z"))

    def test_registration_timestamp_only_not_prospective_evidence(self):
        x=audit_observation(row(protocol_registered_at_utc="2026-11-11T15:00:00Z"))
        self.assertTrue(x["policy_prestart_chronology_consistent"])
        self.assertFalse(x["prospective_policy_registration_proven"])
        self.assertIn("POLICY_TIMESTAMP_ONLY_INDEPENDENT_RECEIPT_UNVERIFIED",x["warnings"])
        late=audit_observation(row(protocol_registered_at_utc="2026-11-12T01:00:00Z"))
        self.assertFalse(late["policy_prestart_chronology_consistent"])

    def test_preferred_side_freezes_independently_of_price(self):
        self.assertEqual(preferred_side({"BUF":.67,"BSU":.33}),"BUF")
        self.assertIsNone(preferred_side({"HOME":.5,"AWAY":.5}))
        with self.assertRaisesRegex(ReviewError,"two model outcomes"):
            preferred_side({"BUF":.67})

    def test_no_opposing_ev_flip_and_totals_shadows(self):
        x=audit_observation(row(product="TOTAL",product_supported=False,observed_result=None))
        self.assertIn("NON_DECISION_FACING_PRODUCT",x["warnings"])
        self.assertIn("PRODUCT_SUPPORT_NOT_VERIFIED",x["warnings"])
        self.assertIsNone(x["binary_brier"])
        self.assertEqual(x["decision"],"NO_PICK")

    def test_cbb_unpriced_tail_visible(self):
        x=audit_observation(row(league="CBB",product="SPREAD",quote=None,model_p_win=.9463))
        self.assertIn("CBB_EXTREME_UNPRICED_TAIL_MONITOR",x["warnings"])
        self.assertIsNone(x["paper_ev_per_unit"])

    def test_personnel_probable_does_not_automatically_become_out(self):
        info=[
            {"kind":"BULLETIN","state":"PROBABLE","published_at_utc":"2026-11-11T15:00:00Z","retrieved_at_utc":"2026-11-11T15:05:00Z"},
            {"kind":"BULLETIN","state":"OUT","published_at_utc":"2026-11-11T20:00:00Z","retrieved_at_utc":"2026-11-11T20:01:00Z"},
            {"kind":"POSTGAME_DNP","state":"OUT","published_at_utc":"2026-11-11T14:00:00Z","retrieved_at_utc":"2026-11-11T15:00:00Z"}
        ]
        x=personnel_asof(info,"2026-11-11T16:00:00Z")
        self.assertEqual(x["state"],"PROBABLE")
        self.assertIsNone(x["numerical_delta"])
        self.assertFalse(x["feature_used"])

    def test_in_game_event_is_not_available_at_cutoff(self):
        x=personnel_asof([{"kind":"IN_GAME_EVENT","state":"OUT","published_at_utc":"2026-11-11T15:00:00Z","retrieved_at_utc":"2026-11-11T15:00:00Z"}],"2026-11-11T16:00:00Z")
        self.assertEqual(x["state"],"UNAVAILABLE_AT_CUTOFF")

    def test_action_authority_and_stakes_fail_closed(self):
        for bad in [row(action_authority=True),row(stake_units=1),row(action_authority=None)]:
            with self.subTest(bad=str(bad)):
                with self.assertRaisesRegex(ReviewError,"authority"):
                    audit_observation(bad)

    def test_two_red_flags_still_pass(self):
        x=audit_observation(row(red_flags=["NO_AUTH_PRICE","PERSONNEL_UNCONSUMED"]))
        self.assertIn("RED_FLAG_GATE_PASS",x["warnings"])
        self.assertEqual(x["official_stake_units"],0)

    def test_grouping_denominators_and_no_cross_league_average(self):
        first=row()
        second=row(product="SPREAD",arm_id="margin.v1",model_p_win=.63,
                   quote={**first["quote"],"market_key":"SPREAD"})
        output=cohort_summary([first,second])
        self.assertEqual(output["unique_events"],1)
        self.assertEqual(output["contract_rows"],2)
        self.assertEqual(len(output["groups"]),2)
        self.assertFalse(output["wagering_authority"])
        self.assertEqual(output["official_units"],0)
        with self.assertRaisesRegex(ReviewError,"duplicate event"):
            cohort_summary([first,first])

    def test_missing_final_is_not_scored(self):
        x=audit_observation(row(observed_result=None,final_source_sha256=None))
        self.assertEqual(x["grade_status"],"NOT_GRADED")
        self.assertIsNone(x["binary_brier"])
        self.assertIsNone(x["paper_realized_units"])

    def test_unsupported_half_settlement_refused(self):
        with self.assertRaisesRegex(ReviewError,"halves"):
            audit_observation(row(product="SPREAD",observed_result="HALF_WIN"))

    def test_cli_stdin_not_needed_output_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture=Path(tmp)/"in.json"
            fixture.write_text(json.dumps({"observations":[row()]}),encoding="utf-8")
            run=subprocess.run([sys.executable,str(ROOT/"scripts/review_cross_model_findings.py"),"--input",str(fixture)],capture_output=True,text=True,check=True)
            out=json.loads(run.stdout)
            self.assertEqual(out["unique_events"],1)
            self.assertEqual(out["groups"][0]["product"],"MONEYLINE")
            self.assertEqual(out["official_units"],0)
            self.assertEqual(out["rows"][0]["decision"],"NO_PICK")


if __name__ == "__main__":
    unittest.main()
