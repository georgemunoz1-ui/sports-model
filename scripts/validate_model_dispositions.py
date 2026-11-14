#!/usr/bin/env python3
"""Read-only verification of eight-league research-only disposition coverage."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research.nov11_cross_model.model_disposition_review import read_manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,default=Path(__file__).resolve().parents[1]/"data/research/nov11_cross_model_dispositions_v1.json")
    args=parser.parse_args(argv)
    print(json.dumps(read_manifest(args.input),indent=2,sort_keys=True))

if __name__=="__main__": main()
