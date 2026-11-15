"""Scenario inputs, priors and covers remain distinct from reviewed model outputs."""
import json

import pytest

from pipelines.cards.missingness import verify_audit
from sportsim.cli import main


def check(packet,mode,side,event,products):
    return verify_audit(packet["missingness_audit"],league=side,event_id=event,
                        model_id=f"scenario/{side}/{mode}",products=products,forecast=packet["binding"])


@pytest.mark.parametrize("sport",["nba","nfl","nhl","mlb"])
def test_csv_missing_fields_and_no_team_rating_are_visible(tmp_path,capsys,sport):
    r=tmp_path/"ratings.csv";r.write_text("team,attack,defense\nH,,1.01\n")
    p=tmp_path/"receipt.json"
    assert main(["game","--sport",sport,"--ratings",str(r),"--home","H","--away","A","--sims","20",
                 "--audit-output",str(p),"--json"])==0
    packet=json.loads(p.read_bytes())
    assert packet==json.loads(capsys.readouterr().out)["missingness"]
    assert check(packet,"game",sport,f"scenario/{sport}/game/A@H",["winner","score_margin","total"])
    assert packet["binding"]["source_evidence"]["ratings"]["default_fields_by_team"]["H"]==["elo","attack","pace"]
    assert packet["missingness_audit"]["details"]["teams_using_average_rating"]==["A"]
    original=p.read_bytes()
    assert main(["game","--sport",sport,"--ratings",str(r),"--home","H","--away","A","--sims","20","--audit-output",str(p)])==2
    assert p.read_bytes()==original


@pytest.mark.parametrize("key,content,reason",[
    ("ratings",None,"ACQUISITION_FAILURE"),
    ("ratings","team,attack\n","SUPPLIED_RATINGS_EMPTY"),
    ("ratings","team,attack\nA,1\nA,1.1\n","DUPLICATE_OR_UNRESOLVED_RATING_TEAM"),
    ("games","date,home,away,home_score,away_score\n2026-01-01,BOS,NYK,102,\n","PARTIAL_SCORE_CANNOT_BECOME_UNPLAYED"),
    ("games","date,home,away\n2026-01-01,H,A\n2026-01-01,H,A\n","DUPLICATE_OR_AMBIGUOUS_GAME_IDENTITY"),
])
def test_supplied_failed_or_ambiguous_source_refuses(tmp_path,capsys,key,content,reason):
    path=tmp_path/"p.csv"
    if content is not None:
        path.write_text(content)
    assert main(["game","--sport","nba","--home","H","--away","A","--sims","25","--json","--"+key,str(path)])==2
    report=json.loads(capsys.readouterr().out)
    assert report["status"]=="BLOCKED"
    packet=report["missingness"]
    assert reason in (report["reason"], packet["missingness_audit"]["details"]["source_state"])
    assert check(packet,"game","nba","scenario/nba/game/A@H",["coverage"])
