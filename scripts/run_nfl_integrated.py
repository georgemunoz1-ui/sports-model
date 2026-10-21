#!/usr/bin/env python3
"""One command: canonical adapter, all model arms, binary and score simulations."""
import argparse,datetime as dt,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pipelines.cards.adapters import nfl
from models.nfl.contextual.runtime import run,persist_run

def main():
    p=argparse.ArgumentParser();p.add_argument('--date',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--simulations',type=int,default=100000);p.add_argument('--model-id');p.add_argument('--mode',default='research_pregame');p.add_argument('--market-packet',type=Path);p.add_argument('--live-packet',type=Path);p.add_argument('--event-id');p.add_argument('--home-spread',type=float,action='append',help='Optional downstream full-game spread calibration, HOME handicap orientation');p.add_argument('--halftime-artifact',type=Path,help='Explicit fitted halftime/joint research artifact; emits a separate model output');p.add_argument('--weekly-state-store',type=Path);p.add_argument('--weekly-state-id');p.add_argument('--distribution-research-config',type=Path,help='Separate hash-bound margin/total research child; does not require or replace combined-arm calibration');p.add_argument('--roster-bundle',type=Path);p.add_argument('--require-roster-aware',action='store_true');p.add_argument('--disclosures',type=Path,help='Presentation-only event scenarios and dependence evidence; requires --event-id');a=p.parse_args()
    from sports.rosters import attach, assess, load_bundle
    roster=load_bundle(a.roster_bundle) if a.roster_bundle else None
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
    cutoff=dt.datetime.now(dt.timezone.utc).isoformat();events=nfl.load_schedule(a.date,cutoff)
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
        result=attach(result,'nfl',e,cutoff,roster)
        persist_run(a.output/e['event_id'],result,win,scores,json.loads((nfl.ROOT/'data/nfl/modes_v1/design.json').read_text()) if fitted is not None else context['model']['design'])
        if a.mode!='live':
            from pipelines.cards.distribution_research import nfl_card
            from pipelines.cards.disclosures import write_report,render_md
            registration=json.loads((a.output/e['event_id']/'registration.jsonl').read_text())
            disclosures=write_report(nfl_card(result,registration['created_at_utc']),a.output/e['event_id']/'disclosures',a.disclosures)
            distribution_incomplete |= bool(disclosures['errors'])
            print(render_md(disclosures))
        if a.distribution_research_config:
            from pipelines.cards.distribution_research import build,load_config,nfl_card
            try:
                registration=json.loads((a.output/e['event_id']/'registration.jsonl').read_text())
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
            overlay,calibrated_margins=nfl.calibrate_spreads(result,scores,a.home_spread,n=a.simulations)
            persist_overlay(a.output/e['event_id']/'spread_calibration',overlay,calibrated_margins)
            print(json.dumps({'spread_calibration':overlay['contracts']},indent=2))
        print(json.dumps({'event':e['event_id'],'selection_policy':result.get('selection_policy'),'coherence':result.get('coherence'),'assimilation':result.get('assimilation'),'joint_distribution':result.get('joint_distribution'),'independent_head_predictions':result['prediction'],'binary':result['winner_simulation'],'scores':result['score_simulation']},indent=2))
    if distribution_incomplete:raise SystemExit(2)
if __name__=='__main__':main()
