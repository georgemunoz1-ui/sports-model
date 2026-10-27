"""One-off 2026-10-27 research execution; existing forecasters are unchanged.
No canonical registration, promotion, wager, schedule deployment or main write.
Current inputs must pass existing source, six-hour freshness and model gates.
"""
from __future__ import annotations
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import math
from pathlib import Path
import subprocess
import sys
import traceback
import urllib.request
import zipfile
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DAY = '2026-10-27'
TZ = ZoneInfo('America/Los_Angeles')
PIN = '1715cfc0821185ce8b0413fb96d2ec1ea3c54aeb'
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
    config_path = out / 'config.json'
    result = build(card, load_config(config_path), out / 'draws', simulations=100000)
    for row in result['results']:
        d = row['distribution']; support, mass = D.validate(d)
        a = np.load(out / 'draws' / row['simulation']['file'])
        b, meta = D.simulate(d, draws=100000)
        if len(a) != 100000 or not np.array_equal(a,b) or meta['draw_sha256'] != row['simulation']['draw_sha256']:
            raise ValueError('DISTRIBUTION_DRAW_REPLAY_MISMATCH')
        row['replay'] = {'exact': True, 'count': len(a), 'seed': meta['seed'],
                         'draw_sha256': meta['draw_sha256'],
                         'simulation_code_sha256': meta['simulation_code_sha256']}
    fit_artifacts = {}
    for product in ('margin', 'total'):
        fit_path = fitroot / league / (product + '_empirical.json')
        if fit_path.exists():
            fit_json = json.loads(fit_path.read_text())
            fit_artifacts[product] = {'sha256':sha(fit_path), 'model_id':fit_json.get('model_id'),
                                      'code_sha256':fit_json.get('code_sha256'),
                                      'parent_model_id':fit_json.get('parent_model_id'),
                                      'settlement':fit_json.get('settlement'),
                                      'fit_as_of_utc':fit_json.get('fit_as_of_utc'),
                                      'training_n':fit_json.get('training_n')}
    result['research_evidence'] = {
        'fit_root_manifest_sha256': sha(fitroot / 'manifest.json'),
        'parent_artifact_sha256': sha(parent_path),
        'parent_model_id': parent['model_id'],
        'fixed_parent_card_sha256': sha(out / 'fixed-parent-card.json'),
        'parent_card_sha256': result.get('parent_card_sha256'),
        'distribution_config_sha256': sha(config_path),
        'distribution_code_sha256': D.code_hash(),
        'fit_artifacts': fit_artifacts,
        'current_package_sha256': ctx['package_sha256'],
        'input_information_set': 'RECONSTRUCTED_PROVIDER_FINALS_FIXED_PARENT',
        'action_authority': False,
        'predictive_validation': 'NOT_ESTABLISHED'
    }
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
        def line_num(value):
            if value is None: return None
            if isinstance(value, (int, float)): return float(value)
            text = str(value).strip().lower()
            if text.startswith('o') or text.startswith('u'): text = text[1:]
            try: return float(text)
            except (TypeError, ValueError): return None

        for f in card['forecasts']:
            if f.get('forecast_status') != 'FORECAST_GENERATED':
                result['blockers'].append(dict(event_id=f.get('event_id'), forecast=f))
                disposition = 'POST_START' if f.get('forecast_status') == 'POST_START' else 'UNAVAILABLE'
                result['forecasts'].append({
                    'event_id': f.get('event_id'), 'away_team': f.get('away_team'),
                    'home_team': f.get('home_team'), 'start_time_utc': f.get('start_time_utc'),
                    'disposition': disposition,
                    'cover': {'status': disposition, 'gate': f.get('forecast_status'),
                              'next_evidence': 'New event-specific pre-cutoff forecast execution if still prestart.'},
                    'action_authority': False, 'dose': 0.0
                })
                continue
            row = {k:f.get(k) for k in ['event_id','away_team','home_team','start_time_utc','model_id','model_winner','analytic_p','sim_p','projected_total']}
            row['home_margin'] = f['diagnostics']['home_margin']
            row['period'] = 'FULL_GAME'; row['action_authority'] = False; row['dose'] = 0.0
            row['disposition'] = 'PRE_START' if D.stamp(f['start_time_utc']) > D.stamp(card['as_of_utc']) else 'POST_START'
            row['warnings'] = f.get('warnings',[])
            row['numerical_identity'] = f.get('numerical_identity')
            row['input_snapshot_hash'] = f.get('input_snapshot_hash')
            row['model_state_config_hash'] = f.get('model_state_config_hash')
            row['simulation'] = f['simulation']['binary']
            ad = np.load(Path(f['simulation']['draw_directory'])/'winner_draws.npy')
            replay,_ = bernoulli_simulation(f['diagnostics']['home_win'], f['numerical_identity']['identity_sha256'],100000)
            assert np.array_equal(ad,replay)
            row['winner_draws_exact_replay'] = True
            raw = sources.get(f['event_id'].split(':')[-1])
            if raw is None: raise ValueError('CURRENT_SCHEDULE_MODEL_EVENT_JOIN:' + f['event_id'])
            e = raw['event']; assert D.stamp(e['date']) == D.stamp(f['start_time_utc'])
            comp = e['competitions'][0]; o = (comp.get('odds') or [{}])[0]
            ps = o.get('pointSpread', {})
            total = o.get('total', {})
            row['quote'] = dict(
                book=o.get('provider',{}).get('name'),
                source='ESPN provider scoreboard snapshot',
                retrieved_at_utc=raw['retrieved_at_utc'],
                quote_timestamp_utc=raw['retrieved_at_utc'],
                source_sha256=raw['source_sha256'],
                provider_observed_at_utc=None,
                moneyline={side:o.get('moneyline',{}).get(side,{}).get('close',{}).get('odds') for side in ('home','away')},
                spread={
                    'home_line': line_num(ps.get('home',{}).get('close',{}).get('line')),
                    'away_line': line_num(ps.get('away',{}).get('close',{}).get('line')),
                    'home_odds': ps.get('home',{}).get('close',{}).get('odds'),
                    'away_odds': ps.get('away',{}).get('close',{}).get('odds')
                },
                total={
                    'over_line': line_num(total.get('over',{}).get('close',{}).get('line')),
                    'under_line': line_num(total.get('under',{}).get('close',{}).get('line')),
                    'over_odds': total.get('over',{}).get('close',{}).get('odds'),
                    'under_odds': total.get('under',{}).get('close',{}).get('odds')
                })
            row['distributions'] = {}
            row['cover'] = {'status':'UNAVAILABLE', 'disposition':row['disposition'],
                            'gate':'MARGIN_DISTRIBUTION_NOT_FOUND',
                            'next_evidence':'Compatible fitted margin arm, current event feature frame and exact replay evidence.'}
            parent_card = json.loads((OUT/'distributions'/'fixed-parent-card.json').read_text()) if ds else None
            parent_row = next((pr for pr in (parent_card or {}).get('forecasts',[]) if pr.get('event_id') == f['event_id']), None)
            if ds:
                for dr in ds['results']:
                    if dr['event_id'] != f['event_id']: continue
                    d = dr['distribution']; product = d['product']; support, mass = D.validate(d)
                    line = None; quoted_lines = {}
                    if product == 'margin':
                        line = line_num(ps.get('home',{}).get('close',{}).get('line'))
                        away_line = line_num(ps.get('away',{}).get('close',{}).get('line'))
                        quoted_lines = {'HOME':line, 'AWAY':away_line}
                        if line is not None and away_line is not None and not math.isclose(away_line, -line, abs_tol=1e-9):
                            raise ValueError('SPREAD_LINE_ORIENTATION_MISMATCH')
                    if product == 'total':
                        line = line_num(total.get('over',{}).get('close',{}).get('line'))
                        under_line = line_num(total.get('under',{}).get('close',{}).get('line'))
                        quoted_lines = {'OVER':line, 'UNDER':under_line}
                        if line is not None and under_line is not None and not math.isclose(under_line, line, abs_tol=1e-9):
                            raise ValueError('TOTAL_LINE_ORIENTATION_MISMATCH')
                    out = {
                        'model_id':d['model_id'], 'distribution_arm':d['model_id'],
                        'parent_model_id':d['provenance']['parent_model_id'],
                        'parent_artifact_sha256':(ds.get('research_evidence') or {}).get('parent_artifact_sha256'),
                        'fit_artifact_sha256':d['provenance'].get('fitted_artifact_sha256'),
                        'parent_forecast_sha256':d['provenance'].get('parent_forecast_sha256'),
                        'distribution_sha256':d['distribution_sha256'],
                        'parent_input_snapshot_hash':(parent_row or {}).get('input_snapshot_hash'),
                        'parent_model_state_config_hash':(parent_row or {}).get('model_state_config_hash'),
                        'parent_card_sha256':ds.get('parent_card_sha256'),
                        'distribution_config_sha256':(ds.get('research_evidence') or {}).get('distribution_config_sha256'),
                        'distribution_code_sha256':(ds.get('research_evidence') or {}).get('distribution_code_sha256'),
                        'fit_code_sha256':((ds.get('research_evidence') or {}).get('fit_artifacts') or {}).get(product,{}).get('code_sha256'),
                        'input_snapshot_hash':(parent_row or {}).get('input_snapshot_hash'),
                        'model_state_config_hash':(parent_row or {}).get('model_state_config_hash'),
                        'settlement':d['settlement'], 'settlement_horizon':d['settlement'],
                        'mean':float(support@mass), 'line':line, 'quoted_lines':quoted_lines,
                        'analytic_states':{}, 'simulation_states':{},
                        'model_cover_pct':{}, 'model_push_pct':{},
                        'simulation_cover_pct':{}, 'simulation_push_pct':{},
                        'simulation_count':100000, 'simulation':dr['simulation'],
                        'replay':dr.get('replay'),
                        'predictive_validation':'NOT_ESTABLISHED',
                        'status':'DIAGNOSTIC', 'action_authority':False
                    }
                    if line is not None:
                        sides = ('HOME','AWAY') if product == 'margin' else ('OVER','UNDER')
                        for side in sides:
                            states = D.price(d, line, side)
                            out['analytic_states'][side] = states
                            out['model_cover_pct'][side] = 100.0 * (states['win'] + states['half_win'])
                            out['model_push_pct'][side] = 100.0 * states['push']
                        draws = np.load(OUT/'distributions'/'draws'/dr['simulation']['file'])
                        for side in sides:
                            counts = {state:0 for state in D.STATES}
                            for value in draws:
                                state = D.outcome(int(value), league=d['league'], product=product,
                                                  settlement=d['settlement'], line=line, side=side)
                                counts[state] += 1
                            out['simulation_states'][side] = {state: counts[state]/len(draws) for state in D.STATES}
                            out['simulation_cover_pct'][side] = 100.0*(counts['win']+counts['half_win'])/len(draws)
                            out['simulation_push_pct'][side] = 100.0*counts['push']/len(draws)
                        if line*2 == round(line*2):
                            first = 'HOME' if product == 'margin' else 'OVER'
                            second = 'AWAY' if product == 'margin' else 'UNDER'
                            model_sum = out['model_cover_pct'][first] + out['model_cover_pct'][second] + out['model_push_pct'][first]
                            sim_sum = out['simulation_cover_pct'][first] + out['simulation_cover_pct'][second] + out['simulation_push_pct'][first]
                            passed = abs(model_sum-100.0) <= 1e-6 and abs(sim_sum-100.0) <= 1e-6
                            out['accounting'] = {'model_cover_plus_push_sum_pct':model_sum,
                                                 'simulation_cover_plus_push_sum_pct':sim_sum, 'passed':passed}
                            if not passed: raise ValueError('COVER_PUSH_ACCOUNTING_FAILED')
                        if product == 'margin' and row['disposition'] == 'POST_START':
                            row['cover'] = {'status':'POST_START', 'disposition':'POST_START',
                                            'gate':'START_TIME_PASSED_BEFORE_CUTOFF',
                                            'distribution_arm':out['distribution_arm'],
                                            'parent_model_id':out['parent_model_id'],
                                            'settlement_horizon':out['settlement_horizon'],
                                            'action_authority':False}
                        elif product == 'margin':
                            quote_side_odds = {'HOME':ps.get('home',{}).get('close',{}).get('odds'),
                                               'AWAY':ps.get('away',{}).get('close',{}).get('odds')}
                            row['cover'] = {
                                'status':'COMPLETED', 'disposition':row['disposition'],
                                'line':line, 'opposing_line':quoted_lines.get('AWAY'),
                                'odds':quote_side_odds, 'book':row['quote'].get('book'),
                                'quote_timestamp_utc':row['quote'].get('quote_timestamp_utc'),
                                'provider_observed_at_utc':row['quote'].get('provider_observed_at_utc'),
                                'parent_model_id':out['parent_model_id'],
                                'distribution_arm':out['distribution_arm'],
                                'settlement_horizon':out['settlement_horizon'],
                                'model_cover_pct':out['model_cover_pct'],
                                'actual_simulation_cover_pct':out['simulation_cover_pct'],
                                'model_push_pct':out['model_push_pct'],
                                'actual_simulation_push_pct':out['simulation_push_pct'],
                                'simulation_count':out['simulation_count'],
                                'seed':(out.get('replay') or {}).get('seed', out['simulation'].get('seed')),
                                'draw_sha256':out['simulation'].get('draw_sha256'),
                                'replay_exact':bool((out.get('replay') or {}).get('exact')),
                                'distribution_sha256':out['distribution_sha256'],
                                'fit_artifact_sha256':out['fit_artifact_sha256'],
                                'parent_artifact_sha256':out['parent_artifact_sha256'],
                                'input_snapshot_hash':out['input_snapshot_hash'],
                                'model_state_config_hash':out['model_state_config_hash'],
                                'predictive_validation':'NOT_ESTABLISHED',
                                'status_label':'DIAGNOSTIC',
                                'action_authority':False
                            }
                    else:
                        out['quote_status'] = 'MISSING_CURRENT_LINE'
                        if product == 'margin':
                            row['cover'] = {'status':'UNAVAILABLE', 'disposition':row['disposition'],
                                            'gate':'CURRENT_QUOTE_LINE_MISSING',
                                            'distribution_arm':out['distribution_arm'],
                                            'parent_model_id':out['parent_model_id'],
                                            'settlement_horizon':out['settlement_horizon'],
                                            'simulation_count':out['simulation_count'],
                                            'seed':(out.get('replay') or {}).get('seed', out['simulation'].get('seed')),
                                            'draw_sha256':out['simulation'].get('draw_sha256'),
                                            'predictive_validation':'NOT_ESTABLISHED'}
                    row['distributions'][product] = out
            if row['cover'].get('status') == 'UNAVAILABLE' and not ds:
                row['cover']['gate'] = 'DISTRIBUTION_RESEARCH_FAILED'
                row['cover']['blockers'] = result.get('blockers', [])
                row['cover']['next_evidence'] = 'Repair the exact failed fit/parent/settlement/hash gate and rerun this event before cutoff.'
            result['forecasts'].append(row)
        if len(result['forecasts']) != len(events): raise ValueError('FORECAST_POPULATION_MISMATCH')
        result['package_event_count']=len(events)
        # Preserve every provider-scheduled event even when it cannot be joined to a model package.
        package_provider_ids = {str(e['event_id'].split(':')[-1]) for e in events}
        for scheduled in report['schedule']['events']:
            se = scheduled['event']; provider_id = str(se.get('provider_event_id'))
            if provider_id in package_provider_ids:
                continue
            start = D.stamp(se['start_time_utc'])
            disposition = 'PRE_START' if start > D.stamp(card['as_of_utc']) else 'POST_START'
            result['forecasts'].append({
                'event_id':se.get('event_id'), 'away_team':se.get('away_team'),
                'home_team':se.get('home_team'), 'start_time_utc':se.get('start_time_utc'),
                'disposition':disposition,
                'cover':{'status':'POST_START' if disposition == 'POST_START' else 'UNAVAILABLE',
                         'gate':'SCHEDULE_EVENT_NOT_IN_MODEL_PACKAGE' if disposition == 'PRE_START' else 'START_TIME_PASSED_BEFORE_CUTOFF',
                         'provider_event_id':provider_id,
                         'source_sha256':scheduled.get('source_sha256'),
                         'next_evidence':'Source-bound model event/team join and compatible current fitted state.'},
                'action_authority':False, 'dose':0.0
            })
        result['expected_scheduled_events'] = len(report['schedule']['events'])
        result['cover_coverage'] = {
            'expected_events':len(report['schedule']['events']),
            'completed':sum(1 for r in result['forecasts'] if (r.get('cover') or {}).get('status') == 'COMPLETED'),
            'blocked':sum(1 for r in result['forecasts'] if (r.get('cover') or {}).get('status') == 'UNAVAILABLE'),
            'post_start':sum(1 for r in result['forecasts'] if (r.get('cover') or {}).get('status') == 'POST_START'),
            'entries':[{k:r.get(k) for k in ('event_id','disposition')} | {'cover_status':(r.get('cover') or {}).get('status'),
                     'cover_gate':(r.get('cover') or {}).get('gate')} for r in result['forecasts']]
        }
        result['status']='PARTIAL_RESEARCH_WITH_SCOPED_BLOCKERS' if result['blockers'] or result['cover_coverage']['blocked'] else 'EXECUTED_RESEARCH_ONLY'
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
