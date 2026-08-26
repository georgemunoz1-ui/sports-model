#!/usr/bin/env python3
"""
LEGACY generator — the original subtle gain-cap profile.

Authored for the previous 3200 DPI / 0.088 setup and NOT valid on the current
1600 DPI hardware (x-axis is counts/ms, so breakpoints land at double the
intended hand speed). Kept for history. Use generate_valorant_curve.py instead.

Target: 3200 DPI, 0.088 in-game sens (eDPI 281.6).
Produces a 64-point "Gain / Velocity" LUT that:
  - is exactly 1:1 (slope 1.000) below 48 counts/ms  (<= 15 in/s @3200dpi),
  - ramps slope 1.000 -> 1.100 over 48..96 counts/ms (15..30 in/s),
  - holds slope 1.100 (+10%) flat out to 640 counts/ms (200 in/s),
  - places knee nodes at EQUAL GAIN INCREMENTS for uniform sensitivity granularity.

The gain profile is taken from the reference CANONICAL curve (116 pts), embedded below,
so this script needs no external files. Run:  python3 generate_curve.py
"""
import json, bisect

# --- embedded reference CANONICAL curve: flat [in,out,in,out,...] in counts/ms ---
CANON = [
    0.0625, 0.0625, 24.0, 24.0, 48.0, 48.0, 50.049114, 50.049217,
    51.793839, 51.794956, 52.742622, 52.745205, 53.465435, 53.469803, 54.070999, 54.077419,
    54.602688, 54.611393, 55.082798, 55.094009, 55.524529, 55.538448, 55.936413, 55.953239,
    56.324341, 56.344257, 56.692566, 56.715748, 57.044273, 57.0709, 57.381924, 57.412167,
    57.707462, 57.741486, 58.022453, 58.060425, 58.328182, 58.370266, 58.625721, 58.672077,
    58.91597, 58.966759, 59.199692, 59.255077, 59.477554, 59.537689, 59.750126, 59.815174,
    60.017914, 60.088028, 60.281357, 60.356701, 60.540852, 60.621582, 60.796749, 60.883026,
    61.049366, 61.14135, 61.298988, 61.396835, 61.545876, 61.64975, 61.790264, 61.90033,
    62.032372, 62.148788, 62.2724, 62.395336, 62.510536, 62.64016, 62.746952, 62.883427,
    62.981808, 63.125301, 63.215256, 63.36594, 63.447433, 63.605488, 63.678482, 63.844078,
    63.908524, 64.081841, 64.13768, 64.318893, 64.366074, 64.555367, 64.593803, 64.791359,
    64.820984, 65.026993, 65.047714, 65.262367, 65.274101, 65.497589, 65.500229, 65.73275,
    65.726204, 65.967957, 65.95211, 66.2033, 66.17804, 66.438881, 66.404083, 66.674782,
    66.630333, 66.911102, 66.856873, 67.147934, 67.083794, 67.385368, 67.31118, 67.623497,
    67.539116, 67.862419, 67.767693, 68.102219, 67.997002, 68.342987, 68.227127, 68.584831,
    68.458168, 68.82785, 68.690216, 69.072128, 68.923355, 69.31778, 69.157692, 69.564903,
    69.393318, 69.813606, 69.630348, 70.064003, 69.868881, 70.316208, 70.109024, 70.570335,
    70.350899, 70.826508, 70.59462, 71.084862, 70.840302, 71.345528, 71.088089, 71.60865,
    71.338112, 71.874367, 71.590508, 72.142845, 71.845436, 72.414253, 72.103058, 72.688751,
    72.363533, 72.966537, 72.627052, 73.247803, 72.893799, 73.532768, 73.163986, 73.821648,
    73.437828, 74.114685, 73.715576, 74.412155, 73.997467, 74.714325, 74.283798, 75.021515,
    74.57486, 75.334045, 74.870979, 75.652283, 75.172531, 75.976624, 75.479897, 76.307503,
    75.793526, 76.645409, 76.113892, 76.990875, 76.441544, 77.344482, 76.777077, 77.706917,
    77.121178, 78.078911, 77.474602, 78.461311, 77.838242, 78.855095, 78.213089, 79.26136,
    78.600311, 79.681389, 79.001259, 80.116676, 79.417534, 80.568977, 79.851028, 81.04039,
    80.304031, 81.533432, 80.779358, 82.051201, 81.280495, 82.597549, 81.811874, 83.177345,
    82.379257, 83.796944, 82.990349, 84.464844, 83.655884, 85.192848, 84.391457, 85.998138,
    85.221283, 86.907379, 86.186523, 87.965881, 87.367668, 89.26223, 88.968109, 91.020248,
    92.069565, 94.430061, 96.0, 98.753342, 153.600006, 162.113342, 249.600006, 267.713348,
]

GX = [CANON[i]   for i in range(0, len(CANON), 2)]
GY = [CANON[i+1] for i in range(0, len(CANON), 2)]

ONSET, CAP_START, CAP_GAIN = 48.0, 96.0, 1.10
Y_AT_CAP = GY[GX.index(96.0)]
XMAX = 640.0                # safe tail: 200 in/s @3200dpi
N_POINTS = 64
NAME = "VAL-3200-088-64pt"

def gt(x):
    if x <= ONSET:     return x
    if x >= CAP_START: return Y_AT_CAP + CAP_GAIN * (x - CAP_START)
    i = bisect.bisect_right(GX, x) - 1; i = max(0, min(i, len(GX)-2))
    x0,x1,y0,y1 = GX[i],GX[i+1],GY[i],GY[i+1]
    return y0 + (y1-y0)*(x-x0)/(x1-x0)

# smooth monotone gain(x) from reference secant slopes (assigned to segment midpoints)
midx=[ONSET]; midg=[1.0]
for i in range(1,len(GX)):
    if GX[i] <= ONSET or GX[i-1] >= CAP_START: continue
    midx.append(0.5*(GX[i]+GX[i-1])); midg.append((GY[i]-GY[i-1])/(GX[i]-GX[i-1]))
midx.append(CAP_START); midg.append(CAP_GAIN)
for i in range(1,len(midg)):
    if midg[i] < midg[i-1]: midg[i]=midg[i-1]

def gain(x):
    if x<=ONSET: return 1.0
    if x>=CAP_START: return CAP_GAIN
    i=bisect.bisect_right(midx,x)-1; i=max(0,min(i,len(midx)-2))
    x0,x1,g0,g1=midx[i],midx[i+1],midg[i],midg[i+1]
    return g0+(g1-g0)*(x-x0)/(x1-x0)

def inv_gain(level):
    lo,hi=ONSET,CAP_START
    for _ in range(80):
        m=0.5*(lo+hi)
        if gain(m)<level: lo=m
        else: hi=m
    return 0.5*(lo+hi)

# base(3) + tail(2) + knee(M incl. cap) = N_POINTS  ->  M = N_POINTS-5
M = N_POINTS - 5
levels = [1.0 + (CAP_GAIN-1.0)*k/M for k in range(1, M+1)]
knee = [inv_gain(L) for L in levels]; knee[-1] = CAP_START
xs = sorted(set(round(x,6) for x in ([0.0625,24.0,ONSET] + knee + [249.6, XMAX])))

def final_y(x):
    if x<=ONSET: return x
    if x>=CAP_START: return Y_AT_CAP + CAP_GAIN*(x-CAP_START)
    return gt(x)

NX=[round(x,5) for x in xs]
NY=[round(final_y(x),5) for x in xs]
assert len(NX)<=64
h_data=[]
for x,y in zip(NX,NY): h_data += [x,y]

def accel(mode, data):
    return {
        "mode": mode, "Gain / Velocity": True, "inputOffset": 0.0, "outputOffset": 0.0,
        "acceleration": 0.005, "decayRate": 0.1, "gamma": 1.0, "motivity": 1.5,
        "exponentClassic": 2.0, "scale": 1.0, "exponentPower": 0.05, "limit": 1.5,
        "syncSpeed": 5.0, "smooth": 0.5, "Cap / Jump": {"x":15.0,"y":1.5},
        "Cap mode": "output", "data": data,
    }

profile = {
    "name": NAME,
    "Stretches domain for horizontal vs vertical inputs": {"x":1.0,"y":1.0},
    "Stretches accel range for horizontal vs vertical inputs": {"x":1.0,"y":1.0},
    "Whole or horizontal accel parameters": accel("lut", h_data),
    "Vertical accel parameters": accel("lut", [0.0625,0.0625,640.0,640.0]),
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
    with open(NAME + ".rawaccelprofile.json","w") as f:
        json.dump(export, f, indent=2); f.write("\n")
    with open(NAME + ".settings.json","w") as f:
        json.dump(settings, f, indent=2); f.write("\n")
    paste = "; ".join(f"{x:g},{y:g}" for x,y in zip(NX,NY))
    with open(NAME + ".paste.txt","w") as f:
        f.write(paste + "\n")
    print("wrote profile + settings + paste with", len(NX), "points")
    print(paste)
