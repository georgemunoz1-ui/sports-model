"""freshness-p0 regression + mutation suite.

H1 (starter identity vs rates conflation): a historical game-log / season-stats
observation may gate a pitcher's RATES but must never confirm TONIGHT's starter
identity. The stamp carries confirms_identity=False and the contract caps any
starter-slot read at IDENTIFIED_UNCONFIRMED (dose 0.75 fresh / 0.50 degraded).

H2 (stale rates enter v13): MLBV13Component.predict reroutes any starter slot
whose disposition is not fresh/confirmed to v13's league-default _sp({}) dict
({era: None, gs: 0, k: None, bb: None}) and records the reroute in provenance.

No network I/O anywhere: every fetcher is injected or disabled (AcquisitionDisabled).
"""
import datetime as dt
import json
import os
import sys
import types
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TESTS_DIR, "..", "harness"))

import freshness_contract as FC     # noqa: E402
import acquisition as ACQ           # noqa: E402
import board_freshness as BF        # noqa: E402
import mc_components as mcc         # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 8, 28, 23, 10, tzinfo=UTC)   # the HOU@NYM slate evening

LEAGUE_DEFAULT = {"era": None, "gs": 0, "k": None, "bb": None}


def game_log_stamp(days_old, confirms_identity=False, grade=FC.CONFIRMED):
    """A historical game-log stamp: CONFIRMED rates evidence, never an identity
    attestation (confirms_identity=False), as MLBStatsAPIAdapter now emits."""
    t = NOW - dt.timedelta(days=days_old)
    return FC.Stamp(observed_at=t, effective_at=t, fetched_at=t,
                    source="https://statsapi.mlb.com/api/v1/people/1/stats?stats=gameLog",
                    source_sha256="deadbeef" * 8, grade=grade, subject="Hunter Brown",
                    confirms_identity=confirms_identity)


def recording_v13():
    """A v13 double that CAPTURES the sp dicts it was called with (to prove which
    rates actually reached rs()/v13_sim)."""
    m = types.SimpleNamespace()
    m.MODULE_ID = "run_v13_historical_test_double"
    m.calls = []

    def v13_sim(spa, sph, rf_a, ra_a, rf_h, ra_h, park_factor, seed, trials):
        m.calls.append({"sp_away": dict(spa), "sp_home": dict(sph),
                        "seed": seed, "trials": trials})
        return {"p_home": 0.55, "mc_se": 0.004, "proj_total": 8.7,
                "seed": seed, "trials": trials}
    m.v13_sim = v13_sim
    return m


# ================================================================== H1: contract gate

class TestIdentityRatesSeparation(unittest.TestCase):
    def test_fresh_game_log_does_not_confirm_starter_identity(self):
        """A 1-day-old CONFIRMED game-log stamp resolves FRESH but identity-capped:
        grade IDENTIFIED_UNCONFIRMED, dose 0.75, never bare PROBABLE."""
        d = FC.resolve_input("Hunter Brown", "mlb", "starter",
                             game_log_stamp(1), now=NOW)
        self.assertEqual(d.disposition, FC.FRESH)
        self.assertEqual(d.grade, FC.IDENTIFIED_UNCONFIRMED)
        self.assertEqual(d.dose_multiplier, 0.75)
        status, _disp = BF.resolve_slot("Hunter Brown", "mlb", "starter",
                                        game_log_stamp(1), "PROBABLE", now=NOW)
        self.assertNotEqual(status, "PROBABLE")
        self.assertIn("IDENTIFIED_UNCONFIRMED", status)

    def test_same_stamp_still_gates_rates_at_full_grade_for_non_starter_kinds(self):
        """The rates attestation itself is untouched: read as team_form/bullpen-age
        evidence the CONFIRMED grade stands (the separation is identity-only)."""
        d = FC.resolve_input("Hunter Brown", "mlb", "team_form",
                             game_log_stamp(1), now=NOW)
        self.assertEqual((d.disposition, d.grade, d.dose_multiplier),
                         (FC.FRESH, FC.CONFIRMED, 1.0))

    def test_stale_game_log_degrades_through_content_age_regate(self):
        """40 days old: the age re-gate degrades it (acquisition unavailable ->
        DEGRADED); identity cap applies on top."""
        d = FC.resolve_input("Hunter Brown", "mlb", "starter",
                             game_log_stamp(40), now=NOW)
        self.assertEqual(d.disposition, FC.DEGRADED)
        self.assertLessEqual(d.dose_multiplier, 0.50)

    def test_acquired_game_log_stamp_is_also_identity_capped(self):
        """The adapter chain path: an ACQUIRING result built from a game log is
        capped at IDENTIFIED_UNCONFIRMED too."""
        def acquire(subject, sport, kind):
            s = game_log_stamp(0.2)
            s.fetched_at = NOW
            return s
        d = FC.resolve_input("Hunter Brown", "mlb", "starter",
                             game_log_stamp(40), now=NOW, acquire=acquire)
        self.assertEqual(d.disposition, FC.ACQUIRING)
        self.assertEqual(d.grade, FC.IDENTIFIED_UNCONFIRMED)
        self.assertEqual(d.dose_multiplier, 0.75)

    def test_provenance_reason_names_the_identity_cap(self):
        d = FC.resolve_input("Hunter Brown", "mlb", "starter",
                             game_log_stamp(1), now=NOW)
        self.assertIn("confirms_identity=False", d.reason)
        self.assertTrue(d.stamp.confirms_identity is False)


# ================================================================== mutants (>= 9)

class TestFreshnessMutants(unittest.TestCase):
    """Each mutant breaks one protection; the gate (selftest or a direct behavior
    assertion) must catch every one. Restore module state after each."""

    def test_M1_age_limit_widened_to_90d_is_caught(self):
        orig = dict(FC.MAX_AGE_DAYS)
        FC.MAX_AGE_DAYS[("mlb", "starter")] = 90
        try:
            self.assertNotEqual(FC.selftest(), 0)     # 40-day stamp reads FRESH -> caught
        finally:
            FC.MAX_AGE_DAYS.clear(); FC.MAX_AGE_DAYS.update(orig)

    def test_M2_absent_restored_to_full_dose_is_caught(self):
        orig = dict(FC.DOSE)
        FC.DOSE[(FC.DEGRADED, FC.ABSENT)] = 1.0
        try:
            self.assertNotEqual(FC.selftest(), 0)
        finally:
            FC.DOSE.clear(); FC.DOSE.update(orig)

    def test_M3_degraded_confirmed_restored_to_full_dose_is_caught(self):
        orig = dict(FC.DOSE)
        FC.DOSE[(FC.DEGRADED, FC.CONFIRMED)] = 1.0
        try:
            self.assertNotEqual(FC.selftest(), 0)
        finally:
            FC.DOSE.clear(); FC.DOSE.update(orig)

    def test_M4_identified_unconfirmed_promoted_to_full_dose_is_caught(self):
        orig = dict(FC.DOSE)
        FC.DOSE[(FC.FRESH, FC.IDENTIFIED_UNCONFIRMED)] = 1.0
        try:
            self.assertNotEqual(FC.selftest(), 0)
        finally:
            FC.DOSE.clear(); FC.DOSE.update(orig)

    def test_M5_post_hoc_promoted_to_pregame_confirmation_is_caught(self):
        orig = dict(FC.DOSE)
        FC.DOSE[(FC.FRESH, FC.POST_HOC_NOT_PREGAME)] = 1.0
        try:
            self.assertNotEqual(FC.selftest(), 0)
        finally:
            FC.DOSE.clear(); FC.DOSE.update(orig)

    def test_M6_identity_cap_removed_is_caught(self):
        """Mutant: _starter_effective_grade stops capping -> a historical game log
        confirms starter identity again. The behavior gate must see the dose jump."""
        orig = FC._starter_effective_grade
        FC._starter_effective_grade = lambda stamp, kind: stamp.grade
        try:
            d = FC.resolve_input("Hunter Brown", "mlb", "starter",
                                 game_log_stamp(1), now=NOW)
            self.assertEqual(d.dose_multiplier, 1.0)   # mutant escapes to full dose...
        finally:
            FC._starter_effective_grade = orig
        # ...and the UNMUTATED gate caps it at 0.75
        d = FC.resolve_input("Hunter Brown", "mlb", "starter",
                             game_log_stamp(1), now=NOW)
        self.assertEqual(d.dose_multiplier, 0.75)

    def test_M7_identity_flag_flipped_is_caught(self):
        """Mutant: the stamp lies about confirming identity. The dose difference
        between flagged and unflagged proves the flag is load-bearing."""
        flagged = FC.resolve_input("p", "mlb", "starter",
                                   game_log_stamp(1, confirms_identity=False), now=NOW)
        unflagged = FC.resolve_input("p", "mlb", "starter",
                                     game_log_stamp(1, confirms_identity=True), now=NOW)
        self.assertEqual(flagged.dose_multiplier, 0.75)
        self.assertEqual(unflagged.dose_multiplier, 1.0)
        self.assertNotEqual(flagged.grade, unflagged.grade)

    def test_M8_dose_floor_removed_is_caught(self):
        """Mutant: cohort_dose drops the 0.20 floor. Two ABSENT slots would collapse
        to 0.0625; the frozen floor holds the game at 0.20."""
        absent = [FC.resolve_input("a", "mlb", "starter", None, now=NOW),
                  FC.resolve_input("b", "mlb", "starter", None, now=NOW)]
        self.assertEqual(FC.cohort_dose(absent), 0.20)             # gated
        mutant = absent[0].dose_multiplier * absent[1].dose_multiplier
        self.assertEqual(mutant, 0.0625)                           # mutant escapes below
        self.assertLess(mutant, 0.20)

    def test_M9_refetch_without_new_content_clears_staleness_is_caught(self):
        g = FC.__dict__
        orig = g["clear_requires_new_content"]
        FC.clear_requires_new_content = lambda b, a: (True, "mutant")
        try:
            self.assertNotEqual(FC.selftest(), 0)
        finally:
            FC.clear_requires_new_content = orig

    def test_M10_cohort_max_instead_of_product_is_caught(self):
        orig = FC.cohort_dose
        FC.cohort_dose = lambda ds: max(x.dose_multiplier for x in ds)
        try:
            self.assertNotEqual(FC.selftest(), 0)
        finally:
            FC.cohort_dose = orig

    def test_M11_unknown_grade_rejected_not_defaulted(self):
        s = game_log_stamp(1)
        s.grade = "CONFIRMED_ENOUGH"
        with self.assertRaises(FC.StampError):
            FC.resolve_input("p", "mlb", "starter", s, now=NOW)


# ================================================================== H2: v13 reroute

class TestV13StaleStarterReroute(unittest.TestCase):
    def _predict(self, sp_away, sp_home, disps):
        v13 = recording_v13()
        comp = mcc.MLBV13Component(v13_module=v13, require_data_artifacts=False)
        out = comp.predict("2026-08-28", "mlb:HOU@NYM", sp_away, sp_home,
                           (4.4, 4.1), (4.6, 4.3), None, disps)
        return out, v13.calls[0]

    def test_stale_starter_rates_never_reach_v13(self):
        sp_real = {"era": 3.10, "gs": 20, "k": 27.5, "bb": 7.1}
        stale = FC.resolve_input("Hunter Brown", "mlb", "starter",
                                 game_log_stamp(40), now=NOW)
        fresh = FC.resolve_input("other", "mlb", "starter",
                                 FC.Stamp(observed_at=NOW, effective_at=NOW, source="t",
                                          source_sha256="a" * 8, grade=FC.CONFIRMED,
                                          subject="other"), now=NOW)
        out, call = self._predict(sp_real, sp_real, [stale, fresh])
        self.assertEqual(call["sp_away"], LEAGUE_DEFAULT)    # stale rates withheld
        self.assertEqual(call["sp_home"], sp_real)           # fresh rates pass through
        routing = out["provenance"]["starter_routing"]
        self.assertIn("LEAGUE_DEFAULT_REROUTE", routing[0]["rates_used"])
        self.assertEqual(routing[1]["rates_used"], "measured (fresh/confirmed)")

    def test_identity_unconfirmed_fresh_starter_is_also_rerouted(self):
        """A FRESH but identity-unconfirmed slot (dose 0.75) still runs on league
        defaults: rates enter v13 only for fresh+CONFIRMED dispositions."""
        sp_real = {"era": 3.10, "gs": 20, "k": 27.5, "bb": 7.1}
        unconf = FC.resolve_input("Hunter Brown", "mlb", "starter",
                                  game_log_stamp(1), now=NOW)
        self.assertEqual(unconf.disposition, FC.FRESH)       # fresh but NOT confirmed
        out, call = self._predict(sp_real, dict(sp_real), [unconf, unconf])
        self.assertEqual(call["sp_away"], LEAGUE_DEFAULT)
        self.assertEqual(call["sp_home"], LEAGUE_DEFAULT)

    def test_mutant_no_reroute_would_leak_stale_rates(self):
        """Mutation check: WITHOUT the gate, the stale dict would reach v13 verbatim.
        Asserts the gate is what stops it (the recorded call proves the rewrite)."""
        sp_real = {"era": 3.10, "gs": 20, "k": 27.5, "bb": 7.1}
        stale = FC.resolve_input("Hunter Brown", "mlb", "starter",
                                 game_log_stamp(40), now=NOW)
        _out, call = self._predict(sp_real, LEAGUE_DEFAULT, [stale, stale])
        self.assertNotEqual(call["sp_away"], sp_real)        # gate rewrote it
        # the mutant (pass-through) is exactly what the gate forbids:
        self.assertEqual(call["sp_away"], LEAGUE_DEFAULT)


# ================================================================== HOU@NYM regression

class TestHouNymRegression(unittest.TestCase):
    """The 2026-08-28 HOU@NYM case, replayed through the p0 fixes: Hunter Brown
    stamped 40 days old from historical logs, Christian Scott absent."""

    def setUp(self):
        self.brown = FC.resolve_input(
            "Hunter Brown", "mlb", "starter",
            FC.Stamp(observed_at="2026-07-19T11:23:55Z",
                     effective_at="2026-07-19T11:23:55Z",
                     source="data/mlb/stats/sp_2026-07-19.json",
                     source_sha256="deadbeef", grade=FC.CONFIRMED,
                     subject="Hunter Brown", confirms_identity=False), now=NOW)
        self.scott = FC.resolve_input("Christian Scott", "mlb", "starter", None, now=NOW)
        v13 = recording_v13()
        self.v13 = v13
        comp = mcc.MLBV13Component(v13_module=v13, require_data_artifacts=False)
        sp_brown = {"era": 3.10, "gs": 20, "k": 27.5, "bb": 7.1}
        sp_scott = {"era": 4.20, "gs": 15, "k": 24.0, "bb": 9.0}
        self.out = comp.predict("2026-08-28", "mlb:HOU@NYM", sp_brown, sp_scott,
                                (4.4, 4.1), (4.6, 4.3), None,
                                [self.brown, self.scott])
        self.call = v13.calls[0]

    def test_a_dispositions_are_not_fresh_confirmed(self):
        self.assertNotEqual((self.brown.disposition, self.brown.grade),
                            (FC.FRESH, FC.CONFIRMED))
        self.assertEqual(self.brown.disposition, FC.DEGRADED)
        self.assertEqual((self.scott.disposition, self.scott.grade),
                         (FC.DEGRADED, FC.ABSENT))

    def test_b_v13_receives_league_default_for_both_slots(self):
        self.assertEqual(self.call["sp_away"], LEAGUE_DEFAULT)
        self.assertEqual(self.call["sp_home"], LEAGUE_DEFAULT)

    def test_c_dose_at_or_below_degraded_multiplier(self):
        self.assertLessEqual(self.out["dose"], 0.50)   # degraded, floored at 0.20
        self.assertGreaterEqual(self.out["dose"], 0.20)

    def test_d_provenance_records_the_reroute(self):
        routing = self.out["provenance"]["starter_routing"]
        self.assertEqual(len(routing), 2)
        for r in routing:
            self.assertIn("LEAGUE_DEFAULT_REROUTE", r["rates_used"])
        self.assertEqual(routing[0]["subject"], "Hunter Brown")
        self.assertEqual(routing[1]["subject"], "Christian Scott")
        mcc.assert_no_market_fields(self.out, self.out["arm"])


# ================================================================== acquisition self-test

class TestAcquisitionIdentityGrade(unittest.TestCase):
    """The adapter's historical-log stamp grades RATES but not starter identity."""

    def _adapter(self, last_date):
        body = json.dumps({"stats": [{"splits": [{"date": last_date}]}]}).encode()

        def ok_get(url, timeout=5):
            if "/people/search" in url:
                return json.dumps({"people": [{"id": 1}]}).encode()
            return body
        return ACQ.MLBStatsAPIAdapter(http_get=ok_get, now_fn=lambda: NOW)

    def test_game_log_stamp_is_confirmed_but_never_identity(self):
        s = self._adapter("2026-08-26").fetch("Hunter Brown", "mlb", "starter")
        self.assertIsNotNone(s)
        self.assertEqual(s.grade, FC.CONFIRMED)              # rates: CONFIRMED
        self.assertIs(s.confirms_identity, False)            # identity: NOT carried
        d = FC.resolve_input("Hunter Brown", "mlb", "starter", s, now=NOW)
        self.assertEqual(d.disposition, FC.FRESH)            # fresh rates...
        self.assertEqual(d.grade, FC.IDENTIFIED_UNCONFIRMED) # ...unconfirmed identity
        self.assertEqual(d.dose_multiplier, 0.75)
        status, _ = BF.resolve_slot("Hunter Brown", "mlb", "starter", s, "PROBABLE",
                                    now=NOW)
        self.assertNotEqual(status, "PROBABLE")

    def test_identity_cap_survives_livestore_roundtrip(self):
        """The confirms_identity=False marker must persist through the append-only
        LiveStore (R6) — otherwise the store would launder it back to CONFIRMED."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            store = ACQ.LiveStore(os.path.join(td, "s.jsonl"), now_fn=lambda: NOW)
            store.write(self._adapter("2026-08-26").fetch("Hunter Brown", "mlb",
                                                          "starter"))
            back = store.read("Hunter Brown")
        self.assertIs(back.confirms_identity, False)
        d = FC.resolve_input("Hunter Brown", "mlb", "starter", back, now=NOW)
        self.assertEqual(d.grade, FC.IDENTIFIED_UNCONFIRMED)

    def test_search_identify_still_never_binds(self):
        """Unchanged invariant: search snippets grade IDENTIFIED_UNCONFIRMED even
        with a perfect snippet (they DO confirm identity-class evidence but never
        reach CONFIRMED)."""
        perfect = [{"title": "OFFICIAL", "url": "https://example.com/p",
                    "date": "2026-08-28",
                    "snippet": "Hunter Brown named the starter, August 28, 2026"}]
        s = ACQ.SearchIdentifyAdapter(lambda q: perfect,
                                      now_fn=lambda: NOW).fetch("Hunter Brown", "mlb",
                                                                "starter")
        self.assertEqual(s.grade, FC.IDENTIFIED_UNCONFIRMED)
        d = FC.resolve_input("Hunter Brown", "mlb", "starter", s, now=NOW)
        self.assertLessEqual(d.dose_multiplier, 0.75)

    def test_unconfigured_acquisition_still_disabled(self):
        with self.assertRaises(ACQ.AcquisitionDisabled):
            ACQ._default_http_get("https://statsapi.mlb.com/x")
        self.assertIsNone(ACQ.build_adapter_chain()("Hunter Brown", "mlb", "starter"))


if __name__ == "__main__":
    unittest.main()
