"""Verify retained bytes, exact seeded replay, full-slate retention and chronology."""
import json,hashlib,sys
from pathlib import Path
import numpy as np
from refresh import parse,encode,digest,N
from mls_baseline_adapter import _pmf
p=Path(sys.argv[1]);manifest=json.loads((p/'manifest.json').read_text())
for name,m in manifest.items():
    raw=(p/name).read_bytes();assert len(raw)==m['bytes'] and digest(raw)==m['sha256'],name
b=json.loads((p/'bundle.json').read_text());cutoff=parse(b['cutoff_utc'])
for r in b['source_receipts'].values():assert parse(r['retrieved_at_utc'])<=cutoff
state=json.loads((p/'cfb_assimilated_state.json').read_text())
assert state['updates'] and not state['second_season_regression_applied']
assert len({r['event_id'] for r in state['updates']})==len(state['updates'])
assert all(r['completed'] and parse(r['start_time_utc'])<cutoff for r in state['updates'])
for sport in ['cfb','mls']:
    scheduled=json.loads((p/(sport+'_reconciled_schedule.json')).read_text())
    rows=[r for r in b['rows'] if r['league']==sport]
    assert {r['event_id'] for r in rows}=={r['event_id'] for r in scheduled}
for r in b['rows']:
    assert not r['action_authority'] and not r['market_inputs_used']
    if r['forecast_status']!='BASELINE_WITH_UNRESOLVED_INPUTS':continue
    assert cutoff<=parse(r['generated_at_utc'])<parse(r['start_time_utc'])
    s=r['simulation'];m=r['model'];assert s['n_sims']==N
    rng=np.random.Generator(np.random.PCG64(s['seed']))
    if r['league']=='cfb':
        d=(rng.random(N)<m['p_home']).astype('uint8')
        assert float(d.mean())==s['p_home']
        assert m['home_margin'] is None and m['total'] is None
    else:
        probs=np.outer(_pmf(m['expected_home_goals']),_pmf(m['expected_away_goals'])).ravel();probs/=probs.sum()
        sample=rng.choice(len(probs),N,p=probs);d=np.column_stack((sample//13,sample%13)).astype('uint8')
        assert abs(m['p_home_win']+m['p_draw']+m['p_away_win']-1)<1e-12
        assert abs(s['p_home']+s['p_draw']+s['p_away']-1)<1e-12
    assert digest(d.tobytes())==s['draws_sha256']
    assert (p/(r['league']+'_'+r['event_id']+'_draws.bin')).read_bytes()==d.tobytes()
print('PASS: manifest bytes, chronology, full-slate retention, 100K counts, exact keyed replay, probability sums, action OFF')
