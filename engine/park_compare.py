"""Did the backfill park-factor fix help? Old (hand) vs New (data-derived) parks on the pooled
7/17+7/18 slate. Focus: TOTALS (parks affect totals most) + Brier + directional. n=27."""
import numpy as np, json
rng=np.random.default_rng(1319)
LG_RPG=4.45; LG_ERA=4.20; LG_K=22.0; LG_BB=8.5; LG_BIP=1-(LG_K+LG_BB)/100
TEAM={"PIT":(5.3,4.9),"CLE":(3.9,3.9),"MIN":(4.9,5.0),"CHC":(5.0,4.5),"NYM":(4.1,4.7),
 "PHI":(4.3,4.5),"CHW":(4.9,4.4),"TOR":(4.1,4.5),"CIN":(4.2,4.8),"COL":(4.7,5.7),
 "BAL":(4.6,4.8),"HOU":(4.6,5.0),"SD":(4.0,4.4),"KC":(4.3,5.2),"STL":(4.5,4.4),
 "ARI":(4.3,4.5),"TB":(4.5,4.3),"BOS":(4.2,3.8),"TEX":(4.1,4.4),"ATL":(4.9,3.8),
 "MIA":(4.5,4.3),"MIL":(5.1,3.8),"SF":(4.1,4.7),"SEA":(4.0,3.9),"LAD":(5.2,3.7),
 "NYY":(4.8,3.8),"WSH":(5.5,5.2),"ATH":(4.4,5.7),"DET":(4.2,4.0),"LAA":(4.4,5.0)}
OLD={"Coors Field":1.18,"Fenway Park":1.03,"Yankee Stadium":1.02,"T-Mobile Park":0.92,
 "Kauffman Stadium":1.00,"Daikin Park":1.01,"Rogers Centre":1.01,"Wrigley Field":1.00,
 "Angel Stadium":0.97,"Sutter Health Park":1.06,"American Family Field":1.00,
 "Progressive Field":0.98,"Citizens Bank Park":1.04,"Chase Field":1.01,"Truist Park":1.00}
NEW=json.load(open("data/backfill/mlb/2026/park_factors.json"))
SP={"McGreevy":(3.01,18,16.5,5.7),"Kelly":(5.38,16,14.4,9.2),"Melton":(1.82,8,21.7,5.8),
 "Detmers":(4.39,19,27.2,7.7),"Cavalli":(3.83,20,25.4,7.4),"Jump":(3.51,9,23.5,7.4),
 "Roupp":(4.27,18,25.3,10.2),"BMiller":(2.19,9,30.2,4.2),"Alcantara":(3.99,20,18.4,6.1),
 "Henderson":(3.18,6,30.6,6.3),"Singer":(4.72,18,18.9,7.7),"HughesC":(3.00,1,22.9,8.6),
 "Jax":(3.47,14,24.7,8.7),"Bennett":(2.64,8,19.2,4.4),"Englert":(3.82,2,20.9,5.2),
 "Rivera":(0.00,1,25.0,8.3),"Kay":(4.23,17,17.6,8.7),"Miles":(2.85,3,23.5,7.8),
 "Kremer":(4.09,4,27.9,4.7),"Lambert":(3.14,15,22.9,9.3),"Sasaki":(5.33,16,22.7,9.4),
 "Cole":(4.04,9,22.7,5.3),"Quantrill":(3.11,4,14.5,6.7),"Sale":(2.20,17,29.0,6.2),
 "Ober":(4.40,13,17.0,6.3),"Rea":(4.75,15,16.8,8.6),"King":(3.41,19,20.8,9.7),"Lugo":(4.56,19,19.1,7.6),
 "Jones":(4.37,8,27.1,7.6),"Williams":(3.81,19,29.1,8.0),"Bradley":(3.59,18,27.4,9.3),
 "Boyd":(4.50,9,24.0,6.6),"Manaea":(4.56,6,22.5,7.3),"Luzardo":(3.51,19,29.4,7.6),
 "Martin":(3.41,18,22.1,7.4),"Bieber":(7.64,4,15.1,11.6),"Lowder":(4.91,13,18.6,11.0),
 "Sugano":(4.80,16,13.4,6.4),"Rogers":(4.48,17,18.1,8.1),"Arrighetti":(4.50,15,22.8,12.4),
 "May":(4.55,18,22.9,7.2),"Pfaadt":(4.70,6,17.7,7.8),"Seymour":(4.59,6,27.8,8.9),
 "Sandoval":(2.08,1,26.3,5.3),"Gore":(4.63,20,25.7,9.2),"Murphy":(2.25,0,28.6,0.0),
 "Meyer":(2.58,19,26.0,8.5),"Drohan":(3.09,9,22.9,6.8),"Webb":(3.86,16,19.4,6.3),
 "Woo":(4.23,18,24.1,4.7),"Sheehan":(4.81,17,26.6,7.4),"Weathers":(4.15,18,26.9,6.6),
 "Littell":(4.90,12,14.8,6.8),"Ginn":(3.67,18,21.4,10.6),"Skubal":(3.09,13,30.0,3.7),"GrayRod":(7.55,7,16.4,11.0)}
def shrunk(e,g): w=g/(g+8); return w*e+(1-w)*LG_ERA
def rs(sp): e,g,k,bb=SP[sp]; return max(2.2,shrunk(e,g)-((k-bb)-13.5)*0.03)
def pen(t): return 0.55*TEAM[t][1]+0.45*LG_RPG
def bip(k,bb): return max(0.45,1-(k+bb)/100)
def sim(aw,hm,asp,hsp,park,PK,hfa,n=40000):
    pf=PK.get(park,1.0); oa=TEAM[aw][0]/LG_RPG; oh=TEAM[hm][0]/LG_RPG
    rah=rs(hsp); raa=rs(asp); pa,ph_=pen(aw),pen(hm)
    pfa=1+(pf-1)*(bip(SP[hsp][2],SP[hsp][3])/LG_BIP); pfh=1+(pf-1)*(bip(SP[asp][2],SP[asp][3])/LG_BIP)
    ip=np.clip(rng.normal(5.4,1.3,n),2,8); ip2=np.clip(rng.normal(5.4,1.3,n),2,8)
    ma=(rah/9*ip+ph_/9*(9-ip))*oa*pfa; mh=(raa/9*ip2+pa/9*(9-ip2))*oh*pfh*hfa
    sa=np.clip(1.8+(SP[hsp][2]-LG_K)*0.16,1.2,6); sh=np.clip(1.8+(SP[asp][2]-LG_K)*0.16,1.2,6)
    ra=rng.poisson(rng.gamma(sa,np.maximum(ma,0.3)/sa)); rh=rng.poisson(rng.gamma(sh,np.maximum(mh,0.3)/sh))
    tie=ra==rh; hx=rng.random(n)<(0.5+0.04*np.sign(pa-ph_)); hw=np.where(tie,hx,rh>ra)
    return hw.mean(),(ra+rh+tie*rng.poisson(1.0,n)).mean()
# (away,home,asp,hsp,park,totline, as,hs)
S=[("STL","ARI","McGreevy","Kelly","Chase Field",8.5,5,4),("DET","LAA","Melton","Detmers","Angel Stadium",8.5,2,1),
 ("WSH","ATH","Cavalli","Jump","Sutter Health Park",10.5,23,4),("SF","SEA","Roupp","BMiller","T-Mobile Park",7.0,7,0),
 ("MIA","MIL","Alcantara","Henderson","American Family Field",8.5,1,2),("CIN","COL","Singer","HughesC","Coors Field",12.0,7,2),
 ("TB","BOS","Jax","Bennett","Fenway Park",8.5,0,10),("CHW","TOR","Kay","Miles","Rogers Centre",8.5,12,4),
 ("BAL","HOU","Kremer","Lambert","Daikin Park",8.5,3,2),("LAD","NYY","Sasaki","Cole","Yankee Stadium",9.0,2,1),
 ("TEX","ATL","Quantrill","Sale","Truist Park",8.0,1,15),("MIN","CHC","Ober","Rea","Wrigley Field",11.0,5,2),
 ("SD","KC","King","Lugo","Kauffman Stadium",9.5,6,7),
 ("PIT","CLE","Jones","Williams","Progressive Field",7.5,7,1),("MIN","CHC","Bradley","Boyd","Wrigley Field",9.0,2,6),
 ("NYM","PHI","Manaea","Luzardo","Citizens Bank Park",8.5,1,6),("CHW","TOR","Martin","Bieber","Rogers Centre",8.0,0,1),
 ("CIN","COL","Lowder","Sugano","Coors Field",12.5,3,10),("STL","ARI","May","Pfaadt","Chase Field",9.0,3,5),
 ("MIA","MIL","Meyer","Drohan","American Family Field",8.0,6,8),("BAL","HOU","Rogers","Arrighetti","Daikin Park",8.5,4,2),
 ("TEX","ATL","Gore","Murphy","Truist Park",9.0,7,6),("TB","BOS","Seymour","Sandoval","Fenway Park",9.5,6,7),
 ("SF","SEA","Webb","Woo","T-Mobile Park",6.5,3,4),("WSH","ATH","Littell","Ginn","Sutter Health Park",11.0,1,15),
 ("DET","LAA","Skubal","GrayRod","Angel Stadium",8.0,7,0)]
def run(PK,hfa,label):
    br=[]; dw=dl=0; tw=tl=0; tabs=[]
    for aw,hm,asp,hsp,pk,line,as_,hs in S:
        hw,tot=sim(aw,hm,asp,hsp,pk,PK,hfa); yb=1 if hs>as_ else 0
        br.append((hw-yb)**2); ph=hw>=.5; dw+=(ph==yb); dl+=(ph!=yb)
        act=as_+hs; tabs.append(abs(tot-act))
        if act!=line:
            p="O" if tot>line else "U"; a="O" if act>line else "U"; tw+=(p==a); tl+=(p!=a)
    print(f"  {label:<28} Brier {np.mean(br):.4f} | dir {dw}-{dl} | TOTALS {tw}-{tl} ({tw/(tw+tl):.0%}) | tot MAE {np.mean(tabs):.2f}")
print("="*84); print("PARK-FACTOR FIX VERIFICATION — pooled 7/17+7/18 (n=27)"); print("="*84)
run(OLD,1.03,"OLD parks (hand) hfa1.03")
run(NEW,1.03,"NEW parks (data) hfa1.03")
run(NEW,1.005,"NEW parks + trimmed HFA1.005")
print("\nWSH@ATH totals check (actual 16, line 11):")
for PK,lab in [(OLD,"OLD"),(NEW,"NEW")]:
    _,t=sim("WSH","ATH","Littell","Ginn","Sutter Health Park",PK,1.03); print(f"  {lab} Sutter Health -> proj total {t:.1f}  (lean {'OVER' if t>11 else 'UNDER'})")
