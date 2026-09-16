"""
V13.1 — cloud-native MC, doctrine-aligned (Taco 2026-07-18).
Changes vs V13.0:
  (1) K-DRIVEN VARIANCE: the gamma shape for a team's runs depends on the OPPOSING starter's K%.
      High-K arm faced -> tight, low-scoring dist. Low-K contact arm faced -> FAT-TAILED dist.
      Rationale: a strikeout is the only BABIP-free out; contact pitchers carry real blow-up variance.
      This is a MECHANISM (not a fitted calibration param) -> safe to add now.
  (2) PARK x CONTACT: park run-inflation acts on balls in play, so it hits low-K pitchers harder.
  (3) BLOWOUT RISK read out of the sim: P(pick loses by >=5). Downside-aware selection suppresses
      a side whose blow-up risk is high even if mean win%>50%  (the WSH/Littell guardrail).
  (4) Multi-market: ML, Run Line (+/-1.5 cover prob), Totals (over/under vs line), K-prop projection.
Deferred (needs multi-slate sample, NOT fit on n=1): global temperature calibration.
"""
import numpy as np
from hfa import V13_1_LEGACY as HFA

rng = np.random.default_rng(1319)
LG_RPG=4.45; LG_ERA=4.20; LG_K=22.0; LG_BB=8.5; LG_BIP=1-(LG_K+LG_BB)/100  # ~0.695

# ---- reuse current team RF/RA + parks (from 7/18 feed) ----
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
# SP: ERA, GS, K%, BB%  (7/18 slate, from feed)
SP={"Jones":(4.37,8,27.1,7.6),"Williams":(3.81,19,29.1,8.0),"Ashcraft":(3.49,19,27.8,5.9),
 "Allen":(0.00,0,36.8,5.3),"Bradley":(3.59,18,27.4,9.3),"Boyd":(4.50,9,24.0,6.6),
 "Manaea":(4.56,6,22.5,7.3),"Luzardo":(3.51,19,29.4,7.6),"Martin":(3.41,18,22.1,7.4),
 "Bieber":(7.64,4,15.1,11.6),"Lowder":(4.91,13,18.6,11.0),"Sugano":(4.80,16,13.4,6.4),
 "Rogers":(4.48,17,18.1,8.1),"Arrighetti":(4.50,15,22.8,12.4),"Canning":(6.47,10,22.3,12.1),
 "Dobnak":(1.86,0,9.8,9.8),"May":(4.55,18,22.9,7.2),"Pfaadt":(4.70,6,17.7,7.8),
 "Seymour":(4.59,6,27.8,8.9),"Sandoval":(2.08,1,26.3,5.3),"Gore":(4.63,20,25.7,9.2),
 "Murphy":(2.25,0,28.6,0.0),"Meyer":(2.58,19,26.0,8.5),"Drohan":(3.09,9,22.9,6.8),
 "Webb":(3.86,16,19.4,6.3),"Woo":(4.23,18,24.1,4.7),"Sheehan":(4.81,17,26.6,7.4),
 "Weathers":(4.15,18,26.9,6.6),"Littell":(4.90,12,14.8,6.8),"Ginn":(3.67,18,21.4,10.6),
 "Skubal":(3.09,13,30.0,3.7),"GrayRod":(7.55,7,16.4,11.0)}

def shrunk_era(era,gs): w=gs/(gs+8); return w*era+(1-w)*LG_ERA
def sp_runsupp(era,gs,k,bb):
    se=shrunk_era(era,gs); return max(2.2, se - ((k-bb)-13.5)*0.03)
def bullpen(t): return 0.55*TEAM[t][1]+0.45*LG_RPG
def bip_rate(k,bb): return max(0.45, 1-(k+bb)/100)

def sim(aw,hm,asp,hsp,park,n=40000):
    pf=PARK[park]
    off_a=TEAM[aw][0]/LG_RPG; off_h=TEAM[hm][0]/LG_RPG
    ra_h=sp_runsupp(*SP[hsp]); ra_a=sp_runsupp(*SP[asp])
    pen_a,pen_h=bullpen(aw),bullpen(hm)
    # (2) park x contact: park inflation weighted by opposing pitcher BIP rate
    pf_a = 1+(pf-1)*(bip_rate(SP[hsp][2],SP[hsp][3])/LG_BIP)   # away offense vs home SP in park
    pf_h = 1+(pf-1)*(bip_rate(SP[asp][2],SP[asp][3])/LG_BIP)
    ip=np.clip(rng.normal(5.4,1.3,n),2.0,8.0); ip2=np.clip(rng.normal(5.4,1.3,n),2.0,8.0)
    mean_a=(ra_h/9*ip + pen_h/9*(9-ip))*off_a*pf_a
    mean_h=(ra_a/9*ip2+ pen_a/9*(9-ip2))*off_h*pf_h*HFA  # HFA-SPLIT: v13_1 lineage value, see engine/hfa.py
    # (1) K-driven variance: gamma shape from OPPOSING SP K% (low K -> low shape -> fat tail)
    sh_a=1.8+ (SP[hsp][2]-LG_K)*0.16   # away runs shape set by home SP's K%
    sh_h=1.8+ (SP[asp][2]-LG_K)*0.16
    sh_a=np.clip(sh_a,1.2,6.0); sh_h=np.clip(sh_h,1.2,6.0)
    ra=rng.poisson(rng.gamma(sh_a,np.maximum(mean_a,0.3)/sh_a))
    rh=rng.poisson(rng.gamma(sh_h,np.maximum(mean_h,0.3)/sh_h))
    tie=ra==rh
    hx=rng.random(n)<(0.5+0.04*np.sign(pen_a-pen_h))
    hw=np.where(tie,hx,rh>ra); tot=ra+rh+tie*rng.poisson(1.0,n)
    margin_home=rh-ra  # + = home wins by
    return dict(hw=hw.mean(), tot=tot.mean(),
        p_home_by2=np.mean(margin_home>=2), p_away_within1=np.mean(margin_home<=1),  # RL covers
        p_home_blow=np.mean(margin_home>=5), p_away_blow=np.mean(margin_home<=-5),
        tot_arr=tot)

def devig(a,h):
    def imp(m): return (-m)/(-m+100) if m<0 else 100/(m+100)
    pa,ph=imp(a),imp(h); s=pa+ph; return pa/s,ph/s

# ---- 7/18 backtest: (away,home,asp,hsp,park, aML,hML, totline, a_score,h_score) ----
BT=[("PIT","CLE","Jones","Williams","Progressive Field",109,-131,7.5,7,1),
 ("MIN","CHC","Bradley","Boyd","Wrigley Field",119,-143,9.0,2,6),
 ("NYM","PHI","Manaea","Luzardo","Citizens Bank Park",144,-175,8.5,1,6),
 ("CHW","TOR","Martin","Bieber","Rogers Centre",-106,-113,8.0,0,1),
 ("CIN","COL","Lowder","Sugano","Coors Field",-117,-103,12.5,3,10),
 ("STL","ARI","May","Pfaadt","Chase Field",-101,-120,9.0,3,5),
 ("MIA","MIL","Meyer","Drohan","American Family Field",113,-136,8.0,6,8),
 ("BAL","HOU","Rogers","Arrighetti","Daikin Park",-109,-110,8.5,4,2),
 ("TEX","ATL","Gore","Murphy","Truist Park",-103,-117,9.0,7,6),
 ("SD","KC","Canning","Dobnak","Kauffman Stadium",-110,-109,10.5,1,6),
 ("TB","BOS","Seymour","Sandoval","Fenway Park",-101,-119,9.5,6,7),
 ("SF","SEA","Webb","Woo","T-Mobile Park",130,-157,6.5,3,4),
 ("WSH","ATH","Littell","Ginn","Sutter Health Park",-117,-103,11.0,1,15),
 ("DET","LAA","Skubal","GrayRod","Angel Stadium",-205,167,8.0,7,0)]

print("="*118); print("V13.1 BACKTEST on 7/18 (14 played; LAD@NYY ppd excluded)"); print("="*118)
print(f"{'Game':<10}{'V13.1 H%':>9}{'mkt H%':>8}{'blowRISK(pick)':>15}{'ML pick':>9}{'result':>8}{'Tot':>6}{'line':>6}{'O/U act':>9}")
briers=[]; mbriers=[]; su_w=su_l=0; blow_flag_hits=0; picks=[]
for aw,hm,asp,hsp,pk,aml,hml,tl,as_,hs in BT:
    r=sim(aw,hm,asp,hsp,pk); hw=r['hw']; pa,ph=devig(aml,hml)
    home_won=hs>as_; yb=1 if home_won else 0
    briers.append((ph_pred:=hw-yb)**2 if False else (hw-yb)**2)
    mbriers.append((ph-yb)**2)
    # ML pick with blowout guardrail: pick side by prob, but if pick's blow-risk>28% -> NO PLAY
    if hw>=0.5: pick,prisk=hm, r['p_away_blow']   # picking home -> risk = away blows us out
    else: pick,prisk=aw, r['p_home_blow']
    guard = prisk>0.28
    picked_home=(pick==hm); won=(picked_home and home_won) or ((not picked_home) and not home_won)
    if not guard: su_w+=won; su_l+=(not won)
    tag=("WIN" if won else "LOSS")+(" [GUARD:NOPLAY]" if guard else "")
    actOU="OVER" if (as_+hs)>tl else ("UNDER" if (as_+hs)<tl else "push")
    print(f"{aw}@{hm:<6}{hw:9.1%}{ph:8.1%}{prisk:14.1%} {pick:<8}{tag:<8}{r['tot']:6.1f}{tl:6.1f}{actOU:>9}")
    picks.append((f"{aw}@{hm}",pick,won,guard,prisk,home_won,as_+hs,tl,r))
print(f"\nV13.1 Brier: {np.mean(briers):.4f} | Market: {np.mean(mbriers):.4f} | coin 0.25")
print(f"V13.1 ML (guardrail-filtered): {su_w}-{su_l}")
# WSH spotlight
wsh=[p for p in picks if p[0]=="WSH@ATH"][0]
print(f"\n>>> WSH@ATH GUARDRAIL CHECK: V13.1 gives ATH home {sim('WSH','ATH','Littell','Ginn','Sutter Health Park')['hw']:.1%}; "
      f"pick={wsh[1]}, blow-risk(pick)={wsh[4]:.0%}, NO-PLAY triggered={wsh[3]} "
      f"-> {'AVOIDED the 1-15' if wsh[3] else 'STILL EXPOSED'}")
