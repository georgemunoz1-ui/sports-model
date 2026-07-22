"""Pitcher-Index test — does it move the needle vs V13.1 base? Backtest on 7/18 (n=14; the slate
where we have BOTH career-vs-roster xwOBA splits AND finals). Three run-suppression variants:
  BASE   = V13.1 (shrunk ERA + small K-BB nudge)
  SKILL  = 50/50 blend of shrunk-ERA and kwERA (=5.40-12*(K-BB)); de-noises ERA (Bieber case)
  SKILL+MATCHUP = SKILL x career-vs-roster xwOBA tilt, HEAVILY shrunk by PA (Holmes/Littell case)
Weights chosen by principle, NOT fit on n=14 (that would overfit — the reference model's own caveat).
"""
import numpy as np
rng=np.random.default_rng(1319)
LG_RPG=4.45; LG_ERA=4.20; LG_K=22.0; LG_BB=8.5; LG_BIP=1-(LG_K+LG_BB)/100; LG_XW=0.320
TEAM={"PIT":(5.3,4.9),"CLE":(3.9,3.9),"MIN":(4.9,5.0),"CHC":(5.0,4.5),"NYM":(4.1,4.7),
 "PHI":(4.3,4.5),"CHW":(4.9,4.4),"TOR":(4.1,4.5),"CIN":(4.2,4.8),"COL":(4.7,5.7),
 "BAL":(4.6,4.8),"HOU":(4.6,5.0),"SD":(4.0,4.4),"KC":(4.3,5.2),"STL":(4.5,4.4),
 "ARI":(4.3,4.5),"TB":(4.5,4.3),"BOS":(4.2,3.8),"TEX":(4.1,4.4),"ATL":(4.9,3.8),
 "MIA":(4.5,4.3),"MIL":(5.1,3.8),"SF":(4.1,4.7),"SEA":(4.0,3.9),"LAD":(5.2,3.7),
 "NYY":(4.8,3.8),"WSH":(5.5,5.2),"ATH":(4.4,5.7),"DET":(4.2,4.0),"LAA":(4.4,5.0)}
PARK={"Coors Field":1.18,"Fenway Park":1.03,"Yankee Stadium":1.02,"T-Mobile Park":0.92,
 "Kauffman Stadium":1.00,"Daikin Park":1.01,"Rogers Centre":1.01,"Wrigley Field":1.00,
 "Angel Stadium":0.97,"Sutter Health Park":1.06,"American Family Field":1.00,
 "Progressive Field":0.98,"Citizens Bank Park":1.04,"Chase Field":1.01,"Truist Park":1.00}
# SP: ERA,GS,K%,BB%, career_xwoba_vs_opp_roster, PA
SP={"Jones":(4.37,8,27.1,7.6,.589,8),"Williams":(3.81,19,29.1,8.0,.387,25),
 "Bradley":(3.59,18,27.4,9.3,.251,29),"Boyd":(4.50,9,24.0,6.6,.367,29),
 "Manaea":(4.56,6,22.5,7.3,.358,146),"Luzardo":(3.51,19,29.4,7.6,.375,127),
 "Martin":(3.41,18,22.1,7.4,.311,33),"Bieber":(7.64,4,15.1,11.6,.433,31),
 "Lowder":(4.91,13,18.6,11.0,.285,2),"Sugano":(4.80,16,13.4,6.4,.243,29),
 "Rogers":(4.48,17,18.1,8.1,.251,38),"Arrighetti":(4.50,15,22.8,12.4,.282,34),
 "Canning":(6.47,10,22.3,12.1,.323,37),"May":(4.55,18,22.9,7.2,.290,63),
 "Pfaadt":(4.70,6,17.7,7.8,.356,49),"Seymour":(4.59,6,27.8,8.9,.124,19),
 "Sandoval":(2.08,1,26.3,5.3,.222,30),"Gore":(4.63,20,25.7,9.2,.364,96),
 "Murphy":(2.25,0,28.6,0.0,None,0),"Meyer":(2.58,19,26.0,8.5,.342,13),
 "Drohan":(3.09,9,22.9,6.8,None,0),"Webb":(3.86,16,19.4,6.3,.265,25),
 "Woo":(4.23,18,24.1,4.7,.306,27),"Sheehan":(4.81,17,26.6,7.4,.266,5),
 "Weathers":(4.15,18,26.9,6.6,.360,79),"Littell":(4.90,12,14.8,6.8,.478,13),
 "Ginn":(3.67,18,21.4,10.6,.000,1),"Skubal":(3.09,13,30.0,3.7,.265,59),
 "GrayRod":(7.55,7,16.4,11.0,.278,40)}
def shrunk(era,gs): w=gs/(gs+8); return w*era+(1-w)*LG_ERA
def rs_base(sp):
    era,gs,k,bb,_,_=SP[sp]; return max(2.2, shrunk(era,gs)-((k-bb)-13.5)*0.03)
def rs_skill(sp):
    era,gs,k,bb,_,_=SP[sp]; kw=5.40-12*((k-bb)/100); return max(2.2, 0.5*shrunk(era,gs)+0.5*kw)
def rs_matchup(sp):
    era,gs,k,bb,xw,pa=SP[sp]; base=rs_skill(sp)
    if xw is None or pa==0: return base
    tilt=1+(xw/LG_XW-1)*(pa/(pa+150))*0.6; return max(2.2, base*tilt)
def pen(t): return 0.55*TEAM[t][1]+0.45*LG_RPG
def bip(k,bb): return max(0.45,1-(k+bb)/100)
def sim(aw,hm,asp,hsp,park,rsfn,n=40000):
    pf=PARK[park]; oa=TEAM[aw][0]/LG_RPG; oh=TEAM[hm][0]/LG_RPG
    rah=rsfn(hsp); raa=rsfn(asp); pa,ph_=pen(aw),pen(hm)
    pfa=1+(pf-1)*(bip(SP[hsp][2],SP[hsp][3])/LG_BIP); pfh=1+(pf-1)*(bip(SP[asp][2],SP[asp][3])/LG_BIP)
    ip=np.clip(rng.normal(5.4,1.3,n),2,8); ip2=np.clip(rng.normal(5.4,1.3,n),2,8)
    ma=(rah/9*ip+ph_/9*(9-ip))*oa*pfa; mh=(raa/9*ip2+pa/9*(9-ip2))*oh*pfh*1.03
    sa=np.clip(1.8+(SP[hsp][2]-LG_K)*0.16,1.2,6); sh=np.clip(1.8+(SP[asp][2]-LG_K)*0.16,1.2,6)
    ra=rng.poisson(rng.gamma(sa,np.maximum(ma,0.3)/sa)); rh=rng.poisson(rng.gamma(sh,np.maximum(mh,0.3)/sh))
    tie=ra==rh; hx=rng.random(n)<(0.5+0.04*np.sign(pa-ph_)); hw=np.where(tie,hx,rh>ra); mg=rh-ra
    return hw.mean(), np.mean(mg<=-5) if hw.mean()>=.5 else np.mean(mg>=5)
BT=[("PIT","CLE","Jones","Williams","Progressive Field",7,1),
 ("MIN","CHC","Bradley","Boyd","Wrigley Field",2,6),("NYM","PHI","Manaea","Luzardo","Citizens Bank Park",1,6),
 ("CHW","TOR","Martin","Bieber","Rogers Centre",0,1),("CIN","COL","Lowder","Sugano","Coors Field",3,10),
 ("STL","ARI","May","Pfaadt","Chase Field",3,5),("MIA","MIL","Meyer","Drohan","American Family Field",6,8),
 ("BAL","HOU","Rogers","Arrighetti","Daikin Park",4,2),("TEX","ATL","Gore","Murphy","Truist Park",7,6),
 ("TB","BOS","Seymour","Sandoval","Fenway Park",6,7),("SF","SEA","Webb","Woo","T-Mobile Park",3,4),
 ("WSH","ATH","Littell","Ginn","Sutter Health Park",1,15),("DET","LAA","Skubal","GrayRod","Angel Stadium",7,0)]
# (SD@KC, Dobnak capped -> excluded from this SP-index test)
def grade(rsfn):
    br=[]; dw=dl=0; blow_flag=0
    for aw,hm,asp,hsp,pk,as_,hs in BT:
        hw,prisk=sim(aw,hm,asp,hsp,pk,rsfn); yb=1 if hs>as_ else 0
        br.append((hw-yb)**2)
        pick_home=hw>=.5; won=(pick_home and yb) or ((not pick_home) and not yb); dw+=won; dl+=(not won)
    return np.mean(br),dw,dl
print("="*80); print("PITCHER-INDEX TEST — 7/18 backtest (n=13, Dobnak-capped game excluded)"); print("="*80)
for name,fn in [("BASE (V13.1)",rs_base),("SKILL (kwERA blend)",rs_skill),("SKILL+MATCHUP tilt",rs_matchup)]:
    b,w,l=grade(fn); print(f"  {name:<22} Brier {b:.4f} | directional {w}-{l}")
print("\nCASE CHECKS (home-win% by variant):")
for g in [("CHW","TOR","Martin","Bieber","Rogers Centre","Bieber 7.64ERA but kwERA~5.0; CWS lost 0-1"),
          ("WSH","ATH","Littell","Ginn","Sutter Health Park","Littell .478 xwOBA vs ATH(13PA); lost 1-15"),
          ("TEX","ATL","Gore","Murphy","Truist Park","Murphy no-matchup; TEX won 7-6")]:
    aw,hm,asp,hsp,pk,note=g
    hb=sim(aw,hm,asp,hsp,pk,rs_base)[0]; hs=sim(aw,hm,asp,hsp,pk,rs_skill)[0]; hm2=sim(aw,hm,asp,hsp,pk,rs_matchup)[0]
    print(f"  {aw}@{hm}: base {hb:.0%} -> skill {hs:.0%} -> +matchup {hm2:.0%}   [{note}]")
