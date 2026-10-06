#!/usr/bin/env python3
"""Chronological retrospective screen, with separate fitted calibration and holdout.

No source-captured-now historical record is advertised as a pregame registration.
"""
import argparse,collections,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from scipy.optimize import minimize_scalar
from research import mlb_postseason_context as C
from research.mlb_postseason_v1 import simulate as baseline,sha,digest,save_once,stamp


def load_sources(root,report):
    out={}
    for r in report['sources']:
        path=(root/r['raw_path']).resolve()
        if not path.is_relative_to(root.resolve()) or r['status']!='CAPTURED' or sha(path)!=r['raw_sha256']: raise ValueError('SOURCE_INTEGRITY')
        if r['kind'] in out: raise ValueError('DUPLICATE_SOURCE_KIND')
        out[r['kind']]=json.loads(path.read_text())
    return out


def merge_players(sources,prefix):
    people={}
    for k,j in sources.items():
        if not k.startswith(prefix): continue
        for p in j['people']:
            row=people.setdefault(p['id'],dict(p,stats=[]));row['stats'].extend(p.get('stats',[]))
    return people


def initial_order(team):
    slots={}
    for p in team['players'].values():
        order=str(p.get('battingOrder',''))
        if order and order.endswith('00'):
            if order in slots: raise ValueError('DUPLICATE_INITIAL_SLOT')
            slots[order]=p['person']['id']
    return [slots[k] for k in sorted(slots)]


def historical_features(g,schedule,box,players,source):
    day=g['officialDate'];gid=str(g['gamePk']);year=day[:4];team_stats=collections.defaultdict(lambda:collections.Counter());seen=set()
    for d in schedule['dates']:
        for prior in d['games']:
            key=str(prior['gamePk'])
            if key in seen or prior['officialDate']>=day or prior['gameType'] not in ('R','F','D','L','W') or prior['status']['abstractGameState']!='Final': continue
            if prior.get('resumeDate','')[:10]>=day: continue
            seen.add(key)
            for side,other in [('away','home'),('home','away')]:
                t=prior['teams'][side];rf=t['score'];ra=prior['teams'][other]['score'];team_stats[t['team']['id']].update(rf=rf,ra=ra,games=1)
    e={'event_id':'MLB:'+gid,'game_type':g['gameType'],'slate_date':day,'through_date':max(d['date'] for d in schedule['dates'] if d['date']<day),'park_factor':1.0,'historical_park_policy':'NEUTRAL_FOR_ALL_ARMS_NOT_CURRENT_2026_PARK_BACKFILL'}
    roster={};feeds={}
    for side in ('away','home'):
        tid=g['teams'][side]['team']['id'];b=box['teams'][side];starters=[p for p in b['players'].values() if p.get('stats',{}).get('pitching',{}).get('gamesStarted')==1]
        if len(starters)!=1: raise ValueError('HISTORICAL_STARTER_AMBIGUOUS')
        pid=starters[0]['person']['id'];e[side+'_team']=str(tid);e[side+'_pitcher_id']=pid;e['sp_'+side]=C.starter_profile(players[pid],day)
        s=team_stats[tid]
        if s['games']<100: raise ValueError('TEAM_CENSUS_INCOMPLETE')
        e[side+'_form']={'rf':s['rf']/s['games'],'ra':s['ra']/s['games'],'games':s['games']};roster[side]=source[f'roster_{year}_{tid}_{day}'];feeds[side]={'order':initial_order(b)}
    return e,feeds,roster


def metric(rows,field):
    p=np.array([r[field] for r in rows]);y=np.array([r['home_win'] for r in rows]);loss=np.where(y==1,-np.log(p),-np.log1p(-p))
    bins=[]
    for left in np.arange(0,1,.1):
        mask=(p>=left)&(p<left+.1 if left<.9 else p<=1);n=int(mask.sum())
        if not n: continue
        rate=float(y[mask].mean());z=1.96;den=1+z*z/n;mid=(rate+z*z/(2*n))/den;hw=z*math.sqrt(rate*(1-rate)/n+z*z/(4*n*n))/den
        bins.append({'range':[round(float(left),1),round(float(left+.1),1)],'n':n,'mean_probability':float(p[mask].mean()),'observed_rate':rate,'outcome_rate_wilson95':[mid-hw,mid+hw]})
    return {'n':len(rows),'binary_brier':float(np.mean((p-y)**2)),'log_loss':float(loss.mean()),'accuracy':float(((p>=.5)==y).mean()),'mean_probability':float(p.mean()),'mean_abs_distance_from_half':float(abs(p-.5).mean()),'reliability':bins}


def bootstrap(rows,a,b,reps=2000):
    blocks=sorted({r['series_id'] for r in rows});rng=np.random.default_rng(61006);groups={block:[r for r in rows if r['series_id']==block] for block in blocks};values=[]
    for _ in range(reps):
        rr=[r for key in rng.choice(blocks,len(blocks),replace=True) for r in groups[key]]
        values.append(np.mean([(r[a]-r['home_win'])**2-(r[b]-r['home_win'])**2 for r in rr]))
    return {'method':'PAIRED_SERIES_CLUSTER_PERCENTILE','seed':61006,'resamples':reps,'blocks':len(blocks),'delta_direction':a+' minus '+b,'delta':float(np.mean([(r[a]-r['home_win'])**2-(r[b]-r['home_win'])**2 for r in rows])),'ci95':np.quantile(values,[.025,.975]).tolist(),'limitation':'Few series; no pregame input timestamp proof; not promotion evidence'}


def evaluate(root,design_path,output):
    root=Path(root).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False);design=json.loads(Path(design_path).read_text())
    source=load_sources(root,json.loads((root/'report.json').read_text()));rows=[];excluded=[]
    for year in design['development_seasons']+design['calibration_seasons']+design['held_out_seasons']:
        schedule=source[f'season_{year}'];people=merge_players(source,f'people_{year}_');games={str(g['gamePk']):g for d in schedule['dates'] for g in d['games'] if g['gameType'] in ('F','D','L','W') and g['status']['abstractGameState']=='Final'}
        for gid,g in sorted(games.items(),key=lambda kv:(kv[1]['officialDate'],kv[0])):
            try:
                e,feeds,rosters=historical_features(g,schedule,source[f'box_{year}_{gid}'],people,source);ctx=C.build_context(e,feeds,rosters,people)
                seed=int(digest({'event_id':gid,'design':sha(design_path)})[:16],16);r,d=baseline(e,100000,seed)
                row={'event_id':e['event_id'],'date':e['slate_date'],'season':year,'series_id':str(year)+':'+g['gameType']+':'+':'.join(sorted(e[s+'_team'] for s in ('away','home'))),'home_win':int(g['teams']['home']['score']>g['teams']['away']['score']),'baseline':r['home_win_probability'],'seed':seed,'n':100000,'input_sha256':digest(e),'context_sha256':digest(ctx),'draw_hashes':{},'nine_innings':g.get('linescore',{}).get('currentInning'), 'actual_total':sum(g['teams'][s]['score'] for s in ('away','home')),'short_workload':min(ctx[s]['workload']['mean'] for s in ('away','home'))<4.5}
                packed={'baseline':np.packbits(d['postseason_home_win'])}
                for stage in (1,2,3):
                    result,draws=C.simulate(e,ctx,stage,100000,seed);name=f'arm{stage}';row[name]=result['home_win_probability'];packed[name]=np.packbits(draws['home_win_raw']);row['draw_hashes'][name]={k:__import__('hashlib').sha256(v.tobytes()).hexdigest() for k,v in draws.items()}
                row['draw_hashes']['baseline']={k:__import__('hashlib').sha256(v.tobytes()).hexdigest() for k,v in d.items()}
                path=output/'draws'/f'{gid}.npz';path.parent.mkdir(exist_ok=True);np.savez_compressed(path,**packed);row['packed_winner_draw_file']=str(path.relative_to(output));row['packed_winner_draw_sha256']=sha(path);row['encoding']='np.packbits default big bit order; first n bits per arm'
                save_once(output/'inputs'/f'{gid}.json',{'event':e,'context':ctx});rows.append(row)
            except (ValueError,KeyError,ZeroDivisionError) as exc: excluded.append({'event_id':'MLB:'+gid,'season':year,'reason':str(exc)})
        print(year,'eligible',sum(r['season']==year for r in rows),'excluded',sum(r['season']==year for r in excluded),flush=True)
    fit=[r for r in rows if r['season'] in design['calibration_seasons']]
    if len(fit)<20: raise ValueError('CALIBRATION_INSUFFICIENT_MIN20_COMPUTATIONAL_GATE_NOT_VALIDATION')
    def obj(slope):
        p=np.array([C.calibrate(r['arm3'],slope) for r in fit]);y=np.array([r['home_win'] for r in fit]);return float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p)))
    opt=minimize_scalar(obj,bounds=(.25,2),method='bounded');slope=float(opt.x)
    state={'model_id':C.ARMS[4],'parent_model_id':C.ARMS[3],'slope':slope,'fit_seasons':design['calibration_seasons'],'fit_event_ids':[r['event_id'] for r in fit],'fit_rows_sha256':digest(fit),'fit_n':len(fit),'training_cutoff':max(r['date'] for r in fit),'objective':'binary log loss','optimizer':'scipy bounded [.25,2]','at_boundary':min(abs(slope-.25),abs(slope-2))<.001,'design_sha256':sha(design_path),'created_at_utc':stamp(),'predictive_validation':'HOLD'}
    save_once(output/'calibration.json',state)
    for r in rows:r['calibrated']=C.calibrate(r['arm3'],slope)
    summary={'created_at_utc':stamp(),'design_sha256':sha(design_path),'source_manifest_sha256':sha(root/'report.json'),'historical_tier':design['historical_tier'],'park_policy':'ALL_HISTORICAL_ARMS_NEUTRAL_PARK','rows':len(rows),'excluded':excluded,'periods':{},'holdout_comparisons':{},'predictive_validation':'HOLD','promotion':False,'official_release_eligible':False,'action_authority':False,'dose':0.}
    fields=['baseline','arm1','arm2','arm3','calibrated']
    for name,years in [('development',design['development_seasons']),('calibration_fit',design['calibration_seasons']),('held_out',design['held_out_seasons'])]:
        rr=[r for r in rows if r['season'] in years];summary['periods'][name]={f:metric(rr,f) for f in fields if rr and not (name=='development' and f=='calibrated')};summary['periods'][name]['years']=years
    test=[r for r in rows if r['season'] in design['held_out_seasons']]
    for f in fields[1:]:summary['holdout_comparisons'][f]=bootstrap(test,f,'baseline')
    for a,b in [('arm2','arm1'),('arm3','arm2'),('calibrated','arm3')]:summary['holdout_comparisons'][a+'_vs_'+b]=bootstrap(test,a,b)
    summary['holdout_slices']={}
    selectors={'extra_innings':lambda r:(r.get('nine_innings') or 0)>9,'regulation':lambda r:(r.get('nine_innings') or 0)<=9,'short_workload':lambda r:r['short_workload'],'favorite_60plus':lambda r:max(r['baseline'],1-r['baseline'])>=.6,'competitive':lambda r:max(r['baseline'],1-r['baseline'])<.6,'high_realized_total_9plus':lambda r:r['actual_total']>=9,'lower_realized_total':lambda r:r['actual_total']<9}
    for key,fn in selectors.items():
        rr=[r for r in test if fn(r)];summary['holdout_slices'][key]={f:metric(rr,f) for f in fields} if rr else {'n':0,'status':'EMPTY_SLICE'}
    summary['unresolved']=['No historical pregame timestamps or announced opener/bulk/injury severity archive','No authentic same-event market benchmark','Below existing 500-game holdout gate','No prospective challenger cohort','No model promotion; operator merge/integration pending','No weather/platoon/defense transform or score-settlement support']
    save_once(output/'rows.json',rows);save_once(output/'summary.json',summary);print(json.dumps({'rows':len(rows),'excluded':len(excluded),'slope':slope,'holdout':{k:v['binary_brier'] for k,v in summary['periods']['held_out'].items() if isinstance(v,dict)}}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--design',required=True);p.add_argument('--output',required=True);a=p.parse_args();evaluate(a.root,a.design,a.output)
