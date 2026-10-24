#!/usr/bin/env python3
"""Grade immutable research registrations against two source-bound final feeds."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from models.nfl.contextual.research_grading import grade_event, status


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--store', type=Path, default=ROOT/'data/grading/nfl_qb_margin')
    p.add_argument('--event-id'); p.add_argument('--schedule', type=Path); p.add_argument('--schedule-receipt', type=Path)
    p.add_argument('--official-final', type=Path); p.add_argument('--official-receipt', type=Path)
    a = p.parse_args(); args = [a.event_id, a.schedule, a.schedule_receipt, a.official_final, a.official_receipt]
    if any(args) and not all(args): p.error('All final source paths, receipts and event ID are required')
    if a.event_id:
        grade_event(a.store, a.event_id, a.schedule.read_bytes(), json.loads(a.schedule_receipt.read_text()),
                    a.official_final.read_bytes(), json.loads(a.official_receipt.read_text()))
    print(json.dumps(status(a.store), indent=2))


if __name__ == '__main__': main()
