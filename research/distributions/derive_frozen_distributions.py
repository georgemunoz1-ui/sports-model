"""Append diagnostic children from preserved inputs/draws, never new forecasts."""
import datetime, hashlib, json
from pathlib import Path
import numpy as np
from models.common.score_distributions_v1 import extract,decode
from models.mlb.monte_carlo_v1 import run

def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n')
out=Path('distribution-children');out.mkdir(exist_ok=False)
mlb_path=next(p for p in Path('parents/mlb').rglob('diagnostic_card.json') if p.parent.name=='mlb')
mlb=json.loads(mlb_path.read_text());config=json.loads(Path('data/models/mlb/v13_1_monte_carlo_config_v1.json').read_text())
children=[]
for row in mlb['forecasts']:
    captured=[]
    replay=run(row['model_input_snapshot'],config,row['simulation']['simulation_count'],score_sink=lambda h,a:captured.append(extract(h,a,score_period='MLB_NINE_INNING_PROXY')))
    if replay['output_hash']!=row['provenance']['output_hash']:
        raise ValueError('PARENT_NUMERICAL_HASH_MISMATCH:'+str(row['event_id']))
    child=dict(event_id=row['event_id'],league='MLB',away_team=row['away_team'],home_team=row['home_team'],
        parent_output_hash=replay['output_hash'],parent_card_sha256=sha(mlb_path.read_bytes()),
        parent_workflow_run_id=34689434612,distribution=captured[0],
        provenance='REPRODUCED_FROM_FROZEN_INPUTS_MATCHED_PARENT_HASH_NOT_ORIGINAL_PREGAME_DRAW_RECEIPT')
    children.append(child)
mls_path=next(Path('parents/mls').rglob('bundle.json'));mls=json.loads(mls_path.read_text())
for row in mls['rows']:
    if row['league']!='mls' or 'simulation' not in row:continue
    s=row['simulation'];p=mls_path.parent/('mls_'+row['event_id']+'_draws.bin');raw=p.read_bytes()
    if sha(raw)!=s['draws_sha256'] or s['shape']!=[100000,2] or s['dtype']!='uint8':raise ValueError('PARENT_DRAW_CONTRACT')
    d=np.frombuffer(raw,dtype='uint8').reshape(s['shape'])
    children.append(dict(event_id=row['event_id'],league='MLS',away_team=row['away_team'],home_team=row['home_team'],
        parent_card_sha256=sha(mls_path.read_bytes()),parent_draw_sha256=s['draws_sha256'],
        parent_workflow_run_id=34690007684,distribution=extract(d[:,0],d[:,1],score_period='MLS_REGULATION_GRID'),
        provenance='EXTRACTED_FROM_PRESERVED_SCORE_PAIRS'))
lines=['# September 12 derived score distributions','',
    'Append-only diagnostic children, not replacement forecasts. MLB draws reproduced from frozen inputs only after exact parent numerical-hash agreement; MLS draws read from original archived bytes. No outcomes or new source data used.',
    '', 'MLB scores are nine-inning proxies; full-game run-line/total settlement remains unsupported. MLS scope is the existing 0–12 renormalized regulation-score grid. Empirical frequencies are simulation estimates, not exact population probabilities. CFB Bernoulli outputs cannot identify scores, margins, or totals.',
    '', '| League | Away @ Home | Home margin mean | Margin P10–P90 | Total mean | Total P10–P90 |',
    '|---|---|---:|---|---:|---|']
for c in children:
    c.update(schema='derived_distribution_child.v1',derived_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),action_authority=False,canonical_prospective_eligible=False)
    # Check lossless decode and exact mean identities before publication.
    h,a=decode(c['distribution']);m=c['distribution']['margin'];t=c['distribution']['total']
    assert float((h-a).mean())==m['mean'] and float((h+a).mean())==t['mean']
    write(out/(c['league']+'_'+c['event_id']+'.json'),c)
    lines.append(f"| {c['league']} | {c['away_team']} @ {c['home_team']} | {m['mean']:.2f} | {m['quantiles']['p10']}–{m['quantiles']['p90']} | {t['mean']:.2f} | {t['quantiles']['p10']}–{t['quantiles']['p90']} |")
(out/'report.md').write_text('\n'.join(lines)+'\n')
write(out/'manifest.json',{p.name:dict(sha256=sha(p.read_bytes()),bytes=p.stat().st_size) for p in out.iterdir()})
print(json.dumps(dict(status='PASS',children=len(children),mlb=sum(c['league']=='MLB' for c in children),mls=sum(c['league']=='MLS' for c in children))))
