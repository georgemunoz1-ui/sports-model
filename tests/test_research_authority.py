import json
import hashlib
import pytest
from pipelines.cards.research_authority import AuthorityError, normalized_sidecar, write_sidecar


def contract(market, side, arm):
    return dict(event_id="CFB:1", arm=arm, market=market, side=side, action_authority=False,
                allocation_units=0, qualification="NO_PICK", official_selection=False)


def fixture():
    contracts = [contract(market, side, "baseline")
                 for market, sides in [("winner", ("home", "away")), ("spread", ("home", "away")),
                                       ("total", ("over", "under"))] for side in sides]
    arm = dict(arm="mean-only", model_id="test.margin", action_authority=False, contracts=[])
    event = dict(event_id="CFB:1", league="CFB", action_authority=False,
                 qualification="NO_PICK", allocated_units=0, contracts=contracts,
                 challengers=[arm, dict(arm="total", model_id="test.total", action_authority=False,
                                        contracts=[contract("total", s, "total") for s in ("over", "under")])])
    return dict(schema="sports.pregame_full_research_card.v2", authority="OFF",
                health=dict(official_release_eligible=False, action_authority=False,
                            release_override=False), release_eligible=False, allocated_units=0,
                qualified_selections=[], events=[event], league_schedule_counts={"CFB": 1})


@pytest.mark.parametrize("legacy", ["OFF", False, "missing"])
def test_safe_encodings_and_scopes(legacy):
    card = fixture()
    if legacy != "missing":
        card["events"][0]["authority"] = legacy
    raw = json.dumps(card).encode()
    out = normalized_sidecar(raw)
    assert out["source_sha256"] == hashlib.sha256(raw).hexdigest()
    event, = out["events"]
    assert len(event["baseline_contracts"]) == 6
    assert [len(a["contracts"]) for a in event["challengers"]] == [0, 2]
    scopes = [out, event, *event["baseline_contracts"], *event["challengers"],
              *event["challengers"][1]["contracts"]]
    assert all(s["action_authority"] is False and s["official_selection"] is False
               and s["allocated_units"] == 0 and s["qualification"] == "NO_PICK" for s in scopes)
    assert all("authority" not in s for s in scopes)


def scope(card, name):
    e = card["events"][0]
    return {"card": card, "health": card["health"], "event": e,
            "contract": e["contracts"][0], "arm": e["challengers"][1],
            "shadow_contract": e["challengers"][1]["contracts"][0]}[name]


@pytest.mark.parametrize("name,key", [
    ("card", "authority"), ("card", "release_eligible"), ("card", "qualified_selections"),
    ("health", "action_authority"), ("health", "release_override"),
    ("event", "action_authority"), ("event", "allocated_units"), ("event", "qualification"),
    ("contract", "official_selection"), ("contract", "action_authority"),
    ("contract", "allocation_units"), ("contract", "qualification"),
    ("arm", "action_authority"), ("shadow_contract", "action_authority"),
    ("shadow_contract", "allocation_units"), ("shadow_contract", "official_selection"),
])
def test_missing_required_control(name, key):
    c = fixture()
    del scope(c, name)[key]
    with pytest.raises(AuthorityError):
        normalized_sidecar(json.dumps(c).encode())


@pytest.mark.parametrize("name,key,value", [
    ("card","authority","ON"), ("event","authority","false"), ("event","authority",None),
    ("contract","action_authority","OFF"), ("arm","action_authority",1),
    ("health","official_release_eligible",True), ("shadow_contract","official_selection","false"),
    ("shadow_contract","allocation_units",False), ("card","allocated_units","0"),
    ("event","book_qualification","PICK"), ("event","allocated_units",0.01),
    ("card","qualified_selections",[1]), ("arm","wagering_enabled",True),
    ("event","wagering_authority","ACTION_ENABLED"), ("event","nhl_joint",{"authority":True}),
    ("event","nhl_joint",{}), ("card","schema","future.schema"), ("contract","event_id","CFB:2"),
    ("contract","side","over"), ("shadow_contract","arm","baseline"),
    ("card","league_schedule_counts",{"CFB":2}),
])
def test_invalid_or_conflicting_values(name, key, value):
    c = fixture()
    scope(c, name)[key] = value
    with pytest.raises(AuthorityError):
        normalized_sidecar(json.dumps(c).encode())


@pytest.mark.parametrize("mutate", [
    lambda c:c["events"].append(c["events"][0]),
    lambda c:c["events"][0]["contracts"].pop(),
    lambda c:c["events"][0]["contracts"].append(c["events"][0]["contracts"][0]),
    lambda c:c["events"][0]["challengers"][1]["contracts"].pop(),
    lambda c:c["events"][0]["challengers"].append(c["events"][0]["challengers"][0]),
])
def test_scope_integrity(mutate):
    c = fixture()
    mutate(c)
    with pytest.raises(AuthorityError):
        normalized_sidecar(json.dumps(c).encode())


@pytest.mark.parametrize("fragment", ['"action_authority":true,"action_authority":false', '"a":NaN'])
def test_ambiguous_json_rejected(fragment):
    with pytest.raises(AuthorityError):
        normalized_sidecar(('{'+fragment+', '+json.dumps(fixture())[1:]).encode())


def test_create_only_and_no_writes_on_failure(tmp_path):
    inp, out = tmp_path/"card.json", tmp_path/"sidecar.json"
    raw = json.dumps(fixture()).encode()
    inp.write_bytes(raw)
    with pytest.raises(FileExistsError):
        write_sidecar(inp, inp)
    write_sidecar(inp, out)
    with pytest.raises(FileExistsError):
        write_sidecar(inp, out)
    assert inp.read_bytes() == raw
    ino = tmp_path/"invalid.json"
    ino.write_text('{"schema":"bad"}')
    with pytest.raises(AuthorityError):
        write_sidecar(ino, tmp_path/"missing.json")
    assert not (tmp_path/"missing.json").exists()
