"""Explicit promotion-independent input contract for a future personnel challenger."""
import datetime as dt, hashlib,urllib.parse

def utc(value):
 d=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
 if d.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
 return d.astimezone(dt.timezone.utc)
def validate(record,raw,cutoff,event_id):
 if record['event_id']!=event_id:raise ValueError('EVENT_MISMATCH')
 if hashlib.sha256(raw).hexdigest()!=record['raw_sha256']:raise ValueError('SOURCE_HASH_MISMATCH')
 for k in ['effective_at_utc','source_published_at_utc','retrieved_at_utc','reviewed_at_utc']:
  if not record.get(k):raise ValueError('MISSING_'+k)
  if utc(record[k])>=utc(cutoff):raise ValueError('POST_CUTOFF_'+k)
 if not record.get('evidence_pointer')or not record.get('reviewer'):raise ValueError('MANUAL_SOURCE_REVIEW_REQUIRED')
 host=urllib.parse.urlparse(record['source_url']).hostname
 if host not in ['www.nhl.com','nhl.com','api-web.nhle.com']:raise ValueError('OFFICIAL_SOURCE_REQUIRED')
 if record.get('status')not in ['CONFIRMED_STARTER','ACTIVE_CONFIRMED','OUT_CONFIRMED']:raise ValueError('UNCONFIRMED_PERSONNEL')
 if not all(record.get(k)for k in ['player_id','team_id']):raise ValueError('PLAYER_TEAM_ID_REQUIRED')
 return {'contract_valid':True,'used_as_model_input':False,'numerical_effect':None}
