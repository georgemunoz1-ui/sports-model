"""Fit ONE global temperature T to fix V13.1 under-dispersion (p_cal=sigmoid(logit(p)/T)).
Fit on graded 7/17+7/18 (n=27, 1 parameter -> low overfit). Validate: Brier down + dispersion
matches outcomes. Then re-run 7/20 EV card with calibrated probs. Interim; full isotonic awaits backfill enrich."""
import numpy as np, json
rng=np.random.default_rng(99)
LG_RPG=4.45; LG_ERA=4.20; LG_K=22.0; LG_BB=8.5; LG_BIP=1-(LG_K+LG_BB)/100
TEAM={"PIT":(5.3,4.9),"CLE":(3.9,3.9),"MIN":(4.9,5.0),"CHC":(5.0,4.5),"NYM":(4.1,4.7),"PHI":(4.3,4.5),
 "CHW":(4.9,4.4),"TOR":(4.1,4.5),"CIN":(4.2,4.8),"COL":(4.7,5.7),"BAL":(4.6,4.8),"HOU":(4.6,5.0),
 "SD":(4.0,4.4),"KC":(4.3,5.2),"STL":(4.5,4.4),"ARI":(4.3,4.5),"TB":(4.5,4.3),"BOS":(4.2,3.8),
 "TEX":(4.1,4.4),"ATL":(4.9,3.8),"MIA":(4.5,4.3),"MIL":(5.1,3.8),"SF":(4.1,4.7),"SEA":(4.0,3.9),
 "LAD":(5.2,3.7),"NYY":(4.8,3.8),"WSH":(5.5,5.2),"ATH":(4.4,5.7),"DET":(4.2,4.0),"LAA":(4.4,5.0)}
PARK=json.load(open("data/backfill/mlb/2026/park_factors.json"))
CAP=(4.20,0,22.0,8.5)
SP={ # 7/17+7/18
 "McGreevy":(3.01,18,16.5,5.7),"Kelly":(5.38,16,14.4,9.2),"Melton":(1.82,8,21.7,5.8),"Detmers":(4.39,19,27.2,7.7),
 "Cavalli":(3.83,20,25.4,7.4),"Jump":(3.51,9,23.5,7.4),"Roupp":(4.27,18,25.3,10.2),"BMiller":(2.19,9,30.2,4.2),
 "Alcantara":(3.99,20,18.4,6.1),"Henderson":(3.18,6,30.6,6.3),"Singer":(4.72,18,18.9,7.7),"HughesC":(3.00,1,22.9,8.6),
 "Jax":(3.47,14,24.7,8.7),"Bennett":(2.64,8,19.2,4.4),"Kay":(4.23,17,17.6,8.7),"Miles":(2.85,3,23.5,7.8),
 "Kremer":(4.09,4,27.9,4.7),"Lambert":(3.14,15,22.9,9.3),"Sasaki":(5.33,16,22.7,9.4),"Cole":(4.04,9,22.7,5.3),
 "Quantrill":(3.11,4,14.5,6.7),"Sale":(2.20,17,29.0,6.2),"Ober":(4.40,13,17.0,6.3),"Rea":(4.75,15,16.8,8.6),
 "King":(3.41,19,20.8,9.7),"Lugo":(4.56,19,19.1,7.6),"Jones":(4.37,8,27.1,7.6),"Williams":(3.81,19,29.1,8.0),
 "Bradley":(3.59,18,27.4,9.3),"Boyd":(4.50,9,24.0,6.6),"Manaea":(4.56,6,22.5,7.3),"Luzardo":(3.51,19,29.4,7.6),
 "Martin":(3.41,18,22.1,7.4),"Bieber":(7.64,4,15.1,11.6),"Lowder":(4.91,13,18.6,11.0),"Sugano":(4.80,16,13.4,6.4),
 "Rogers":(4.48,17,18.1,8.1),"Arrighetti":(4.50,15,22.8,12.4),"May":(4.55,18,22.9,7.2),"Pfaadt":(4.70,6,17.7,7.8),
 "Seymour":(4.59,6,27.8,8.9),"Sandoval":(2.08,1,26.3,5.3),"Gore":(4.63,20,25.7,9.2),"Murphy":(2.25,0,28.6,0.0),
 "Meyer":(2.58,19,26.0,8.5),"Drohan":(3.09,9,22.9,6.8),"Webb":(3.86,16,19.4,6.3),"Woo":(4.23,18,24.1,4.7),
 "Sheehan":(4.81,17,26.6,7.4),"Weathers":(4.15,18,26.9,6.6),"Littell":(4.90,12,14.8,6.8),"Ginn":(3.67,18,21.4,10.6),
 "Skubal":(3.09,13,30.0,3.7),"GrayRod":(7.55,7,16.4,11.0),
 # 7/20
 "JRyan":(2.85,20,28.4,5.6),"Bibee":(3.90,20,19.0,7.4),"Sanchez":(2.62,20,27.4,4.8),"Ashcraft":(3.49,19,27.8,5.9),
 "Martinez":(2.65,18,14.5,4.4),"Cease":(2.56,17,36.9,11.0),"Baz":(4.19,19,20.5,8.7),"Tolle":(3.11,15,25.5,7.3),
 "Sears":(5.03,4,19.8,9.3),"Elder":(4.12,18,19.8,7.4),"Peralta":(4.66,20,22.3,9.4),"Misiorowski":(1.62,18,39.6,6.4),
 "Fedde":(4.15,9,15.4,9.0),"deGrom":(3.49,18,30.4,5.5),"Flaherty":(4.48,18,26.4,10.8),"Taillon":(5.19,13,20.6,8.0),
 "Junk":(4.57,12,17.4,6.2),"Blanco":CAP,"Mahle":(5.31,15,21.7,9.5),"Wacha":(3.77,19,19.7,7.0),
 "Springs":(6.08,19,19.5,8.6),"Bratt":(6.00,2,10.7,17.9),"Abbott":(4.11,20,18.4,10.5),"Kirby":(3.76,18,21.5,5.3),
 "Leahy":(3.73,18,19.3,8.5),"Soriano":(3.49,20,24.7,11.4)}
CAPPED20={"Blanco","Bratt"}
def shrunk(e,g): w=g/(g+8); return w*e+(1-w)*LG_ERA
def rs(sp): e,g,k,bb=SP[sp]; return max(2.2,shrunk(e,g)-((k-bb)-13.5)*0.03)
def pen(t): return 0.55*TEAM[t][1]+0.45*LG_RPG
def bip(k,bb): return max(0.45,1-(k+bb)/100)
def sim(aw,hm,asp,hsp,park,n=40000):
    pf=PARK.get(park,1.0); oa=TEAM[aw][0]/LG_RPG; oh=TEAM[hm][0]/LG_RPG
    rah=rs(hsp); raa=rs(asp); pa,ph_=pen(aw),pen(hm)
    pfa=1+(pf-1)*(bip(SP[hsp][2],SP[hsp][3])/LG_BIP); pfh=1+(pf-1)*(bip(SP[asp][2],SP[asp][3])/LG_BIP)
    ip=np.clip(rng.normal(5.4,1.3,n),2,8); ip2=np.clip(rng.normal(5.4,1.3,n),2,8)
    ma=(rah/9*ip+ph_/9*(9-ip))*oa*pfa; mh=(raa/9*ip2+pa/9*(9-ip2))*oh*pfh*1.005
    sa=np.clip(1.8+(SP[hsp][2]-LG_K)*0.16,1.2,6); sh=np.clip(1.8+(SP[asp][2]-LG_K)*0.16,1.2,6)
    ra=rng.poisson(rng.gamma(sa,np.maximum(ma,0.3)/sa)); rh=rng.poisson(rng.gamma(sh,np.maximum(mh,0.3)/sh))
    tie=ra==rh; hx=rng.random(n)<(0.5+0.04*np.sign(pa-ph_)); hw=np.where(tie,hx,rh>ra); mg=rh-ra
    return hw.mean(),np.mean(mg>=5),np.mean(mg<=-5)
# pooled graded games: (away,home,asp,hsp,park, home_win)
GR=[("STL","ARI","McGreevy","Kelly","Chase Field",0),("DET","LAA","Melton","Detmers","Angel Stadium",0),
 ("WSH","ATH","Cavalli","Jump","Sutter Health Park",0),("SF","SEA","Roupp","BMiller","T-Mobile Park",0),
 ("MIA","MIL","Alcantara","Henderson","American Family Field",1),("CIN","COL","Singer","HughesC","Coors Field",0),
 ("TB","BOS","Jax","Bennett","Fenway Park",1),("CHW","TOR","Kay","Miles","Rogers Centre",0),
 ("BAL","HOU","Kremer","Lambert","Daikin Park",0),("LAD","NYY","Sasaki","Cole","Yankee Stadium",0),
 ("TEX","ATL","Quantrill","Sale","Truist Park",1),("MIN","CHC","Ober","Rea","Wrigley Field",0),
 ("SD","KC","King","Lugo","Kauffman Stadium",1),
 ("PIT","CLE","Jones","Williams","Progressive Field",0),("MIN","CHC","Bradley","Boyd","Wrigley Field",1),
 ("NYM","PHI","Manaea","Luzardo","Citizens Bank Park",1),("CHW","TOR","Martin","Bieber","Rogers Centre",1),
 ("CIN","COL","Lowder","Sugano","Coors Field",1),("STL","ARI","May","Pfaadt","Chase Field",1),
 ("MIA","MIL","Meyer","Drohan","American Family Field",1),("BAL","HOU","Rogers","Arrighetti","Daikin Park",0),
 ("TEX","ATL","Gore","Murphy","Truist Park",0),("TB","BOS","Seymour","Sandoval","Fenway Park",1),
 ("SF","SEA","Webb","Woo","T-Mobile Park",1),("WSH","ATH","Littell","Ginn","Sutter Health Park",1),
 ("DET","LAA","Skubal","GrayRod","Angel Stadium",0)]
probs=[]; ys=[]
for aw,hm,asp,hsp,pk,y in GR:
    hw,_,_=sim(aw,hm,asp,hsp,pk); probs.append(hw); ys.append(y)
probs=np.array(probs); ys=np.array(ys)
def logit(p): p=np.clip(p,1e-6,1-1e-6); return np.log(p/(1-p))
def sig(x): return 1/(1+np.exp(-x))
def cal(p,T): return sig(logit(p)/T)
def logloss(T):
    pc=cal(probs,T); pc=np.clip(pc,1e-6,1-1e-6); return -np.mean(ys*np.log(pc)+(1-ys)*np.log(1-pc))
Ts=np.arange(0.55,1.31,0.01); best=min(Ts,key=logloss)
def brier(T): return np.mean((cal(probs,T)-ys)**2)
print("="*80); print(f"TEMPERATURE FIT on n={len(ys)} graded games (7/17+7/18), 1 parameter"); print("="*80)
print(f"  Best T = {best:.2f}   (T<1 = widen/less-flat; T>1 = shrink)")
print(f"  Brier:  T=1.00 (raw) {brier(1.0):.4f}  ->  T={best:.2f} {brier(best):.4f}")
print(f"  Dispersion mean|p-.5|: raw {np.mean(np.abs(probs-.5)):.3f} -> cal {np.mean(np.abs(cal(probs,best)-.5)):.3f} | outcomes base {np.mean(np.abs(ys-.5)):.3f}")
print(f"  NOTE: n={len(ys)}, 1 DOF — interim calibration. Full isotonic awaits backfill feature-enrichment.")
# ---- re-run 7/20 with calibration ----
def raw_imp(ml): return (-ml)/(-ml+100) if ml<0 else 100/(ml+100)
def profm(ml): return (100/(-ml)) if ml<0 else (ml/100)
G=[("MIN","CLE","JRyan","Bibee","Progressive Field",-120,106),("LAD","PHI","Sheehan","Sanchez","Citizens Bank Park",118,-134),
 ("PIT","NYY","Ashcraft","Weathers","Yankee Stadium",110,-120),("TB","TOR","Martinez","Cease","Rogers Centre",126,-140),
 ("BAL","BOS","Baz","Tolle","Fenway Park",120,-135),("SD","ATL","Sears","Elder","Truist Park",135,-142),
 ("NYM","MIL","Peralta","Misiorowski","American Family Field",158,-178),("CHW","TEX","Fedde","deGrom","Globe Life Field",143,-162),
 ("DET","CHC","Flaherty","Taillon","Wrigley Field",-108,-108),("MIA","HOU","Junk","Blanco","Daikin Park",122,-135),
 ("SF","KC","Mahle","Wacha","Kauffman Stadium",-106,-110),("ATH","ARI","Springs","Bratt","Chase Field",136,-162),
 ("CIN","SEA","Abbott","Kirby","T-Mobile Park",140,-155),("STL","LAA","Leahy","Soriano","Angel Stadium",105,-120)]
print("\n"+"="*100); print(f"7/20 CARD RE-RUN with calibrated probs (T={best:.2f}) — EV rule, 4pp buffer"); print("="*100)
print(f"{'Game':<9}{'raw H%':>7}{'cal H%':>7}{'side':>6}{'price':>7}{'p_cal':>7}{'edge':>7}{'EV%':>7}{'blow':>6}  CALL")
plays=[]
for aw,hm,asp,hsp,pk,aml,hml in G:
    hw,hblow,ablow=sim(aw,hm,asp,hsp,pk); hwc=cal(hw,best)
    capped=(asp in CAPPED20)or(hsp in CAPPED20)
    cands=[(hm,hml,hwc,ablow),(aw,aml,1-hwc,hblow)]
    side,ml,p,blow=max(cands,key=lambda c:c[2]-raw_imp(c[1])); be=raw_imp(ml); edge=p-be; ev=p*profm(ml)-(1-p)
    if capped: call="CAP"
    elif blow>=0.18: call="GUARDRAIL"
    elif ev>0 and edge>=0.04: call="*** PLAY ***"; plays.append((f"{aw}@{hm}",side,ml,ev,edge,p,be))
    elif ev>0: call="sub-buffer"
    else: call="pass -EV"
    print(f"{aw}@{hm:<5}{hw:7.0%}{hwc:7.0%}{side:>6}{ml:>7}{p:7.0%}{edge:+7.1%}{ev*100:+7.1f}{blow:6.0%}  {call}")
print(f"\nPLAYS after calibration ({len(plays)}):")
for g,s,ml,ev,edge,p,be in sorted(plays,key=lambda x:-x[3]): print(f"  {g:<9} {s:<4} {ml:+d}  EV {ev*100:+.1f}%  p={p:.0%} vs b/e {be:.0%}")
favs=sum(1 for g,s,ml,ev,edge,p,be in plays if ml<0)
print(f"  favorites among plays: {favs}/{len(plays)}  (was 0/5 pre-calibration — balance is the validation signal)")
