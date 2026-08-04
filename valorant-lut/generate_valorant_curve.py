#!/usr/bin/env python3
"""
Generator for VAL-CURVE-3200-088-64pt — a continuous Valorant accel curve
for Raw Accel Reimagined (gain/velocity LUT, 64 points).

Target: 3200 DPI, 0.088 in-game sens (eDPI 281.6, ~39.4 cm/360).

Design (gain space — the LUT slope IS the felt per-count multiplier):
  - exactly 1.000x below 8 in/s (25.6 counts/ms): tracking, spray control,
    micro-adjust all stay pixel-identical to raw 3200/0.088
  - C2-smooth quintic ease (smootherstep) from 1.00x to 1.30x across
    8 -> 40 in/s: the curve is live through the whole flick range, with no
    kinks (gain derivative is zero at both ends)
  - flat 1.30x gain cap beyond 40 in/s, extended to 200 in/s

The velocity curve is the exact analytic integral of the gain function, so
the LUT's slope reproduces the intended gain precisely. Knee nodes are
placed at equal gain increments (uniform 0.005x/step resolution).
"""
import json

DPI = 3200.0
A_INS, B_INS, G = 8.0, 40.0, 1.30      # onset in/s, cap-speed in/s, max gain
A, B = DPI*A_INS/1000.0, DPI*B_INS/1000.0   # 25.6, 128.0 counts/ms
XMAX = 640.0                            # 200 in/s tail
N_POINTS = 64
NAME = "VAL-CURVE-3200-088-64pt"

def s(u):  return 6*u**5 - 15*u**4 + 10*u**3          # smootherstep (gain shape)
def S(u):  return u**6 - 3*u**5 + 2.5*u**4            # its integral, S(1)=0.5

def gain(x):
    if x <= A: return 1.0
    if x >= B: return G
    return 1.0 + (G-1.0)*s((x-A)/(B-A))

def y_of(x):
    if x <= A: return x
    if x >= B: return B + (G-1.0)*(B-A)*0.5 + G*(x-B)
    u = (x-A)/(B-A)
    return x + (G-1.0)*(B-A)*S(u)

def inv_gain(level):
    lo, hi = A, B
    for _ in range(80):
        m = 0.5*(lo+hi)
        if gain(m) < level: lo = m
        else: hi = m
    return 0.5*(lo+hi)

# nodes: base(2) + knee at equal gain steps(M incl. B) + tail(2) = 64
M = N_POINTS - 4
levels = [1.0 + (G-1.0)*k/M for k in range(1, M+1)]
knee = [inv_gain(L) for L in levels]
knee[-1] = B
xs = sorted(set(round(x, 6) for x in ([0.0625, A] + knee + [320.0, XMAX])))

NX = [round(x, 5) for x in xs]
NY = [round(y_of(x), 5) for x in xs]
assert len(NX) <= 64
h_data = []
for x, yv in zip(NX, NY): h_data += [x, yv]

def accel(mode, data):
    return {
        "mode": mode, "Gain / Velocity": True, "inputOffset": 0.0, "outputOffset": 0.0,
        "acceleration": 0.005, "decayRate": 0.1, "gamma": 1.0, "motivity": 1.5,
        "exponentClassic": 2.0, "scale": 1.0, "exponentPower": 0.05, "limit": 1.5,
        "syncSpeed": 5.0, "smooth": 0.5, "Cap / Jump": {"x": 15.0, "y": 1.5},
        "Cap mode": "output", "data": data,
    }

profile = {
    "name": NAME,
    "Stretches domain for horizontal vs vertical inputs": {"x": 1.0, "y": 1.0},
    "Stretches accel range for horizontal vs vertical inputs": {"x": 1.0, "y": 1.0},
    "Whole or horizontal accel parameters": accel("lut", h_data),
    "Vertical accel parameters": accel("lut", [0.0625, 0.0625, 640.0, 640.0]),
    "Input speed calculation parameters": {
        "Whole/combined accel (set false for 'by component' mode)": False,
        "lpNorm": 2.0,
        "Time in ms after which an input is weighted at half its original value.": 0.0,
        "Time in ms after which scale is weighted at half its original value.": 0.0,
        "Time in ms after which an output is weighted at half its original value.": 0.0,
    },
    "Output DPI": 1000.0,
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
    with open(NAME + ".rawaccelprofile.json", "w") as f:
        json.dump(export, f, indent=2); f.write("\n")
    with open(NAME + ".settings.json", "w") as f:
        json.dump(settings, f, indent=2); f.write("\n")
    paste = "; ".join(f"{x:g},{yv:g}" for x, yv in zip(NX, NY))
    with open(NAME + ".paste.txt", "w") as f:
        f.write(paste + "\n")
    print("wrote profile + settings + paste with", len(NX), "points")
