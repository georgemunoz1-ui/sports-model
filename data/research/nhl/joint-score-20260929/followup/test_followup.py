import copy,hashlib
import pytest
from validate_personnel import validate
BASE={'event_id':'NHL:1','player_id':'p','team_id':'t','status':'CONFIRMED_STARTER','effective_at_utc':'2026-09-29T20:00:00Z','source_published_at_utc':'2026-09-29T20:00:00Z','retrieved_at_utc':'2026-09-29T20:01:00Z','reviewed_at_utc':'2026-09-29T20:02:00Z','source_url':'https://www.nhl.com/team/news/test','raw_sha256':hashlib.sha256(b'evidence').hexdigest(),'evidence_pointer':'paragraph 3','reviewer':'agent'}
def test_valid_is_not_model_assimilation():
 assert validate(BASE,b'evidence','2026-09-29T21:00:00Z','NHL:1')['used_as_model_input']is False
@pytest.mark.parametrize('field,value', [('status','PROJECTED'),('status','POST_START_ACTUAL'),('source_published_at_utc',None),('reviewed_at_utc','2026-09-29T21:01:00Z'),('event_id','NHL:2'),('raw_sha256','wrong'),('source_url','https://example.org/a'),('effective_at_utc','2026-09-29T20:00:00'),('evidence_pointer','')])
def test_invalid(field,value):
 r=copy.deepcopy(BASE);r[field]=value
 with pytest.raises(ValueError):validate(r,b'evidence','2026-09-29T21:00:00Z','NHL:1')
