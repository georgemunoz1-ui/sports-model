"""One-off 2026-10-24 research execution; existing forecasters are unchanged.
No canonical registration, promotion, wager, schedule deployment or main write.
Current inputs must pass existing source, six-hour freshness and model gates.
"""
from __future__ import annotations
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
import urllib.request
import zipfile
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DAY = '2026-10-24'
TZ = ZoneInfo('America/Los_Angeles')
PIN = '2fbfaa687c03c8736fd14e329c9f16fa3d101386'
LEAGUE = sys.argv[1]
OUT = ROOT / 'run-output' / LEAGUE
OUT.mkdir(parents=True, exist_ok=False)
from scripts.recovery_capture import ROUTES, capture, save_json, utc
from scripts.capture_priority_schedules import requests_for, build_schedule

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def seal(root):
    save_json(root / 'manifest.json', {str(p.relative_to(root)): sha(p)
              for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'manifest.json'})

def cmd(args, label, env=None):
    before = utc()
    p = subprocess.run([sys.executable, *args], cwd=ROOT, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (OUT / (label + '.log')).write_text(p.stdout)
    save_json(OUT / (label + '.command.json'), dict(command=[sys.executable, *args],
              started_at_utc=before, completed_at_utc=utc(), returncode=p.returncode,
              log_sha256=sha(OUT / (label + '.log'))))
    print('COMMAND', label, 'exit', p.returncode, p.stdout[-3000:], flush=True)
    if p.returncode:
        raise RuntimeError('COMMAND_FAILED:' + label)

def current(league):
    folder = OUT / ('current-' + league)
    folder.mkdir()
    specs = requests_for(league, DAY, ['regular', 'postseason'])
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        got = list(pool.map(lambda s: capture(folder, s), specs))
    events = {}
    for r, payload in got:
        if payload:
            for e in payload.get('events', []):
                events[str(e['id'])] = dict(event=e, source_sha256=r['raw_sha256'],
                                           retrieved_at_utc=r['retrieved_at_utc'])
    try:
        schedule = build_schedule(folder, league, DAY, 'America/Los_Angeles',
                                  ['regular', 'postseason'], got)
    except (ValueError, KeyError, TypeError) as e:
        schedule = dict(schedule_status='SCHEDULE_UNKNOWN', reason=str(e), events=[])
    save_json(folder / 'events.json', {league: events})
    report = dict(sources=[r for r, _ in got], created_at_utc=utc(), covered_dates=[DAY],
                  timezone='America/Los_Angeles', action_authority=False, schedule=schedule)
    if league == 'nhl':
        from scripts.nhl_history_applicability import SCOPE_SHA256
        report['season_scope_sha256'] = SCOPE_SHA256
        report['pending_requests'] = sum(r['status'] != 'CAPTURED' for r, _ in got)
    save_json(folder / 'report.json', report)
    seal(folder)
    return folder, report, events

def cfb_source():
    root = OUT / 'cfb-source'; root.mkdir()
    old = 'c1af1a0ab26d63dea1be4d3ea730ea48a16d8b43'
    specs = [dict(name=f'cfb_schedule_{y}',
                  url=f'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/{old}/schedules/parquet/cfb_schedules_{y}.parquet',
                  path=f'binary/schedules/parquet/cfb_schedules_{y}.parquet')
             for y in range(2001, 2026)]
    specs.append(dict(name='cfb_schedule_2026',
                      url='https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/schedules/parquet/cfb_schedules_2026.parquet',
                      path='binary/cfb_current.parquet'))
    def fetch(s):
        r = dict(s, requested_at_utc=utc())
        try:
            with urllib.request.urlopen(s['url'], timeout=45) as response:
                raw = response.read(); r['http_status'] = response.status
            r['retrieved_at_utc'] = utc()
            if not raw.startswith(b'PAR1') or not raw.endswith(b'PAR1'):
                raise ValueError('PARQUET_MAGIC')
            p = root / s['path']; p.parent.mkdir(parents=True, exist_ok=True)
            with p.open('xb') as f: f.write(raw)
            r.update(sha256=sha(p), status='CAPTURED')
        except Exception as e:
            r.update(status='FAILED', error=str(e), retrieved_at_utc=utc())
        return r
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(fetch, specs))
    save_json(root / 'report.json', dict(binary_sources=records, created_at_utc=utc(), action_authority=False))
    seal(root)
    bad = [r for r in records if r['status'] != 'CAPTURED']
    if bad: raise RuntimeError('CFB_SOURCE_INCOMPLETE:' + json.dumps(bad))
    return root

def nhl_history():
    from scripts import nhl_atomic_capture as C
    scope_path = ROOT / 'research/nhl-season-scope-2026-27-v2.json'
    scope = C.load_scope(scope_path); plan = C.history_plan(scope)
    root = OUT / 'history'; root.mkdir()
    C.atomic(root / 'capture-plan.json', C.encoded(plan))
    selected = {}
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for start in range(0, len(plan['sources']), 4):
            batch = plan['sources'][start:start+4]
            rows = list(pool.map(lambda s: C.capture_one(root, s, C.http_transport, C.utc), batch))
            for s, r in zip(batch, rows): selected[s['id']] = r
            if any(r['status'] != 'CAPTURED' for r in rows):
                C.export_history(root, plan, selected, [], C.utc)
                raise RuntimeError('NHL_HISTORY_INCOMPLETE:' + json.dumps([r for r in rows if r['status'] != 'CAPTURED']))
    for spec in plan['sources']:
        C.verified_receipt(root, spec, selected[spec['id']], now=C.utc(), max_age_hours=6)
    C.export_history(root, plan, selected, [], C.utc, complete=True)
    return root, scope_path

def distributions(league, package_dir, events):
    import numpy as np
    from models.current import common, baseline, cfb
    from models.current.linear import predict
    from models.common import discrete_research as D
    from pipelines.cards.distribution_research import build, load_config
    os.environ['SPORTS_RESEARCH_PACKAGE_DIR'] = str(package_dir)
    cutoff = D.writer_clock(); ctx = common.context(league, events, cutoff)
    fitroot = ROOT / 'data/research/distribution_replay_20261007'
    manifest = json.loads((fitroot / 'manifest.json').read_text())
    parent_path = fitroot / league / 'parent.json'
    assert sha(parent_path) == manifest[league + '/parent.json']
    parent = json.loads(parent_path.read_text()); entries = []
    out = OUT / 'distributions'; out.mkdir()
    for product in ('margin', 'total'):
        p = fitroot / league / (product + '_empirical.json')
        if p.exists():
            assert sha(p) == manifest[league + '/' + p.name]
            entries.append(dict(path=str(p), sha256=sha(p)))
    rows = []
    for e in events:
        p = ctx['package']
        x = cfb.feature_row(p['team_state'], e, p['parameters']) if league == 'cfb' else baseline.feature(p['team_state'], e, parent['source']['prior'])
        names = parent['source']['features'] if league == 'cfb' else baseline.FEATURES
        values = [x[n] for n in names]
        diag = dict(home_margin=predict(parent['fitted']['margin'], values), market_input=False)
        if 'total' in parent['fitted']: diag['total'] = predict(parent['fitted']['total'], values)
        rows.append({**e, 'forecast_status':'FORECAST_GENERATED', 'model_id':parent['model_id'],
                    'model_input_snapshot':x, 'input_snapshot_hash':D.digest(x),
                    'model_state_config_hash':D.digest(dict(fitted_parent_file_sha256=sha(parent_path), package_sha256=ctx['package_sha256'], team_state=p['team_state'])),
                    'parent_artifact_sha256':sha(parent_path), 'current_package_sha256':ctx['package_sha256'],
                    'diagnostics':diag, 'warnings':p['limitations'] + ['FIXED_PARENT_SEPARATE_FROM_WINNER', 'UNCALIBRATED_RESEARCH_DISTRIBUTION', 'NOT_RECOMMENDATION_ELIGIBLE']})
    card = dict(league=league.upper(), as_of_utc=cutoff, generated_at_utc=D.writer_clock(), forecasts=rows, action_authority=False)
    save_json(out / 'fixed-parent-card.json', card)
    save_json(out / 'config.json', dict(schema='sports.distribution_card_config.research.v1', information_set='RECONSTRUCTED_PROVIDER_FINALS_FIXED_PARENT', action_authority=False, models=entries, contracts=[]))
    result = build(card, load_config(out / 'config.json'), out / 'draws', simulations=100000)
    for row in result['results']:
        d = row['distribution']; support, mass = D.validate(d)
        a = np.load(out / 'draws' / row['simulation']['file'])
        b, meta = D.simulate(d, draws=100000)
        assert np.array_equal(a,b) and meta['draw_sha256'] == row['simulation']['draw_sha256']
    return result

result = dict(schema='sports.oneoff_run_summary.v1', requested_date=DAY, timezone='America/Los_Angeles',
              league=LEAGUE, started_at_utc=utc(), requested_base_sha=PIN,
              execution_commit=os.environ.get('GITHUB_SHA'), workflow_run_id=os.environ.get('GITHUB_RUN_ID'),
              action_authority=False, canonical_registrations=0, live_allocation_units=0,
              model_defaults_changed=False, forecasts=[], blockers=[])
try:
    if LEAGUE == 'scope':
        for l in ('nfl','mlb','wnba','mls'):
            _, report, raw = current(l)
            display = []
            for e in (r['event'] for r in raw.values()):
                if dt.datetime.fromisoformat(e['date'].replace('Z','+00:00')).astimezone(TZ).date().isoformat() != DAY: continue
                display.append(dict(event_id=l.upper()+':'+str(e['id']), name=e.get('name'), start_time_utc=e['date'], season=e.get('season')))
            result.setdefault('schedule', {})[l] = dict(status=report['schedule']['schedule_status'], reason=report['schedule'].get('reason'), events=display)
        result['status'] = 'SCHEDULE_SCOPE_ONLY_NO_FORECASTS'
    else:
        current_dir, report, sources = current(LEAGUE)
        if report['schedule']['schedule_status'] != 'PROVIDER_SCHEDULE_CAPTURED':
            raise RuntimeError('SCHEDULE_UNKNOWN:' + str(report['schedule'].get('reason')))
        result['schedule_count'] = len(report['schedule']['events'])
        packages = OUT / 'packages'
        if LEAGUE == 'cfb':
            source = cfb_source()
            cmd(['scripts/prepare_cfb_current.py','--source',str(source),'--output',str(packages)], 'prepare')
        elif LEAGUE == 'nba':
            history = OUT / 'history'
            cmd(['scripts/capture_team_histories.py','--league','nba','--nba-current-bundle',str(current_dir),'--output',str(history)], 'history')
            cmd(['scripts/prepare_initial_baselines.py','--league','nba','--history',str(history),'--current',str(current_dir),'--nba-acquisition-scope',str(history/'nba_acquisition_scope.json'),'--output',str(packages)], 'prepare')
        elif LEAGUE == 'nhl':
            history, scope = nhl_history()
            cmd(['scripts/prepare_initial_baselines.py','--league','nhl','--history',str(history),'--current',str(current_dir),'--season-scope',str(scope),'--output',str(packages)], 'prepare')
        env = {**os.environ, 'SPORTS_RESEARCH_PACKAGE_DIR':str(packages)}
        args = ['scripts/generate_card_force.py','--league',LEAGUE,'--date',DAY,'--simulations','100000','--output-dir',str(OUT/'card')]
        if LEAGUE in ('nba','nhl'): args += ['--initial-research-baselines']
        cmd(args, 'inference', env)
        card = json.loads((OUT/'card/diagnostic_card.json').read_text())
        pkg = json.loads((packages/LEAGUE/'package.json').read_text())
        events = [e for e in pkg['events'] if e['slate_date'] == DAY]
        result['input_cutoff_utc'] = card['as_of_utc']
        result['card_sha256'] = sha(OUT/'card/diagnostic_card.json')
        result['package_sha256'] = sha(packages/LEAGUE/'package.json')
        result['model_lineage'] = {k:v for k,v in pkg['model_lineage'].items() if k != 'evaluation'}
        ds = None
        try: ds = distributions(LEAGUE,packages,events)
        except Exception as e:
            result['blockers'].append('DISTRIBUTIONS:' + type(e).__name__ + ':' + str(e))
            (OUT/'distribution-error.txt').write_text(traceback.format_exc())
        import numpy as np
        from models.common import discrete_research as D
        from models.nfl.contextual.recovered_inference import bernoulli_simulation
        for f in card['forecasts']:
            if f.get('forecast_status') != 'FORECAST_GENERATED':
                result['blockers'].append(dict(event_id=f.get('event_id'), forecast=f)); continue
            row = {k:f.get(k) for k in ['event_id','away_team','home_team','start_time_utc','model_id','model_winner','analytic_p','sim_p','projected_total']}
            row['home_margin'] = f['diagnostics']['home_margin']
            row['period'] = 'FULL_GAME'; row['action_authority'] = False
            row['warnings'] = f.get('warnings',[])
            row['numerical_identity'] = f.get('numerical_identity')
            row['simulation'] = f['simulation']['binary']
            ad = np.load(Path(f['simulation']['draw_directory'])/'winner_draws.npy')
            replay,_ = bernoulli_simulation(f['diagnostics']['home_win'], f['numerical_identity']['identity_sha256'],100000)
            assert np.array_equal(ad,replay)
            row['winner_draws_exact_replay'] = True
            raw = sources.get(f['event_id'].split(':')[-1])
            if raw is None: raise ValueError('CURRENT_SCHEDULE_MODEL_EVENT_JOIN:' + f['event_id'])
            e = raw['event']; assert D.stamp(e['date']) == D.stamp(f['start_time_utc'])
            comp = e['competitions'][0]; o = (comp.get('odds') or [{}])[0]
            row['quote'] = dict(book=o.get('provider',{}).get('name'), retrieved_at_utc=raw['retrieved_at_utc'],
                                source_sha256=raw['source_sha256'], provider_observed_at_utc=None,
                                moneyline={s:o.get('moneyline',{}).get(s,{}).get('close',{}).get('odds') for s in ('home','away')})
            row['distributions'] = {}
            if ds:
                for dr in ds['results']:
                    if dr['event_id'] != f['event_id']: continue
                    d = dr['distribution']; product = d['product']; support,mass = D.validate(d)
                    line = None; ps=o.get('pointSpread',{}); tot=o.get('total',{})
                    if product=='margin' and ps.get('home',{}).get('close',{}).get('line') is not None:
                        line=float(ps['home']['close']['line']); assert float(ps['away']['close']['line']) == -line
                    if product=='total' and tot.get('over',{}).get('close',{}).get('line') is not None:
                        line=float(tot['over']['close']['line'].removeprefix('o')); assert float(tot['under']['close']['line'].removeprefix('u'))==line
                    out=dict(model_id=d['model_id'], parent_model_id=d['provenance']['parent_model_id'], settlement=d['settlement'],
                             mean=float(support@mass),line=line,analytic={},simulations=100000,simulation=dr['simulation'])
                    if line is not None:
                        for side in (('HOME','AWAY') if product=='margin' else ('OVER','UNDER')): out['analytic'][side]=D.price(d,line,side)
                    row['distributions'][product]=out
            result['forecasts'].append(row)
        if len(result['forecasts']) != len(events): raise ValueError('FORECAST_POPULATION_MISMATCH')
        result['status']='EXECUTED_RESEARCH_ONLY'
        result['package_event_count']=len(events)
        result['schedule_only_ids']=sorted({e['event']['provider_event_id'] for e in report['schedule']['events']} - {e['event_id'].split(':')[-1] for e in events})
except Exception as e:
    result['status']='BLOCKED';result['blockers'].append(type(e).__name__+':'+str(e))
    (OUT/'error.txt').write_text(traceback.format_exc())
    print('ERROR',traceback.format_exc(),flush=True)
finally:
    result['completed_at_utc']=utc()
    save_json(OUT/'summary.json',result)
    seal(OUT)
    for row in result['forecasts']: print('CARD_ROW '+json.dumps(row,sort_keys=True,allow_nan=False),flush=True)
    print('RUN_SUMMARY '+json.dumps({k:v for k,v in result.items() if k!='forecasts'},sort_keys=True,allow_nan=False),flush=True)
    print('SUMMARY_SHA256 '+sha(OUT/'summary.json'),flush=True)
    archive=OUT.parent/(LEAGUE+'-evidence.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file():z.write(p,str(p.relative_to(OUT)))
    print('EVIDENCE_ARCHIVE '+json.dumps(dict(path=str(archive),sha256=sha(archive),bytes=archive.stat().st_size)),flush=True)
if result['status']=='BLOCKED':sys.exit(2)
