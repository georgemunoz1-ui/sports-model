# Improvement Roadmap — Taquitos #TACO

Silver 3 → Gold 3+ · drafted Aug 8, 2026 · built from measured V26:A4 data.

**The finding under every number:** aim now outruns rank (HS% top 28%); deaths and queue
habits hold the rating down (K/D bottom 26%, KAST bottom 32%). Gear is solved and frozen.

**Baseline (Aug 8):** comp 0.90 K/D · 24.9% HS · 69% KAST · ACS 214 · DDΔ +1/rd.
Swiftplay same act: 1.05 K/D · DDΔ +17/rd · ACS 239 — the comp-translation gap is the project.
Hours are inverted for climbing: 68h swift vs 21h comp.
Gear (current): **1600 DPI · 0.15 · 8000 Hz · base Raw Accel**, curve
`VAL-LOWGRAD-1600-015-WHOLE-257pt` (gain 1.000× below 12 in/s, 1.15 cap by 40 in/s, whole mode)
· Wooting RT 0.15mm. The earlier `VAL-SCURVE-V2` was authored for 3200 DPI; running it after the DPI
switch put all aim speeds below 1.0× gain and caused the reported drift. Escalation trigger 3 fired
and the curve was regenerated.

The 75% WR / 1.31 K/D / 49% HS run was recorded on the **previous 3200 DPI setup** and does not
describe current form. No games have been logged on the 1600 DPI hardware yet — that is the open
item, not the curve.

## Phase 0 — Freeze (this week)
- No settings changes for 30 comp games. Curve, DPI, sens, crosshair: all frozen.
- One Wooting fix first, then frozen too: W/S actuation 0.20 → 0.8–1.0 mm; crouch → 0.5 mm.
- Save the profile to the keyboard hardware.

## Phase 1 — Restructure the queue (weeks 1–2)
- Session template: 10 min DM warmup → 2–3 Swiftplay → 3–5 comp. Comp while fresh.
- Agent lock: Clove primary; Fade / KAY/O / Sova pool. **Iso benched** (32% WR / 84 games).
  Raze only in premades.
- Maps: queue toward Lotus + Fracture; avoid Bind. Ascent neutral.
- Targets: 15+ comp games · KAST ≥ 71% · deaths ≤ kills.

## Phase 2 — Kill the death leak (weeks 3–4)
- The habit: before every peek, know your trade. No trade available → hold.
- Carry discipline: when hot, discipline goes *up*. No repeat angles, no third re-peek
  (the Summit lesson: 6-7 vs a Deadlock while beating everyone else).
- One VOD/week, one number: untradeable deaths. Target < 4/game.
- Targets: comp K/D 0.90 → 1.05+ · KAST 73%+ · checkpoint: Gold 1 pace.

## Phase 3 — Close the comp gap (month 2)
- Comp hours exceed Swiftplay hours for the first time this act.
- Premier nights with the 1000 iqers roster — structured pressure normalizes nerves.
- Daily 10-min warmup; aim is maintenance now, not the project.
- Targets: DDΔ +1 → +8/rd · ACS 214 → 240 · HS% 24.9 → 28+.

## Phase 4 — Gold 3 and reassess (month 3)
- Re-run numbers on freshest 30 comp games; draft the next roadmap from the new baseline.
- Gear reopens only via the triggers below.

## Standing rules (never change)
1. Hard stop after two consecutive comp losses.
2. No queue after midnight (the 2 AM Haven game cost more RR than the OT loss before it).
3. Never re-queue after an OT loss — 15 minutes away, minimum.
4. No 10+ game marathons (the 11-game block contains the 0/6 game exactly where fatigue predicts).

## Escalation triggers (gear reopens only if one fires)
- HS% < 30 averaged over 30 games while flicks feel like overshooting → LOWGRAD cap 1.15× → 1.12×.
- Flicks feel dead after 30 games → raise cap 1.15× → 1.20×, or pull the cap speed in from 40 to 35 in/s.
  (The older triggers referenced the S-curve's 1.40 cap and 0.80 floor; LOWGRAD has neither.)
- Movement still feels wrong after the Whole-mode A/B → do the Wooting W/S fix next, alone, then
  raw 1:1 as a baseline. Do not change the curve for a movement complaint.
- Any DPI/sens change → regenerate the curve to match. Never play a mismatched curve.
  (FIRED Aug 2026: 3200/0.088 → 1600/0.15. Curve regenerated as VAL-LOWGRAD-1600-015.
  This trigger exists because a mismatched curve is indistinguishable from a "bad" curve by feel.)

**Weekly check, four numbers only:** KAST · K/D · HS% · untradeable deaths. Weekly, never mid-session.
