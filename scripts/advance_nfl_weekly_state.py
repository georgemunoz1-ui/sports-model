#!/usr/bin/env python3
"""Initialize or advance the immutable NFL research state store from captured bytes."""
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.weekly_state import capture, initialize, advance


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--store', type=Path, required=True)
    p.add_argument('--model', type=Path, default=ROOT/'data/nfl/contextual_v1/model_packed.json')
    p.add_argument('--schedule', type=Path, required=True)
    p.add_argument('--schedule-receipt', type=Path, required=True)
    p.add_argument('--seed', type=Path, help='Historical Week1 reconstructed state; initialization only')
    p.add_argument('--parent-id')
    p.add_argument('--seed-id', help='Independently retained seed ID, not a packet-provided assertion')
    p.add_argument('--pbp', type=Path)
    p.add_argument('--pbp-receipt', type=Path)
    p.add_argument('--week', type=int)
    a = p.parse_args()
    model = load_artifact(a.model)
    schedule = capture(a.schedule, json.loads(a.schedule_receipt.read_text()))
    cutoff = dt.datetime.now(dt.timezone.utc).isoformat()
    if a.seed:
        if any((a.parent_id, a.seed_id, a.pbp, a.pbp_receipt, a.week)): p.error('Seed initialization cannot include update arguments')
        key = initialize(a.store, json.loads(a.seed.read_text()), schedule, model, cutoff)
    else:
        if not all((a.parent_id, a.seed_id, a.pbp, a.pbp_receipt, a.week)): p.error('Update requires parent ID, seed ID, PBP, receipt and week')
        key = advance(a.store, a.parent_id, a.seed_id, model, schedule,
                      capture(a.pbp, json.loads(a.pbp_receipt.read_text())), a.week, cutoff)
    print(json.dumps({'state_id': key, 'store': str(a.store.resolve()), 'research_only': True,
                      'action_authority': False, 'cutoff_utc': cutoff}))


if __name__ == '__main__': main()
