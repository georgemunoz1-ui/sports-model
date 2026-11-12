"""Research-only correlated exposure tests; no synthetic portfolio superiority claims."""
import math
import unittest
from harness.event_exposure_shadow import (
    ExposureError, review_event_exposure, review_exposure_book,
)


def position(contract_id, orientation, american=-110, settles=None):
    return {
        "event_id": "CFB:demo-1", "contract_id": contract_id,
        "market": "moneyline" if "ML" in contract_id else "spread",
        "orientation": orientation, "american": american,
        "reference_stake_units": 1.0,
        **({"settlements": settles} if settles is not None else {}),
    }


SCENARIOS = {
    "event_id": "CFB:demo-1", "law_id": "synthetic-for-test-only",
    "scenarios": [
        {"id": "HOME_BY_10", "probability": .35},
        {"id": "HOME_BY_1", "probability": .30},
        {"id": "AWAY_BY_7", "probability": .35},
    ],
}


class ExposureShadowTests(unittest.TestCase):
    def test_nested_moneyline_and_spread_not_independent(self):
        ml=position("HOME_ML", "HOME", -122,
                    {"HOME_BY_10":"WIN","HOME_BY_1":"WIN","AWAY_BY_7":"LOSS"})
        spread=position("HOME_-1.5", "HOME", -102,
                        {"HOME_BY_10":"WIN","HOME_BY_1":"LOSS","AWAY_BY_7":"LOSS"})
        out=review_event_exposure([ml,spread],event_scenarios=SCENARIOS)
        self.assertEqual(out["n_contracts"], 2)
        self.assertEqual(out["pairwise_structure"][0]["relationship"],"NESTED_STACK")
        self.assertEqual(out["dependence_status"],"COMMON_EVENT_LAW_SUPPLIED_NOT_INDEPENDENTLY_ATTESTED")
        expected=(.35*(100/122+100/102)+.30*(100/122-1)+.35*(-2))
        self.assertAlmostEqual(out["expected_event_return_units"],expected)
        self.assertIsNone(out["portfolio_cross_event_variance"])
        self.assertFalse(out["action_authority"])
        self.assertEqual(out["official_stake_units"],0)

    def test_opposing_side_middle_window(self):
        home=position("HOME_+3.5", "HOME", -110,
            {"HOME_BY_10":"WIN","HOME_BY_1":"WIN","AWAY_BY_7":"LOSS"})
        away=position("AWAY_+3.5", "AWAY", -110,
            {"HOME_BY_10":"LOSS","HOME_BY_1":"WIN","AWAY_BY_7":"WIN"})
        out=review_event_exposure([home,away],event_scenarios=SCENARIOS)
        self.assertEqual(out["pairwise_structure"][0]["relationship"],"OPPOSING_MIDDLE_WINDOW")
        self.assertGreater(out["scenario_returns"]["HOME_BY_1"]["net_units"],0)

    def test_disjoint_opposing_wins_not_middle(self):
        home=position("HOME_ML", "HOME", -110,
            {"HOME_BY_10":"WIN","HOME_BY_1":"WIN","AWAY_BY_7":"LOSS"})
        away=position("AWAY_ML", "AWAY", +110,
            {"HOME_BY_10":"LOSS","HOME_BY_1":"LOSS","AWAY_BY_7":"WIN"})
        out=review_event_exposure([home,away],event_scenarios=SCENARIOS)
        self.assertEqual(out["pairwise_structure"][0]["relationship"],"OPPOSING_NO_MIDDLE")

    def test_no_joint_law_cannot_estimate_correlation(self):
        out=review_event_exposure([position("HOME_ML","HOME")])
        self.assertIsNone(out["expected_event_return_units"])
        self.assertIsNone(out["event_return_sd_units"])
        self.assertIsNone(out["pairwise_structure"])
        self.assertEqual(out["dependence_status"],"UNASSESSED_NO_COMMON_JOINT_LAW")

    def test_refuse_settlements_without_common_law(self):
        with self.assertRaisesRegex(ExposureError,"without a common"):
            review_event_exposure([position("HOME_ML","HOME",settles={"A":"WIN"})])

    def test_scenario_identity_and_mass_fail_closed(self):
        good=position("HOME_ML","HOME",settles={"HOME_BY_10":"WIN", "HOME_BY_1":"WIN","AWAY_BY_7":"LOSS"})
        for changed in [
            {**SCENARIOS,"event_id":"OTHER"},
            {**SCENARIOS,"law_id":""},
            {**SCENARIOS,"scenarios":[{"id":"A","probability":.2}]},
            {**SCENARIOS,"scenarios":[{"id":"A","probability":.5},{"id":"A","probability":.5}]},
        ]:
            with self.subTest(changed=changed), self.assertRaises(ExposureError):
                review_event_exposure([good],event_scenarios=changed)

    def test_refuse_incomplete_and_unsupported_settlements(self):
        for outcomes in [{"HOME_BY_10":"WIN"},
                         {"HOME_BY_10":"HALF_WIN","HOME_BY_1":"WIN","AWAY_BY_7":"LOSS"}]:
            with self.subTest(outcomes=outcomes),self.assertRaises(ExposureError):
                review_event_exposure([position("HOME_ML","HOME",settles=outcomes)],event_scenarios=SCENARIOS)

    def test_refuse_bad_price_and_stake(self):
        for price in [0,-101.5,True,float("inf")]:
            with self.subTest(price=price),self.assertRaises(ExposureError):
                review_event_exposure([position("HOME_ML","HOME",american=price)])
        for stake in [0,-1,float("nan"),True]:
            bad=position("HOME_ML","HOME")
            bad["reference_stake_units"]=stake
            with self.subTest(stake=stake),self.assertRaises(ExposureError):
                review_event_exposure([bad])

    def test_refuse_duplicate_ids_and_cross_event_rows(self):
        p=position("HOME_ML","HOME")
        with self.assertRaisesRegex(ExposureError,"unique"):
            review_event_exposure([p,p])
        with self.assertRaisesRegex(ExposureError,"one event"):
            review_event_exposure([p,{**p,"event_id":"CFB:demo-2","contract_id":"OTHER"}])

    def test_push_void_are_zero_net(self):
        p=position("HOME_+0", "HOME", -110,
            {"HOME_BY_10":"WIN","HOME_BY_1":"PUSH","AWAY_BY_7":"VOID"})
        out=review_event_exposure([p],event_scenarios=SCENARIOS)
        self.assertEqual(out["scenario_returns"]["HOME_BY_1"]["net_units"],0)
        self.assertEqual(out["scenario_returns"]["AWAY_BY_7"]["net_units"],0)

    def test_book_aggregates_by_event_but_no_portfolio_sd(self):
        p=position("HOME_ML","HOME")
        q={**position("AWAY_ML","AWAY"),"event_id":"NFL:demo-2"}
        result=review_exposure_book([p,q])
        self.assertEqual(result["unique_events"],2)
        self.assertEqual(result["contract_rows"],2)
        self.assertEqual(result["reference_gross_risk_units"],2)
        self.assertIsNone(result["cross_event_portfolio_sd"])
        self.assertIsNone(result["cross_event_portfolio_ev"])

    def test_official_exposure_is_refused(self):
        with self.assertRaisesRegex(ExposureError,"authorize"):
            review_event_exposure([position("HOME_ML","HOME")],action_authority=True)
        with self.assertRaisesRegex(ExposureError,"authorize"):
            review_exposure_book([position("HOME_ML","HOME")],official_stake_units=1)


if __name__=="__main__":
    unittest.main()
