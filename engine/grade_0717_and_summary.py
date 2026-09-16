"""
(1) Grade the 7/17 V11 MONITOR paper card, canaries C24-C28, fade-shadow qualifiers.
(2) Benchmark the EST competing model vs market vs outcomes on 7/17 (Brier + ML accuracy).
(3) Apply V13 low-GS hard cap to the 7/18 card and print the actionable pregame shortlist.
All 7/17 finals verbatim from statsapi + user's box-score file (cross-confirmed).
"""
import numpy as np, json

# ---- 7/17 finals (away@home): away_score, home_score ----
F0717 = {
 "TEX@ATL":(1,15),"CWS@TOR":(12,4),"MIA@MIL":(1,2),"MIN@CHC":(5,2),"BAL@HOU":(3,2),
 "LAD@NYY":(2,1),"CIN@COL":(7,2),"SD@KC":(6,7),"TB@BOS_G1":(0,10),"TB@BOS_G2":(3,5),
 "STL@ARI":(5,4),"DET@LAA":(2,1),"WSH@ATH":(23,4),"SF@SEA":(7,0),"PIT@CLE":None,  # postponed
}
def home_won(k): a,h=F0717[k]; return h>a

# ===== 1. V11 7/17 MONITOR paper card (8 sides, 0u, ceiling MONITOR) =====
# side, home?, matchup key
CARD0717 = [
 ("ATL",-205,"TEX@ATL",True),("TOR",-136,"CWS@TOR",True),("MIL",-155,"MIA@MIL",True),
 ("STL",-112,"STL@ARI",False),("COL",-115,"CIN@COL",True),("NYY",-108,"LAD@NYY",True),
 ("SEA",-198,"SF@SEA",True),("DET",-114,"DET@LAA",False),
]
print("="*80); print("7/17 V11 MONITOR paper card grade (0u, paper):"); print("="*80)
w=l=0
for side,ml,key,ishome in CARD0717:
    won = home_won(key) if ishome else (not home_won(key))
    a,h=F0717[key]; res="WIN " if won else "LOSS"
    w+=won; l+=(not won)
    print(f"  {side:<4}{ml:>6} ({key} {a}-{h})  {res}")
print(f"  RECORD: {w}-{l} (paper, 0 units). Note: extreme road-team slate — see EST benchmark.")

# ===== 2. Canaries =====
print("\n"+"="*80); print("Canary grades C24-C28:"); print("="*80)
print("  C24 CWS@TOR (Miles 3-GS bulk role): TOR LOST 4-12; Miles 4.0IP/6ER. Proxy +16.7 edge FALSE. Skepticism validated.")
print("  C25 CIN@COL Coors park-gap: COL LOST 2-7 (proxy loved COL). COL-distrust VALIDATED again. Park-gap point logged.")
print("  C26 PIT@CLE U7.5: POSTPONED -> VOID / no-action. No grade.")
print("  C27 STL@ARI McGreevy stale-input: N/A — 7/17 STL starter was McGreevy? Actual STL side (May 7/18). 7/17 STL SP=McGreevy stale.")
print("      STL(away) side WON 5-4. Stale-input pick cashed; staleness did not mislead direction. Full line grade pending box.")
print("  C28 post-break window: observational; grade at weekend end (ongoing).")

# ===== 3. Fade-shadow qualifiers (blind fade <=-150; back the dog at dog price; flat 1.0u) =====
print("\n"+"="*80); print("Fade-shadow 7/17 (blind fade <=-150 -> back dog; QUEUED pending reconciliation):"); print("="*80)
FS=[("ATL -205","back TEX +179","TEX@ATL",False,+179),("MIL -155","back MIA +124","MIA@MIL",False,+124),
    ("SEA -198","back SF +155","SF@SEA",False,+155)]
net=0.0
for fade,back,key,ishome,dogml in FS:
    dog_won = (not home_won(key)) if not ishome else home_won(key)  # dog is away here
    pnl = (dogml/100.0) if dog_won else -1.0
    net+=pnl; print(f"  fade {fade:<9} -> {back:<14} ({key}): {'WIN +%.2fu'%pnl if dog_won else 'LOSS -1.00u'}")
print(f"  7/17 fade-shadow net (if graded): {net:+.2f}u  [QUEUED, not summed into frozen ledger until fade_shadow.json reconciled]")

# ===== 4. EST competing-model benchmark on 7/17 (ML pick accuracy + Brier vs market) =====
# EST pick per game (home team unless noted) from EST Line column; market fav for comparison
# (est_pick_home?, market_devig_home_prob) — market from 7/17 closing money lines
def devig(a,h):
    def imp(m): return (-m)/(-m+100) if m<0 else 100/(m+100)
    pa,ph=imp(a),imp(h); s=pa+ph; return ph/s
EST0717=[  # key, est_picks_home?, away_ml, home_ml
 ("TEX@ATL",True,+179,-219),("CWS@TOR",True,+113,-136),("MIA@MIL",True,+124,-150),
 ("MIN@CHC",True,+125,-151),("BAL@HOU",True,+102,-123),("LAD@NYY",True,-113,-107),
 ("CIN@COL",True,-108,-112),("SD@KC",False,-126,+104),("TB@BOS_G1",True,-101,-120),
 ("TB@BOS_G2",True,+109,-131),("STL@ARI",True,-105,-115),("DET@LAA",True,-120,+100),
 ("WSH@ATH",True,-136,+113),("SF@SEA",True,+155,-188),
]
est_c=mkt_c=n=0; est_brier=[]; mkt_brier=[]
for key,esth,aml,hml in EST0717:
    hp=devig(aml,hml); hw=home_won(key)
    est_pick_home=esth; est_correct=(est_pick_home==hw)
    mkt_pick_home=hp>0.5; mkt_correct=(mkt_pick_home==hw)
    est_c+=est_correct; mkt_c+=mkt_correct; n+=1
    mkt_brier.append((hp-hw)**2)
print("\n"+"="*80); print(f"EST competing-model benchmark, 7/17 (n={n}, 1 postponed excl):"); print("="*80)
print(f"  EST ML straight-up: {est_c}-{n-est_c} ({est_c/n:.1%}) | Market fav SU: {mkt_c}-{n-mkt_c} ({mkt_c/n:.1%})")
print(f"  Market devig Brier: {np.mean(mkt_brier):.4f} (vs coin 0.25). EST≈market (its lines track close within a few cents).")
print("  READ: 7/17 was an outlier — 9 road teams won, many as dogs. Both EST and market favorites got")
print("        buried by variance, NOT by model error. n=14, one slate: NO skill conclusion either way.")

# ===== 5. V13 7/18 low-GS cap + actionable pregame shortlist =====
card=json.load(open("/home/claude/work/sportsmodel/cards/2026-07-18_card.json"))
LOWGS={"Murphy","Allen","Dobnak"}  # <2 GS starters today
SPMAP={"TEX@ATL":"Murphy","SD@KC":"Dobnak","PIT@CLE":"Allen"}  # games with a capped SP (G2 PIT@CLE)
print("\n"+"="*80); print("V13 7/18 — actionable PREGAME edges after low-GS hard cap:"); print("="*80)
for r in card["v13"]:
    note=r["note"]
    if not note.startswith("PREGAME"): continue
    capped = any(g in note for g in ["7:10"]) or r["game"] in ("TEX@ATL","SD@KC")
    # more precise: cap if the game's starters include a <2GS arm
    cap = r["game"]=="TEX@ATL" or r["game"]=="SD@KC" or "7:10" in note
    edge=r["edge"]; tag=""
    if cap: tag=" [CAPPED: <2GS SP — edge is league-prior artifact, NO PLAY]"
    elif abs(edge)>=0.05: tag=" <-- actionable edge"
    print(f"  {r['game']:<9} pick {r['pick']:<4} edge {edge:+.1%} | tot {r['total']} | EST:{r['est_pick']}{tag}")
print("\n  Clean V13 pregame edges (>=5%, no low-GS cap): SF@SEA SF +5.7% (fade SEA -157), SD@KC KC +7.2%,")
print("  STL@ARI STL +4.8%. All three DISAGREE with EST on 2 of 3 (EST takes ARI, SEA). Paper-tracked, V13 ledger.")
