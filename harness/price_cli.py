#!/usr/bin/env python3
"""CANONICAL board pricing — the ONLY sanctioned path from a props board to plays.
Usage: python3 harness/price_cli.py board.json   where board.json = {pitcher: [[book,line,under,over],...]}
Prints evaluations; appends qualifying plays to state.json pending (enriched schema fields stubbed)."""

MODULE_ID = "price_cli"
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"engine"))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kprops, datetime
board={k:[tuple(q) for q in v] for k,v in json.load(open(sys.argv[1])).items()}
plays,evals=kprops.price_board(board)
for name,ek,gs,res in evals: print(f"{name:<20} E[K] {ek} GS {gs} -> {res}")
if plays:
    st=json.load(open("state.json")); today=str(datetime.date.today())
    for p in plays: p["date"]=today
    st["ledgers"]["kprops_paper"]["plays_pending"]+=plays
    json.dump(st,open("state.json","w"),indent=1)
    print(f"\n{len(plays)} plays appended to state.json pending")
