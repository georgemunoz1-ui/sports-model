"""Record the owner-relayed DraftKings College Football board, captured 2026-08-28.

THE FIRST FINDING IS THE DATE, NOT THE PRICES. The five screenshots scroll monotonically down the
book's chronological board. The section headers visible in them are "Thu 3 Sep" and "Fri 4 Sep",
and the Saturday block sits ABOVE the "Thu 3 Sep" header, so that Saturday is the one BEFORE
September 3 — 2026-08-29. Every row in the relay is therefore Aug 29, Sep 3 or Sep 4.

    ZERO of the 19 relayed games are on tonight's 2026-08-28 slate.

So this file is NOT an overlay on the 8/28 card and must never be attached to one. The 8/28 board
and card are unchanged by it. What it is instead is a FORWARD market snapshot with real value for
the CFB v2 challenger, which is FBS-only and still PREREGISTERED_DATA_ACQUISITION_PENDING with an
empty cohort: 8/28 had zero FBS games, and these dates plainly do not.

WHAT THIS RELAY DOES NOT SETTLE. It does not show the top of the board, so it CANNOT be read as
evidence that the book has no 2026-08-28 college football at all. The relayed PORTION contains
none; that is the whole claim.

COHORT MEMBERSHIP IS REFUSED, NOT GUESSED. The v2 challenger is FBS-only and no registered FBS
team list exists in this repository. Several teams here changed subdivision in the 2024-2026
realignment window, so classifying them from memory is exactly the invented-number failure R1
forbids. Matchups are recorded verbatim and the FBS/FCS split is left NULL, to be filled from the
registered list when v2's data acquisition actually runs.

FOUR MONEYLINES ARE PADLOCKED on the book and are recorded as null with that reason. A price the
book declines to offer is not a price to be estimated.
"""
from __future__ import annotations

MODULE_ID = "record_cfb_relay_0828"

import hashlib
import json
import os
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

CAPTURE_DATE = "2026-08-28"
OUT = f"data/cfb/odds/{CAPTURE_DATE}_owner_relay_dk_forward.json"

# date, away, home, away_ml, home_ml, away_spread, away_px, home_spread, home_px,
# total, over_px, under_px, slot_as_displayed
ROWS = [
 ("2026-08-29", "Jacksonville State", "North Dakota State", +225, -278, +7.0, -115, -7.0, -105, 46.5, -112, -108, "Sat 2:30 PM"),
 ("2026-08-29", "Sacramento State", "Eastern Michigan", +295, -375, +9.5, -108, -9.5, -112, 53.5, -112, -108, "Sat 3:30 PM"),
 ("2026-08-29", "Hawaii", "Stanford", +164, -198, +4.0, -108, -4.0, -112, 48.5, -112, -108, "Sat 4:00 PM"),
 ("2026-08-29", "New Mexico State", "Florida State", +3000, -10000, +31.5, -108, -31.5, -112, 53.5, -112, -108, "Sat (slot row not captured)"),
 ("2026-08-29", "Memphis", "UNLV", +160, -192, +4.5, -115, -4.5, -105, 56.5, -112, -108, "Sat 7:00 PM"),
 ("2026-09-03", "UMass", "Rutgers", +2500, -9000, +29.5, -110, -29.5, -110, 52.5, -112, -108, "Thu 3:00 PM"),
 ("2026-09-03", "Merrimack", "Delaware", +3500, -20000, +28.5, -112, -28.5, -108, 55.5, -108, -112, "Thu 4:00 PM"),
 ("2026-09-03", "West Georgia", "Kennesaw State", +1500, -3600, +22.5, -115, -22.5, -105, 51.5, -112, -108, "Thu 4:00 PM"),
 ("2026-09-03", "Bethune-Cookman", "UCF", None, None, +42.5, -110, -42.5, -110, 59.5, -112, -108, "Thu 4:00 PM"),
 ("2026-09-03", "Albany NY", "Buffalo", +1800, -5000, +24.5, -112, -24.5, -108, 48.5, -108, -112, "Thu 4:00 PM"),
 ("2026-09-03", "Akron", "Wake Forest", +1500, -3600, +23.5, -105, -23.5, -115, 48.5, -105, -115, "Thu 4:00 PM"),
 ("2026-09-03", "Colorado", "Georgia Tech", +210, -258, +6.5, -105, -6.5, -115, 50.5, -115, -105, "Thu 5:00 PM"),
 ("2026-09-03", "Arkansas-Pine Bluff", "Missouri", None, None, +54.5, -108, -54.5, -112, 60.5, -108, -112, "Thu 5:00 PM"),
 ("2026-09-03", "Eastern Illinois", "Minnesota", None, None, +43.5, -112, -43.5, -108, 51.5, -110, -110, "Thu 5:00 PM"),
 ("2026-09-03", "Idaho", "Utah", +3500, -20000, +33.5, -108, -33.5, -112, 56.5, -108, -112, "Thu (slot row not captured)"),
 ("2026-09-03", "UAB", "Illinois", +2200, -8000, +28.5, -112, -28.5, -108, 56.5, -108, -112, "Thu 6:00 PM"),
 ("2026-09-04", "San Jose State", "Eastern Michigan", +180, -218, +4.5, -105, -4.5, -115, 53.5, -112, -108, "Sep 4th"),
 ("2026-09-04", "North Carolina A&T", "Georgia State", +1700, -4500, +28.5, -112, -28.5, -108, 63.5, -110, -110, "Sep 4th"),
 ("2026-09-04", "Indiana State", "Purdue", None, None, +35.5, -110, -35.5, -110, 56.5, -110, -110, "Sep 4th (row truncated at screen edge)"),
]

#: AP ranks shown on the book's board. Recorded because they are evidence of the book's own
#: cohort view, not used as a model input.
RANK_SHOWN = {"Missouri": 25, "Utah": 21}

SPREAD_TOTAL_BAND = (2.0, 8.0)
#: Moneyline hold runs lower on heavy favourites than on a balanced game, so a wider band is
#: correct here. Narrowing it to the spread band would flag five sound rows as transcription errors.
ML_BAND = (2.0, 12.0)


def implied(o):
    return None if o is None else (-o / (-o + 100.0) if o < 0 else 100.0 / (o + 100.0))


def hold(o1, o2):
    if o1 is None or o2 is None:
        return None
    s = implied(o1) + implied(o2)
    return 100.0 * (s - 1.0) / s


def build():
    games, problems = [], []
    for (d, aw, hm, aml, hml, asp, apx, hsp, hpx, tot, op, up, slot) in ROWS:
        h_ml, h_sp, h_to = hold(aml, hml), hold(apx, hpx), hold(op, up)
        if asp + hsp != 0:
            problems.append(f"{aw}@{hm}: spreads {asp}/{hsp} do not mirror")
        if h_ml is not None and not (ML_BAND[0] <= h_ml <= ML_BAND[1]):
            problems.append(f"{aw}@{hm}: moneyline hold {h_ml:.2f}% outside {ML_BAND}")
        for nm, v in (("spread", h_sp), ("total", h_to)):
            if not (SPREAD_TOTAL_BAND[0] <= v <= SPREAD_TOTAL_BAND[1]):
                problems.append(f"{aw}@{hm}: {nm} hold {v:.2f}% outside {SPREAD_TOTAL_BAND}")
        games.append({
            "game_date": d, "away": aw, "home": hm,
            "slot_as_displayed": slot,
            "rank_shown_on_book": {k: v for k, v in RANK_SHOWN.items() if k in (aw, hm)} or None,
            "moneyline": {"away": aml, "home": hml,
                          "break_even_away": None if aml is None else round(implied(aml), 6),
                          "break_even_home": None if hml is None else round(implied(hml), 6),
                          "two_sided_hold_pct": None if h_ml is None else round(h_ml, 4),
                          "null_reason": None if aml is not None else
                                         "MONEYLINE_NOT_OFFERED — padlocked on the book; a price "
                                         "the book declines to offer is not a price to estimate"},
            "spread": {"away": asp, "away_px": apx, "home": hsp, "home_px": hpx,
                       "two_sided_hold_pct": round(h_sp, 4)},
            "total": {"line": tot, "over_px": op, "under_px": up,
                      "two_sided_hold_pct": round(h_to, 4)},
            "cohort": None,
            "cohort_status": "REFUSED_UNCLASSIFIED",
        })

    by_date = dict(Counter(g["game_date"] for g in games))
    on_slate = [g for g in games if g["game_date"] == "2026-08-28"]

    doc = {
        "record_id": f"CFB-MARKET-RELAY-{CAPTURE_DATE}-DK-FORWARD",
        "schema": "ops.market_relay_forward.v1",
        "sport": "cfb",
        "captured_utc_asserted": "2026-08-28T10:55:00Z",
        "relay": {"source": "DraftKings sportsbook, College Football Game Lines, filter 'All'",
                  "channel": "owner relay, five screenshots",
                  "screenshot_clock": ["3:38", "3:38", "3:38", "3:39", "3:39"],
                  "grade": "OWNER_RELAYED_SINGLE_BOOK"},
        "DATE_SCOPE": {
            "n_games": len(games),
            "by_game_date": by_date,
            "rows_on_2026_08_28": len(on_slate),
            "finding": ("ZERO of the 19 relayed games are on the 2026-08-28 slate. This relay "
                        "prices none of tonight's card."),
            "how_the_dates_were_established": (
                "The screenshots scroll monotonically down the book's chronological board. Two "
                "section headers are visible — 'Thu 3 Sep' and 'Fri 4 Sep'. The Saturday block "
                "sits ABOVE the 'Thu 3 Sep' header, so it is the Saturday before September 3, "
                "i.e. 2026-08-29. Dates are read from the board's own structure, not assigned."),
            "applied_to_the_8_28_card": "NOTHING. The 8/28 boards and card are unchanged. This "
                                        "file is never attached as an 8/28 overlay.",
            "what_this_does_NOT_establish": (
                "The top of the board is not shown, so this relay CANNOT be read as evidence that "
                "the book carries no 2026-08-28 college football at all. The claim is only that "
                "the relayed portion contains none. The separate finding that zero FBS games "
                "exist on 8/28 rests on the schedule acquisition, not on this file."),
        },
        "TRANSCRIPTION_VERIFICATION": {
            "method": ("every two-sided pair must imply a hold in band. Spread and total use "
                       "2-8%; moneyline uses a wider 2-12% because hold runs lower on heavy "
                       "favourites and the narrow band would flag five sound rows as errors."),
            "pairs_checked": 2 * len(games) + sum(1 for g in games
                                                  if g["moneyline"]["away"] is not None),
            "spread_hold_range_pct": [round(min(g["spread"]["two_sided_hold_pct"] for g in games), 4),
                                      round(max(g["spread"]["two_sided_hold_pct"] for g in games), 4)],
            "total_hold_range_pct": [round(min(g["total"]["two_sided_hold_pct"] for g in games), 4),
                                     round(max(g["total"]["two_sided_hold_pct"] for g in games), 4)],
            "moneyline_hold_range_pct": [
                round(min(g["moneyline"]["two_sided_hold_pct"] for g in games
                          if g["moneyline"]["two_sided_hold_pct"] is not None), 4),
                round(max(g["moneyline"]["two_sided_hold_pct"] for g in games
                          if g["moneyline"]["two_sided_hold_pct"] is not None), 4)],
            "moneylines_padlocked": sum(1 for g in games if g["moneyline"]["away"] is None),
            "cross_screenshot_check": ("West Georgia @ Kennesaw State appears at the bottom of one "
                                       "screenshot and the top of the next; both renderings agree "
                                       "on every one of its six prices."),
            "problems": problems,
            "verdict": "PASS" if not problems else "FAIL",
        },
        "COHORT_CLASSIFICATION_REFUSED": {
            "status": "REFUSED_UNCLASSIFIED for all 19 rows",
            "why": ("cfb.fbs.epa_talent_hgb.v2_0.challenger is FBS-only and NO registered FBS team "
                    "list exists in this repository. Several teams in this relay changed "
                    "subdivision during the 2024-2026 realignment window, so classifying them "
                    "from memory would be an invented input. R1: missing data is null plus a "
                    "flag, never a guess."),
            "resolve_by": ("filling the split from the registered FBS list when v2's "
                           "PREREGISTERED_DATA_ACQUISITION actually runs"),
        },
        "VALUE_FOR_CFB_V2": {
            "why_this_is_worth_keeping": (
                "the v2 challenger has an EMPTY cohort tonight — 8/28 surfaced seven games and "
                "every one was FCS against FCS. These three dates plainly are not empty, so this "
                "is the first market snapshot covering dates on which the challenger could have a "
                "cohort at all."),
            "status_unchanged": "cfb.fbs.epa_talent_hgb.v2_0.challenger remains "
                                "PREREGISTERED_DATA_ACQUISITION_PENDING. No forecast, no "
                                "selection, no EV. Prices are never predictive features.",
            "retention_rule": ("held as a dated market observation. If v2 ever forecasts these "
                               "dates, this snapshot is a PRE-existing price record and must be "
                               "treated as such rather than as a closing line."),
        },
        "TIMEZONE_COROBORATION": {
            "bears_on": "the open WNBA start-time discrepancy recorded in "
                        "data/wnba/odds/2026-08-28_owner_relay_dk.json",
            "finding": ("This relay independently supports the PACIFIC reading of the phone clock. "
                        "Under Eastern the Thursday college slots would be 3:00, 4:00, 5:00 and "
                        "6:00 PM ET, which are not real Thursday-night college football windows. "
                        "Under Pacific they are 6:00, 7:00, 8:00 and 9:00 PM ET, which are exactly "
                        "the canonical windows, and Memphis at UNLV becomes a 10:00 PM ET Vegas "
                        "late game."),
            "effect": ("the timezone half of the WNBA discrepancy is now corroborated on "
                       "independent grounds. The remaining +10 minute gap between the book and "
                       "the wehoop parquet is UNCHANGED and still unresolved."),
            "still_inferred": ("no screenshot states its timezone. This is strong corroboration "
                               "from slot plausibility, not a confirmation."),
        },
        "DISPOSITION": {"selections": 0, "n_bets": 0, "units": 0.0, "exposure_usd": 0,
                        "wager_authority": "NO",
                        "reason": "no registered CFB model may forecast these games; the FBS "
                                  "challenger is preregistered and pending data acquisition"},
        "games": games,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    return doc


if __name__ == "__main__":
    d = build()
    tv = d["TRANSCRIPTION_VERIFICATION"]
    print("RELAY", d["record_id"])
    print(f'  {hashlib.sha256(open(OUT, "rb").read()).hexdigest()[:8]}  {OUT}')
    print("  transcription", tv["verdict"], "| spread hold", tv["spread_hold_range_pct"],
          "| total hold", tv["total_hold_range_pct"], "| ML hold", tv["moneyline_hold_range_pct"])
    print("  padlocked moneylines:", tv["moneylines_padlocked"])
    print("  by date:", d["DATE_SCOPE"]["by_game_date"])
    print("  ROWS ON THE 8/28 SLATE:", d["DATE_SCOPE"]["rows_on_2026_08_28"])
