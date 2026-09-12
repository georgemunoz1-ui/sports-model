"""Explicit research refresh; no operational registry or market access.

CFB updates the launch Elo on completed FBS/FBS games only. It never feeds
causal Elo into the unrelated fitted margin model. MLS reuses the repository
Poisson baseline and samples its exact renormalized score grid.
"""
import concurrent.futures, csv, datetime as dt, hashlib, json, math, sys, os
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
from mls_baseline_adapter import run_baseline, _pmf

ROOT = Path(__file__).resolve().parent
N = 100000
TZ = ZoneInfo('America/Los_Angeles')
def stamp(): return dt.datetime.now(dt.timezone.utc)
def parse(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
def digest(b): return hashlib.sha256(b).hexdigest()
def encode(x): return (json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def score(x):
    v=x.get('value') if isinstance(x,dict) else x
    f=float(v)
    if not math.isfinite(f) or f<0 or f!=int(f): raise ValueError('INVALID_FINAL_SCORE')
    return int(f)
def normalize(e):
    c=e['competitions'][0]; t={x['homeAway']:x for x in c['competitors']}
    return dict(event_id=str(e['id']),start_time_utc=e['date'],
        home_id=str(t['home']['team']['id']),away_id=str(t['away']['team']['id']),
        home_team=t['home']['team']['displayName'],away_team=t['away']['team']['displayName'],
        neutral_site=c.get('neutralSite'),time_valid=c.get('timeValid',e.get('timeValid',False)),
        completed=c.get('status',e.get('status',{})).get('type',{}).get('completed',False),
        home_score=score(t['home']['score']) if 'score' in t['home'] else None,
        away_score=score(t['away']['score']) if 'score' in t['away'] else None)
def run():
    out=ROOT.parent/('run-'+stamp().strftime('%Y%m%dT%H%M%SZ'));out.mkdir()
    for name in ['refresh.py','validate.py','mls_baseline_adapter.py','launch.json','cfb_schedule.csv']:
        (out/('source_'+name)).write_bytes((ROOT/name).read_bytes())
    sources={
      'cfb_schedule':'football/college-football/scoreboard?dates=20260912-20260912&groups=80&limit=1000',
      'cfb_history':'football/college-football/scoreboard?dates=20260801-20260912&groups=80&limit=1000',
      'mls_schedule':'soccer/usa.1/scoreboard?dates=20260912-20260912&limit=1000',
      'mls_history':'soccer/usa.1/scoreboard?dates=20260201-20260912&limit=1000'}
    def fetch(item):
        key,suffix=item;url='https://site.api.espn.com/apis/site/v2/sports/'+suffix
        errors=[]
        for attempt in range(3):
            try:
                raw=urllib.request.urlopen(url,timeout=60).read();retrieved=stamp().isoformat()
                data=json.loads(raw)
                if 'events' not in data: raise ValueError('EVENTS_MISSING')
                (out/(key+'.json')).write_bytes(raw)
                return key,data,dict(url=url,retrieved_at_utc=retrieved,sha256=digest(raw),attempt=attempt+1)
            except Exception as e: errors.append(str(e))
        raise RuntimeError(str((key,errors)))
    captured=list(concurrent.futures.ThreadPoolExecutor(4).map(fetch,sources.items()))
    data={k:d for k,d,r in captured}; receipts={k:r for k,d,r in captured}
    cutoff=stamp(); write=lambda name,x:(out/name).write_bytes(encode(x))
    write('source_receipts.json',receipts)
    cached_path=ROOT/'cfb_schedule.csv'
    cached=list(csv.DictReader(cached_path.open()))
    identities={}; conflict_ids=set()
    for r in cached:
        for s in ('home','away'):
            key=r[s+'_id']; value=(r[s+'_team'],r[s+'_division'])
            if key in identities and identities[key]!=value:conflict_ids.add(key)
            identities[key]=value
    launch=json.loads((ROOT/'launch.json').read_text()); elo=dict(launch['team_elo'])
    params=launch['parameters']; updates=[]; rejected=[]
    history={}
    for e in data['cfb_history']['events']:
        r=normalize(e)
        if r['event_id'] in history and history[r['event_id']]!=r:raise ValueError('CONFLICTING_HISTORY')
        history[r['event_id']]=r
    for r in sorted(history.values(),key=lambda x:(x['start_time_utc'],x['event_id'])):
        if not r['completed'] or parse(r['start_time_utc'])>=cutoff: continue
        h,a=r['home_id'],r['away_id']
        if h not in identities or a not in identities or h in conflict_ids or a in conflict_ids:
            rejected.append(dict(event_id=r['event_id'],reason='IDENTITY_UNRESOLVED'));continue
        hn,hd=identities[h];an,ad=identities[a]
        if hd!='fbs' or ad!='fbs':
            rejected.append(dict(event_id=r['event_id'],reason='CROSS_DIVISION_UPDATE_EXCLUDED'));continue
        if hn not in elo or an not in elo:raise ValueError('FBS_PRIOR_MISSING')
        if r['neutral_site'] is None:raise ValueError('NEUTRAL_STATUS_MISSING')
        p=1/(1+10**(-(elo[hn]-elo[an]+(0 if r['neutral_site'] else params['home_advantage']))/400))
        margin=r['home_score']-r['away_score'];y=1 if margin>0 else 0 if margin<0 else .5
        delta=params['k']*math.log1p(abs(margin))*(y-p)
        updates.append(dict(**r,home_elo_before=elo[hn],away_elo_before=elo[an],delta=delta))
        elo[hn]+=delta;elo[an]-=delta
    state=dict(model_id='cfb.causal_elo_2026_fbs_updates.v0_1.research',
        parent_model_id=launch['model_id'],parent_sha256=digest((ROOT/'launch.json').read_bytes()),
        cutoff_utc=cutoff.isoformat(),parameters=params,team_elo=elo,updates=updates,
        excluded_updates=rejected,second_season_regression_applied=False,
        update_scope='FBS_VS_FBS_ONLY',status='UNVALIDATED_RESEARCH',action_authority=False)
    write('cfb_assimilated_state.json',state)
    # Build MLS state only from captured completed league events.
    teams={}; league=dict(matches=0,home_goals=0,away_goals=0,goals=0); seen={}
    for e in data['mls_history']['events']:
        r=normalize(e)
        if not r['completed'] or parse(r['start_time_utc'])>=cutoff:continue
        if r['event_id'] in seen:
            if seen[r['event_id']]!=r:raise ValueError('MLS_HISTORY_CONFLICT')
            continue
        seen[r['event_id']]=r
        for side,opp in [('home','away'),('away','home')]:
            t=teams.setdefault(r[side+'_id'],dict(games=0,gf=0,ga=0))
            t['games']+=1;t['gf']+=r[side+'_score'];t['ga']+=r[opp+'_score']
        league['matches']+=1;league['home_goals']+=r['home_score'];league['away_goals']+=r['away_score']
        league['goals']+=r['home_score']+r['away_score']
    mstate=dict(teams=teams,league=league,history_event_ids=sorted(seen),cutoff_utc=cutoff.isoformat())
    write('mls_state.json',mstate)
    rows=[]
    for sport in ('cfb','mls'):
        slate=[normalize(e) for e in data[sport+'_schedule']['events']]
        assert len({r['event_id'] for r in slate})==len(slate)
        write(sport+'_reconciled_schedule.json',slate)
        for r in slate:
            r.update(league=sport,forecast_status='BLOCKED',action_authority=False,
                market_inputs_used=False,canonical_prospective_eligible=False)
            rows.append(r)
            if parse(r['start_time_utc']).astimezone(TZ).date().isoformat()!='2026-09-12':
                r['reason']='OUTSIDE_PACIFIC_SLATE';continue
            if not r['time_valid'] or parse(r['start_time_utc'])<=stamp():
                r['reason']='START_UNCONFIRMED_OR_POST_START';continue
            if sport=='cfb':
                ids=[r['home_id'],r['away_id']]
                if any(t not in identities or t in conflict_ids for t in ids):
                    r['reason']='IDENTITY_UNRESOLVED';continue
                (hn,hd),(an,ad)=[identities[t] for t in ids]
                if hd!='fbs' or ad!='fbs':r['reason']='OOD_REJECT_FCS_FBS_BRIDGE_BLOCKED';continue
                if not updates or hn not in elo or an not in elo:
                    r['reason']='CURRENT_RATING_UNAVAILABLE';continue
                if r['neutral_site'] is None:r['reason']='VENUE_STATE_UNKNOWN';continue
                p=1/(1+10**(-(elo[hn]-elo[an]+(0 if r['neutral_site'] else params['home_advantage']))/400))
                model_id=state['model_id']; snapshot=dict(event=r,state_sha256=digest(encode(state)))
                sh=digest(encode(snapshot));seed=int(digest(f"{r['event_id']}|{sh}|{model_id}|{N}".encode())[:16],16)
                draws=(np.random.Generator(np.random.PCG64(seed)).random(N)<p).astype('uint8')
                sim=dict(p_home=float(draws.mean()),method='BERNOULLI_OUTCOME_MC_NOT_SCORE_SIMULATION')
                model=dict(p_home=p,home_margin=None,total=None)
            else:
                if any(t not in teams for t in [r['home_id'],r['away_id']]):r['reason']='TEAM_HISTORY_MISSING';continue
                event=dict(r,home_team=r['home_id'],away_team=r['away_id'])
                model=run_baseline(event,teams,league);model_id=model['model_id']
                snapshot=dict(event=r,state_sha256=digest(encode(mstate)))
                sh=digest(encode(snapshot));seed=int(digest(f"{r['event_id']}|{sh}|{model_id}|{N}".encode())[:16],16)
                probs=np.outer(_pmf(model['expected_home_goals']),_pmf(model['expected_away_goals'])).ravel();probs/=probs.sum()
                sample=np.random.Generator(np.random.PCG64(seed)).choice(len(probs),N,p=probs)
                draws=np.column_stack((sample//13,sample%13)).astype('uint8')
                sim=dict(p_home=float(np.mean(draws[:,0]>draws[:,1])),p_draw=float(np.mean(draws[:,0]==draws[:,1])),p_away=float(np.mean(draws[:,0]<draws[:,1])),mean_home_goals=float(draws[:,0].mean()),mean_away_goals=float(draws[:,1].mean()),method='SAME_13_BY_13_RENORMALIZED_POISSON_GRID')
            raw=draws.tobytes();(out/(sport+'_'+r['event_id']+'_draws.bin')).write_bytes(raw)
            r.update(forecast_status='BASELINE_WITH_UNRESOLVED_INPUTS',model_id=model_id,
                model=model,simulation=dict(**sim,n_sims=N,seed=seed,draws_sha256=digest(raw),dtype='uint8',shape=list(draws.shape)),
                input_snapshot_hash=sh,cutoff_utc=cutoff.isoformat(),generated_at_utc=stamp().isoformat(),
                unresolved_inputs=['lineup_or_availability','injury_suspension','weather','travel_effect'],
                freshness_scope='COMPLETED_RESULTS_REFRESH_ONLY',information_adjustment=0)
            if stamp()>=parse(r['start_time_utc']):r['forecast_status']='POST_START_REJECT'
    write('bundle.json',dict(schema='research_refresh.v1',rows=rows,cutoff_utc=cutoff.isoformat(),
        source_receipts=receipts,source_commit=os.environ.get('GITHUB_SHA'),code_sha256=digest(Path(__file__).read_bytes()),numpy_version=np.__version__,
        action_authority=False,operational_health='RED_PREEXISTING_FAILURES',
        cfb_update_count=len(updates),mls_history_count=len(seen)))
    lines=['# September 12 refreshed CFB and MLS research card','',
      'Action authority OFF. New research baselines; predictive improvement unvalidated. Existing production models and frozen cards unchanged.',
      '',f'Cutoff: {cutoff.isoformat()}. Completed FBS/FBS updates: {len(updates)}. Completed MLS matches: {len(seen)}.',
      '', 'CFB: causal Elo winner probability plus Bernoulli outcome Monte Carlo; no margin or total inference. MLS: native independent-Poisson score grid plus Monte Carlo from that same grid. 100,000 paths per generated forecast.',
      '', 'Freshness is limited to captured completed results. Lineups, injuries, travel effects and weather remain unresolved. Historical source-effective times are not certified; observations were fetched before this new cutoff. Not canonical prospective evidence.',
      '', '| League | Away @ Home | Status | Model home % | MC home % | Model draw % | MC draw % | Away–home expected goals |',
      '|---|---|---|---:|---:|---:|---:|---|']
    for r in rows:
        if r['forecast_status']!='BASELINE_WITH_UNRESOLVED_INPUTS':
            lines.append(f"| {r['league']} | {r['away_team']} @ {r['home_team']} | {r.get('reason')} | — | — | — | — | — |")
            continue
        m=r['model'];s=r['simulation'];ph=m.get('p_home',m.get('p_home_win'))
        draw=f"{100*m['p_draw']:.2f}" if 'p_draw' in m else '—'
        ds=f"{100*s['p_draw']:.2f}" if 'p_draw' in s else '—'
        goals=f"{m['expected_away_goals']:.2f}–{m['expected_home_goals']:.2f}" if r['league']=='mls' else 'UNSUPPORTED'
        lines.append(f"| {r['league']} | {r['away_team']} @ {r['home_team']} | RESEARCH_BASELINE | {100*ph:.2f} | {100*s['p_home']:.2f} | {draw} | {ds} | {goals} |")
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    write('manifest.json',{p.name:dict(bytes=p.stat().st_size,sha256=digest(p.read_bytes())) for p in out.iterdir()})
    print(json.dumps(dict(output=str(out),cfb_updates=len(updates),mls_history=len(seen),
        counts={s:{status:sum(r['league']==s and r['forecast_status']==status for r in rows) for status in sorted({r['forecast_status'] for r in rows})} for s in ['cfb','mls']})))
if __name__=='__main__':run()
