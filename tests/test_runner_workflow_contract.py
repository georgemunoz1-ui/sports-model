"""Exercise the workflow's terminal command with actual on-disk artifacts."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from pipelines.cards.recipient_card import write_recipient_card
from scripts.prepare_card_workflow_inputs import validate_request

ROOT = Path(__file__).resolve().parents[1]
STEPS = yaml.safe_load((ROOT / ".github/workflows/diagnostic-shadow-card.yml").read_text())["jobs"]["generate-card"]["steps"]
GATE = next(s for s in STEPS if s.get("id") == "validate")
DATE = "2030-11-08"
CUTOFF = DATE + "T10:00:00Z"


def run_gate(tmp, env):
    proc = subprocess.run(["bash", "-euo", "pipefail", "-c", GATE["run"]], cwd=tmp,
                          env={**os.environ, "PYTHONPATH": str(ROOT), **env},
                          text=True, capture_output=True)
    return proc.returncode, json.loads((tmp / "output/card/manifest.json").read_text())


def prepare(tmp, league="nhl", *, n=1):
    out = tmp / "output/card"
    evidence = tmp / "output/run-evidence"
    out.mkdir(parents=True)
    evidence.mkdir()
    games = [dict(event_id=f"game-{i}", slate_date=DATE, gameday=DATE, home_team="Home",
                  away_team="Away", start_time_utc=DATE + "T16:00:00Z") for i in range(n)]
    pp = tmp / "package.json"
    pp.write_text(json.dumps(dict(events=games, covered_dates=[DATE])))
    pin = hashlib.sha256(pp.read_bytes()).hexdigest()
    (evidence / "package-inputs.json").write_text(json.dumps(dict(league=league, action_authority=False,
        package_path=str(pp), package_sha256=pin, artifact_id="123", archive_sha256="1" * 64)))
    card = dict(card_date=DATE, league=league.upper(), simulation_count=100000,
                as_of_utc=CUTOFF, scheduled_game_count=n, forecast_count=n, action_authority=False,
                authority="SHADOW_ONLY", actionable=False, package_binding=dict(sha256=pin,date=DATE,league=league),
                forecasts=[dict(**event, model_id="test-only", action_authority=False, model_winner="Home",
                                forecast_status="FORECAST_GENERATED", model_p=.5, sim_p=.5, stochastic_sim_p=.5)
                           for event in games])
    for name in ("pit_integrity.json", "diagnostic_card.csv", "diagnostic_card.md", "run.log"):
        (out / name).write_text("fixture")
    if league == "mlb":
        (out/"divergence").mkdir()
        for ext in ("json", "csv", "md"):
            (out/f"divergence/divergence_report.{ext}").write_text("fixture")
    env = dict(LEAGUE=league, CARD_DATE=DATE, AS_OF_UTC=CUTOFF, FORECAST_EXIT_CODE="0",
               PACKAGE_ARTIFACT_ID="123", PACKAGE_ARCHIVE_SHA256="1"*64,SIMULATION_COUNT="100000")
    return env, card, out


def write_card(card, out):
    (out/"diagnostic_card.json").write_text(json.dumps(card))
    write_recipient_card(card, out/"diagnostic_card.html")


@pytest.mark.parametrize("league", ["cfb","mlb","wnba","nba","nhl","mls"])
def test_shared_success_and_published_readback(tmp_path, league):
    env, card, out = prepare(tmp_path, league=league)
    write_card(card, out)
    rc, manifest = run_gate(tmp_path, env)
    assert rc == 0 and manifest["overall_status"] == "PASS"
    assert manifest["registration_policy"] == "EXISTING_REGISTRATION_RULES"
    assert manifest["forecasted_events"] == manifest["recipient_readback"]["rows"] == 1
    from pipelines.cards.runner_contract import verify_archived_card
    downloaded = tmp_path / "retrieved"
    shutil.copytree(out, downloaded)
    verify_archived_card(out, downloaded)
    (downloaded/"diagnostic_card.html").write_text("<html></html>")
    with pytest.raises(ValueError, match="READBACK"):
        verify_archived_card(out, downloaded)


@pytest.mark.parametrize(("case","reason"), [
    ("blocked_receipt_zero_exit","WEEKLY_STATE_MISSING"),
    ("nonzero_exit_populated_card","GENERATOR_NONZERO:2"),
    ("missing_exit","GENERATOR_EXIT_NOT_RECORDED"),
    ("wrong_day","CARD_REQUEST_MISMATCH"),
    ("wrong_home","CARD_FIXTURE_MISMATCH"),
    ("wrong_package","CARD_PACKAGE_BINDING_MISMATCH"),
    ("omitted_rows","CARD_EVENT_SET_MISMATCH"),
    ("refused_row_zero_exit","CARD_HAS_REFUSALS_OR_INCIDENTS"),
    ("empty_artifact","NO_GAMES_VERIFICATION_REQUIRED"),
    ("script_only_card","RECIPIENT_HTML_READBACK_MISMATCH"),
    ("cbb_unavailable","CBB_RUNNER_UNAVAILABLE_ON_THIS_REVISION"),
    ("dedicated_nfl_refused","NFL_RUNNER_RECEIPT_BLOCKED_OR_MISMATCH"),
])
def test_final_gate_refuses_and_preserves_outputs(tmp_path, case, reason):
    league = "nfl" if case=="dedicated_nfl_refused" else "cbb" if case=="cbb_unavailable" else "nhl"
    env, card, out = prepare(tmp_path,league,n=0 if case=="empty_artifact" else 1)
    if case=="blocked_receipt_zero_exit":
        (out/"runner_failure.json").write_text(json.dumps({"status":"BLOCKED","reason":"WEEKLY_STATE_MISSING"}))
    elif case=="nonzero_exit_populated_card":
        env["FORECAST_EXIT_CODE"]="2"
    elif case=="missing_exit":
        del env["FORECAST_EXIT_CODE"]
    elif case=="wrong_day":
        card["card_date"]="2030-11-07"
    elif case=="wrong_home":
        card["forecasts"][0]["home_team"]="Wrong"
    elif case=="wrong_package":
        card["package_binding"]["sha256"]="b"*64
    elif case=="omitted_rows":
        card["forecasts"]=[]
    elif case=="refused_row_zero_exit":
        card["forecasts"][0].update(forecast_status="BLOCKED",refusal_reason="HISTORY_REQUIRED",model_p=None,sim_p=None,
                                    model_winner=None, stochastic_sim_p=None)
        card["forecast_count"]=0
    elif case=="cbb_unavailable":
        with pytest.raises(ValueError) as rejection:
            validate_request("cbb")
        env["REQUEST_ERROR"]=str(rejection.value)
    elif case=="dedicated_nfl_refused":
        (out/"nfl_runner_receipt.json").write_text(json.dumps({"status":"PARTIAL","reason":"STATE_REVIEW_REQUIRED"}))
    write_card(card,out)
    if case=="script_only_card":
        (out/"diagnostic_card.html").write_text("<script>fillRows()</script>")
    before={p:p.read_bytes() for p in out.rglob("*") if p.is_file()}
    rc, manifest=run_gate(tmp_path,env)
    assert rc == 2 and manifest["overall_status"] == "FAIL"
    assert manifest["failure_reason"].startswith(reason)
    assert all(p.read_bytes()==value for p,value in before.items())


def test_validation_and_readback_precede_both_registration_steps():
    names=[step["name"] for step in STEPS]
    upload=next(s for s in STEPS if s.get("id")=="card_artifact")
    assert "always()" in GATE["if"] and "always()" in upload["if"]
    assert names.index(GATE["name"]) < names.index(upload["name"]) < names.index("Verify published card readback")
    for name in ("Register priority-league prospective research card","Register pregame MLB calibration card"):
        registration=next(s for s in STEPS if s["name"]==name)
        assert "success()" in registration["if"] and "always()" not in registration["if"]
        assert names.index(name)>names.index("Verify published card readback")


@pytest.mark.parametrize(("league","winner","allocation","expected"), [
    ("mls", "Draw", 0, "PASS"), ("cfb", "Draw", 0, "FAIL"),
    ("nba","Another team",0,"FAIL"), ("nba","Home",1,"FAIL")
])
def test_sport_specific_subject_and_allocation(tmp_path,league,winner,allocation,expected):
    env,card,out=prepare(tmp_path,league)
    card["forecasts"][0].update(model_winner=winner,allocated_units=allocation)
    write_card(card,out)
    rc,manifest=run_gate(tmp_path,env)
    assert manifest["overall_status"]==expected and (rc==0)==(expected=="PASS")


def test_invented_heads_in_refused_row(tmp_path):
    env,card,out=prepare(tmp_path)
    card["forecasts"][0].update(forecast_status="BLOCKED",refusal_reason="MISSING")
    card["forecast_count"]=0
    write_card(card,out)
    rc,manifest=run_gate(tmp_path,env)
    assert rc==2 and "REFUSAL_CONTAINS_FORECAST" in manifest["failure_reason"]


@pytest.mark.parametrize(("mode","exit_code"), [("RETROSPECTIVE_DIAGNOSTIC",2),("PREGAME_DIAGNOSTIC",0)])
def test_native_nfl_receipt_uses_exact_dated_card_and_excludes_replay(tmp_path,mode,exit_code):
    env,card,out=prepare(tmp_path,"nfl")
    card.update(execution_mode=mode,canonical_prospective_eligible=False)
    card["forecasts"][0]["forecast_sha256"]="a"*64
    write_card(card,out)
    sha=lambda name: hashlib.sha256((out/name).read_bytes()).hexdigest()
    native=dict(schema="nfl.runner_receipt.v1", canonical_prospective_eligible=False, status="COMPLETED", action_authority=False, league="nfl", date=DATE,
                package_sha256=card["package_binding"]["sha256"],execution_mode=mode,
                card_sha256=sha("diagnostic_card.json"),html_sha256=sha("diagnostic_card.html"),
                events=[dict(event_id="game-0",status="COMPLETED",forecast_sha256="a"*64)])
    (out/"nfl_runner_receipt.json").write_text(json.dumps(native))
    rc,manifest=run_gate(tmp_path,env)
    assert rc==exit_code
    if rc:
        assert "NFL_RUNNER_RECEIPT" in manifest["failure_reason"]
    else:
        assert manifest["registration_policy"]=="NATIVE_DIAGNOSTIC_INELIGIBLE"
        guard=next(step["if"] for step in STEPS if step.get("id")=="research_registration")
        assert "steps.validate.outputs.registration_policy == 'EXISTING_REGISTRATION_RULES'" in guard


@pytest.mark.parametrize(("child_rc","blocked","expected_rc"),[(0,True,2),(2,False,2),(0,False,0)])
def test_generator_capture_and_final_job_gate_together(tmp_path,child_rc,blocked,expected_rc):
    env,card,out=prepare(tmp_path)
    write_card(card,out)
    shutil.move(out,tmp_path/"fixture")
    scripts=tmp_path/"scripts"
    scripts.mkdir()
    (scripts/"generate_card_force.py").write_text(
        "import shutil,os,json\nfrom pathlib import Path\n"
        "out=Path('output/card');shutil.copytree('fixture',out)\n"
        "if os.environ['BLOCKED']=='True': (out/'runner_failure.json').write_text(json.dumps({'status':'BLOCKED','reason':'STATE_UNAVAILABLE'}))\n"
        "raise SystemExit(int(os.environ['CHILD_RC']))\n")
    github_output=tmp_path/"github-output"
    env.update(INITIAL_RESEARCH="true",GITHUB_OUTPUT=str(github_output),CHILD_RC=str(child_rc),BLOCKED=str(blocked))
    generate=next(s for s in STEPS if s.get("id")=="forecast")
    proc=subprocess.run(["bash","-euo","pipefail","-c",generate["run"]],cwd=tmp_path,env={**os.environ,**env})
    assert proc.returncode==0
    key,recorded=github_output.read_text().strip().split("=")
    assert key=="exit_code" and recorded==str(child_rc)
    env["FORECAST_EXIT_CODE"]=recorded
    assert run_gate(tmp_path,env)[0]==expected_rc
    assert (out/"diagnostic_card.json").read_bytes()==(tmp_path/"fixture/diagnostic_card.json").read_bytes()
