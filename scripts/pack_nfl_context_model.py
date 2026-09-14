#!/usr/bin/env python3
"""Reproducible portable parameter packaging and explicit tie-frequency fit."""
import argparse,base64,gzip,hashlib,json
from pathlib import Path
import pandas as pd

def main():
    p=argparse.ArgumentParser();p.add_argument('--fit',type=Path,required=True);p.add_argument('--simulation-spec',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    model=json.loads((a.fit/'model.json').read_text());spec=json.loads(a.simulation_spec.read_text());f=pd.read_csv(a.fit/'features.csv');games=f[f.home_margin.notna()]
    spec['training_final_games']=len(games);spec['training_ties']=int((games.home_margin==0).sum());spec['tie_rate']=(spec['training_ties']+.5)/(len(games)+1)
    model['simulation_v2']=spec;raw=json.dumps(model,allow_nan=False).encode();packed={'encoding':'GZIP_BASE64','sha256':hashlib.sha256(raw).hexdigest(),'payload':base64.b64encode(gzip.compress(raw,mtime=0)).decode()}
    with a.output.open('x') as out:json.dump(packed,out)
    print(a.output)
if __name__=='__main__':main()
