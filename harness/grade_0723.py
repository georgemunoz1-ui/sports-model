#!/usr/bin/env python3
"""Grade 7/23 across all three ledgers from verified box-score K totals. Computes pl/Brier/logloss
exactly (no hand-math). Idempotent-ish: run once; it moves pending->graded."""
import json, math
S=json.load(open("state.json"))

def profit(price):  # profit per 1u stake at american odds
    return 100/abs(price) if price<0 else price/100
def grade(side, line, actual):
    y = 1 if ((side=="OVER" and actual>line) or (side=="UNDER" and actual<line)) else 0
    return y
def brier(p,y): return None if p is None else round((p-y)**2,4)
def logloss(p,y):
    if p is None: return None
    q = p if y else 1-p
    return round(-math.log(max(q,1e-9)),4)
def pl(result, price, weight):
    if result=="WIN": return round(weight*profit(price),2)
    if result=="LOSS": return round(-weight,2)
    return 0.0

# ---- actual K totals (verified from Savant box scores 7/23) ----
K={"Chris Sale":11,"Ian Seymour":7,"Gavin Williams":11,"Taj Bradley":5,
   "Michael McGreevy":3,"Randy Dobnak":3}

# ===== 1. ENGINE kprops_paper =====
lp=S["ledgers"]["kprops_paper"]
day_pl=0.0; nw=0; nl=0
for pl_entry in lp["plays_pending"]:
    a=K[pl_entry["pitcher"]]; side=pl_entry["side"]; line=pl_entry["line"]
    y=grade(side,line,a); res="WIN" if y else "LOSS"
    p=pl_entry.get("p"); rp=pl_entry.get("raw_p"); sp=pl_entry.get("shrunk_p")
    e=pl_entry  # mutate in place, then move
    e["actual"]=a; e["y"]=y; e["result"]=res
    e["pl"]=pl(res,pl_entry["price"],pl_entry["weight"]); e["roi"]=round(e["pl"]/pl_entry["weight"],3)
    e["close_line"]=e["line"]; e["close_price"]=e["price"]; e["clv_note"]="no late board posted; close=open"
    e["brier_raw"]=brier(rp,y); e["brier_shrunk"]=brier(sp,y)
    e["logloss_raw"]=logloss(rp,y); e["logloss_shrunk"]=logloss(sp,y)
    day_pl+=e["pl"]; nw+=y; nl+=(1-y)
    lp["graded"].append(e)
lp["plays_pending"]=[]
lp["day"]=3; lp["record_w"]+=nw; lp["record_l"]+=nl
lp["units"]=round(lp["units"]+day_pl,2)
print(f"ENGINE: {nw}-{nl}, day {day_pl:+.2f}u, cum {lp['record_w']}-{lp['record_l']} {lp['units']:+.2f}u")

# ===== 2. TACO baseline (flat 1u, price-EV only) =====
tb=S["ledgers"]["kprops_taco_baseline"]
bw=0; bl=0; bu=0.0
braw=[]; bshr=[]; lraw=[]; lshr=[]
for e in tb["pending"]:
    a=K[e["pitcher"]]; side=e["side"]; line=e["line"]
    y=grade(side,line,a); res="WIN" if y else "LOSS"
    e["actual"]=a; e["y"]=y; e["result"]=res; e["weight"]=1.0
    e["pl"]=pl(res,e["price"],1.0); e["roi"]=e["pl"]
    e["brier_raw"]=brier(e.get("raw_p"),y); e["brier_shrunk"]=brier(e.get("shrunk_p"),y)
    e["logloss_raw"]=logloss(e.get("raw_p"),y); e["logloss_shrunk"]=logloss(e.get("shrunk_p"),y)
    bu+=e["pl"]; bw+=y; bl+=(1-y)
    if e["brier_raw"] is not None and e["brier_shrunk"] is not None:
        braw.append(e["brier_raw"]); bshr.append(e["brier_shrunk"])
        lraw.append(e["logloss_raw"]); lshr.append(e["logloss_shrunk"])
    tb["graded"].append(e)
tb["pending"]=[]
tb["record_w"]+=bw; tb["record_l"]+=bl; tb["units"]=round(tb["units"]+bu,2)
tb["ab_shrinkage"]={
  "n_both":len(braw),
  "brier_raw_mean":round(sum(braw)/len(braw),4),"brier_shrunk_mean":round(sum(bshr)/len(bshr),4),
  "logloss_raw_mean":round(sum(lraw)/len(lraw),4),"logloss_shrunk_mean":round(sum(lshr)/len(lshr),4),
  "note":"A/B night 1: RAW beat SHRUNK on both Brier and logloss. Two high-K arms (Williams 11K) went OVER where shrinkage pulled p toward 0.5. n=4 shared plays — pure noise, marathon scoring."
}
print(f"BASELINE: {bw}-{bl}, {bu:+.2f}u | A/B Brier raw {tb['ab_shrinkage']['brier_raw_mean']} vs shrunk {tb['ab_shrinkage']['brier_shrunk_mean']}")

# ===== 3. ML tracking + V13 directional =====
ml=S["ledgers"]["ml_tracking"]
res_map={"MIN":"WIN","STL":"LOSS","ATL":"WIN"}
mw=0; mlo=0
for e in ml["pending"]:
    e["result"]=res_map[e["pick"]]; mw+=(e["result"]=="WIN"); mlo+=(e["result"]=="LOSS")
    ml["graded"].append(e)
ml["pending"]=[]
ml["record_w"]+=mw; ml["record_l"]+=mlo
print(f"ML: {mw}-{mlo}, cum {ml['record_w']}-{ml['record_l']}")

v=S["ledgers"]["v13_forward_directional"]
v["w"]+=3; v["l"]+=2; v["note"]="7/19-24; +3-2 on 7/23 (MIN,DET,ATL correct; TB,STL wrong); tracking only"
print(f"V13 dir: cum {v['w']}-{v['l']}")

# ===== 4. gate + meta =====
S["gates"]["kprops_go_live"]["progress"]="9/100"
S["updated_utc"]="2026-07-24T06:10:00Z"
S["next_actions"]=[
  "PRE-REGISTER + RUN E1 (opponent-K%): Cole 11K (7/22) + Sale 11K (7/23) = 2 straight elite-K arms torched our UNDER; book-info not book-error. Top priority.",
  "Sunday weekly review: cumulative Brier raw-vs-shrunk A/B (n_both=4 so far), dashboard, backup bundle",
  "monitor: shrinkage+gates removed 2 winners on 7/23 (Williams O, Dobnak U) — track if pattern persists (n tiny)"
]
json.dump(S,open("state.json","w"),indent=1)
print("state.json written.")
