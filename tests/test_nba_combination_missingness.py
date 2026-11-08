"""The predictor's model/code pin stays intact. All data and fitted parameters here are synthetic."""
from copy import deepcopy
from pathlib import Path
import hashlib

import pytest
from research import nba_forecast_combination as model
from scripts.run_nba_forecast_combination import bound, predictions
from pipelines.cards.missingness import verify_audit
import json, subprocess, sys


@pytest.mark.parametrize("stage",["C1","C2"])
def test_withholding_each_source_isolation_fitted_parity_and_readback(stage):
    from test_nba_forecast_combination import CombinationTests
    f=CombinationTests();f.setUp()
    try:
        good=f.rows[-1];bad=deepcopy(f.rows[-2]);del bad["sources"]["B1"]
        state={"fitted":True,"stage":stage,"protocol_hash":model.digest(f.protocol),
               "code_hash":hashlib.sha256(Path(model.__file__).read_bytes()).hexdigest(),
               "created_at":"2019-01-01T00:00:00Z","trained_events":[],"trained_event_keys":[],
               "source_stratum":model.stratum(good,stage),"train_before":"2019-01-01T00:00:00Z",
               "alpha":0.1,"weight":0.4,"scaler":{"mean":[0.]*len(model.FEATURES),"scale":[1.]*len(model.FEATURES)},
               "gamma":[.001]*len(model.FEATURES)}
        state["state_hash"]=model.digest(state)
        a,b=predictions([good,bad],f.root,state,f.protocol)["predictions"]
        for k,v in model.predict(good,f.root,state,f.protocol).items():assert a[k]==v
        assert b["emitted_stage"]=="B0_FALLBACK" and b["challenger_emitted"] is False
        assert verify_audit(a["missingness_audit"],**bound(a))
        probes=a["missingness_audit"]["details"]["perturbations"]
        assert probes["B0"]["emitted_stage"] is None and probes["B1"]["emitted_stage"]=="B0_FALLBACK"
        assert ("databallr" in probes)==(stage=="C2")
        reordered=deepcopy(good);reordered["sources"]=dict(reversed(list(reordered["sources"].items())))
        assert predictions([reordered],f.root,state,f.protocol)["predictions"][0]["home_margin"]==a["home_margin"]
        a["home_margin"]=12345
        assert not verify_audit(a["missingness_audit"],**bound(a))
        assert predictions([good,good],f.root,state,f.protocol)["emitted_count"]==0
        for filename,value in (("data",{"rows":[good,bad]}),("protocol",f.protocol),("state",state)):
            (f.root/filename).write_text(json.dumps(value))
        out=f.root/"operator.json"
        cmd=[sys.executable,"scripts/run_nba_forecast_combination.py","predict","--stage",stage,
             "--dataset",str(f.root/"data"),"--protocol",str(f.root/"protocol"),"--state",str(f.root/"state"),"--output",str(out)]
        run=subprocess.run(cmd,capture_output=True,text=True)
        assert run.returncode==2, run.stderr
        stored=json.loads(out.read_bytes())
        assert stored["status"]=="PARTIAL" and stored["emitted_count"]==1
        assert all(verify_audit(r["missingness_audit"],**bound(r)) for r in stored["predictions"])

    finally:
        f.doCleanups()
