"""Core tests for models.common.margins. Self-contained; numpy/scipy only."""
import numpy as np
import pytest
from scipy.stats import norm

from models.common.margins import (
    MarginDistribution,
    cover_quote,
    discrete_football_margin,
    empirical_margin,
    estimate_sigma,
    margin_quote_record,
    normal_margin,
    simulated_margin,
    validate_record,
)
from models.common.margins.emit import _record_hash

PROV = {"sport": "nfl", "window_start": "2023-09-01", "window_end": "2024-01-01", "oof": True}
MODEL = {"model_id": "margin-core-test", "artifact_sha256": "ab" * 32}
TS = "2024-01-01T00:00:00+00:00"


def _code(excinfo):
    return str(excinfo.value)


# ---------------- distribution: normal ----------------

class TestNormalMargin:
    def test_cdf_known_phi_values(self):
        d = normal_margin(0.0, 1.0, PROV)
        assert d.cdf(0.0) == pytest.approx(0.5, abs=1e-12)
        assert d.cdf(1.959963984540054) == pytest.approx(0.975, abs=1e-9)
        assert d.cdf(-1.6448536269514722) == pytest.approx(0.05, abs=1e-9)

    def test_cdf_shifted_matches_scipy(self):
        d = normal_margin(3.0, 10.5, PROV)
        for m in (-7.5, 0.0, 3.0, 13.25):
            assert d.cdf(m) == pytest.approx(norm.cdf(m, 3.0, 10.5), abs=1e-12)

    def test_push_mass_zero_everywhere(self):
        d = normal_margin(3.0, 10.0, PROV)
        assert d.push_mass(-3.0) == 0.0
        assert d.push_mass(-2.5) == 0.0

    def test_sigma_validation(self):
        with pytest.raises(ValueError, match="MARGIN_SIGMA_INVALID"):
            normal_margin(0.0, 0.0, PROV)
        with pytest.raises(ValueError, match="MARGIN_SIGMA_INVALID"):
            normal_margin(0.0, -1.5, PROV)

    def test_sample_deterministic(self):
        d = normal_margin(1.0, 2.0, PROV)
        a = d.sample(500, seed=7)
        b = d.sample(500, seed=7)
        np.testing.assert_array_equal(a, b)
        assert abs(a.mean() - 1.0) < 0.3

    def test_distribution_id_stability_and_provenance(self):
        d1 = normal_margin(3.0, 10.0, PROV)
        d2 = normal_margin(3.0, 10.0, dict(PROV))
        assert d1.distribution_id == d2.distribution_id
        d3 = normal_margin(3.0, 10.0, {**PROV, "window_end": "2024-02-01"})
        assert d1.distribution_id != d3.distribution_id
        d4 = normal_margin(3.5, 10.0, PROV)
        assert d1.distribution_id != d4.distribution_id

    def test_protocol_conformance(self):
        assert isinstance(normal_margin(0.0, 1.0, PROV), MarginDistribution)


# ---------------- distribution: empirical / simulated / discrete ----------------

class TestEmpiricalMargin:
    def test_min_support_error_code(self):
        with pytest.raises(ValueError, match="EMPIRICAL_MARGIN_MIN_SUPPORT"):
            empirical_margin(0.0, np.arange(199.0), PROV)

    def test_cdf_direct_counting(self):
        resid = np.arange(400.0) - 200.0
        d = empirical_margin(0.0, resid, PROV)
        # xs = sorted resid in [-200, 199]; P(M <= 0) = 201/400
        assert d.cdf(0.0) == pytest.approx(201 / 400)
        assert d.cdf(-200.5) == 0.0
        assert d.cdf(199.0) == 1.0

    def test_no_push_mass_without_snap(self):
        resid = np.arange(400.0) - 200.0
        d = empirical_margin(0.0, resid, PROV, integer_snap=False)
        assert d.push_mass(0.0) == 0.0

    def test_integer_snap_push_mass(self):
        rng = np.random.default_rng(0)
        resid = rng.normal(0, 5, 1000)
        d = empirical_margin(0.0, resid, PROV, integer_snap=True)
        assert d.push_mass(0.0) > 0.0
        assert d.push_mass(0.5) == 0.0
        assert d.push_mass(2.0) > 0.0

    def test_sample_deterministic(self):
        resid = np.arange(400.0) - 200.0
        d = empirical_margin(2.0, resid, PROV)
        np.testing.assert_array_equal(d.sample(100, seed=1), d.sample(100, seed=1))


class TestSimulatedMargin:
    def test_min_draws_error_code(self):
        with pytest.raises(ValueError, match="SIMULATED_MARGIN_MIN_DRAWS"):
            simulated_margin(np.zeros(9999), PROV)

    def test_direct_counting_matches_normal_large_draws(self):
        draws = np.random.default_rng(42).normal(2.5, 11.0, 60000)
        d = simulated_margin(draws, PROV)
        for m in (-10.0, 0.0, 2.5, 15.0):
            assert d.cdf(m) == pytest.approx(norm.cdf(m, 2.5, 11.0), abs=0.01)
        assert d.integer_support is False
        assert d.push_mass(0.0) == 0.0

    def test_integer_draws_auto_push_mass(self):
        rng = np.random.default_rng(1)
        draws = np.round(rng.normal(-3.0, 9.0, 20000))
        d = simulated_margin(draws, PROV)
        assert d.integer_support is True
        expected = float(np.mean(draws == -3.0))
        assert d.push_mass(-3.0) == pytest.approx(expected, abs=1e-12)
        assert d.push_mass(-3.5) == 0.0


class TestDiscreteFootballMargin:
    def test_requires_key_number_mass(self):
        with pytest.raises(ValueError, match="DISCRETE_FOOTBALL_REQUIRES_KEY_NUMBER_MASS"):
            discrete_football_margin(-3.0, 13.0, None, PROV)

    def test_plain_normal_escape_hatch(self):
        d = discrete_football_margin(-3.0, 13.0, None, {**PROV, "allow_plain_normal": True})
        assert d.push_mass(3.0) == 0.0
        assert d.cdf(-3.0) == pytest.approx(0.5, abs=1e-12)

    def test_key_number_inflation(self):
        d = discrete_football_margin(0.0, 13.0, {3: 0.10, 7: 0.08}, PROV)
        base = norm.pdf(3, 0.0, 13.0) / sum(norm.pdf(k, 0.0, 13.0) for k in range(-130, 131))
        assert d.push_mass(3.0) > base  # inflated above plain discretized normal
        assert d.push_mass(4.0) < d.push_mass(3.0)
        assert d.push_mass(2.5) == 0.0

    def test_cdf_sums_to_one(self):
        d = discrete_football_margin(-3.0, 13.0, {3: 0.1}, PROV)
        assert d.cdf(10_000.0) == pytest.approx(1.0, abs=1e-12)
        assert 0.0 < d.cdf(-3.0) < 1.0


# ---------------- cover ----------------

class TestCoverQuote:
    def test_half_line_push_exactly_zero(self):
        d = discrete_football_margin(-3.0, 13.0, {3: 0.1}, PROV)
        q = cover_quote(d, -3.5)
        assert q.p_push == 0.0
        assert q.p_cover + q.p_loss == pytest.approx(1.0, abs=1e-12)

    def test_integer_line_push_positive_discrete(self):
        d = discrete_football_margin(-3.0, 13.0, {3: 0.1}, PROV)
        q = cover_quote(d, -3.0)
        assert q.p_push == pytest.approx(d.push_mass(3.0), abs=1e-12)
        assert q.p_push > 0.0

    def test_integer_line_push_positive_simulated(self):
        rng = np.random.default_rng(2)
        draws = np.round(rng.normal(-3.0, 9.0, 20000))
        d = simulated_margin(draws, PROV)
        q = cover_quote(d, -3.0)
        assert q.p_push > 0.0
        assert q.p_cover + q.p_push + q.p_loss == pytest.approx(1.0, abs=1e-9)

    def test_cover_formula_normal(self):
        # mu=3, s=-3 -> cover iff M > 3 -> 1 - Phi(0) = 0.5
        d = normal_margin(3.0, 10.0, PROV)
        q = cover_quote(d, -3.0)
        assert q.p_cover == pytest.approx(0.5, abs=1e-12)
        q2 = cover_quote(d, 0.0)  # cover iff M > 0
        assert q2.p_cover == pytest.approx(1 - norm.cdf(0, 3.0, 10.0), abs=1e-12)

    def test_symmetry_both_sides(self):
        d = discrete_football_margin(-2.5, 12.0, {3: 0.1, 7: 0.05, -3: 0.1}, PROV)
        for s in (-7.0, -3.0, 0.0, 2.5, 3.5, 10.0):
            qh = cover_quote(d, s, orientation="home")
            qa = cover_quote(d, s, orientation="away")
            assert qh.p_cover + qa.p_cover + qh.p_push == pytest.approx(1.0, abs=1e-9)
            assert qa.p_push == qh.p_push
            assert qa.p_cover == pytest.approx(qh.p_loss, abs=1e-12)
            assert qa.p_loss == pytest.approx(qh.p_cover, abs=1e-12)

    def test_ex_push_value_and_label(self):
        d = discrete_football_margin(-3.0, 13.0, {3: 0.1}, PROV)
        q = cover_quote(d, -3.0)
        assert q.p_cover_ex_push == pytest.approx(q.p_cover / (1 - q.p_push), abs=1e-12)
        assert "EXCLUDING_PUSHES" in q.labels

    def test_ex_push_unlabeled_on_half_line(self):
        d = normal_margin(3.0, 10.0, PROV)
        q = cover_quote(d, -3.5)
        assert q.labels == ()
        assert q.p_cover_ex_push == pytest.approx(q.p_cover, abs=1e-12)

    def test_symmetry_violation_fail_closed(self):
        class BadDist:
            distribution_id = "bad"

            def cdf(self, m):  # strict-style cdf: excludes the point mass
                return float(norm.cdf(m, 0.0, 10.0))

            def push_mass(self, m):
                return 0.1 if m == 3.0 else 0.0

            def sample(self, n, seed):
                return np.zeros(n)

        with pytest.raises(ValueError, match="COVER_SYMMETRY_VIOLATION"):
            cover_quote(BadDist(), -3.0)

    def test_invalid_orientation(self):
        d = normal_margin(0.0, 1.0, PROV)
        with pytest.raises(ValueError, match="COVER_ORIENTATION_INVALID"):
            cover_quote(d, -3.0, orientation="neutral")

    def test_all_push_degenerate_quote_and_record(self):
        # All mass at one point: p_push == 1.0, so p_cover_ex_push is
        # undefined (None) and the EXCLUDING_PUSHES label must be suppressed;
        # the emitted record must still validate.
        d = empirical_margin(0.0, np.zeros(300), PROV, integer_snap=True)
        q = cover_quote(d, 0.0)  # push iff M == 0
        assert q.p_push == 1.0
        assert q.p_cover == 0.0 and q.p_loss == 0.0
        assert q.p_cover_ex_push is None
        assert "EXCLUDING_PUSHES" not in q.labels
        rec = margin_quote_record(
            d, q, event={"event_id": "evt-all-push"}, source_model=MODEL,
            sigma_provenance=PROV, generated_at_utc=TS,
        )
        assert rec["probabilities"]["p_cover_ex_push"] is None
        assert "EXCLUDING_PUSHES" not in rec["probabilities"]["labels"]
        assert validate_record(rec) is True

    def test_degenerate_push_record_with_ex_push_value_rejected(self):
        d = empirical_margin(0.0, np.zeros(300), PROV, integer_snap=True)
        q = cover_quote(d, 0.0)
        rec = margin_quote_record(
            d, q, event={"event_id": "evt-all-push"}, source_model=MODEL,
            sigma_provenance=PROV, generated_at_utc=TS,
        )
        rec["probabilities"]["p_cover_ex_push"] = 0.5  # undefined at p_push==1
        rec["record_sha256"] = _record_hash(rec)
        with pytest.raises(ValueError, match="MARGIN_RECORD_LABEL_VIOLATION"):
            validate_record(rec)

    def test_non_finite_line_rejected(self):
        d = normal_margin(0.0, 10.0, PROV)
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError, match="COVER_LINE_NOT_FINITE"):
                cover_quote(d, bad)


# ---------------- sigma ----------------

class TestEstimateSigma:
    def test_oof_enforced(self):
        rng = np.random.default_rng(0)
        pred = rng.normal(0, 1, 500)
        actual = pred + rng.normal(0, 5, 500)
        with pytest.raises(ValueError, match="SIGMA_REQUIRES_CHRONOLOGICAL_OOF"):
            estimate_sigma(pred, actual, provenance={**PROV, "oof": False})
        with pytest.raises(ValueError, match="SIGMA_REQUIRES_CHRONOLOGICAL_OOF"):
            estimate_sigma(pred, actual)  # no provenance at all

    def test_sport_required(self):
        pred = np.zeros(300)
        actual = np.ones(300)
        prov = {k: v for k, v in PROV.items() if k != "sport"}
        with pytest.raises(ValueError, match="SIGMA_REQUIRES_SPORT"):
            estimate_sigma(pred, actual, label_in_sample=True, provenance=prov)

    def test_sigma_matches_std_ddof1(self):
        rng = np.random.default_rng(3)
        pred = rng.normal(0, 1, 500)
        actual = pred + rng.normal(1.0, 5.0, 500)
        out = estimate_sigma(pred, actual, provenance=PROV)
        resid = actual - pred
        assert out["sigma"] == pytest.approx(resid.std(ddof=1), abs=1e-12)
        assert out["mean_bias"] == pytest.approx(resid.mean(), abs=1e-12)
        assert out["n"] == 500
        assert out["groups"] is None
        assert out["sport"] == "nfl"

    def test_min_support_error(self):
        with pytest.raises(ValueError, match="SIGMA_MIN_SUPPORT"):
            estimate_sigma(np.zeros(100), np.zeros(100), provenance=PROV)

    def test_per_group_min_n_flag(self):
        rng = np.random.default_rng(4)
        n_big, n_small = 300, 50
        pred = np.concatenate([rng.normal(0, 1, n_big), rng.normal(0, 1, n_small)])
        actual = pred + np.concatenate([rng.normal(0, 4, n_big), rng.normal(0, 9, n_small)])
        seasons = np.array(["2023"] * n_big + ["2024"] * n_small)
        out = estimate_sigma(pred, actual, group_by=(seasons,), provenance=PROV)
        groups = {g["key"][0]: g for g in out["groups"]}
        assert groups["2023"]["flag"] == "OK"
        assert groups["2023"]["sigma"] == pytest.approx(4.0, abs=0.6)
        assert groups["2024"]["flag"] == "INSUFFICIENT_SUPPORT"
        assert groups["2024"]["sigma"] is None

    def test_multikey_groupby(self):
        rng = np.random.default_rng(5)
        n = 600
        pred = rng.normal(0, 1, n)
        actual = pred + rng.normal(0, 6, n)
        sports = np.array(["nfl"] * 300 + ["ncaaf"] * 300)
        weeks = np.array(["w1"] * 150 + ["w2"] * 150 + ["w1"] * 150 + ["w2"] * 150)
        out = estimate_sigma(pred, actual, group_by=(sports, weeks), provenance=PROV)
        assert len(out["groups"]) == 4
        assert all(g["flag"] == "INSUFFICIENT_SUPPORT" for g in out["groups"])  # 150 < 200

    def test_in_sample_label_allowed(self):
        pred = np.zeros(300)
        actual = np.random.default_rng(0).normal(0, 3, 300)
        out = estimate_sigma(pred, actual, label_in_sample=True, provenance=PROV)
        assert out["label_in_sample"] is True
        assert out["sigma"] > 0

    def test_inverted_window_rejected(self):
        rng = np.random.default_rng(6)
        pred = rng.normal(0, 1, 300)
        actual = pred + rng.normal(0, 4, 300)
        inverted = {**PROV, "window_start": "2025-01-01", "window_end": "2021-01-01"}
        with pytest.raises(ValueError, match="SIGMA_WINDOW_INVERTED"):
            estimate_sigma(pred, actual, provenance=inverted)
        numeric_inverted = {"sport": "nfl", "oof": True,
                            "window_start": 2025, "window_end": 2021}
        with pytest.raises(ValueError, match="SIGMA_WINDOW_INVERTED"):
            estimate_sigma(pred, actual, provenance=numeric_inverted)
        numeric_ok = {"sport": "nfl", "oof": True,
                      "window_start": 2021, "window_end": 2025}
        assert estimate_sigma(pred, actual, provenance=numeric_ok)["sigma"] > 0
        mixed_types = {"sport": "nfl", "oof": True,
                       "window_start": "2021-01-01", "window_end": 2025}
        with pytest.raises(ValueError, match="SIGMA_WINDOW_INVERTED"):
            estimate_sigma(pred, actual, provenance=mixed_types)

    def test_zero_variance_rejected(self):
        with pytest.raises(ValueError, match="SIGMA_ZERO_VARIANCE"):
            estimate_sigma(np.ones(300), np.ones(300), min_n=200, provenance=PROV)

    def test_min_n_below_two_rejected(self):
        # std(ddof=1) is undefined at n=1; min_n must be >= 2.
        with pytest.raises(ValueError, match="SIGMA_MIN_N_INVALID"):
            estimate_sigma(np.arange(5.0), np.arange(5.0) + 1.0, min_n=1,
                           provenance=PROV)


# ---------------- emit ----------------

def _record():
    d = discrete_football_margin(-3.0, 13.0, {3: 0.1, 7: 0.05}, PROV)
    q = cover_quote(d, -3.0)
    return margin_quote_record(
        d, q, event={"event_id": "evt-1"}, source_model=MODEL,
        sigma_provenance=PROV, generated_at_utc=TS,
    )


class TestEmit:
    def test_record_schema_and_fields(self):
        rec = _record()
        assert rec["schema"] == "sports.margin_quote.v2"
        assert rec["event_id"] == "evt-1"
        assert rec["home_spread"] == -3.0
        assert rec["research_only"] is True
        assert rec["action_authority"] is False
        assert rec["generated_at_utc"] == TS
        assert isinstance(rec["limitations"], list) and len(rec["limitations"]) > 0
        assert "EXCLUDING_PUSHES" in rec["warnings"]
        assert rec["source_model"]["artifact_sha256"] == MODEL["artifact_sha256"]

    def test_probabilities_sum(self):
        rec = _record()
        p = rec["probabilities"]
        assert p["p_cover"] + p["p_push"] + p["p_loss"] == pytest.approx(1.0, abs=1e-9)

    def test_validate_roundtrip(self):
        assert validate_record(_record()) is True

    def test_hash_stability(self):
        r1, r2 = _record(), _record()
        assert r1["record_sha256"] == r2["record_sha256"]
        d = discrete_football_margin(-3.0, 13.0, {3: 0.1, 7: 0.05}, PROV)
        q = cover_quote(d, -3.0)
        r3 = margin_quote_record(d, q, event={"event_id": "evt-2"},
                                 source_model=MODEL, sigma_provenance=PROV,
                                 generated_at_utc=TS)
        assert r3["record_sha256"] != r1["record_sha256"]

    def test_validate_missing_key(self):
        rec = _record()
        del rec["distribution_id"]
        with pytest.raises(ValueError, match="MARGIN_RECORD_SCHEMA_VIOLATION"):
            validate_record(rec)

    def test_validate_probability_sum(self):
        rec = _record()
        rec["probabilities"]["p_cover"] = 0.99
        with pytest.raises(ValueError, match="MARGIN_RECORD_(PROBABILITY_SUM|HASH_MISMATCH)"):
            validate_record(rec)

    def test_validate_authority(self):
        rec = _record()
        rec["action_authority"] = True
        with pytest.raises(ValueError, match="MARGIN_RECORD_(AUTHORITY_VIOLATION|HASH_MISMATCH)"):
            validate_record(rec)

    def test_validate_hash_mismatch(self):
        rec = _record()
        rec["record_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="MARGIN_RECORD_HASH_MISMATCH"):
            validate_record(rec)

    def test_event_id_required(self):
        d = normal_margin(0.0, 10.0, PROV)
        q = cover_quote(d, -3.5)
        with pytest.raises(ValueError, match="MARGIN_RECORD_EVENT_ID_REQUIRED"):
            margin_quote_record(d, q, event={}, source_model=MODEL,
                                sigma_provenance=PROV, generated_at_utc=TS)

    def test_stripped_ex_push_label_rejected(self):
        # A relabeled/rehashed record with EXCLUDING_PUSHES removed must not
        # pass validation while p_push > 0.
        rec = _record()
        assert rec["probabilities"]["p_push"] > 0.0
        assert "EXCLUDING_PUSHES" in rec["probabilities"]["labels"]
        rec["probabilities"]["labels"] = []
        rec["warnings"] = [w for w in rec["warnings"] if w != "EXCLUDING_PUSHES"]
        rec["record_sha256"] = _record_hash(rec)
        with pytest.raises(ValueError, match="MARGIN_RECORD_LABEL_VIOLATION"):
            validate_record(rec)
