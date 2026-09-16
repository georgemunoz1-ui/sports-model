"""Read-only deterministic scorer for manifest-pinned frozen forecasts and grades."""
from __future__ import annotations
import argparse, csv, datetime as dt, io, json, math, statistics as S, sys
from pathlib import Path

from research import offline_benchmark as B
from research.adapters.base import (
    EVALUATABLE_SCOPES, EvaluationError, GradeIndex, MANIFEST_SCHEMA_VERSION,
    ROW_SCHEMA_VERSION, canonical_bytes, digest, finite_number, load_json_readonly,
    load_jsonl_readonly, require_sha256, sha256_bytes, sha256_file,
)
from research.adapters.mlb import MLBAdapter
from research.adapters.cfb import CFBAdapter
from research.adapters.mls import MLSAdapter

REPORT_SCHEMA_VERSION = "evaluation_report.v1"
BINARY_BRIER_CONVENTION = "SINGLE_CLASS_MEAN_(P-Y)^2"
BINARY_BRIER_ALTERNATE = "TWO_CLASS_SUM_(2X_SINGLE)"
MULTICLASS_BRIER_CONVENTION = "CLASS_SUM_MEAN"
QLEVELS = {"p05":.05,"p10":.10,"p25":.25,"p50":.50,"p75":.75,"p90":.90,"p95":.95}
INTERVALS = {"50_percent":("p25","p75"),"80_percent":("p10","p90"),"90_percent":("p05","p95")}
ADAPTERS = {"MLB":MLBAdapter(),"CFB":CFBAdapter(),"MLS":MLSAdapter()}


def _json(v): return canonical_bytes(v)+b"\n"
def _jsonl(rows): return b"".join(canonical_bytes(r)+b"\n" for r in rows)


def _csv(rows, fields):
    b=io.StringIO(newline=""); w=csv.DictWriter(b,fieldnames=fields,extrasaction="ignore",lineterminator="\n")
    w.writeheader(); [w.writerow({k:r.get(k) for k in fields}) for r in rows]
    return b.getvalue().encode()


def _write(path: Path, data: bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=data: raise EvaluationError(f"immutable output collision: {path}")
        return
    with path.open("xb") as f: f.write(data)


def _manifest(v):
    if not isinstance(v,dict) or v.get("schema_version")!=MANIFEST_SCHEMA_VERSION:
        raise EvaluationError(f"manifest schema must be {MANIFEST_SCHEMA_VERSION}")
    arts=v.get("artifacts")
    if not isinstance(arts,list) or not arts: raise EvaluationError("manifest artifacts[] required")
    paths=set(); hashes=set()
    for e in arts:
        if not isinstance(e,dict) or str(e.get("league","")).upper() not in ADAPTERS:
            raise EvaluationError("invalid manifest artifact entry")
        p=e.get("path"); h=require_sha256(e.get("sha256",""),"manifest artifact sha256")
        if not p or p in paths: raise EvaluationError(f"duplicate/missing manifest path: {p}")
        if h in hashes: raise EvaluationError(f"duplicate forecast artifact hash in manifest: {h}")
        if not e.get("artifact_schema"): raise EvaluationError("manifest artifact_schema missing")
        paths.add(p); hashes.add(h)
    return v


def _path(manifest: Path, p: str):
    x=Path(p); return (x if x.is_absolute() else manifest.parent/x).resolve()


def _validate_row(r):
    req={"schema_version","league","event_id","event_date_local","forecast_output_hash","grade_record_hash",
         "model_id","model_arm_id","evidence_scope","canonical_prospective_eligible","forecast_cutoff_utc",
         "scheduled_start_utc","graded_at_utc","outcome_type","outcome_value","probabilities","actuals",
         "target_contract","score_target_compatible","score_metrics_excluded_reason"}
    if req-set(r): raise EvaluationError(f"evaluation row missing {sorted(req-set(r))}")
    if r["schema_version"]!=ROW_SCHEMA_VERSION or r["evidence_scope"] not in EVALUATABLE_SCOPES:
        raise EvaluationError("invalid evaluation row schema/scope")
    require_sha256(r["forecast_output_hash"],"row forecast hash"); require_sha256(r["grade_record_hash"],"row grade hash")
    p=r["probabilities"]
    if r["outcome_type"]=="BINARY_HOME_WIN":
        vals=[finite_number(p[k],k) for k in ("home_win","away_win")]
        if r["outcome_value"] not in (0,1) or any(not 0<=x<=1 for x in vals) or not math.isclose(sum(vals),1,abs_tol=1e-9): raise EvaluationError("invalid binary row")
    elif r["outcome_type"]=="MULTICLASS_HDA":
        vals=[finite_number(p[k],k) for k in ("home_win","draw","away_win")]
        if r["outcome_value"] not in ("HOME","DRAW","AWAY") or any(not 0<=x<=1 for x in vals) or not math.isclose(sum(vals),1,abs_tol=1e-9): raise EvaluationError("invalid multiclass row")
    else: raise EvaluationError(f"unknown outcome type {r['outcome_type']}")


def _error(pairs):
    if not pairs: return {"status":"NOT_AVAILABLE","n":0,"mae":None,"rmse":None}
    e=[a-p for a,p in pairs]
    return {"status":"AVAILABLE","n":len(e),"mae":S.mean(map(abs,e)),"rmse":math.sqrt(S.mean(x*x for x in e))}


def _qmetrics(rows,target):
    pins={}
    for key,tau in QLEVELS.items():
        vals=[]
        for r in rows:
            if not r["score_target_compatible"]: continue
            y=r.get("actuals",{}).get(target); q=r.get("quantiles",{}).get(target,{}).get(key)
            if y is None or q is None: continue
            y=finite_number(y,target); q=finite_number(q,key); e=y-q; vals.append(max(tau*e,(tau-1)*e))
        pins[key]={"status":"AVAILABLE" if vals else "NOT_AVAILABLE_IN_FROZEN_ARTIFACT","n":len(vals),"mean":S.mean(vals) if vals else None}
    cov={}
    for label,(lo,hi) in INTERVALS.items():
        hits=[]; widths=[]
        for r in rows:
            if not r["score_target_compatible"]: continue
            y=r.get("actuals",{}).get(target); qs=r.get("quantiles",{}).get(target,{})
            if y is None or qs.get(lo) is None or qs.get(hi) is None: continue
            y=finite_number(y,target); a=finite_number(qs[lo],lo); b=finite_number(qs[hi],hi)
            if a>b: raise EvaluationError("crossing quantiles")
            hits.append(int(a<=y<=b)); widths.append(b-a)
        cov[label]={"status":"AVAILABLE" if hits else "NOT_AVAILABLE_IN_FROZEN_ARTIFACT","n":len(hits),"coverage":S.mean(hits) if hits else None,"mean_interval_width":S.mean(widths) if widths else None,"bounds":[lo,hi]}
    ys=[]; means=[]; qfull=[]
    for r in rows:
        qs=r.get("quantiles",{}).get(target,{}); y=r.get("actuals",{}).get(target); m=r.get("point_predictions",{}).get(target)
        if r["score_target_compatible"] and y is not None and m is not None and all(qs.get(k) is not None for k in QLEVELS):
            ys.append(finite_number(y,target)); means.append(finite_number(m,target)); qfull.append({tau:finite_number(qs[k],k) for k,tau in QLEVELS.items()})
    full=B.state_scores(ys,means,qfull) if ys else None
    return {"pinball_by_quantile":pins,"central_interval_coverage":cov,"full_seven_quantile_state_scores":{"status":"AVAILABLE" if full else "NOT_AVAILABLE_IN_FROZEN_ARTIFACT","value":full}}


def _summary(rows):
    r0=rows[0]; out={"league":r0["league"],"model_id":r0["model_id"],"model_arm_id":r0["model_arm_id"],"evidence_scope":r0["evidence_scope"],"n_input_rows":len(rows),"n_graded":len(rows)}
    if r0["outcome_type"]=="BINARY_HOME_WIN":
        y=[int(r["outcome_value"]) for r in rows]; ps=[[r["probabilities"]["away_win"],r["probabilities"]["home_win"]] for r in rows]
        s=B.probability_scores(y,ps); one=S.mean((r["probabilities"]["home_win"]-int(r["outcome_value"]))**2 for r in rows)
        if not math.isclose(s["brier_sum"],2*one,abs_tol=1e-12): raise EvaluationError("binary Brier invariant failed")
        out["probability_metrics"]={"binary_brier_single_class_mean":one,"binary_brier_multiclass_sum_mean":s["brier_sum"],"log_loss_mean":s["log_loss"],"winner_accuracy_diagnostic_only":S.mean(int((r["probabilities"]["home_win"]>=.5)==bool(r["outcome_value"])) for r in rows),"brier_convention":BINARY_BRIER_CONVENTION,"brier_alternate":BINARY_BRIER_ALTERNATE}
    else:
        m={"HOME":0,"DRAW":1,"AWAY":2}; y=[m[r["outcome_value"]] for r in rows]; ps=[[r["probabilities"][k] for k in ("home_win","draw","away_win")] for r in rows]; s=B.probability_scores(y,ps)
        out["probability_metrics"]={"multiclass_brier_class_sum_mean":s["brier_sum"],"multiclass_log_loss_mean":s["log_loss"],"top_class_accuracy_diagnostic_only":S.mean(int(max(range(3),key=lambda i:ps[j][i])==y[j]) for j in range(len(rows))),"brier_convention":MULTICLASS_BRIER_CONVENTION}
    good=[r for r in rows if r["score_target_compatible"]]
    out["target_compatibility"]={"score_compatible_rows":len(good),"score_excluded_rows":len(rows)-len(good),"exclusion_reasons":sorted({r["score_metrics_excluded_reason"] for r in rows if r["score_metrics_excluded_reason"]})}
    out["continuous_metrics"]={}
    for t in ("home_margin","total"):
        pairs=[(finite_number(r["actuals"][t],t),finite_number(r["point_predictions"][t],t)) for r in good if r.get("actuals",{}).get(t) is not None and r.get("point_predictions",{}).get(t) is not None]
        out["continuous_metrics"][t]={"point_error":_error(pairs),"quantiles":_qmetrics(rows,t)}
    return out


def _loss(r):
    y=int(r["outcome_value"]); p=r["probabilities"]["home_win" if y else "away_win"]
    if p<=0: raise EvaluationError("zero realized probability")
    return -math.log(p)


def _pairkey(r): return f"{r['event_id']}|{r['forecast_cutoff_utc']}|{r['evidence_scope']}|{digest(r['target_contract'])}"


def _pairs(rows,seed,draws):
    ex={}
    for r in rows:
        if r["league"]=="CFB" and r.get("experiment_id"): ex.setdefault(r["experiment_id"],[]).append(r)
    reports=[]
    for eid in sorted(ex):
        roles={}; bad=False
        for r in ex[eid]:
            role=(r.get("pairing") or {}).get("pair_role")
            if role not in {"incumbent","challenger"}: reports.append({"experiment_id":eid,"paired_comparison_status":"REJECTED_MISSING_PAIR_ROLE"}); bad=True; break
            roles.setdefault(role,[]).append(r)
        if bad: continue
        if set(roles)!={"incumbent","challenger"}: reports.append({"experiment_id":eid,"paired_comparison_status":"REJECTED_INCOMPLETE_POPULATION"}); continue
        inc,ch=roles["incumbent"],roles["challenger"]; im={(r["model_id"],r["model_arm_id"]) for r in inc}; cm={(r["model_id"],r["model_arm_id"]) for r in ch}
        if len(im)!=1 or len(cm)!=1: reports.append({"experiment_id":eid,"paired_comparison_status":"REJECTED_MULTIPLE_MODELS_PER_ROLE"}); continue
        iid=next(iter(im))[0]; cid=next(iter(cm))[0]
        if not all((r.get("pairing") or {}).get("paired_with_model_id") in (None,cid) for r in inc) or not all((r.get("pairing") or {}).get("paired_with_model_id") in (None,iid) for r in ch): reports.append({"experiment_id":eid,"paired_comparison_status":"REJECTED_PAIR_MODEL_CROSS_REFERENCE_MISMATCH"}); continue
        u={(r.get("pairing") or {}).get("paired_game_universe_hash") for r in ex[eid]}
        if len(u)!=1 or None in u: reports.append({"experiment_id":eid,"paired_comparison_status":"REJECTED_EVENT_UNIVERSE_MISMATCH"}); continue
        a={_pairkey(r):r for r in inc}; b={_pairkey(r):r for r in ch}
        if len(a)!=len(inc) or len(b)!=len(ch) or set(a)!=set(b): reports.append({"experiment_id":eid,"paired_comparison_status":"REJECTED_INCOMPLETE_POPULATION","incumbent_count":len(inc),"challenger_count":len(ch),"paired_count":len(set(a)&set(b))}); continue
        keys=sorted(a); base={k:_loss(a[k]) for k in keys}; chall={k:_loss(b[k]) for k in keys}; dates={k:a[k]["event_date_local"] for k in keys}
        if any(a[k]["event_date_local"]!=b[k]["event_date_local"] for k in keys): reports.append({"experiment_id":eid,"paired_comparison_status":"REJECTED_DATE_MISMATCH"}); continue
        nd=len(set(dates.values())); rep={"experiment_id":eid,"paired_comparison_status":"PAIRED_POPULATION_VALID","incumbent_model_id":iid,"incumbent_model_arm_id":next(iter(im))[1],"challenger_model_id":cid,"challenger_model_arm_id":next(iter(cm))[1],"required_event_set_hash":next(iter(u)),"computed_pair_key_set_hash":digest(keys),"eligible_pair_count":len(keys),"rejected_pair_count":0,"mean_log_loss_delta_challenger_minus_incumbent":S.mean(chall[k]-base[k] for k in keys),"n_date_clusters":nd}
        rep["paired_date_cluster_bootstrap"]={"status":"NOT_RUN_INSUFFICIENT_DATE_CLUSTERS","n_date_clusters":nd} if nd<2 else {"status":"AVAILABLE",**B.paired_day_bootstrap(keys,dates,base,chall,seed,draws=draws)}; reports.append(rep)
    return reports


def _md(r):
    lines=["# Frozen Forecast Evaluation Report","",f"- Scope: `{r['evaluation_scope']}`",f"- Canonical prospective eligible: `{r['canonical_prospective_eligible']}`",f"- Dataset: `{r['canonical_row_dataset_sha256']}`",f"- Report: `{r['report_hash']}`","","## Model summaries","","```json",json.dumps(r["model_summaries"],sort_keys=True,indent=2,allow_nan=False),"```"]
    if r["paired_comparisons"]: lines += ["","## Paired comparisons","","```json",json.dumps(r["paired_comparisons"],sort_keys=True,indent=2,allow_nan=False),"```"]
    return "\n".join(lines)+"\n"


def evaluate(*,forecast_manifest:Path,grade_ledger:Path,scope:str,league:str,output_dir:Path,report_date:str,exclude_statuses:set[str],fail_on_unexpected_row:bool,write_canonical_rows:bool,allow_combined_descriptive:bool=False,bootstrap_seed:int=9172026,bootstrap_draws:int=2000):
    if scope not in EVALUATABLE_SCOPES|{"COMBINED_DESCRIPTIVE"}: raise EvaluationError(f"bad scope {scope}")
    if scope=="COMBINED_DESCRIPTIVE" and not allow_combined_descriptive: raise EvaluationError("combined report requires explicit opt-in")
    league=league.upper(); dt.date.fromisoformat(report_date)
    if league!="ALL" and league not in ADAPTERS: raise EvaluationError(f"bad league {league}")
    man,mhash=load_json_readonly(forecast_manifest); man=_manifest(man); grecs,ghash=load_jsonl_readonly(grade_ledger); grades=GradeIndex(grecs)
    gset=sorted({r["grade_record_hash"] for r in grecs})
    if len(gset)!=len(grecs): raise EvaluationError("duplicate grade_record_hash")
    rows=[]; excluded=[]; receipts=[]; ahashes=set(); sources={forecast_manifest.resolve():mhash,grade_ledger.resolve():ghash}
    for e in sorted(man["artifacts"],key=lambda x:(str(x["league"]).upper(),x["path"])):
        lg=str(e["league"]).upper()
        if league!="ALL" and lg!=league: continue
        p=_path(forecast_manifest,e["path"]); payload,h=load_json_readonly(p)
        if h!=e["sha256"]: raise EvaluationError(f"forecast artifact hash mismatch: {p}")
        if h in ahashes: raise EvaluationError(f"duplicate forecast artifact hash: {h}")
        ahashes.add(h); sources[p]=h; a=ADAPTERS[lg].adapt(payload,e,grades,scope,exclude_statuses=exclude_statuses,fail_on_unexpected_row=fail_on_unexpected_row,allow_combined_descriptive=allow_combined_descriptive)
        rows+=a.rows; excluded+=a.excluded; receipts.append({"league":lg,"path":e["path"],"sha256":h,"artifact_schema":e["artifact_schema"],"source_evidence_scope":e.get("source_evidence_scope") or e.get("registration_scope")})
    if not rows: raise EvaluationError("no canonical evaluation rows produced")
    [_validate_row(r) for r in rows]; ids=[(r["league"],r["event_id"],r["model_id"],r["model_arm_id"],r["forecast_output_hash"]) for r in rows]
    if len(set(ids))!=len(ids): raise EvaluationError("duplicate canonical evaluation row")
    rows.sort(key=lambda r:(r["league"],r["event_date_local"],r["event_id"],r["model_id"],r["model_arm_id"])); excluded.sort(key=lambda r:(r.get("league") or "",r.get("event_id") or "",r.get("model_id") or "",r.get("model_arm_id") or ""))
    groups={}
    for r in rows: groups.setdefault((r["league"],r["model_id"],r["model_arm_id"],r["evidence_scope"]),[]).append(r)
    sums=[_summary(groups[k]) for k in sorted(groups)]
    for s in sums:
        x=[e for e in excluded if e.get("league")==s["league"] and e.get("model_id") in (None,s["model_id"])]; s["n_excluded"]=len(x); s["exclusion_reasons"]={reason:sum(e["reason"]==reason for e in x) for reason in sorted({e["reason"] for e in x})}
    pair=_pairs(rows,bootstrap_seed,bootstrap_draws); dset=digest(rows); config={"scope":scope,"league":league,"report_date":report_date,"exclude_statuses":sorted(exclude_statuses),"fail_on_unexpected_row":fail_on_unexpected_row,"write_canonical_rows":write_canonical_rows,"allow_combined_descriptive":allow_combined_descriptive,"bootstrap_seed":bootstrap_seed,"bootstrap_draws":bootstrap_draws}
    core={"schema_version":REPORT_SCHEMA_VERSION,"evaluation_scope":scope,"evidence_scopes_present":sorted({r["evidence_scope"] for r in rows}),"canonical_prospective_eligible":all(r["canonical_prospective_eligible"] for r in rows),"forecast_artifacts_mutated":False,"outcome_grades_mutated":False,"dataset_manifest_sha256":mhash,"canonical_row_dataset_sha256":dset,"forecast_hash_set_sha256":digest(sorted(ahashes)),"grade_hash_set_sha256":digest(gset),"grade_ledger_file_sha256":ghash,"evaluation_config_sha256":digest(config),"report_date":report_date,"pit_validation":"PASS","pit_evidence_source":"FROZEN_ARTIFACT_FIELDS","pit_validation_scope_note":"Structural chronology reasserted; source timestamp truth remains bound to frozen evidence.","binary_brier_convention":BINARY_BRIER_CONVENTION,"binary_brier_alternate":BINARY_BRIER_ALTERNATE,"multiclass_brier_convention":MULTICLASS_BRIER_CONVENTION,"n_canonical_rows":len(rows),"n_excluded_rows":len(excluded),"source_artifacts":receipts,"model_summaries":sums,"paired_comparisons":pair,"promotion_authority":False,"canonical_ledger_write_permitted":False,"market_fields_emitted":False,"ev_action_recommendation_fields_emitted":False}
    rh=digest(core); report={**core,"report_hash":rh,"report_hash_basis":"SHA256_CANONICAL_REPORT_WITHOUT_REPORT_HASH_FIELDS"}; dest=output_dir/scope.lower()/dset/rh
    outs={"evaluation_report.json":_json(report),"evaluation_report.md":_md(report).encode(),"excluded_rows.csv":_csv(excluded,["league","event_id","model_id","model_arm_id","status","reason"]),"validation_failures.csv":_csv([],["source","league","event_id","reason"])}
    if write_canonical_rows: outs["evaluation_rows.jsonl"]=_jsonl(rows)
    for n,b in sorted(outs.items()): _write(dest/n,b)
    for p,h in sources.items():
        if sha256_file(p)!=h: raise EvaluationError(f"source hash changed during evaluation: {p}")
    em={"schema_version":"evaluation_manifest.v1","evaluation_scope":scope,"dataset_sha256":dset,"report_hash":rh,"source_forecast_manifest_sha256":mhash,"source_grade_ledger_sha256":ghash,"source_artifacts":receipts,"output_files":{n:sha256_bytes(b) for n,b in sorted(outs.items())},"source_mutation_check":"PASS"}; eb=_json(em); eh=sha256_bytes(eb); _write(dest/"evaluation_manifest.json",eb); _write(dest/"evaluation_manifest.sha256",f"{eh}  evaluation_manifest.json\n".encode())
    return {"output_dir":str(dest),"report_hash":rh,"dataset_sha256":dset,"evaluation_manifest_sha256":eh,"report":report,"rows":rows,"excluded":excluded}


def parser():
    p=argparse.ArgumentParser(); p.add_argument("--forecast-manifest",type=Path,required=True); p.add_argument("--grade-ledger",type=Path,required=True); p.add_argument("--scope",choices=["LOCAL_DIAGNOSTIC","REMOTE_DURABLE_PROSPECTIVE","COMBINED_DESCRIPTIVE"],required=True); p.add_argument("--league",choices=["mlb","cfb","mls","all"],required=True); p.add_argument("--output-dir",type=Path,required=True); p.add_argument("--report-date",required=True); p.add_argument("--exclude-status",nargs="*",default=[]); p.add_argument("--fail-on-unexpected-row",action="store_true"); p.add_argument("--write-canonical-rows",action="store_true"); p.add_argument("--allow-combined-descriptive",action="store_true"); p.add_argument("--bootstrap-seed",type=int,default=9172026); p.add_argument("--bootstrap-draws",type=int,default=2000); return p


def main(argv=None):
    a=parser().parse_args(argv)
    try: r=evaluate(forecast_manifest=a.forecast_manifest,grade_ledger=a.grade_ledger,scope=a.scope,league=a.league,output_dir=a.output_dir,report_date=a.report_date,exclude_statuses=set(a.exclude_status),fail_on_unexpected_row=a.fail_on_unexpected_row,write_canonical_rows=a.write_canonical_rows,allow_combined_descriptive=a.allow_combined_descriptive,bootstrap_seed=a.bootstrap_seed,bootstrap_draws=a.bootstrap_draws)
    except EvaluationError as e: print(f"EVALUATION_FAILED: {e}",file=sys.stderr); return 2
    print(json.dumps({"status":"PASS","output_dir":r["output_dir"],"dataset_sha256":r["dataset_sha256"],"report_hash":r["report_hash"],"evaluation_manifest_sha256":r["evaluation_manifest_sha256"]},sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())
