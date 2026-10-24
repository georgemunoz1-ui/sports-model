"""Complete the October 24 report's missing event joins, never refit forecasts.

The original one-off runner generated 44 CFB forecasts before its downstream
market join stopped at a provider response containing only 25 current events.
Recover the exact original archive and acquire event-specific source evidence.
Failures are reported per event; unrelated original research is preserved.
"""
from __future__ import annotations
import concurrent.futures as cf
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import sys
import unicodedata
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.recovery_capture import capture, save_json, utc

OUT = ROOT / 'reconcile-output'
ARTIFACT = 12553308267
OUTER_SHA = '5d38d2ebec92647ce70c0a83d505ccace199d1cca35400318376c6d47e924c33'
INNER_SHA = 'dbf8bc959ae3ee3ad68f0b53b51a4f2c912711491ea885163060e520f09a19a1'
CARD_SHA = 'fa9f591842031515d38adb5fcb5fc2efa3659a50fedcf9d2ae9f3dfe0dff0056'


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def unpack(raw, dest):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts:
                raise ValueError('UNSAFE_ARCHIVE_PATH')
        z.extractall(dest)


def normalized(s):
    return ''.join(c.lower() for c in unicodedata.normalize('NFKD', s)
                   if c.isalnum())


def bind_summary(payload, expected):
    header = payload.get('header', {})
    provider_id = expected['event_id'].split(':')[-1]
    if str(header.get('id')) != provider_id:
        raise ValueError('EVENT_ID_MISMATCH')
    competitions = header.get('competitions') or []
    if len(competitions) != 1:
        raise ValueError('COMPETITION_COUNT')
    comp = competitions[0]
    source_start = comp.get('date') or header.get('date')
    stamp = lambda x: dt.datetime.fromisoformat(x.replace('Z', '+00:00'))
    if source_start is None or stamp(source_start) != stamp(expected['start_time_utc']):
        raise ValueError('START_TIME_MISMATCH')
    if stamp(source_start) <= dt.datetime.now(dt.timezone.utc):
        raise ValueError('POST_START_CAPTURE_NOT_PREGAME')
    competitors = comp.get('competitors') or []
    if len(competitors) != 2:
        raise ValueError('TEAM_COUNT')
    sides = {c.get('homeAway'): c for c in competitors}
    if set(sides) != {'home', 'away'}:
        raise ValueError('TEAM_SIDE_MISMATCH')
    evidence = {}
    for side in ('home', 'away'):
        t = sides[side]['team']
        aliases = [t.get(k, '') for k in ('location','displayName','shortDisplayName','abbreviation','name')]
        wanted = normalized(expected[side + '_team'])
        if wanted not in {normalized(a) for a in aliases}:
            raise ValueError('TEAM_NAME_UNRECONCILED:' + side + ':' + expected[side + '_team'])
        evidence[side] = dict(provider_id=str(t['id']), expected_team=expected[side + '_team'], source_aliases=aliases)
    return dict(provider_event_id=provider_id, start_time_utc=source_start,
                team_identity=evidence, raw_quotes=payload.get('pickcenter', []),
                odds_scope='PROVIDER_EVENT_QUOTES_RULES_AND_EXECUTABILITY_NOT_VERIFIED')


def selftest():
    e = dict(event_id='CFB:123', home_team='Troy', away_team='San José State', start_time_utc='2099-10-24T20:00:00+00:00')
    p = dict(header=dict(id='123', competitions=[dict(date='2099-10-24T20:00Z', competitors=[
        dict(homeAway='home',team=dict(id='1',location='Troy')),
        dict(homeAway='away',team=dict(id='2',location='San Jose State'))])]), pickcenter=[])
    assert bind_summary(p,e)['provider_event_id']=='123'
    for changed in [dict(e,event_id='CFB:999'),dict(e,home_team='UTSA'),dict(e,start_time_utc='2099-10-24T21:00Z')]:
        try: bind_summary(p,changed)
        except ValueError: pass
        else: raise AssertionError('IDENTITY_MUTATION_ACCEPTED')
    print('RECONCILIATION_SELFTEST: 4 checks passed', flush=True)


def main():
    selftest()
    OUT.mkdir(exist_ok=False)
    started = utc()
    req = urllib.request.Request(
        f'https://api.github.com/repos/georgemunoz1-ui/sports-model/actions/artifacts/{ARTIFACT}/zip',
        headers={'Authorization':'Bearer ' + os.environ['GH_TOKEN'], 'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=90) as r:
        outer = r.read()
    if sha_bytes(outer) != OUTER_SHA:
        raise ValueError('ORIGINAL_OUTER_ARCHIVE_HASH_MISMATCH')
    unpack(outer, OUT/'original-artifact')
    inner=(OUT/'original-artifact/cfb-evidence.zip').read_bytes()
    if sha_bytes(inner) != INNER_SHA:
        raise ValueError('ORIGINAL_INNER_ARCHIVE_HASH_MISMATCH')
    unpack(inner, OUT/'original')
    original=OUT/'original'
    manifest=json.loads((original/'manifest.json').read_text())
    verified=0
    for rel, expected_hash in manifest.items():
        if sha_bytes((original/rel).read_bytes()) != expected_hash:
            raise ValueError('ORIGINAL_MEMBER_HASH_MISMATCH:'+rel)
        verified+=1
    card_bytes=(original/'card/diagnostic_card.json').read_bytes()
    if sha_bytes(card_bytes) != CARD_SHA: raise ValueError('ORIGINAL_CARD_HASH_MISMATCH')
    card=json.loads(card_bytes)
    old_events=json.loads((original/'current-cfb/events.json').read_text())['cfb']
    missing=[f for f in card['forecasts'] if f['event_id'].split(':')[-1] not in old_events]
    source_dir=OUT/'supplement'; source_dir.mkdir()
    def acquire(f):
        eid=f['event_id'].split(':')[-1]
        spec=('cfb','event_reconciliation',f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event={eid}',2)
        receipt,payload=capture(source_dir,spec)
        row=dict(event_id=f['event_id'], source_receipt=receipt, original_cutoff_utc=card['as_of_utc'], market_is_downstream_only=True)
        try:
            if receipt.get('status')!='CAPTURED' or not isinstance(payload,dict): raise ValueError('SOURCE_CAPTURE_FAILED')
            row.update(bind_summary(payload,f));row['status']='EVENT_BOUND'
        except Exception as ex:
            row.update(status='UNRESOLVED',reason=type(ex).__name__+':'+str(ex))
        return row
    with cf.ThreadPoolExecutor(max_workers=4) as pool: rows=list(pool.map(acquire,missing))
    report=dict(schema='sports.cfb_market_join_reconciliation.v1',created_at_utc=utc(),started_at_utc=started,
                execution_commit=os.environ.get('GITHUB_SHA'),workflow_run_id=os.environ.get('GITHUB_RUN_ID'),
                original_run_id=40076728158,original_artifact_id=ARTIFACT,original_outer_sha256=OUTER_SHA,
                original_inner_sha256=INNER_SHA,original_card_sha256=CARD_SHA,verified_original_members=verified,
                original_forecast_count=len(card['forecasts']),original_quote_join_count=len(card['forecasts'])-len(missing),
                missing_event_count=len(missing),recovered_event_count=sum(r['status']=='EVENT_BOUND' for r in rows),
                event_reconciliation=rows,forecast_bytes_unchanged=sha_bytes((original/'card/diagnostic_card.json').read_bytes())==CARD_SHA,
                new_model_inference=False,original_failed_run_preserved=True,action_authority=False,
                status='COMPLETE' if all(r['status']=='EVENT_BOUND' for r in rows) else 'PARTIAL_EVENT_DEPENDENCIES')
    save_json(source_dir/'report.json',report)
    save_json(source_dir/'manifest.json',{str(p.relative_to(source_dir)):sha_bytes(p.read_bytes()) for p in sorted(source_dir.rglob('*')) if p.is_file() and p.name!='manifest.json'})
    print('RECONCILIATION_SUMMARY '+json.dumps({k:v for k,v in report.items() if k!='event_reconciliation'},sort_keys=True),flush=True)
    for r in rows:print('EVENT_STATUS '+json.dumps({k:r[k] for k in ('event_id','status','reason') if k in r}),flush=True)
    # Event-specific unresolved sources do not discard unrelated original research.
    if report['status']!='COMPLETE':sys.exit(2)


if __name__=='__main__': main()
