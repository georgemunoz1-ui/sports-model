"""V13.1 card — 2026-07-19. Engine validated (7/17+7/18 pooled): blowout guardrail LIVE @18%,
ML market-competitive (paper), TOTALS NOT READY (reference only). Missing-SP games = capped no-play."""
import numpy as np, json
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
CAP=(4.20,0,22.0,8.5)  # league-prior stand-in for a missing/rookie SP (triggers cap/no-play)
SP={"Burke":(3.90,15,25.9,7.9),"Yesavage":(3.72,14,22.2,12.5),"Yamamoto":(2.85,17,24.9,5.9),
 "Schlittler":(2.05,20,29.2,5.3),"McClanahan":(2.83,17,23.2,7.9),"Gray":(2.54,17,22.3,6.3),
 "McLean":(3.52,19,27.9,8.7),"Eovaldi":(4.04,18,25.9,5.6),"Holmes":(3.78,17,21.1,9.0),
 "Skenes":(3.57,20,29.5,5.5),"Cantillo":(3.56,20,24.4,11.4),"BYoung":(3.42,15,18.5,8.5),
 "Brown":(3.57,7,25.5,14.4),"Cameron":(4.89,18,21.5,7.6),"EPerez":(3.78,16,27.2,9.7),
 "Matthews":(4.57,11,19.6,6.5),"Imanaga":(4.17,19,24.0,6.2),"Greene":(6.97,2,42.2,11.1),
 "Feltner":(4.55,13,17.6,9.0),"Griffin":(2.77,19,24.5,5.8),"Mize":(2.79,14,25.3,5.9),
 "Ray":(3.59,18,19.5,11.9),"Gilbert":(3.32,19,26.5,5.3),"Pallante":(3.96,18,17.0,6.9),
 "ERod":(2.29,19,17.1,8.4),
 "Rangel":CAP,"Marquez":CAP,"Gasser":CAP,"JLopez":CAP,"RJohnson":CAP}
CAPPED={"Rangel","Marquez","Gasser","JLopez","RJohnson"}; LOWSAMP={"Greene","Brown"}
def shrunk(era,gs): w=gs/(gs+8); return w*era+(1-w)*LG_ERA
def rs(era,gs,k,bb): return max(2.2,shrunk(era,gs)-((k-bb)-13.5)*0.03)
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
    tie=ra==rh; hx=rng.random(n)<(0.5+0.04*np.sign(pa-ph_)); hw=np.where(tie,hx,rh>ra); mg=rh-ra
    return dict(hw=hw.mean(),tot=(ra+rh+tie*rng.poisson(1.0,n)).mean(),
        hblow=np.mean(mg>=5),ablow=np.mean(mg<=-5),
        rl_home=np.mean(mg>=2),rl_away=np.mean(mg<=-2))
def devig(a,h):
    f=lambda m:(-m)/(-m+100) if m<0 else 100/(m+100); pa,ph=f(a),f(h); s=pa+ph; return pa/s,ph/s
# (away,home,asp,hsp,park, aML,hML, total)  None ML = no market (CHW@TOR)
G=[("CHW","TOR","Burke","Yesavage","Rogers Centre",None,None,None),
 ("LAD","NYY","Yamamoto","Schlittler","Yankee Stadium",-120,100,7.5),
 ("TB","BOS","McClanahan","Gray","Fenway Park",105,-127,8.0),
 ("NYM","PHI","McLean","Rangel","Citizens Bank Park",-131,109,8.5),
 ("TEX","ATL","Eovaldi","Holmes","Truist Park",-120,100,9.0),
 ("PIT","CLE","Skenes","Cantillo","Progressive Field",-131,109,7.0),
 ("BAL","HOU","BYoung","Brown","Daikin Park",101,-122,8.0),
 ("SD","KC","Marquez","Cameron","Kauffman Stadium",109,-131,10.0),
 ("MIA","MIL","EPerez","Gasser","American Family Field",109,-131,8.0),
 ("MIN","CHC","Matthews","Imanaga","Wrigley Field",142,-172,7.5),
 ("CIN","COL","Greene","Feltner","Coors Field",-144,119,11.0),
 ("WSH","ATH","Griffin","JLopez","Sutter Health Park",-143,119,10.5),
 ("DET","LAA","Mize","RJohnson","Angel Stadium",-156,129,9.0),
 ("SF","SEA","Ray","Gilbert","T-Mobile Park",148,-180,7.0),
 ("STL","ARI","Pallante","ERod","Chase Field",101,-122,9.0)]
print("="*120)
print("V13.1 CARD — 2026-07-19  | ML=paper(market-competitive) | guardrail LIVE@18% | TOTALS=reference-only(not validated)")
print("="*120)
print(f"{'Game':<9}{'V13 H%':>7}{'mkt H%':>7}{'pick':>6}{'edge':>7}{'blowRISK':>9}{'flag':<22}{'tot':>6}{'line':>6}{'lean':>6}")
rows=[]
for aw,hm,asp,hsp,pk,aml,hml,tl in G:
    r=sim(aw,hm,asp,hsp,pk); hw=r['hw']
    capped = (asp in CAPPED) or (hsp in CAPPED)
    low = (asp in LOWSAMP) or (hsp in LOWSAMP)
    if aml is not None:
        pa,ph=devig(aml,hml); mktH=ph
    else:
        pa=ph=mktH=None
    pick = hm if hw>=0.5 else aw
    prisk = r['ablow'] if hw>=0.5 else r['hblow']   # downside blowout risk on our pick
    edge = (hw-ph) if (ph is not None and hw>=0.5) else ((1-hw)-pa if pa is not None else None)
    # flags
    if capped: flag="CAPPED no-play (missing SP)"
    elif prisk>=0.18: flag="BLOWOUT-RISK no-play"
    elif low: flag="LOW-SAMPLE watch"
    else: flag=""
    tlean = ("OVER" if (tl and r['tot']>tl) else ("UNDER" if tl else "")) if tl else ""
    es = f"{edge:+.0%}" if edge is not None else "  n/a"
    mh = f"{mktH:.0%}" if mktH is not None else " n/a"
    print(f"{aw}@{hm:<5}{hw:7.0%}{mh:>7}{pick:>6}{es:>7}{prisk:9.0%}  {flag:<22}{r['tot']:6.1f}{(tl or 0):6.1f}{tlean:>6}")
    rows.append(dict(game=f"{aw}@{hm}",hw=round(hw,3),mktH=(round(mktH,3) if mktH else None),pick=pick,
        edge=(round(edge,3) if edge is not None else None),blowrisk=round(prisk,3),flag=flag,
        tot=round(r['tot'],1),line=tl,rl_home=round(r['rl_home'],3),rl_away=round(r['rl_away'],3),
        capped=capped,low=low))
json.dump({"date":"2026-07-19","engine":"V13.1","rows":rows},open("cards/2026-07-19_card.json","w"),indent=1)
# actionable shortlist: uncapped, not blowout-flagged, edge>=+3%
act=[r for r in rows if not r['capped'] and r['blowrisk']<0.18 and r['edge'] is not None and r['edge']>=0.03]
print("\nACTIONABLE ML leans (uncapped, guardrail-clear, edge>=+3%, PAPER):")
for r in sorted(act,key=lambda x:-x['edge']):
    print(f"  {r['game']:<9} {r['pick']:<4} edge {r['edge']:+.0%}  (V13 {r['hw']:.0%} vs mkt {r['mktH']:.0%})  blow-risk {r['blowrisk']:.0%}")
if not act: print("  (none clear the bar)")
print(f"\nCAPPED no-plays: {[r['game'] for r in rows if r['capped']]}")
print(f"Blowout-risk no-plays: {[r['game'] for r in rows if r['flag']=='BLOWOUT-RISK no-play']}")
