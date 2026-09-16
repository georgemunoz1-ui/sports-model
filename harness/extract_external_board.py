#!/usr/bin/env python3
"""Extract the external v2 slate board into machine-readable form for side-by-side grading.

Input : data/mlb/external/2026-07-29_slate_board_v2.html (frozen; v1 is NEVER used — wrong starters)
Output: data/mlb/external/2026-07-29_board_v2_extract.json

Classification travels with the data (owner ruling 2026-07-29):
EXTERNAL_MARKET_ANCHORED_REFERENCE · PROVENANCE_INCOMPLETE · DESCRIPTIVE_ONLY.
Its totals are slate-scaled (x0.950) to the market-average total and its K method adjusts the
market K line — so it is NOT independent of the market and is graded only as a labeled reference
column. Unparsed rows are counted, never guessed.
"""

from __future__ import annotations

MODULE_ID = "extract_external_board"

import hashlib
import html
import json
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

SRC = "data/mlb/external/2026-07-29_slate_board_v2.html"
OUT = "data/mlb/external/2026-07-29_board_v2_extract.json"

TIME = re.compile(r"^\d{1,2}:\d{2}[ap]$")
PRICE = re.compile(r"^[+-]\d{2,4}$")
NUM = re.compile(r"^[+-]?\d+(\.\d+)?$")


def _text(p):
    s = open(p, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.S)
    t = re.sub(r"<[^>]+>", "\n", t)
    return [l.strip() for l in html.unescape(t).splitlines() if l.strip()]


def extract():
    L = _text(SRC)
    ml, totals, kprops, problems = [], [], [], []

    i = 0
    while i < len(L) - 10:
        if TIME.match(L[i]) and "@" in L[i + 1]:
            g = L[i + 1]
            # ML row: side, price, "vs SP", model, market, edge, fair, ev
            if PRICE.match(L[i + 3]) and L[i + 4].startswith("vs "):
                ml.append(dict(game=g, side=L[i + 2], best_price=int(L[i + 3]),
                               opp_sp=L[i + 4][3:], model_pct=float(L[i + 5]),
                               market_pct=float(L[i + 6]), edge=float(L[i + 7]),
                               fair=L[i + 8], ev_pct=float(L[i + 9])))
                i += 10
                continue
            # totals row: "Over 7.5"/"Under 7.5", [wide gap], price, model_total, model%, market%, edge, ev
            if L[i + 2].startswith(("Over ", "Under ")):
                j = i + 3
                wide = L[j] == "wide gap"
                if wide:
                    j += 1
                try:
                    row = dict(game=g, side=L[i + 2].split()[0], line=float(L[i + 2].split()[1]),
                               best_price=int(L[j]), model_total=float(L[j + 1]),
                               model_pct_conditional=float(L[j + 2]), market_pct=float(L[j + 3]),
                               edge=float(L[j + 4]), ev_pct=float(L[j + 5]), wide_gap=wide)
                    totals.append(row)
                    i = j + 6
                    continue
                except (ValueError, IndexError):
                    problems.append(f"totals row parse failed near line {i}: {L[i:i+9]}")
        i += 1

    # K rows: Name / LHP|RHP / Tm / Opp / line / projk / diff / spk / matchupk / lineupk / over / under / book
    i = 0
    while i < len(L) - 12:
        if L[i + 1] in ("LHP", "RHP") and re.fullmatch(r"[A-Z]{2,3}", L[i + 2]):
            seq = L[i + 4:i + 12]
            if all(NUM.match(x) for x in seq[:6]):
                kprops.append(dict(player=L[i], hand=L[i + 1], team=L[i + 2], opp=L[i + 3],
                                   line=float(seq[0]), proj_k=float(seq[1]), diff=float(seq[2]),
                                   sp_k_pct=float(seq[3]), matchup_k_pct=float(seq[4]),
                                   lineup_k_pct=float(seq[5]),
                                   over=seq[6] if len(seq) > 6 else None,
                                   under=seq[7] if len(seq) > 7 else None))
                i += 12
                continue
        i += 1

    out = {
        "record_id": "EXTERNAL-BOARD-V2-EXTRACT-2026-07-29",
        "source_file": SRC, "source_sha256": hashlib.sha256(open(SRC, "rb").read()).hexdigest(),
        "classification": ["EXTERNAL_MARKET_ANCHORED_REFERENCE", "PROVENANCE_INCOMPLETE",
                           "DESCRIPTIVE_ONLY"],
        "anchoring": {"totals": "slate-scaled x0.950 to market-average total (stated on board) — "
                                "NOT independent of the market",
                      "k_props": "MARKET-ANCHORED MATCHUP ADJUSTMENT: log5 rate rescale of the "
                                 "posted line; the line already embeds workload+skill+matchup+market",
                      "lineups": "TOP-NINE-VOLUME ROSTER PROXY — no lineups were posted; does not "
                                 "test confirmed-lineup value",
                      "totals_display": "Over/Under percentages are CONDITIONAL-ON-SETTLEMENT; "
                                        "P(push) incorporated in EV but NOT displayed -> not auditable"},
        "ml_rows": ml, "totals_rows": totals, "k_rows": kprops, "problems": problems,
    }
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"{OUT}: {len(ml)} ML rows, {len(totals)} totals rows, {len(kprops)} K rows, "
          f"{len(problems)} problems")
    for p in problems[:5]:
        print("  PROBLEM: " + p)
    return 1 if (len(ml) != 32 or len(totals) != 32) else 0


if __name__ == "__main__":
    raise SystemExit(extract())
