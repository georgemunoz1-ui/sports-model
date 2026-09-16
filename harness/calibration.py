"""Calibration layer — method ladder, sample-size gate, leakage rules, metrics, decision table.

TIER-5 module, SHIPPED DORMANT: the current WNBA bound Tier-1 base is n=4 and the sample-size
gate below refuses every fit under 500 events. Nothing here runs in a forecast path; it is an
evaluation-layer tool bound to the PointInTime store (harness/backtest_causal.py).

METHOD LADDER (binary markets — ML/spread/total/props):
  1. raw probabilities (ALWAYS reported alongside any calibrator)
  2. Platt scaling — baseline; fit on raw scores/logits where available
  3. Beta calibration — challenger for favorite/underdog asymmetry:
       p_hat = sigma(a*log(p) - b*log(1-p) + c);  a reshapes the low tail, b the high tail,
       c the global shift (never set manually)
  4. Isotonic — only with >10k broad calibration rows AND balanced per-bucket coverage
     (per-bucket n checked, not just the total); rejected when it wins only in-sample
Multiclass is out of scope for the current leagues; the sum-to-1 guard below is the tripwire:
classes must NEVER be independently calibrated (sum-to-1 violation). Tree models, if added
later, start Platt -> beta, never temperature.

SAMPLE-SIZE GATE (named constants, enforced by gate_method):
  <500 events           -> NO calibrator (raw + reliability diagnostics only)
  500-2,000             -> Platt only
  2,000-10,000          -> Platt vs beta
  >10,000 broad+balanced -> isotonic eligible

LEAKAGE RULES (bound to the PointInTime store): three chronological stages per fold —
train the base model / fit the calibrator on OUT-OF-SAMPLE predictions / evaluate on an
untouched later period. fit() REFUSES predictions marked as coming from the training stage
(calibrator-fit-on-training-predictions detection). Calibration data respects decision_time
exactly like features. Method SELECTION uses a separate chronological window from the final
test — never pick the winner on the test set.

METRICS: log loss is the primary selection score (it punishes overconfident-wrong — the
financially dangerous case for sizing); Brier companion; reliability slope/intercept + ECE by
bucket; sharpness reported separately. CLV and post-vig ROI are separate betting tests and are
NEVER mixed into calibration scoring.
"""
from __future__ import annotations

MODULE_ID = "calibration"

import math
import sys

#: sample-size gate constants (owner-specified)
CAL_MIN_EVENTS = 500          # below: no calibrator at all
CAL_PLATT_ONLY_MAX = 2000     # 500-2,000: Platt only
CAL_ISOTONIC_MIN = 10000      # >10,000 broad+balanced: isotonic eligible

CLIP = 1e-6                   # probabilities are clipped at 1e-6 before any log
SUM_TO_1_TOL = 1e-6

METHODS = ("NONE", "PLATT", "BETA", "ISOTONIC")


class CalibratorRefused(RuntimeError):
    """The gate, the leakage rules, or a numerical guard refused the fit. Fail-closed."""


def clip_prob(p):
    """Clip before logs: 0/1 probabilities are infinitely confident and infinitely wrong."""
    return min(1.0 - CLIP, max(CLIP, float(p)))


def gate_method(n_events, broad_and_balanced=False, bucket_ns=None):
    """The sample-size gate as a rule with named constants. Returns the eligible ladder rung.
    bucket_ns: per-bucket row counts; isotonic needs breadth AND balance, checked per bucket,
    not just the total."""
    if n_events < CAL_MIN_EVENTS:
        raise CalibratorRefused(
            f"n={n_events} < CAL_MIN_EVENTS={CAL_MIN_EVENTS}: NO calibrator — report raw "
            "probabilities plus reliability diagnostics only (the current WNBA bound Tier-1 "
            "base is n=4; this layer is dormant)")
    if n_events <= CAL_PLATT_ONLY_MAX:
        return "PLATT"
    if n_events <= CAL_ISOTONIC_MIN:
        return "PLATT_VS_BETA"
    if broad_and_balanced and bucket_ns and min(bucket_ns) >= CAL_MIN_EVENTS:
        return "ISOTONIC_ELIGIBLE"
    return "PLATT_VS_BETA"


def _sigmoid(z):
    return 1.0 / (1.0 + math.exp(-z))


def fit(method, scores, labels, fold_role="calibrate", max_iter=2000, lr=0.05):
    """Fit a binary calibrator. scores: raw probabilities (or logits for Platt).

    LEAKAGE: fold_role MUST be 'calibrate' — out-of-sample predictions only. 'train' or 'test'
    is refused: a calibrator fit on training predictions is overfit before it starts, and one
    fit on test predictions is selection on the evaluation set.
    """
    if fold_role != "calibrate":
        raise CalibratorRefused(
            f"fold_role={fold_role!r}: a calibrator fits ONLY on out-of-sample 'calibrate' "
            "predictions — fitting on training predictions leaks, fitting on test predictions "
            "is method selection on the evaluation set")
    if len(scores) < CAL_MIN_EVENTS:
        raise CalibratorRefused(f"n={len(scores)} < {CAL_MIN_EVENTS}; gate refused")
    y = [float(v) for v in labels]
    if method == "PLATT":
        x = [math.log(clip_prob(s)) - math.log(1 - clip_prob(s)) for s in scores]
        a, b = 1.0, 0.0
        for _ in range(max_iter):
            ga = gb = 0.0
            for xi, yi in zip(x, y):
                e = _sigmoid(a * xi + b) - yi
                ga += e * xi
                gb += e
            a -= lr * ga / len(x)
            b -= lr * gb / len(x)
        return {"method": "PLATT", "a": a, "b": b,
                "predict": lambda s, _a=a, _b=b: _sigmoid(
                    _a * (math.log(clip_prob(s)) - math.log(1 - clip_prob(s))) + _b)}
    if method == "BETA":
        x1 = [math.log(clip_prob(s)) for s in scores]
        x2 = [math.log(1 - clip_prob(s)) for s in scores]
        a, b, c = 1.0, 1.0, 0.0
        for _ in range(max_iter):
            ga = gb = gc = 0.0
            for u, v, yi in zip(x1, x2, y):
                e = _sigmoid(a * u - b * v + c) - yi
                ga += e * u
                gb -= e * v
                gc += e
            n = len(y)
            a -= lr * ga / n
            b -= lr * gb / n
            c -= lr * gc / n
        return {"method": "BETA", "a": a, "b": b, "c": c,
                "predict": lambda s, _a=a, _b=b, _c=c: _sigmoid(
                    _a * math.log(clip_prob(s)) - _b * math.log(1 - clip_prob(s)) + _c)}
    if method == "ISOTONIC":
        order = sorted(zip(scores, y))
        xs = [clip_prob(s) for s, _ in order]
        ys = [v for _, v in order]
        # pool-adjacent-violators
        w = list(ys)
        cnt = [1] * len(w)
        i = 0
        while i < len(w) - 1:
            if w[i] > w[i + 1] + 1e-12:
                w[i] = (w[i] * cnt[i] + w[i + 1] * cnt[i + 1]) / (cnt[i] + cnt[i + 1])
                cnt[i] += cnt[i + 1]
                del w[i + 1]
                del cnt[i + 1]
                i = max(0, i - 1)
            else:
                i += 1
        knots = list(zip([xs[0]] + xs, [w[0]] + w))

        def _iso(s, _xs=xs, _w=w):
            s = clip_prob(s)
            for xv, wv in zip(_xs, _w):
                if s <= xv:
                    return wv
            return _w[-1]
        return {"method": "ISOTONIC", "predict": _iso}
    raise CalibratorRefused(f"unknown method {method!r}")


def assert_multiclass_sum_to_1(prob_rows):
    """Sum-to-1 guard for any multiclass path: classes are NEVER independently calibrated.
    Any row whose class probabilities do not sum to 1 is a sum-to-1 violation — refuse it."""
    for i, row in enumerate(prob_rows):
        if abs(sum(row) - 1.0) > SUM_TO_1_TOL:
            raise CalibratorRefused(
                f"row {i} sums to {sum(row)}: independent per-class calibration violates "
                "sum-to-1; multiclass needs temperature/vector/Dirichlet, not per-class fits")
    return True


def log_loss(probs, labels):
    """PRIMARY selection score: punishes overconfident-wrong — the financially dangerous case."""
    return -sum(y * math.log(clip_prob(p)) + (1 - y) * math.log(1 - clip_prob(p))
                for p, y in zip(probs, labels)) / len(labels)


def brier(probs, labels):
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(labels)


def reliability(probs, labels, n_buckets=10):
    """ECE by bucket plus slope/intercept; per-bucket n is returned because balance is checked
    per bucket, never just on the total (isotonic gate)."""
    buckets = {}
    for p, y in zip(probs, labels):
        buckets.setdefault(min(n_buckets - 1, int(clip_prob(p) * n_buckets)), []).append((p, y))
    ece = 0.0
    per_bucket = {}
    for b, rows in sorted(buckets.items()):
        mp = sum(p for p, _ in rows) / len(rows)
        my = sum(y for _, y in rows) / len(rows)
        ece += len(rows) / len(probs) * abs(mp - my)
        per_bucket[b] = {"n": len(rows), "mean_pred": mp, "mean_obs": my}
    mp = sum(probs) / len(probs)
    my = sum(labels) / len(labels)
    var = sum((p - mp) ** 2 for p in probs) or 1e-12
    slope = sum((p - mp) * (y - my) for p, y in zip(probs, labels)) / var
    return {"ece": ece, "slope": slope, "intercept": my - slope * mp,
            "per_bucket": per_bucket, "sharpness_mean_pred": mp}


def decide(fold_results):
    """THE DECISION TABLE, encoded verbatim from the owner spec.

    fold_results: {method: {"logloss_oos": [per-fold], "wins_seasons": n_seasons_won,
                  "clv_harm": bool, "unstable_ev_tails": bool, "in_sample_only_win": bool}}.
    """
    raw = fold_results.get("RAW", {}).get("logloss_oos") or [float("inf")]
    raw_ll = sum(raw) / len(raw)
    out = {}
    for m in ("PLATT", "BETA", "ISOTONIC"):
        r = fold_results.get(m)
        if not r:
            continue
        ll = sum(r["logloss_oos"]) / len(r["logloss_oos"])
        out[m] = {**r, "mean_ll": ll, "beats_raw": ll < raw_ll}
    if not any(v["beats_raw"] for v in out.values()):
        return {"decision": "RAW", "why": "neither calibrator improves out-of-sample; keep raw, "
                                          "revisit the base model"}
    iso = out.get("ISOTONIC")
    if iso and iso.get("in_sample_only_win"):
        return {"decision": "PLATT" if out.get("PLATT", {}).get("beats_raw") else "RAW",
                "why": "isotonic win was in-sample only — rejected"}
    beta = out.get("BETA")
    platt = out.get("PLATT")
    if beta and beta["beats_raw"]:
        if beta.get("clv_harm") or beta.get("unstable_ev_tails"):
            return {"decision": "PLATT", "why": "beta improves calibration but harms CLV / has "
                                                "unstable EV tails — clip/shrink or Platt"}
        if beta.get("wins_seasons", 0) <= 1 and platt:
            return {"decision": "PLATT", "why": "beta wins one season only — Platt"}
        return {"decision": "BETA", "why": "beta wins across most folds with stable tails"}
    return {"decision": "PLATT", "why": "Platt wins"}


# ====================================================================== selftest

def selftest():
    import random
    f = []
    # gate: dormant under 500 (the current WNBA n=4 case), Platt-only to 2000, beta window, isotonic
    for n in (4, 499):
        try:
            gate_method(n)
            f.append(f"the gate allowed a fit at n={n}")
        except CalibratorRefused:
            pass
    if gate_method(600) != "PLATT" or gate_method(3000) != "PLATT_VS_BETA":
        f.append("gate rungs wrong in the Platt/beta windows")
    if gate_method(15000, broad_and_balanced=True, bucket_ns=[1200] * 12) != "ISOTONIC_ELIGIBLE":
        f.append("isotonic gate wrong at 15k broad+balanced")
    if gate_method(15000, broad_and_balanced=True, bucket_ns=[120] * 12) == "ISOTONIC_ELIGIBLE":
        f.append("isotonic admitted with a starved bucket")
    # clipping
    if clip_prob(0.0) != CLIP or clip_prob(1.0) != 1 - CLIP:
        f.append("1e-6 clipping broken")
    # leakage: calibrator on training predictions refused
    random.seed(7)
    probs = [random.random() for _ in range(600)]
    labels = [1 if random.random() < p else 0 for p in probs]
    try:
        fit("PLATT", probs, labels, fold_role="train")
        f.append("a calibrator fit on training predictions was allowed")
    except CalibratorRefused:
        pass
    cal = fit("PLATT", probs, labels, fold_role="calibrate")
    p2 = cal["predict"](0.8)
    if not (0.0 < p2 < 1.0):
        f.append("platt predict out of range")
    # sum-to-1 guard
    try:
        assert_multiclass_sum_to_1([[0.5, 0.4, 0.2]])
        f.append("a sum-to-1 violation passed")
    except CalibratorRefused:
        pass
    assert_multiclass_sum_to_1([[0.5, 0.3, 0.2]])
    # metrics sane
    ll = log_loss([0.9, 0.1], [1, 0])
    if ll > 0.2:
        f.append(f"log loss wrong: {ll}")
    # decision table: in-sample-only isotonic rejected; one-season beta -> Platt
    d = decide({"RAW": {"logloss_oos": [0.7, 0.7]},
                "PLATT": {"logloss_oos": [0.6, 0.62]},
                "ISOTONIC": {"logloss_oos": [0.55, 0.56], "in_sample_only_win": True}})
    if d["decision"] != "PLATT":
        f.append(f"decision table wrong on in-sample isotonic: {d}")
    d2 = decide({"RAW": {"logloss_oos": [0.7]},
                 "PLATT": {"logloss_oos": [0.6]},
                 "BETA": {"logloss_oos": [0.58], "wins_seasons": 1}})
    if d2["decision"] != "PLATT":
        f.append(f"decision table wrong on one-season beta: {d2}")

    print(f"calibration selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("   -", x)
    return 0 if not f else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
