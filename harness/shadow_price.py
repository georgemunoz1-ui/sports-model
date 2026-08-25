#!/usr/bin/env python3
"""READ-ONLY shadow pricing. Same canonical engine call as price_cli.py (engine.kprops.price_board),
but writes NOTHING to state.json. Use whenever a board is sourced AFTER the slate is final, or for
any what-if: retroactive plays must never enter the paper ledger or advance the 100-play gate.
Usage: python3 harness/shadow_price.py board.json"""

MODULE_ID = "shadow_price"
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kprops

raw = json.load(open(sys.argv[1]))
meta = raw.pop("_meta", {})
board = {k: [tuple(q) for q in v] for k, v in raw.items()}
plays, evals = kprops.price_board(board)

print(f"=== SHADOW PRICING (NO STATE WRITE) — {meta.get('date','?')} ===")
if meta.get("capture_is_post_slate"):
    print("!! POST-SLATE CAPTURE: results already known. NOT gate-eligible, NOT staked, NOT logged as plays.\n")
for name, ek, gs, res in sorted(evals, key=lambda e: (e[1] is None, -(e[1] or 0))):
    r = res if isinstance(res, str) else f"{res['side']} {res['line']} @{res['price']} ({res['book']}) p={res['p']} edge={res['edge']:+.3f} EV={res['ev']:+.3f} disp={res['disp']:+.2f} w={res['weight']}"
    print(f"{name:<20} E[K] {str(ek):>5} GS {str(gs):>3} -> {r}")
print(f"\nWOULD-HAVE-QUALIFIED: {len(plays)} of {len(board)} priced arms")
json.dump({"meta": meta, "shadow_plays": plays, "n_evaluated": len(board)},
          open(sys.argv[1].replace(".json", "_shadow.json"), "w"), indent=1)
print("state.json UNCHANGED (by design).")
