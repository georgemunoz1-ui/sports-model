# Valorant acceleration curves — base Raw Accel

Mouse-acceleration curves for **[Raw Accel](https://github.com/RawAccelOfficial/rawaccel)** (the
original, not Reimagined), tuned for Valorant.

> ## Current setup
> **1600 DPI · in-game sens 0.15 · 8000 Hz · base Raw Accel**
> eDPI **240** ≈ **54.4 cm/360** at Valorant's 0.07 yaw (a raw 180° ≈ 27.2 cm).
>
> **Active curve: `VAL-LOWGRAD-1600-015-WHOLE-257pt`**

## How to load a curve

You are on **base Raw Accel**, which means two things:

1. **`.rawaccelprofile.json` files do not work for you.** Those are Raw Accel *Reimagined's* export
   format. They are kept here for reference only.
2. **Use `.settings.json` or `.paste.txt`:**
   - `.settings.json` — drop into the Raw Accel folder as `settings.json`, refresh, **Apply**. Sets
     the curve *and* every supporting field (whole mode, gain switch, Lp norm) in one step.
   - `.paste.txt` — paste the `x,y;x,y` string into the LUT text box. Sets **only** the curve; you
     must set the mode switches yourself.

Supporting settings for any curve here:

| Setting | Value |
|---|---|
| Apply as | **Velocity** (gain switch on) |
| Whole / By Component | **Whole** |
| Sens Multiplier | 1.00 |
| Lp Norm | 2 |
| Rotation / angle snapping | 0 |
| Device DPI normalization | **0** |
| Device polling-rate override | **0** |
| In-game sens | 0.15 |

### Point budget

Base Raw Accel's real limit is **`LUT_POINTS_CAPACITY = 257`** (validator: *"too many data points
(max=257)"*). The "64 editable points" figure comes from Raw Accel Reimagined's editor UI and does
not apply here. Curves ending in `-64pt` were built under that mistaken constraint; the `-257pt`
builds are the same designs at full resolution.

## The active curve: `VAL-LOWGRAD`

Gain is exactly **1.000× below 12 in/s**, then a C2-smooth quintic ease to a **1.15 cap at 40 in/s**,
flat beyond out to 200 in/s.

| Hand speed | Gain (slope) | Sensitivity (ratio) |
|---:|---:|---:|
| ≤12 in/s | 1.0000 | 1.0000 |
| 15 | 1.0015 | 1.0001 |
| 20 | 1.0216 | 1.0024 |
| 25 | 1.0650 | 1.0103 |
| 30 | 1.1130 | 1.0235 |
| 40 | 1.1500 | 1.0525 |
| 100 | 1.1500 | 1.1110 |
| 200 | 1.1500 | 1.1305 |

The two columns differ because the LUT runs in gain/velocity mode: the driver applies `y(s)/s` (the
ratio) as the per-packet multiplier, while the LUT *slope* is the marginal gain. Sensitivity therefore
lags the gain and only approaches 1.15 asymptotically.

**Design intent.** Zero gain gradient through the entire micro-aim and deceleration band, so nothing —
hand-speed variation, velocity-estimation noise, 8 kHz packet quantization — can modulate sensitivity
while you are placing a shot. No sub-1.0 region, so slow aim is genuinely raw and muscle memory has a
fixed anchor.

**Quality at 257 points:** gain monotonic non-decreasing, range exactly [1.0000, 1.1500], max gain
step at a node **0.000888**, max deviation from the analytic curve **0.000245 counts/ms**.

## Whole vs By Component

Raw Accel's guide states that By Component with different x and y curves produces a vector field
*with curl* — a straight diagonal hand movement yields a curved cursor path — and that "it is
precisely the restrictions imposed by Whole (no curl) that make it smoother."

Measured skew for **this** curve (45° diagonal, by-component):

| Diagonal speed | Skew from 45° |
|---:|---:|
| ≤20 in/s | 0.00° |
| 30 in/s | 0.11° |
| 40 in/s | 0.53° |
| 80 in/s | 2.23° |

**This is small.** An earlier version of this document said "a few degrees at the cap" — that was
wrong; it applied the gain figure to a full-speed axis instead of the ratio to each component's
`v/√2` share. Curl is real here but under half a degree at any realistic flick speed.

Whole is still the right choice, because its usual cost does not apply: the curve is flat 1.000 below
12 in/s, so spray control, recoil pulls and headshot-line settles are already raw in whole mode. You
gain directional consistency and give up nothing.

## Files

| Pattern | What it is |
|---|---|
| `VAL-LOWGRAD-1600-015-WHOLE-257pt.*` | **Active.** Whole mode, full resolution |
| `VAL-LOWGRAD-1600-015-257pt.*` | Same curve, By Component — the A/B control |
| `VAL-LOWGRAD-1600-015-*-64pt.*` | Same design, reduced-resolution (superseded) |
| `VAL-LOWGRAD-800-030-*`, `VAL-LOWGRAD-400-060-*` | Same design rescaled for other DPI |
| `VAL-SCURVE-V2-1600-015-64pt.*` | S-curve control (0.80 floor, 1.40 cap) — see below |
| `VAL-SYNC-1600-015-64pt.*` | Native synchronous, no LUT — see below |
| `*-3200-088-*` | **Legacy.** Authored for the previous 3200 DPI / 0.088 setup |
| `generate_*.py` | Self-contained generators; edit `PROFILES` and re-run |

### DPI is baked into the x-axis

Breakpoints are counts/ms, so a curve authored for one DPI is wrong at another. Matched builds exist
for 400 / 800 / 1600 DPI, each holding eDPI 240:

| DPI | In-game sens | Curve file |
|---:|---:|---|
| 400 | 0.60 | `VAL-LOWGRAD-400-060-64pt` |
| 800 | 0.30 | `VAL-LOWGRAD-800-030-64pt` |
| **1600** | **0.15** | **`VAL-LOWGRAD-1600-015-WHOLE-257pt`** |

Never load a curve whose DPI does not match the mouse. Doing so is what caused the drift documented
below, and it is indistinguishable from a "bad" curve by feel.

## History: the drift, and what caused it

Drift during micro-corrections was reported after switching **3200 → 1600 DPI** while still running
`VAL-SCURVE-V2`, which was authored for 3200. Halving DPI doubles the hand speed every breakpoint
maps to: the sub-1.0 floor stretched from ≤2 to ≤4 in/s and the baseline crossing moved from 7.6 to
**15.2 in/s**, so all crosshair placement, tracking and micro-correction ran **below 1.0× gain**.

| Hand speed | Intended @3200 | Actual @1600 |
|---:|---:|---:|
| 8 in/s | 1.015 | **0.835** |
| 12 in/s | 1.165 | **0.925** |
| 15 in/s | 1.255 | **0.995** |

Combined with the sens change (281.6 → 240 eDPI), effective sensitivity at 10 in/s fell **23%**.

**Note on the response:** the fix changed two variables at once — it corrected the DPI *and* replaced
the S-curve philosophy with the low-gradient shape. `VAL-SCURVE-V2-1600-015-64pt` is the control that
isolates them: the original S-curve design with correct 1600 DPI breakpoints. Run it only if LOWGRAD
proves too flat, and in whole mode (its sub-1.0 floor makes by-component skew much larger).

## Valorant's forced Raw Input Buffer does not affect any of this

Riot removed the toggle in **patch 11.06 (2025-09-16)** and forces it on. It selects how the *game*
reads already-delivered input (`GetRawInputBuffer()` batching vs per-message `WM_INPUT`) — a
CPU-overhead optimization, not an input-path change.

Raw Accel runs far upstream: `rawaccel.sys` is a KMDF upper filter on the mouse class stack that hooks
`IOCTL_INTERNAL_MOUSE_CONNECT`, substitutes its own `ClassService` callback, and mutates `LastX`/`LastY`
**in place** before forwarding to mouclass. The source comment is explicit — *"Called when there are
mouse packets to report to the RIT."* win32k's Raw Input Thread and every downstream read path see only
post-acceleration deltas. The driver contains zero references to `WM_INPUT`, `GetRawInputData`, or
`GetRawInputBuffer`.

The math closes it too: acceleration is per-packet upstream, so the game receives `Σ f(dᵢ)`. Batched
vs per-message reads are re-partitions of the same sum, and Valorant's `0.15` is a linear scalar that
commutes with summation.

## Device settings: leave them at defaults

Tested by simulation against the real LUT; the shipped defaults win:

| Field | Value | Why |
|---|---|---|
| `DPI (normalizes input speed)` | **0** | Non-zero rescales input by `1000/DPI`. The x-axis is raw counts/ms locked to the mouse DPI — setting this breaks the curve. |
| `Polling rate Hz` | **0** | Setting 8000 raises the Δt floor to 0.125 ms, and that clamp is **one-sided**: it lifts short intervals (under-reading speed) while leaving long ones alone. Net systematic undershoot. |
| `Use constant time interval` | **false** | Exact only if polls never merge or drop; at a 5% merged-poll rate it degrades to +1.0–1.7% error. |
| Smoothing half-lives | **0** | Baseline jitter error is ~0.01–0.05% of stroke displacement. A 2 ms half-life moves error away from zero; 8 ms causes ~−1.3% flick undershoot from speed-estimate lag. |

### Why 8 kHz makes the flat floor more valuable, not less

At 1600 DPI with 0.125 ms packets you get ~0.2 counts per packet at 1 in/s, so the driver's speed
estimate carries up to ±250% error at low speed. All of that lands in the flat 1.000× region where it
cannot move the multiplier:

| Hand speed | Speed-estimate error | Resulting gain error |
|---:|---:|---:|
| 1 in/s | ±250% | **0.00%** |
| 5 in/s | ±50% | **0.00%** |
| 12 in/s | ±21% | 0.06% |
| 25 in/s | ±10% | 2.35% (worst case) |

## Alternative approaches on file

- **`VAL-SYNC-1600-015`** — native `synchronous` mode, no LUT. Analytic (continuous gain, no staircase)
  where a LUT is piecewise linear. Parameters: motivity 1.0724, gamma 0.12, syncSpeed 40 counts/ms,
  smooth 0.5, **Apply as Sensitivity**, Sens Multiplier 1.0724 (lifts the log-symmetric span off its
  sub-1.0 floor to give exactly 1.000 → 1.150). Caveat: its *gain* is non-monotonic — it peaks at
  1.2147 around 31 in/s then decays back to 1.15, because specifying the multiplier means
  `gain = mult + v·mult′`. Note synchronous in *gain* mode builds an internal LUT; sensitivity mode is
  the only fully analytic path.
- **`VAL-SCURVE-V2-1600-015`** — the drift-era S-curve at correct DPI. Control experiment, not an upgrade.

## Rebuild

```
python3 generate_valorant_curve.py    # LOWGRAD family, all DPI, 64 and 257 point
python3 generate_scurve.py            # S-curve family
python3 generate_synchronous.py       # native synchronous parameters
python3 generate_curve.py             # legacy 3200 DPI subtle profile
```

Each is self-contained. Edit the `PROFILES` list at the top and re-run.
