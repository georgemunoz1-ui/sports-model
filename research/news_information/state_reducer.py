"""Cutoff-specific projection of immutable, explicitly superseding claims."""
from collections import defaultdict
from research.news_information.contracts import digest, parse_utc


def reduce_claims(claims, cutoff):
    at = parse_utc(cutoff)
    if at is None:
        raise ValueError('cutoff required')
    by_id, groups, rejected = {}, defaultdict(list), []
    for c in claims:
        core = {k: v for k, v in c.items() if k != 'claim_id'}
        if c.get('claim_id') != digest(core):
            raise ValueError('claim hash mismatch')
        if c['claim_id'] in by_id:
            continue
        by_id[c['claim_id']] = c
    for cid, c in sorted(by_id.items()):
        key = tuple(c[k] for k in ('league', 'event_id', 'subject_id', 'state_dimension'))
        if not all(isinstance(v, str) and v for v in key):
            raise ValueError('complete claim identity required')
        times = [parse_utc(c[k]) for k in ('retrieved_at_utc', 'effective_at_utc')]
        if c.get('published_at_utc') is not None:
            times.append(parse_utc(c['published_at_utc']))
        if any(t is None for t in times):
            raise ValueError('claim timestamps required')
        if not c.get('evidence_set_hash') or not c.get('source_id'):
            raise ValueError('claim evidence required')
        if max(times) > at:
            rejected.append({'claim_id': cid, 'reason': 'NOT_KNOWN_OR_EFFECTIVE_AT_CUTOFF'})
            continue
        groups[key].append(c)
    states = []
    for key, members in sorted(groups.items()):
        visible = {c['claim_id']: c for c in members}
        superseded, invalid = set(), []
        for c in members:
            prev = c.get('supersedes_claim_id')
            if prev is None:
                continue
            p = visible.get(prev)
            if (p is None or p['source_id'] != c['source_id']
                or p['new_state'] != c['previous_state']
                or parse_utc(p['retrieved_at_utc']) >= parse_utc(c['retrieved_at_utc'])
                or parse_utc(p['effective_at_utc']) > parse_utc(c['effective_at_utc'])):
                invalid.append(c['claim_id'])
            else:
                superseded.add(prev)
        leaves = [c for c in members if c['claim_id'] not in superseded]
        values = sorted({c['new_state'] for c in leaves})
        status = 'INVALID_CHAIN' if invalid else 'CONFLICTING' if len(values) != 1 else 'RESOLVED'
        states.append(dict(zip(('league', 'event_id', 'subject_id', 'state_dimension'), key),
                           status=status, value=values[0] if status == 'RESOLVED' else None,
                           claim_ids=sorted(c['claim_id'] for c in leaves), invalid_claim_ids=invalid))
    return {'cutoff': cutoff, 'states': states, 'excluded': rejected,
            'forecast_adjustment_enabled': False, 'action_authority': 'OFF'}
