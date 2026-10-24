"""Read back exact hosted artifacts; reconcile existing forecasts without refitting.
Missing market evidence blocks only quote comparisons, not source-bound forecasts.
Original artifacts and the failed first aggregation are retained unchanged.
"""
from __future__ import annotations
import concurrent.futures as cf
import hashlib, json, os, subprocess, sys, zipfile
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from scripts.recovery_capture import capture, save_json, utc, ROUTES
from models.common import discrete_research as D
from models.nfl.contextual.recovered_inference import bernoulli_simulation
SRC_RUN=40076728158
SPECS={'cfb':(12553308267,'5d38d2ebec92647ce70c0a83d505ccace199d1cca35400318376c6d47e924c33'), 'nba':(12553288320,'8ecb8bdb74bfd601bd031c31888d6dc5757bb3fc501dbdcb8353034eb7e8065d'), 'nhl':(12553970261,'d44fb9a26798ccf9ae1a6376a278d218d85d2cc18d1c9cbafab4402bc5fb2718'), 'scope':(12553522553,'de9fff87f1f3361e9872b21e98ee61711fd2f653368a2875918b15c1d01b6add')}
OUT=ROOT/'reports/executions/2026-10-24-40076728158';OUT.mkdir(parents=True,exist_ok=False)
WORK=ROOT/'run-output/recovery';WORK.mkdir(parents=True,exist_ok=False)
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def extract(path,dest):
    dest.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if Path(n).is_absolute() or '..' in Path(n).parts: raise ValueError('ZIP_PATH')
        z.extractall(dest)
def read(p):return json.loads(p.read_text())
receipts=[];roots={}
for league,(aid,digest) in SPECS.items():
    target=WORK/(league+'-download.zip')
    with target.open('xb') as f: subprocess.run(['gh','api',f'repos/georgemunoz1-ui/sports-model/actions/artifacts/{aid}/zip'],stdout=f,check=True)
    assert sha(target)==digest, 'ARCHIVE_READBACK_HASH:'+league
    outer=WORK/(league+'-outer');extract(target,outer)
    nested=list(outer.rglob(league+'-evidence.zip'));assert len(nested)==1
    root=WORK/league;extract(nested[0],root);roots[league]=root
    manifest=read(root/'manifest.json')
    for name,d in manifest.items(): assert sha(root/name)==d, 'MEMBER_HASH:'+name
    receipts.append(dict(league=league,artifact_id=aid,artifact_sha256=digest,downloaded_at_utc=utc(),nested_sha256=sha(nested[0]),verified_members=len(manifest),summary_sha256=sha(root/'summary.json')))
allrows=[];coverage={};tests=[]
for league in ('cfb','nba','nhl'):
    root=roots[league];card=read(root/'card/diagnostic_card.json');summary=read(root/'summary.json')
    assert sha(root/'card/diagnostic_card.json')==summary['card_sha256']
    assert sha(root/'packages'/league/'package.json')==summary['package_sha256']
    sources=read(root/('current-'+league)/'events.json')[league]
    drp=root/'distributions/draws/distribution_report.json'
    dr=read(drp) if drp.exists() else {'results':[]}
    missing=[f for f in card['forecasts'] if f['event_id'].split(':')[-1] not in sources]
    additions={};extra=[]
    def detail(f):
        eid=f['event_id'].split(':')[-1]
        spec=(league,'missing_market_event_detail',f'https://site.api.espn.com/apis/site/v2/sports/{ROUTES[league]}/summary?event={eid}',2)
        receipt,payload=capture(WORK/'supplemental',spec)
        return eid,receipt,payload
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        for eid,receipt,payload in pool.map(detail,missing):
            extra.append(receipt)
            if receipt.get('status')=='CAPTURED' and payload:
                header=payload.get('header',{})
                if str(header.get('id'))==eid: additions[eid]=(receipt,payload)
    save_json(OUT/(league+'-supplemental-receipts.json'),extra)
    rows=[];blocked=[]
    for f in card['forecasts']:
        if f.get('forecast_status')!='FORECAST_GENERATED':blocked.append(f);continue
        eid=f['event_id'];short=eid.split(':')[-1]
        assert D.stamp(card['as_of_utc'])<D.stamp(f['start_time_utc'])
        assert D.stamp(card['generated_at_utc'])<D.stamp(f['start_time_utc'])
        simdir=root/'card/draws'/Path(f['simulation']['draw_directory']).name
        original=np.load(simdir/'winner_draws.npy',allow_pickle=False)
        replay,meta=bernoulli_simulation(f['diagnostics']['home_win'],f['numerical_identity']['identity_sha256'],100000)
        assert np.array_equal(original,replay) and len(original)==100000
        row={k:f.get(k) for k in ('event_id','away_team','home_team','start_time_utc','model_id','model_winner','analytic_p','sim_p','projected_total')}
        row.update(league=league.upper(),home_margin=f['diagnostics']['home_margin'],period='FULL_GAME',action_authority=False,cutoff_utc=card['as_of_utc'],forecast_row_sha256=D.digest(f),winner_draw_sha256=f['simulation']['binary']['sha256'],winner_draws_exact_replay=True,warnings=f.get('warnings',[]),quote={},distributions={})
        raw=sources.get(short);odds={}
        if raw:
            e=raw['event'];assert D.stamp(e['date'])==D.stamp(f['start_time_utc'])
            odds=(e['competitions'][0].get('odds') or [{}])[0]
            row['quote'].update(retrieved_at_utc=raw['retrieved_at_utc'],source_sha256=raw['source_sha256'],source_kind='ORIGINAL_SCOREBOARD')
        elif short in additions:
            receipt,payload=additions[short];comp=payload['header']['competitions'][0]
            if D.stamp(comp['date'])==D.stamp(f['start_time_utc']):
                sides={c['homeAway']:c for c in comp['competitors']}
                assert set(sides)=={'home','away'} and sides['home']['team']['id']!=sides['away']['team']['id']
                odds=(payload.get('pickcenter') or comp.get('odds') or [{}])[0]
                row['quote'].update(retrieved_at_utc=receipt['retrieved_at_utc'],source_sha256=receipt['raw_sha256'],source_kind='POST_FORECAST_SUMMARY_CAPTURE',provider_team_ids={s:sides[s]['team']['id'] for s in sides})
            else:row['warnings'].append('SUPPLEMENTAL_EVENT_START_MISMATCH_QUOTES_WITHHELD')
        if odds:
            row['quote'].update(book=odds.get('provider',{}).get('name'),provider_observed_at_utc=None,moneyline={s:odds.get('moneyline',{}).get(s,{}).get('close',{}).get('odds') for s in ('home','away')})
        else:row['warnings'].append('MARKET_QUOTE_UNAVAILABLE_RAW_FORECAST_PRESERVED')
        for drow in dr['results']:
            if drow['event_id']!=eid:continue
            d=drow['distribution'];support,mass=D.validate(d);a=np.load(drp.parent/drow['simulation']['file'],allow_pickle=False);b,m=D.simulate(d,draws=100000)
            assert np.array_equal(a,b) and m['draw_sha256']==drow['simulation']['draw_sha256']
            product=d['product'];line=None;prices={}
            if product=='margin':
                ps=odds.get('pointSpread',{})
                hl=ps.get('home',{}).get('close',{}).get('line');al=ps.get('away',{}).get('close',{}).get('line')
                if hl is not None and al is not None and float(hl)==-float(al):line=float(hl)
                prices={s.upper():ps.get(s,{}).get('close',{}).get('odds') for s in ('home','away')}
            else:
                total=odds.get('total',{});ol=total.get('over',{}).get('close',{}).get('line');ul=total.get('under',{}).get('close',{}).get('line')
                if ol is not None and ul is not None and float(str(ol).lstrip('oO'))==float(str(ul).lstrip('uU')):line=float(str(ol).lstrip('oO'))
                prices={s.upper():total.get(s,{}).get('close',{}).get('odds') for s in ('over','under')}
            child=dict(model_id=d['model_id'],parent_model_id=d['provenance']['parent_model_id'],settlement=d['settlement'],mean=float(support@mass),line=line,analytic={},monte_carlo={},odds=prices,draw_count=100000,draw_sha256=m['draw_sha256'],distribution_sha256=d['distribution_sha256'],exact_replay=True)
            if line is not None:
                emp=D.make_distribution(a.tolist(),[1.]*len(a),league=league,product=product,settlement=d['settlement'],model_id=d['model_id'],provenance=d['provenance'])
                for side in (('HOME','AWAY') if product=='margin' else ('OVER','UNDER')):
                    child['analytic'][side]=D.price(d,line,side);child['monte_carlo'][side]=D.price(emp,line,side)
            row['distributions'][product]=child
        rows.append(row)
    assert len(rows)+len(blocked)==len(card['forecasts'])
    assert len({r['event_id'] for r in rows})==len(rows)
    coverage[league]=dict(forecasts=len(rows),blocked_forecast_rows=blocked,original_input_cutoff=card['as_of_utc'],original_card_sha256=summary['card_sha256'],original_driver_status=summary['status'],original_driver_blockers=summary['blockers'],quotes_available=sum(bool(r['quote'].get('book')) for r in rows),supplemental_quote_requests=len(extra),new_forecasts=0,source_run=SRC_RUN)
    allrows.extend(rows);save_json(OUT/(league+'-forecasts.json'),rows)
    fields=['event_id','away_team','home_team','start_time_utc','model_winner','analytic_p','sim_p','home_margin','projected_total','home_spread','home_cover','home_cover_sim','spread_push','total_line','over','over_sim','total_push','distribution_margin_mean','distribution_total_mean']
    compact=[]
    for r in rows:
        m=r['distributions'].get('margin',{});t=r['distributions'].get('total',{})
        q={**r,'home_spread':m.get('line'),'home_cover':m.get('analytic',{}).get('HOME',{}).get('win'),'home_cover_sim':m.get('monte_carlo',{}).get('HOME',{}).get('win'),'spread_push':m.get('analytic',{}).get('HOME',{}).get('push'),'total_line':t.get('line'),'over':t.get('analytic',{}).get('OVER',{}).get('win'),'over_sim':t.get('monte_carlo',{}).get('OVER',{}).get('win'),'total_push':t.get('analytic',{}).get('OVER',{}).get('push'),'distribution_margin_mean':m.get('mean'),'distribution_total_mean':t.get('mean')}
        compact.append([q.get(k) for k in fields])
    (OUT/(league+'-display.json')).write_text('{"fields":'+json.dumps(fields)+',"rows":[\n'+',\n'.join(json.dumps(r) for r in compact)+'\n]}\n')
    print('RECOVERED',league,len(rows),'quotes',coverage[league]['quotes_available'],flush=True)
result=dict(schema='sports.card_reconciliation.v1',source_run_id=SRC_RUN,recovery_run_id=os.environ.get('GITHUB_RUN_ID'),recovery_commit=os.environ.get('GITHUB_SHA'),created_at_utc=utc(),date='2026-10-24',timezone='America/Los_Angeles',source_readback=receipts,coverage=coverage,other_leagues=read(roots['scope']/'summary.json'),unique_forecasts=len(allrows),new_model_inference=0,original_forecasts_unchanged=True,draws_replayed=sum(1+len(r['distributions']) for r in allrows)*100000,canonical_registrations=0,action_authority=False,live_allocation_units=0)
save_json(OUT/'reconciliation.json',result)
save_json(OUT/'manifest.json',{str(p.relative_to(OUT)):sha(p) for p in sorted(OUT.rglob('*')) if p.is_file()})
print('RECONCILIATION',json.dumps(result),flush=True)
