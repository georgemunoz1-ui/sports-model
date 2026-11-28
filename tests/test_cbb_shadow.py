from copy import deepcopy

import numpy as np
import pytest

from scripts import cbb_shadow as model


def event():
    return {
        "id": "10",
        "season": {"year": 2027, "type": 2},
        "competitions": [
            {
                "date": "2026-11-05T03:00:00Z",
                "neutralSite": False,
                "status": {"type": {"name": "STATUS_SCHEDULED", "completed": False}},
                "competitors": [
                    {
                        "id": "1",
                        "homeAway": "home",
                        "team": {"displayName": "Home", "conferenceId": "2"},
                    },
                    {
                        "id": "2",
                        "homeAway": "away",
                        "team": {"displayName": "Away", "conferenceId": "3"},
                    },
                ],
            }
        ],
    }


def test_schedule_role_and_market_blind_inputs():
    espn = event()
    clean = model.normalized(espn)
    assert clean["day"] == "2026-11-04" and clean["d1"] and not clean["final"]
    changed = deepcopy(espn)
    changed["competitions"][0]["odds"] = [{"spread": -75, "overUnder": 500}]
    assert model.normalized(changed) == clean
    del changed["competitions"][0]["competitors"][1]["team"]["conferenceId"]
    assert not model.normalized(changed)["d1"]


def test_neutral_home_and_away_reverse_without_changing_total():
    state = {"1": np.array([4, 2, 8]), "2": np.array([-4, 3, 10])}
    h, a = model.project(state, {"h": "1", "a": "2", "neutral": True}, [3, 145])
    assert (a, h) == model.project(
        state, {"h": "2", "a": "1", "neutral": True}, [3, 145]
    )
    home, away = model.project(state, {"h": "1", "a": "2", "neutral": False}, [3, 145])
    assert home - away == (h - a) + 3 and home + away == h + a


def test_discrete_pair_support_excludes_ties_and_negative_scores():
    err = np.array([[0, 0], [1, 0], [-80, 0], [1, 0], [0, 1]])
    s = model.legal_scores(70, 70, err)
    assert model.pmf(s[:, 0] - s[:, 1]) == {
        "support": [-1, 1],
        "masses": [1 / 3, 2 / 3],
    }
    assert model.pmf(s.sum(axis=1)) == {"support": [141], "masses": [1.0]}
    with pytest.raises(ValueError, match="EMPTY_LEGAL_SUPPORT"):
        model.legal_scores(70, 70, np.array([[0, 0]]))
