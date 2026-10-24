#!/usr/bin/env python3
"""One command: canonical adapter, all model arms, binary and score simulations."""
import argparse,datetime as dt,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pipelines.cards.adapters import nfl
from models.nfl.contextual.runtime import run
from pipelines.cards.nfl_flip_integration import attach_diagnostic, persist_run


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
    p=argparse.ArgumentParser();p.add_argument('--date',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--simulations',type=int,default=100000);p.add_argument('--model-id');p.add_argument('--mode',default='research_pregame');p.add_argument('--market-packet',type=Path);p.add_argument('--live-packet',type=Path);p.add_argument('--event-id');p.add_argument('--home-spread',type=float,action='append',help='Optional downstream full-game spread calibration, HOME handicap orientation');p.add_argument('--halftime-artifact',type=Path,help='Explicit fitted halftime/joint research artifact; emits a separate model output');p.add_argument('--weekly-state-store',type=Path);p.add_argument('--weekly-state-id');p.add_argument('--distribution-research-config',type=Path,help='Separate hash-bound margin/total research child; does not require or replace combined-arm calibration');p.add_argument('--disclosures',type=Path,help='Presentation-only event scenarios and dependence evidence; requires --event-id');p.add_argument('--identity-semantics',choices=['legacy.v1','market_blind_numeric.v2'],default='market_blind_numeric.v2');p.add_argument('--selection-config',type=Path,help='Frozen selector config; absent config produces diagnostic NO_PICK');p.add_argument('--replay-cutoff-utc',help='Explicit retained-package replay, never prospective registration');p.add_argument('--roster-bundle',type=Path);p.add_argument('--require-roster-aware',action='store_true');p.add_argument('--qb-margin',action='store_true',help='Emit the separately registered QB-only full-game margin research model');p.add_argument('--qb-margin-calibrated',action='store_true',help='Emit the separately registered integer-margin calibration successor');p.add_argument('--comparison-market-packet',type=Path,help='Display-only source snapshot loaded after forecast freeze');p.add_argument('--research-grading-store',type=Path,default=ROOT/'data/grading/nfl_qb_margin');p.add_argument('--margin-model',type=Path,help='Explicit separate selected-QB full-game margin research config');a=p.parse_args()
    from sports.rosters import attach, assess, load_bundle
    roster=load_bundle(a.roster_bundle) if a.roster_bundle else None
    if a.disclosures and (not a.event_id or a.mode=='live'):p.error('Disclosure packets require a single pregame --event-id')
    margin_path=a.margin_model
    margin_loaded=None
    if margin_path is not None:
        if a.mode!='research_pregame':p.error('Selected-QB margin distribution supports research_pregame only')
        from models.nfl.contextual.margin_distribution import load_config
        margin_loaded=load_config(margin_path)
    if a.distribution_research_config and a.mode=='live':p.error('Distribution research supports pregame only')
    qb_margin_requested=a.qb_margin or a.qb_margin_calibrated
    if qb_margin_requested and margin_loaded is not None:p.error('Choose one distinct margin research product per command')
    if margin_loaded is not None and (a.replay_cutoff_utc or a.halftime_artifact or a.model_id not in {None,'nfl.integrated_context.qb.v1.research'}):p.error('Margin child requires a prospective selected-QB full-game parent')
    if a.qb_margin and a.qb_margin_calibrated:p.error('Choose one distinct QB margin model per command')
    if a.comparison_market_packet and a.mode!='research_pregame':p.error('Display-only snapshot belongs to the market-blind research board')
    if qb_margin_requested and a.replay_cutoff_utc:p.error('QB margin registration requires an actual prospective run; replay cannot register research grades')
    if bool(a.weekly_state_store)!=bool(a.weekly_state_id):p.error('Both weekly-state store and ID are required')
    if a.weekly_state_store and a.mode=='live':p.error('Weekly state is a pregame input')
    if ((a.home_spread and margin_loaded is None) or a.halftime_artifact) and a.model_id is None and not qb_margin_requested:p.error('Spread/halftime diagnostics require an explicit --model-id; the selected QB winner model has no joint score simulator')
    if a.halftime_artifact and (a.mode!='research_pregame' or (a.model_id is not None and a.model_id!='nfl.integrated_context.combined.v1.research')):raise ValueError('HALFTIME_REQUIRES_COMBINED_FOOTBALL_FEATURE_SOURCE')
    if a.home_spread and margin_loaded is None and not qb_margin_requested and (a.mode!='research_pregame' or (a.model_id is not None and a.model_id!='nfl.integrated_context.combined.v1.research')):raise ValueError('SPREAD_CALIBRATION_REQUIRES_COMBINED_FOOTBALL_ARM')
    if qb_margin_requested:
        if a.mode!='research_pregame' or a.model_id not in {None,'nfl.integrated_context.qb.v1.research'} or a.halftime_artifact:p.error('QB margin requires the selected QB research arm and full-game-only products')
        from models.nfl.contextual import qb_margin, qb_margin_calibration
        margin_module=qb_margin_calibration if a.qb_margin_calibrated else qb_margin
        margin_module.load_registered()
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
        if a.require_roster_aware:
            coverage=assess('nfl',e,cutoff,roster)
            if not coverage['roster_aware_forecast_eligible']:raise ValueError('ROSTER_AWARE_FORECAST_UNAVAILABLE:'+';'.join(coverage['reasons']))
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
        result=attach_diagnostic(result,context['model'])
        result=attach(result,'nfl',e,cutoff,roster)
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
        margin=margins=None
        if qb_margin_requested:
            margin,margins=margin_module.build(result,n=a.simulations)
            margin_folder=a.output/e['event_id']/('qb_margin_calibrated' if a.qb_margin_calibrated else 'qb_margin')
            margin_module.persist(margin_folder,margin,margins)
            if a.qb_margin and a.home_spread:
                with (a.output/e['event_id']/'qb_margin_comparison.json').open('x') as f:json.dump(margin_module.compare(margin,margins,a.home_spread),f,indent=2)
            from models.nfl.contextual.research_grading import register
            quarterbacks=packet['context']['personnel']['state']['quarterbacks']
            register(a.research_grading_store,margin_folder,result,
                     quarterback_conditions={team:q['id'] for team,q in quarterbacks.items()},home_handicaps=a.home_spread or [])
        if a.mode=='research_pregame' and (qb_margin_requested or a.comparison_market_packet):
            from models.nfl.contextual.research_board import board,persist_board
            # Prices enter only after model, draws, and registration are frozen.
            display=json.loads(a.comparison_market_packet.read_text()) if a.comparison_market_packet else None
            if display and 'event_packets' in display:display=display['event_packets'].get(e['event_id'])
            comparison=board(result,margin,margins,market=display,home_handicaps=a.home_spread or [])
            persist_board(a.output/e['event_id'],comparison)
            print(json.dumps({'market_overlay':comparison['market_overlay'],'cover_probabilities':comparison['spread_rows']},indent=2))
        if margin_loaded is not None:
            from models.nfl.contextual.margin_distribution import build as build_margin, persist as persist_margin
            try:
                margin,margin_draws=build_margin(result,margin_loaded,a.home_spread,n=a.simulations)
                persist_margin(a.output/e['event_id']/'margin_distribution',margin,margin_draws)
                print(json.dumps({'margin_distribution':margin['contracts'],'model_id':margin['model_id'],'mode':margin['mode']},indent=2))
            except (ValueError,KeyError,TypeError,OSError) as exc:
                distribution_incomplete=True
                failure={'status':'FAILED','reason':str(exc),'action_authority':False}
                with (a.output/e['event_id']/'margin_distribution_failure.json').open('x') as handle:json.dump(failure,handle,indent=2)
                print(json.dumps({'margin_distribution':failure}))
        if a.home_spread and margin_loaded is None and not qb_margin_requested:
            from models.nfl.contextual.spread_runtime import persist_overlay
            if a.identity_semantics == 'legacy.v1':
                overlay,calibrated_margins=nfl.calibrate_spreads(result,scores,a.home_spread,n=a.simulations)
            else:
                from pipelines.cards.semantic_identity import build_spread_overlay
                overlay,calibrated_margins=build_spread_overlay(result,scores,a.home_spread,n=a.simulations,semantics=a.identity_semantics)
            persist_overlay(a.output/e['event_id']/'spread_calibration',overlay,calibrated_margins)
            print(json.dumps({'spread_calibration':overlay['contracts']},indent=2))
        print(json.dumps({'event':e['event_id'],'selection_policy':result.get('selection_policy'),'flip_diagnostics':result.get('flip_diagnostics'),'coherence':result.get('coherence'),'assimilation':result.get('assimilation'),'joint_distribution':result.get('joint_distribution'),'independent_head_predictions':result['prediction'],'binary':result['winner_simulation'],'scores':result['score_simulation']},indent=2))
    if distribution_incomplete:raise SystemExit(2)
if __name__=='__main__':main()
