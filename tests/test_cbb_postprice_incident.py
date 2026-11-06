import copy
import json
import sys
from hashlib import sha256

import pytest

from pipelines.cards.cbb_incident import LABEL, cbb_road_dog_review, incident_rows, main


ARGS = dict(league="CBB", market="spread", side="away", neutral=False, line=3.5,
            win_mass=0.72, push_mass=0.10, loss_mass=0.18, has_paired_price=True)


@pytest.mark.parametrize("change,evaluable,flag", [
    ({}, True, True),
    ({"win_mass": 0.71999, "loss_mass": 0.18001}, True, False),
    ({"neutral": True}, True, False), ({"line": -3.5}, True, False),
    ({"line": 0}, True, False), ({"neutral": None}, False, False),
    ({"has_paired_price": 1}, False, False), ({"side": "home"}, False, False),
    ({"market": "winner"}, False, False), ({"league": "NBA"}, False, False),
    ({"arm": "mean_only"}, False, False), ({"line": float("nan")}, False, False),
    ({"win_mass": None}, False, False), ({"win_mass": 1.2}, False, False),
    ({"loss_mass": -0.1}, False, False), ({"push_mass": 0}, False, False),
    ({"win_mass": 0, "loss_mass": 0, "push_mass": 1}, False, False),
])
def test_inclusive_decisive_gate(change, evaluable, flag):
    assert cbb_road_dog_review(**(ARGS | change)) == (evaluable, flag)


def card():
    shared = dict(event_id="CBB:1", book_event_id="123", book="book",
                  settlement="FULL_GAME_INCLUDING_OVERTIME", home="H", away="A",
                  quote_retrieved_utc="2026-11-06T10:00Z", source_sha256="a"*64,
                  american=-110, market="spread", push=0.1)
    return {"events": [dict(event_id="CBB:1", league="CBB", neutral=False,
                            home="H", away="A", home_margin=1.5, contracts=[
                                dict(shared, side="away", win=.72, loss=.18, line=3, book_outcome_id="away3"),
                                dict(shared, side="home", win=.18, loss=.72, line=-3, book_outcome_id="home3")]) ]}


@pytest.mark.parametrize("changed", [
    {"book": "other"}, {"line": 3.5}, {"event_id": "CBB:2"},
    {"arm": "challenger"}, {"quote_retrieved_utc": None}, {"away": "H"},
    {"settlement": "FIRST_HALF"}, {"book_outcome_id": "home3"}, {"american": None},
])
def test_reject_unpaired_or_wrong_scope(changed):
    data = card()
    data["events"][0]["contracts"][0].update(changed)
    row, = incident_rows(data)
    assert row["incident_evaluable"] is False and row["market_home_margin"] is None
    assert row["qualification"] == "NO_PICK" and row["home_margin_gap"] is None


def test_sidecar_preserves_input_and_refuses_existing_output(tmp_path, monkeypatch):
    data = card()
    data["events"].append(dict(event_id="CBB:2", league="CBB", contracts=[]))
    original = copy.deepcopy(data)
    a, b = incident_rows(data)
    assert a["incident_review"] == LABEL and a["home_margin_gap"] == -1.5
    assert a["action_authority"] is False and a["allocation_units"] == 0
    assert not b["incident_evaluable"] and data == original
    source, out = tmp_path/"source.json", tmp_path/"result.json"
    source.write_text(json.dumps(data))
    monkeypatch.setattr(sys, "argv", ["review", str(source), str(out)])
    main()
    assert json.loads(out.read_text())["priced_card_sha256"] == sha256(source.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        main()
    monkeypatch.setattr(sys, "argv", ["review", str(source), str(source)])
    with pytest.raises(FileExistsError):
        main()


def test_duplicate_events_fails_closed():
    data = card()
    data["events"] *= 2
    with pytest.raises(ValueError):
        list(incident_rows(data))
