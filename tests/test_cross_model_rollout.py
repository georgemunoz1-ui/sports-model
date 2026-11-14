"""Exercise the same public research evaluation for every league and its native products."""
import copy
import unittest

from research.nov11_cross_model.cross_model_learning_review import LEAGUES, ReviewError, cohort_summary


class AllLeagueComparisonTests(unittest.TestCase):
    def test_coverage_holds_and_quote_clocks(self):
        for league in sorted(LEAGUES):
            for product in (("THREE_WAY", "TOTAL") if league == "MLS" else
                            ("MONEYLINE", {"MLB": "RUN_LINE", "NHL": "PUCK_LINE"}.get(league, "SPREAD"), "TOTAL")):
                with self.subTest(league=league, product=product):
                    side = "OVER" if product == "TOTAL" else "HOME"
                    period = "REGULATION" if league == "MLS" else "FULL_GAME"
                    line = {"TOTAL": 6.5, "RUN_LINE": -1.5, "PUCK_LINE": -1.5, "SPREAD": -3}.get(product)
                    quote = dict(event_id="fixture", period=period, side=side, line=line, american=-110,
                                 book="test", market_key=product, retrieved_at_utc="2026-11-13T16:10:00Z")
                    row = dict(league=league, event_id="fixture", product=product, period=period, line=line,
                               selected_outcome=side, action_authority=False, model_id="synthetic", arm_id="test",
                               forecast_cutoff_utc="2026-11-13T16:00:00Z", forecast_issued_at_utc="2026-11-13T16:01:00Z",
                               start_time_utc="2026-11-13T17:00:00Z", model_p_win=.55, model_p_push=.02 if line==-3 else 0,
                               three_way_probabilities={"HOME":.55,"DRAW":.2,"AWAY":.25}, quote=quote)
                    good = cohort_summary([row])
                    self.assertEqual(good["rows"][0]["quote_status"], "POST_SEAL_COMPARISON_ONLY")
                    self.assertEqual(good["league_coverage"][league]["reviewed_contracts"], 1)
                    wrong = copy.deepcopy(row)
                    wrong["quote"]["event_id"] = "wrong fixture"
                    with self.assertRaises(ReviewError):
                        cohort_summary([wrong])
                    late = copy.deepcopy(row)
                    late["quote"]["retrieved_at_utc"] = row["start_time_utc"]
                    self.assertIsNone(cohort_summary([late])["rows"][0]["paper_ev_per_unit"])
                    held = cohort_summary([row, dict(row, schedule_hold=True)])
                    self.assertFalse(held["rows"])
                    self.assertEqual(held["league_coverage"][league]["held_contracts"], 2)
                    self.assertEqual(held["unique_events"], 1)
