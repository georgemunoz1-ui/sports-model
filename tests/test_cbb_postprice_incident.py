import copy
import json
import sys
from hashlib import sha256

from datetime import datetime, timezone

import pytest

from test_cbb_quote_evidence import make_source_fixture

from pipelines.cards.cbb_incident import LABEL, cbb_road_dog_review, incident_rows, main, review_sidecar


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
                  american=-110, market="spread", push=0.1, quote_status="EXACT_PAIR", arm="baseline")
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
    assert a["evidence_reason"] == "EVIDENCE_BUNDLE_REQUIRED"
    assert not a["incident_evaluable"] and a["home_margin_gap"] is None
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


@pytest.fixture
def retained(tmp_path, monkeypatch):
    # Wall-clock verification in production. The audit fixture must work on any CI date.
    class Clock(datetime):
        @classmethod
        def now(cls, tz):
            return datetime(2026, 11, 7, tzinfo=timezone.utc)
    monkeypatch.setattr("pipelines.cards.cbb_incident_bundle.datetime", Clock)
    raw = tmp_path / "market/raw"
    event, _ = make_source_fixture(raw)
    schedule = {k: event[k] for k in ("home", "away", "home_id", "away_id", "neutral", "start_time_utc")}
    census = [dict(schedule, event_id="CBB:1", status="STATUS_SCHEDULED")]
    identity = {"events": {"1": dict(schedule, ncaa_id="101", state="PRE",
                                     ncaa_start_time_utc=event["start_time_utc"])}}
    policy = {"registered_at_client_utc": "2026-11-06T08:00Z", "quote_cutoff_utc": "2026-11-06T10:00Z"}

    def write(path, obj, encode=json.dumps):
        path = tmp_path / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encode(obj))
        return sha256(path.read_bytes()).hexdigest()

    def run(*, corrupt=None, checked_utc="2026-11-06T12:00Z", extra_events=(), encode_policy=json.dumps):
        for extra in extra_events:
            info = {key: extra[key] for key in schedule}
            census.append(dict(info, event_id=extra["event_id"], status="STATUS_SCHEDULED"))
            identity["events"][extra["espn_id"]] = dict(info, state="PRE", ncaa_id="10"+extra["espn_id"],
                                                        ncaa_start_time_utc=extra["start_time_utc"])
        census_hash = write("census/events.json", census)
        policy_hash = write("evaluation-protocol.json", dict(policy, initial_schedule_sha256=census_hash), encode_policy)
        schedule_hash = write("cbb/schedule-identity.json", identity)
        freeze_hash = write("forecast-freeze.json", {
            "sealed_at_utc": "2026-11-06T09:00Z", "protocol_sha256": policy_hash,
            "census_sha256": census_hash, "files": {"cbb/schedule-identity.json": schedule_hash}})
        card = {"events": [event, *extra_events, {"event_id": "CBB:2", "league": "CBB", "contracts": []}],
                "forecast_freeze_sha256": freeze_hash, "evaluation_protocol_sha256": policy_hash}
        digest = write("delivered/card.json", card)
        write("verification.json", {"checked_utc": checked_utc, "card_sha256": digest})
        manifest = tmp_path / "SHA256SUMS.txt"
        manifest.write_text("".join(
            f"{sha256(p.read_bytes()).hexdigest()}  {p.relative_to(tmp_path).as_posix()}\n"
            for p in sorted(tmp_path.rglob("*.json"))))
        pin = sha256(manifest.read_bytes()).hexdigest()
        if corrupt:
            corrupt()
        data = (tmp_path/"delivered/card.json").read_bytes()
        return review_sidecar(data, evidence_root=tmp_path, manifest_sha256=pin)["rows"]

    return event, policy, identity, raw, run


@pytest.mark.parametrize("change,reason", [
    ("valid_at_cutoff", None), ("equivalent_offsets", None), ("below_threshold", None),
    ("post_tip", "QUOTE_NOT_PRE_TIP"), ("at_tip", "QUOTE_NOT_PRE_TIP"),
    ("after_cutoff", "QUOTE_AFTER_CUTOFF"), ("before_seal", "QUOTE_BEFORE_FORECAST_SEAL"),
    ("retrieval_disagrees", "PAIR_RETRIEVAL_MISMATCH"),
    ("invalid_retrieval", "INVALID_QUOTE_RETRIEVAL"), ("naive", "INVALID_QUOTE_RETRIEVAL"),
    ("missing_start", "INVALID_EVENT_START"), ("start_mismatch", "EVENT_START_MISMATCH"),
    ("after_verification", "QUOTE_AFTER_VERIFICATION"), ("verification_in_future", "VERIFICATION_TIME_OUT_OF_SEQUENCE"),
    ("missing_verified_start", "INVALID_VERIFIED_TIPOFF"), ("no_cutoff", "POLICY_QUOTE_CUTOFF_MISSING"),
    ("invalid_digest", "INVALID_SOURCE_DIGEST"), ("wrong_bytes", "SOURCE_DIGEST_MISMATCH"),
    ("missing_payload", "SOURCE_PAYLOAD_MISSING"), ("wrong_price", "SOURCE_CONTRACT_MISMATCH"),
    ("wrong_event", "SOURCE_EVENT_MISMATCH"), ("wrong_sides", "SOURCE_CONTRACT_MISMATCH"),
    ("wrong_lines", "SOURCE_CONTRACT_MISMATCH"), ("forged_receipt_time", "RECEIPT_RETRIEVAL_MISMATCH"),
    ("tampered_policy", "BOUND_FILE_DIGEST_MISMATCH"), ("unbound_card", "PRICED_CARD_NOT_BOUND"),
    ("malformed_side", "EXACT_SPREAD_PAIR_UNAVAILABLE"),
])
def test_retained_eligibility(retained, tmp_path, change, reason):
    event, policy, identity, raw, run = retained
    away, home = event["contracts"]
    corrupt = None
    times = {"post_tip": "19:00Z", "at_tip": "18:00Z", "after_cutoff": "10:01Z",
             "before_seal": "08:59Z", "invalid_retrieval": "bad", "naive": "10:00:00"}
    if change in times:
        stamp = "2026-11-06T" + times[change]
        for row in (home, away):
            row.update(quote_retrieved_utc=stamp, retrieved_at_utc=stamp)
        path = raw / "CBB-1.receipt.json"
        path.write_text(json.dumps(json.loads(path.read_bytes()) | {"retrieved_at_utc": stamp}))
    elif change == "equivalent_offsets":
        away["quote_retrieved_utc"] = "2026-11-06T05:00:00-05:00"
    elif change == "retrieval_disagrees":
        away["quote_retrieved_utc"] = "2026-11-06T09:59:59Z"
    elif change == "below_threshold":
        away.update(win=.70, loss=.20)
    elif change == "no_cutoff":
        del policy["quote_cutoff_utc"]
    elif change == "missing_start":
        del event["start_time_utc"]
    elif change == "missing_verified_start":
        del identity["events"]["1"]["ncaa_start_time_utc"]
    elif change == "start_mismatch":
        event["start_time_utc"] = "2026-11-06T22:00Z"
    elif change == "invalid_digest":
        away["source_sha256"] = home["source_sha256"] = "invalid"
    elif change == "wrong_bytes":
        path = raw/"CBB-1.json"
        corrupt = lambda: path.write_bytes(path.read_bytes() + b" ")
    elif change == "missing_payload":
        corrupt = (raw/"CBB-1.json").unlink
    elif change == "wrong_price":
        home["american"] = -101
    elif change == "wrong_event":
        home["espn_id"] = "3"
    elif change == "wrong_sides":
        away["book_outcome_id"], home["book_outcome_id"] = home["book_outcome_id"], away["book_outcome_id"]
    elif change == "wrong_lines":
        away["line"], home["line"] = 6.5, -6.5
    elif change == "forged_receipt_time":
        for row in (home, away):
            row.update(quote_retrieved_utc="2026-11-06T09:58Z", retrieved_at_utc="2026-11-06T09:58Z")
    elif change in ("unbound_card", "tampered_policy"):
        path = tmp_path / ("delivered/card.json" if change == "unbound_card" else "evaluation-protocol.json")
        corrupt = lambda: path.write_bytes(path.read_bytes() + b" ")
    elif change == "malformed_side":
        away["side"] = []
    checked = {"after_verification": "2026-11-06T09:59Z",
               "verification_in_future": "2027-01-01T00:00Z"}.get(change, "2026-11-06T12:00Z")
    row, uncovered = run(corrupt=corrupt, checked_utc=checked)
    assert uncovered["event_id"] == "CBB:2" and uncovered["evidence_reason"] == "EXACT_SPREAD_PAIR_UNAVAILABLE"
    assert row["incident_evaluable"] is (reason is None)
    assert row["incident_review"] == (LABEL if reason is None and change != "below_threshold" else None)
    assert row["evidence_reason"] == reason
    assert row["qualification"] == "NO_PICK" and row["allocation_units"] == 0
    assert row["action_authority"] is False
    if reason is None:
        assert row["verified_quote"]["observation_basis"] == "retrieval_only"
        assert row["home_margin_gap"] == -1.5
    else:
        assert row["verified_quote"] is None and row["decisive_probability"] is None

def test_bad_quote_isolated_between_independent_fixtures(retained):
    _, _, _, raw, run = retained
    middle, _ = make_source_fixture(raw, "3")
    last, _ = make_source_fixture(raw, "4")
    middle["contracts"][0]["american"] = -109
    rows = run(extra_events=[middle, last])
    assert [(r["event_id"], r["incident_evaluable"], r["evidence_reason"]) for r in rows] == [
        ("CBB:1", True, None), ("CBB:3", False, "SOURCE_CONTRACT_MISMATCH"),
        ("CBB:4", True, None), ("CBB:2", False, "EXACT_SPREAD_PAIR_UNAVAILABLE"),
    ]
    assert rows[0]["incident_review"] == rows[2]["incident_review"] == LABEL
    assert rows[1]["incident_review"] is None and rows[1]["verified_quote"] is None
    assert all(r["qualification"] == "NO_PICK" and r["action_authority"] is False
               and r["allocation_units"] == 0 for r in rows)


def test_ambiguous_cutoff_in_hash_bound_policy(retained):
    *_, run = retained
    def conflicting_cutoffs(policy):
        return json.dumps(policy)[:-1] + ', "quote_cutoff_utc": "2026-11-06T17:00Z"}'
    row, _ = run(encode_policy=conflicting_cutoffs)
    assert row["evidence_reason"] == "AMBIGUOUS_BOUND_DOCUMENT"
    assert row["incident_evaluable"] is False and row["incident_review"] is None
