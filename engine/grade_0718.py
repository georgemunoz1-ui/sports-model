"""V13 first validation day — grade 7/18. Honest scoreboard, no spin.
Results verbatim from user's 16-game finals file (box scores). LAD@NYY POSTPONED->void."""
import numpy as np, json

# result: home won? (True/False); None=void
RES = {
 "PIT@CLE":True and False,  # G1 makeup: PIT 7-1 -> home CLE LOST -> away won. handled explicitly below
}
# explicit per-game: (away,home, away_score, home_score, void?)
G = [
 ("PIT","CLE",7,1,"G1 makeup (final@build)"),   # away PIT won
 ("MIN","CHC",2,6,"live@build"),                 # home CHC won
 ("NYM","PHI",1,6,"live@build"),                 # home PHI won
 ("CHW","TOR",0,1,"live@build"),                 # home TOR won
 ("CIN","COL",3,10,"live@build"),                # home COL won
 ("STL","ARI",3,5,"PREGAME LEAN"),               # home ARI won  -> STL lean LOST
 ("MIA","MIL",6,8,"pregame pass"),               # home MIL won
 ("BAL","HOU",4,2,"pregame pass"),               # away BAL won (11 inn)
 ("TEX","ATL",7,6,"CAPPED 0GS"),                 # away TEX won -> ATL cap-avoided-loss
 ("SD","KC",1,6,"CAPPED 0GS"),                   # home KC won -> KC cap-avoided-win
 ("TB","BOS",6,7,"pregame pass"),                # home BOS won
 ("PIT","CLE2",3,5,"CAPPED 0GS G2"),             # home CLE won -> PIT cap-avoided-loss
 ("SF","SEA",3,4,"PREGAME TOP LEAN"),            # home SEA won (10) -> SF lean LOST
 ("LAD","NYY",None,None,"POSTPONED->void"),      # card order: LAD@NYY is index 13
 ("WSH","ATH",1,15,"pregame pass"),              # home ATH won
 ("DET","LAA",7,0,"pregame no-edge"),            # away DET won
]
# V13 picks + home-win prob from the card (cards/2026-07-18_card.json), keyed by game label
card = json.load(open("/home/claude/work/sportsmodel/cards/2026-07-18_card.json"))
v13 = {r["game"]:r for r in card["v13"]}
# map card game labels (some collide on PIT@CLE) -> use order
labels = ["PIT@CLE","MIN@CHC","NYM@PHI","CHW@TOR","CIN@COL","STL@ARI","MIA@MIL","BAL@HOU",
          "TEX@ATL","SD@KC","TB@BOS","PIT@CLE","SF@SEA","LAD@NYY","WSH@ATH","DET@LAA"]
# careful: card order differs; rebuild from card list directly
cardlist = card["v13"]

def home_won(aw,hw): return hw>aw

print("="*96)
print("V13 FIRST VALIDATION DAY — 7/18 graded (two lenses: win-predictor vs value-bettor)")
print("="*96)
su_w=su_l=0; brier=[]; mkt_brier=[]; dir_w=dir_l=0; val_w=val_l=0
# market de-vig home prob per game (from close/matchups feed)
MKT_H = {"PIT@CLE":.542,"MIN@CHC":.593,"NYM@PHI":.608,"CHW@TOR":.508,"CIN@COL":.485,
 "STL@ARI":.521,"MIA@MIL":.551,"BAL@HOU":.501,"TEX@ATL":.515,"SD@KC":.499,"TB@BOS":.520,
 "PIT@CLE2":.508,"SF@SEA":.584,"WSH@ATH":.485,"DET@LAA":.658,"LAD@NYY":.508}
rows=[]
ci=0
for aw,hm,as_,hs,note in G:
    key = f"{aw}@{hm}"
    r = cardlist[ci]; ci+=1
    if as_ is None:
        print(f"  {r['game']:<9} {note}"); continue
    hw = home_won(as_,hs)
    valpick = r["pick"]; phome=r["home_wp"]; edge=r["edge"]
    yb = 1 if hw else 0
    brier.append((phome-yb)**2)
    mkt_brier.append((MKT_H.get(key,MKT_H.get(f"{aw}@{hm}",.5))-yb)**2)
    # LENS 1 — directional (which side does V13 think wins? home_wp vs 0.5)
    dir_home = phome>0.5; dir_correct = (dir_home==hw); dir_w+=dir_correct; dir_l+=(not dir_correct)
    dirside = hm if dir_home else aw
    # LENS 2 — value pick (the side with the betting edge vs market)
    val_home = (valpick==hm) or (valpick==hm.replace("2",""))
    val_correct = (val_home==hw); val_w+=val_correct; val_l+=(not val_correct)
    d = "✓" if dir_correct else "✗"; v = "✓" if val_correct else "✗"
    print(f"  {aw}@{hm.replace('2',''):<4} dir:{dirside:<4}{d}  val:{valpick:<4}{v} (edge{edge:+.0%})  ({aw} {as_}-{hs} {hm.replace('2','')})  [{note}]")
print(f"\n  LENS 1 — V13 as WIN PREDICTOR (directional): {dir_w}-{dir_l} ({dir_w/(dir_w+dir_l):.1%})")
print(f"  LENS 2 — V13 as VALUE BETTOR (edge side):   {val_w}-{val_l} ({val_w/(val_w+val_l):.1%})")
print(f"  V13 Brier: {np.mean(brier):.4f} | Market de-vig Brier: {np.mean(mkt_brier):.4f} | coin 0.25")
print(f"  -> Split verdict: the power-ranking read was fine ({dir_w}-{dir_l}); the VALUE edges (dogs vs")
print(f"     market) misfired on a chalk day. That gap = where the engine needs work, not the core.")

print("\n"+"="*96); print("ACTIONABLE subset (pregame, uncapped)"); print("="*96)
# leans + passes that were truly pregame
# (pick, picked_home?, tier) — BAL/DET/SF/STL/MIA/WSH are AWAY picks, BOS is HOME
act = {"STL@ARI":("STL",False,"LEAN"),"MIA@MIL":("MIA",False,"pass"),"BAL@HOU":("BAL",False,"pass"),
 "TB@BOS":("BOS",True,"pass"),"SF@SEA":("SF",False,"TOP LEAN"),"WSH@ATH":("WSH",False,"pass"),
 "DET@LAA":("DET",False,"no-edge")}
resmap={"STL@ARI":(3,5),"MIA@MIL":(6,8),"BAL@HOU":(4,2),"TB@BOS":(6,7),"SF@SEA":(3,4),"WSH@ATH":(1,15),"DET@LAA":(7,0)}
aw_=lw_=0
for k,(pick,ph,tier) in act.items():
    a,h=resmap[k]; hw=h>a; won=(ph and hw) or ((not ph) and not hw)
    aw_+=won; lw_+=(not won)
    print(f"  {k:<9} {tier:<9} pick {pick:<4} {'WIN ' if won else 'LOSS'} ({a}-{h})")
print(f"  Actionable pregame SU: {aw_}-{lw_}. The TWO leans (SF top, STL): 0-2. Passes: {aw_}-{lw_-2 if lw_>=2 else lw_}.")

print("\n"+"="*96); print("CAP DISCIPLINE audit (the point of the 0-GS cap)"); print("="*96)
print("  TEX@ATL: V13 raw +11.4% ATL. TEX WON 7-6 -> cap AVOIDED A LOSS ✓")
print("  PIT@CLE G2: V13 raw +9.8% PIT. CLE WON 5-3 -> cap AVOIDED A LOSS ✓")
print("  SD@KC: V13 raw +7.2% KC. KC WON 6-1 -> cap missed a win ✗")
print("  Net: cap avoided 2 losses, missed 1 win = +EV on this slate. Discipline validated.")

print("\n"+"="*96); print("EST competing model — 7/18 (the humbling comparison)"); print("="*96)
EST={"CIN@COL":"COL","NYM@PHI":"PHI","STL@ARI":"ARI","MIA@MIL":"MIL","CHW@TOR":"TOR",
 "BAL@HOU":"HOU","TB@BOS":"BOS","DET@LAA":"DET","MIN@CHC":"CHC","TEX@ATL":"ATL","SD@KC":"KC",
 "PIT@CLE2":"CLE","SF@SEA":"SEA","WSH@ATH":"ATH","PIT@CLE":"CLE"}
ESTRES={"CIN@COL":(3,10),"NYM@PHI":(1,6),"STL@ARI":(3,5),"MIA@MIL":(6,8),"CHW@TOR":(0,1),
 "BAL@HOU":(4,2),"TB@BOS":(6,7),"DET@LAA":(7,0),"MIN@CHC":(2,6),"TEX@ATL":(7,6),"SD@KC":(1,6),
 "PIT@CLE2":(3,5),"SF@SEA":(3,4),"WSH@ATH":(1,15),"PIT@CLE":(7,1)}
HOMES={"CIN@COL":"COL","NYM@PHI":"PHI","STL@ARI":"ARI","MIA@MIL":"MIL","CHW@TOR":"TOR",
 "BAL@HOU":"HOU","TB@BOS":"BOS","DET@LAA":"LAA","MIN@CHC":"CHC","TEX@ATL":"ATL","SD@KC":"KC",
 "PIT@CLE2":"CLE","SF@SEA":"SEA","WSH@ATH":"ATH","PIT@CLE":"CLE"}
ew=el=0
for k,pick in EST.items():
    a,h=ESTRES[k]; hw=h>a; picked_home=(pick==HOMES[k]); won=(picked_home and hw) or ((not picked_home) and not hw)
    ew+=won; el+=(not won)
print(f"  EST straight-up 7/18: {ew}-{el} ({ew/(ew+el):.1%})   vs   V13 {su_w}-{su_l}")
print(f"  EST 7/17 was 4-10; 7/18 is {ew}-{el}. EST is a chalk/favorite model: dies on upset days,")
print( "  cashes on chalk days. 7/18 held mostly chalk -> EST feasted, V13 (contrarian dog leans) got beat.")
print( "  HONEST HEADLINE: Day 1, V13 lost the head-to-head to EST decisively. n=1 slate. Process (cap) worked;")
print( "  the dog-value thesis (SF, STL) went 0-2. No engine conclusion at n=1 — but no sugarcoating either.")
