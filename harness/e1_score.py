#!/usr/bin/env python3
"""SCORE the confirmatory E1 replay (task 21). Reads the FROZEN table once, computes every §5 metric
+ complement slice, applies the frozen §6 adopt/gate/reject rule. Line-dependent metrics (displaced-
hit, decision-change ROI) are DEFERRED per §3 (no historical prop lines). Proper score = mean Poisson
log-loss (line-free analog of Brier). Emits report + JSON summary. Run ONCE; no intermediate peeking."""
import csv, math, json, os
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(BASE)
rows=list(csv.DictReader(open("data/mlb/e1_score_pop.csv")))  # PAIRED experiment-of-record (n_prior>=5, <=7/19)
for r in rows:
    for k in ("actual","ek_base","ek_e1","p_asof","o","L","premium","highk"): r[k]=float(r[k])

def mae(rs,key): return sum(abs(r[key]-r["actual"]) for r in rs)/len(rs) if rs else float('nan')
def rmse(rs,key): return (sum((r[key]-r["actual"])**2 for r in rs)/len(rs))**0.5 if rs else float('nan')
def bias(rs,key): return sum(r[key]-r["actual"] for r in rs)/len(rs) if rs else float('nan')
def nll(rs,key):  # Poisson negative log-likelihood (proper score); lower better
    s=0
    for r in rs:
        lam=max(r[key],1e-6); k=r["actual"]
        s+= lam - k*math.log(lam) + math.lgamma(k+1)
    return s/len(rs) if rs else float('nan')
def slope(rs,key):  # regress actual ~ a + b*pred; b is calibration slope
    n=len(rs);
    if n<2: return float('nan')
    xs=[r[key] for r in rs]; ys=[r["actual"] for r in rs]
    mx=sum(xs)/n; my=sum(ys)/n
    num=sum((x-mx)*(y-my) for x,y in zip(xs,ys)); den=sum((x-mx)**2 for x in xs)
    return num/den if den else float('nan')

def block(name,rs):
    return dict(name=name,n=len(rs),
        mae_base=round(mae(rs,"ek_base"),4),mae_e1=round(mae(rs,"ek_e1"),4),
        d_mae=round(mae(rs,"ek_base")-mae(rs,"ek_e1"),4),  # positive = E1 better
        rmse_base=round(rmse(rs,"ek_base"),4),rmse_e1=round(rmse(rs,"ek_e1"),4),
        nll_base=round(nll(rs,"ek_base"),4),nll_e1=round(nll(rs,"ek_e1"),4),
        slope_base=round(slope(rs,"ek_base"),3),slope_e1=round(slope(rs,"ek_e1"),3),
        bias_base=round(bias(rs,"ek_base"),3),bias_e1=round(bias(rs,"ek_e1"),3))

ALL=rows
PREM=[r for r in rows if r["premium"]]
HIGHK=[r for r in rows if r["highk"]]
INTER=[r for r in rows if r["premium"] and r["highk"]]
COMP=[r for r in rows if not(r["premium"] and r["highk"])]   # narrative-repair detector
adj_mag=sum(abs(r["ek_e1"]-r["ek_base"]) for r in rows)/len(rows)

blocks={b["name"]:b for b in [block("OVERALL",ALL),block("premium-K arms",PREM),
    block("high-oppK offenses",HIGHK),block("INTERACTION (prem x highK)",INTER),
    block("COMPLEMENT (rest)",COMP)]}

# ---- frozen §6 decision rule ----
ov=blocks["OVERALL"]; comp=blocks["COMPLEMENT (rest)"]; inter=blocks["INTERACTION (prem x highK)"]
c1 = ov["d_mae"] >= 0.03                                   # overall MAE down >=0.03K
c2 = (ov["nll_e1"] <= ov["nll_base"]+1e-9) and (0.90 <= ov["slope_e1"] <= 1.10)  # score not worse + calib band
c3 = True   # displaced-line hit: DEFERRED (no historical lines) -> not a blocker
c4 = comp["d_mae"] >= -0.01                                # complement improves or within 0.01K
c5 = True   # decision-change ROI: DEFERRED (no historical lines)
adopt = c1 and c2 and c3 and c4 and c5
gate_partial = (not adopt) and (inter["d_mae"] >= 0.10) and (comp["d_mae"] < -0.01)
if adopt: verdict="ADOPT (general)"
elif gate_partial: verdict="GATE-TO-MATCHUP (experimental, premium x highK only)"
else: verdict="REJECT (retain H0: short-run clustering; projections unchanged)"

print(f"=== E1 CONFIRMATORY REPLAY — {len(rows)} starts (frozen table) ===")
print(f"mean |E1 - baseline| adjustment = {adj_mag:.3f} K  (how much opponent-K moves the projection)\n")
print(f"{'slice':<28}{'n':>5}{'MAE base':>10}{'MAE E1':>9}{'ΔMAE':>8}{'NLL base':>10}{'NLL E1':>9}{'slope E1':>9}")
for b in blocks.values():
    print(f"{b['name']:<28}{b['n']:>5}{b['mae_base']:>10.3f}{b['mae_e1']:>9.3f}{b['d_mae']:>+8.3f}{b['nll_base']:>10.3f}{b['nll_e1']:>9.3f}{b['slope_e1']:>9.3f}")
print(f"\nDEFERRED (no historical prop lines): displaced-line hit rate, decision-change ROI -> forward tracking.")
print(f"\nfrozen §6 rule:")
print(f"  [{'PASS' if c1 else 'FAIL'}] overall ΔMAE {ov['d_mae']:+.3f} >= 0.03")
print(f"  [{'PASS' if c2 else 'FAIL'}] NLL not worse ({ov['nll_e1']:.3f} vs {ov['nll_base']:.3f}) AND slope {ov['slope_e1']:.3f} in [0.90,1.10]")
print(f"  [DEFER] displaced-line hit (no lines)")
print(f"  [{'PASS' if c4 else 'FAIL'}] complement ΔMAE {comp['d_mae']:+.3f} >= -0.01 (broad, not narrative-only)")
print(f"  [DEFER] decision-change ROI (no lines)")
print(f"\n  VERDICT: {verdict}")

json.dump(dict(n=len(rows),adj_mag=round(adj_mag,3),blocks=blocks,
    checks=dict(c1_overall_mae=c1,c2_score_calib=c2,c4_complement=c4,
                deferred=["displaced_line_hit","decision_change_roi"]),
    verdict=verdict),open("data/mlb/e1_result.json","w"),indent=1)
print("\nsummary -> data/mlb/e1_result.json")
