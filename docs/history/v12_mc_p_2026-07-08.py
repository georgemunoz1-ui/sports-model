"""V12-MC-P (parametric variant) — July 8 2026 — SHADOW ONLY, NOT V12-MC v2.
Inputs: SP ERA/K%/BB%/GS, team RF/RA per game (season aggregates, doc3).
Construction: clipped-normal IP (~5.5,1.2); gamma-Poisson SP runs (shrunk ERA x opp
offense); bullpen via team RA proxy (0.95 factor) over remaining IP; extras via
coinflip weighted by pen quality. NO walk-off truncation (ML win% unaffected;
run-line/margin outputs would be invalid — do not use them).
Shrinkage: SP ERA -> GS/(GS+8) toward league 4.20 (~50-IP prior).
Variance: k=3.5 dispersion (assumed, not resampled).
Caveats: team RA double-counts quality pens; totals lean Under slate-wide ->
relative leans only.
Calibration check (2026-07-08): shadow totals avg 0.6 below market; absolute Under
leans quarantined; only ML edges >5% monitored w/ relative-total rank. Re-estimate
offset/threshold once graded sample exists.
Separation: NEVER merges with V11/V12-v2 audited ledger. Seed=78, 10k sims/game."""
import numpy as np
rng = np.random.default_rng(78)
LG = 4.55  # league runs/team/game approx from doc3 RF averages

# team: (RF, RA) from doc 3
T = {"CHC":(5.1,4.5),"BAL":(4.5,4.9),"ATH":(4.6,5.4),"DET":(4.2,4.1),
     "ATL":(4.9,3.9),"PIT":(5.3,4.8),"SEA":(4.1,3.8),"MIA":(4.6,4.3),
     "NYY":(4.8,3.9),"TB":(4.5,4.2),"HOU":(4.6,5.0),"WSH":(5.4,5.3),
     "PHI":(4.4,4.5),"CIN":(4.1,4.8),"KC":(4.3,5.1),"NYM":(4.1,4.8),
     "CLE":(3.9,4.1),"MIN":(4.9,5.1),"BOS":(4.1,4.0),"CWS":(4.8,4.6),
     "MIL":(5.1,3.6),"STL":(4.6,4.5),"LAA":(4.4,5.1),"TEX":(4.1,4.2),
     "AZ":(4.2,4.5),"SD":(3.9,4.4),"COL":(4.9,5.7),"LAD":(5.3,3.6)}

SP = {"Rea":(4.74,14),"Kremer":(3.18,3),"Springs":(5.79,18),"Melton":(2.05,7),
 "Holmes":(3.83,16),"Jones":(5.28,7),"Kirby":(3.81,17),"Phillips":(3.52,7),
 "Cole":(4.01,8),"McClanahan":(3.05,16),"Arrighetti":(3.81,14),"Griffin":(2.87,18),
 "Rangel":(3.38,1),"Burns":(2.40,17),"Cecconi":(4.44,18),"Prielipp":(4.96,12),
 "Bennett":(3.10,7),"Martin":(3.08,17),"Harrison":(2.82,16),"McGreevy":(3.12,17),
 "Urena":(3.03,14),"Gore":(4.31,18),"Cabrera":(4.72,3),"King":(5*0+3.52,18),
 "Hughes":(4.20,0),"Sasaki":(5.40,15),  # Hughes: pure league prior, 0 weight
 "CruzOrDobnak":(4.20,0)}  # unresolved starter -> league prior, flagged

def shrunk(era,gs): w=gs/(gs+8); return w*era+(1-w)*4.20

def negbin(mean,k=3.5,size=1): p=k/(k+mean); return rng.negative_binomial(k,p,size)

def sim_game(away,home,asp,hsp,n=10000):
    ea,eh = shrunk(*SP[asp]), shrunk(*SP[hsp])
    ofa = T[away][0]/LG; ofh = T[home][0]/LG
    pena = max(T[away][1]-  0.0,3.0); penh = max(T[home][1],3.0)  # team RA as pen proxy
    ip_sp = np.clip(rng.normal(5.5,1.2,n),2.5,8.0)
    # away offense vs home SP + home pen
    m1 = eh/9*ip_sp*ofa + penh/9*(9-ip_sp)*ofa*0.95
    ip_sp2 = np.clip(rng.normal(5.5,1.2,n),2.5,8.0)
    m2 = ea/9*ip_sp2*ofh + pena/9*(9-ip_sp2)*ofh*0.95
    ra = negbin(np.maximum(m1,0.5).mean(),size=n)*0  # vectorize properly below
    # per-sim negbin with varying mean: use poisson-gamma
    ra = rng.poisson(rng.gamma(3.5, np.maximum(m1,0.3)/3.5))
    rh = rng.poisson(rng.gamma(3.5, np.maximum(m2,0.3)/3.5))
    tie = ra==rh
    # extras: 55/45 to better pen (lower RA)
    homewin_x = rng.random(n) < (0.5 + 0.05*np.sign(pena-penh))
    hw = np.where(tie, homewin_x, rh>ra)
    total = ra+rh + tie*rng.poisson(1.1,n)  # extras add runs
    return hw.mean(), total

def ml_prob(ml):
    ml=int(ml); return (-ml)/(-ml+100) if ml<0 else 100/(ml+100)

games=[("CHC","BAL","Rea","Kremer","-122","home",10.5),
 ("ATH","DET","Springs","Melton","-127","home",9.5),
 ("ATL","PIT","Holmes","Jones","+114","away",9.5),
 ("SEA","MIA","Kirby","Phillips","-117","away",8.5),
 ("NYY","TB","Cole","McClanahan","-114","home",7.5),
 ("HOU","WSH","Arrighetti","Griffin","-125","home",9.5),
 ("PHI","CIN","Rangel","Burns","-132","home",8.5),
 ("KC","NYM","CruzOrDobnak","Scott_","-180","home",9.5),
 ("CLE","MIN","Cecconi","Prielipp","-117","home",8.5),
 ("BOS","CWS","Bennett","Martin","-101","home",8.5),
 ("MIL","STL","Harrison","McGreevy","-141","away",8.5),
 ("LAA","TEX","Urena","Gore","-125","home",8.0),
 ("AZ","SD","Cabrera","King","-133","home",8.5),
 ("COL","LAD","Hughes","Sasaki","-239","home",9.5)]
SP["Scott_"]=(3.49,11)

print(f"{'Game':<11}{'our':<5}{'mkt%':>6}{'sim%':>6}{'edge':>7}{'simTot':>8}{'line':>6}  note")
for aw,hm,asp,hsp,ml,side,tl in games:
    hw,tot = sim_game(aw,hm,asp,hsp)
    p = hw if side=="home" else 1-hw
    mp = ml_prob(ml)
    note = "STARTER UNRESOLVED" if asp=="CruzOrDobnak" else ("debut/no-data SP" if asp=="Hughes" else "")
    print(f"{aw}@{hm:<7}{(hm if side=='home' else aw):<5}{mp:6.1%}{p:6.1%}{p-mp:+7.1%}{tot.mean():8.2f}{tl:6.1f}  {note}")
