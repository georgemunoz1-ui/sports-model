#!/usr/bin/env python3
"""Calibrate saved NFL final-score draws at supplied full-game spread lines."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from models.nfl.contextual.spread_runtime import build_overlay,persist_overlay

def main():
    p=argparse.ArgumentParser();p.add_argument('--forecast-directory',type=Path,required=True);p.add_argument('--home-spread',type=float,action='append',required=True);p.add_argument('--simulations',type=int,default=100000);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    manifest=json.loads((a.forecast_directory/'manifest.json').read_text())
    for name,h in manifest.items():
        if hashlib.sha256((a.forecast_directory/name).read_bytes()).hexdigest()!=h:raise ValueError('FORECAST_MANIFEST_MISMATCH:'+name)
    forecast=json.loads((a.forecast_directory/'forecast.json').read_text());scores=np.load(a.forecast_directory/'score_draws.npy',allow_pickle=False)
    out,draws=build_overlay(forecast,scores,a.home_spread,n=a.simulations)
    persist_overlay(a.output,out,draws)
    for name,h in manifest.items():assert hashlib.sha256((a.forecast_directory/name).read_bytes()).hexdigest()==h
    print(json.dumps({'contracts':out['contracts'],'simulation':out['simulation'],'warnings':out['warnings']},indent=2))
if __name__=='__main__':main()
