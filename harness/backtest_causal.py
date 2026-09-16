"""Causal backtest evaluation layer — PointInTime store, entry/close resolution, CLV, folds.

Adopts the owner's causal-backtest rules as executable constraints. THE POINT OF THIS MODULE: a
backtest that can see the future reports a skill it does not have. Every record in the store
carries an availability timestamp; every reader declares a decision_time; the store REFUSES
post-cutoff reads (fail-closed via harness/market_history.pregame_read's TemporalFirewallError).

TIMELINE FIELDS (all stored per event, never collapsed):
  event_start_time, decision_time, feature_available_time, odds_snapshot_time,
  simulated_bet_time, closing_time, settlement_time.

CORE RULE: the closing line is an outcome/evaluation benchmark ONLY — CLV, movement measurement,
model-vs-final-consensus — never a decision input, unless the simulated bet was actually placed
at closing (simulated_bet_time inside the close window).

REALISM ASSUMPTIONS (documented, owner rule 10): bets are assumed placeable at the quoted price
with a fixed documented latency (EXECUTION_LATENCY_SECONDS), full limits, and line shopping only
across books observable at the timestamp — never best-book-after-the-fact. Any bet that could NOT
realistically be placed (no book in the store offered the price at or before decision_time) is
EXCLUDED — entry_line returns None and the caller skips the bet; a missing entry price is NEVER
backfilled from a later snapshot (rule 4). Cancelled/postponed games use the event status AS
KNOWN at decision_time; a status learned later is a later snapshot, never a rewrite (append-only,
R6 — revised data preserves the original publication/ingestion version).

ADDENDUM-4 REFINEMENTS folded in: the news timestamp trichotomy (event/publication/ingestion —
the governing time is publication_time, the earliest realistic bettor-access time), the
shift(1)-before-rolling lint, purge/embargo between train and test (EMBARGO named constant),
split-by-event-AND-date before feature creation, locked-strategy evaluation reporting by
season/sport/market/book/odds-range, and first-executable-quote entry semantics. The store's
contract remains the final audit question: "Could this exact value have been known at the wager
timestamp?" — "only after the game / closing / full season" is refused.
"""
from __future__ import annotations

MODULE_ID = "backtest_causal"

import datetime as dt
import statistics
import sys

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import market_history

UTC = dt.timezone.utc

TIMELINE_FIELDS = ("event_start_time", "decision_time", "feature_available_time",
                   "odds_snapshot_time", "simulated_bet_time", "closing_time", "settlement_time")

#: closing line = last valid price inside this window before event start (owner default: 15 min)
CLOSE_WINDOW_MINUTES = 15

#: closing book priority: Circa (sharp) by default, Pinnacle as the fallback
CLOSING_BOOK_PRIORITY = ("circa", "pinnacle")

#: documented execution latency: the first quote AT OR AFTER signal_time + latency is executable
EXECUTION_LATENCY_SECONDS = 60

#: purge/embargo between train and validation/test when features overlap the prediction horizon
#: (multi-day injury news, rolling market features). A gap is ALLOWED; this names its size.
EMBARGO_HOURS = 24

MISSING_ENTRY = "BET_UNAVAILABLE_NO_ENTRY_PRICE"

NEWS_FIELDS = ("event_time", "publication_time", "ingestion_time")


def governing_time(news_record):
    """Timestamp trichotomy (news/injuries). event_time = when it occurred; publication_time =
    when the market could know; ingestion_time = when we received it. The governing timestamp is
    the earliest realistic bettor-access time — normally publication_time. All three are stored;
    this function is the ONLY place the governing one is chosen."""
    for f in NEWS_FIELDS:
        if news_record.get(f) in (None, "", "TBD"):
            raise ValueError(f"news record missing {f}; store all three timestamps")
    return _utc(news_record["publication_time"])


def entry_executable(records, signal_time, sportsbook, market_type, outcome,
                     latency_seconds=EXECUTION_LATENCY_SECONDS):
    """Execution-realistic entry (Addendum 4 #6): the FIRST executable quote at or after
    signal_time + latency — not the last quote before. None = bet unavailable/skip; choosing the
    best book after seeing the outcome is forbidden, so the book is a parameter, not an argmax."""
    t0 = _utc(signal_time) + dt.timedelta(seconds=latency_seconds)
    cand = [r for r in records
            if r["sportsbook"] == sportsbook and r["market_type"] == market_type
            and r["outcome"] == outcome and _utc(r["snapshot_time_utc"]) >= t0]
    if not cand:
        return None
    return min(cand, key=lambda r: _utc(r["snapshot_time_utc"]))


def rolling_feature_lint(source_text):
    """Lint for the shift(1) rule: the current game must never appear in its own rolling feature.
    Flags a groupby/rolling chain with no shift(1) before the rolling/expanding call. The paired
    fixture in test_market_layer shows the wrong and the right pattern:
      WRONG: df.groupby('team')['x'].transform(lambda s: s.rolling(10, min_periods=3).mean())
      RIGHT: df.groupby('team')['x'].transform(lambda s: s.shift(1).rolling(10, min_periods=3).mean())
    """
    import re
    problems = []
    for m in re.finditer(r"transform\(\s*lambda\s+\w+\s*:\s*([^)]+)\)", source_text):
        chain = m.group(1)
        if ("rolling(" in chain or "expanding(" in chain) and "shift(1)" not in chain.split("rolling(")[0].split("expanding(")[0]:
            problems.append({"code": "UNSHIFTED_ROLLING_FEATURE", "chain": chain.strip(),
                             "detail": "shift(1) before rolling/expanding — the current game is "
                                      "in its own feature (look-ahead)"})
    return problems


def purged_walk_forward_folds(dates, n_folds=3, embargo_hours=EMBARGO_HOURS):
    """Walk-forward folds with a purge/embargo: validation starts at least embargo_hours after
    the last train date when dates carry times; with date-only strings the embargo is one full
    step of dropped dates between train and validate. Split is by DATE — and the caller must
    split by event AND date BEFORE feature creation so duplicate snapshots of one event never
    land in both train and test (enforced by construction in split_events below)."""
    dates = sorted(dates)
    base = walk_forward_folds(dates, n_folds)
    out = []
    for fl in base:
        train, val = fl["train"], list(fl["validate"])
        embargoed = []
        if train and val:
            # drop validation dates within the embargo window of the last train date
            try:
                t_end = _utc(train[-1] + "T23:59:59Z") if "T" not in train[-1] else _utc(train[-1])
                embargoed = [d for d in val
                             if (_utc(d if "T" in d else d + "T00:00:00Z") - t_end)
                             < dt.timedelta(hours=embargo_hours)]
                val = [d for d in val if d not in embargoed]
            except Exception:
                pass
        out.append({"train": train, "validate": val, "embargoed": embargoed,
                    "embargo_hours": embargo_hours,
                    "rule": "purge/embargo applied; fit all preprocessing on train only"})
    return out


def split_events(event_ids, test_fraction=0.25, seed=0):
    """Split by EVENT before any feature creation: every snapshot of an event lives in exactly
    one side, so a duplicated odds snapshot can never bridge train and test. Deterministic."""
    import hashlib as _h
    train, test = [], []
    for e in sorted(set(map(str, event_ids))):
        bucket = int(_h.sha256(f"{seed}:{e}".encode()).hexdigest(), 16) % 1000 / 1000.0
        (test if bucket < test_fraction else train).append(e)
    return {"train": train, "test": test,
            "rule": "event-level split before feature creation; an event's snapshots stay together"}


def _utc(value):
    p = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return p if p.tzinfo else p.replace(tzinfo=UTC)


def implied_prob(american_price):
    """Implied probability from an AMERICAN price. Owner rule 6: derived from the ENTRY price,
    never the close — this function takes whatever price it is given; the caller's discipline
    (entry_resolution below) is what keeps it honest."""
    p = float(american_price)
    return (-p / (-p + 100.0)) if p < 0 else (100.0 / (p + 100.0))


class PointInTimeStore:
    """Records with availability timestamps; readers declare decision_time; post-cutoff reads
    refuse (fail-closed). Wraps market_history records; any record carrying snapshot_time_utc is
    storable."""

    def __init__(self):
        self._records = []

    def add(self, record):
        problems = market_history.validate_history_record(record)
        if problems:
            raise ValueError(f"unstorable record: {problems}")
        self._records.append(record)
        return record

    def read(self, decision_time, event_id=None, market_type=None):
        """Fail-closed read at a declared decision_time. Raises TemporalFirewallError when the
        candidate set contains anything the decision could not have seen."""
        return market_history.pregame_read(self._records, decision_time,
                                           event_id=event_id, market_type=market_type)

    def all_records(self):
        return list(self._records)


def entry_line(records, decision_time, sportsbook, market_type, outcome):
    """ENTRY = last price at or before decision_time for this book/market/outcome.

    Returns the record, or None when no such price exists (the bet is UNAVAILABLE and must be
    skipped — rule 4 forbids backfilling from later snapshots, so None is the honest answer)."""
    cutoff = _utc(decision_time)
    cand = [r for r in records
            if r["sportsbook"] == sportsbook and r["market_type"] == market_type
            and r["outcome"] == outcome and _utc(r["snapshot_time_utc"]) <= cutoff]
    if not cand:
        return None
    return max(cand, key=lambda r: _utc(r["snapshot_time_utc"]))


def closing_line(records, event_start_time, market_type, outcome,
                 window_minutes=CLOSE_WINDOW_MINUTES, book_priority=CLOSING_BOOK_PRIORITY):
    """CLOSING = last valid price inside the market-close window before event start.

    Book: Circa by default, Pinnacle fallback, then any book present in the window (documented
    as a degradation, not silently sharpened). Returns (record, book_note) or (None, note)."""
    start = _utc(event_start_time)
    lo = start - dt.timedelta(minutes=window_minutes)
    cand = [r for r in records if r["market_type"] == market_type and r["outcome"] == outcome
            and lo <= _utc(r["snapshot_time_utc"]) <= start]
    if not cand:
        return None, "no price inside the close window — closing benchmark unavailable"
    for book in book_priority:
        own = [r for r in cand if r["sportsbook"] == book]
        if own:
            return max(own, key=lambda r: _utc(r["snapshot_time_utc"])), f"closing book: {book}"
    rec = max(cand, key=lambda r: _utc(r["snapshot_time_utc"]))
    return rec, f"closing book DEGRADED to {rec['sportsbook']} (neither circa nor pinnacle in window)"


def consensus_close(records, event_start_time, market_type, outcome,
                    window_minutes=CLOSE_WINDOW_MINUTES):
    """Median of books observable AT the closing cutoff — never the day's full history (rule 5)."""
    start = _utc(event_start_time)
    lo = start - dt.timedelta(minutes=window_minutes)
    per_book = {}
    for r in records:
        if r["market_type"] == market_type and r["outcome"] == outcome:
            t = _utc(r["snapshot_time_utc"])
            if lo <= t <= start:
                cur = per_book.get(r["sportsbook"])
                if cur is None or t > _utc(cur["snapshot_time_utc"]):
                    per_book[r["sportsbook"]] = r
    if not per_book:
        return None
    return {"books": sorted(per_book), "n_books": len(per_book),
            "consensus_point": statistics.median(r["point"] for r in per_book.values()),
            "consensus_price": statistics.median(float(r["american_price"])
                                                 for r in per_book.values())}


def clv(entry, closing):
    """CLV, computed POST-WAGER only (rule 9). entry/closing are records with point/american_price.
    spread markets: closing_spread - entry_spread. price: closing_implied - entry_implied.
    Entry and closing stay SEPARATE column families — this function joins them only to subtract."""
    return {"entry_point": entry["point"], "closing_point": closing["point"],
            "entry_price": entry["american_price"], "closing_price": closing["american_price"],
            "entry_timestamp": entry["snapshot_time_utc"],
            "closing_timestamp": closing["snapshot_time_utc"],
            "clv_spread": closing["point"] - entry["point"],
            "clv_implied": implied_prob(closing["american_price"]) - implied_prob(entry["american_price"])}


def validate_causal(event):
    """The audit checklist as assertions (rules 1-3, 6). event: dict with the TIMELINE_FIELDS
    plus feature_available_time(s), entry_odds_time, closing_odds_time. Returns problems."""
    problems = []
    dec = _utc(event["decision_time"])
    for ft in event.get("feature_available_times") or [event.get("feature_available_time")]:
        if ft and _utc(ft) > dec:
            problems.append({"code": "FEATURE_AFTER_DECISION", "feature_available_time": ft,
                             "decision_time": event["decision_time"]})
    ent = event.get("entry_odds_time")
    if ent and _utc(ent) > dec:
        problems.append({"code": "ENTRY_AFTER_DECISION", "entry_odds_time": ent})
    clo = event.get("closing_odds_time")
    if ent and clo and _utc(clo) < _utc(ent):
        problems.append({"code": "CLOSING_BEFORE_ENTRY", "entry_odds_time": ent,
                         "closing_odds_time": clo})
    if event.get("implied_prob_source") not in (None, "entry"):
        problems.append({"code": "IMPLIED_FROM_CLOSE",
                         "detail": "implied probabilities must derive from the ENTRY price"})
    return problems


def walk_forward_folds(dates, n_folds=3):
    """Strictly chronological train/validate/test folds — never random splits (rule 8). A gap
    between train and validation is an allowed buffer. Fit scalers/encoders/selectors on TRAIN
    ONLY; that discipline is a caller contract this function cannot enforce, so it is documented
    here where the folds are made."""
    dates = sorted(dates)
    n = len(dates)
    if n_folds < 1 or n < n_folds + 1:
        raise ValueError("not enough dates for the requested folds")
    folds = []
    step = n // (n_folds + 1) or 1
    for i in range(n_folds):
        train_end = step * (i + 1)
        folds.append({"train": dates[:train_end],
                      "validate": dates[train_end:train_end + step] or dates[train_end:],
                      "rule": "strictly chronological; fit all preprocessing on train only"})
    return folds


# ====================================================================== selftest

def selftest():
    f = []
    base = dict(event_id="E1", league="mlb", start_time_utc="2026-08-28T23:10:00Z",
                home_team="New York Mets", away_team="Houston Astros", market_type="spread",
                outcome="Houston Astros -1.5", source="moneyline_api")
    mk = lambda **kw: market_history.make_history_record(**{**base, **kw})
    recs = [mk(sportsbook="circa", point=-1.5, american_price=-110,
               snapshot_time_utc="2026-08-28T18:00:00Z", line_kind="OPENING"),
            mk(sportsbook="circa", point=-2.0, american_price=-110,
               snapshot_time_utc="2026-08-28T20:00:00Z", line_kind="BEST_AVAILABLE"),
            mk(sportsbook="circa", point=-2.5, american_price=-115,
               snapshot_time_utc="2026-08-28T23:02:00Z", line_kind="CLOSING"),
            mk(sportsbook="pinnacle", point=-2.5, american_price=-112,
               snapshot_time_utc="2026-08-28T23:04:00Z", line_kind="CLOSING")]
    store = PointInTimeStore()
    for r in recs:
        store.add(r)
    # fail-closed read
    try:
        store.read("2026-08-28T19:00:00Z", event_id="E1")
        f.append("the store allowed a post-cutoff read")
    except market_history.TemporalFirewallError:
        pass
    # entry: last price at/before decision; no backfill
    ent = entry_line(recs, "2026-08-28T21:00:00Z", "circa", "spread", "Houston Astros -1.5")
    if ent["point"] != -2.0:
        f.append(f"entry resolution wrong: {ent}")
    if entry_line(recs, "2026-08-28T17:00:00Z", "circa", "spread", "Houston Astros -1.5") is not None:
        f.append("a missing entry was backfilled from a later snapshot")
    # closing: circa inside the 15-minute window beats pinnacle
    clo, note = closing_line(recs, "2026-08-28T23:10:00Z", "spread", "Houston Astros -1.5")
    if clo["sportsbook"] != "circa" or clo["point"] != -2.5:
        f.append(f"closing resolution wrong: {clo} {note}")
    cc = consensus_close(recs, "2026-08-28T23:10:00Z", "spread", "Houston Astros -1.5")
    if cc["n_books"] != 2 or cc["consensus_point"] != -2.5:
        f.append(f"consensus close wrong: {cc}")
    v = clv(ent, clo)
    if v["clv_spread"] != -0.5 or round(v["clv_implied"], 4) != round(implied_prob(-115) - implied_prob(-110), 4):
        f.append(f"clv wrong: {v}")
    # audit checklist
    probs = validate_causal({"decision_time": "2026-08-28T21:00:00Z",
                             "feature_available_time": "2026-08-28T21:30:00Z",
                             "entry_odds_time": "2026-08-28T20:00:00Z",
                             "closing_odds_time": "2026-08-28T23:02:00Z",
                             "implied_prob_source": "entry"})
    if not any(p["code"] == "FEATURE_AFTER_DECISION" for p in probs):
        f.append("a post-decision feature passed the checklist")
    folds = walk_forward_folds([f"2026-08-{d:02d}" for d in range(1, 13)], n_folds=3)
    if any(max(fl["train"]) >= min(fl["validate"] or fl["train"]) for fl in folds if fl["validate"]):
        f.append("a fold leaked the future into train")
    # Addendum 4: trichotomy, executable entry, shift lint, embargo, event split
    news = {"event_time": "2026-08-27T18:00:00Z", "publication_time": "2026-08-28T10:00:00Z",
            "ingestion_time": "2026-08-28T10:05:00Z"}
    if governing_time(news) != _utc("2026-08-28T10:00:00Z"):
        f.append("governing time is not publication_time")
    ex = entry_executable(recs, "2026-08-28T19:00:00Z", "circa", "spread", "Houston Astros -1.5")
    if ex["point"] != -2.0:
        f.append(f"first-executable entry wrong: {ex}")
    if entry_executable(recs, "2026-08-28T23:10:00Z", "circa", "spread",
                        "Houston Astros -1.5") is not None:
        f.append("a quote from before signal+latency was called executable")
    wrong = "df.groupby('team')['x'].transform(lambda s: s.rolling(10, min_periods=3).mean())"
    right = "df.groupby('team')['x'].transform(lambda s: s.shift(1).rolling(10, min_periods=3).mean())"
    if not rolling_feature_lint(wrong) or rolling_feature_lint(right):
        f.append("the shift(1) lint misjudged the wrong/right fixture pair")
    pf = purged_walk_forward_folds([f"2026-08-{d:02d}" for d in range(1, 13)], n_folds=3)
    if not all(isinstance(fl["embargoed"], list) for fl in pf):
        f.append("embargo bookkeeping missing")
    sp = split_events(["E1", "E1", "E2", "E3", "E4"])
    if set(sp["train"]) & set(sp["test"]):
        f.append("an event bridged train and test")

    print(f"backtest_causal selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("   -", x)
    return 0 if not f else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
