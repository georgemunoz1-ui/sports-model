# Valorant LUTs — 3200 DPI · 0.088 sens (Raw Accel Reimagined)

Valorant-tuned mouse-acceleration LUTs for **[Raw Accel Reimagined](https://github.com/diskcell/Raw-Accel-Reimagined)**,
built for **3200 DPI** with **0.088** in-game sensitivity (**eDPI 281.6**, ≈ 39 cm/360).

Two profiles:

- **`VAL-CURVE-3200-088-64pt`** (recommended) — a continuous curve: raw below 8 in/s, C2-smooth gain
  rise 1.00× → 1.30× across the whole flick range (8–40 in/s), capped at +30%.
- **`VAL-3200-088-64pt`** — the earlier subtle gain-cap profile (raw <15 in/s, +10% cap by 30 in/s),
  rebuilt from the `CANONICAL` reference.

> Independent community project. Not affiliated with Riot Games or the official Raw Accel team.

## Files

| File | Use |
|------|-----|
| `VAL-CURVE-3200-088-64pt.rawaccelprofile.json` | **Import Profile** — the continuous curve (recommended) |
| `VAL-CURVE-3200-088-64pt.settings.json` | Import Settings variant of the same |
| `VAL-CURVE-3200-088-64pt.paste.txt` | Free Curve Editor paste string |
| `VAL-CURVE-3200-088-64pt.curve.svg` | Gain chart (new curve vs old, overlaid) |
| `generate_valorant_curve.py` | Self-contained generator for the continuous curve |
| `VAL-3200-088-64pt.rawaccelprofile.json` | **Import Profile** — subtle gain-cap profile |
| `VAL-3200-088-64pt.settings.json` | Import Settings variant of the same |
| `VAL-3200-088-64pt.paste.txt` | Free Curve Editor paste string |
| `VAL-3200-088-64pt.curve.svg` | Chart for the subtle profile |
| `generate_curve.py` | Self-contained generator for the subtle profile |

## The continuous curve (`VAL-CURVE`)

Gain shape: exactly **1.000×** below **8 in/s** (25.6 counts/ms), then a quintic smootherstep ease to
**1.300×** at **40 in/s** (128 counts/ms), flat beyond. The velocity LUT is the exact analytic integral
of that gain function, sampled at equal gain increments (uniform 0.005×/step), so the curve is live and
smooth through the entire realistic flick range — no dead plateau in the middle of your aim speeds.

| Hand speed | Gain (slope) | Sens (ratio) | Effective eDPI |
|-----------:|-------------:|-------------:|---------------:|
|  ≤8 in/s | 1.000× | 1.000× | 281.6 |
|  15 in/s | 1.022× | 1.003× | 282 |
|  20 in/s | 1.082× | 1.014× | 286 |
|  25 in/s | 1.168× | 1.036× | 292 |
|  30 in/s | 1.248× | 1.065× | 300 |
|  40 in/s | 1.300× | 1.120× | 315 |
|  50 in/s | 1.300× | 1.156× | 326 |
|  80 in/s | 1.300× | 1.210× | 341 |

What that means in play: crosshair placement, tracking, spray control and micro-flicks (all ≤8 in/s)
are pixel-identical to raw 3200/0.088. Mid-speed flicks get progressively more help, and a fast 180°
swipe needs ~**17 cm** of pad instead of 19.7 cm. Vertical stays raw 1:1 (by-component mode), so the
headshot line and recoil pulls are untouched.

## How to load it

1. In Raw Accel Reimagined, use **Import Profile** and pick `VAL-CURVE-3200-088-64pt.rawaccelprofile.json`
   (or the subtle `VAL-3200-088-64pt` variant; **Import Settings** works with the `.settings.json` files).
2. Make sure your **mouse DPI is 3200** and Valorant in-game sens is **0.088** — the curve is scaled to that DPI.
3. **Leave device "DPI (normalizes input speed)" at 0 / disabled** (Advanced → device config). If you enter
   3200 there, Raw Accel rescales input to 1000-DPI equivalents and the accel onset moves from 15 in/s to
   ~48 in/s — the curve would barely ever activate. Chart-display DPI is cosmetic and safe either way.
4. Keep Sens Multiplier 1.00, rotation/angle snapping 0, smoothing 0.
5. Press **Save & Apply**.

Alternatively, open the **Free Curve Editor (LUT)**, select all points, and paste the contents of
`VAL-3200-088-64pt.paste.txt` (v1.8.4+ supports precise `x,y;x,y` pasting), then **Save & Apply**.

## The subtle profile (`VAL-3200-088-64pt`)

The LUT runs in **Gain / Velocity** mode, so it is a velocity curve. Raw Accel distinguishes two things:

- **Gain** = the *slope* of the curve — the per-count multiplier applied to additional movement at that speed.
- **Sensitivity** = the *ratio* output/input — the average multiplier over the whole motion, which lags
  behind the gain because the slow start of a flick was still 1:1.

This is a **gain-cap** curve: gain reaches +10% at 30 in/s, while actual sensitivity climbs gradually and
only approaches 1.10× at extreme speeds. That lag is intentional — it keeps flick distances predictable.
Input speed is in **counts/ms**.

| Zone | Input speed | Hand speed @3200 DPI | Gain (slope) |
|------|-------------|----------------------|--------------|
| **Raw / precise** | 0 – 48 counts/ms | 0 – 15 in/s | **exactly 1.000×** (untouched) |
| **Ramp** | 48 – 96 counts/ms | 15 – 30 in/s | smoothly 1.000× → 1.100× |
| **Cap** | ≥ 96 counts/ms | ≥ 30 in/s | flat **1.100×** (+10%) |

Gain vs actual sensitivity at typical hand speeds (3200 DPI):

```
 hand speed   gain (slope)   sensitivity (ratio)
   15 in/s      1.000x           1.000x
   20 in/s      1.035x           1.003x
   25 in/s      1.089x           1.015x
   30 in/s      1.100x           1.029x
   50 in/s      1.100x           1.057x
  100 in/s      1.100x           1.079x
```

Slow tracking and micro-adjustments (≤15 in/s) stay **perfectly 1:1**, so your base 3200/0.088 aim
(eDPI 281.6) is unchanged and muscle memory is preserved. A fast flick ends at only ~+3% total sensitivity,
with the extra help ramping in progressively during genuinely fast swipes.

## Design notes / improvements over the reference

- **64 points, uniform granularity.** Rebuilt from your 116-point `CANONICAL` curve. Instead of subsampling,
  the knee nodes are placed at **equal gain increments**, giving very uniform ~0.0017×/step gain resolution
  (max step 0.00198×) within the 64-point budget. Max deviation from your original
  curve: **0.0015 counts/ms** (imperceptible).
- **Exact base and cap.** Slope is forced to *exactly* 1.000 below 48 counts/ms and *exactly* 1.100 above
  96 counts/ms — no drift, no dips; slope is monotonically non-decreasing throughout.
- **Safe tail.** Extended to 640 counts/ms (200 in/s), far beyond any real flick, so behavior is well-defined
  even on the fastest snaps.
- **By-component (unchanged from your setup).** `Whole/combined = false`: the accel curve applies to
  **horizontal** movement while **vertical stays 1:1 raw** — horizontal flick assist, raw vertical for
  recoil control and the headshot line.

### Variants (easy to make on request)
- **Tighter** (later onset ~60 counts/ms, +8% cap) — matches your `tight` reference.
- **Whole/combined** magnitude-based accel (uniform on diagonals, no directional skew).
- **Raw** (no acceleration) — your `RAW` reference.

## Rebuild

The curve is generated deterministically by the self-contained `generate_curve.py` (embeds the reference
gain profile — no external files needed):

```
python3 generate_curve.py     # rewrites the .rawaccelprofile.json, .settings.json and .paste.txt
```

Parameters: onset 48 counts/ms, cap 96 counts/ms, max gain 1.10, 64 points, equal-gain node spacing.

### Notes on the engine
LUT runs in gain/velocity space: the points are an output-velocity curve, and the effective sensitivity
is its **slope** (Raw Accel's official guide calls them "velocity points"). That's why the base region uses
`y = x` (slope 1.000 → no accel) rather than a flat ratio. Input speed is **counts/ms**, which scales with
mouse DPI — so this curve is specific to **3200 DPI**. If you change DPI, the onset/cap hand-speeds shift and
the curve should be rescaled.
