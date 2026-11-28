import copy,datetime as dt,json
from pathlib import Path
import numpy as np
import pytest
from models.current import common
from models.current.baseline import feature,probabilities,IDS
from models.current.linear import predict
from models.nfl.contextual.recovered_inference import digest
from scripts.prepare_initial_baselines import causal_rows,parse
from scripts.prepare_mlb_official_current import innings_outs,pitcher
from pipelines.cards.selected import apply_default
from pipelines.cards.selection import SelectionError
from scripts.generate_card_force import load_adapter


def event(day,home=100,away=90,eid=None):
    return {'event_id':eid or 'NBA:'+day,'start_time_utc':day+'T12:00:00+00:00','home_id':'1','away_id':'2','home_team':'H','away_team':'A','neutral_site':False,'home_score':home,'away_score':away,'season':2026}


def test_future_and_same_day_scores_cannot_change_features():
    a=event('2026-01-01');b=event('2026-01-02');c=event('2026-01-03');d=event('2026-01-03',eid='NBA:other')
    before,_,_=causal_rows([a,b,c,d],95,'2026-01-06T00:00Z')
    altered=copy.deepcopy([a,b,c,d]);altered[1]['home_score']=250;altered[2]['away_score']=300
    after,_,_=causal_rows(altered,95,'2026-01-06T00:00Z')
    assert before[1][1]==after[1][1]
    assert before[2][1]==after[2][1]==before[3][1]==after[3][1]
    assert before[2][1]!=before[0][1]


def test_final_state_embargo_and_ids():
    g=[event('2026-01-01'),event('2026-01-02'),event('2026-01-03')]
    _,state,ids=causal_rows(g,95,'2026-01-03T18:00Z')
    assert ids==['NBA:2026-01-01'] and state['1']['n']==1


def package():
    now='2026-09-22T08:00:00Z'
    return {'league':'nba','schema':'sports.current_research_package.v1','model_id':IDS['nba'],'action_authority':False,'code_pins':{},'captured_at_utc':now,'training_cutoff_utc':now,'source_fetches':[{'fetched_at_utc':now}],'fitted_model':{},'team_state':{},'prior':100,'events':[],'covered_dates':['2026-09-22']}


def test_tampered_model_state_refused(tmp_path,monkeypatch):
    p=package();p['model_sha256']=digest({'model':{},'state':{},'prior':100});(tmp_path/'nba').mkdir();path=tmp_path/'nba/package.json';path.write_text(json.dumps(p));monkeypatch.setenv('SPORTS_RESEARCH_PACKAGE_DIR',str(tmp_path))
    assert common.load('nba')[0]['prior']==100
    p['prior']=101;path.write_text(json.dumps(p))
    with pytest.raises(ValueError,match='MODEL_STATE_DIGEST'):common.load('nba')


@pytest.mark.parametrize('change,asof,reason',[
 ('none','2026-09-22T07:59Z','PACKAGE_NOT_CURRENT'),('none','2026-09-22T14:01Z','PACKAGE_NOT_CURRENT'),('old_source','2026-09-22T08:01Z','PACKAGE_NOT_CURRENT'),('future_fit','2026-09-22T08:01Z','FUTURE_FITTED_STATE'),('no_source','2026-09-22T08:01Z','SOURCE_RECEIPTS_REQUIRED')])
def test_context_cutoff_guards(change,asof,reason):
    p=package()
    if change=='old_source':p['source_fetches'][0]['fetched_at_utc']='2026-09-21T00:00Z'
    if change=='future_fit':p['training_cutoff_utc']='2026-09-22T09:00Z'
    if change=='no_source':p['source_fetches']=[]
    with pytest.raises(ValueError,match=reason):common.current(p,asof)


def test_research_never_implicitly_replaces_tested_default(monkeypatch):
    monkeypatch.delenv('SPORTS_INITIAL_BASELINES',raising=False)
    for l in IDS:
        with pytest.raises(SelectionError):load_adapter(l)
    monkeypatch.setenv('SPORTS_INITIAL_BASELINES','1')
    r=apply_default('nba',{}, {'model_id':IDS['nba'],'dose':1,'action_authority':True})
    assert r['dose']==0 and r['action_authority'] is False
    assert r['diagnostics']['research_selection']['accuracy_default'] is False
    with pytest.raises(ValueError,match='IDENTITY'):apply_default('nba',{}, {'model_id':'failed-ensemble'})


def test_baseball_outs_are_not_decimal_innings():
    assert innings_outs('4.1')==13 and innings_outs('3.2')==11
    with pytest.raises(ValueError):innings_outs('4.3')


def test_pitcher_cutoff_duplicate_and_identity():
    r={'player':{'id':1},'gameType':'R','date':'2026-09-20','game':{'gamePk':10},'stat':{'inningsPitched':'4.1','outs':13,'earnedRuns':2,'strikeOuts':4,'baseOnBalls':1,'battersFaced':20,'gamesStarted':1}}
    j={'stats':[{'group':{'displayName':'pitching'},'type':{'displayName':'gameLog'},'splits':[r]}]}
    out=pitcher(j,1,'2026-09-22',{'10'});assert out['era']==round(54/13,3) and out['k']==20
    future=copy.deepcopy(r);future['date']='2026-09-22';future['game']['gamePk']=99;j['stats'][0]['splits'].append(future)
    assert pitcher(j,1,'2026-09-22',{'10'})==out
    j['stats'][0]['splits'].append(r)
    with pytest.raises(ValueError,match='DUPLICATE'):pitcher(j,1,'2026-09-22',{'10'})
    with pytest.raises(ValueError,match='IDENTITY'):pitcher(j,2,'2026-09-22',{'10'})


def test_mls_three_way_probability_mass():
    head={'kind':'poisson','impute':[0],'mean':[0],'scale':[1],'coefficient':[0],'intercept':np.log(1.5)}
    p=probabilities({'home_goals':head,'away_goals':head},[0],'mls')
    assert sum(p)==pytest.approx(1) and p[0]==pytest.approx(p[2]) and p[1]>0


def test_nba_cup_final_is_not_regular_season():
    e={'season':{'year':2026},'seasonType':{'name':'Regular Season'},'competitions':[{'type':{'id':'39'}}]}
    assert parse(e,'nba',True) is None


def test_binary_draw_replay_and_immutable_output(tmp_path,monkeypatch):
    p=package();e=event('2026-09-23');p.update(events=[e],model_sha256='fitted',data_grade='TEST_FIXTURE',model_lineage={})
    ctx={'package':p,'package_sha256':'test','cutoff':'2026-09-22T08:01Z'}
    monkeypatch.setenv('SPORTS_RESEARCH_DRAW_OUTPUT',str(tmp_path/'one'));a=common.emit(e,ctx,{},.6,2,200,10000)
    monkeypatch.setenv('SPORTS_RESEARCH_DRAW_OUTPUT',str(tmp_path/'two'));b=common.emit(e,ctx,{},.6,2,200,10000)
    x=np.load(Path(a['simulation']['draw_directory'])/'winner_draws.npy');y=np.load(Path(b['simulation']['draw_directory'])/'winner_draws.npy')
    assert np.array_equal(x,y) and a['sim_p']==float(x.mean()) and a['model_p']==.6
    with pytest.raises(FileExistsError):common.emit(e,ctx,{},.6,2,200,10000)


def test_nfl_runtime_default_cannot_point_to_failed_ensemble():
    from pipelines.cards.selection import select
    root=Path(__file__).resolve().parents[1]
    config=json.loads((root/'data/nfl/contextual_v1/runtime.json').read_text())
    assert config['default_research_model']==select('nfl')['default_model_id']
    assert 'combined' not in config['default_research_model']


@pytest.mark.parametrize("flag,expected", [([], None), (["--max-state-age-hours", "12"], 12.0)])
def test_card_cli_binds_explicit_state_age_policy_without_refitting(tmp_path, monkeypatch, flag, expected):
    import sys
    from scripts import generate_card_force as runner
    from models.current.baseline import FEATURES

    source = package()
    cutoff = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    day = (cutoff + dt.timedelta(days=2)).date().isoformat()
    fixture = event(day)
    fixture.pop("home_score")
    fixture.pop("away_score")
    fixture["slate_date"] = day
    stamp = (cutoff - dt.timedelta(hours=18)).isoformat()

    def head(kind, intercept):
        return {"kind": kind, "coefficient": [0.] * 9, "intercept": intercept, "mean": [0.] * 9,
                "scale": [1.] * 9, "impute": [0.] * 9}

    source.update(captured_at_utc=cutoff.isoformat(), training_cutoff_utc=cutoff.isoformat(),
                  source_fetches=[{"fetched_at_utc": cutoff.isoformat()}], events=[fixture],
                  covered_dates=[day], feature_names=FEATURES, data_grade="TEST_ONLY", model_lineage={},
                  fitted_model={"winner": head("logistic", 0.5), "margin": head("linear", 3.),
                                "total": head("linear", 200.)},
                  team_state={t: {"last": stamp, "n": 10, "for": 100., "against": 100.} for t in ("1","2")})
    source["model_sha256"] = digest({"model": source["fitted_model"], "state": source["team_state"], "prior": source["prior"]})
    (tmp_path/"nba").mkdir()
    (tmp_path/"nba"/"package.json").write_text(json.dumps(source))
    out = tmp_path/"card"
    monkeypatch.setenv("SPORTS_RESEARCH_PACKAGE_DIR", str(tmp_path))
    monkeypatch.setenv("SPORTS_INITIAL_BASELINES", "1")
    monkeypatch.setenv("SPORTS_RESEARCH_DRAW_OUTPUT", str(out/"draws"))
    monkeypatch.setattr(sys, "argv", ["generate_card_force.py", "--league", "nba", "--date", day,
        "--simulations", "50", "--initial-research-baselines", "--identity-semantics", "legacy.v1",
        "--as-of-utc", cutoff.isoformat(), "--output-dir", str(out), *flag])
    with pytest.raises(SystemExit) as exited:
        runner.main()
    assert exited.value.code == 0
    row = json.loads((out/"diagnostic_card.json").read_text())["forecasts"][0]
    receipt = row["diagnostics"]["state_freshness_receipt"]
    assert receipt["max_state_age_hours_policy"] == expected
    assert ("HOME:CONSUMED_STATE_OLDER_THAN_POLICY" in receipt["blocking_reasons"]) == bool(flag)
    assert row["model_p"] == pytest.approx(1 / (1 + np.exp(-0.5)))
    assert row["home_id"] == "1" and row["away_id"] == "2"


@pytest.mark.parametrize("league,hours", [("cfb", 10), ("nba", -1), ("nhl", 0), ("mls", float("nan")),
                                          ("nba", float("inf")), ("nba", True)])
def test_invalid_policy_rejected_before_acquisition(league, hours):
    from scripts.generate_card_force import generate
    with pytest.raises(ValueError, match="STATE_AGE"):
        generate("unused", league, "unused", 1, None, max_state_age_hours=hours)
