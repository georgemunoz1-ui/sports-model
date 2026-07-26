#!/usr/bin/env python3
"""Apply the verified 2026-07-25 grades to results.csv and state.json.

Reads data/mlb/box/2026-07-25_grades.json, produced by harness/grade_0725.py,
which refuses to run unless the user paste and statsapi agree on all 30 team
scores. Idempotent: re-running does not double-append or double-count.
"""
import json, csv, os

G = json.load(open("data/mlb/box/2026-07-25_grades.json"))
RES = "data/backfill/mlb/2026/results.csv"

# ---- results.csv ------------------------------------------------------------
with open(RES) as f:
    hdr = next(csv.reader(f))
existing = {r["game_id"] for r in csv.DictReader(open(RES))}
new = [r for r in G["results_rows"] if r["game_id"] not in existing]
if new:
    with open(RES, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=hdr)
        for r in new:
            w.writerow({k: r.get(k, "") for k in hdr})
print("results.csv: +%d rows (%d already present)" % (len(new), len(G["results_rows"]) - len(new)))

# ---- state.json -------------------------------------------------------------
s = json.load(open("state.json"))
led = s["ledgers"]["ml_ev_tracking"]
already = {(g["date"], g["pick"]) for g in led["graded"]}
moved = [g for g in G["ml_ev_graded"] if (g["date"], g["pick"]) not in already]
led["graded"].extend(moved)
led["pending"] = [p for p in led["pending"] if p["date"] != "2026-07-25"]
if moved:
    led["record_w"] = G["ml_ev_new"]["w"]
    led["record_l"] = G["ml_ev_new"]["l"]
    led["units"] = G["ml_ev_new"]["units"]
n = led["record_w"] + led["record_l"]
led["roi_pct"] = round(100.0 * led["units"] / n, 1)
led["n_note"] = ("n=%d. Far too few plays to distinguish skill from noise; a 3-play "
                 "ROI is a number, not evidence. No bootstrap CI is quoted because at "
                 "n=%d it would span every plausible value." % (n, n))
print("ml_ev_tracking: %d-%d %+.2fu (ROI %+.1f%%) on n=%d" %
      (led["record_w"], led["record_l"], led["units"], led["roi_pct"], n))

fd = s["ledgers"]["v13_forward_directional"]
if "2026-07-25" not in fd.get("note", ""):
    fd["w"] += G["directional"]["w"]; fd["l"] += G["directional"]["l"]
    fd["note"] = ("7/19-25; 7/25 went %d-%d on the full 15-game slate (tracking only, no stake). "
                  "Cumulative %d-%d = %.1f%%. Sides remain DEAD under R3: a win rate without a "
                  "price is not an edge." % (G["directional"]["w"], G["directional"]["l"],
                                             fd["w"], fd["l"], 100.0 * fd["w"] / (fd["w"] + fd["l"])))
    t = G["totals"]
    fd["total_leans_note"] = ("7/25 total leans %d-%d-%d. Combined with 7/24's 5-7, totals are "
                              "11-16 over two slates. Totals remain NOT_READY." % (t["w"], t["l"], t["p"]))
print("v13_forward_directional: %d-%d; 7/25 totals %d-%d-%d" %
      (fd["w"], fd["l"], G["totals"]["w"], G["totals"]["l"], G["totals"]["p"]))

# ---- K calibration (exploratory) -------------------------------------------
k = G["kcal"]
x = [r["ek"] for r in k["rows"]]; y = [r["so"] for r in k["rows"]]; nn = len(x)
mx, my = sum(x) / nn, sum(y) / nn
sxx = sum((a - mx) ** 2 for a in x); syy = sum((b - my) ** 2 for b in y)
sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
s.setdefault("mlb_kprops", {})["calibration_2026_07_25_oos"] = dict(
    status="EXPLORATORY - one slate, n=%d, not pre-registered, NOT confirmatory" % nn,
    n=nn, mae=round(sum(abs(b - a) for a, b in zip(x, y)) / nn, 2),
    bias_actual_minus_proj=round(my - mx, 2),
    rmse=round((sum((b - a) ** 2 for a, b in zip(x, y)) / nn) ** 0.5, 2),
    corr=round(sxy / (sxx * syy) ** 0.5, 3),
    ols_slope=round(sxy / sxx, 2),
    sd_projected=round((sxx / nn) ** 0.5, 2), sd_actual=round((syy / nn) ** 0.5, 2),
    tail_SO_ge_8=dict(expected_poisson=4.5, actual=6),
    tail_SO_le_3=dict(expected_poisson=5.8, actual=5),
    finding=("Point projections are UNDER-DISPERSED: projected sd 0.96 against actual sd 2.67, "
             "OLS slope 1.35. The shrinkage is too aggressive - the fix would be to stretch the "
             "projections, not to shift them. BUT the quantity K-props actually price is the "
             "Poisson TAIL, and the tails came in close to nominal (6 vs 4.5 expected at SO>=8, "
             "5 vs 5.8 at SO<=3), because Poisson noise supplies most of the missing dispersion. "
             "So this slate is evidence of a real but modest defect in the point estimate and NOT "
             "evidence that prop pricing is broken."),
    caveat=("n=%d on ONE slate. The slope CI is wide enough to include 1.0. This does not license "
            "an engine change; it licenses a pre-registered experiment (R7)." % nn),
    source="2-source verified finals; harness/grade_0725.py")
print("kcal: n=%d MAE %.2f slope %.2f corr %.3f" %
      (nn, s["mlb_kprops"]["calibration_2026_07_25_oos"]["mae"],
       s["mlb_kprops"]["calibration_2026_07_25_oos"]["ols_slope"],
       s["mlb_kprops"]["calibration_2026_07_25_oos"]["corr"]))

# ---- corrections & new known issues ----------------------------------------
ki = s["known_issues"]
def add(obj, key):
    if not any(isinstance(i, dict) and i.get("issue") == key for i in ki):
        ki.append(obj)

add({"issue": "CLOCK CORRECTION: the 'container clock runs ~3.8h fast' finding is WITHDRAWN. It was an artifact.",
     "evidence": ("2026-07-26 03:16Z container time. A statsapi fetch at the URL spelling "
                  "'date=2026-07-25' returned all late games Pre-Game; refetching the SAME data at "
                  "'startDate=&endDate=' returned all 15 Final with scores matching the user's paste "
                  "exactly. NYY@PHI first pitch was 23:20Z and cannot be Final before ~02:20Z, so real "
                  "time was >= 02:20Z on 7/26 - i.e. the container clock was right and the stale read "
                  "was the liar. Every previous 'clock is fast' correction was probably this same "
                  "cached-response artifact."),
     "consequence": ("Provenance stamps written under the old belief are wrong by ~3.8h. The 7/26 board "
                     "was captured at ~02:13Z on 7/26 (not 22:30Z on 7/25), so it is ~14.0h pre-slate, "
                     "not 17.75h. Still genuinely pre-slate: NO pick is invalidated, the claim was "
                     "merely overstated. Corrected in place."),
     "rule": "Do not infer wall-clock time from a WebFetch of live sports state. That inverts the dependency."},
    "CLOCK CORRECTION: the 'container clock runs ~3.8h fast' finding is WITHDRAWN. It was an artifact.")

add({"issue": "WebFetch can serve responses FAR older than the documented 15-minute cache.",
     "evidence": "Same statsapi content, two URL spellings, ~4h apart in freshness, in the same turn. "
                 "timeapi.io returned 2026-07-24T03:40 on 2026-07-26 - two days stale.",
     "rule": "When recency is load-bearing, vary the URL spelling to force a fresh read, and verify "
             "the response against something that cannot be stale (a game that could not yet have finished)."},
    "WebFetch can serve responses FAR older than the documented 15-minute cache.")

add({"issue": "results.csv close_ml_away / close_ml_home / close_total contain OPENING prices, not closes.",
     "scope": "All MLB 2026 rows dated 2026-07-19 through 2026-07-25.",
     "cause": "A true closing snapshot has never once been captured. The card's opening snapshot was "
              "written into the close_* columns for continuity.",
     "consequence": "Any CLV computation (E3) that reads these columns measures nothing. E3 must capture "
                    "its own closes prospectively.",
     "rule": "Do not backfill these retroactively - the closes are gone. Fix forward only."},
    "results.csv close_ml_away / close_ml_home / close_total contain OPENING prices, not closes.")

add({"issue": "Probable-starter staleness and openers are unhandled by the K pipeline.",
     "evidence": "On 7/25, 6 of 30 card starters did not match the actual first arm. PHI used a true "
                 "opener (Tim Mayza, 2.0 IP, then Brian Keller 3.0). SD listed JP Sears but started "
                 "Randy Vasquez; ATH listed Mason Barnett but started Brady Basso (Barnett followed).",
     "consequence": "E[TBF] assumes the listed probable throws a normal start. Against an opener that "
                    "assumption is simply false, and the projection is not merely noisy but wrong.",
     "rule": "Any K play on an arm whose start is an opener/bulk arrangement must be excluded, not "
             "adjusted. There is no detector for this yet."},
    "Probable-starter staleness and openers are unhandled by the K pipeline.")

add({"issue": "SOURCE defect in the 7/25 box paste: LAD@NYM Team Pitching SO row reads 8, true value 9.",
     "evidence": "NYM per-pitcher SO (McLean 7 + Duarte 2 + Brazoban 0) = 9, and LAD's batting SO column "
                 "= 9. Two fields against one; the Team Pitching aggregate is the dissenter.",
     "resolution": "Recorded 9. Resolved by 2-of-3 majority across independent fields, not by preference.",
     "rule": "The Team Pitching row is a Statcast-derived aggregate and is NOT authoritative over the "
             "per-pitcher lines. Keep it as a checksum, never as a source."},
    "SOURCE defect in the 7/25 box paste: LAD@NYM Team Pitching SO row reads 8, true value 9.")

# correct the overstated 7/26 pre-slate margin in place
for p in led["pending"]:
    if p["date"] == "2026-07-26" and "22:30Z" in p.get("price_snapshot", ""):
        p["price_snapshot"] = p["price_snapshot"].replace(
            "captured 2026-07-25T22:30Z, ~18h pre-slate", "captured 2026-07-26T02:13Z, ~14.0h pre-slate")
        p["provenance_correction"] = ("Timestamp corrected 2026-07-26T03:20Z. The original stamp assumed "
                                      "a 3.8h-fast container clock; that belief has been withdrawn. Still "
                                      "genuinely pre-slate, so the registration stands unaltered.")
pj = "cards/2026-07-26_ml_ev_picks.json"
if os.path.exists(pj):
    c = json.load(open(pj))
    c["preregistered_utc"] = "2026-07-26T02:13Z"
    c["hours_before_first_pitch"] = 14.0
    c["timestamp_correction"] = ("Was 2026-07-25T22:30Z / 17.75h. The container-clock-is-fast belief that "
                                 "produced it is withdrawn (see known_issues). Registration still "
                                 "comfortably pre-slate; only the claimed margin shrinks.")
    json.dump(c, open(pj, "w"), indent=1)
    print("corrected", pj)

s["next_actions"] = [
    "Capture a genuine CLOSING snapshot for 7/26 before 16:15Z. Never once done; blocks E3 and E4, and is "
    "now known to be the ONLY way to get real closes since results.csv close_* columns are opens.",
    "Still need real K-prop PRICES. Unblocking artifact remains the source page's 'Export Table Data -> CSV'.",
    "Grade the 7/26 pending rows (COL +265, NYY +140) after the slate.",
    "Pre-register E5: stretch the K point projection (slope correction) - motivated by the 7/25 OOS slope "
    "of 1.35, but n=24 on one slate, so it is a hypothesis and must be tested on an untouched holdout (R7).",
    "Build an opener/bulk detector, or an exclusion for it. 1 of 30 arms on 7/25 was a true opener.",
    "Amend rule 3's written text to match the code (TBD or gs<2), effective 2026-07-27, forward only.",
    "NEXT EXPERIMENT = E3 (before E2): pre-register prop line-move CLV capture, then run.",
    "Sunday weekly review: dashboard + backup bundle + cumulative Brier A/B.",
    "8-field parser fix deferred (no forward opponent writes).",
    "Verify TOR@BOS run-line side labels (still UNVERIFIED) if sides ever leave DEAD status.",
]
s["updated_utc"] = "2026-07-26T03:20:00Z"
json.dump(s, open("state.json", "w"), indent=1)
print("state.json written")
