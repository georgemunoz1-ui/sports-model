import hashlib,json,unittest
from test_nfl_starter_adjudication import fixture
from models.nfl.contextual.starter_adjudication import apply

class TimezoneBinding(unittest.TestCase):
    def case(self, day, clock, source):
        games,pbp,r=fixture();games['gameday']=day;games['gametime']=clock
        j=json.loads(r['evidence']['text']);j['header']['competitions'][0]['date']=source
        r['evidence']['text']=json.dumps(j);r['evidence']['receipt']['sha256']=hashlib.sha256(r['evidence']['text'].encode()).hexdigest()
        return games,pbp,r
    def test_evening_utc_rollover_preserves_raw_starter(self):
        g,p,r=self.case('2026-09-20','20:15','2026-09-21T00:15:00Z')
        self.assertEqual(apply(g,p,[r],r['reviewed_at_utc']).iloc[0].home_qb_id,'new')
        self.assertEqual(g.iloc[0].home_qb_id,'old')
    def test_eastern_wrong_day_refused(self):
        g,p,r=self.case('2026-09-20','20:15','2026-09-20T00:15:00Z')
        with self.assertRaisesRegex(ValueError,'ADJUDICATION_DATE_BINDING'):apply(g,p,[r],r['reviewed_at_utc'])
    def test_right_date_wrong_time_refused(self):
        g,p,r=self.case('2026-09-20','20:15','2026-09-21T01:15:00Z')
        with self.assertRaisesRegex(ValueError,'ADJUDICATION_KICKOFF_BINDING'):apply(g,p,[r],r['reviewed_at_utc'])
    def test_standard_time_uses_zone_database(self):
        g,p,r=self.case('2026-12-03','20:15','2026-12-04T01:15:00Z')
        self.assertEqual(apply(g,p,[r],r['reviewed_at_utc']).iloc[0].home_active_qb_id,'new')
