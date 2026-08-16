#!/usr/bin/env python3
"""
VAL-SYNC — a different approach: no LUT at all.

Everything before this was a 64-point lookup table approximating a smooth
gain function. This uses Raw Accel's native *synchronous* curve instead,
which the official guide calls "what we think is most 'correct'".

Two structural reasons this differs from the LUT builds:

1. WHOLE MODE, NOT BY-COMPONENT. The guide is explicit that by-component
   with different x and y curves produces a vector field WITH CURL — a
   straight diagonal hand movement comes out as a curved cursor path, and
   the direction of travel shifts as you speed up. Our LUT profiles ran
   horizontal-accelerated / vertical-raw, which is exactly that case.
   Whole mode has no curl: "it is precisely the restrictions imposed by
   Whole (no curl) that make it smoother."

2. ANALYTIC, NOT PIECEWISE. A LUT is piecewise linear, so its gain is a
   staircase of 63 constant segments. Synchronous in SENSITIVITY mode
   (Gain switch OFF) evaluates a closed form per packet:

       sens(v) = exp( tanh( (gamma/ln M) * ln(v/syncSpeed) ) * ln M )

   with smooth=0.5 giving sharpness 1 (the tanh case). Note synchronous in
   GAIN mode builds an internal lookup table, so sensitivity mode is the
   only fully analytic path.

Synchronous is log-symmetric about syncSpeed, spanning [1/M, M]. To put
the slow end at exactly 1.000 rather than below it, we set the output DPI
(= sens multiplier * 1000) equal to the motivity, giving an effective
span of [1.000, M^2]. With M = sqrt(1.15) that is [1.000, 1.150] — the
same range as VAL-LOWGRAD, reached smoothly instead of in steps.
"""
import json, math

DPI = 1600.0
TARGET_TOP = 1.15                    # effective multiplier at high speed
MOTIVITY = math.sqrt(TARGET_TOP)     # 1.0724 -> span [1/M, M], lifted to [1, M^2]
GAMMA = 0.12                         # transition sharpness (small: ln(M) is small)
SYNC_INS = 25.0                      # anchor speed in in/s
SMOOTH = 0.5                         # tanh tailing, the documented default
NAME = "VAL-SYNC-1600-015"

SYNC_SPEED = DPI * SYNC_INS / 1000.0        # counts/ms
OUTPUT_DPI = 1000.0 * MOTIVITY              # sens multiplier * 1000

def sens(v, M=MOTIVITY, gamma=GAMMA, ss=SYNC_SPEED, smooth=SMOOTH):
    """Raw Accel synchronous, sensitivity mode. Mirrors activation_framework<LEGACY>."""
    lm = math.log(M)
    gc = gamma / lm
    sharp = 16.0 if smooth == 0 else 0.5 / smooth
    if sharp >= 16:                          # linear-clamp branch
        ls = gc * (math.log(v) - math.log(ss))
        if ls < -1: return 1 / M
        if ls > 1:  return M
        return math.exp(ls * lm)
    if v == ss: return 1.0
    ld = math.log(v) - math.log(ss)
    sr = 1 / sharp
    if ld > 0:
        e = pow(math.tanh(pow(gc * ld, sharp)), sr)
    else:
        e = -pow(math.tanh(pow(-gc * ld, sharp)), sr)
    return math.exp(e * lm)

def effective(v):
    """What you actually feel: sens multiplier * curve."""
    return MOTIVITY * sens(v)

def accel(mode):
    return {
        "mode": mode,
        "Gain / Velocity": False,            # sensitivity mode = fully analytic
        "inputOffset": 0.0, "outputOffset": 0.0,
        "acceleration": 0.005, "decayRate": 0.1,
        "gamma": GAMMA, "motivity": MOTIVITY,
        "exponentClassic": 2.0, "scale": 1.0, "exponentPower": 0.05, "limit": 1.5,
        "syncSpeed": SYNC_SPEED, "smooth": SMOOTH,
        "Cap / Jump": {"x": 15.0, "y": 1.5}, "Cap mode": "output",
        "data": [],
    }

profile = {
    "name": NAME,
    "Stretches domain for horizontal vs vertical inputs": {"x": 1.0, "y": 1.0},
    "Stretches accel range for horizontal vs vertical inputs": {"x": 1.0, "y": 1.0},
    "Whole or horizontal accel parameters": accel("synchronous"),
    "Vertical accel parameters": accel("noaccel"),
    "Input speed calculation parameters": {
        "Whole/combined accel (set false for 'by component' mode)": True,   # no curl
        "lpNorm": 2.0,
        "Time in ms after which an input is weighted at half its original value.": 0.0,
        "Time in ms after which scale is weighted at half its original value.": 0.0,
        "Time in ms after which an output is weighted at half its original value.": 0.0,
    },
    "Output DPI": OUTPUT_DPI,
    "Y/X output DPI ratio (vertical sens multiplier)": 1.0,
    "L/R output DPI ratio (left sens multiplier)": 1.0,
    "U/D output DPI ratio (up sens multiplier)": 1.0,
    "Degrees of rotation": 0.0, "Degrees of angle snapping": 0.0, "Input Speed Cap": 0.0,
}

export = {
    "format": "RawAccelReimagined.Profile", "formatVersion": 1,
    "rawAccelVersion": "1.7.0", "exportedAtUtc": "2026-08-04T00:00:00.0000000Z",
    "profile": profile,
}

settings = {
    "### Accel modes ###": "classic | jump | natural | synchronous | power | lut | noaccel",
    "### Cap modes ###": "in_out | input | output",
    "version": "1.7.0",
    "defaultDeviceConfig": {
        "disable": False,
        "Use constant time interval based on polling rate": False,
        "DPI (normalizes input speed unit: counts/ms -> in/s)": 0,
        "Polling rate Hz (keep at 0 for automatic adjustment)": 0,
    },
    "profiles": [profile],
    "devices": [],
}

if __name__ == "__main__":
    with open(NAME + "-64pt.rawaccelprofile.json", "w") as f:
        json.dump(export, f, indent=2); f.write("\n")
    with open(NAME + "-64pt.settings.json", "w") as f:
        json.dump(settings, f, indent=2); f.write("\n")
    print(f"{NAME}: synchronous, whole mode, sensitivity (analytic)")
    print(f"  motivity {MOTIVITY:.4f}  gamma {GAMMA}  syncSpeed {SYNC_SPEED:.0f} c/ms "
          f"({SYNC_INS:.0f} in/s)  smooth {SMOOTH}  outputDPI {OUTPUT_DPI:.1f}")
    print("\n  in/s   effective multiplier")
    for ins in [2, 5, 8, 12, 15, 20, 25, 30, 40, 60, 100]:
        print(f"  {ins:>4}   {effective(DPI*ins/1000.0):.4f}")
