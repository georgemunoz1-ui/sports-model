"""Independent capture inventory and mutually rehashed tampering checks."""
import copy, importlib.util, json, os, sys, hashlib, datetime as dt
from pathlib import Path
from urllib.parse import parse_qs,urlparse
import pytest
REPO=Path(os.environ['VERIFY_REPO']);sys.path.insert(0,str(REPO))
from scripts.validate_operational_capture import verify_capture
spec=importlib.util.spec_from_file_location('capture_fixture_setup',REPO/'tests/test_operational_capture_validation.py')
F=importlib.util.module_from_spec(spec);spec.loader.exec_module(F)
ROUTES={'nfl':'football/nfl','cfb':'football/college-football','nba':'basketball/nba','wnba':'basketball/wnba','mlb':'baseball/mlb','nhl':'hockey/nhl','mls':'soccer/usa.1'}

@pytest.fixture
def tree(tmp_path,monkeypatch):return F.capture_tree.__wrapped__(tmp_path,monkeypatch)
def verify(root):return verify_capture(root,'2026-11-04',now=F.NOW)
def load(root):return json.loads((root/'report.json').read_bytes())
def store(root,r):
 F.dump(root/'report.json',r);F.dump(root/'nfl/receipt.json',r['nfl_sources']);F.manifest(root)
def raw_mutation(root,r,row,payload):
 raw=json.dumps(payload,sort_keys=True).encode();sha=hashlib.sha256(raw).hexdigest();row.update(raw_sha256=sha,raw_path='raw/'+sha+'.json');(root/row['raw_path']).write_bytes(raw)
 used={row['raw_path'] for row in r['sources']}
 for path in (root/'raw').iterdir():
  if path.relative_to(root).as_posix() not in used:path.unlink()
 store(root,r)

def test_independently_enumerated_inventory(tree):
 r=load(tree);expected=set();day=dt.date(2026,11,4)
 for offset in range(-7,8):
  d=day+dt.timedelta(days=offset)
  for league,route in ROUTES.items():expected.add((league,'schedule',f'https://site.api.espn.com/apis/site/v2/sports/{route}/scoreboard?dates={d:%Y%m%d}&limit=1000',2))
  expected.add(('mlb','official_schedule',f'https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}&hydrate=probablePitcher,linescore,venue',1))
 d=dt.date(2026,8,30)
 while d<day-dt.timedelta(days=7):
  expected.add(('wnba','schedule',f'https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={d:%Y%m%d}&limit=1000',2));d+=dt.timedelta(days=1)
 got={(x['league'],x['kind'],x['url'],x['evidence_tier']) for x in r['sources'] if x['kind']!='event_summary'}
 assert got==expected
 result=verify(tree);assert result['ok'] and not result['action_authority'] and not result['provider_authenticity_verified']
 assert {x['filename']:x['source_url'] for x in r['nfl_sources']}=={'games.csv':'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv','play_by_play_2026.csv':'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2026.csv'}

@pytest.mark.parametrize('which',['one_day','whole_league','wnba_history','nfl_file','all_sources'])
def test_mutually_rehashed_inventory_omissions_refuse(tree,which):
 r=load(tree)
 if which=='one_day':r['sources'].pop(0)
 if which=='whole_league':r['sources']=[x for x in r['sources'] if x['league']!='mls']
 if which=='wnba_history':r['sources']=[x for x in r['sources'] if 'dates=20260830' not in x['url']]
 if which=='nfl_file':r['nfl_sources'].pop()
 if which=='all_sources':r['sources']=[]
 store(tree,r)
 with pytest.raises(ValueError):verify(tree)

@pytest.mark.parametrize('which',['capture','future','negative','wrong_date','http_false','event_count_bool'])
def test_mutually_rehashed_identity_and_clock_refuse(tree,which):
 r=load(tree);x=r['sources'][0]
 if which=='capture':x['capture_id']='f'*32
 if which=='future':x['retrieved_at_utc']='2026-11-04T16:01:00Z'
 if which=='negative':x['requested_at_utc']='2026-11-04T16:01:00Z'
 if which=='wrong_date':r['date']='2026-11-03'
 if which=='http_false':x['http_status']=True
 if which=='event_count_bool':r['event_counts']['nfl']=True
 store(tree,r)
 with pytest.raises(ValueError):verify(tree)

@pytest.mark.parametrize('which',['empty','no_competition','wrong_competition','wrong_teams','wrong_start'])
def test_summary_id_alone_does_not_substitute_for_identity(tree,which):
 r=load(tree);x=next(x for x in r['sources'] if x['kind']=='event_summary');eid=parse_qs(urlparse(x['url']).query)['event'][0]
 events=json.loads((tree/'events.json').read_bytes());event=copy.deepcopy(events[x['league']][eid]['event']);payload={'header':event}
 if which=='empty':payload={}
 if which=='no_competition':payload['header'].pop('competitions')
 if which=='wrong_competition':payload['header']['competitions'][0]['id']='999999'
 if which=='wrong_teams':payload['header']['competitions'][0]['competitors'][0]['team']['id']='999999'
 if which=='wrong_start':payload['header']['date']='2026-11-04T22:00:00Z';payload['header']['competitions'][0]['date']='2026-11-04T22:00:00Z'
 raw_mutation(tree,r,x,payload)
 with pytest.raises(ValueError):verify(tree)

@pytest.mark.parametrize('name',['report.json','events.json','manifest.json'])
def test_empty_claims_cannot_verify_themselves(tree,name):
 F.dump(tree/name,{})
 if name!='manifest.json':F.manifest(tree)
 with pytest.raises(ValueError):verify(tree)

def test_unrecorded_manifest_file_and_changed_raw_bytes_refuse(tree):
 r=load(tree);raw=tree/r['sources'][0]['raw_path'];raw.write_bytes(b'{}')
 with pytest.raises(ValueError,match='HASH_MISMATCH'):verify(tree)

def test_csv_later_malformed_row_cannot_hide_behind_valid_first_row(tree):
 r=load(tree);raw=tree/'nfl/games.csv';raw.write_bytes(b'game_id,season,week\n2026_01_A_B,2026,1\nbad,2026,1,extra\n');r['nfl_sources'][0]['sha256']=hashlib.sha256(raw.read_bytes()).hexdigest();store(tree,r)
 with pytest.raises(ValueError):verify(tree)

def test_declarations_cannot_erase_events_from_complete_raw_inventory(tree):
 r=load(tree);F.dump(tree/'events.json',{league:{} for league in ROUTES});r['event_counts']={league:0 for league in ROUTES};store(tree,r)
 with pytest.raises(ValueError,match='EVENT_COVERAGE'):verify(tree)

def test_rehashed_url_change_cannot_declare_itself_required_inventory(tree):
 r=load(tree);r['sources'][0]['url']=r['sources'][0]['url'].replace('limit=1000','limit=1');r['sources'][0]['final_url']=r['sources'][0]['url'];store(tree,r)
 with pytest.raises(ValueError,match='MANDATORY_SCHEDULE'):verify(tree)

def test_receipt_mirror_not_merely_manifest_consistent(tree):
 F.dump(tree/'nfl/receipt.json',[]);F.manifest(tree)
 with pytest.raises(ValueError,match='MIRROR'):verify(tree)
