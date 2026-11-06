import copy
import pytest
from scripts.review_mlb_current_readiness import census, pbp_check

def test_schedule_census_refuses_missing_and_duplicate():
    good = {"totalGames":1,"dates":[{"date":"2026-09-23","totalGames":1,"games":[{"gamePk":1}]}]}
    assert len(census(good,"2026-09-23")) == 1
    bad = copy.deepcopy(good); bad["totalGames"] = 2
    with pytest.raises(ValueError,match="CENSUS"): census(bad,"2026-09-23")
    bad = copy.deepcopy(good); bad["totalGames"]=2; bad["dates"][0]["totalGames"]=2
    bad["dates"][0]["games"] *= 2
    with pytest.raises(ValueError,match="DUPLICATE"): census(bad,"2026-09-23")

def fixture():
    game={"gamePk":1,"teams":{"home":{"score":2},"away":{"score":1}}}
    feed={"gamePk":1,"gameData":{"status":{"abstractGameState":"Final"}},
          "liveData":{"linescore":{"teams":{"home":{"runs":2},"away":{"runs":1}}},
                      "plays":{"allPlays":[{"about":{"atBatIndex":0,"isComplete":True},
                                           "result":{"homeScore":2,"awayScore":1}}]}}}
    return game,feed

def test_pbp_acceptance_is_explicitly_narrow():
    game,feed=fixture()
    assert pbp_check(game,feed)["status"]=="FINAL_SEQUENCE_AND_SCORE_RECONCILED"
    assert "PRIOR_DAY_ONLY" in pbp_check(game,feed)["scope"]

@pytest.mark.parametrize("fault",["identity","sequence","score","incomplete"])
def test_pbp_refuses_corrupt_feed(fault):
    game,feed=fixture()
    if fault=="identity": feed["gamePk"]=2
    if fault=="sequence": feed["liveData"]["plays"]["allPlays"][0]["about"]["atBatIndex"]=1
    if fault=="score": feed["liveData"]["linescore"]["teams"]["home"]["runs"]=3
    if fault=="incomplete": feed["liveData"]["plays"]["allPlays"][0]["about"]["isComplete"]=False
    with pytest.raises(ValueError): pbp_check(game,feed)
