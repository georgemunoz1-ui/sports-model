"""Shared seeded joint margin/total Monte Carlo utility for shadow models."""
from __future__ import annotations
import hashlib, json
import numpy as np
ENGINE_ID="sports.joint_margin_total_mc.v1"; ENGINE_VERSION="1.0.0"; MIN_SIMS=50_000

def canonical_hash(obj):
    b=json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return "sha256:"+hashlib.sha256(b).hexdigest()

def derive_seed(event_id, card_date, model_version, feature_snapshot_hash):
    material=f"{event_id}:{card_date}:{model_version}:{feature_snapshot_hash}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8],"big",signed=False)

def run(*, event_id, card_date, model_version, feature_snapshot_hash, margin_mean, total_mean, margin_sd, total_sd, rho, simulations=100_000, spread=None, total_line=None):
    if simulations < MIN_SIMS: raise ValueError("simulation_count_below_50000")
    vals=[margin_mean,total_mean,margin_sd,total_sd,rho]
    if not all(np.isfinite(vals)) or margin_sd<=0 or total_sd<=0 or not -0.95<=rho<=0.95: raise ValueError("invalid_distribution_parameters")
    seed=derive_seed(event_id,card_date,model_version,feature_snapshot_hash)
    rng=np.random.Generator(np.random.PCG64(seed))
    z=rng.multivariate_normal([0.,0.],[[1.,rho],[rho,1.]],size=simulations)
    margin=margin_mean+margin_sd*z[:,0]; total=total_mean+total_sd*z[:,1]
    home=(total+margin)/2.; away=(total-margin)/2.
    q=lambda a:{str(p):float(np.quantile(a,p)) for p in (.10,.25,.50,.75,.90)}
    out={"simulation_engine":ENGINE_ID,"simulation_engine_version":ENGINE_VERSION,"rng":"numpy.random.Generator(PCG64)","simulation_count":simulations,"random_seed":seed,
      "distribution":{"class":"JOINT_NORMAL_MARGIN_TOTAL_V1","margin_mean":float(margin_mean),"total_mean":float(total_mean),"margin_sd":float(margin_sd),"total_sd":float(total_sd),"rho":float(rho)},
      "home_win_p":float(np.mean(margin>0)),"away_win_p":float(np.mean(margin<0)),"home_points_mean":float(np.mean(home)),"away_points_mean":float(np.mean(away)),
      "margin_mean":float(np.mean(margin)),"total_mean":float(np.mean(total)),"margin_quantiles":q(margin),"total_quantiles":q(total),"home_points_quantiles":q(home),"away_points_quantiles":q(away)}
    if spread is not None: out["home_cover_p"]=float(np.mean(margin+float(spread)>0)); out["reference_home_spread"]=float(spread)
    if total_line is not None: out["over_p"]=float(np.mean(total>float(total_line))); out["under_p"]=float(np.mean(total<float(total_line))); out["reference_total"]=float(total_line)
    out["output_hash"]=canonical_hash(out)
    return out
