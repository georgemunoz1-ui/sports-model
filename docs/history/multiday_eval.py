"""Multi-day V12-MC-P evaluation 7/8-7/12/2026.
7/8: SP-informed (already run, seed 78) — graded prior.
7/9: SP-informed, PREDICTION-CLASS retro: SP season stats from DK doc dated 7/8 (pregame),
     FD pregame lines, finals from Savant export. No look-ahead.
7/10-12: TEAM-ONLY variant (team RF/RA as of 7/8, all SPs = league prior 4.20).
     Weaker engine, labeled; lines unavailable except partial 7/10 -> Brier vs outcomes only.
"""
import numpy as np, json
rng = np.random.default_rng(79)
LG=4.55
T={"CHC":(5.1,4.5),"BAL":(4.5,4.9),"ATH":(4.6,5.4),"DET":(4.2,4.1),"ATL":(4.9,3.9),
"PIT":(5.3,4.8),"SEA":(4.1,3.8),"MIA":(4.6,4.3),"NYY":(4.8,3.9),"TB":(4.5,4.2),
"HOU":(4.6,5.0),"WSH":(5.4,5.3),"PHI":(4.4,4.5),"CIN":(4.1,4.8),"KC":(4.3,5.1),
"NYM":(4.1,4.8),"CLE":(3.9,4.1),"MIN":(4.9,5.1),"BOS":(4.1,4.0),"CWS":(4.8,4.6),
"MIL":(5.1,3.6),"STL":(4.6,4.5),"LAA":(4.4,5.1),"TEX":(4.1,4.2),"AZ":(4.2,4.5),
"SD":(3.9,4.4),"COL":(4.9,5.7),"LAD":(5.3,3.6),"TOR":(4.0,4.5),"SF":(4.1,4.8)}
def shrunk(era,gs): w=gs/(gs+8); return w*era+(1-w)*4.20
def sim(away,home,ea,eh,n=10000):
    ofa=T[away][0]/LG; ofh=T[home][0]/LG
    pena=max(T[away][1],3.0); penh=max(T[home][1],3.0)
    ip1=np.clip(rng.normal(5.5,1.2,n),2.5,8.0); ip2=np.clip(rng.normal(5.5,1.2,n),2.5,8.0)
    m1=eh/9*ip1*ofa+penh/9*(9-ip1)*ofa*0.95
    m2=ea/9*ip2*ofh+pena/9*(9-ip2)*ofh*0.95
    ra=rng.poisson(rng.gamma(3.5,np.maximum(m1,0.3)/3.5))
    rh=rng.poisson(rng.gamma(3.5,np.maximum(m2,0.3)/3.5))
    tie=ra==rh; hx=rng.random(n)<(0.5+0.05*np.sign(pena-penh))
    return np.where(tie,hx,rh>ra).mean()
def mp(ml): ml=int(ml); return (-ml)/(-ml+100) if ml<0 else 100/(ml+100)

# ---- 7/9 PREDICTION-CLASS: (away,home,ERA_a,GS_a,ERA_h,GS_h, home_ml_FD, away_win_actual)
# ERA/GS from DK 7/9 probables (doc2, pregame); FD lines (fetched); finals (Savant export)
d9=[("ATL","PIT",4.01,16,5.02,18,None,1,("ATL",-112)),  # FD: ATL -112/PIT -104 (away fav)
    ("KC","NYM",3.45,17,5.16,15,-136,0,None),
    ("NYY","TB",None,0,None,0,-148,1,None),  # Rasmussen/Blackburn not in DK doc -> league prior both, flag
    ("CHC","BAL",6.75,18,4.70,17,-130,0,None),
    ("CLE","MIN",3.89,17,4.60,12,None,1,("CLE",-124)),  # CLE away fav -124 (FD lists Guardians -124)
    ("BOS","CWS",None,0,4.39,15,-110,1,None),  # Sandoval no 2026 line in DK doc -> prior; CWS -110
    ("ATH","DET",6.75,10,4.29,18,-126,0,None),
    ("SEA","MIA",1.71,10,4.80,15,None,0,("SEA",-132)),  # SEA away fav -132; MIA won
    ("PHI","CIN",3.75,17,5.03,17,None,1,("PHI",-172)),  # PHI away fav; PHI won 1-0
    ("MIL","STL",2.74,8,3.60,18,None,1,("MIL",-130)),   # MIL away fav; MIL won 8-4
    ("LAA","TEX",4.13,14,4.02,18,-134,0,None),          # TEX won 7-6
    ("AZ","SD",5.71,17,6.71,12,-126,1,None),            # AZ won 3-1
    ("COL","SF",None,0,4.27,17,-126,0,None)]            # Whisenhunt no line->prior; SF won 8-2
# actual away wins col7: ATL 10-5 W=1, KC 3-7 L=0, NYY 12-4 W=1, CHC 2-3 L=0, CLE 5-2 W=1,
# BOS 2-1 W=1, ATH 1-4 L=0, SEA 4-8 L=0, PHI 1-0 W=1, MIL 8-4 W=1, LAA 6-7 L=0, AZ 3-1 W=1, COL 2-8 L=0

print("=== 7/9 SP-informed (prediction-class) ===")
briers=[]; edges=[]
for away,home,ea_,ga,eh_,gh,hml,awin,awayfav in d9:
    ea = shrunk(ea_,ga) if ea_ else 4.20
    eh = shrunk(eh_,gh) if eh_ else 4.20
    hw = sim(away,home,ea,eh)
    aw = 1-hw
    if hml: mkt_h = mp(hml); edge = hw - mkt_h; side=home; sim_side=hw; won = (1-awin)
    else: ml=awayfav[1]; mkt_a=mp(ml); edge = aw-mkt_a; side=away; sim_side=aw; won = awin
    briers.append((aw - awin)**2)
    edges.append((f"{away}@{home}",side,round(edge,3),bool(won)))
    print(f"{away}@{home:<4} simA {aw:.1%} actualA {awin}  mktfav {side} edge{edge:+.1%}")
print(f"Brier(SP-informed 7/9, away-win basis): {np.mean(briers):.4f} vs coin 0.25")
print(">5% edges:", [e for e in edges if abs(e[2])>0.05])

# ---- 7/10-7/12 TEAM-ONLY (all SPs league prior) — Brier calibration only
sched = {
"7/10":[("PHI","DET",0),("NYY","WSH",1),("KC","BAL",0),("CHC","CIN",0),("SEA","TB",0),
        ("CLE","MIA",1),("BOS","NYM",1),("ATH","CWS",0),("HOU","TEX",0),("LAA","MIN",1),
        ("ATL","STL",0),("TOR","SD",1),("AZ","LAD",1),("COL","SF",1)],
"7/11":[("LAA","MIN",0),("ATH","CWS",0),("COL","SF",0),("NYY","WSH",1),("BOS","NYM",1),
        ("SEA","TB",0),("CLE","MIA",1),("PHI","DET",1),("KC","BAL",0),("HOU","TEX",1),
        ("CHC","CIN",1),("ATL","STL",0),("TOR","SD",0),("AZ","LAD",1)],
"7/12":[("KC","BAL",0),("NYY","WSH",1),("CHC","CIN",1),("BOS","NYM",1),("SEA","TB",1),
        ("PHI","DET",1),("CLE","MIA",1),("LAA","MIN",0),("ATH","CWS",0),("ATL","STL",1),
        ("HOU","TEX",0),("COL","SF",0),("AZ","LAD",1),("TOR","SD",0)]}
# away-win flags from extracted finals (MIL/PIT doubleheader 7/11 excluded: split 0/1... include both:
# 7/11 MIL@PIT G1 6-7 L, G2 2-3 L -> two entries
sched["7/11"] += [("MIL","PIT",0),("MIL","PIT",0)]
sched["7/12"] += [("MIL","PIT",0)]

print("\n=== 7/10-7/12 TEAM-ONLY shadow (league-prior SPs) ===")
allb=[]
for d,games in sched.items():
    b=[]
    for away,home,awin in games:
        aw = 1-sim(away,home,4.20,4.20)
        b.append((aw-awin)**2)
    print(f"{d}: n={len(games)} Brier {np.mean(b):.4f}")
    allb+=b
print(f"Team-only 3-day Brier: {np.mean(allb):.4f} (n={len(allb)}) vs coin 0.25")
