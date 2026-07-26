#!/usr/bin/env python3
"""LENIENT K-quote ingester.

Purpose: stop requiring a full 30-arm 6-book board. The K board is the hardest
thing on the slate to capture consistently, so this accepts whatever actually
gets captured -- one arm, one book, both sides of the price is enough -- and
runs only the integrity tests that a capture of that shape can actually support.

DROP FILE  data/mlb/props/drops/<date>_<tag>.json

    {"date": "2026-07-27",
     "captured_utc": "2026-07-27T16:40:00Z",     # omit if unknown -> never gate-eligible
     "source_type": "book_direct",               # or "aggregator"
     "source_note": "DK app, Sanchez prop page",
     "teams": {"Cristopher Sanchez": "PHI"},     # OPTIONAL, only needed for a TBD starter
     "quotes": [["DK", "Cristopher Sanchez", 7.5, -123, -104]]}

  quotes accepts three shapes, all equivalent:
    flat list  [book, pitcher, line, under, over]
    object     {"book":..,"pitcher":..,"line":..,"under":..,"over":..}
    keyed dict {"Cristopher Sanchez": [[book, line, under, over], ...]}
  null / missing under or over is fine. A one-sided quote is still usable:
  select_play just cannot take the missing side.

WHICH TESTS RUN, AND WHY

  T1 HOLD        runs on every quote that has BOTH sides. Overround outside
                 2-12% means a transcription error or not a real paired market.
                 A one-sided quote cannot be hold-checked and is passed through
                 with that stated, not silently trusted.
  T2 RUNG        runs when a pitcher has >=2 distinct lines with OVER prices.
                 Demoted 7/26 to necessary-but-not-sufficient: an alt ladder
                 passes T2 by construction. Warning only, never a rejection.
  T3 DISPERSION  runs ONLY when source_type == "aggregator" AND the pitcher has
                 >=2 books. A single book's own page has no alt-ladder ambiguity,
                 so there is nothing for dispersion to discriminate and forcing
                 the test there would throw away good prices. This is the
                 load-bearing test on aggregator boards (7/26: it caught 10 rows
                 that T2 passed, and the unfiltered fit was 65% too aggressive).
  T4 RE-READ     runs when an earlier drop for the same date covers the same
                 pitcher+book+line. Disagreement quarantines the pitcher.

GATE ELIGIBILITY is decided by the clock, never by the operator:
  registerable  <=> captured_utc is known AND captured_utc < first pitch
                    AND processing time < first pitch.
  Anything else is SHADOW: measured, written down, staked 0.0, advances the
  100-play authorization gate by zero.

Everything is PAPER. $0. select_play is imported unmodified; this file does not
tune, reweight, or second-guess a single engine threshold.
"""
import argparse, json, os, re, shutil, sys, unicodedata
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.kprops import select_play, proj

DROPDIR = "data/mlb/props/drops"
HOLD_LO, HOLD_HI = 2.0, 12.0
DISP_MAX = 1.0          # cross-book line spread, K
SHORT_LINE = 3.5        # known opener/bulk-arm defect zone


def a_(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def imp(ml):
    return (-ml) / (-ml + 100.0) if ml < 0 else 100.0 / (ml + 100.0)


def parse_utc(s):
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})(?::(\d{2}))?Z?$", s.strip())
    if not m:
        return None
    y, mo, d, h, mi, se = m.groups()
    return datetime(int(y), int(mo), int(d), int(h), int(mi), int(se or 0), tzinfo=timezone.utc)


def normalize_quotes(drop):
    """Any of the three accepted shapes -> [(book, pitcher, line, under, over)]."""
    q = drop.get("quotes")
    if q is None:
        for k in ("live_at_processing", "rows", "board"):
            if k in drop:
                q = drop[k]
                break
    out = []
    if isinstance(q, dict):
        for pitcher, cells in q.items():
            for c in cells:
                out.append((str(c[0]), pitcher, c[1],
                            c[2] if len(c) > 2 else None, c[3] if len(c) > 3 else None))
    elif isinstance(q, list):
        for c in q:
            if isinstance(c, dict):
                out.append((str(c["book"]), c["pitcher"], c.get("line"),
                            c.get("under"), c.get("over")))
            elif isinstance(c, dict) is False and len(c) >= 3 and isinstance(c[1], str):
                out.append((str(c[0]), c[1], c[2],
                            c[3] if len(c) > 3 else None, c[4] if len(c) > 4 else None))
            else:
                raise SystemExit("unrecognised quote row: %r" % (c,))
    else:
        raise SystemExit("drop file has no readable 'quotes'")
    return out


def load_card(date):
    """pitcher -> (ek, gs, game, first_pitch_utc), plus team -> first pitch.

    The card is the frozen pre-slate artifact: it was built from statsapi before
    any game started and never saw a price. It is the reproducible source of
    truth for E[K]. Its one weakness is that it stores E[K] rounded to 2dp, and
    a TBD starter has no name to match on -- both handled below.
    """
    path = "cards/%s_card.json" % date
    if not os.path.exists(path):
        return {}, {}, None
    C = json.load(open(path))
    ps, teams = {}, {}
    for r in C.get("rows", []):
        gk = "%s@%s" % (r["away"], r["home"])
        m = re.match(r"^(\d{1,2}):(\d{2})Z?$", str(r.get("time") or ""))
        fp = parse_utc("%sT%02d:%sZ" % (date, int(m.group(1)), m.group(2))) if m else None
        for t in (r["away"], r["home"]):
            teams[t.upper()] = dict(game=gk, first_pitch=fp)
        for sp in ("asp", "hsp"):
            st = r.get(sp + "_stats") or {}
            nm = r.get(sp)
            if nm and a_(nm) != "tbd":
                ps[a_(nm)] = dict(ek=st.get("ek"), gs=st.get("gs"), game=gk, first_pitch=fp)
    return ps, teams, path


def resolve_ek(pit, meta):
    """Full-precision E[K] without giving up the card's leak-proofing.

    engine.kprops.proj reads the pitcher logs as they stand RIGHT NOW, so on a
    replay it can silently include the very start being priced. The card cannot,
    but it only stores 2dp. So: take proj's precision only when proj still agrees
    with the frozen card to within that rounding. If they disagree, the log has
    moved since the card was cut -- use the card and say so out loud.
    """
    r = proj(pit)
    if meta and meta.get("ek") is not None:
        if r and abs(r[0] - meta["ek"]) <= 0.005 and r[1] == meta["gs"]:
            return r[0], meta["gs"], "card (frozen pre-slate), full precision from proj which still agrees to 2dp"
        if r:
            return meta["ek"], meta["gs"], ("card (frozen pre-slate), 2dp. proj now says %.4f / %d GS -- the log "
                                            "has MOVED since the card was cut, so proj is not usable here" % (r[0], r[1]))
        return meta["ek"], meta["gs"], "card (frozen pre-slate), 2dp. proj returns nothing"
    if r:
        return r[0], r[1], ("engine.kprops.proj on the live log -- NOT frozen pre-slate. Fine on a same-day "
                            "pregame drop, leaky on a replay")
    return None, (meta or {}).get("gs"), None


def prior_drops(date, this_path):
    """Every earlier drop for the same date, for T4."""
    seen = {}
    if not os.path.isdir(DROPDIR):
        return seen
    for fn in sorted(os.listdir(DROPDIR)):
        p = os.path.join(DROPDIR, fn)
        if not fn.startswith(date) or not fn.endswith(".json") or os.path.abspath(p) == os.path.abspath(this_path):
            continue
        if fn.endswith("_ingest.json"):
            continue
        try:
            for bk, pit, ln, u, o in normalize_quotes(json.load(open(p))):
                seen.setdefault(a_(pit), {})[(bk, ln)] = (u, o, fn)
        except Exception:
            continue
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("drop")
    ap.add_argument("--register", action="store_true",
                    help="write gate-eligible plays into ledgers.kprops_paper.plays_pending")
    ap.add_argument("--allow-short-lines", action="store_true",
                    help="permit registering arms posted at <=%.1f K (known opener/bulk-arm defect)" % SHORT_LINE)
    ap.add_argument("--now", default=None, help="override processing time, UTC, for replay")
    args = ap.parse_args()

    drop = json.load(open(args.drop))
    date = drop.get("date") or os.path.basename(args.drop)[:10]
    src = drop.get("source_type", "aggregator")
    if src not in ("aggregator", "book_direct"):
        raise SystemExit("source_type must be 'aggregator' or 'book_direct', got %r" % src)
    cap = parse_utc(drop.get("captured_utc"))
    now = parse_utc(args.now) or datetime.now(timezone.utc)

    quotes = normalize_quotes(drop)
    card, teamidx, cardpath = load_card(date)
    dropteams = {a_(k): str(v).upper() for k, v in (drop.get("teams") or {}).items()}
    priors = prior_drops(date, args.drop)

    print("drop        %s" % args.drop)
    print("date        %s   source_type %s" % (date, src))
    print("source_note %s" % drop.get("source_note", "(none given)"))
    print("captured    %s" % (drop["captured_utc"] if cap else "UNKNOWN -> nothing here can be gate-eligible"))
    print("processing  %s" % now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    print("card        %s (%d arms)" % (cardpath or "MISSING", len(card)))
    print("quotes      %d cells, %d arms\n" % (quotes and len(quotes) or 0,
                                               len({a_(p) for _, p, _, _, _ in quotes})))

    byp = {}
    for bk, pit, ln, u, o in quotes:
        byp.setdefault(pit, []).append([bk, ln, u, o])

    results, plays = [], []
    for pit, cells in byp.items():
        rej, warn, note = [], [], []

        # ---- T1 hold -------------------------------------------------------
        kept = []
        for bk, ln, u, o in cells:
            if ln is None:
                rej.append("%s: no line" % bk)
                continue
            if u is not None and o is not None:
                h = 100.0 * (imp(u) + imp(o) - 1.0)
                if not (HOLD_LO <= h <= HOLD_HI):
                    rej.append("T1 %s %.1f hold %.2f%% out of band" % (bk, ln, h))
                    continue
                note.append("T1 %s %.1f hold %.2f%%" % (bk, ln, h))
            elif u is None and o is None:
                rej.append("%s: line only, no price (R1: not a market)" % bk)
                continue
            else:
                note.append("T1 %s %.1f n/a (one-sided)" % (bk, ln))
            kept.append([bk, ln, u, o])

        # ---- T2 rung coherence (warning only) ------------------------------
        pts = sorted((ln, bk, o) for bk, ln, u, o in kept if o is not None)
        for (l1, b1, o1), (l2, b2, o2) in zip(pts, pts[1:]):
            if l1 != l2 and imp(o1) <= imp(o2):
                warn.append("T2 %.1f@%s %+d not priced above %.1f@%s %+d" % (l1, b1, o1, l2, b2, o2))

        # ---- T3 dispersion (aggregator, >=2 books only) --------------------
        books = {bk for bk, _, _, _ in kept}
        lns = [ln for _, ln, _, _ in kept]
        if src == "aggregator" and len(books) >= 2 and lns:
            sp = max(lns) - min(lns)
            if sp > DISP_MAX:
                rej.append("T3 cross-book spread %.1f K > %.1f -> alt rungs present, whole arm quarantined"
                           % (sp, DISP_MAX))
                kept = []
            else:
                note.append("T3 spread %.1f K over %d books" % (sp, len(books)))
        elif src == "book_direct":
            note.append("T3 skipped: single-book capture has no alt-ladder ambiguity")
        else:
            note.append("T3 skipped: only %d book" % len(books))

        # ---- T4 re-read vs earlier drops today -----------------------------
        pri = priors.get(a_(pit), {})
        for bk, ln, u, o in list(kept):
            if (bk, ln) in pri:
                pu, po, fn = pri[(bk, ln)]
                if (pu, po) != (u, o):
                    rej.append("T4 %s %.1f disagrees with %s (was U %s O %s, now U %s O %s)"
                               % (bk, ln, fn, pu, po, u, o))
                    kept = []
                    break
                note.append("T4 %s %.1f matches %s" % (bk, ln, fn))

        # ---- resolve the arm ------------------------------------------------
        oncard = a_(pit) in card
        meta = dict(card.get(a_(pit)) or dict(ek=None, gs=None, game=None, first_pitch=None))
        ek, gs, ek_src = resolve_ek(pit, card.get(a_(pit)))
        meta["ek"], meta["gs"] = ek, gs
        if ek is None:
            rej.append("no E[K]: %s, and engine.kprops.proj returns nothing (no log, or <5 GS)"
                       % ("on the card but the card carries no E[K]" if oncard
                          else "not on the card (likely a TBD starter when the card was cut)"))

        # a TBD starter has no card row, but the drop can still name his team,
        # and the team is enough to put him on a game clock.
        if meta.get("first_pitch") is None:
            tm = dropteams.get(a_(pit))
            if tm and tm in teamidx:
                meta["game"] = teamidx[tm]["game"]
                meta["first_pitch"] = teamidx[tm]["first_pitch"]
                note.append("clock resolved via team %s (arm not on the card)" % tm)

        fp = meta.get("first_pitch")
        if fp is None:
            eligible, why = False, "first pitch unknown (arm not on the card) -> cannot prove pre-lock"
        elif cap is None:
            eligible, why = False, "capture time unknown -> cannot prove pre-lock"
        elif cap >= fp:
            eligible, why = False, "captured %s, first pitch %s -> already locked" % (
                cap.strftime("%H:%MZ"), fp.strftime("%H:%MZ"))
        elif now >= fp:
            eligible, why = False, "processed %s, first pitch %s -> lock passed before this ran" % (
                now.strftime("%H:%MZ"), fp.strftime("%H:%MZ"))
        else:
            eligible, why = True, "captured %s, processed %s, first pitch %s -> %d min of runway" % (
                cap.strftime("%H:%MZ"), now.strftime("%H:%MZ"), fp.strftime("%H:%MZ"),
                (fp - now).total_seconds() // 60)

        sel = None
        if kept and meta.get("ek") is not None:
            sel = select_play([(b, l, u, o) for b, l, u, o in kept], meta["ek"], meta["gs"])

        status = "REJECTED"
        if sel:
            if sel["line"] <= SHORT_LINE and not args.allow_short_lines:
                status = "SHADOW"
                warn.append("posted line %.1f <= %.1f: a short posted line IS the book encoding a short "
                            "outing, and the engine's E[TBF] prior does not read it. Known defect "
                            "(Fedde/Freeland/Avila/Baz, 7/26). Held to shadow; --allow-short-lines to override."
                            % (sel["line"], SHORT_LINE))
            else:
                status = "REGISTERABLE" if eligible else "SHADOW"
        elif kept:
            status = "no play"

        row = dict(pitcher=pit, status=status, game=meta.get("game"),
                   first_pitch=fp.strftime("%Y-%m-%dT%H:%M:%SZ") if fp else None,
                   ek=meta.get("ek"), gs=meta.get("gs"), ek_source=ek_src,
                   quotes_in=len(cells), quotes_kept=len(kept),
                   gate_eligible=eligible, eligibility=why,
                   tests=note, warnings=warn, rejections=rej, play=sel)
        results.append(row)
        if sel:
            plays.append(row)

        mark = {"REGISTERABLE": "**", "SHADOW": " ~", "REJECTED": " x", "no play": "  "}[status]
        print("%s %-22s %-12s E[K] %-6s gs %-4s %s" % (
            mark, pit, status, ("%.2f" % meta["ek"]) if meta.get("ek") is not None else "--",
            meta.get("gs") if meta.get("gs") is not None else "--",
            ("%s %.1f @ %+d (%s) EV %+.3f edge %+.3f p %.3f"
             % (sel["side"], sel["line"], sel["price"], sel["book"], sel["ev"], sel["edge"], sel["p"]))
            if sel else ""))
        for t in note:
            print("      . " + t)
        for t in warn:
            print("      ! " + t)
        for t in rej:
            print("      X " + t)
        print("      clock: " + why)

    reg = [r for r in results if r["status"] == "REGISTERABLE"]
    print("\n%d arms in, %d priced, %d REGISTERABLE, %d SHADOW, %d rejected"
          % (len(byp), len(plays),
             len(reg), len([r for r in results if r["status"] == "SHADOW"]),
             len([r for r in results if r["status"] == "REJECTED"])))

    out = dict(drop=args.drop, date=date, source_type=src,
               source_note=drop.get("source_note"), captured_utc=drop.get("captured_utc"),
               processed_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
               selector="engine.kprops.select_play, unmodified",
               staked=0.0, rows=results)
    op = os.path.splitext(args.drop)[0] + "_ingest.json"
    json.dump(out, open(op, "w"), indent=1)
    print("wrote %s" % op)

    if not args.register:
        if reg:
            print("\n%d play(s) are gate-eligible. Re-run with --register to add them to "
                  "ledgers.kprops_paper.plays_pending." % len(reg))
        return

    if not reg:
        print("\n--register: nothing gate-eligible, state.json untouched.")
        return

    shutil.copy("state.json", "/tmp/state.bak.ingest.json")
    S = json.load(open("state.json"))
    L = S["ledgers"]["kprops_paper"]
    have = {(p["date"], a_(p["pitcher"])) for p in L["plays_pending"]}
    added = 0
    for r in reg:
        if (date, a_(r["pitcher"])) in have:
            print("  already pending, skipped: %s" % r["pitcher"])
            continue
        p = r["play"]
        L["plays_pending"].append(dict(
            date=date, pitcher=r["pitcher"], side=p["side"], line=p["line"], price=p["price"],
            book=p["book"], ek=round(r["ek"], 2), gs=r["gs"], p=p["p"], weight=p["weight"],
            edge=p["edge"], ev_per_unit=p["ev"], disp=p["disp"], game=r["game"],
            first_pitch_utc=r["first_pitch"], registered_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            preregistered_before_first_pitch=True,
            selector="engine/kprops.select_play via harness/ingest_kquote.py, UNMODIFIED. "
                     "Canonical thresholds (EV>0, edge>=0.04, |disp|>=0.8, gs>=5, directional sanity).",
            price_provenance="%s capture, source_type=%s. %s. Observed price, never invented (R1). "
                             "Captured %s, registered %s." % (
                                 drop.get("source_note", "user drop"), src,
                                 "; ".join(r["tests"]) or "no test applicable",
                                 drop.get("captured_utc"), now.strftime("%H:%MZ")),
            integrity_warnings=r["warnings"], staked=0.0))
        have.add((date, a_(r["pitcher"])))
        added += 1
        print("  registered: %s %s %.1f @ %+d (%s)" % (r["pitcher"], p["side"], p["line"], p["price"], p["book"]))

    graded = L["record_w"] + L["record_l"]
    names = ", ".join(p["pitcher"] for p in L["plays_pending"])
    L["units"] = L["units"]  # untouched: nothing here grades
    S["gates"]["kprops_go_live"]["progress"] = "%d/100 graded%s" % (
        graded, (", +%d pending (%s)" % (len(L["plays_pending"]), names)) if L["plays_pending"] else "")
    S["updated_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump(S, open("state.json", "w"), indent=1)

    V = json.load(open("state.json"))
    assert V["ledgers"]["kprops_paper"]["record_w"] == L["record_w"]
    assert V["ledgers"]["kprops_paper"]["record_l"] == L["record_l"]
    assert V["gates"]["kprops_go_live"]["passes"] is False
    print("\n%d added. gate now: %s" % (added, V["gates"]["kprops_go_live"]["progress"]))
    print("backup at /tmp/state.bak.ingest.json")


if __name__ == "__main__":
    main()
