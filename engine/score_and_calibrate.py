"""THE PAYOFF: score V13.1 across all 1,461 enriched games (as-of inputs, no look-ahead) and fit the
temperature calibration on a REAL sample with a train/test split. Compare to the n=26 boundary fit."""
import csv, json, numpy as np
rng=np.random.default_rng(7)
LG_RPG=4.45; LG_ERA=4.20; LG_K=22.0; LG_BB=8.5; LG_BIP=1-(LG_K+LG_BB)/100
PARK=json.load(open("data/backfill/mlb/2026/park_factors.json"))
def shrunk(e,g): w=g/(g+8); return w*e+(1-w)*LG_ERA
def rs(era,gs,k,bb):
    era=era if era is not None else LG_ERA; gs=gs if gs is not None else 0
    k=k if k is not None else LG_K; bb=bb if bb is not None else LG_BB
    return max(2.2, shrunk(era,gs)-((k-bb)-13.5)*0.03)
def bipf(k,bb):
    k=k if k is not None else LG_K; bb=bb if bb is not None else LG_BB
    return max(0.45,1-(k+bb)/100)
def sim(sp_a,sp_h,rf_a,ra_a,rf_h,ra_h,pf,n=4000):
    oa=(rf_a or LG_RPG)/LG_RPG; oh=(rf_h or LG_RPG)/LG_RPG
    pena=0.55*(ra_a or LG_RPG)+0.45*LG_RPG; penh=0.55*(ra_h or LG_RPG)+0.45*LG_RPG
    rah=rs(**sp_h); raa=rs(**sp_a)
    pfa=1+(pf-1)*(bipf(sp_h["k"],sp_h["bb"])/LG_BIP); pfh=1+(pf-1)*(bipf(sp_a["k"],sp_a["bb"])/LG_BIP)
    ip=np.clip(rng.normal(5.4,1.3,n),2,8); ip2=np.clip(rng.normal(5.4,1.3,n),2,8)
    ma=(rah/9*ip+penh/9*(9-ip))*oa*pfa; mh=(raa/9*ip2+pena/9*(9-ip2))*oh*pfh*1.005
    ka=sp_h["k"] if sp_h["k"] is not None else LG_K; kh=sp_a["k"] if sp_a["k"] is not None else LG_K
    sa=np.clip(1.8+(ka-LG_K)*0.16,1.2,6); sh=np.clip(1.8+(kh-LG_K)*0.16,1.2,6)
    ra=rng.poisson(rng.gamma(sa,np.maximum(ma,0.3)/sa)); rh=rng.poisson(rng.gamma(sh,np.maximum(mh,0.3)/sh))
    tie=ra==rh; hx=rng.random(n)<(0.5+0.04*np.sign(pena-penh))
    return np.where(tie,hx,rh>ra).mean()
def spd(d): return dict(era=d.get("era"),gs=d.get("gs") or 0,k=d.get("k"),bb=d.get("bb")) if d else None
probs=[]; ys=[]
for r in csv.DictReader(open("data/backfill/mlb/2026/features.csv")):
    if r["home_win"]=="" : continue
    f=json.loads(r["features"]); asp=spd(f["away_sp"]); hsp=spd(f["home_sp"])
    if not asp or not hsp: continue
    p=sim(asp,hsp,f["away_rf"],f["away_ra"],f["home_rf"],f["home_ra"],f["park"])
    probs.append(p); ys.append(int(r["home_win"]))
probs=np.array(probs); ys=np.array(ys); N=len(ys)
def logit(p): p=np.clip(p,1e-6,1-1e-6); return np.log(p/(1-p))
def sig(x): return 1/(1+np.exp(-x))
def cal(p,T): return sig(logit(p)/T)
# train/test split
idx=rng.permutation(N); tr,te=idx[:int(.7*N)],idx[int(.7*N):]
def ll(T,ii):
    pc=np.clip(cal(probs[ii],T),1e-6,1-1e-6); return -np.mean(ys[ii]*np.log(pc)+(1-ys[ii])*np.log(1-pc))
Ts=np.arange(0.50,1.51,0.01); bestT=min(Ts,key=lambda T:ll(T,tr))
def brier(T,ii): return np.mean((cal(probs[ii],T)-ys[ii])**2)
print(f"V13.1 scored on N={N} enriched games (as-of, no look-ahead). Home-win base rate {ys.mean():.3f}")
print(f"Fitted T (on 70% train) = {bestT:.2f}   [interior? grid is 0.50-1.50]  (n=26 fit was T=0.55 at boundary)")
print(f"HELD-OUT (30%, n={len(te)}):  Brier raw {brier(1.0,te):.4f}  ->  calibrated {brier(bestT,te):.4f}")
print(f"Full-sample dispersion mean|p-.5|: raw {np.mean(np.abs(probs-.5)):.3f} -> cal {np.mean(np.abs(cal(probs,bestT)-.5)):.3f}")
# reliability: does raw over/under-confidence show?
print(f"Directional accuracy (argmax): {np.mean((probs>=.5)==ys):.1%}   vs coin 0.500 / base {max(ys.mean(),1-ys.mean()):.3f}")
json.dump({"N":int(N),"T":round(float(bestT),3),"brier_raw":round(float(brier(1.0,te)),4),
 "brier_cal":round(float(brier(bestT,te)),4),"note":"train/test 70/30; as-of features; no look-ahead"},
 open("data/backfill/mlb/2026/calibration.json","w"),indent=1)
print("\nsaved calibration.json")

# ---- MATURITY SPLIT: is V13 blind early but real once stats mature? ----
print("\n=== ACCURACY / BRIER by input maturity (min as-of GS of the two starters) ===")
gsmin=[]
import csv as _c, json as _j
rows=[r for r in _c.DictReader(open("data/backfill/mlb/2026/features.csv")) if r["home_win"]!=""]
i=0; gm=[]
for r in rows:
    f=_j.loads(r["features"]); a=f["away_sp"]; h=f["home_sp"]
    if not a or not h: continue
    gm.append(min(a.get("gs") or 0, h.get("gs") or 0))
gm=np.array(gm)
for lo,hi,lab in [(0,3,"0-2 GS (blind)"),(3,8,"3-7 GS (thin)"),(8,99,"8+ GS (mature)")]:
    m=(gm>=lo)&(gm<hi)
    if m.sum()<20: continue
    acc=np.mean((probs[m]>=.5)==ys[m]); br=np.mean((probs[m]-ys[m])**2); base=max(ys[m].mean(),1-ys[m].mean())
    print(f"  {lab:<16} n={m.sum():>4}  acc {acc:.1%}  (base {base:.1%})  Brier {br:.4f}")
print("  Market reference (mature slates, prior n=73 study): Brier ~0.238, picks ~57%.")
