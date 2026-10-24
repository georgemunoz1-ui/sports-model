"""Contract tests, not predictive validation or promotion evidence."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from models.common import discrete_research as D
from models.common.margin_contract import bind_margin, cover_quote, validate_quote

CUTOFF = "2026-10-19T16:00:00Z"
SOURCE = D.digest({"test_fixture": "integer paired margins, not actual games"})
SCOPES = [(league, settlement) for league, contracts in D.SETTLEMENTS.items()
          for settlement in contracts]


def law(league="nfl", settlement="FULL_GAME_OT_REGULAR", values=(-7, -3, 3, 7),
        masses=(.1, .2, .3, .4)):
    return D.make_distribution(values, masses, league=league, product="margin",
        settlement=settlement, model_id="synthetic.contract.v1", provenance={
            "event_id": "synthetic-event", "cutoff": CUTOFF,
            "source_sha256": SOURCE, "orientation": "HOME_MINUS_AWAY"})


def bound(artifact):
    return bind_margin(artifact, event_id="synthetic-event", cutoff=CUTOFF,
                       source_sha256=SOURCE)


@pytest.mark.parametrize("league,settlement", SCOPES)
@pytest.mark.parametrize("line", [-7.5, -7, -3.5, -3, 0, 3, 3.5, 7, 7.5])
def test_signed_handicaps_and_pushes_against_direct_counts(league, settlement, line):
    d = law(league, settlement); before = copy.deepcopy(d); view = bound(d)
    # Independent oracle: direct comparison, no shared settlement helper.
    values = np.array(d["support"]); masses = np.array(d["masses"])
    win = masses[values + line > 0].sum()
    push = masses[values + line == 0].sum()
    loss = masses[values + line < 0].sum()
    home = cover_quote(view, line); away = cover_quote(view, line, orientation="away")
    assert list(home["probabilities"].values()) == pytest.approx([win, 0, push, 0, loss])
    assert list(away["probabilities"].values()) == pytest.approx([loss, 0, push, 0, win])
    assert home["side_handicap"] == line and away["side_handicap"] == -line
    assert home["record_sha256"] != away["record_sha256"]
    assert home["p_cover_ex_push"] == pytest.approx(win / (win + loss))
    assert validate_quote(home, view) and d == before
    assert view.distribution_id == d["distribution_sha256"]


@pytest.mark.parametrize("line,home,away", [
    (-.25, [.5, 0, 0, .3, .2], [.2, .3, 0, 0, .5]),
    (.25, [.5, .3, 0, 0, .2], [.2, 0, 0, .3, .5]),
    (-.75, [0, .5, 0, 0, .5], [.5, 0, 0, .5, 0]),
    (.75, [.8, 0, 0, .2, 0], [0, .2, 0, 0, .8]),
])
def test_mls_quarter_handicaps_keep_half_outcomes(line, home, away):
    d = bound(law("mls", "REGULATION_90_STOPPAGE", [-1, 0, 1], [.2, .3, .5]))
    for side, expected in [("home", home), ("away", away)]:
        q = cover_quote(d, line, orientation=side)
        assert list(q["probabilities"].values()) == pytest.approx(expected)
        assert q["p_cover_ex_push"] is None
        assert q["ex_push_basis"] == "UNAVAILABLE_SPLIT_HANDICAP"
        assert q["winning_stake_probability"] == pytest.approx(expected[0] + .5 * expected[1])
        assert q["losing_stake_probability"] == pytest.approx(expected[4] + .5 * expected[3])


@pytest.mark.parametrize("line", [-.25, .25, .75])
def test_quarter_handicaps_refused_outside_mls(line):
    with pytest.raises(ValueError, match="QUARTER_LINES_ONLY_MLS"):
        cover_quote(bound(law()), line)


def test_all_push_has_no_conditional_probability():
    q = cover_quote(bound(law(values=[3], masses=[1])), -3)
    assert q["probabilities"]["push"] == 1 and q["p_cover_ex_push"] is None
    assert q["ex_push_basis"] == "UNDEFINED_ALL_PUSH"


@pytest.mark.parametrize("field,value", [("event_id", "different-event"),
    ("cutoff", "2026-10-19T17:00:00Z"), ("source_sha256", "f" * 64)])
def test_same_event_and_source_binding_required(field, value):
    args = dict(event_id="synthetic-event", cutoff=CUTOFF, source_sha256=SOURCE)
    args[field] = value
    with pytest.raises(ValueError, match="EVENT_CUTOFF_SOURCE_MISMATCH"):
        bind_margin(law(), **args)


@pytest.mark.parametrize("orientation", [None, "AWAY_MINUS_HOME"])
def test_missing_or_reversed_margin_orientation_is_refused(orientation):
    d = law(); d["provenance"]["orientation"] = orientation
    d.pop("distribution_sha256"); d["distribution_sha256"] = D.digest(d)
    with pytest.raises(ValueError, match="EXPLICIT_HOME_MINUS_AWAY_REQUIRED"):
        bound(d)


@pytest.mark.parametrize("line", [True, float("nan"), float("inf"), -.1])
def test_malformed_lines_refused(line):
    with pytest.raises(ValueError):
        cover_quote(bound(law()), line)


@pytest.mark.parametrize("league,settlement", [s for s in SCOPES if not D.SETTLEMENTS[s[0]][s[1]]])
def test_illegal_final_ties_are_not_conditioned_away(league, settlement):
    with pytest.raises(ValueError, match="FINAL_TIE_UNSUPPORTED"):
        law(league, settlement, [0, 1], [.2, .8])


def test_frozen_input_and_returned_copies_cannot_mutate_bound_law():
    d = law(); view = bound(d); identity = view.distribution_id
    d["masses"][0] = .9
    view.artifact()["masses"][0] = .9
    assert view.distribution_id == identity
    assert cover_quote(view, -3)["probabilities"]["push"] == .3
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        bound(d)


@pytest.mark.parametrize("field,value", [("side", "AWAY"), ("action_authority", True),
    ("prospective_grade_eligible", True), ("predictive_validation", "PASS"),
    ("settlement", "REGULATION"), ("event_id", "other"),
    ("probability_basis", "CONDITIONAL_NON_PUSH")])
def test_resealing_does_not_hide_semantic_tampering(field, value):
    d = bound(law()); q = cover_quote(d, -3); q[field] = value
    q.pop("record_sha256"); q["record_sha256"] = D.digest(q)
    with pytest.raises(ValueError, match="MARGIN_QUOTE_BINDING_MISMATCH"):
        validate_quote(q, d)


def test_protocol_alone_or_winner_only_cannot_enable_spread_product():
    with pytest.raises(ValueError, match="BOUND_DISCRETE_MARGIN_REQUIRED"):
        cover_quote({"home_win": .6, "draw": .2, "away_win": .2}, -.25)
    d = law(); d["product"] = "total"; d["support"] = [1, 2, 3, 7]
    d.pop("distribution_sha256"); d["distribution_sha256"] = D.digest(d)
    with pytest.raises(ValueError, match="MARGIN_PRODUCT_REQUIRED"):
        bound(d)


def test_retained_nfl_reconstruction_preserves_law_key_numbers_and_hold():
    path = Path(__file__).parent / "fixtures/margin_integration/nfl_retrospective.json"
    raw = path.read_bytes(); fixture = json.loads(raw); d = fixture["distribution"]
    p = d["provenance"]
    view = bind_margin(d, event_id=p["event_id"], cutoff=p["cutoff"],
        source_field="parent_forecast_sha256", source_sha256=p["parent_forecast_sha256"])
    for key in [-17, -14, -10, -7, -3, 0, 3, 7, 10, 14, 17]:
        expected = sum(m for x, m in zip(d["support"], d["masses"]) if x == key)
        assert view.push_mass(key) == expected
        assert cover_quote(view, -key)["probabilities"]["push"] == expected
    assert cover_quote(view, -7.5)["probabilities"]["win"] == pytest.approx(.551492, abs=5e-7)
    assert fixture["evaluation_status"] == "HOLD"
    assert fixture["mode"] == "RETROSPECTIVE_RECONSTRUCTION"
    assert not p["artifact_existed_at_forecast_cutoff"]
    assert view.distribution_id == d["distribution_sha256"]
    np.testing.assert_array_equal(view.sample(100000, 20261021), view.sample(100000, 20261021))
    assert path.read_bytes() == raw
