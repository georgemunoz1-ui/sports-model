"""Current official-plus-one WNBA package using the pinned incumbent fitter."""
import numpy as np
from models.current import common
from models.nfl.contextual.recovered_inference import digest
from pipelines.cards.selection import require_default


def forecast(event,ctx,n):
    from harness import wnba_model_v1 as W
    p=ctx['package'];require_default('wnba',p['model_id'])
    if event['season_type']!=2:raise ValueError('WNBA_REGULAR_SEASON_ONLY')
    model={k:np.asarray(v,dtype=float) for k,v in p['fitted_model'].items()}
    ts=W.TeamState();ts.s={(int(r['season']),r['team']):r['values'] for r in p['team_state']}
    lg=tuple(p['league_state'])
    result=W.predict_slate(model,ts,lg,[(event['away_team'],event['home_team'],event['start_time_utc'])],event['season'])[0]
    if 'p_home' not in result:raise ValueError('WNBA_INSUFFICIENT_OBSERVED_HISTORY')
    features={'home':ts.feats(event['season'],event['home_team'],result['et_date']),
              'away':ts.feats(event['season'],event['away_team'],result['et_date']),
              'league_state':p['league_state'],'consumed_game_ids_sha256':digest(p['consumed_game_ids'])}
    return common.emit(event,ctx,features,result['p_home'],result['margin_home'],result['total'],n,
                       limitations=['FROZEN_MODEL_ROUNDING_RETAINED','MARGIN_TOTAL_DIAGNOSTICS_NOT_SETTLEMENT_PRICES'])
