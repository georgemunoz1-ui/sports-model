"""Opt-in offline NFL count-support challenger; reads supported artifacts and emits distinct research heads."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

from models.nfl.contextual.model import TARGETS, fit, load_artifact, predict_frame
from models.nfl.contextual.recovered_inference import digest

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).with_name("nfl_report_count_design.json")
FEATURE = "report_missing_count"
ARCHIVE_PATH = ROOT/"data/nfl/qb_margin_v1/acquisition.json"
SAVED = {"home_win":"p_home", "home_margin":"pred_margin", "total_points":"pred_total"}


def support(train):
    """Same listwise training population used by contextual.model.fit for all three heads."""
    v = train.dropna(subset=list(TARGETS))[FEATURE]
    if v.empty or not v.isin([0,1,2]).all():
        raise ValueError("UNIDENTIFIABLE_TRAINING_SUPPORT")
    return {int(k):int(n) for k,n in v.value_counts().sort_index().items()}


def transform(frame, counts):
    levels = sorted(counts)
    if not levels or any(type(k) is not int or k not in (0,1,2) or type(n) is not int or n <= 0
                         for k,n in counts.items()):
        raise ValueError("INVALID_TRAINING_SUPPORT")
    if levels != list(range(levels[0], levels[-1]+1)):
        raise ValueError("NONCONTIGUOUS_TRAINING_SUPPORT")
    values = frame[FEATURE]
    if not values.isin([0,1,2]).all():
        raise ValueError("UNSUPPORTED_INPUT_COUNT")
    return frame.assign(**{FEATURE:values.clip(levels[0],levels[-1])})


def metrics(frame, prefix):
    if frame.empty:
        return None
    result={"events":len(frame)}
    for t in TARGETS:
        z=frame.dropna(subset=[t])
        y=z[t].to_numpy()
        predictions=z[prefix+t].to_numpy()
        if t=="home_win":
            p=np.where(y==1, predictions, 1-predictions)
            result[t]={"n":len(z), "brier":float(np.mean((y-predictions)**2)),
                       "log_loss":float(-np.mean(np.log(p)))}
        else:
            err=y-predictions
            result[t]={"n":len(z), "mean_error":float(err.mean()), "mae":float(abs(err).mean()),
                       "rmse":float(np.sqrt((err**2).mean()))}
    return result


def replay(archive, dest, examples=()):
    design=json.loads(CONFIG.read_bytes())
    pins=json.loads(ARCHIVE_PATH.read_bytes())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != pins["archive_sha256"]:
        raise ValueError("HISTORICAL_ARCHIVE_HASH")
    tables={}
    with zipfile.ZipFile(archive) as z:
        for name in ("features.csv","oof_predictions.csv"):
            b=z.read("evaluation/"+name)
            if hashlib.sha256(b).hexdigest()!=pins["extracted"][name]:
                raise ValueError("HISTORICAL_INPUT_HASH")
            tables[name]=pd.read_csv(io.BytesIO(b))
    features=tables["features.csv"].set_index("game_id",verify_integrity=True)
    saved=tables["oof_predictions.csv"]
    parent=load_artifact(ROOT/"data/nfl/contextual_v1/model_packed.json")
    if digest(parent)!=design["parent_model_sha256"]:
        raise ValueError("PARENT_ARTIFACT_CHANGED")
    dest.mkdir(exist_ok=False,parents=True)
    folds=[]; pairs=[]; summaries={}
    for arm in design["selected_arms"]:
        ref=saved[saved.arm==arm].set_index("game_id",verify_integrity=True)
        for year in range(2019,2026):
            train=features[features.season<year]
            test=features[features.season==year]
            archive_test=ref[ref.season==year].reindex(test.index)
            if set(test.index)!=set(ref[ref.season==year].index):
                raise ValueError("OOF_POPULATION_MISMATCH")
            model=fit(train,arm,parent["design"])
            counts=support(train)
            if max(model["training_seasons"])>=year or sum(counts.values())!=model["training_rows"]:
                raise ValueError("FOLD_TRAINING_SCOPE")
            amended=transform(test,counts)
            old=predict_frame(model,test)
            new=predict_frame(model,amended)
            rows=test[list(TARGETS)+["season",FEATURE]].copy()
            rows["arm"]=arm
            rows["effective_count"]=amended[FEATURE]
            rows["ood"]=amended[FEATURE]!=test[FEATURE]
            max_diff={}
            for t,k in SAVED.items():
                if not np.allclose(test[t],archive_test[t],rtol=0,atol=0,equal_nan=True):
                    raise ValueError("OUTCOME_IDENTITY_MISMATCH")
                max_diff[t]=float(np.max(np.abs(old[t]-archive_test[k])))
                if max_diff[t]>1e-7:
                    raise ValueError(f"INCUMBENT_OOF_REPLAY_MISMATCH:{year}:{arm}:{t}:{max_diff[t]}")
                rows["incumbent_"+t]=old[t]
                rows["candidate_"+t]=new[t]
                for label, predictions in (("incumbent", old[t]), ("candidate", new[t])):
                    error = rows[t]-predictions
                    if t == "home_win":
                        rows[label+"_winner_brier"] = error**2
                    else:
                        rows[label+"_"+t+"_abs_error"] = error.abs()
            pairs.append(rows)
            folds.append({"arm":arm,"test_season":year,"latest_training_season":max(model["training_seasons"]),
                          "fitted_parameters_sha256":digest(model),"fit_counts":counts,"test_counts":dict(test[FEATURE].value_counts().items()),
                          "scored":len(test),"ood":int(rows.ood.sum()),"max_head_replay_error":max_diff})
    both=pd.concat(pairs)
    for arm,rows in both.groupby("arm"):
        summaries[arm]={}
        for scope,data in (("all",rows),("ood",rows[rows.ood])):
            summaries[arm][scope]={k:metrics(data,k+"_") for k in ("incumbent","candidate")}
    examples_result=[]
    full=support(features)
    for path,expected in examples:
        data=Path(path).read_bytes()
        if hashlib.sha256(data).hexdigest()!=expected:
            raise ValueError("EXAMPLE_FORECAST_HASH")
        e=json.loads(data)
        if (e["model_artifact_sha256"] != design["parent_model_sha256"] or e["market_input"] is not False
                or datetime.fromisoformat(e["cutoff_utc"]) >= datetime.fromisoformat(e["event"]["start_time_utc"])
                or e["action_authority"] is not False):
            raise ValueError("EXAMPLE_FIT_SCOPE")
        frame=pd.DataFrame([e["features"]]);derived=transform(frame,full);out={}
        for arm in design["selected_arms"]:
            params=parent["arms"][arm]
            if params["training_rows"]!=sum(full.values()):
                raise ValueError("DEPLOYMENT_COUNT_SCOPE")
            o=predict_frame(params,frame); n=predict_frame(params,derived)
            for t in TARGETS:
                if abs(float(o[t][0])-float(e["arms"][arm]["prediction"][t]))>1e-9:
                    raise ValueError("ARCHIVED_HEAD_MISMATCH")
            out[arm]={t:{"incumbent":float(o[t][0]),"challenger":float(n[t][0])} for t in TARGETS}
        examples_result.append({"event":e["event"]["event_id"],"forecast_sha256":expected,"cutoff":e["cutoff_utc"],
                                "reported_count":int(frame[FEATURE].iloc[0]),"effective_count":int(derived[FEATURE].iloc[0]),"arms":out,
                                "role":"DEVELOPMENT_DIAGNOSTIC"})
    paired_path=dest/"paired_losses.csv"
    both.to_csv(paired_path,index=True)
    result={"model_id":design["model_id"],"ran_at_utc":datetime.now(timezone.utc).isoformat(),
            "design_sha256":hashlib.sha256(CONFIG.read_bytes()).hexdigest(),"pinned_source_archive":pins["archive_sha256"],
            "arm_identities": {arm:{"parent":parent["arms"][arm]["model_id"],
                                    "challenger":design["model_id"]+"."+arm} for arm in design["selected_arms"]},
            "scored_heads":list(TARGETS),"quote_or_simulation_translation":False,
            "source_facts":"Retrospective season folds with prior-season training. Historical publication and registration times unavailable.",
            "folds":folds,"summaries":summaries,"deployment_training_counts":full,"development_examples":examples_result,
            "unique_historical_test_games":int(both.index.nunique()),"unique_ood_games":int(both[both.ood].index.nunique()),
            "paired_rows_sha256":hashlib.sha256(paired_path.read_bytes()).hexdigest(),"wagering_authority":False,
            "predictive_validation":"NOT_ESTABLISHED","official_release":"HOLD"}
    (dest/"result.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--forecast",nargs=2,action="append",metavar=("PATH","SHA256"),default=[])
    a=parser.parse_args()
    result=replay(a.archive,a.output,a.forecast)
    print(result["unique_historical_test_games"],result["unique_ood_games"],result["deployment_training_counts"])
