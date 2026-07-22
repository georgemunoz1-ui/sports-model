# Reframe V13's 7/18 by LOSS QUALITY (Taco doctrine: live losses OK, avoidable blowouts NOT)
# side we'd have bet (value pick), result, margin. Capped games excluded (no play).
picks = [
 ("PIT@CLE G1","PIT","W",6,"win"),
 ("MIN@CHC","MIN","L",4,"trailed, mid"),
 ("NYM@PHI","NYM","L",5,"Manaea shelled; scored 1 — never live"),
 ("CHW@TOR","CHW","L",1,"lost 0-1, live to the end"),
 ("CIN@COL","COL","W",7,"win"),
 ("STL@ARI","STL","L",2,"lost by 2, live"),
 ("MIA@MIL","MIA","L",2,"lost by 2, live"),
 ("BAL@HOU","BAL","W",2,"win (11 inn)"),
 ("SD@KC","KC","W",5,"win"),
 ("TB@BOS","BOS","W",1,"win (nailbiter)"),
 ("SF@SEA","SF","L",1,"led 3-0 into 7th, lost in 10 — pure variance"),
 ("WSH@ATH","WSH","L",14,"Littell 8ER/9HH in hitter park — AVOIDABLE"),
 ("DET@LAA","DET","W",7,"win (directional)"),
]
wins=[p for p in picks if p[2]=="W"]; losses=[p for p in picks if p[2]=="L"]
live   = [p for p in losses if p[3]<=2]      # competitive: lost by <=2
mid    = [p for p in losses if p[3] in (3,4)]
blowout= [p for p in losses if p[3]>=5]      # avoidable-class: lost by >=5
print(f"V13 7/18 (uncapped bets): {len(wins)}-{len(losses)}")
print(f"  LIVE losses (<=2 runs, acceptable variance): {len(live)}  -> {[p[0] for p in live]}")
print(f"  MID  losses (3-4 runs):                      {len(mid)}   -> {[p[0] for p in mid]}")
print(f"  BLOWOUT losses (>=5, data-should-avoid):     {len(blowout)} -> {[p[0] for p in blowout]}")
print()
print("  Detail:")
for g,s,r,m,note in losses:
    tag = "LIVE ✓ok" if m<=2 else ("MID" if m<=4 else "BLOWOUT ✗")
    print(f"    {g:<11} bet {s:<4} L by {m:>2}  [{tag}]  {note}")
tot=len(wins)+len(losses)
blr=len(blowout)/tot
print()
print(f"  BLOWOUT-LOSS RATE = {len(blowout)}/{tot} = {blr:.0%}  (target metric to MINIMIZE)")
print(f"  Of {len(losses)} losses, {len(live)} were 1-2 run games. The doctrine-relevant failures = {len(blowout)}:")
print(f"    WSH (Littell, avoidable) + NYM (Manaea 6-GS low-sample dog). Those two are the ones to indict.")
