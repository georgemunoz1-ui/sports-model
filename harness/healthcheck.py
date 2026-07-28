#!/usr/bin/env python3
"""Session-start integrity gate. Run BEFORE any work. Exit 0 = healthy. Mechanically enforces
what can be enforced (Anthropic/OpenAI harness pattern: rules as tooling, not vibes)."""
import csv, json, os, re, sys, glob, datetime, subprocess
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
fails=[]; warns=[]
def check(name, ok, warn=False):
    tag = "OK " if ok else ("WARN" if warn else "FAIL")
    print(f"[{tag}] {name}")
    if not ok:
        (warns if warn else fails).append(name)

# 1. core files exist
for f in ["state.json","AGENTS.md","AUTHORIZATIONS.md","harness/runbook.md",
          "data/backfill/mlb/2026/results.csv","data/backfill/mlb/2026/park_factors.json"]:
    check(f"exists: {f}", os.path.exists(f))
# 2. state.json parses + invariants
try:
    st=json.load(open("state.json"))
    check("state.json parses", True)
    check("real money still 0 / unauthorized", st["ledgers"]["real_money"]["risked"]==0.0 and not st["ledgers"]["real_money"]["authorized"], warn=True)
    # Label changed 2026-07-28: DEAD -> NO_PROMOTE. "DEAD" overstated the finding -- it read as a
    # property of the problem, when the evidence covers THIS implementation and THIS feature set.
    # The gate is unchanged: no sides plays without a pre-registered experiment beating the market.
    check("sides verdict still NO_PROMOTE (R3)", st["verdicts"]["mlb_sides"]["status"]=="NO_PROMOTE", warn=True)
except Exception as e:
    check(f"state.json parses ({e})", False)
# 3. results.csv integrity
try:
    rows=list(csv.DictReader(open("data/backfill/mlb/2026/results.csv")))
    ids=[r["game_id"] for r in rows]
    finals=[r for r in rows if r["status"]=="final"]
    check(f"results.csv rows={len(rows)} finals={len(finals)} (>=1505)", len(finals)>=1505)
    check("no duplicate game_ids", len(ids)==len(set(ids)))
    bad=[r for r in finals if r["home_win"] not in ("0","1") or r["total"]=="" ]
    check("all finals have home_win+total", len(bad)==0)
    last=max(r["date"] for r in finals)
    days_stale=(datetime.date.today()-datetime.date.fromisoformat(last)).days
    check(f"dataset freshness: last final {last} ({days_stale}d old)", days_stale<=2, warn=True)
except Exception as e:
    check(f"results.csv readable ({e})", False)
# 4. pitcher logs cache
def _logfiles():
    """Only real pitcher logs. README_NOTE.txt lives in this directory and matched *.txt, so it was
    being counted as a log (and fed to the integrity scan, where it parses to width 1 and vanishes)."""
    return [f for f in glob.glob("data/backfill/mlb/2026/pitcher_logs/*.txt")
            if os.path.basename(f)[0] not in "_." and not os.path.basename(f).startswith("README")]
n=len(_logfiles())
check(f"pitcher_logs cached: {n} (>=310)", n>=310)
# 3b. results.csv close_* columns hold OPENING prices. Declared machine-readably so a future CLV
# consumer cannot silently treat them as closes, and so the contaminated range cannot grow unnoticed.
try:
    _cc=json.load(open("data/backfill/mlb/2026/results_close_columns_contamination.json"))
    _rows=list(csv.DictReader(open("data/backfill/mlb/2026/results.csv")))
    _pop={r["date"] for r in _rows if r["close_ml_away"] or r["close_ml_home"] or r["close_total"]}
    _new=sorted(_pop-set(_cc["all_populated_dates"]))
    check(f"close_* contamination declared and not growing ({len(_pop)} dates populated, {len(_new)} undeclared)", not _new)
    for d in _new[:5]: print(f"   UNDECLARED close_* DATE: {d} — is it a real close, or another opening?")
except Exception as e: check(f"close_* contamination manifest ({e})", False)
# 4a. ER/BB placeholder manifest — the caveat used to live only in README_NOTE.txt, which no code
# read and no check tested, so a genuine 0-ER start was indistinguishable from a placeholder.
try:
    _pm=json.load(open("data/backfill/mlb/2026/pitcher_logs/_placeholders.json"))
    _bad=[]
    for r in _pm["rows"]:
        got=None
        for ln in open(f"data/backfill/mlb/2026/pitcher_logs/{r['pitcher_id']}.txt"):
            p=ln.strip().split("|")
            if p and p[0]==r["date"]: got=p; break
        if got is None: _bad.append(f"{r['pitcher_id']} {r['date']} row missing")
        elif not (float(got[2])==0.0 and float(got[4])==0.0):
            _bad.append(f"{r['pitcher_id']} {r['date']} ER/BB no longer 0 — backfilled? drop it from the manifest")
        elif float(got[3])!=r["SO"] or float(got[5])!=r["TBF"]:
            _bad.append(f"{r['pitcher_id']} {r['date']} SO/TBF changed since the manifest was cut")
    check(f"ER/BB placeholder manifest matches logs ({len(_pm['rows'])} rows, {len(_bad)} drift)", not _bad)
    for b in _bad[:5]: print(f"   PLACEHOLDER DRIFT: {b}")
except Exception as e: check(f"ER/BB placeholder manifest ({e})", False)
# 4b. HFA single-source — HFA-SPLIT was two unexplained literals (1.03 / 1.005) across the tree.
try:
    _live={"harness/daily_card.py","engine/v13_1.py"}
    _stray=[]
    for f in sorted(_live):
        for i,ln in enumerate(open(f),1):
            if re.search(r"pfh\*1\.\d+|pf_h\*1\.\d+", ln.replace(" ","")): _stray.append(f"{f}:{i}")
    check(f"HFA read from engine/hfa.py in live paths ({len(_stray)} stray literals)", not _stray)
    for s in _stray[:5]: print(f"   STRAY HFA LITERAL: {s}")
except Exception as e: check(f"HFA single-source scan ({e})", False)
# 5. ledger consistency: pending plays graded?
try:
    lp=st["ledgers"]["kprops_paper"]
    pend=[p for p in lp.get("plays_pending",[]) if p["date"]<str(datetime.date.today())]
    check(f"kprop pending plays from past dates: {len(pend)} (grade them!)", len(pend)==0, warn=True)
except Exception: pass
# 5a1. pitcher-log integrity (Sale-corruption class): dupe dates or consecutive-day REAL starts
try:
    import datetime as _dt
    badlogs=[]
    for f in _logfiles():
        starts=[]
        for ln in open(f):
            p=ln.strip().split("|")
            # exact-width dispatch; width 8 = date|opp|IP|... (forward format) was previously
            # skipped entirely by this scan, so an 8-field log could not be integrity-checked
            if len(p)==10 and p[9]=="1": starts.append((p[0],float(p[4])))
            elif len(p)==8 and p[7]=="1": starts.append((p[0],float(p[2])))
            elif len(p)==7 and p[6]=="1": starts.append((p[0],float(p[1])))
        starts.sort()
        # Taco validation spec 7/23: dupes/spacing FLAG for reconciliation, never auto-verdict.
        if len(starts)!=len(set(d for d,_ in starts)): badlogs.append((f,"dupe-date (check DH vs phantom)")); continue
        for (d1,ip1),(d2,ip2) in zip(starts,starts[1:]):
            if (_dt.date.fromisoformat(d2)-_dt.date.fromisoformat(d1)).days<3 and ip1>3 and ip2>3:
                badlogs.append((f,"traditional-starter <3d gap")); break
    check(f"pitcher-log integrity ({len(badlogs)} flagged -> reconcile per runbook, do NOT delete)", len(badlogs)==0, warn=True)
    if badlogs:
        for f,why in badlogs[:5]: print(f"   RECONCILE: {f} ({why})")
except Exception as e: check(f"log-integrity scan ({e})", False)
# 5a2. engine self-test (Sale regression + sample gates) — mechanical protection
try:
    r=subprocess.run([sys.executable,"engine/kprops.py"],capture_output=True,text=True)
    check(f"kprops self-test ({r.stdout.strip()})", r.returncode==0)
except Exception as e: check(f"kprops self-test ran ({e})", False)
# 5a2b. parse-equivalence: engine/kprops.py is a published KSIM lineage hash. If it changes, the
# change must be proven a no-op on the frozen inputs rather than silently accepted.
try:
    r=subprocess.run([sys.executable,"harness/test_parse_equivalence.py"],capture_output=True,text=True)
    check(f"parse equivalence ({(r.stdout.strip().splitlines() or ['no output'])[-1]})", r.returncode==0)
except Exception as e: check(f"parse equivalence ran ({e})", False)
# 5a3. gate counter: COMPUTED, not typed. The gate line used to be written as
# record_w + record_l on every --register run, which counts every settled row whatever
# policy produced it -- so a prospective 0/100 was silently clobbered back to 9/100.
# This FAILS rather than warns: a gate that has quietly drifted is worse than no gate.
try:
    r=subprocess.run([sys.executable,"harness/policy_gate.py","--selftest"],capture_output=True,text=True)
    check(f"policy gate self-test ({(r.stdout+r.stderr).strip().splitlines()[-1] if (r.stdout+r.stderr).strip() else 'no output'})", r.returncode==0)
    sys.path.insert(0,"harness"); import policy_gate
    st2=json.load(open("state.json")); gc=policy_gate.gate_counts(st2)
    stored=st2["gates"]["kprops_go_live"]["progress"]
    check("gate string matches recomputed value", stored==policy_gate.progress_string(st2))
    check(f"prospective gate counts only current-policy rows ({gc['prospective_graded']}/{gc['prospective_target']} under {gc['policy_version']})",
          gc["prospective_graded"]==len(policy_gate.prospective_rows(st2)))
    check(f"historical audit preserved ({gc['historical_settled']} settled, {gc['historical_record']}, {gc['historical_units']:+.2f}u)",
          gc["historical_settled"]==st2["ledgers"]["kprops_paper"]["record_w"]+st2["ledgers"]["kprops_paper"]["record_l"])
    check("no invented policy tag on historical rows",
          all(x.get("decision_policy_version") is None for x in policy_gate.untagged_rows(st2)))
except Exception as e: check(f"policy gate checks ({e})", False)
# 5b. git hygiene: no large uncommitted drift
import subprocess
try:
    dirty=subprocess.run(["git","status","--porcelain"],capture_output=True,text=True).stdout.strip()
    check(f"git tree: {len(dirty.splitlines())} uncommitted path(s) (<=3 tolerated)", len(dirty.splitlines())<=3, warn=True)
except Exception: pass
# 6. progress journal fresh
if os.path.exists("docs/progress.md"):
    mtime=datetime.date.fromtimestamp(os.path.getmtime("docs/progress.md"))
    check(f"progress.md last touched {mtime}", (datetime.date.today()-mtime).days<=2, warn=True)
else: check("docs/progress.md exists", False, warn=True)
print(f"\n{'HEALTHY' if not fails else 'UNHEALTHY'} — {len(fails)} fail, {len(warns)} warn")
if fails: print("Fix FAILs before new work:", fails)
sys.exit(1 if fails else 0)
