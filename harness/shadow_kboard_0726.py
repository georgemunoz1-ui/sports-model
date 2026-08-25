#!/usr/bin/env python3
"""SHADOW run of the canonical K engine over the 2026-07-26 real price board.

This is the first time the engine has ever seen a full slate of REAL two-sided
strikeout prices. It is explicitly NON-GATE-ELIGIBLE:

  * every game on this board had already started by the time the board was
    processed, except the four already handled in the live pass;
  * staked = 0.0;
  * it does not touch gates.kprops_go_live.progress.

Only rows that survive harness/audit_kboard_0726.py (T1 hold, T2 rung,
T3 dispersion, T4 re-read) are priced. Quarantined rows are listed and skipped.
E[K] and GS come from cards/2026-07-26_card.json, which was built PRE-SLATE from
statsapi - not from anything in the screenshot.
"""

MODULE_ID = "shadow_kboard_0726"
import json, sys, unicodedata
sys.path.insert(0, ".")
from engine.kprops import select_play, p_over, ev

def ascii_(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()

B = json.load(open("data/mlb/props/2026-07-26_kboard_full.json"))
AUD = json.load(open("data/mlb/props/2026-07-26_kboard_audit.json"))
CARD = json.load(open("cards/2026-07-26_card.json"))
LIVE4 = set(json.load(open("data/mlb/props/2026-07-26_klines_live4.json"))["live_at_processing"])

# pitcher -> (ek, gs, game, first_pitch)
PS = {}
for r in CARD["rows"]:
    gk = "%s@%s" % (r["away"], r["home"])
    for sp in ("asp", "hsp"):
        st = r.get(sp + "_stats") or {}
        PS[ascii_(r[sp]).lower()] = dict(ek=st.get("ek"), gs=st.get("gs"),
                                         game=gk, t=r["time"])

clean = set(AUD["clean"])
print("=== engine over the permitted rows (SHADOW, staked 0.0) ===")
plays, skipped = [], []
for r in B["rows"]:
    name = r["pitcher"]
    if name not in clean:
        skipped.append((name, "QUARANTINED by T3 dispersion")); continue
    key = ascii_(name).lower()
    if key not in PS:
        skipped.append((name, "not on the pre-slate card")); continue
    meta = PS[key]
    ek, gs = meta["ek"], meta["gs"]
    if ek is None:
        skipped.append((name, "no pre-slate E[K] (gs=%s, engine requires >=5)" % gs)); continue
    quotes = [(bk, ln, u, o) for bk, ln, u, o in r["q"]
              if ln is not None and (u is not None or o is not None)]
    if not quotes:
        skipped.append((name, "no priced cell in the image (line-only row)")); continue
    sel = select_play(quotes, ek, gs)
    cons = sorted(ln for bk, ln, u, o in r["q"] if ln is not None)
    med = cons[len(cons) // 2]
    print("  %-20s %-9s %s  E[K] %4.2f  gs %2d  med line %4.1f  disp %+5.2f  -> %s"
          % (name, meta["game"], meta["t"], ek, gs, med, ek - med,
             "%s %.1f @ %+d (%s) EV %+.3f edge %+.3f p %.3f"
             % (sel["side"], sel["line"], sel["price"], sel["book"], sel["ev"],
                sel["edge"], sel["p"]) if sel else "no play"))
    if sel:
        plays.append(dict(pitcher=name, game=meta["game"], first_pitch=meta["t"],
                          ek=ek, gs=gs, **sel,
                          live_at_capture=name in LIVE4))

print("\n  %d plays selected from %d permitted rows" % (len(plays), len(clean)))
print("\n=== skipped ===")
for n, why in skipped:
    print("  %-20s %s" % (n, why))

out = dict(date="2026-07-26", kind="SHADOW", gate_eligible=False, staked=0.0,
           note=("Games were already in progress when this board was captured. "
                 "These are NOT bets and MUST NOT advance gates.kprops_go_live. "
                 "Recorded to measure what the canonical engine does against a "
                 "full board of real two-sided K prices for the first time."),
           permitted=sorted(clean), quarantined=AUD["quarantined"],
           plays=plays, skipped=skipped)
json.dump(out, open("data/mlb/props/2026-07-26_kboard_shadow.json", "w"), indent=1)
print("\nwrote data/mlb/props/2026-07-26_kboard_shadow.json")
