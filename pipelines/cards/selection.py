"""Versioned, evidence-bound defaults. Selection never grants release authority."""
import copy,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
CATALOG=ROOT/'data/model_selection/defaults_v1.json'

class SelectionError(ValueError):pass

def select(league,target='winner',*,week=None,division=None,catalog=None,root=ROOT):
    catalog=json.loads(CATALOG.read_text()) if catalog is None else catalog
    league=league.lower();key=league+':'+target
    if league=='cfb':
        if division!='FBS_VS_FBS':raise SelectionError('CFB_SUBDIVISION_SCOPE_REQUIRED_OR_UNSUPPORTED')
        if week is None or int(week)<1:raise SelectionError('CFB_WEEK_SCOPE_REQUIRED')
        if int(week)==1:key+=':week1'
    if key not in catalog['profiles']:raise SelectionError('NO_TESTED_DEFAULT_FOR_PRODUCT:'+key)
    result=copy.deepcopy(catalog['profiles'][key])
    if not result['default_model_id']:raise SelectionError('NO_VERIFIED_TESTED_DEFAULT:'+key)
    if result['selection_status'] in {'FAILED','UNSCREENED','QUARANTINED'}:raise SelectionError('INELIGIBLE_DEFAULT:'+key)
    if not result['evidence']:raise SelectionError('DEFAULT_EVIDENCE_REQUIRED')
    for e in result['evidence']:
        p=Path(root)/e['path']
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=e['sha256']:
            raise SelectionError('SELECTION_EVIDENCE_DRIFT:'+e['path'])
    result.update(league=league,target=target,profile=key,policy_sha256=hashlib.sha256(json.dumps(catalog,sort_keys=True).encode()).hexdigest(),official_release=False,action_authority=False)
    return result

def require_default(league,model_id,**kwargs):
    result=select(league,**kwargs)
    if model_id!=result['default_model_id']:raise SelectionError('CHALLENGER_CANNOT_HEADLINE:'+str(model_id))
    return result

def inventory():
    c=json.loads(CATALOG.read_text());out={}
    for key,p in c['profiles'].items():
        league,target,*scope=key.split(':')
        try:out[key]=select(league,target,week=1 if scope else 2,division='FBS_VS_FBS')
        except SelectionError as e:out[key]={**p,'blocked_reason':str(e)}
    return {'schema':c['schema'],'profiles':out,'action_authority':False}
