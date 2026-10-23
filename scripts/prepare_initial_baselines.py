#!/usr/bin/env python3
"""Preregistered train/validation/later-period audit, then current research fit."""
import argparse,collections,datetime as dt,hashlib,json,sys
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression,Ridge,PoissonRegressor
from models.current.common import save
from models.current.linear import pack,predict
from models.current.baseline import IDS,FEATURES,feature,update,probabilities
from models.nfl.contextual.recovered_inference import digest,utc
from scripts.verify_nfl_weekly_sources import manifest


def parse(e,league,historical=False):
    c=e['competitions'][0];season=e['season'];typ=e.get('seasonType',{})
    if historical:
        regular=typ.get('name')=='Regular Season'
    else:regular=season.get('slug')=='regular-season'
    if not regular:return None
    if league=='nba' and c.get('type',{}).get('id')=='39':return None  # Cup championship is not a regular-season game.
    sides={x['homeAway']:x for x in c['competitors']}
    if set(sides)!={'home','away'}:raise ValueError('TEAM_SIDE_IDENTITY')
    status=c.get('status',e.get('status'))['type'];final=bool(status['completed'])
    if final and status['state']!='post':raise ValueError('FINAL_STATUS_CONFLICT')
    r={'event_id':league.upper()+':'+str(e['id']),'start_time_utc':utc(e['date']).isoformat(),'season':int(season['year']),'neutral_site':bool(c.get('neutralSite',False)),'final':final}
    for side,t in sides.items():
        r[side+'_id']=str(t['team']['id']);r[side+'_team']=t['team']['displayName']
        if final:
            val=t['score'];val=val['value'] if isinstance(val,dict) else val
            f=float(val)
            if not np.isfinite(f) or f<0 or f!=int(f):raise ValueError('INVALID_FINAL_SCORE')
            r[side+'_score']=int(f)
    if r['home_id']==r['away_id']:raise ValueError('SELF_MATCH')
    if final and league!='mls' and r['home_score']==r['away_score']:raise ValueError('BINARY_TIED_FINAL')
    r['slate_date']=utc(r['start_time_utc']).astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
    return r


def load_season_scope(path):
    if path is None:return None
    from scripts.nhl_history_applicability import load_scope
    return load_scope(path)


def histories(root,league,season_scope=None,cutoff=None,nba_acquisition_scope=None):
    report=json.loads((root/'report.json').read_text());games={};copies=collections.Counter();receipts=[]
    if season_scope is not None and nba_acquisition_scope is not None:raise ValueError('ONE_ACQUISITION_SCOPE_REQUIRED')
    active_scope=season_scope or nba_acquisition_scope
    seasons=range(2021,2027) if active_scope is None else range(active_scope['first_provider_season'],active_scope['last_provider_season']+1)
    if season_scope is not None and season_scope['league']!=league:raise ValueError('SEASON_SCOPE_LEAGUE')
    requested_seasons=collections.Counter()
    sources=report['sources']
    if nba_acquisition_scope is not None:
        if league!='nba' or cutoff is None:raise ValueError('NBA_SCOPE_AND_CUTOFF_REQUIRED')
        from scripts.nba_history_scope import history_sources
        sources=history_sources(root,report,nba_acquisition_scope,cutoff)
    if season_scope is not None:
        from scripts.nhl_history_applicability import history_sources
        sources=history_sources(root,report,season_scope,cutoff)
    for rec in sources:
        if rec['league']!=league or rec['kind']!='team_season_schedule':continue
        if rec['status']!='CAPTURED':raise ValueError('HISTORICAL_SOURCE_FAILURE')
        receipts.append(rec);j=json.loads((root/rec['raw_path']).read_text())
        from urllib.parse import urlparse,parse_qs
        requested=int(parse_qs(urlparse(rec['url']).query)['season'][0])
        requested_seasons[requested]+=1
        if requested not in seasons:raise ValueError('REQUESTED_SEASON_OUT_OF_SCOPE')
        if active_scope is not None:
            if hashlib.sha256((root/rec['raw_path']).read_bytes()).hexdigest()!=rec['raw_sha256']:raise ValueError('SOURCE_RAW_DIGEST_MISMATCH')
            if str(parse_qs(urlparse(rec['url']).query).get('seasontype',[''])[0])!='2':raise ValueError('REGULAR_SEASON_SOURCE_REQUIRED')
        for e in j.get('events',[]):
            r=parse(e,league,True)
            if not r or not r['final']:continue
            if r['season'] not in seasons:raise ValueError('SEASON_OUT_OF_SCOPE')
            from urllib.parse import urlparse,parse_qs
            if int(parse_qs(urlparse(rec['url']).query)['season'][0])!=r['season']:raise ValueError('REQUESTED_SEASON_MISMATCH')
            key=r['event_id'];copies[key]+=1
            if key in games and games[key]!=r:raise ValueError('PROVIDER_ID_REVISION:'+key)
            games[key]=r
    if len(receipts)<180:raise ValueError('TEAM_SEASON_SOURCE_COVERAGE')
    if active_scope is not None and set(requested_seasons)!=set(seasons):raise ValueError('SEASON_SOURCE_COVERAGE')
    return sorted(games.values(),key=lambda r:(r['start_time_utc'],r['event_id'])),receipts,dict(collections.Counter(copies.values()))


def causal_rows(games,prior,cutoff):
    state={};rows=[];pending=[];used=[]
    for day,group in __import__('itertools').groupby(games,key=lambda r:r['start_time_utc'][:10]):
        boundary=utc(day+'T00:00:00+00:00')-dt.timedelta(days=1)
        ready=[r for r in pending if utc(r['start_time_utc'])<boundary]
        pending=[r for r in pending if utc(r['start_time_utc'])>=boundary]
        for r in ready:update(state,r);used.append(r['event_id'])
        group=list(group)
        for r in group:rows.append((r,list(feature(state,r,prior).values())))
        pending.extend(group)
    boundary=utc(cutoff).replace(hour=0,minute=0,second=0,microsecond=0)-dt.timedelta(days=1)
    for r in pending:
        if utc(r['start_time_utc'])<boundary:update(state,r);used.append(r['event_id'])
    return rows,state,used


def operational_rest_training_example(state,event,prior,records,*,cutoff_utc,coverage=(),max_capture_age_hours=6):
    """Build one separately identified training vector from a pre-event snapshot.

    This candidate adapter is not selected by causal_rows/prepare's legacy path.
    It consumes no current-event target and reads no state.last/rest proxy. Each
    training example needs its own historically available all-game capture; a
    present-day final snapshot is not silently reused at an earlier cutoff.
    A5 hand-computed vectors test this adapter independently of serving parity.
    """
    from models.current.freshness import candidate_form_features, operational_rest, REST_SEMANTICS
    form=candidate_form_features(state,event,prior)
    receipt=operational_rest(event,records,cutoff_utc=cutoff_utc,coverage=coverage,max_capture_age_hours=max_capture_age_hours)
    ready=all(row['status']=='KNOWN' for row in receipt['per_side'].values())
    if ready:
        values=dict(form)
        values['home_rest']=receipt['per_side']['home']['candidate_feature_value']
        values['away_rest']=receipt['per_side']['away']['candidate_feature_value']
        features={name:values[name] for name in FEATURES}
    else:features=None
    return {'adapter_id':'initial_causal_score.operational_rest.training.v1',
            'feature_semantics_id':REST_SEMANTICS,'candidate_ready':ready,'features':features,
            'rest_receipt':receipt,'proxy_columns_used':[],'action_authority':False}


def fit(rows,league):
    X=np.array([x for _,x in rows]);hg=np.array([r['home_score'] for r,_ in rows]);ag=np.array([r['away_score'] for r,_ in rows]);heads={}
    specs= [('home_goals',hg,PoissonRegressor(alpha=1,max_iter=1000),'poisson'),('away_goals',ag,PoissonRegressor(alpha=1,max_iter=1000),'poisson')] if league=='mls' else [('winner',(hg>ag).astype(int),LogisticRegression(C=1,max_iter=2000),'logistic'),('margin',hg-ag,Ridge(alpha=1),'linear'),('total',hg+ag,Ridge(alpha=1),'linear')]
    for name,y,est,kind in specs:heads[name]=pack(make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),est).fit(X,y),kind)
    return heads


def evaluate(rows,fitted,league,base):
    if not rows:raise ValueError('EMPTY_TEMPORAL_SPLIT')
    ps=np.array([probabilities(fitted,x,league) for _,x in rows]);labels=np.array([(0 if r['home_score']<r['away_score'] else 1 if r['home_score']==r['away_score'] else 2) if league=='mls' else int(r['home_score']>r['away_score']) for r,_ in rows]);ys=np.eye(len(base))[labels]
    if not np.isfinite(ps).all() or not np.allclose(ps.sum(axis=1),1):raise ValueError('INVALID_PROBABILITY_VECTOR')
    brier=((ps-ys)**2).sum(1)/(1 if league=='mls' else 2);bb=((np.array(base)-ys)**2).sum(1)/(1 if league=='mls' else 2)
    ll=-np.log(np.clip(ps[np.arange(len(rows)),labels],1e-15,1));bl=-np.log(np.array(base)[labels]);groups=collections.defaultdict(list)
    for i,(r,_) in enumerate(rows):groups[utc(r['start_time_utc']).strftime('%G-%V')].append(i)
    blocks=[np.array(v) for v in groups.values()];rng=np.random.default_rng(7);boot=[]
    for _ in range(1000):
        ix=np.concatenate([blocks[i] for i in rng.integers(0,len(blocks),len(blocks))]);boot.append([float((brier-bb)[ix].mean()),float((ll-bl)[ix].mean())])
    reliability=[]
    for cat in range(len(base)):
        for low in np.arange(0,1,.1):
            mask=(ps[:,cat]>=low)&(ps[:,cat]<(low+.1+ (1e-12 if low>.89 else 0)))
            if mask.any():reliability.append({'category':cat,'lower':round(float(low),1),'n':int(mask.sum()),'mean_p':float(ps[mask,cat].mean()),'frequency':float(ys[mask,cat].mean())})
    result={'n':len(rows),'brier':float(brier.mean()),'baseline_brier':float(bb.mean()),'log_loss':float(ll.mean()),'baseline_log_loss':float(bl.mean()),'paired_week_bootstrap_95ci_brier_delta':np.quantile(np.array(boot)[:,0],[.025,.975]).tolist(),'paired_week_bootstrap_95ci_log_loss_delta':np.quantile(np.array(boot)[:,1],[.025,.975]).tolist(),'reliability':reliability,'prediction_sha256':digest(ps.tolist())}
    if league!='mls':
        result['margin_mae']=float(np.mean([abs(predict(fitted['margin'],x)-(r['home_score']-r['away_score'])) for r,x in rows]));result['total_mae']=float(np.mean([abs(predict(fitted['total'],x)-(r['home_score']+r['away_score'])) for r,x in rows]))
    return result


def verify_current_sources(root,league,report,events,cutoff=None):
    """Bind current events, timestamps and date coverage to captured bytes."""
    from scripts.nhl_history_applicability import receipt,SCOPE_SHA256,BASE
    from urllib.parse import urlparse,parse_qs
    if report.get('season_scope_sha256')!=SCOPE_SHA256 or report.get('action_authority') is not False:raise ValueError('CURRENT_SCOPE_BINDING')
    if report.get('pending_requests',0)!=0:raise ValueError('CURRENT_SOURCE_PENDING')
    captured={};receipts={};dates=set();urls=set()
    for rec in report['sources']:
        if rec.get('league')!=league or rec.get('kind')!='schedule':raise ValueError('CURRENT_SOURCE_KIND')
        url=urlparse(rec['url']);query=parse_qs(url.query)
        if url.scheme+'://'+url.netloc+url.path!=BASE+'/scoreboard' or rec['url'] in urls:raise ValueError('CURRENT_SOURCE_URL')
        urls.add(rec['url']);dates.add(query.get('dates',[''])[0])
        data=receipt(root,rec,cutoff);rows=data.get('events',[])
        if len({str(e['id']) for e in rows})!=len(rows):raise ValueError('DUPLICATE_CURRENT_EVENT')
        captured[rec['raw_sha256']]={str(e['id']):e for e in rows};receipts[rec['raw_sha256']]=rec
    if not captured:raise ValueError('CURRENT_SCHEDULE_RECEIPT_REQUIRED')
    for eid,rec in events.items():
        original=captured.get(rec['source_sha256'],{}).get(str(eid))
        if original is None or original!=rec['event']:raise ValueError('CURRENT_EVENT_SOURCE_BINDING:'+str(eid))
        if rec.get('retrieved_at_utc')!=receipts[rec['source_sha256']]['retrieved_at_utc']:raise ValueError('CURRENT_EVENT_RECEIPT_BINDING')
    expected=set().union(*(set(v) for v in captured.values()))
    if set(map(str,events))!=expected:raise ValueError('CURRENT_SOURCE_EVENT_COVERAGE')
    if not report.get('covered_dates') or report.get('timezone')!='America/Los_Angeles':raise ValueError('SOURCE_BOUND_COVERAGE_REQUIRED')
    for day in report['covered_dates']:
        date=dt.date.fromisoformat(day)
        if any((date+dt.timedelta(days=offset)).strftime('%Y%m%d') not in dates for offset in (-1,0,1)):raise ValueError('CURRENT_SLATE_TIMEZONE_COVERAGE')


def preparation_cutoff(as_of_utc=None):
    wall=dt.datetime.now(dt.timezone.utc)
    cutoff=utc(as_of_utc) if as_of_utc else wall
    if cutoff>wall:raise ValueError('FUTURE_PACKAGE_CUTOFF')
    return cutoff


def prepare(history,current,output,*,leagues=None,season_scope_path=None,as_of_utc=None,nba_acquisition_scope_path=None):
    season_scope=load_season_scope(season_scope_path)
    selected=list(IDS) if leagues is None else list(leagues)
    if not selected or any(l not in IDS for l in selected):raise ValueError('INITIAL_BASELINE_LEAGUE')
    if season_scope is not None and selected!=[season_scope['league']]:raise ValueError('SEASON_SCOPE_EXPLICIT_LEAGUE_REQUIRED')
    nba_scope=None
    if nba_acquisition_scope_path is not None:
        if season_scope is not None or selected!=['nba']:raise ValueError('NBA_ACQUISITION_EXPLICIT_LEAGUE_REQUIRED')
        from scripts.nba_history_scope import load_scope as load_nba_scope
        nba_scope=load_nba_scope(nba_acquisition_scope_path)
    manifest(history,'manifest.json');manifest(current,'manifest.json');now=preparation_cutoff(as_of_utc);stamp=now.isoformat();current_events=json.loads((current/'events.json').read_text());reports={}
    cr=json.loads((current/'report.json').read_text())
    for league in selected:
        if season_scope is not None:verify_current_sources(current,league,cr,current_events[league],now)
        if nba_scope is not None:
            from scripts.nba_history_scope import current_season,verify_current_events
            observed_season,_=current_season(current,now)
            if observed_season!=nba_scope['last_provider_season']:raise ValueError('NBA_CURRENT_HISTORY_SEASON_GAP')
            verify_current_events(current,current_events[league],now)
        games,receipts,copies=histories(history,league,season_scope,now,nba_scope)
        if season_scope is not None or nba_scope is not None:
            for source in receipts+[r for r in cr['sources'] if r['league']==league and r['kind']=='schedule']:
                age=(now-utc(source['retrieved_at_utc'])).total_seconds()
                if not 0<=age<=6*3600:raise ValueError('SOURCE_NOT_AVAILABLE_AND_CURRENT_AT_CUTOFF')
        if any(utc(r['start_time_utc'])>=now for r in games):raise ValueError('FUTURE_HISTORICAL_FINAL')
        train=[r for r in games if r['season']<=2024];prior=float(np.mean([r[s+'_score'] for r in train for s in ('home','away')]))
        rows,state,used=causal_rows(games,prior,stamp);tr=[r for r in rows if r[0]['season']<=2024];fitted=fit(tr,league)
        labels=[(0 if r['home_score']<r['away_score'] else 1 if r['home_score']==r['away_score'] else 2) if league=='mls' else int(r['home_score']>r['away_score']) for r,_ in tr];base=(np.bincount(labels,minlength=3 if league=='mls' else 2)/len(tr)).tolist()
        ev={'schema':'initial_baseline_temporal_audit.v1','league':league,'model_id':IDS[league],'training_seasons':[2021,2022,2023,2024],'training_n':len(tr),'season_counts':dict(collections.Counter(r['season'] for r in games)),'provider_copy_counts':copies,'training_prior':prior,'baseline_probabilities':base,'evaluation_fit_sha256':digest(fitted),'validation_2025':evaluate([r for r in rows if r[0]['season']==2025],fitted,league,base),'later_audit_2026':evaluate([r for r in rows if r[0]['season']==2026],fitted,league,base),'historical_availability_proven':False,'promotion_status':'INITIAL_RESEARCH_ONLY_NO_DEFAULT_PROMOTION','action_authority':False}
        save(output/league/'evaluation.json',ev);save(output/league/'evaluation_model.json',fitted)
        # Fixed-parameter refit after the independent audit is written. No selection on its result.
        eligible=set(used);deployment=fit([r for r in rows if r[0]['event_id'] in eligible],league);events=[];excluded=collections.Counter()
        historic_by_id={r['event_id']:r for r in games}
        for rec in current_events[league].values():
            e=rec['event'];r=parse(e,league)
            if not r:excluded['outside_regular_season']+=1;continue
            if season_scope is not None and r['season']!=season_scope['last_provider_season']:raise ValueError('CURRENT_PROVIDER_SEASON_MISMATCH')
            if nba_scope is not None and r['season']!=nba_scope['last_provider_season']:raise ValueError('NBA_CURRENT_PROVIDER_SEASON_MISMATCH')
            if r['final']:
                old=historic_by_id.get(r['event_id'])
                if old!=r:raise ValueError('CURRENT_HISTORY_RECONCILIATION:'+r['event_id'])
                continue
            if utc(r['start_time_utc'])<=now:continue
            if season_scope is not None and r['slate_date'] not in cr.get('covered_dates',[]):excluded['outside_acquired_slate_dates']+=1;continue
            r.pop('final');events.append(r)
        fetches=[{'source':r['url'],'sha256':r['raw_sha256'],'fetched_at_utc':r['retrieved_at_utc']} for r in receipts]
        fetches += [{'source':r['url'],'sha256':r['raw_sha256'],'fetched_at_utc':r['retrieved_at_utc']} for r in cr['sources'] if r['league']==league and r['status']=='CAPTURED' and r['kind']=='schedule']
        if len(fetches)==len(receipts):raise ValueError('CURRENT_SCHEDULE_RECEIPT_REQUIRED')
        pkg={'schema':'sports.current_research_package.v1','league':league,'model_id':IDS[league],'captured_at_utc':stamp,'training_cutoff_utc':stamp,'ttl_hours':6,'covered_dates':sorted({(now.astimezone(ZoneInfo('America/Los_Angeles')).date()+dt.timedelta(days=i)).isoformat() for i in range(8)}),'events':events,'fitted_model':deployment,'team_state':state,'prior':prior,'feature_names':FEATURES,'consumed_game_ids':used,'model_sha256':digest({'model':deployment,'state':state,'prior':prior}),'data_grade':'RETAINED_PROVIDER_FINALS_CURRENT_RESEARCH','model_lineage':{'evaluation_sha256':digest(ev),'evaluation':ev,'deployment_training_rows':len(used),'embargo':'PREVIOUS_UTC_DAY_EXCLUDED','excluded_current_events':dict(excluded)},'source_fetches':fetches,'limitations':['INITIAL_RESEARCH_BASELINE_NOT_ACCURACY_DEFAULT','RETROSPECTIVE_PROVIDER_REVISIONS_NOT_HISTORICAL_PIT','NO_PLAYER_AVAILABILITY_FEATURES','NO_WAGERING_AUTHORITY']+(['INDEPENDENT_POISSON_NO_LOW_SCORE_DEPENDENCE'] if league=='mls' else ['INDEPENDENT_MARGIN_TOTAL_NOT_JOINT_SCORE_MODEL']),'action_authority':False,'code_pins':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['models/current/common.py','models/current/linear.py','models/current/baseline.py',f'pipelines/cards/adapters/{league}.py']}}
        if season_scope is not None:
            covered=cr.get('covered_dates')
            if not covered or any(e['slate_date'] not in covered for e in events):raise ValueError('SOURCE_BOUND_COVERAGE_REQUIRED')
            pkg['covered_dates']=sorted(set(covered))
            pkg['model_lineage']['season_scope']=season_scope
            pkg['model_lineage']['season_scope_sha256']=hashlib.sha256(Path(season_scope_path).read_bytes()).hexdigest()
            pkg['model_lineage']['preparation_code_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            pkg['model_lineage']['acquisition_contract_code_sha256']=hashlib.sha256((ROOT/'scripts/nhl_history_applicability.py').read_bytes()).hexdigest()
            pkg['model_lineage']['history_manifest_sha256']=hashlib.sha256((history/'manifest.json').read_bytes()).hexdigest()
            pkg['model_lineage']['current_manifest_sha256']=hashlib.sha256((current/'manifest.json').read_bytes()).hexdigest()
            from models.current.common import current as assert_current
            assert_current(pkg,stamp)
        if nba_scope is not None:
            pkg['model_lineage']['nba_acquisition_scope']=nba_scope
            pkg['model_lineage']['preparation_code_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            pkg['model_lineage']['history_manifest_sha256']=hashlib.sha256((history/'manifest.json').read_bytes()).hexdigest()
            pkg['model_lineage']['current_manifest_sha256']=hashlib.sha256((current/'manifest.json').read_bytes()).hexdigest()
            pkg['limitations'].append('NBA_ACQUISITION_REPAIRED_EXPLICIT_RESEARCH_REFIT_NOT_PROMOTED')
        save(output/league/'package.json',pkg);reports[league]={'events':len(events),'seasons':ev['season_counts'],'validation':ev['validation_2025']['brier'],'audit':ev['later_audit_2026']['brier']};print(json.dumps({league:reports[league]}),flush=True)
    return reports

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--history',type=Path,required=True);p.add_argument('--current',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--league',choices=tuple(IDS),action='append');p.add_argument('--season-scope',type=Path);p.add_argument('--as-of-utc');p.add_argument('--nba-acquisition-scope',type=Path);a=p.parse_args();prepare(a.history,a.current,a.output,leagues=a.league,season_scope_path=a.season_scope,as_of_utc=a.as_of_utc,nba_acquisition_scope_path=a.nba_acquisition_scope)
