"""V13.1 card — 2026-07-20. Corrected objective (AUTH-7): flag a PLAY on positive EV vs the price's
break-even with a >=4pp uncertainty buffer — NOT win%. New data-derived parks + HFA 1.005 + guardrail@18%."""
import numpy as np, json
rng=np.random.default_rng(720)
LG_RPG=4.45; LG_ERA=4.20; LG_K=22.0; LG_BB=8.5; LG_BIP=1-(LG_K+LG_BB)/100
TEAM={"PIT":(5.3,4.9),"CLE":(3.9,3.9),"MIN":(4.9,5.0),"CHC":(5.0,4.5),"NYM":(4.1,4.7),
 "PHI":(4.3,4.5),"CHW":(4.9,4.4),"TOR":(4.1,4.5),"CIN":(4.2,4.8),"COL":(4.7,5.7),
 "BAL":(4.6,4.8),"HOU":(4.6,5.0),"SD":(4.0,4.4),"KC":(4.3,5.2),"STL":(4.5,4.4),
 "ARI":(4.3,4.5),"TB":(4.5,4.3),"BOS":(4.2,3.8),"TEX":(4.1,4.4),"ATL":(4.9,3.8),
 "MIA":(4.5,4.3),"MIL":(5.1,3.8),"SF":(4.1,4.7),"SEA":(4.0,3.9),"LAD":(5.2,3.7),
 "NYY":(4.8,3.8),"WSH":(5.5,5.2),"ATH":(4.4,5.7),"DET":(4.2,4.0),"LAA":(4.4,5.0)}
PARK=json.load(open("data/backfill/mlb/2026/park_factors.json"))
CAP=(4.20,0,22.0,8.5)
SP={"JRyan":(2.85,20,28.4,5.6),"Bibee":(3.90,20,19.0,7.4),"Sheehan":(4.81,17,26.6,7.4),
 "Sanchez":(2.62,20,27.4,4.8),"Ashcraft":(3.49,19,27.8,5.9),"Weathers":(4.15,18,26.9,6.6),
 "Martinez":(2.65,18,14.5,4.4),"Cease":(2.56,17,36.9,11.0),"Baz":(4.19,19,20.5,8.7),
 "Tolle":(3.11,15,25.5,7.3),"Sears":(5.03,4,19.8,9.3),"Elder":(4.12,18,19.8,7.4),
 "Peralta":(4.66,20,22.3,9.4),"Misiorowski":(1.62,18,39.6,6.4),"Fedde":(4.15,9,15.4,9.0),
 "deGrom":(3.49,18,30.4,5.5),"Flaherty":(4.48,18,26.4,10.8),"Taillon":CAP,"Junk":(4.57,12,17.4,6.2),
 "Blanco":CAP,"Mahle":(5.31,15,21.7,9.5),"Wacha":(3.77,19,19.7,7.0),"Alvarez":(4.05,6,23.3,12.5),
 "Freeland":(7.36,18,19.7,4.5),"Springs":(6.08,19,19.5,8.6),"Bratt":(6.00,2,10.7,17.9),
 "Abbott":(4.11,20,18.4,10.5),"Kirby":(3.76,18,21.5,5.3),"Leahy":(3.73,18,19.3,8.5),"Soriano":(3.49,20,24.7,11.4)}
CAPPED={"Taillon","Blanco","Bratt"}  # Taillon/Blanco no FG data; Bratt 2 GS
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
    return hw.mean(),(ra+rh+tie*rng.poisson(1.0,n)).mean(),np.mean(mg>=5),np.mean(mg<=-5)
def raw_imp(ml): return (-ml)/(-ml+100) if ml<0 else 100/(ml+100)
def prof(ml): return (100/(-ml)) if ml<0 else (ml/100)   # profit per $1
# (away,home,asp,hsp,park, aML,hML, total)
G=[("MIN","CLE","JRyan","Bibee","Progressive Field",-120,106,7.5),
 ("LAD","PHI","Sheehan","Sanchez","Citizens Bank Park",118,-134,8.0),
 ("PIT","NYY","Ashcraft","Weathers","Yankee Stadium",110,-120,7.5),
 ("TB","TOR","Martinez","Cease","Rogers Centre",126,-140,7.5),
 ("BAL","BOS","Baz","Tolle","Fenway Park",120,-135,8.5),
 ("SD","ATL","Sears","Elder","Truist Park",135,-142,9.5),
 ("NYM","MIL","Peralta","Misiorowski","American Family Field",158,-178,7.0),
 ("CHW","TEX","Fedde","deGrom","Globe Life Field",143,-162,7.5),
 ("DET","CHC","Flaherty","Taillon","Wrigley Field",-108,-108,None),
 ("MIA","HOU","Junk","Blanco","Daikin Park",122,-135,8.5),
 ("SF","KC","Mahle","Wacha","Kauffman Stadium",-106,-110,10.5),
 ("ATH","ARI","Springs","Bratt","Chase Field",136,-162,9.0),
 ("CIN","SEA","Abbott","Kirby","T-Mobile Park",140,-155,7.5),
 ("STL","LAA","Leahy","Soriano","Angel Stadium",105,-120,8.5)]
# WSH@COL omitted — no line posted (Alvarez/Freeland). Sim reference only.
print("="*120)
print("V13.1 CARD 2026-07-20 | PLAY = +EV vs break-even AND edge>=4pp buffer (NOT win%) | parks=data | guardrail@18%")
print("="*120)
print(f"{'Game':<9}{'V13 H%':>7}{'side':>6}{'price':>7}{'p_win':>7}{'b/e':>6}{'edge':>7}{'EV%':>7}{'blow':>6}  {'CALL'}")
rows=[]
for aw,hm,asp,hsp,pk,aml,hml,tl in G:
    hw,tot,hblow,ablow=sim(aw,hm,asp,hsp,pk)
    capped=(asp in CAPPED)or(hsp in CAPPED)
    # evaluate both sides, pick max EV
    cands=[(hm,hml,hw,ablow),(aw,aml,1-hw,hblow)]
    best=max(cands,key=lambda c:(c[2]-raw_imp(c[1])))
    side,ml,p,blow=best; be=raw_imp(ml); edge=p-be; ev=p*prof(ml)-(1-p)
    if capped: call="CAP no-play"
    elif blow>=0.18: call="GUARDRAIL no-play"
    elif ev>0 and edge>=0.04: call="*** PLAY ***"
    elif ev>0: call="lean (sub-buffer)"
    else: call="pass (-EV)"
    print(f"{aw}@{hm:<5}{hw:7.0%}{side:>6}{ml:>7}{p:7.0%}{be:6.0%}{edge:+7.1%}{ev*100:+7.1f}{blow:6.0%}  {call}")
    rows.append(dict(game=f"{aw}@{hm}",side=side,price=ml,p=round(p,3),be=round(be,3),edge=round(edge,3),ev=round(ev,3),blow=round(blow,3),tot=round(tot,1),line=tl,capped=capped,call=call))
json.dump({"date":"2026-07-20","engine":"V13.1","rule":"EV>0 & edge>=0.04","rows":rows},open("cards/2026-07-20_card.json","w"),indent=1)
plays=[r for r in rows if r['call']=="*** PLAY ***"]
print("\nPLAYS (positive EV, buffer-clear, uncapped, guardrail-clear):")
for r in sorted(plays,key=lambda x:-x['ev']): print(f"  {r['game']:<9} {r['side']:<4} {r['price']:+d}  EV {r['ev']*100:+.1f}%  edge {r['edge']:+.0%}  p={r['p']:.0%} vs b/e {r['be']:.0%}")
if not plays: print("  (none clear +EV and the 4pp buffer — correct outcome on an efficient board)")
print(f"\nCapped no-plays: {[r['game'] for r in rows if r['capped']]}")
print("Sub-buffer leans (positive EV but < 4pp — NOT plays):", [f"{r['game']}:{r['side']}({r['ev']*100:+.0f}%)" for r in rows if r['call']=='lean (sub-buffer)'])
