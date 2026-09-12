import pathlib,json,hashlib
from model import predict
root=pathlib.Path(__file__).parent;run=root/'run';b=json.load(open(run/'bundle.json'));i=json.load(open(run/'inputs.json'))
p,md,td=predict(i['trained_model'],'264','328',i['home_elo'],i['away_elo'],b['event_id'],b['input_sha256'])
assert p==b['projection']
assert md.tobytes()==(run/'full_margin.bin').read_bytes()
assert td.tobytes()==(run/'first_half_total.bin').read_bytes()
for name,expected in json.load(open(run/'manifest.json')).items():
 raw=(run/name).read_bytes();assert len(raw)==expected['bytes'];assert hashlib.sha256(raw).hexdigest()==expected['sha256']
print('PASS: model identity, 2 x 100K exact draws, run manifest')
