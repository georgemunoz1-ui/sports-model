#!/usr/bin/env python3
"""One command: canonical adapter, all model arms, binary and score simulations."""
import argparse,datetime as dt,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pipelines.cards.adapters import nfl
from models.nfl.contextual.runtime import run,persist_run


def persist_replay(folder, bundle, winner, scores, captured_package):
    """Record actual execution now; never call the prospective artifact writer."""
    import hashlib
    import numpy as np
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    created = dt.datetime.now(dt.timezone.utc).isoformat()
    receipt = {'schema': 'nfl.retrospective_execution.v1', 'created_at_utc': created,
        'execution_mode': 'RETROSPECTIVE_DIAGNOSTIC', 'information_cutoff_utc': bundle['cutoff_utc'],
        'captured_package_sha256': hashlib.sha256(json.dumps(captured_package, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'prospective_registration_verified': False, 'canonical_prospective_eligible': False,
        'publication_allowed': False, 'action_authority': False, 'wagering_status': 'OFF'}
    with (folder / 'forecast.json').open('x') as stream:
        json.dump(bundle, stream, indent=2, allow_nan=False)
    np.save(folder / 'winner_draws.npy', winner, allow_pickle=False)
    if scores is not None:
        np.save(folder / 'score_draws.npy', scores, allow_pickle=False)
    with (folder / 'execution_receipt.json').open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
    with (folder / 'manifest.json').open('x') as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
    return receipt

def main():
    p=argparse.ArgumentParser();p.add_argument('--date',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--simulations',type=int,default=100000);p.add_argument('--model-id');p.add_argument('--mode',default='research_pregame');p.add_argument('--market-packet',type=Path);p.add_argument('--live-packet',type=Path);p.add_argument('--event-id');p.add_argument('--home-spread',type=float,action='append',help='Optional downstream full-game spread calibration, HOME handicap orientation');p.add_argument('--halftime-artifact',type=Path,help='Explicit fitted halftime/joint research artifact; emits a separate model output');p.add_argument('--weekly-state-store',type=Path);p.add_argument('--weekly-state-id');p.add_argument('--distribution-research-config',type=Path,help='Separate hash-bound margin/total research child; does not require or replace combined-arm calibration');p.add_argument('--disclosures',type=Path,help='Presentation-only event scenarios and dependence evidence; requires --event-id');p.add_argument('--identity-semantics',choices=['legacy.v1','market_blind_numeric.v2'],default='market_blind_numeric.v2');p.add_argument('--selection-config',type=Path,help='Frozen selector config; absent config produces diagnostic NO_PICK');p.add_argument('--replay-cutoff-utc',help='Explicit retained-package replay, never prospective registration');a=p.parse_args()
    if a.disclosures and (not a.event_id or a.mode=='live'):p.error('Disclosure packets require a single pregame --event-id')
    if a.distribution_research_config and a.mode=='live':p.error('Distribution research supports pregame only')
    if bool(a.weekly_state_store)!=bool(a.weekly_state_id):p.error('Both weekly-state store and ID are required')
    if a.weekly_state_store and a.mode=='live':p.error('Weekly state is a pregame input')
    if (a.home_spread or a.halftime_artifact) and a.model_id is None:p.error('Spread/halftime diagnostics require an explicit --model-id; the selected QB winner model has no joint score simulator')
    if a.halftime_artifact and (a.mode!='research_pregame' or (a.model_id is not None and a.model_id!='nfl.integrated_context.combined.v1.research')):raise ValueError('HALFTIME_REQUIRES_COMBINED_FOOTBALL_FEATURE_SOURCE')
    if a.home_spread and (a.mode!='research_pregame' or (a.model_id is not None and a.model_id!='nfl.integrated_context.combined.v1.research')):raise ValueError('SPREAD_CALIBRATION_REQUIRES_COMBINED_FOOTBALL_ARM')
    fitted=nfl.mode_artifact(a.mode) if a.mode!='research_pregame' else None
    market=json.loads(a.market_packet.read_text()) if a.market_packet else None
    live=json.loads(a.live_packet.read_text()) if a.live_packet else None
    default_id=fitted['model_id'] if fitted is not None else json.loads((nfl.DATA/'runtime.json').read_text())['default_research_model']
    cutoff=a.replay_cutoff_utc or dt.datetime.now(dt.timezone.utc).isoformat()
    if a.replay_cutoff_utc:
        from models.nfl.contextual.recovered_inference import utc
        if a.mode != 'research_pregame' or utc(cutoff) > dt.datetime.now(dt.timezone.utc):p.error('Replay requires past cutoff and independent research_pregame mode')
    events=nfl.load_schedule(a.date,cutoff)
    if a.event_id:
        events=[e for e in events if e['event_id']==a.event_id]
        if not events:raise ValueError('EVENT_NOT_IN_CAPTURED_SCHEDULE')
    if a.home_spread and len(events)!=1:raise ValueError('SPREAD_OVERLAY_REQUIRES_SINGLE_EVENT_SELECTION')
    context=nfl.build_context(events,cutoff,mode=a.mode)
    distribution_incomplete=False
    for e in events:
        packet={'base':None,'context':None} if a.mode=='live' else context['package']['event_inputs'][e['event_id']]
        if a.weekly_state_store:
            from models.nfl.contextual.weekly_state import bind_packet
            packet=bind_packet(packet,context['model'],e,cutoff,a.weekly_state_store,a.weekly_state_id)
        market_for_event=market.get('event_packets',{}).get(e['event_id']) if market and 'event_packets' in market else market
        live_for_event=live.get('event_packets',{}).get(e['event_id']) if live and 'event_packets' in live else live
        from models.nfl.contextual.week2 import applies,policy
        if a.mode=='research_pregame' and a.model_id is None and applies(packet['base'],e):default_id=policy()['default_reference_model']
        result,win,scores=run(context['model'],context['recovered'],packet['base'],packet['context'],e,cutoff,a.simulations,model_id=default_id if a.model_id is None else a.model_id,mode=a.mode,mode_artifact=fitted,market=market_for_event,live_state=live_for_event)
        if a.identity_semantics != 'legacy.v1':
            from pipelines.cards.semantic_identity import reidentify_nfl_run
            result,win,scores=reidentify_nfl_run(context['model'],e,cutoff,result,win,scores,semantics=a.identity_semantics)
        if a.replay_cutoff_utc:
            registration=persist_replay(a.output/e['event_id'],result,win,scores,context['package'])
        else:
            persist_run(a.output/e['event_id'],result,win,scores,json.loads((nfl.ROOT/'data/nfl/modes_v1/design.json').read_text()) if fitted is not None else context['model']['design'])
            registration=json.loads((a.output/e['event_id']/'registration.jsonl').read_text())
        from pipelines.cards.selection_integration import nfl_selection_card,write_card_selection
        selection_card=nfl_selection_card(result,registration['created_at_utc'])
        selection_source=a.output/e['event_id']/'selection_source_card.json'
        with selection_source.open('x') as handle:json.dump(selection_card,handle,sort_keys=True,indent=2,allow_nan=False)
        selection_config=json.loads(a.selection_config.read_text()) if a.selection_config else None
        selection_report=write_card_selection(selection_source,a.output/e['event_id']/'research_selection',config=selection_config,retrospective=bool(a.replay_cutoff_utc))
        print(json.dumps({'research_selection':selection_report['decision_counts'],'wagering_status':'OFF'}))
        if a.mode!='live':
            from pipelines.cards.distribution_research import nfl_card
            from pipelines.cards.disclosures import write_report,render_md
            disclosures=write_report(nfl_card(result,registration['created_at_utc']),a.output/e['event_id']/'disclosures',a.disclosures)
            distribution_incomplete |= bool(disclosures['errors'])
            print(render_md(disclosures))
        if a.distribution_research_config:
            from pipelines.cards.distribution_research import build,load_config,nfl_card
            try:
                child=build(nfl_card(result,registration['created_at_utc']),load_config(a.distribution_research_config),a.output/e['event_id']/'distribution_research',simulations=a.simulations)
                distribution_incomplete |= any(r['status']!='COMPLETED' for r in child['coverage'])
                print(json.dumps({'distribution_research':child['coverage']},indent=2))
            except (ValueError,KeyError,TypeError,OSError) as exc:
                distribution_incomplete=True
                failure={'status':'FAILED','reason':str(exc),'action_authority':False}
                with (a.output/e['event_id']/'distribution_research_failure.json').open('x') as handle:json.dump(failure,handle,indent=2)
                print(json.dumps({'distribution_research':failure}))
        if a.halftime_artifact:
            from models.nfl.contextual.halftime import run_artifact
            half=run_artifact(a.halftime_artifact,result,a.output/e['event_id']/'halftime_joint',a.simulations)
            print(json.dumps({'halftime_joint':half['simulation_probabilities'],'model_id':half['model_id']},indent=2))
        if a.home_spread:
            from models.nfl.contextual.spread_runtime import persist_overlay
            if a.identity_semantics == 'legacy.v1':
                overlay,calibrated_margins=nfl.calibrate_spreads(result,scores,a.home_spread,n=a.simulations)
            else:
                from pipelines.cards.semantic_identity import build_spread_overlay
                overlay,calibrated_margins=build_spread_overlay(result,scores,a.home_spread,n=a.simulations,semantics=a.identity_semantics)
            persist_overlay(a.output/e['event_id']/'spread_calibration',overlay,calibrated_margins)
            print(json.dumps({'spread_calibration':overlay['contracts']},indent=2))
        print(json.dumps({'event':e['event_id'],'selection_policy':result.get('selection_policy'),'coherence':result.get('coherence'),'assimilation':result.get('assimilation'),'joint_distribution':result.get('joint_distribution'),'independent_head_predictions':result['prediction'],'binary':result['winner_simulation'],'scores':result['score_simulation']},indent=2))
    if distribution_incomplete:raise SystemExit(2)
if __name__=='__main__':main()
