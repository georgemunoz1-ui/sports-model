"""Serving-time missingness diagnostics for the shared research card.

Read the actual adapter snapshot after inference. Diagnostic perturbations never
enter the parent prediction, numerical identity, seed, selector or draws.
"""
import hashlib
import json
import math
from pathlib import Path
from functools import lru_cache

from .missingness import factorial_attribution, seal_audit, verify_audit

INITIAL = {"nba", "nhl", "mls"}
LINEAR = INITIAL | {"cfb"}
@lru_cache(maxsize=1)
def shared_contracts():
    raw=(Path(__file__).resolve().parents[2]/"data/model_selection/missingness/shared_contracts.json").read_bytes()
    return hashlib.sha256(raw).hexdigest(), json.loads(raw)["league"]


def binding(row, league, cutoff):
    if row["forecast_status"] == "FORECAST_GENERATED":
        products = ["winner"]
        if league == "mls":
            products = ["regulation_1x2", "home_goals", "away_goals"]
        for field, product in (("projected_margin", "margin"), ("projected_total", "total"),
                               ("projected_home_runs", "home_runs"), ("projected_away_runs", "away_runs")):
            if type(row.get(field)) in (float, int):
                products.append(product)
    else:
        products = ["coverage"]
    return dict(league=league, event_id=row["event_id"], model_id=row.get("model_id") or "UNRESOLVED",
                products=products, forecast={"cutoff_utc":cutoff,
                    "row":{k:v for k,v in row.items() if k!="missingness_audit"}})


def load_parent(path, pin, league, cutoff):
    """Compare only an explicitly pinned, earlier, audited edition."""
    from models.nfl.contextual.recovered_inference import utc
    if path is None and pin is None:
        return {}
    if not path or not pin:
        raise ValueError("PREVIOUS_CARD_AND_PIN_REQUIRED")
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError("PREVIOUS_CARD_HASH_MISMATCH")
    card = json.loads(raw)
    if card["league"].lower() != league or utc(card["as_of_utc"]) > utc(cutoff) or utc(card["generated_at_utc"]) > utc(cutoff):
        raise ValueError("PREVIOUS_CARD_SCOPE_OR_CHRONOLOGY")
    rows = {}
    for row in card["forecasts"]:
        eid = row["event_id"]
        if eid in rows:
            raise ValueError("DUPLICATE_PREVIOUS_EVENT")
        valid = verify_audit(row.get("missingness_audit"), **binding(row,league,card["as_of_utc"]))
        rows[eid] = row if valid else {"refusal_reason":"PREVIOUS_RECEIPT_UNVERIFIED"}
    return rows


def training_support(feature_names, rows):
    """Count actual fit-vector support by season; only explicit masks/NaNs are identifiable here."""
    counts={}
    for season, values in rows:
        bucket=counts.setdefault(str(season),{"rows":0,"missing":dict.fromkeys(feature_names,0),
                                              "cold_indicators":{k:0 for k in feature_names if k.endswith("_cold")}})
        if len(values)!=len(feature_names):
            raise ValueError("TRAINING_SUPPORT_VECTOR_LENGTH")
        bucket["rows"]+=1
        for name,value in zip(feature_names,values):
            if value is None or math.isnan(float(value)):
                bucket["missing"][name]+=1
            elif name in bucket["cold_indicators"] and value==1:
                bucket["cold_indicators"][name]+=1
    return {"basis":"DEPLOYMENT_FIT_ROWS_BEFORE_IMPUTATION",
            "limitation":"Upstream capture failures already replaced by numeric defaults cannot be recovered from normalized fit vectors.",
            "by_season":counts}


def check_source_inputs(package):
    """An explicit failed acquisition or duplicate consumed result cannot masquerade as a prior."""
    if not package:
        return
    ids = package.get("consumed_game_ids", [])
    if len(ids) != len(set(map(str,ids))):
        raise ValueError("DUPLICATE_CONSUMED_RESULT")
    for record in package.get("source_fetches", []):
        status = record.get("status")
        if record.get("error") or record.get("ok") is False or (status is not None and
                str(status).upper() not in {"OK", "SUCCESS", "CAPTURED", "VERIFIED", "COMPLETED"}
                and not (str(status).isdigit() and 200 <= int(status) < 300)):
            raise ValueError("SOURCE_ACQUISITION_FAILED")
    if package.get("league") == "wnba":
        keys = [(r["season"],r["team"]) for r in package["team_state"]]
        if len(keys) != len(set(keys)):
            raise ValueError("DUPLICATE_TEAM_STATE")


def _feature_status(league, name, value, package, event):
    if value is None:
        return "IMPUTED_TRAINING_MEDIAN"
    if league in INITIAL:
        side = name.split("_", 1)[0]
        if side in ("home","away"):
            state = package["team_state"].get(event[side+"_id"], {})
            if name.endswith("_cold"):
                return "HISTORY_SUPPORT_INDICATOR"
            if name.endswith("_rest"):
                return "CAPPED_ELIGIBLE_HISTORY_REST" if state.get("last") else "IMPUTED_14_DAY_REST"
            if not state.get("n"):
                return "LEAGUE_PRIOR"
            return "SHRUNK_TOWARD_LEAGUE_PRIOR"
        if name == "neutral":
            return "NORMALIZED_VENUE_FLAG_RAW_MISSINGNESS_UNRESOLVED"
    if league == "cfb" and name == "elo_diff_with_home_advantage":
        if any(event[s+"_team"] not in package["team_state"]["elo"] for s in ("home","away")):
            return "ELO_1500_PRIOR"
    if name in ("neutral_site","conference_game"):
        return "NORMALIZED_SCHEDULE_FLAG"
    return "OBSERVED_TRANSFORMED"


def _head_outputs(league,row):
    diag = row.get("diagnostics") or {}
    if league == "mls":
        return {"home_goals":row.get("projected_home_points"), "away_goals":row.get("projected_away_points")}
    return {"winner":diag.get("home_win"),"margin":diag.get("home_margin"),"total":diag.get("total")}


def _linear_trace(league, row, event, package):
    from models.current.linear import predict
    features = row["model_input_snapshot"]
    if league in INITIAL:
        from models.current.baseline import FEATURES
        names=package.get("feature_names",FEATURES)
        if list(names)!=FEATURES:
            raise ValueError("INITIAL_FEATURE_ORDER_MISMATCH")
    else:
        names=package["feature_names"]
    if len(set(names)) != len(names) or set(names) != set(features):
        raise ValueError("FEATURE_SCHEMA_MISMATCH")
    values = [features[n] for n in names]
    actual = _head_outputs(league,row)
    heads = {}
    states = {key:_feature_status(league,key,features[key],package,event) for key in names}
    for target, params in package["fitted_model"].items():
        center = predict(params, values)
        if target not in actual or actual[target] is None or not math.isclose(center,actual[target],rel_tol=1e-11,abs_tol=1e-12):
            raise ValueError("FITTED_HEAD_REPLAY_MISMATCH:"+target)
        terms = {}
        for i, name in enumerate(names):
            observed = values[i]
            used = params["impute"][i] if observed is None else observed
            # Probe numeric imputation; for binary support flags, also toggle the actual indicator.
            probe = list(values)
            probe[i] = 1.-float(observed) if states[name]=="HISTORY_SUPPORT_INDICATOR" else None
            terms[name] = {"value":observed,"state":states[name],"imputation_value":params["impute"][i],
                           "diagnostic_delta":predict(params,probe)-center,
                           "probe":"toggle" if states[name]=="HISTORY_SUPPORT_INDICATOR" else "replace_with_fitted_median",
                           "linear_contribution":(used-params["mean"][i])/params["scale"][i]*params["coefficient"][i]}
        heads[target] = {"link":params["kind"], "fitted_value":center, "imputation":"FITTED_TRAINING_MEDIAN", "intercept":params["intercept"],
                         "features":terms}
    return heads


def _refresh(previous, row, heads, fitted_hash, fitted_heads):
    from models.current.linear import predict
    if not previous:
        return {"status":"NO_PAIRED_PARENT"}
    if "missingness_audit" not in previous:
        return {"status":"PREVIOUS_RECEIPT_UNVERIFIED"}
    if any(row.get(k)!=previous.get(k) for k in ("start_time_utc","away_team","home_team")):
        return {"status":"FIXTURE_AMENDMENT_REVIEW_REQUIRED"}
    old = previous["missingness_audit"]["details"]
    if previous.get("model_id") != row.get("model_id") or old.get("fitted_parameters_sha256") != fitted_hash:
        return {"status":"MODEL_OR_CONFIGURATION_CHANGED","attribution":"UNRESOLVED"}
    value = {"status":"PAIRED_DIAGNOSTIC", "method":"EXACT_ADDITIVE_ON_LINK_SCALE",
             "prior_receipt_sha256":previous["missingness_audit"]["receipt_sha256"],
             "prior_forecast_sha256":previous["missingness_audit"]["forecast_sha256"],
             "model_version_change":"SAME_FITTED_PARAMETERS","interactions":"Nonlinear output link is not allocated to individual inputs",
             "side_before":previous.get("model_winner"),"side_after":row.get("model_winner"),
             "simulation":"FINITE_DRAWS_REPORTED_SEPARATELY",
             "sim_p_before":previous.get("sim_p"),"sim_p_after":row.get("sim_p"),"heads":{}}
    if not heads or heads.keys()!=old.get("linear_heads",{}).keys():
        return {"status":"NO_COMPARABLE_FITTED_HEAD_TRACE","attribution":"UNRESOLVED"}
    ordinary={"OBSERVED_TRANSFORMED","NORMALIZED_SCHEDULE_FLAG"}
    for name, head in heads.items():
        prev=old["linear_heads"][name]
        if prev["features"].keys()!=head["features"].keys() or head["link"]!=prev["link"]:
            return {"status":"FEATURE_SCHEMA_CHANGED","attribution":"UNRESOLVED"}
        changes={"substantive":0., "missingness_indicator":0., "mixed_imputation_or_unknown":0.}
        sporting_only, reporting_only = [], []
        inseparable = False
        for k, f in head["features"].items():
            prior=prev["features"][k]
            statuses={f["state"],prior["state"]}
            if statuses=={"HISTORY_SUPPORT_INDICATOR"}:
                group="missingness_indicator"
            elif statuses<=ordinary:
                group="substantive"
            else:
                group="mixed_imputation_or_unknown"
            changes[group]+=f["linear_contribution"]-prior["linear_contribution"]
            if group == "mixed_imputation_or_unknown" and prior["value"] != f["value"]:
                inseparable = True
            sporting_only.append(f["value"] if group=="substantive" else prior["value"])
            reporting_only.append(f["value"] if group=="missingness_indicator" else prior["value"])
        value["heads"][name]={"fitted_before":prev["fitted_value"],"fitted_after":head["fitted_value"],
                              "scale":{"linear":"native","logistic":"home_log_odds","poisson":"log_goals"}[head["link"]],
                              "native_head_interaction": factorial_attribution(
                                  original=prev["fitted_value"], refreshed=head["fitted_value"],
                                  sporting_only=None if inseparable else predict(fitted_heads[name],sporting_only),
                                  reporting_only=None if inseparable else predict(fitted_heads[name],reporting_only)),
                              **changes}
    return value


def _wnba_trace(package, event, row):
    """Run the same fitted three heads with and without each team's recorded history."""
    import numpy as np
    from harness import wnba_model_v1 as model
    fit={k:np.asarray(v,dtype=float) for k,v in package["fitted_model"].items()}
    teams=model.TeamState()
    teams.s={(int(r["season"]),r["team"]):r["values"] for r in package["team_state"]}
    matchup=[(event["away_team"],event["home_team"],event["start_time_utc"])]
    def serve(state):
        return model.predict_slate(fit,state,package["league_state"],matchup,event["season"])[0]
    replay=serve(teams)
    for target, observed in (("p_home","home_win"),("margin_home","home_margin"),("total","total")):
        if replay[target]!=row["diagnostics"][observed]:
            raise ValueError("WNBA_HEAD_REPLAY_MISMATCH:"+target)
    withheld={}
    for side in ("home","away"):
        probe=model.TeamState()
        probe.s=dict(teams.s)
        del probe.s[(event["season"],event[side+"_team"])]
        denial=serve(probe)
        if "p_home" in denial:
            raise ValueError("WNBA_MISSING_HISTORY_ACCEPTED")
        withheld[side]=denial["status"]
    return {"current":{k:replay[k] for k in ("p_home","margin_home","total","games_used")},
            "withhold_team_history":withheld,"source":"eligible same-season boxes plus league state",
            "units":{"p_home":"probability","margin_home":"points","total":"points"},
            "missing_policy":"Refusal below minimum games or for nonpositive possessions"}


def _mlb_trace(row):
    """Separate the winner sampler's rate parameters from the fitted challenger."""
    from harness import run_v13_historical as v13
    snap=row["model_input_snapshot"]
    form={s:snap[s+"_form"] for s in ("away","home")}
    pitchers={s:snap["sp_"+s] for s in ("away","home")}
    beta=v13.load_candidate_beta()
    def params(starters):
        r=[form[s][k] for s in ("away","home") for k in ("rf","ra")]
        era=[starters[s][k] for s in ("away","home") for k in ("era","gs")]
        result={"d_logistic_2f_home_p":v13.candidate_p(*r,*era,beta)}
        for s in ("away","home"):
            sp=starters[s]
            result[s+"_runs_scale"]=v13.rs(sp['era'],sp['gs'],sp['k'],sp['bb'])
            result[s+"_balls_in_play_factor"]=v13.bipf(sp['k'],sp['bb'])
        return result
    observed=params(pitchers)
    if not math.isclose(observed["d_logistic_2f_home_p"],row["diagnostics"]["analytic_home_win"],abs_tol=1e-10):
        raise ValueError("MLB_CHALLENGER_REPLAY_MISMATCH")
    probes={}
    for side in pitchers:
        for feature in ("era","gs","k","bb"):
            probe={**pitchers,side:{**pitchers[side],feature:None}}
            probes[side+"_"+feature]={k:v-observed[k] for k,v in params(probe).items()}
    return {"treatment_by_starter":{s:sp.get("treatment") for s,sp in pitchers.items()},
            "current":observed,"withheld_input_deltas":probes,
            "law_scope":"PARTIAL_V13_STARTER_RATE_PARAMETERS; MC_WINNER_OMITTED_FROM_FITTED_DELTAS",
            "d_logistic_2f_scope":"CHALLENGER_ONLY"}


def attach_shared_audit(league,row,event,context,cutoff,previous=None):
    from models.nfl.contextual.recovered_inference import digest
    league=league.lower()
    package=context.get("package") or {}
    key=binding(row,league,cutoff)
    details={"contract_review":"PENDING","historical_support":"UNMEASURED",
             "limits":"NO_REVIEWED_PRODUCT_LIMIT","source_freshness":"PACKAGE_SOURCE_CUTOFF_AND_TTL",
             "units":{"nhl":"goals","mls":"goals","mlb":"runs"}.get(league,"points"),
             "refresh":{"status":"NO_PAIRED_PARENT" if previous is None else "ATTRIBUTION_UNRESOLVED"}}
    registry_hash, rules=shared_contracts()
    details["contract_registry_sha256"]=registry_hash
    if league in rules:
        details["registered_scope"]=rules[league]
    if row["forecast_status"]!="FORECAST_GENERATED":
        details.update(status="REFUSED",reason=row["refusal_reason"],
                       current_state=("ACQUISITION_FAILURE" if "ACQUISITION_FAILED" in row["refusal_reason"]
                                      else "UNRESOLVED_IDENTITY_OR_COVERAGE"))
    elif league in LINEAR and package.get("schema")=="sports.current_research_package.v1":
        try:
            heads=_linear_trace(league,row,event,package)
            fit_hash=digest({"fitted_model":package["fitted_model"],"parameters":package.get("parameters"),
                             "prior":package.get("prior"),"code_pins":package.get("code_pins")})
            details.update(status="FITTED_HEADS_REPLAYED",linear_heads=heads,fitted_parameters_sha256=fit_hash,
                           historical_support=package.get("missingness_training_support", "UNMEASURED"),
                           refresh=_refresh(previous,row,heads,fit_hash,package["fitted_model"]),
                           probe_scope="ONE_FEATURE_AT_A_TIME_DIAGNOSTIC; UNITS_OF_FITTED_HEAD; NOT_A_SPORTING_COUNTERFACTUAL")
        except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
            # Keep valid research head visible without granting missingness clearance.
            details.update(status="TRACE_BLOCKED",reason=str(exc))
    elif league == "nfl" and (row.get("diagnostics") or {}).get("missingness_audit"):
        native=row["diagnostics"]["missingness_audit"]
        details.update(status="NATIVE_NFL_RECEIPT",native=native,
                       refresh=native.get("details",{}).get("refresh",details["refresh"]))
    elif league == "wnba" and package.get("schema")=="sports.current_research_package.v1":
        snap=row.get("model_input_snapshot") or {}
        details.update(status="SCOPED_INPUTS_ONLY",inputs={k:snap.get(k) for k in ("home","away","league_state")},
                       rules="Insufficient games or invalid possessions refuse. Team net rating shrinks with games played. Rest is ET-date based and capped at five days. Rebounds use a one-miss denominator floor.")
    elif league == "mlb" and row.get("model_input_snapshot"):
        snap=row["model_input_snapshot"]
        details.update(status="SCOPED_INPUTS_ONLY",starter_values={s:{k:(snap.get("sp_"+s) or {}).get(k) for k in ("era","gs","k","bb","treatment")} for s in ("home","away")},
                       rules="Missing ERA/K/BB use league priors and missing starts use zero. Missing form and park factor use league/neutral defaults. V13 uses simulation; d_logistic_2f is separate.",
                       challenger=(row.get("diagnostics") or {}).get("challengers"))
    else:
        details.update(status="UNREGISTERED_OR_UNSUPPORTED",reason="A numerical missingness trace is unavailable for this model and route.")
    if details["status"]=="SCOPED_INPUTS_ONLY":
        try:
            if league=="wnba":
                details["sensitivity"]=_wnba_trace(package,event,row)
                details["status"]="FITTED_HEADS_AND_REFUSALS_REPLAYED"
            else:
                details["sensitivity"]=_mlb_trace(row)
                details["status"]="PARTIAL_LAW_AND_CHALLENGER_REPLAYED"
        except (ValueError,KeyError,TypeError,ArithmeticError, OSError) as exc:
            details.update(status="TRACE_BLOCKED",reason=str(exc))
    row["missingness_audit"]=seal_audit(**key,details=details)
    return row
