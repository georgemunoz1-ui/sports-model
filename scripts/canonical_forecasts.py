#!/usr/bin/env python3
"""Prospective research receipts and append-only scores for supported shared cards.

The original card stays immutable. A receipt proves writer/artifact chronology, not
source authenticity, historical PIT validity, model promotion, or wagering authority.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.canonical_results import verify_result_source
from scripts.register_mlb_calibration import atomic_json, registry_lock, dt, utcnow, digest
from scripts.accumulate_mlb_calibration import finite_prob, home_probability, save_ledger, load_ledger

LEAGUES = {'NFL', 'CFB', 'WNBA', 'NBA', 'NHL'}
SCHEMA = 'canonical.prospective_research.v1'


def draw_relative(row):
    """Known child semantics choose a fixed path; never follow arbitrary metadata."""
    suffix = '.semantic-v2' if row.get('identity_semantics') == 'market_blind_numeric.v2' else ''
    return Path('draws') / (str(row['event_id']).replace(':', '_') + suffix) / 'winner_draws.npy'


def selection_attachment(path, card_sha, registered_at):
    from pipelines.cards.selection_integration import verify_sidecar
    if not path.is_file():
        return None
    raw = path.read_bytes()
    document = json.loads(raw)
    verify_sidecar(document, source_card_sha256=card_sha)
    if document['execution_mode'] != 'UNREGISTERED_RESEARCH':
        raise ValueError('RETROSPECTIVE_SELECTION_CANNOT_REGISTER')
    if dt(document['created_at_utc']) > dt(registered_at):
        raise ValueError('SELECTION_SIDECAR_AFTER_REGISTRATION')
    for decision in document['decisions']:
        if dt(decision['decision_at_utc']) > dt(document['created_at_utc']):
            raise ValueError('SELECTION_DECISION_AFTER_SIDECAR_CREATION')
        if dt(document['created_at_utc']) >= dt(decision['target']['starts_at_utc']) and decision['decision_class'] != 'BLOCKED':
            raise ValueError('POST_START_SELECTION_NOT_BLOCKED')
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'raw': raw, 'document': document}


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def firewall(value):
    """Reject asserted authority/market use at every nested layer."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {'action_authority', 'actionable', 'market_input', 'market_features_used', 'market_overlay_enabled'} and item:
                raise ValueError('MARKET_ACTION_FIREWALL_FAIL')
            firewall(item)
    elif isinstance(value, list):
        for item in value:
            firewall(item)


def card_rows(card, registered_at):
    league = card.get('league')
    if league not in LEAGUES:
        raise ValueError('UNSUPPORTED_LEAGUE')
    firewall(card)
    pit = card.get('pit_provenance') or {}
    if pit.get('pit_status') not in {'PIT_ORDERED', 'PIT_ALIGNED'}:
        raise ValueError('SOURCE_CHRONOLOGY_UNVERIFIED')
    cutoff = dt(card['requested_as_of_utc'])
    generated = dt(card['generated_at_utc'])
    registered = dt(registered_at)
    sources = pit.get('source_fetches') or []
    if not sources:
        raise ValueError('SOURCE_RECEIPTS_REQUIRED')
    stamps = [dt(s['fetched_at_utc']) for s in sources]
    if max(stamps) != dt(pit['max_source_timestamp_utc']) or not max(stamps) <= cutoff <= generated <= registered:
        raise ValueError('REGISTRATION_CHRONOLOGY_INVALID')
    rows, seen = [], set()
    for row in card.get('forecasts', []):
        if row.get('forecast_status') != 'FORECAST_GENERATED':
            continue
        grading = row.get('grading') or {}
        allowed_reasons = {'REGISTRATION_ATTESTATION_REQUIRED', 'MLB_CALIBRATION_ONLY', 'PIT_STATUS_PIT_ORDERED'}
        if row.get('probability_estimator') == 'MONTE_CARLO_ONLY':
            allowed_reasons.add('HOME_PROBABILITY_UNAVAILABLE')
        if grading.get('eligibility_reason') not in allowed_reasons:
            raise ValueError('FORECAST_INELIGIBLE:' + str(grading.get('eligibility_reason')))
        event = str(row['event_id'])
        model = row.get('model_id') or (row.get('provenance') or {}).get('model_id')
        if not model or not row.get('input_snapshot_hash') or not row.get('model_state_config_hash'):
            raise ValueError('MODEL_INPUT_BINDING_REQUIRED')
        if not row.get('home_team') or not row.get('away_team') or row['home_team'] == row['away_team']:
            raise ValueError('TEAM_IDENTITY_REQUIRED')
        if registered >= dt(row['start_time_utc']):
            raise ValueError('REGISTRATION_NOT_PREGAME:' + event)
        key = identity({'league': league, 'event_id': event, 'model_id': model})
        if key in seen:
            raise ValueError('DUPLICATE_FORECAST_IDENTITY')
        seen.add(key)
        for field in ('analytic_p', 'stochastic_sim_p'):
            if row.get(field) is not None and not finite_prob(row[field]):
                raise ValueError('INVALID_PROBABILITY')
        probabilities = {}
        for estimator, explicit, legacy in [('analytic', 'analytic_p_home', 'analytic_p'), ('simulation', 'stochastic_sim_p_home', 'stochastic_sim_p')]:
            p = home_probability(row, explicit, legacy)
            if p is not None:
                if not finite_prob(p):
                    raise ValueError('INVALID_PROBABILITY')
                probabilities[estimator] = p
        if 'simulation' not in probabilities:
            raise ValueError('SIMULATION_PROBABILITY_REQUIRED')
        if 'analytic' not in probabilities and row.get('probability_estimator') != 'MONTE_CARLO_ONLY':
            raise ValueError('ANALYTIC_PROBABILITY_REQUIRED')
        sim = row.get('simulation') or {}
        binary = sim.get('binary') or sim
        if type(binary.get('count')) is not int or binary['count'] < 1 or not binary.get('sha256') or type(binary.get('seed')) is not int:
            raise ValueError('SIMULATION_IDENTITY_REQUIRED')
        rows.append((key, {'league': league, 'event_id': event, 'model_id': model,
            'model_state_config_hash': row['model_state_config_hash'], 'input_snapshot_hash': row['input_snapshot_hash'],
            'output_hash': identity(row), 'selection_hash': row.get('selection_hash'),
            'home_team': row['home_team'], 'away_team': row['away_team'], 'start_time_utc': row['start_time_utc'],
            'probabilities': probabilities, 'simulation_identity': binary,
            'product': 'home_win_binary', 'tie_policy': 'EXCLUDE_UNSUPPORTED_TIE',
            'unsupported_products': ['cover', 'total'], 'pit_status': pit['pit_status'],
            'source_provenance': 'NOT_INDEPENDENTLY_VERIFIED', 'certified_calibration_eligible': False,
            'evaluation_cohort': 'PROSPECTIVE_RESEARCH_SOURCE_UNVERIFIED', 'predictive_validation': 'NOT_ASSESSED',
            'publication_eligibility': 'NOT_EVALUATED', 'action_authority': False}))
        if row.get('identity_semantics'):
            rows[-1][1]['identity_semantics'] = row['identity_semantics']
    if not rows:
        raise ValueError('NO_GENERATED_FORECASTS')
    return rows


def validate_draws(path, simulation):
    import numpy as np
    draws = np.load(path, allow_pickle=False)
    if draws.ndim != 1 or len(draws) != simulation['count'] or not np.isin(draws, [0, 1]).all():
        raise ValueError('DRAW_COUNT_OR_SUPPORT_MISMATCH')
    if hashlib.sha256(draws.tobytes()).hexdigest() != simulation['sha256']:
        raise ValueError('DRAW_HASH_MISMATCH')
    if float(draws.mean()) != simulation['home_win_probability']:
        raise ValueError('DRAW_PROBABILITY_MISMATCH')
    return digest(path)


def register(card_path, root, run_id, artifact):
    root, card_path = Path(root), Path(card_path)
    card = json.loads(card_path.read_text())
    sha = digest(card_path)
    with registry_lock(root / 'registry.json'):
        path = root / 'registry.json'
        registry = json.loads(path.read_text()) if path.exists() else {'schema': SCHEMA, 'forecasts': {}}
        # Exact retry uses the original writer clock, never manufactures a new timestamp.
        entries = [r for r in registry['forecasts'].values() if r['card_sha256'] == sha and r['run_id'] == run_id]
        now = entries[0]['registered_at_utc'] if entries else utcnow()
        rows = card_rows(card, now)
        attachment = selection_attachment(card_path.parent / 'research_selection/decisions.json', sha, now)
        if not artifact.get('id') or not artifact.get('digest') or artifact.get('run_id') != run_id:
            raise ValueError('ARTIFACT_BINDING_REQUIRED')
        observed = dt(artifact['created_at'])
        if not dt(card['generated_at_utc']) <= observed <= dt(now):
            raise ValueError('ARTIFACT_CHRONOLOGY_INVALID')
        draw_paths = {}
        for key, row in rows:
            source = card_path.parent / draw_relative(row)
            row['draw_file_sha256'] = validate_draws(source, row['simulation_identity'])
            if abs(row['probabilities']['simulation'] - row['simulation_identity']['home_win_probability']) > 1e-12:
                raise ValueError('CARD_DRAW_PROBABILITY_MISMATCH')
            draw_paths[key] = source
        added, skipped = [], []
        for key, row in rows:
            prior = registry['forecasts'].get(key)
            if prior:
                # First pregame forecast per event/model is canonical. Later refreshes
                # cannot replace it or increase the evaluation denominator.
                verify_receipt(root, prior)
                skipped.append(key)
                continue
            row.update(receipt_id=key, card_sha256=sha, card_date=card['card_date'], run_id=run_id,
                       artifact=artifact, registered_at_utc=now)
            if attachment:
                matches = [d for d in attachment['document']['decisions'] if d['target']['event_id'] == row['event_id'] and d['target']['product'] == 'winner']
                if len(matches) != 1:
                    raise ValueError('EXACT_WINNER_SELECTION_SIDECAR_REQUIRED')
                if dt(attachment['document']['created_at_utc']) >= dt(matches[0]['target']['starts_at_utc']):
                    raise ValueError('SELECTION_REGISTRATION_NOT_PREGAME')
                row['selection_sidecar_sha256'] = attachment['sha256']
                row['selection_decision_id'] = matches[0]['decision_id']
            registry['forecasts'][key] = row
            added.append(key)
        frozen = root / 'cards' / (sha + '.json')
        if added:
            frozen.parent.mkdir(parents=True, exist_ok=True)
            if frozen.exists() and digest(frozen) != sha:
                raise ValueError('FROZEN_CARD_CONFLICT')
            if not frozen.exists():
                with frozen.open('xb') as handle:
                    handle.write(card_path.read_bytes()); handle.flush(); os.fsync(handle.fileno())
            draw_root = root / 'draws'
            draw_root.mkdir(parents=True, exist_ok=True)
            for key in added:
                row = registry['forecasts'][key]
                target = draw_root / (row['draw_file_sha256'] + '.npy')
                if target.exists() and digest(target) != row['draw_file_sha256']:
                    raise ValueError('FROZEN_DRAW_CONFLICT')
                if not target.exists():
                    with target.open('xb') as output:
                        output.write(draw_paths[key].read_bytes()); output.flush(); os.fsync(output.fileno())
            if attachment:
                selections = root / 'selections'
                selections.mkdir(parents=True, exist_ok=True)
                target = selections / (attachment['sha256'] + '.json')
                if target.exists() and digest(target) != attachment['sha256']:
                    raise ValueError('FROZEN_SELECTION_CONFLICT')
                if not target.exists():
                    with target.open('xb') as output:
                        output.write(attachment['raw']); output.flush(); os.fsync(output.fileno())
            atomic_json(path, registry)
        return {'status': 'REGISTERED' if added else 'ALREADY_REGISTERED', 'added': added, 'existing': skipped,
                'action_authority': False}


def verify_receipt(root, receipt):
    path = Path(root) / 'cards' / (receipt['card_sha256'] + '.json')
    if digest(path) != receipt['card_sha256']:
        raise ValueError('REGISTERED_CARD_HASH_MISMATCH')
    card = json.loads(path.read_text())
    expected = dict(card_rows(card, receipt['registered_at_utc']))[receipt['receipt_id']]
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError('RECEIPT_IDENTITY_MISMATCH:' + key)
    draw_path = Path(root) / 'draws' / (receipt['draw_file_sha256'] + '.npy')
    if validate_draws(draw_path, receipt['simulation_identity']) != receipt['draw_file_sha256']:
        raise ValueError('REGISTERED_DRAW_HASH_MISMATCH')
    artifact = receipt['artifact']
    if not artifact.get('id') or not artifact.get('digest') or artifact['run_id'] != receipt['run_id']:
        raise ValueError('ARTIFACT_BINDING_REQUIRED')
    if not dt(card['generated_at_utc']) <= dt(artifact['created_at']) <= dt(receipt['registered_at_utc']):
        raise ValueError('ARTIFACT_CHRONOLOGY_INVALID')
    if receipt.get('selection_sidecar_sha256'):
        attachment = selection_attachment(Path(root) / 'selections' / (receipt['selection_sidecar_sha256'] + '.json'), receipt['card_sha256'], receipt['registered_at_utc'])
        if not attachment or attachment['sha256'] != receipt['selection_sidecar_sha256']:
            raise ValueError('REGISTERED_SELECTION_HASH_MISMATCH')
        matches = [d for d in attachment['document']['decisions'] if d['decision_id'] == receipt.get('selection_decision_id')]
        if len(matches) != 1 or matches[0]['target']['event_id'] != receipt['event_id'] or matches[0]['target']['product'] != 'winner':
            raise ValueError('REGISTERED_SELECTION_TARGET_MISMATCH')


def selection_grades(root, registry, result_map):
    """Compute actual registered sidecar settlements, independently of winner grades.

    NO_PICK is retained in the population and never credited as a correct pick.
    Unsupported/absent sidecars receive no invented or retrospective selection.
    """
    from pipelines.cards.selection_integration import settle_target
    ledger = load_ledger(root / 'selection_ledger.jsonl')
    existing = {x['grade_id']: x for x in ledger}
    additions = []
    for receipt in registry['forecasts'].values():
        if not receipt.get('selection_sidecar_sha256'):
            continue
        result = result_map.get((receipt['league'], receipt['event_id']))
        if not result or result.get('status') != 'FINAL':
            continue
        verify_result_source(result)
        if (result['home_team'], result['away_team']) != (receipt['home_team'], receipt['away_team']) or dt(result['start_time_utc']) != dt(receipt['start_time_utc']):
            raise ValueError('SELECTION_RESULT_IDENTITY_MISMATCH')
        if dt(result['fetched_at_utc']) < dt(receipt['start_time_utc']):
            raise ValueError('SELECTION_RESULT_CAPTURE_NOT_POST_START')
        attachment = selection_attachment(root / 'selections' / (receipt['selection_sidecar_sha256'] + '.json'), receipt['card_sha256'], receipt['registered_at_utc'])
        decision = next(d for d in attachment['document']['decisions'] if d['decision_id'] == receipt['selection_decision_id'])
        outcome = settle_target(decision['target'], result['home_score'], result['away_score'],
                                score_period=result.get('score_period'))
        gid = identity({'receipt_id': receipt['receipt_id'], 'decision_id': decision['decision_id']})
        immutable = {'grade_id': gid, 'forecast_receipt_id': receipt['receipt_id'], 'event_id': receipt['event_id'],
            'decision_id': decision['decision_id'], 'target_id': decision['target_id'], 'target': decision['target'],
            'procedure_id': decision['procedure_id'], 'selector_config_id': decision['selector_config_id'],
            'selection_sidecar_sha256': receipt['selection_sidecar_sha256'],
            'decision_class': decision['decision_class'], 'selection_decision': decision['selection_decision'],
            'outcome': outcome, 'raw_probability': decision['raw_probability'],
            'raw_probability_basis': decision.get('raw_probability_basis', 'unconditional_win'),
            'selection_probability': decision['selection_probability'],
            'selected_outcome': outcome if decision['decision_class'] == 'SHADOW_SELECTED' else None,
            'blocking_reasons': decision['blocking_reasons'], 'home_score': result['home_score'],
            'away_score': result['away_score'], 'publication_allowed': False, 'action_authority': False}
        if gid in existing:
            if any(existing[gid].get(k) != v for k, v in immutable.items()):
                raise ValueError('IMMUTABLE_SELECTION_GRADE_CONFLICT')
        else:
            additions.append({**immutable, 'result_source': result, 'graded_at_utc': utcnow()})
    return ledger, additions


def grade(root, results):
    """Normalized provider results are observations, never instructions or forecasts."""
    root = Path(root)
    with registry_lock(root / 'registry.json'):
        registry_path = root / 'registry.json'
        registry = json.loads(registry_path.read_text()) if registry_path.exists() else {'forecasts': {}}
        ledger_path = root / 'ledger.jsonl'
        ledger = load_ledger(ledger_path)
        existing = {r['grade_id']: r for r in ledger}
        result_map = {}
        for r in results:
            key = (r['league'], str(r['event_id']))
            if key in result_map:
                raise ValueError('DUPLICATE_RESULT')
            result_map[key] = r
        additions, pending, excluded = [], [], []
        for key, receipt in registry['forecasts'].items():
            if key != receipt['receipt_id']:
                raise ValueError('RECEIPT_KEY_MISMATCH')
            verify_receipt(root, receipt)
            result = result_map.get((receipt['league'], receipt['event_id']))
            if not result or result.get('status') != 'FINAL':
                if key not in existing:
                    pending.append(key)
                continue
            verify_result_source(result)
            if dt(result['start_time_utc']) != dt(receipt['start_time_utc']):
                raise ValueError('RESULT_START_TIME_RECONCILIATION_REQUIRED')
            if (result['home_team'], result['away_team']) != (receipt['home_team'], receipt['away_team']):
                raise ValueError('RESULT_TEAM_MISMATCH')
            scores = [result['home_score'], result['away_score']]
            if any(isinstance(s, bool) or not isinstance(s, int) or s < 0 for s in scores):
                raise ValueError('INVALID_FINAL_SCORE')
            if not result.get('source_sha256') or not result.get('source_url') or dt(result['fetched_at_utc']) < dt(receipt['start_time_utc']):
                raise ValueError('RESULT_SOURCE_BINDING_REQUIRED')
            if scores[0] == scores[1]:
                if key in existing:
                    raise ValueError('IMMUTABLE_GRADE_CONFLICT:TIE_CORRECTION')
                excluded.append({'receipt_id': key, 'reason': 'UNSUPPORTED_TIE'})
                continue
            y = int(scores[0] > scores[1])
            immutable = {'grade_id': key, 'receipt_id': key, 'league': receipt['league'], 'event_id': receipt['event_id'],
                'model_id': receipt['model_id'], 'model_state_config_hash': receipt['model_state_config_hash'],
                'input_snapshot_hash': receipt['input_snapshot_hash'], 'output_hash': receipt['output_hash'],
                'card_sha256': receipt['card_sha256'], 'product': receipt['product'], 'evaluation_cohort': receipt['evaluation_cohort'],
                'certified_calibration_eligible': False, 'home_score': scores[0], 'away_score': scores[1],
                'home_won': y, 'probabilities': receipt['probabilities'], 'scores': {}}
            for estimator, p in receipt['probabilities'].items():
                clipped = min(1 - 1e-12, max(1e-12, p))
                immutable['scores'][estimator] = {'brier': (p-y)**2, 'log_loss': -(y*math.log(clipped)+(1-y)*math.log(1-clipped))}
            if key in existing:
                if any(existing[key].get(k) != v for k, v in immutable.items()):
                    raise ValueError('IMMUTABLE_GRADE_CONFLICT')
                continue
            additions.append({**immutable, 'result_source': result, 'graded_at_utc': utcnow(), 'action_authority': False})
        # Validate entire batch before append. save_ledger enforces immutable prefix.
        selection_ledger, selection_additions = selection_grades(root, registry, result_map)
        if additions:
            save_ledger(ledger_path, ledger + additions)
        if selection_additions:
            save_ledger(root / 'selection_ledger.jsonl', selection_ledger + selection_additions)
        all_rows = ledger + additions
        groups = {}
        for row in all_rows:
            for estimator, scores in row['scores'].items():
                group = '|'.join((row['league'], row['model_id'], row['model_state_config_hash'], row['product'], estimator))
                g = groups.setdefault(group, {'n': 0, 'brier_sum': 0., 'log_loss_sum': 0.})
                g['n'] += 1
                g['brier_sum'] += scores['brier']; g['log_loss_sum'] += scores['log_loss']
        summary = {'schema': SCHEMA, 'registered_count': len(registry['forecasts']), 'graded_count': len(all_rows),
                   'certified_calibration_count': 0, 'evaluation_cohort': 'PROSPECTIVE_RESEARCH_SOURCE_UNVERIFIED',
                   'groups': {k: {'n': g['n'], 'brier': g['brier_sum']/g['n'], 'log_loss': g['log_loss_sum']/g['n']} for k,g in groups.items()},
                   'action_authority': False, 'predictive_validation': 'NOT_ASSESSED'}
        if registry_path.exists():
            atomic_json(root / 'summary.json', summary)
        return {'status': 'GRADED' if additions else ('PENDING_RESULTS' if pending else 'NO_NEW_GRADES'),
                'registered_count': len(registry['forecasts']), 'added_count': len(additions),
                'selection_added_count': len(selection_additions), 'selection_graded_count': len(selection_ledger) + len(selection_additions),
                'pending': pending, 'excluded': excluded, 'action_authority': False}


def verified_artifact(card, run_id, artifact_id):
    repo = os.environ['GITHUB_REPOSITORY']
    meta = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/actions/artifacts/{artifact_id}'], text=True))
    if meta.get('expired') or meta['workflow_run']['id'] != run_id:
        raise ValueError('ARTIFACT_RUN_MISMATCH_OR_EXPIRED')
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(['gh', 'run', 'download', str(run_id), '--repo', repo, '--name', meta['name'], '--dir', work], check=True)
        matches = list(Path(work).rglob('diagnostic_card.json'))
        if len(matches) != 1 or digest(matches[0]) != digest(card):
            raise ValueError('UPLOADED_CARD_MISMATCH')
        for row in json.loads(Path(card).read_text()).get('forecasts', []):
            if row.get('forecast_status') == 'FORECAST_GENERATED':
                relative = draw_relative(row)
                if digest(matches[0].parent / relative) != digest(Path(card).parent / relative):
                    raise ValueError('UPLOADED_DRAW_MISMATCH')
        relative = Path('research_selection/decisions.json')
        if (Path(card).parent / relative).exists() and digest(matches[0].parent / relative) != digest(Path(card).parent / relative):
            raise ValueError('UPLOADED_SELECTION_SIDECAR_MISMATCH')
    return {**{k: meta[k] for k in ('id', 'name', 'digest', 'created_at')}, 'run_id': run_id,
            'code_commit': meta['workflow_run']['head_sha'], 'repository': repo}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['register', 'grade'])
    p.add_argument('--root', type=Path, default=Path('data/grading/canonical'))
    p.add_argument('--card', type=Path)
    p.add_argument('--run-id', type=int)
    p.add_argument('--artifact-id', type=int)
    p.add_argument('--results', type=Path)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    if a.operation == 'register':
        if not a.card or not a.run_id or not a.artifact_id:
            raise ValueError('REGISTER_REQUIRES_CARD_RUN_AND_UPLOADED_ARTIFACT')
        report = register(a.card, a.root, a.run_id, verified_artifact(a.card, a.run_id, a.artifact_id))
    else:
        if not a.results:
            p.error('grade requires --results containing normalized source-bound outcomes')
        report = grade(a.root, json.loads(a.results.read_text()))
    atomic_json(a.report, report)
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        if '--report' in sys.argv:
            atomic_json(Path(sys.argv[sys.argv.index('--report') + 1]), {'status': 'BLOCKED', 'reason': str(exc), 'action_authority': False})
        raise
