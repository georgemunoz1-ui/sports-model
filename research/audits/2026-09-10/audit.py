import json,zipfile,hashlib,math,sys
from pathlib import Path
import numpy as np
from scipy.stats import poisson,nbinom
import engine_snapshot as e
P=Path(__file__).parent
config=json.loads((P/'config.json').read_text());traces=[];mechanics=[];reconciliations=[]
for date,path,run in [('2026-09-08',P.parent/'sep8_refresh.zip',34273154914),('2026-09-09',P.parent/'postgame_sep9/forecast.zip',34330917567)]:
 with zipfile.ZipFile(path) as z:card=json.loads(z.read('diagnostic_card.json'))
 for f in card['forecasts']:
  s=f['model_input_snapshot'];d=f['diagnostics'];n=f['simulation']['simulation_count'];adj=[]
  asp=e.normalize_sp(s['away_sp'],'AWAY',adj);hsp=e.normalize_sp(s['home_sp'],'HOME',adj)
  rng=np.random.Generator(np.random.PCG64(f['simulation']['random_seed']))
  ai=np.clip(rng.normal(5.4,1.3,n),2,8);hi=np.clip(rng.normal(5.4,1.3,n),2,8)
  pens={side:.55*e.val(s[side+'_ra_pg'],4.45)+.45*4.45 for side in ('away','home')}
  for side,opp,sp,ips in [('away','home',hsp,ai),('home','away',asp,hi)]:
   starter=e.starter_ra9(sp);ip=float(ips.mean());off=e.val(s[side+'_rf_pg'],4.45)/4.45;park=1+(e.val(s['park_factor'],1)-1)*e.bipf(sp)/e.LG_BIP
   values=[4.45,4.45+(starter-4.45)*ip/9]
   values.append(values[-1]+(pens[opp]-4.45)*(9-ip)/9);values.append(values[-1]*off);values.append(values[-1]*park);values.append(values[-1]*(1.005 if side=='home' else 1))
   components=dict(zip(['league_environment','opposing_starter','opposing_bullpen_proxy','team_offense','park','home_multiplier'],[values[0]]+[values[i]-values[i-1] for i in range(1,len(values))]))
   frozen=d['projected_'+side+'_runs_latent_mean'];assert abs(values[-1]-frozen)<1e-10
   traces.append(dict(date=date,event_id=f['event_id'],side=side,team=f[side+'_team'],expected_runs=frozen,components=components,trace_method='ORDERED_TELESCOPING_ACCOUNTING_NOT_CAUSAL_ATTRIBUTION',component_order=list(components),lineup='NOT_MODELED',weather_roof='NOT_MODELED',bullpen='TEAM_RA_PROXY_NOT_AVAILABILITY',starter_ip_mean=ip,starter_ra9=starter,offense_factor=off,park_factor=park,expected_run_trace_error=values[-1]-frozen))
  mh=d['projected_home_runs_latent_mean'];ma=d['projected_away_runs_latent_mean'];kh=d['gamma_shape_home'];ka=d['gamma_shape_away'];x=np.arange(1000)
  hp=nbinom.pmf(x,kh,kh/(kh+mh));ap=nbinom.pmf(x,ka,ka/(ka+ma));tie=float(hp@ap);hw=float(hp@np.r_[0,np.cumsum(ap)[:-1]])
  ph=poisson.pmf(x,mh);pa=poisson.pmf(x,ma);pt=float(ph@pa);pw=float(ph@np.r_[0,np.cumsum(pa)[:-1]])
  tshare=.5+.04*np.sign(pens['away']-pens['home']);p=f['grading']['analytic_p_home'];q=f['grading']['stochastic_sim_p_home'];g50=hw+.5*tie;gc=hw+tshare*tie
  mechanics.append(dict(date=date,event_id=f['event_id'],away=f['away_team'],home=f['home_team'],fixed_frozen_home=p,gamma_frozen_home=q,direction_flip=(p>.5)!=(q>.5),lambda_home=mh,lambda_away=ma,shape_home=kh,shape_away=ka,rate_home=kh/mh,rate_away=ka/ma,fixed_latent_home=pw+.5*pt,fixed_tie=pt,gamma_fixed_means_home_tie50=g50,gamma_fixed_means_home_context_tie=gc,gamma_tie=tie,tie_home_share=float(tshare),tie_effect_pp=100*(gc-g50),gamma_mc_se=math.sqrt(q*(1-q)/n),gamma_fixed_ablation_mc=d['ablation']['B_FIXED_GAMMA']['home_win_p'],full_minus_exact_fixed_gamma_pp=100*(q-gc),rates='INDEPENDENT',extra_innings='WINNER_ONLY_NO_SCORE_CONTINUATION',gamma_tail_mass=1-float(hp.sum()*ap.sum())))
  box=P/'sources'/('box_'+f['event_id']+'.json')
  r=dict(date=date,event_id=f['event_id'],forecast_run_id=run,requested_cutoff=card['requested_as_of_utc'],actual_data_vintage=card['pit_provenance']['actual_data_vintage_utc'],was_actual_known_before_cutoff=None,promotion_population_eligible=False)
  states=[]
  for side in ('away','home'):
   sp=s.get(side+'_sp') or {};r['frozen_'+side+'_starter_id']=sp.get('id');r['frozen_'+side+'_starter_state']='PROBABLE_BOUND' if sp.get('id') else 'FALLBACK'
   actual=None
   if box.exists():
    b=json.loads(box.read_text());team=b['teams'][side];starters=[v for v in team['players'].values() if v.get('stats',{}).get('pitching',{}).get('gamesStarted')==1]
    if len(starters)==1:actual=starters[0]['person']['id']
   r['actual_'+side+'_starter_id']=actual;states.append(None if not actual or not sp.get('id') else actual==sp['id'])
  r['starter_match_state']='UNRESOLVED' if None in states else ('BOTH_MATCH' if all(states) else 'BOTH_MISMATCH' if not any(states) else 'AWAY_MISMATCH' if not states[0] else 'HOME_MISMATCH')
  r['reconciliation_source_hash']=hashlib.sha256(box.read_bytes()).hexdigest() if box.exists() else None
  reconciliations.append(r)
for name,rows in [('run_contributions',traces),('gamma_mechanics',mechanics),('starter_reconciliation',reconciliations)]:
 (P/(name+'.json')).write_text(json.dumps(rows,indent=2)+'\n')
print('traces',len(traces),'mechanics',len(mechanics));print(json.dumps([r for r in mechanics if r['direction_flip']],indent=2))
