"""Write a new personnel review next to, and hash-bound to, an existing research card."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipelines.cards.personnel_review import bind_grades, build_review, load_pregame_review
from research.personnel_events import load_observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card', required=True, type=Path)
    evidence = parser.add_mutually_exclusive_group()
    evidence.add_argument('--personnel-events', type=Path, help='Hash-bound personnel source manifest')
    evidence.add_argument('--pregame-review', type=Path, help='Carry the exact personnel review to a later assessment')
    parser.add_argument('--pregame-review-sha256', help='Optional previously retained hash of the prior review file')
    parser.add_argument('--grades', type=Path, help='Existing descriptive board or CBB research grades')
    parser.add_argument('--output', required=True, type=Path, help='New JSON file')
    args = parser.parse_args()
    if args.pregame_review_sha256 and not args.pregame_review:
        parser.error('--pregame-review-sha256 requires --pregame-review')
    raw = args.card.read_bytes()
    card = json.loads(raw)
    card_sha = hashlib.sha256(raw).hexdigest()
    if args.pregame_review:
        if not args.grades:
            parser.error('--pregame-review requires --grades')
        report, source_sha = load_pregame_review(args.pregame_review, card, card_sha, args.pregame_review_sha256)
        report['pregame_review_file_sha256'] = source_sha
    else:
        observations = load_observations(args.personnel_events) if args.personnel_events else ()
        report = build_review(card, observations)
        report['parent_file_sha256'] = card_sha
        report['review_created_at_utc'] = datetime.now(timezone.utc).isoformat()
        report['registration_status'] = 'NO_VERIFIED_PREGAME_REGISTRATION'
    if args.grades:
        grade_raw = args.grades.read_bytes()
        bind_grades(report, json.loads(grade_raw), card_sha)
        report['grades_file_sha256'] = hashlib.sha256(grade_raw).hexdigest()
        report['postgame_assessed_at_utc'] = datetime.now(timezone.utc).isoformat()
        report['review_source'] = 'EXISTING_REVIEW_FILE' if args.pregame_review else 'REVIEW_COMPUTED_DURING_ASSESSMENT'
    data = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n'
    with args.output.open('x') as stream:
        stream.write(data)
    return 0


if __name__ == '__main__':
    sys.exit(main())
