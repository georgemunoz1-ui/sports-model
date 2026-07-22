"""V13.1 pooled backtest: 7/17 + 7/18 (~27 games, 2 opposite slate types).
Tests: pooled Brier, directional ML, and — the point — does blowout-RISK actually
separate picks that get blown out from picks that don't? SP stats verbatim from the
user's daily feeds; results verbatim from box scores."""
import numpy as np
rng=np.random.default_rng(1319)
LG_RPG=4.45; LG_ERA=4.20; LG_K=22.0; LG_BB=8.5; LG_BIP=1-(LG_K+LG_BB)/100
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
# ERA,GS,K%,BB%
SP={ # 7/18
 "Jones":(4.37,8,27.1,7.6),"Williams":(3.81,19,29.1,8.0),"Bradley":(3.59,18,27.4,9.3),
 "Boyd":(4.50,9,24.0,6.6),"Manaea":(4.56,6,22.5,7.3),"Luzardo":(3.51,19,29.4,7.6),
 "Martin":(3.41,18,22.1,7.4),"Bieber":(7.64,4,15.1,11.6),"Lowder":(4.91,13,18.6,11.0),
 "Sugano":(4.80,16,13.4,6.4),"Rogers":(4.48,17,18.1,8.1),"Arrighetti":(4.50,15,22.8,12.4),
 "Canning":(6.47,10,22.3,12.1),"Dobnak":(1.86,0,9.8,9.8),"May":(4.55,18,22.9,7.2),
 "Pfaadt":(4.70,6,17.7,7.8),"Seymour":(4.59,6,27.8,8.9),"Sandoval":(2.08,1,26.3,5.3),
 "Gore":(4.63,20,25.7,9.2),"Murphy":(2.25,0,28.6,0.0),"Meyer":(2.58,19,26.0,8.5),
 "Drohan":(3.09,9,22.9,6.8),"Webb":(3.86,16,19.4,6.3),"Woo":(4.23,18,24.1,4.7),
 "Sheehan":(4.81,17,26.6,7.4),"Weathers":(4.15,18,26.9,6.6),"Littell":(4.90,12,14.8,6.8),
 "Ginn":(3.67,18,21.4,10.6),"Skubal":(3.09,13,30.0,3.7),"GrayRod":(7.55,7,16.4,11.0),
 # 7/17 adds
 "McGreevy":(3.01,18,16.5,5.7),"Kelly":(5.38,16,14.4,9.2),"Melton":(1.82,8,21.7,5.8),
 "Detmers":(4.39,19,27.2,7.7),"Cavalli":(3.83,20,25.4,7.4),"Jump":(3.51,9,23.5,7.4),
 "Roupp":(4.27,18,25.3,10.2),"BMiller":(2.19,9,30.2,4.2),"Alcantara":(3.99,20,18.4,6.1),
 "Henderson":(3.18,6,30.6,6.3),"Singer":(4.72,18,18.9,7.7),"HughesC":(3.00,1,22.9,8.6),
 "Jax":(3.47,14,24.7,8.7),"Bennett":(2.64,8,19.2,4.4),"Englert":(3.82,2,20.9,5.2),
 "Rivera":(0.00,1,25.0,8.3),"Kay":(4.23,17,17.6,8.7),"Miles":(2.85,3,23.5,7.8),
 "Kremer":(4.09,4,27.9,4.7),"Lambert":(3.14,15,22.9,9.3),"Sasaki":(5.33,16,22.7,9.4),
 "Cole":(4.04,9,22.7,5.3),"Quantrill":(3.11,4,14.5,6.7),"Sale":(2.20,17,29.0,6.2),
 "Ober":(4.40,13,17.0,6.3),"Rea":(4.75,15,16.8,8.6),"King":(3.41,19,20.8,9.7),"Lugo":(4.56,19,19.1,7.6)}
def shrunk(era,gs): w=gs/(gs+8); return w*era+(1-w)*LG_ERA
def rs(era,gs,k,bb): return max(2.2, shrunk(era,gs)-((k-bb)-13.5)*0.03)
def pen(t): return 0.55*TEAM[t][1]+0.45*LG_RPG
def bip(k,bb): return max(0.45,1-(k+bb)/100)
def sim(aw,hm,asp,hsp,park,n=40000):
    pf=PARK[park]; oa=TEAM[aw][0]/LG_RPG; oh=TEAM[hm][0]/LG_RPG
    rah=rs(*SP[hsp]); raa=rs(*SP[asp]); pa,ph_=pen(aw),pen(hm)
    pfa=1+(pf-1)*(bip(SP[hsp][2],SP[hsp][3])/LG_BIP); pfh=1+(pf-1)*(bip(SP[asp][2],SP[asp][3])/LG_BIP)
    ip=np.clip(rng.normal(5.4,1.3,n),2,8); ip2=np.clip(rng.normal(5.4,1.3,n),2,8)
    ma=(rah/9*ip+ph_/9*(9-ip))*oa*pfa; mh=(raa/9*ip2+pa/9*(9-ip2))*oh*pfh*1.03
    sa=np.clip(1.8+(SP[hsp][2]-LG_K)*0.16,1.2,6); sh=np.clip(1.8+(SP[asp][2]-LG_K)*0.16,1.2,6)
    ra=rng.poisson(rng.gamma(sa,np.maximum(ma,0.3)/sa)); rh=rng.poisson(rng.gamma(sh,np.maximum(mh,0.3)/sh))
    tie=ra==rh; hx=rng.random(n)<(0.5+0.04*np.sign(pa-ph_)); hw=np.where(tie,hx,rh>ra)
    mg=rh-ra
    return hw.mean(),(ra+rh+tie*rng.poisson(1.0,n)).mean(),np.mean(mg>=5),np.mean(mg<=-5)
def devig(a,h):
    f=lambda m:(-m)/(-m+100) if m<0 else 100/(m+100); pa,ph=f(a),f(h); s=pa+ph; return pa/s,ph/s
# slates: (away,home,asp,hsp,park,aML,hML,totline,as,hs)
S17=[("STL","ARI","McGreevy","Kelly","Chase Field",-105,-115,8.5,5,4),
 ("DET","LAA","Melton","Detmers","Angel Stadium",-120,100,8.5,2,1),
 ("WSH","ATH","Cavalli","Jump","Sutter Health Park",-136,113,10.5,23,4),
 ("SF","SEA","Roupp","BMiller","T-Mobile Park",155,-188,7.0,7,0),
 ("MIA","MIL","Alcantara","Henderson","American Family Field",124,-150,8.5,1,2),
 ("CIN","COL","Singer","HughesC","Coors Field",-108,-112,12.0,7,2),
 ("TB","BOS","Jax","Bennett","Fenway Park",-101,-120,8.5,0,10),
 ("TB","BOS","Englert","Rivera","Fenway Park",109,-131,9.0,3,5),
 ("CHW","TOR","Kay","Miles","Rogers Centre",113,-136,8.5,12,4),
 ("BAL","HOU","Kremer","Lambert","Daikin Park",102,-123,8.5,3,2),
 ("LAD","NYY","Sasaki","Cole","Yankee Stadium",-113,-107,9.0,2,1),
 ("TEX","ATL","Quantrill","Sale","Truist Park",179,-219,8.0,1,15),
 ("MIN","CHC","Ober","Rea","Wrigley Field",125,-151,11.0,5,2),
 ("SD","KC","King","Lugo","Kauffman Stadium",-126,104,9.5,6,7)]
S18=[("PIT","CLE","Jones","Williams","Progressive Field",109,-131,7.5,7,1),
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
briers=[];mb=[];dw=dl=0;tot_w=tot_l=0;risk_rows=[]
for lab,S in [("7/17",S17),("7/18",S18)]:
    for aw,hm,asp,hsp,pk,aml,hml,tl,as_,hs in S:
        hw,tot,hblow,ablow=sim(aw,hm,asp,hsp,pk); pa,ph=devig(aml,hml)
        home_won=hs>as_; yb=1 if home_won else 0
        briers.append((hw-yb)**2); mb.append((ph-yb)**2)
        pick_home=hw>=0.5; won=(pick_home and home_won) or ((not pick_home) and not home_won)
        dw+=won; dl+=(not won)
        # downside blow-risk on the PICK = chance the OTHER side wins by >=5
        prisk = ablow if pick_home else hblow
        margin=hs-as_ if pick_home else as_-hs  # our pick's margin (+ = pick won by)
        got_blown = margin<=-5
        risk_rows.append((prisk,got_blown,f"{aw}@{hm}",lab))
        # totals directional
        pred_ou = "O" if tot>tl else "U"; act=as_+hs
        if act!=tl:
            act_ou="O" if act>tl else "U"; tot_w+=(pred_ou==act_ou); tot_l+=(pred_ou!=act_ou)
print("="*88); print(f"V13.1 POOLED BACKTEST — 7/17+7/18 (n={len(briers)} games)"); print("="*88)
print(f"Directional ML: {dw}-{dl} ({dw/(dw+dl):.1%})")
print(f"Brier: V13.1 {np.mean(briers):.4f} | Market {np.mean(mb):.4f} | coin 0.2500")
print(f"Totals directional: {tot_w}-{tot_l} ({tot_w/max(1,tot_w+tot_l):.1%})")
print()
# THE KEY TEST: does blow-risk separate landmines?
hi=[r for r in risk_rows if r[0]>=0.18]; lo=[r for r in risk_rows if r[0]<0.18]
hi_blow=sum(r[1] for r in hi); lo_blow=sum(r[1] for r in lo)
print("BLOWOUT-RISK SIGNAL TEST (does high modeled risk => actually got blown out?):")
print(f"  HIGH risk (>=18%): {len(hi)} picks, {hi_blow} got blown out ({hi_blow/max(1,len(hi)):.0%})")
print(f"  LOW  risk (<18%):  {len(lo)} picks, {lo_blow} got blown out ({lo_blow/max(1,len(lo)):.0%})")
print(f"  -> signal {'SEPARATES' if (hi_blow/max(1,len(hi)))>(lo_blow/max(1,len(lo))) else 'does NOT separate'} landmines")
print("  High-risk picks that got blown out:", [f'{r[2]}({r[3]})' for r in hi if r[1]])
print("  Blowouts the signal MISSED (low-risk but blown out):", [f'{r[2]}({r[3]})' for r in lo if r[1]])
