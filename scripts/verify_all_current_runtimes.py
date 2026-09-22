#!/usr/bin/env python3
"""Build and exercise all current league packages; coverage errors are fatal."""
import argparse,datetime as dt,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from models.current.common import save
from models.nfl.contextual.recovered_inference import digest
from scripts.prepare_mlb_official_current import prepare as mlb
from scripts.prepare_wnba_current import prepare as wnba
from scripts.prepare_cfb_current import prepare as cfb
from scripts.prepare_initial_baselines import prepare as initial


def verify(recovery,current,history,output):
    output=output.resolve();packages=output/'packages';cards=output/'cards';packages.mkdir(parents=True,exist_ok=False)
    mlb(recovery,packages);wnba(recovery,current,packages);cfb(recovery,packages);initial(history,current,packages)
    asof=dt.datetime.now(dt.timezone.utc).isoformat();summary={'schema':'all_current_research_acceptance.v1','asof':asof,'simulations_per_event':100000,'leagues':{},'action_authority':False}
    env=dict(os.environ,SPORTS_RESEARCH_PACKAGE_DIR=str(packages),SPORTS_INITIAL_BASELINES='1')
    for league in ('mlb','wnba','cfb','nba','nhl','mls'):
        p=json.loads((packages/league/'package.json').read_text());days=sorted({e['slate_date'] for e in p['events']}) or p['covered_dates'];count=0;draws=0
        for day in days:
            dest=cards/league/day
            cmd=[sys.executable,str(ROOT/'scripts/generate_card_force.py'),'--league',league,'--date',day,'--as-of-utc',asof,'--simulations','100000','--output-dir',str(dest),'--initial-research-baselines']
            subprocess.run(cmd,env=env,check=True,capture_output=True,text=True,cwd=ROOT)
            card=json.loads((dest/'diagnostic_card.json').read_text())
            if card['incidents'] or card['forecast_count']!=card['scheduled_game_count']:raise ValueError('CURRENT_COVERAGE_FAILURE:'+league+':'+json.dumps(card['incidents']))
            for row in card['forecasts']:
                if row['action_authority'] or row['dose']!=0 or row['model_id']!=p['model_id']:raise ValueError('SELECTION_AUTHORITY_DRIFT')
                drawdir=Path(row['simulation']['draw_directory']);m=json.loads((drawdir/'manifest.json').read_text())
                for name,h in m.items():
                    if hashlib.sha256((drawdir/name).read_bytes()).hexdigest()!=h:raise ValueError('DRAW_MANIFEST_DRIFT')
                arrays={f.stem:np.load(f,allow_pickle=False) for f in drawdir.glob('*.npy')}
                if not arrays or any(len(x)!=100000 for x in arrays.values()):raise ValueError('DRAW_COUNT')
                if league=='mlb':home=float(arrays['hw'].mean());sim=home if row['model_winner']==row['home_team'] else 1-home
                elif league=='mls':
                    a=arrays['away_goals'];h=arrays['home_goals'];ps=[float((a>h).mean()),float((a==h).mean()),float((h>a).mean())]
                    if not np.allclose(ps,row['diagnostics']['simulation_probabilities'],atol=1e-12):raise ValueError('MLS_PROBABILITY_DRAW_MISMATCH')
                    sim=ps[['away','draw','home'].index('draw' if row['model_winner']=='Draw' else 'home' if row['model_winner']==row['home_team'] else 'away')]
                else:
                    home=float(arrays['winner_draws'].mean());sim=home if row['model_winner']==row['home_team'] else 1-home
                if abs(sim-row['sim_p'])>1e-12:raise ValueError('PROBABILITY_NOT_RETAINED_DRAW_MEAN')
                draws+=100000
            count+=card['forecast_count']
        if count!=len(p['events']):raise ValueError('PACKAGE_EVENT_COVERAGE')
        summary['leagues'][league]={'status':'OPERATIONAL' if count else 'OPERATIONAL_NO_SCHEDULED_EVENTS','model_id':p['model_id'],'forecasts':count,'winner_or_score_pairs':draws,'package_sha256':hashlib.sha256((packages/league/'package.json').read_bytes()).hexdigest(),'state_sha256':p['model_sha256'],'model_lineage':p['model_lineage'],'dates_checked':days,'limitations':p['limitations']}
    # Re-run one card for each active league at the same cutoff; retained arrays must match byte-for-byte.
    replay={}
    for league,record in summary['leagues'].items():
        if not record['forecasts']:continue
        day=record['dates_checked'][0];dest=output/'replay'/league
        subprocess.run([sys.executable,str(ROOT/'scripts/generate_card_force.py'),'--league',league,'--date',day,'--as-of-utc',asof,'--simulations','100000','--output-dir',str(dest),'--initial-research-baselines'],env=env,check=True,capture_output=True,text=True,cwd=ROOT)
        old=cards/league/day/'draws';new=dest/'draws'
        a={str(f.relative_to(old)):hashlib.sha256(f.read_bytes()).hexdigest() for f in old.rglob('*.npy')};b={str(f.relative_to(new)):hashlib.sha256(f.read_bytes()).hexdigest() for f in new.rglob('*.npy')}
        if not a or a!=b:raise ValueError('DETERMINISTIC_REPLAY_FAILURE:'+league)
        replay[league]={'identical_draw_files':len(a),'digest':digest(a)}
    summary['deterministic_replay']=replay;save(output/'acceptance.json',summary);print(json.dumps({k:{x:v[x] for x in ('status','forecasts','winner_or_score_pairs')} for k,v in summary['leagues'].items()}));return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--recovery',type=Path,required=True);p.add_argument('--current',type=Path,required=True);p.add_argument('--history',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();verify(a.recovery,a.current,a.history,a.output)
