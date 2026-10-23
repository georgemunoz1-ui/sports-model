#!/usr/bin/env python3
"""Execute A5 tests and genuine retained-source feature challengers, never a fit.

Inputs are two immutable GitHub Actions ZIPs with published SHA256 digests.
The output retains the exact NHL package/raw captures, all request receipts,
independent training/serving results, execution logs and a content manifest.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlparse
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from models.current.freshness import normalize_captured_schedule
from models.nfl.contextual.recovered_inference import utc
from scripts.prepare_initial_baselines import operational_rest_training_example

ARCHIVES={
 'a5-runtime-sep22.zip':{'sha256':'7f9798c8039b50552fd626957fe27311b772f436dd251df215455af7faa5d182','artifact_id':10684699470,'run_id':35706907718},
 'a5-operational-sources-sep22.zip':{'sha256':'14e10b0d998c107d333aae3dd940569d9333d2e37a72061a3f283567c84f2776','artifact_id':10682535981,'run_id':35700164324}}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:json.dump(value,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')


def run(source_recovery,output):
    source_recovery,output=Path(source_recovery),Path(output)
    for name,receipt in ARCHIVES.items():
        if sha((source_recovery/name).read_bytes())!=receipt['sha256']:raise ValueError('ARCHIVE_DIGEST_MISMATCH:'+name)
    output.mkdir(parents=True,exist_ok=False)
    source=output/'inputs';source.mkdir()
    with zipfile.ZipFile(source_recovery/'a5-runtime-sep22.zip') as archive:
        raw=archive.read('runtime-acceptance/packages/nhl/package.json')
        (source/'package.json').write_bytes(raw);package=json.loads(raw)
    cutoff=package['captured_at_utc'];cut=utc(cutoff)
    with zipfile.ZipFile(source_recovery/'a5-operational-sources-sep22.zip') as archive:
        report_raw=archive.read('report.json');report=json.loads(report_raw)
        (source/'original_source_report.json').write_bytes(report_raw)
        rows=[r for r in report['sources'] if r.get('league')=='nhl' and r.get('kind')=='schedule']
        expected={(dt.date(2026,9,15)+dt.timedelta(days=i)).strftime('%Y%m%d') for i in range(15)}
        actual=[];unique={};all_records=[]
        for rec in rows:
            parsed=urlparse(rec['url']);query=parse_qs(parsed.query)
            if parsed.scheme+'://'+parsed.netloc+parsed.path!='https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard':raise ValueError('SCOREBOARD_URL')
            if set(query)!={'dates','limit'} or query['limit']!=['1000']:raise ValueError('FILTERED_OR_TRUNCATED_QUERY')
            actual.append(query['dates'][0])
            if rec.get('status')!='CAPTURED' or rec.get('http_status')!=200:raise ValueError('CAPTURE_INCOMPLETE')
            if not utc(rec['requested_at_utc'])<=utc(rec['retrieved_at_utc'])<=cut:raise ValueError('CAPTURE_CUTOFF')
            raw=archive.read(rec['raw_path'])
            if sha(raw)!=rec['raw_sha256']:raise ValueError('RAW_CAPTURE_DIGEST')
            decoded=json.loads(raw)
            if not isinstance(decoded.get('events'),list) or len(decoded['events'])>=1000:raise ValueError('CENSUS_TRUNCATION_UNPROVEN')
            if rec['raw_sha256'] not in unique:
                path='raw/'+rec['raw_sha256']+'.json';(source/'raw').mkdir(exist_ok=True)
                (source/path).write_bytes(raw)
                unique[rec['raw_sha256']]={'raw_path':path,'source_sha256':rec['raw_sha256'],
                   'captured_at_utc':rec['retrieved_at_utc'],'source_url':rec['url'],
                   'observation_basis':'RETRIEVAL_BOUND_FINAL_STATUS_NOT_PROVIDER_OBSERVED_TIMESTAMP'}
                all_records.extend(normalize_captured_schedule(raw,league='nhl',captured_at_utc=rec['retrieved_at_utc'],source_sha256=rec['raw_sha256']))
        if set(actual)!=expected or len(actual)!=len(expected):raise ValueError('DAILY_REQUEST_CENSUS')
    # One-day interior guard avoids claiming coverage across provider/UTC date edges.
    since='2026-09-16T00:00:00Z'
    through=min((utc(r['retrieved_at_utc']) for r in rows)).isoformat()
    coverage=[]
    teams={e[s+'_id'] for e in package['events'] for s in ['home','away']}
    for team in sorted(teams):
        eligible=[r for r in all_records if team in {r['home_id'],r['away_id']} and r['status']=='final'
                  and utc(since)<=utc(r['start_time_utc'])<cut and utc(r['observed_at_utc'])<=cut]
        if eligible:
            latest=max(eligible,key=lambda r:(utc(r['start_time_utc']),r['event_id']))
            coverage.append({'team_id':team,'from_utc':since,'through_utc':through,
                             'observed_at_utc':latest['observed_at_utc'],'source_sha256':latest['source_sha256'],
                             'complete':True,'population':'ALL_PLAYED_GAMES',
                             'source_population_definition':'ALL_NHL_SCOREBOARD_GAME_TYPES_WITHIN_INTERIOR_CAPTURE_WINDOW',
                             'request_census_sha256':sha(json.dumps(rows,sort_keys=True,separators=(',',':')).encode())})
    packet={'schema':'sports.operational_rest_history.v1','league':'nhl','sources':list(unique.values()),'coverage':coverage}
    write(source/'history_packet.json',packet)
    write(source/'source_census_receipt.json',{'archives':ARCHIVES,'current_main_source_ref':'90daf8e0036c67a5304aa0747bf50b2266e0b364',
          'all_expected_queries_observed':True,'query_dates':sorted(expected),'requests':rows,
          'coverage_from_utc':since,'coverage_through_utc':through,
          'capture_availability_basis':'ORIGINAL_RETRIEVAL_RECEIPTS_AND_PRE_EVENT_GITHUB_ACTIONS_ARTIFACTS',
          'scope_limitations':['NHL_TEAM_GAME_REST_ONLY_NOT_PLAYER_INTERNATIONAL_WORKLOAD','RETROSPECTIVE_FEATURE_REBUILD_NOT_PREGAME_REGISTRATION']} )
    outcomes=[]
    for event in package['events']:
        key=event['event_id'].replace(':','_')
        command=[sys.executable,str(ROOT/'scripts/build_operational_rest_candidate.py'),'--package',str(source/'package.json'),
                 '--history-packet',str(source/'history_packet.json'),'--event-id',event['event_id'],
                 '--as-of-utc',cutoff,'--output',str(output/'serving'/key)]
        result=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
        write(output/'execution'/f'{key}.json',{'command':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        if result.returncode:raise RuntimeError('ACTUAL_SERVING_EXECUTION_FAILED:'+event['event_id']+':'+result.stderr)
        serving=json.loads((output/'serving'/key/'candidate.json').read_text())
        training=operational_rest_training_example(package['team_state'],event,package['prior'],all_records,cutoff_utc=cutoff,coverage=coverage)
        training.update(parent_package_sha256=sha((source/'package.json').read_bytes()),history_packet_sha256=sha((source/'history_packet.json').read_bytes()),
                        evidence_class='ACTUAL_RETAINED_SOURCE_FEATURE_REBUILD_NOT_MODEL_FIT',forecast_generated=False)
        write(output/'training'/f'{key}.json',training)
        # Parity is reported in addition to, never instead of, independent golden vectors.
        outcomes.append({'event_id':event['event_id'],'home_team':event['home_team'],'away_team':event['away_team'],
                         'legacy_home_rest':serving['legacy_features']['home_rest'],'legacy_away_rest':serving['legacy_features']['away_rest'],
                         'candidate_ready':serving['candidate_ready'],'candidate_features':serving['candidate_features'],
                         'training_serving_same_features':training['features']==serving['candidate_features'],
                         'candidate_artifact_id':serving['candidate_artifact_id'],
                         'rest_receipt':serving['rest_receipt']})
    command=[sys.executable,'-m','unittest','tests.test_operational_rest_golden_vectors','-v']
    test=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
    write(output/'golden_vector_execution.json',{'command':command,'returncode':test.returncode,'stdout':test.stdout,'stderr':test.stderr,
          'oracle_sha256':sha((ROOT/'tests/fixtures/operational_rest_golden_vectors_v1.json').read_bytes()),
          'independent_expected_value_checks':18,'oracle_source':'LITERAL_HAND_COMPUTED_VALUES_NOT_ADAPTER_PARITY'})
    if test.returncode:raise RuntimeError('A5_GOLDEN_VECTOR_FAILURE')
    summary={'schema':'sports.operational_rest_a5_checkpoint.v1','created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
             'candidate_procedure_id':'nhl.initial_causal_score.operational_rest_candidate.v1','parent_model_id':package['model_id'],
             'original_cutoff_utc':cutoff,'actual_source_events':outcomes,'golden_vectors_passed':9,'separate_adapter_oracle_checks':18,
             'execution_class':'RETROSPECTIVE_ACTUAL_SOURCE_FEATURE_CHALLENGER','fitted_model_count':0,
             'forecasts_generated':0,'active_shadow_claim':False,'PREDICTIVE_VALIDATION':'UNVALIDATED','PUBLICATION_ELIGIBILITY':'INELIGIBLE',
             'WAGERING_AUTHORITY':'OFF','oct22_repair_status':'BLOCKED_ORIGINAL_OCT22_PACKAGE_AND_ALL_PLAYED_CAPTURE_NOT_RECOVERED',
             'code_sha256':{p:sha((ROOT/p).read_bytes()) for p in ['models/current/freshness.py','scripts/build_operational_rest_candidate.py',
                    'scripts/prepare_initial_baselines.py','tests/test_operational_rest_golden_vectors.py','tests/run_operational_rest_a5_checkpoint.py']}}
    write(output/'summary.json',summary)
    write(output/'manifest.json',{str(p.relative_to(output)):sha(p.read_bytes()) for p in sorted(output.rglob('*')) if p.is_file()})
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-recovery',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=run(a.source_recovery,a.output)
    print(json.dumps({'actual_events':len(r['actual_source_events']),'ready':sum(x['candidate_ready'] for x in r['actual_source_events']),
                      'golden_oracle_checks':r['separate_adapter_oracle_checks'],'fitted_models':0,'active_shadow':False}))
