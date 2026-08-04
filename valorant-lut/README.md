# Valorant LUTs — 3200 DPI · 0.088 sens (Raw Accel Reimagined)

Valorant-tuned mouse-acceleration LUTs for **[Raw Accel Reimagined](https://github.com/diskcell/Raw-Accel-Reimagined)**,
built for **3200 DPI** with **0.088** in-game sensitivity (**eDPI 281.6** ≈ **46.4 cm/360** at
Valorant's 0.07 yaw; a raw 180° is ≈ 23.2 cm).

Four profiles:

- **`VAL-SCURVE-3200-088-64pt`** — whaamkabaam-style S-curve: slow movements run *below* baseline
  (gain 0.85× for extra micro precision), crosses baseline at ~8 in/s, rises to 1.30× for flicks.
  "Low and high sens at the same time." Whole mode (both axes).
- **`VAL-CURVE-3200-088-64pt`** — punchy boost-only curve: raw below 8 in/s, gain 1.00× → 1.30×
  across 8–40 in/s. The assist lands in the realistic flick range (20–50 in/s). Vertical stays raw.
- **`VAL-MILD-3200-088-64pt`** — conservative: raw below 12 in/s, gain 1.00× → 1.20× across
  12–90 in/s. Near-raw at ordinary flick speeds; assist arrives mostly at very fast swipes. Vertical raw.
- **`VAL-3200-088-64pt`** — the earlier subtle gain-cap profile (raw <15 in/s, +10% cap by 30 in/s),
  rebuilt from the `CANONICAL` reference.

> Independent community project. Not affiliated with Riot Games or the official Raw Accel team.

## Files

| File | Use |
|------|-----|
| `VAL-SCURVE-3200-088-64pt.rawaccelprofile.json` | **Import Profile** — whaamkabaam-style S-curve |
| `VAL-CURVE-3200-088-64pt.rawaccelprofile.json` | **Import Profile** — punchy boost-only curve |
| `VAL-MILD-3200-088-64pt.rawaccelprofile.json` | **Import Profile** — conservative boost-only curve |
| `VAL-*.settings.json` | Import Settings variants of each |
| `VAL-*.paste.txt` | Free Curve Editor paste strings |
| `curves-overlay.svg` | Gain chart — all four profiles overlaid |
| `generate_scurve.py` | Self-contained generator for the S-curve |
| `generate_valorant_curve.py` | Self-contained generator for the boost-only curves |
| `VAL-3200-088-64pt.rawaccelprofile.json` | **Import Profile** — subtle gain-cap profile |
| `VAL-3200-088-64pt.settings.json` | Import Settings variant of the same |
| `VAL-3200-088-64pt.paste.txt` | Free Curve Editor paste string |
| `VAL-3200-088-64pt.curve.svg` | Chart for the subtle profile |
| `generate_curve.py` | Self-contained generator for the subtle profile |

## The S-curve (`VAL-SCURVE`) — whaamkabaam-style

The other profiles only ever *add* sensitivity. The S-curve implements the "low and high sens at the
same time" philosophy: slow movements run **below** your baseline for extra micro precision, and fast
movements rise above it. Gain is a log-space smootherstep (the same family as Raw Accel's
synchronous/motivity mode):

- **≤2 in/s:** gain 0.85× — micro-adjust/tracking at effective eDPI **239** (more room for precision)
- **2–50 in/s:** smooth S rising through **1.00× at ~8 in/s** (your baseline feel sits at normal aim speed)
- **≥50 in/s:** gain 1.30× — flick assist comparable to VAL-CURVE

| Hand speed | Gain | Sens (ratio) | Effective eDPI |
|-----------:|-----:|-------------:|---------------:|
|   3 in/s | 0.85× | 0.85× | 240 |
|   8 in/s | 1.00× | 0.89× | 252 |
|  12 in/s | 1.10× | 0.95× | 266 |
|  20 in/s | 1.22× | 1.03× | 292 |
|  30 in/s | 1.28× | 1.11× | 313 |
|  50 in/s | 1.30× | 1.18× | 334 |
|  80 in/s | 1.30× | 1.23× | 346 |

Two things change vs the boost-only curves, both deliberate:

1. **Whole mode** (accel applies to both axes uniformly). With a sub-1.0 slow region, keeping vertical
   raw would make slow diagonals skew ~15% — unacceptable. Consequence: vertical micro (headshot-line
   settling, recoil pulls) also runs at 0.85×, i.e. slightly slower and more precise, but different
   from your raw muscle memory. This is how S-curves are normally shipped.
2. **Slow aim is not raw anymore.** That's the trade: more precision headroom up close in exchange for
   re-learning the slow-speed feel. Expect a few sessions of adaptation — the payoff is the "both
   sensitivities at once" effect.

Tuning knobs at the top of `generate_scurve.py`: `G_LO` (floor), `G_HI` (cap), and the speed window.
If 0.85 feels too slow on sprays, try `G_LO = 0.90`.

## The boost-only curves (`VAL-CURVE` and `VAL-MILD`)

Both use the same construction: exactly **1.000×** gain below the onset, a quintic smootherstep ease up
to the max gain at the cap speed, flat beyond. The velocity LUT is the exact analytic integral of the
gain function, sampled at equal gain increments, so the LUT slope reproduces the intended gain precisely.
Note the gain cap is a *slope* cap: actual sensitivity (output/input ratio) keeps rising after the cap
speed and approaches the cap value only asymptotically at extreme speeds.

Side-by-side (gain / actual-sensitivity ratio):

| Hand speed | VAL-CURVE gain | VAL-CURVE sens | VAL-MILD gain | VAL-MILD sens |
|-----------:|---------------:|---------------:|--------------:|--------------:|
|  ≤8 in/s  | 1.000× | 1.000× | 1.000× | 1.000× |
|  15 in/s  | 1.022× | 1.003× | 1.000× | 1.000× |
|  20 in/s  | 1.083× | 1.014× | 1.002× | 1.000× |
|  30 in/s  | 1.246× | 1.065× | 1.017× | 1.003× |
|  40 in/s  | 1.300× | 1.120× | 1.050× | 1.010× |
|  50 in/s  | 1.300× | 1.156× | 1.095× | 1.022× |
|  60 in/s  | 1.300× | 1.180× | 1.142× | 1.039× |
|  80 in/s  | 1.300× | 1.210× | 1.197× | 1.073× |
| 100 in/s  | 1.300× | 1.228× | 1.200× | 1.098× |
| 200 in/s  | 1.300× | 1.264× | 1.200× | 1.149× |

Both keep everything below their onset pixel-identical to raw 3200/0.088, and vertical stays raw 1:1
(by-component mode) so the headshot line and recoil pulls are untouched. The difference is *where the
help lands*: VAL-CURVE assists ordinary fast flicks (20–50 in/s), while VAL-MILD is nearly inert there
and only meaningfully assists very fast swipes (60+ in/s).

On 180s: a raw 180° needs ≈23.2 cm of pad. The multiplier varies during a swipe (it depends on the whole
speed trajectory), but as a constant-speed approximation at 50 in/s, VAL-CURVE brings it to ≈20 cm and
VAL-MILD to ≈22.7 cm.

**Which to pick:** start with **VAL-CURVE** if you wanted acceleration you can actually feel during
normal flicking (that was the complaint with the flat profile); start with **VAL-MILD** if you want your
established flick memory essentially untouched and only long swipes shortened. They bracket the space —
after a session with each, the right cap/onset for you is usually obvious, and the generator makes any
in-between (`PROFILES` list at the top of `generate_valorant_curve.py`).

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
