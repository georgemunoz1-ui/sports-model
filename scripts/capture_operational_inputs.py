#!/usr/bin/env python3
"""Acquire current seven-league evidence and NFL weekly sources; never infer readiness."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
import uuid
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.recovery_capture import ROUTES, capture, save_json
from scripts.operational_capture_contract import SCHEMA, TIMEZONE, schedule_specs, summary_spec, nfl_source_urls


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    started=dt.datetime.now(dt.timezone.utc)
    today=started.astimezone(ZoneInfo(TIMEZONE)).date()
    capture_id=uuid.uuid4().hex
    specs=schedule_specs(today)
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda s:capture(a.output,s),specs))
    events={k:{} for k in ROUTES};details={}
    for rec,payload in results:
        if not payload or rec['kind']!='schedule':continue
        for e in payload.get('events',[]):
            events[rec['league']][e['id']]={'event':e,'source_sha256':rec['raw_sha256'],'retrieved_at_utc':rec['retrieved_at_utc']}
            if rec['league'] in {'wnba','mlb','nfl'}:
                spec=summary_spec(rec['league'],e['id'])
                details[spec[2]]=spec
    with ThreadPoolExecutor(max_workers=6) as pool:results.extend(pool.map(lambda s:capture(a.output,s),details.values()))
    for rec,_ in results:rec['capture_id']=capture_id
    nfl=[]
    urls=nfl_source_urls(today)
    folder=a.output/'nfl';folder.mkdir()
    for name,url in urls.items():
        rec={'capture_id':capture_id,'filename':name,'source_url':url,'requested_at_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            with urllib.request.urlopen(url,timeout=60) as response:
                raw=response.read(80_000_001);headers=dict(response.headers)
                rec.update(http_status=response.status,final_url=response.url)
            rec['retrieved_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
            if len(raw)>80_000_000:raise ValueError('SOURCE_SIZE_LIMIT')
            (folder/name).write_bytes(raw);rec.update(status='captured',sha256=hashlib.sha256(raw).hexdigest(),headers=headers)
        except Exception as e:rec.update(status='failed',error=str(e),retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        nfl.append(rec)
    save_json(folder/'receipt.json',nfl)
    save_json(a.output/'events.json',events)
    save_json(a.output/'report.json',{'schema':SCHEMA,'capture_id':capture_id,'date':str(today),'timezone':TIMEZONE,'capture_started_at_utc':started.isoformat(),'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'sources':[r for r,_ in results],'nfl_sources':nfl,'event_counts':{k:len(v) for k,v in events.items()},'source_capture_only':True,'action_authority':False})
    save_json(a.output/'manifest.json',{str(p.relative_to(a.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.rglob('*') if p.is_file()})
    print(json.dumps({'events':{k:len(v) for k,v in events.items()},'failed_sources':sum(r['status']=='FAILED' for r,_ in results)+sum(r['status']=='failed' for r in nfl)}))
    return 2 if any(r['status']!='CAPTURED' for r,_ in results) or any(r['status']!='captured' for r in nfl) else 0

if __name__=='__main__':raise SystemExit(main())
