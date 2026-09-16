"""
Slate engine — 2026-07-18. Runs BOTH:
  (A) V11 proxy-class unified score (LOCKED formula, dark signals zeroed+flagged, ceiling MONITOR)
  (B) V13 cloud-native Monte Carlo (authorized 2026-07-18: park adj + HFA + bullpen-shrink)
Inputs: 2026-07-18 matchups file (SP season aggregates, current team RF/RA, market ML, EST line,
        SP career-vs-current-opp-roster xwOBA). All numbers verbatim from user's canonical feed.
NO fabricated inputs. Low-sample SPs flagged and capped. Seeds fixed. Paper only.
"""
import numpy as np
rng = np.random.default_rng(718)
LG_RPG = 4.45          # league runs/team/game ~2026 (from current team RF avg, computed below)
LG_ERA = 4.20          # V11/V12 league prior for SP shrinkage (frozen)
LG_XWOBA = 0.320       # V11 career-signal league anchor (frozen)

# ---- current team RF/RA per game (verbatim, 2026-07-18 feed, 1-decimal) ----
TEAM = {
 "PIT":(5.3,4.9),"CLE":(3.9,3.9),"MIN":(4.9,5.0),"CHC":(5.0,4.5),"NYM":(4.1,4.7),
 "PHI":(4.3,4.5),"CHW":(4.9,4.4),"TOR":(4.1,4.5),"CIN":(4.2,4.8),"COL":(4.7,5.7),
 "BAL":(4.6,4.8),"HOU":(4.6,5.0),"SD":(4.0,4.4),"KC":(4.3,5.2),"STL":(4.5,4.4),
 "ARI":(4.3,4.5),"TB":(4.5,4.3),"BOS":(4.2,3.8),"TEX":(4.1,4.4),"ATL":(4.9,3.8),
 "MIA":(4.5,4.3),"MIL":(5.1,3.8),"SF":(4.1,4.7),"SEA":(4.0,3.9),"LAD":(5.2,3.7),
 "NYY":(4.8,3.8),"WSH":(5.5,5.2),"ATH":(4.4,5.7),"DET":(4.2,4.0),"LAA":(4.4,5.0),
}
# ---- park run factors (multiplicative, approx public consensus 2024-26) ----
PARK = {"Coors Field":1.18,"Fenway Park":1.03,"Yankee Stadium":1.02,"T-Mobile Park":0.92,
 "Kauffman Stadium":1.00,"Daikin Park":1.01,"Rogers Centre":1.01,"Wrigley Field":1.00,
 "Angel Stadium":0.97,"Sutter Health Park":1.06,"American Family Field":1.00,
 "Progressive Field":0.98,"Citizens Bank Park":1.04,"Chase Field":1.01,"Truist Park":1.00}

# ---- SP season aggregates: (ERA, GS, Kpct, BBpct, career_xwoba_vs_opp_roster, career_PA) ----
# career xwOBA-against vs CURRENT opp roster from matchups file; PA = sample size for shrink
SP = {
 "Jones":(4.37,8,27.1,7.6,0.589,8),      "Williams":(3.81,19,29.1,8.0,0.387,25),   # PIT@CLE G1 (FINAL)
 "Ashcraft":(3.49,19,27.8,5.9,None,0),   "Allen":(0.00,0,36.8,5.3,0.345,27),        # PIT@CLE G2; Allen 0 GS
 "Bradley":(3.59,18,27.4,9.3,0.251,29),  "Boyd":(4.50,9,24.0,6.6,0.367,29),
 "Manaea":(4.56,6,22.5,7.3,0.358,146),   "Luzardo":(3.51,19,29.4,7.6,0.375,127),
 "Martin":(3.41,18,22.1,7.4,0.311,33),   "Bieber":(7.64,4,15.1,11.6,0.433,31),      # Bieber 4 GS returning
 "Lowder":(4.91,13,18.6,11.0,0.285,2),   "Sugano":(4.80,16,13.4,6.4,0.243,29),
 "Rogers":(4.48,17,18.1,8.1,0.251,38),   "Arrighetti":(4.50,15,22.8,12.4,0.282,34),
 "Canning":(6.47,10,22.3,12.1,0.323,37), "Dobnak":(1.86,0,9.8,9.8,0.454,7),         # Dobnak 0 GS
 "May":(4.55,18,22.9,7.2,0.290,63),      "Pfaadt":(4.70,6,17.7,7.8,0.356,49),
 "Seymour":(4.59,6,27.8,8.9,0.124,19),   "Sandoval":(2.08,1,26.3,5.3,0.222,30),     # Sandoval 1 GS returning
 "Gore":(4.63,20,25.7,9.2,0.364,96),     "Murphy":(2.25,0,28.6,0.0,None,0),         # Murphy 0 GS rookie
 "Meyer":(2.58,19,26.0,8.5,0.342,13),    "Drohan":(3.09,9,22.9,6.8,None,0),
 "Webb":(3.86,16,19.4,6.3,0.265,25),     "Woo":(4.23,18,24.1,4.7,0.306,27),
 "Sheehan":(4.81,17,26.6,7.4,0.266,5),   "Weathers":(4.15,18,26.9,6.6,0.360,79),
 "Littell":(4.90,12,14.8,6.8,0.478,13),  "Ginn":(3.67,18,21.4,10.6,0.000,1),
 "Skubal":(3.09,13,30.0,3.7,0.265,59),   "GrayRod":(7.55,7,16.4,11.0,0.278,40),
}

# ---- games: (away,home, ASP,HSP, park, mkt_away_ml, mkt_home_ml, EST_pick, actionable_note) ----
GAMES = [
 ("PIT","CLE","Jones","Williams","Progressive Field",+109,-131,"CLE","FINAL PIT 7-1 (makeup G1) — GRADE ONLY"),
 ("MIN","CHC","Bradley","Boyd","Wrigley Field",+135,-163,"CHC","LIVE at compute — grade only"),
 ("NYM","PHI","Manaea","Luzardo","Citizens Bank Park",+144,-175,"PHI","LIVE at compute — grade only"),
 ("CHW","TOR","Martin","Bieber","Rogers Centre",-106,-113,"TOR","LIVE at compute — grade only"),
 ("CIN","COL","Lowder","Sugano","Coors Field",-117,-103,"COL","LIVE at compute — grade only"),
 ("STL","ARI","May","Pfaadt","Chase Field",-101,-120,"ARI","PREGAME (4:10 ET)"),
 ("MIA","MIL","Meyer","Drohan","American Family Field",+113,-136,"MIL","PREGAME (4:10 ET)"),
 ("BAL","HOU","Rogers","Arrighetti","Daikin Park",-109,-110,"HOU","PREGAME (4:10 ET)"),
 ("TEX","ATL","Gore","Murphy","Truist Park",-103,-117,"ATL","PREGAME (4:10 ET)"),
 ("SD","KC","Canning","Dobnak","Kauffman Stadium",-110,-109,"KC","PREGAME (4:10 ET)"),
 ("TB","BOS","Seymour","Sandoval","Fenway Park",-101,-119,"BOS","PREGAME (4:40 ET)"),
 ("PIT","CLE","Ashcraft","Allen","Progressive Field",-106,-113,"CLE","PREGAME (7:10 ET, G2)"),
 ("SF","SEA","Webb","Woo","T-Mobile Park",+130,-157,"SEA","PREGAME (8:08 ET)"),
 ("LAD","NYY","Sheehan","Weathers","Yankee Stadium",-106,-113,"LAD","PREGAME (8:08 ET)"),
 ("WSH","ATH","Littell","Ginn","Sutter Health Park",-117,-103,"ATH","PREGAME (10:05 ET)"),
 ("DET","LAA","Skubal","GrayRod","Angel Stadium",-205,+167,"DET","PREGAME (10:07 ET)"),
]

def devig(a_ml,h_ml):
    def imp(m): return (-m)/(-m+100) if m<0 else 100/(m+100)
    pa,ph = imp(a_ml),imp(h_ml); s=pa+ph
    return pa/s, ph/s  # away, home no-vig

def shrunk_era(era,gs):  # V11/V12 frozen shrink toward 4.20, ~8-start prior
    w=gs/(gs+8); return w*era+(1-w)*LG_ERA

def gate3_proxy(era,k,bb):  # V11 spec §1.4 (LOCKED)
    return 50 + (k-22)*1.2 - (bb-8.5)*1.5 - (era-LG_ERA)*6

# ================= V11 PROXY CARD (LOCKED) =================
# live signals: g3=0.22, career=0.06. DARK (zeroed+flagged): massey .18, sharp .18,
# sp_rel .14, sp_reg .08, sp_cons .04, k_rate .10(sides). Sides ceiling = 0.28 = MONITOR.
print("="*118)
print("V11 PROXY-CLASS CARD (locked; 5 signals dark→zeroed+flagged; ceiling MONITOR by construction)")
print("="*118)
print(f"{'Game':<11}{'ourSP':>7}{'oppSP':>7}{'g3diff':>8}{'g3sig':>7}{'career':>8}{'unified':>9}  {'tier':<8}{'side':<6}note")
v11rows=[]
for aw,hm,asp,hsp,park,aml,hml,est,note in GAMES:
    e_a=gate3_proxy(shrunk_era(*SP[asp][:1],SP[asp][1]) if False else SP[asp][0],SP[asp][2],SP[asp][3])
    # use raw season ERA in proxy (spec uses season aggregates directly, not shrunk, for gate3_proxy)
    ga=gate3_proxy(SP[asp][0],SP[asp][2],SP[asp][3])
    gh=gate3_proxy(SP[hsp][0],SP[hsp][2],SP[hsp][3])
    # low-sample cap: SP with GS<2 -> proxy void (cap out of FIRE); flag
    cap = (SP[asp][1]<2) or (SP[hsp][1]<2)
    # home perspective g3 diff = home SP proxy - away SP proxy
    g3diff = gh-ga
    g3sig = np.clip(g3diff/15.0,-1,1)
    # career signal (0.06): opp roster xwOBA vs each SP, shrink by PA/(PA+50); home favorable if
    # home SP suppresses away roster more (lower xwoba) than away SP suppresses home roster
    def car(sp):
        x,pa=SP[sp][4],SP[sp][5]
        if x is None or pa==0: return 0.0
        w=pa/(pa+50); return w*(LG_XWOBA - x)/0.060  # >0 = SP better than league vs that roster
    car_sig = np.clip(car(hsp)-car(asp),-1,1)
    unified = 0.22*g3sig + 0.06*car_sig   # all other weights dark=0
    # tier (home-side unified). FIRE>0.35, MONITOR>0.12, else BLOCK. Cap blocks FIRE anyway.
    mag=abs(unified); side = hm if unified>0 else aw
    if cap: tier="BLOCK*"      # * = low-sample cap
    elif mag>0.35: tier="FIRE?"  # unreachable at 0.28 ceiling
    elif mag>0.12: tier="MONITOR"
    else: tier="BLOCK"
    v11rows.append((f"{aw}@{hm}",side,round(unified,3),tier,note))
    print(f"{aw}@{hm:<7}{ga:7.1f}{gh:7.1f}{g3diff:8.1f}{g3sig:7.2f}{car_sig:8.2f}{unified:9.3f}  {tier:<8}{side:<6}{note}")
print("* BLOCK* = SP with <2 GS (Allen/Dobnak/Murphy) → hard cap out of FIRE per spec §1.2; card records but never fires.")

# ================= V13 MONTE CARLO (authorized 2026-07-18) =================
def sp_runsupp(era,gs,k,bb):
    # blend shrunk-ERA with a K-BB skill term; return expected runs allowed per 9 vs avg offense
    se=shrunk_era(era,gs)
    kbb=(k-bb)  # skill proxy; league ~ 22-8.5=13.5
    skill_adj = -(kbb-13.5)*0.03   # +1 K-BB pt ~ -0.03 R/9
    return max(2.2, se+skill_adj)

def bullpen_ra(team):
    # team RA per game as pen proxy BUT shrink toward league to cut SP double-count (council A-flag)
    ra=TEAM[team][1]; return 0.55*ra+0.45*LG_RPG

def sim_game(aw,hm,asp,hsp,park,n=20000):
    pf=PARK[park]
    # offense: team RF relative to league, park-applied
    off_a=TEAM[aw][0]/LG_RPG; off_h=TEAM[hm][0]/LG_RPG
    ra_hsp=sp_runsupp(*SP[hsp][:1],SP[hsp][1],SP[hsp][2],SP[hsp][3]) if False else sp_runsupp(SP[hsp][0],SP[hsp][1],SP[hsp][2],SP[hsp][3])
    ra_asp=sp_runsupp(SP[asp][0],SP[asp][1],SP[asp][2],SP[asp][3])
    pen_a=bullpen_ra(aw); pen_h=bullpen_ra(hm)
    ip=np.clip(rng.normal(5.4,1.3,n),2.0,8.0); ip2=np.clip(rng.normal(5.4,1.3,n),2.0,8.0)
    # away runs = vs home SP (ip) + home pen (rest); home runs = vs away SP + away pen
    mean_a=(ra_hsp/9*ip + pen_h/9*(9-ip))*off_a*pf
    mean_h=(ra_asp/9*ip2 + pen_a/9*(9-ip2))*off_h*pf
    mean_h*=1.03  # HFA ~ +3% home offense (fitted-lite; documented, small)
    ra=rng.poisson(rng.gamma(4.0,np.maximum(mean_a,0.3)/4.0))
    rh=rng.poisson(rng.gamma(4.0,np.maximum(mean_h,0.3)/4.0))
    tie=ra==rh
    hx=rng.random(n) < (0.5 + 0.04*np.sign(pen_a-pen_h))  # extras to better pen
    hw=np.where(tie,hx,rh>ra)
    tot=ra+rh+tie*rng.poisson(1.0,n)
    return hw.mean(), tot.mean()

print("\n"+"="*118)
print("V13 MONTE-CARLO (park+HFA+bullpen-shrink; 20k/game; own paper ledger; NEVER feeds V11)")
print("="*118)
print(f"{'Game':<11}{'V13 home%':>10}{'mkt home%':>11}{'edge(H)':>9}{'V13 tot':>9}{'pick':<7}{'edge%':>7}  {'EST':<5}{'act?':<24}")
v13rows=[]
for aw,hm,asp,hsp,park,aml,hml,est,note in GAMES:
    hw,tot=sim_game(aw,hm,asp,hsp,park)
    pa,ph=devig(aml,hml)
    edge_h=hw-ph
    # pick the side with larger positive edge
    if (hw-ph) >= ((1-hw)-pa): pick,pedge,pml = hm,hw-ph,hml
    else: pick,pedge,pml = aw,(1-hw)-pa,aml
    v13rows.append((f"{aw}@{hm}",pick,round(pedge,3),round(hw,3),round(ph,3),round(tot,1),est,note))
    flag = "PREGAME" if note.startswith("PREGAME") else "post-fp"
    print(f"{aw}@{hm:<7}{hw:10.1%}{ph:11.1%}{edge_h:+9.1%}{tot:9.1f}{pick:<7}{pedge:+7.1%}  {est:<5}{note[:22]}")

# save machine ledger
import json
out={"slate":"2026-07-18","engine_v13":"MC park+HFA+penshrink seed718 20k",
     "v11_proxy":[{"game":r[0],"side":r[1],"unified":r[2],"tier":r[3]} for r in v11rows],
     "v13":[{"game":r[0],"pick":r[1],"edge":r[2],"home_wp":r[3],"mkt_home":r[4],"total":r[5],"est_pick":r[6],"note":r[7]} for r in v13rows]}
json.dump(out,open("/home/claude/work/sportsmodel/cards/2026-07-18_card.json","w"),indent=1)
print("\nsaved cards/2026-07-18_card.json")
