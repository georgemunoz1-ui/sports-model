"""Source-bound research assimilation. Never rewrites or upgrades canonical finals."""
import collections
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
from harness.mlb_form_state import normalize_team

ROOT = Path(__file__).resolve().parents[2]

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def instant(value):
    x = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if x.tzinfo is None:
        raise ValueError('NAIVE_TIMESTAMP')
    return x

def assimilate(canonical_path, staged_path, target_date, cutoff):
    """Exact identities retain doubleheaders. Same-ID conflicts fail closed."""
    target = dt.date.fromisoformat(target_date)
    now = instant(cutoff)
    base = []
    with Path(canonical_path).open() as f:
        for x in csv.DictReader(f):
            if x['status'] != 'final' or x.get('result_status') != 'FINAL' or x.get('source_tier') != '1' or x['date'] >= target_date:
                continue
            base.append(dict(game_id=x['game_id'], date=x['date'], away=normalize_team(x['away']), home=normalize_team(x['home']), away_score=int(x['away_score']), home_score=int(x['home_score']), source='CANONICAL_TIER1'))
    if not base:
        raise ValueError('CANONICAL_BASE_ABSENT')
    boundary = max(x['date'] for x in base)
    rows = {x['game_id']: x for x in base}
    if len(rows) != len(base):
        raise ValueError('DUPLICATE_CANONICAL_ID')
    new = []
    for x in json.loads(Path(staged_path).read_text()):
        if x['league'] != 'mlb' or x['status'] != 'final':
            continue
        day = x['slate_date']
        if day >= target_date or day <= boundary:
            continue
        if instant(x['retrieved_at']) > now or instant(x['start_utc']) >= now:
            raise ValueError('STAGED_SOURCE_AFTER_CUTOFF')
        if not x.get('source_sha256') or not x.get('away_code') or not x.get('home_code'):
            raise ValueError('UNBOUND_STAGED_FINAL')
        a, h = x['away_score'], x['home_score']
        if type(a) is not int or type(h) is not int or min(a,h) < 0 or a == h:
            raise ValueError('INVALID_FINAL_SCORE')
        row = dict(game_id=x['event_id'],date=day,away=normalize_team(x['away_code']),home=normalize_team(x['home_code']),away_score=a,home_score=h,source='STAGED_WEB_SPORTS_RESEARCH',source_sha256=x['source_sha256'],retrieved_at=x['retrieved_at'],start_utc=x['start_utc'])
        if row['away'] == row['home']:
            raise ValueError('TEAM_IDENTITY_CONFLICT')
        if row['game_id'] in rows:
            raise ValueError('DUPLICATE_OR_CONFLICTING_STAGED_ID')
        rows[row['game_id']] = row
        new.append(row)
    seen = set()
    for r in new:
        key = (r['date'],r['away'],r['home'],r['start_utc'])
        if key in seen: raise ValueError('DUPLICATE_STAGED_MATCHUP_START')
        seen.add(key)
    counts = collections.Counter(x['date'] for x in rows.values())
    required = [(target-dt.timedelta(days=n)).isoformat() for n in range(1,15)]
    holes = [day for day in required if not counts[day]]
    if holes: raise ValueError('FORM_DATE_HOLES:'+','.join(holes))
    def aggregate(values):
        totals = collections.defaultdict(lambda: [0,0,0])
        for r in values:
            for tm,rf,ra in [(r['away'],r['away_score'],r['home_score']),(r['home'],r['home_score'],r['away_score'])]:
                totals[tm][0]+=rf;totals[tm][1]+=ra;totals[tm][2]+=1
        return {tm:dict(rf=v[0]/v[2],ra=v[1]/v[2],games=v[2]) for tm,v in totals.items()}
    return {'schema':'mlb.current_form.research.v1','target_date':target_date,'built_at':cutoff,'canonical_boundary':boundary,'canonical_rows':len(base),'assimilated_rows':len(new),'rows':list(rows.values()),'teams':aggregate(rows.values()),'before_teams':aggregate(base),'date_counts':dict(sorted(counts.items())),'through_date':max(counts),'trailing_date_holes':holes,'coverage':'DATE_CONTINUITY_VERIFIED; PER_DAY_AUTHORITATIVE_CENSUS_UNVERIFIED','canonical_ledger_modified':False,'canonical_source_sha256':digest(canonical_path),'staged_source_sha256':digest(staged_path),'historical_pregame_eligible':False}
