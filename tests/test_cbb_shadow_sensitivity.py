"""Regression tests for research-only spread and winner sensitivity."""
import copy
import math
import unittest

from research.cbb_shadow_sensitivity import expanded_margin, normalized_home, paired_probability, run


class TestShadowSensitivity(unittest.TestCase):
    def test_integer_projection_preserves_mass_mean_and_overtime(self):
        distribution = {"support": [-3, -1, 1, 2, 5], "masses": [.10, .35, .25, .15, .15]}
        original = copy.deepcopy(distribution)
        law = expanded_margin(distribution)
        self.assertAlmostEqual(sum(law.values()), 1)
        mean = sum(x*p for x, p in zip(distribution["support"], distribution["masses"]))
        self.assertAlmostEqual(sum(x*p for x,p in law.items()), mean)
        self.assertNotIn(0, law)
        self.assertTrue(all(type(x) is int for x in law))
        self.assertEqual(original, distribution)

    def test_bad_law_refused(self):
        for support,masses in [([0,1],[.5,.5]),([1,1],[.2,.8]),([1,2],[.6,.7]),([1,2],[math.nan,.3])]:
            with self.assertRaises(ValueError):
                expanded_margin({"support":support,"masses":masses})

    def test_normalization_requires_paired_quotes(self):
        self.assertAlmostEqual(normalized_home({"home":{"odds":-110},"away":{"odds":-110}}),.5)
        with self.assertRaises(ValueError):
            normalized_home({"home":{"odds":-110},"away":{"odds":None}})

    def test_spread_benchmark_needs_exact_opposing_line(self):
        forecast = dict(distribution_input_sha256="margin", distributions={
            "margin": {"support": [-3, 1, 4], "masses": [.2, .4, .4]}})
        pair = {"away": {"line": 2.5, "odds": -110}, "home": {"line": -2.5, "odds": -110}}
        source = {"frozen_source": "margin"}
        args = ("spread", forecast, {"quotes": {"spread": pair}}, source, "away", 2.5, "parent")
        p, b, q = paired_probability(*args)
        self.assertAlmostEqual(p, .6)
        self.assertAlmostEqual(q, .5)
        pair["home"]["line"] = -3.5
        self.assertEqual((p, b, None), paired_probability(*args))

    def test_paired_home_win_and_late_quote_refusal(self):
        cutoff="2026-11-14T07:00Z"
        issue="2026-11-14T09:00Z"
        start="2026-11-14T17:00Z"
        f=dict(event_id="CBB:1",forecast_status="FORECAST_GENERATED",home_team="H",away_team="A",
               start_time_utc=start,settlement="FULL_GAME_INCLUDING_OVERTIME",model_id="v1",
               p_home_win=.7, model_state_config_hash="s")
        parent=dict(forecasts=[f],schema="sports.cbb.shadow_card.v2",date="2026-11-14",
                    league="CBB",market_input=False,as_of_utc=cutoff,generated_at_utc=issue)
        m=dict(cutoff=cutoff,issue=issue,model="v1",period=f["settlement"],frozen_source="parent",
               preferred="home",preferred_data={"win":.7},quote_cohort="POST_SEAL_PRESTART")
        r=dict(event_id=f["event_id"],league="CBB",home="H",away="A",start=start,hold=[],
               quote_utc="2026-11-14T15:00Z",quote_sha256="quote",book="test",markets={"moneyline":[m]},
               quotes={"moneyline":{"home":{"odds":-110},"away":{"odds":-110}}})
        grade=[["CBB","A at H","72–80","moneyline","home","","70.0%","W"]]
        board=dict(rows=[r],slate_date=parent["date"])
        rows,errors=run(parent,board,grade,"parent")
        self.assertFalse(errors)
        self.assertAlmostEqual(rows[0]["challenger"],.65)
        self.assertEqual(rows[0]["y"],1)
        r["quote_utc"]=start
        rows,errors=run(parent,board,grade,"parent")
        self.assertFalse(rows)
        self.assertEqual(errors[0]["reason"],"chronology mismatch")

if __name__ == "__main__":
    unittest.main()
