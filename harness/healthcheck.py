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
    # home_win is mandatory on every final. total may be empty ONLY on an explicit WINNER-ONLY
    # row: result_status PROVISIONAL with BOTH scores empty (winner proven by tier-1 standings
    # arithmetic before any box supplies the score, as on 2026-08-11). A FINAL-status row or a
    # row with any score present must still carry a total — partial scores stay a hard failure.
    def _winner_only(r):
        return (r.get("result_status")=="PROVISIONAL" and r.get("away_score","")==""
                and r.get("home_score","")=="")
    bad=[r for r in finals if r["home_win"] not in ("0","1")
         or (r["total"]=="" and not _winner_only(r))]
    check("all finals have home_win+total (or explicit winner-only PROVISIONAL)", len(bad)==0)
    last=max(r["date"] for r in finals)
    days_stale=(datetime.date.today()-datetime.date.fromisoformat(last)).days
    # Freshness is satisfied by PROVISIONAL rows too. Requiring FINAL here would recreate the exact
    # pressure that caused the 2026-08-08 incident: statsapi was egress-blocked, the gate demanded a
    # current dataset, and the agent improvised search snippets into finals to satisfy it.
    check(f"dataset freshness: last final {last} ({days_stale}d old)", days_stale<=2, warn=True)
except Exception as e:
    check(f"results.csv readable ({e})", False)
# 3b. OUTCOME-LABEL provenance + content integrity (added 2026-08-10 after the 8/8 ingestion
# failure: the old block validated SHAPE only and passed HEALTHY on three reversed winners).
try:
    import importlib.util as _ilu
    def _load(mod, path):
        s=_ilu.spec_from_file_location(mod, path); m=_ilu.module_from_spec(s); s.loader.exec_module(m); return m
    _rp=_load("result_provenance","harness/result_provenance.py")
    _rc=_load("result_content_checks","harness/result_content_checks.py")
    _rows=list(csv.DictReader(open("data/backfill/mlb/2026/results.csv")))
    # (a) provenance: only tier-1 may claim FINAL; a cited evidence file must exist and its hash match.
    _probs,_stats=_rp.audit_rows(_rows)
    check(f"result provenance ({_stats['FINAL']} FINAL/tier-1, {_stats['PROVISIONAL']} PROVISIONAL, "
          f"{_stats['evidence_bound']} evidence-bound){'' if not _probs else ': '+_probs[0]}", not _probs)
    # (b) orientation flips: only a verbatim winner NAME from the source can catch these, because a
    # flipped row is internally consistent. Reported honestly as UNCHECKABLE when evidence lacks it.
    _mism,_checked=_rc.winner_name_mismatch(_rows)
    check(f"winner-name reconciliation ({_checked} rows checkable, {len(_mism)} mismatch)", not _mism)
    # (c) adjacent-day echo: a RECONCILE signal, not a verdict — genuine repeats exist, so this warns.
    _un=_rc.unreconciled_echoes(_rows)
    check(f"adjacent-day duplicate scores on non-tier-1 sources: {len(_un)} "
          f"({', '.join(h['matchup']+' '+h['dates'][1] for h in _un[:3]) or 'none'})", not _un, warn=True)
    # (d) completeness: a game on a frozen slate that never got a result (the 7/23 class).
    _miss=_rc.slate_completeness(_rows)
    check(f"frozen-slate games missing a result: {len(_miss)}", not _miss)
    # (e) REGISTRATION IS THE ONLY WAY TO GRADE. The 8/6-8/9 gradings were reported to the owner as
    # "diagnostic evidence toward the promotion gate" while never entering the hash-chained registry
    # at all (head.json sat at 71/69). Any date with a committed card AND finals must be registered.
    # Scoped to dates on/after the registry's authorization (2026-07-28); earlier cards predate it.
    _REG_START="2026-07-28"
    _cd={os.path.basename(p).split("_")[0] for p in glob.glob("cards/*_card.json")}
    _fd={r["date"] for r in _rows if r["status"]=="final"}
    _rd={json.loads(l).get("slate_date") for l in open("data/mlb/forecasts/forecasts.jsonl")}
    _unreg=sorted(d for d in (_cd & _fd) if d>=_REG_START and d not in _rd)
    check(f"graded slates registered in the forecast registry (unregistered: {_unreg or 'none'})", not _unreg)
except Exception as e:
    check(f"result provenance/content checks ({e})", False)
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
# 5a2b. TWO SEPARATE lineage verifiers, deliberately not merged. A asserts what generated Phase 1
# and never accepts a successor hash; B asks whether the current engine still agrees. Merging them
# would let 'enrolment' quietly weaken the provenance claim.
try:
    # VERIFIER A: provenance. Reads every input from the freeze commit; never accepts a successor.
    ra=subprocess.run([sys.executable,"harness/verify_lineage.py"],capture_output=True,text=True)
    check("FROZEN_LINEAGE (verifier A: published hashes describe commit 6d4a7c0)", ra.returncode==0)
    # VERIFIER B: does the CURRENT engine agree with the frozen one? Cannot alter what A asserts.
    rb=subprocess.run([sys.executable,"harness/test_parse_equivalence.py"],capture_output=True,text=True)
    check(f"SUCCESSOR_EQUIVALENCE (verifier B: {(rb.stdout.strip().splitlines() or ['no output'])[-1][:60]})", rb.returncode==0)
except Exception as e: check(f"parse equivalence ran ({e})", False)
# 5a2c2. forecast/grade registries: hash-chain + rules + falsification battery
try:
    r=subprocess.run([sys.executable,"harness/forecast_registry.py"],capture_output=True,text=True)
    check(f"forecast registry ({(r.stdout.strip().splitlines() or ['no output'])[-1][:70]})", r.returncode==0)
    r=subprocess.run([sys.executable,"harness/test_forecast_registry.py"],capture_output=True,text=True)
    check(f"forecast-registry falsifications ({(r.stdout.strip().splitlines() or ['?'])[-1][:60]})", r.returncode==0)
except Exception as e: check(f"forecast registry ({e})", False)
# 5a2d. ML as-of firewall (P1B): dataset rebuild determinism + manifest + fixture battery
try:
    if os.path.exists("data/mlb/ml_asof/manifest.json"):
        r=subprocess.run([sys.executable,"harness/build_ml_asof.py","--check"],capture_output=True,text=True)
        check(f"ml_asof rebuild {((r.stdout.strip().splitlines() or ['?'])[-1])[:60]}", r.returncode==0)
        import importlib.util as _u
        _sp=_u.spec_from_file_location("bma","harness/build_ml_asof.py"); _bm=_u.module_from_spec(_sp); _sp.loader.exec_module(_bm)
        _mf=json.load(open("data/mlb/ml_asof/manifest.json"))
        _mc=_bm.manifest_check(_mf)
        check(f"ml_asof manifest complete ({len(_mc)} problems)", not _mc)
        _n=sum(1 for _ in open("data/mlb/ml_asof/dataset.jsonl"))
        check(f"ml_asof row count matches manifest ({_n} vs {_mf['row_count']})", _n==_mf["row_count"])
    r=subprocess.run([sys.executable,"harness/test_ml_firewall.py"],capture_output=True,text=True)
    check(f"ml firewall fixtures ({(r.stdout.strip().splitlines() or ['no output'])[-1][:70]})", r.returncode==0)
except Exception as e: check(f"ml firewall ({e})", False)
# 5a2d2. ML-P4 forward generator: frozen-candidate double-hash refusal + disposition fixtures
try:
    r=subprocess.run([sys.executable,"harness/ml_p4_forward.py"],capture_output=True,text=True)
    check(f"ml p4 forward ({(r.stdout.strip().splitlines() or ['no output'])[-1][:70]})", r.returncode==0)
except Exception as e: check(f"ml p4 forward ({e})", False)
# 5a2d3. ML-E1 player-evolution engine (SHADOW dev): math fixtures + honest evidence gate
try:
    r=subprocess.run([sys.executable,"engine/player_evolution.py"],capture_output=True,text=True)
    check(f"player evolution shadow ({(r.stdout.strip().splitlines() or ['no output'])[-1][:70]})", r.returncode==0)
except Exception as e: check(f"player evolution shadow ({e})", False)
# 5a2c. model registry + market priority enforcement (P1A)
try:
    r=subprocess.run([sys.executable,"harness/model_registry.py"],capture_output=True,text=True)
    check(f"model registry ({(r.stdout.strip().splitlines() or ['no output'])[-1][:70]})", r.returncode==0)
    _st=json.load(open("state.json"))
    check("market_priority frozen [ML,K,RL,TOTAL]", _st.get("market_priority")==["ML","K","RL","TOTAL"])
    _ms=_st.get("market_status",{})
    # Owner override 2026-07-28: Phase 4 active states. mlb_sides VERDICT stays NO_PROMOTE separately.
    check("market statuses (ML FORWARD_VALIDATION_ACTIVE, K MAINTENANCE_ONLY_ACTIVE, RL/TOTAL DATA_CAPTURE_ACTIVE)",
          _ms.get("ML")=="FORWARD_VALIDATION_ACTIVE" and _ms.get("K")=="MAINTENANCE_ONLY_ACTIVE"
          and str(_ms.get("RL")).startswith("DATA_CAPTURE_ACTIVE") and str(_ms.get("TOTAL")).startswith("DATA_CAPTURE_ACTIVE"))
    _qp=_st.get("experiment_queue_policy",{})
    _act=_qp.get("active_experiment")
    _ok=_act is None or str(_act).upper().startswith("E4") or "ML" in str(_act).upper()
    check(f"queue policy: no non-ML model-changing experiment active (active={_act})", _ok and not _qp.get("ml_recovery_complete",False) or _ok)
except Exception as e: check(f"P1A enforcement ({e})", False)
# 5a3. gate counter: COMPUTED, not typed. The gate line used to be written as
# record_w + record_l on every --register run, which counts every settled row whatever
# policy produced it -- so a prospective 0/100 was silently clobbered back to 9/100.
# This FAILS rather than warns: a gate that has quietly drifted is worse than no gate.
# Outcome-label tooling selftests. An ungated selftest is a selftest that stops being run: the 8/5
# "echo guard" existed only as prose and was never executed, so it never prevented anything.
for _m in ("result_provenance","result_content_checks","parse_box_dump",
           "acquisition_ledger","missing_data_audit","tier_discipline","artifact_immutability",
           "tier1_board_gate","form_refresh_diff","tier1_lineage","pregame_preflight","card_render",
           "settlement_contract","unified_card","decision_card","ats_ledgers",
           "journal_continuity","acquisition_ladder","echo_gate","sports_acquisition","retry_ladder",
           "information_class","grade_ledger","baseline_offset","paired_eval",
           "adaptive_layers","adaptive_state","empirical_uncertainty","drift_monitor",
           "champion_challenger",
           # 2026-08-23: the never-adapt audit found that the SAME-BOOK DE-VIG requirement was
           # on the do-not-adapt list with no enforcing module running here. freshness_gates
           # carries the cross-book guard and a full selftest, and was simply never wired.
           "freshness_gates","never_adapt_audit","forecast_contract","evaluation_standard","prequential","promotion_gate","evaluation_arm","keyed_seed","cohort_fork","three_arm_card",
           # 2026-08-23 owner amendments 1-10. Wired the same day they were written: a rule
           # that is not executed by this gate is a rule that stops running (lesson 26).
           "arm_coverage","totals_estimand","simulation_standard","render_contract",
           "franchise_identity","finalization_evidence",
           # 2026-08-24 owner directives: source attribution, and who stamped the clock.
           "source_artifact_gate","prospectivity_evidence","widening_rule","anchor_verify",
           # 2026-08-24 price recovery: the ladder, the overlay contract, the EV screen and
           # the distributional identity that "distribution retained" was standing in for.
           "price_acquisition","price_overlay","ev_screen","distribution_identity",
           "uncertainty_estimand","decision_view"):
    _r=subprocess.run([sys.executable,f"harness/{_m}.py","--selftest"],capture_output=True,text=True)
    _out=(_r.stdout+_r.stderr).strip().splitlines()
    check(f"{_m} selftest ({_out[-1][:72] if _out else 'no output'})", _r.returncode==0)
# 5a2e. WORKFLOW SHELL SYNTAX. The first timestamp-anchor run died in under a second on an
# indented quoted heredoc, whose terminator must sit at column 0. A `run:` block is shell that
# nothing checked before it reached GitHub. `bash -n` parses without executing, so this costs
# nothing and would have caught it.
try:
    import yaml as _yaml, tempfile as _tf
    _wf=sorted(glob.glob(".github/workflows/*.yml"))+sorted(glob.glob(".github/workflows/*.yaml"))
    _bad=[]
    for _p in _wf:
        try: _d=_yaml.safe_load(open(_p))
        except Exception as _e: _bad.append(f"{_p}: YAML {_e}"); continue
        for _jn,_j in (_d.get("jobs") or {}).items():
            for _st in (_j.get("steps") or []):
                _r=_st.get("run")
                if not _r: continue
                with _tf.NamedTemporaryFile("w",suffix=".sh",delete=False) as _fh:
                    _fh.write(_r); _sp=_fh.name
                _rc=subprocess.run(["bash","-n",_sp],capture_output=True,text=True)
                os.unlink(_sp)
                if _rc.returncode!=0:
                    _bad.append(f"{_p}:{_jn}:{_st.get('name','?')}: {_rc.stderr.strip().splitlines()[-1] if _rc.stderr.strip() else 'shell syntax error'}")
    check(f"workflow shell syntax ({len(_wf)} workflow file(s)){'' if not _bad else ': '+_bad[0]}", not _bad)
except ImportError:
    check("workflow shell syntax (pyyaml absent — NOT CHECKED)", True, warn=True)

# 5a3b. per-game acquisition coverage + canonical-tier discipline (owner ruling 2026-08-16).
# These are GATES, not selftests: they read the live ledgers and the live canonical table, so they
# fail when a date-level deferral, a post-ruling tier-2/3 canonical ingestion, a duplicate grade, or
# a forecast generated after first pitch actually appears in the repository.
try:
    _r=subprocess.run([sys.executable,"harness/acquisition_ledger.py","--gate"],capture_output=True,text=True)
    _out=(_r.stdout+_r.stderr).strip().splitlines()
    check(f"acquisition ledgers valid ({_out[0][:72] if _out else 'no output'})", _r.returncode==0)
    _r=subprocess.run([sys.executable,"harness/missing_data_audit.py","--gate"],capture_output=True,text=True)
    _out=(_r.stdout+_r.stderr).strip().splitlines()
    check(f"missing-data audit ({_out[-1][:80] if _out else 'no output'})", _r.returncode==0)
    # Canonical-tier exposure must never GROW. It does not fail on today's 136 legacy rows (removing
    # those changes a FROZEN model's as-of inputs and is an owner decision) — it fails the moment a
    # NEW non-tier-1 row becomes visible to the repo's tier-blind label consumers.
    _r=subprocess.run([sys.executable,"harness/tier_discipline.py","--gate"],capture_output=True,text=True)
    _out=(_r.stdout+_r.stderr).strip().splitlines()
    check(f"canonical-tier exposure ({_out[0][:80] if _out else 'no output'})", _r.returncode==0)
    # Registered cohort artifacts must still hash to what was registered. daily_card.py hardcodes its
    # output path, so a rebuild for a date CLOBBERS that date's v1 artifact; this makes the resulting
    # damage impossible to miss instead of relying on the operator having kept a copy.
    _r=subprocess.run([sys.executable,"harness/artifact_immutability.py","--gate"],capture_output=True,text=True)
    _out=(_r.stdout+_r.stderr).strip().splitlines()
    check(f"registered-artifact immutability ({_out[0][:78] if _out else 'no output'})", _r.returncode==0)
    # 5a3c. INFORMATION CLASS (owner ruling 2026-08-23). Every card carries a class DERIVED FROM ITS
    # SLOT STATS, and an all-CAP slate is a baseline cohort with ACTION_AUTHORITY = NONE. This gate
    # re-derives the class of every card and fails on drift, on a card that was never classified,
    # and on a ledgered authority that contradicts the class. Five committed cards are all-CAP.
    _r=subprocess.run([sys.executable,"harness/information_class.py","--gate"],capture_output=True,text=True)
    _out=(_r.stdout+_r.stderr).strip().splitlines()
    check(f"information-class ledger ({_out[0][:78] if _out else 'no output'})", _r.returncode==0)
    # 5a3d. GRADE SUMMARIES ARE DERIVED (owner ruling 2026-08-23, ordered before item 2). The
    # per-game ledger is canonical; every cohort statistic must rebuild from all active
    # non-superseded records, bind its grade ids and an input hash, and reproduce exactly. This
    # fails on a partial summary, a stale binding, statistic drift, and on the specific 2026-08-21
    # shape where already_graded_skipped was substituted for previously graded rows.
    _r=subprocess.run([sys.executable,"harness/grade_ledger.py","--gate"],capture_output=True,text=True)
    _out=(_r.stdout+_r.stderr).strip().splitlines()
    check(f"grade-summary reproducibility ({_out[0][:78] if _out else 'no output'})", _r.returncode==0)
    # 5a3e. NEVER-ADAPT AUDIT (owner ruling 2026-08-23). Ten things must never adapt automatically.
    # This fails when any of them is bound to a module that does not actually RUN here — a rule that
    # is documented, implemented and never executed reads exactly like a rule that works. On its
    # first run it found the same-book de-vig requirement in precisely that state.
    _r=subprocess.run([sys.executable,"harness/never_adapt_audit.py"],capture_output=True,text=True)
    _out=(_r.stdout+_r.stderr).strip().splitlines()
    check(f"never-adapt enforcement ({_out[0][:70] if _out else 'no output'})", _r.returncode==0)
    # Tier-1 board completeness for the 8/15-8/16 refresh window (owner instruction 2026-08-17).
    # Completeness is proven by the 30-franchise slot invariant, not by trusting the board's own
    # expected_game_count, and every row's evidence file is re-hashed against what was recorded.
    _r=subprocess.run([sys.executable,"harness/tier1_board_gate.py","--gate"],capture_output=True,text=True)
    _out=[l for l in (_r.stdout+_r.stderr).strip().splitlines() if "missing_tier1" in l or "LATEST" in l]
    check(f"tier-1 board completeness ({'; '.join(x.strip() for x in _out[:2])[:96] if _out else 'no output'})",
          _r.returncode==0)
    # PREGAME PREFLIGHT (owner 2026-08-17): "model gates cannot compensate for absent pregame inputs."
    # Every other gate here checks the QUALITY of data that arrived; this one fires when data never
    # arrives, which is what actually cost 2026-08-16. It fails only once the acquisition window has
    # CLOSED -- a gate keyed to mere absence would fail every morning and be ignored by lunchtime.
    _now=datetime.datetime.now(datetime.timezone.utc)
    # today (still actionable if pregame) and tomorrow (the one that gets forgotten)
    for _d in [_now.strftime("%Y-%m-%d"), (_now+datetime.timedelta(days=1)).strftime("%Y-%m-%d")]:
        _r=subprocess.run([sys.executable,"harness/pregame_preflight.py","--date",_d,"--gate"],
                          capture_output=True,text=True)
        _out=(_r.stdout+_r.stderr).strip().splitlines()
        check(f"pregame inputs for {_d} ({_out[0][:80] if _out else 'no output'})",
              _r.returncode==0, warn=True)
    # Settlement contract (owner 2026-08-19): estimands structured and separate, no generic 'side',
    # no ATS grade without a pre-tip selection id. Pre-cutoff records grandfathered.
    _r=subprocess.run([sys.executable,"harness/settlement_contract.py","--gate"],capture_output=True,text=True)
    _out=(_r.stdout+_r.stderr).strip().splitlines()
    check(f"settlement contract ({_out[0][:78] if _out else 'no output'})", _r.returncode==0)
    # The successor lineage must never silently certify itself while it has interior gaps.
    _r=subprocess.run([sys.executable,"harness/tier1_lineage.py","--gate"],capture_output=True,text=True)
    _out=[l for l in (_r.stdout+_r.stderr).strip().splitlines() if "READINESS" in l or "whole days" in l]
    check(f"tier-1 successor lineage ({' '.join(x.strip() for x in _out)[:88] if _out else 'no output'})",
          _r.returncode==0, warn=True)
except Exception as e: check(f"acquisition/audit gates ({e})", False)
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
# 6c. SEMANTIC journal continuity (owner ruling 2026-08-22). mtime is an extra signal, NOT the
#     source of truth: it moves on checkout, restore, copy and touch, and says nothing about whether
#     the file a COLD SESSION reads contains the latest work. This checks committed content:
#     exactly one canonical journal, the latest committed entry and its date, the commit it binds
#     to, a cold-bootstrap simulation through the loader window PARSED OUT OF AGENTS.md, and that
#     the closed redirect carries no independent state.
try:
    import journal_continuity as _jc
    _ok, _jf, _jd = _jc.check()
    check(f"journal continuity (latest committed entry {_jd.get('latest_committed_entry')}, "
          f"cold-bootstrap window {(_jd.get('loader') or {}).get('lines')} lines)", _ok)
    if not _ok:
        for _x in _jf:
            print(f"       ! {_x}")
    for _w in (_jd.get("warnings") or []):
        check(f"journal: {_w}", False, warn=True)
except Exception as e:
    check(f"journal continuity check ({e})", False)
# 6b. journal split: AGENTS.md step 3, runbook.md and check 6 above all read docs/progress.md.
#     A second journal at the repo root existed and silently took the daily entries from 2026-08-20
#     onward, so the file the next session actually bootstraps from went three days stale while
#     looking maintained. Freshness of the canonical file is not enough — a stray journal that is
#     NEWER than it means handoff state is being written where nobody reads it.
if os.path.exists("progress.md") and os.path.exists("docs/progress.md"):
    stray=os.path.getmtime("progress.md"); canon=os.path.getmtime("docs/progress.md")
    check("journal split: root progress.md is not newer than canonical docs/progress.md",
          stray<=canon, warn=True)
print(f"\n{'HEALTHY' if not fails else 'UNHEALTHY'} — {len(fails)} fail, {len(warns)} warn")
if fails: print("Fix FAILs before new work:", fails)
sys.exit(1 if fails else 0)
