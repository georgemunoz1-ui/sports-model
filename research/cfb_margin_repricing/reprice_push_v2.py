"""Opt-in research repricing of rounded-normal margins, with explicit push mass."""
import math
from reprice import _distribution

def reprice_with_push(row, home_line, *, research_only=False, period='full_game'):
    if not research_only: raise ValueError('EXPLICIT_RESEARCH_OPT_IN_REQUIRED')
    if period!='full_game': raise ValueError('PERIOD_MISMATCH')
    if isinstance(home_line,bool) or not isinstance(home_line,(int,float)) or not math.isfinite(home_line) or (home_line*2)%1: raise ValueError('INTEGER_OR_HALF_POINT_REQUIRED')
    pairs,n=_distribution(row)
    mu=row['model']['full_game_home_margin'];sigma=row['model']['margin_sigma']
    if not math.isfinite(mu) or not math.isfinite(sigma) or sigma<=0: raise ValueError('INVALID_PARAMETERS')
    threshold=-home_line
    # Rounded normal: for integer threshold k, tie bin is [k-.5, k+.5).
    lo=threshold-.5 if float(threshold).is_integer() else threshold
    hi=threshold+.5 if float(threshold).is_integer() else threshold
    cdf=lambda x:.5*math.erfc(-(x-mu)/(sigma*math.sqrt(2)))
    survival=lambda x:.5*math.erfc((x-mu)/(sigma*math.sqrt(2)))
    away=cdf(lo);home=survival(hi);push=max(0.,1-home-away)
    counts={k:sum(c for m,c in pairs if predicate(m)) for k,predicate in [('home_cover',lambda m:m>threshold),('away_cover',lambda m:m<threshold),('push',lambda m:m==threshold)]}
    def package(h,a,p):
        den=h+a
        return dict(home_cover=h,away_cover=a,push=p,home_cover_given_no_push=h/den if den else None,away_cover_given_no_push=a/den if den else None)
    return dict(schema_version='cfb.push_repricing.v2',status='RESEARCH_DIAGNOSTIC_UNCALIBRATED',period=period,home_line=home_line,model=package(home,away,push),simulation=package(counts['home_cover']/n,counts['away_cover']/n,counts['push']/n),counts=counts,n_sims=n,settlement_definition='home_margin + home_line >0 cover; =0 push; <0 loss',push_calibration='NOT_ESTABLISHED',action_authority='OFF')
