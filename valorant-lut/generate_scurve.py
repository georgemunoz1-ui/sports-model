#!/usr/bin/env python3
"""
Generator for VAL-SCURVE-3200-088-64pt — a whaamkabaam-style S-curve for
Raw Accel Reimagined (gain/velocity LUT, 64 points).

Target: 3200 DPI, 0.088 in-game sens (eDPI 281.6, ~46.4 cm/360 at 0.07 yaw).

Philosophy ("low and high sens at the same time"): slow movements run BELOW
baseline for extra micro precision, the curve crosses baseline at normal
aim speed, fast movements rise above it for flicks.

Gain shape (log-space smootherstep, matching how motivity/synchronous-style
S-curves are constructed — symmetric on a log speed axis):
  gain = 0.85            below 2 in/s   (micro: effective eDPI ~239)
  gain = 0.85 -> 1.30    across 2-50 in/s, crossing 1.00 at ~8 in/s
  gain = 1.30            above 50 in/s  (flicks), out to 200 in/s

Applied in WHOLE mode (both axes uniformly): with a sub-1.0 slow region,
by-component vertical-raw would skew slow diagonals by up to 15%.

The velocity LUT is the numeric integral of the gain function (Simpson,
sub-1e-6 accuracy), so the LUT slope reproduces the intended gain. Knee
nodes sit at equal gain increments (uniform 0.0075x/step resolution).
"""
import json, math

N_POINTS = 64
TAIL_INS = 200.0

# (name, gain floor, gain cap, floor-end in/s, cap-start in/s, dpi)
PROFILES = [
    # V1: original — floor 0.85, cap 1.30 at 50 in/s
    ("VAL-SCURVE-3200-088-64pt", 0.85, 1.30, 2.0, 50.0, 3200.0),
    # V2: tighter hold + faster flicks — floor 0.80, cap 1.40 by 40 in/s
    ("VAL-SCURVE-V2-3200-088-64pt", 0.80, 1.40, 2.0, 40.0, 3200.0),
    # V2 design regenerated for the 1600 DPI hardware. This is the control that
    # isolates the DPI variable: identical philosophy to V2, correct breakpoints.
    ("VAL-SCURVE-V2-1600-015-64pt", 0.80, 1.40, 2.0, 40.0, 1600.0),
    ("VAL-SCURVE-V2-800-030-64pt", 0.80, 1.40, 2.0, 40.0, 800.0),
]

def s(u): return 6*u**5 - 15*u**4 + 10*u**3

def build_lut(G_LO, G_HI, vlo_ins, vhi_ins, DPI=3200.0):
    XMAX = DPI*TAIL_INS/1000.0
    V_LO, V_HI = DPI*vlo_ins/1000.0, DPI*vhi_ins/1000.0
    lnlo, lnhi = math.log(V_LO), math.log(V_HI)
    lgl, lgh = math.log(G_LO), math.log(G_HI)
    def gain(x):
        if x <= V_LO: return G_LO
        if x >= V_HI: return G_HI
        u = (math.log(x) - lnlo) / (lnhi - lnlo)
        return math.exp(lgl + (lgh - lgl)*s(u))
    def inv_gain(level):
        lo, hi = V_LO, V_HI
        for _ in range(80):
            m = 0.5*(lo+hi)
            if gain(m) < level: lo = m
            else: hi = m
        return 0.5*(lo+hi)
    def simpson(a, b, n=400):
        if b <= a: return 0.0
        n += n % 2
        h = (b-a)/n
        acc = gain(a) + gain(b)
        for i in range(1, n):
            acc += gain(a+i*h) * (4 if i % 2 else 2)
        return acc*h/3.0
    # nodes: base(2) + knee at equal gain steps(M incl. V_HI) + tail(2) = 64
    M = N_POINTS - 4
    levels = [G_LO + (G_HI-G_LO)*k/M for k in range(1, M+1)]
    knee = [inv_gain(L) for L in levels]
    knee[-1] = V_HI
    tail = [0.5*(V_HI+XMAX), XMAX]
    xs = sorted(set(round(x, 6) for x in ([0.0625, V_LO] + knee + tail)))
    NX, NY = [], []
    acc = None
    for x in xs:
        if x <= V_LO:
            y = G_LO * x
        elif x >= V_HI:
            if acc is None:
                acc = G_LO*V_LO + simpson(V_LO, V_HI, 4000)
            y = acc + G_HI*(x - V_HI)
        else:
            y = G_LO*V_LO + simpson(V_LO, x, 2000)
        NX.append(round(x, 5)); NY.append(round(y, 5))
    assert len(NX) <= 64
    h_data = []
    for x, yv in zip(NX, NY): h_data += [x, yv]
    return NX, NY, h_data, inv_gain, XMAX

def accel(mode, data):
    return {
        "mode": mode, "Gain / Velocity": True, "inputOffset": 0.0, "outputOffset": 0.0,
        "acceleration": 0.005, "decayRate": 0.1, "gamma": 1.0, "motivity": 1.5,
        "exponentClassic": 2.0, "scale": 1.0, "exponentPower": 0.05, "limit": 1.5,
        "syncSpeed": 5.0, "smooth": 0.5, "Cap / Jump": {"x": 15.0, "y": 1.5},
        "Cap mode": "output", "data": data,
    }

def make_profile(name, h_data):
    return {
    "name": name,
    "Stretches domain for horizontal vs vertical inputs": {"x": 1.0, "y": 1.0},
    "Stretches accel range for horizontal vs vertical inputs": {"x": 1.0, "y": 1.0},
    "Whole or horizontal accel parameters": accel("lut", h_data),
    "Vertical accel parameters": accel("noaccel", []),
    "Input speed calculation parameters": {
        "Whole/combined accel (set false for 'by component' mode)": True,
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

def make_export(profile):
    return {
    "format": "RawAccelReimagined.Profile", "formatVersion": 1,
    "rawAccelVersion": "1.7.0", "exportedAtUtc": "2026-08-04T00:00:00.0000000Z",
    "profile": profile,
}

def make_settings(profile):
    return {
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
    for name, g_lo, g_hi, vlo, vhi, dpi in PROFILES:
        NX, NY, h_data, inv_gain, _x = build_lut(g_lo, g_hi, vlo, vhi, dpi)
        profile = make_profile(name, h_data)
        with open(name + ".rawaccelprofile.json", "w") as f:
            json.dump(make_export(profile), f, indent=2); f.write("\n")
        with open(name + ".settings.json", "w") as f:
            json.dump(make_settings(profile), f, indent=2); f.write("\n")
        paste = "; ".join(f"{x:g},{yv:g}" for x, yv in zip(NX, NY))
        with open(name + ".paste.txt", "w") as f:
            f.write(paste + "\n")
        cross = inv_gain(1.0)
        print(f"{name}: {len(NX)} pts, floor {g_lo} cap {g_hi}, "
              f"baseline crossing {cross*1000/dpi:.1f} in/s @{dpi:.0f}dpi")
