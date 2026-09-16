#!/usr/bin/env python3
"""Show or validate the selected model for an exact sport/product scope."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pipelines.cards.selection import select,inventory
p=argparse.ArgumentParser();p.add_argument('--league');p.add_argument('--target',default='winner');p.add_argument('--week',type=int);p.add_argument('--division');a=p.parse_args()
print(json.dumps(select(a.league,a.target,week=a.week,division=a.division) if a.league else inventory(),indent=2))
