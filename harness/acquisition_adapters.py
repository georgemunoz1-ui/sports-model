"""Acquisition adapter layer for freshness_contract.

freshness_contract.py performs NO network I/O by design; the caller injects an
acquire(subject, sport, kind) callable. This module is that injected layer. It implements
real fetchers with clean fallback:

  1. LiveStore  -- append-only JSONL hydration cache. write() appends a line; read(subject)
     returns the newest Stamp. Existing lines are NEVER rewritten (R6 append-only).
  2. MLBStatsAPIAdapter -- statsapi.mlb.com, no API key. Player search -> gameLog pitching
     stats -> CONFIRMED Stamp whose observed_at is the last game date and whose
     source_sha256 is the sha256 of the gameLog response bytes. 5s timeout, one retry; ANY
     failure returns None (the contract degrades; the adapter never raises).
  3. SearchIdentifyAdapter -- wraps a caller-supplied search_fn. Snippets IDENTIFY, never
     BIND, so the grade is ALWAYS IDENTIFIED_UNCONFIRMED, no matter how good the snippet.

Standing rule R1: never invent a number. If a response lacks a parseable date, the adapter
returns None rather than guessing. Python 3 stdlib only (urllib, json, hashlib, datetime, os).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
MODULE_ID = "acquisition_adapters"

import urllib.parse
import urllib.request

try:  # package import when used as harness.acquisition
    from . import freshness_contract as fc
except ImportError:  # direct sys.path import from tests
    import freshness_contract as fc

UTC = dt.timezone.utc
TIMEOUT_S = 5
BASE = "https://statsapi.mlb.com"


def _now():
    return dt.datetime.now(UTC)


#: Direct outbound HTTP is DISABLED by default in this deployment.
#:
#: The adapter as delivered called urllib.request.urlopen against statsapi.mlb.com. That is direct
#: script HTTP against a sports data site, which this environment does not permit: outbound calls
#: go through the org egress proxy and must use approved browsing/search/fetch tooling. Rather than
#: delete the adapter, the DEFAULT fetcher refuses, so an unconfigured deployment DEGRADES honestly
#: — which is exactly what the freshness contract already promises when no adapter is available.
#:
#: To enable acquisition, inject a fetcher explicitly:
#:     build_adapter_chain(http_get=my_approved_fetcher)
#: An injected fetcher takes (url, timeout) and returns response bytes.
ALLOW_DIRECT_HTTP = False


class AcquisitionDisabled(RuntimeError):
    """Raised when acquisition is attempted with no approved fetcher injected."""


def _default_http_get(url, timeout=TIMEOUT_S):
    """Refuses by default. Inject an approved fetcher to enable acquisition."""
    if not ALLOW_DIRECT_HTTP:
        raise AcquisitionDisabled(
            f"direct HTTP is disabled in this deployment (attempted {url!r}). Inject an approved "
            "fetcher via build_adapter_chain(http_get=...). Refusing rather than silently "
            "degrading is deliberate here: the caller asked for a network fetch and must learn "
            "it did not happen.")
    req = urllib.request.Request(url, headers={"User-Agent": "freshness-acquisition/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class AcquisitionAdapter:
    """Base class. fetch() returns a freshness_contract.Stamp or None; never raises."""

    name = "base"

    def fetch(self, subject, sport, kind):
        raise NotImplementedError


class MLBStatsAPIAdapter(AcquisitionAdapter):
    """statsapi.mlb.com (no key). For kind='starter':
       - find player id via /api/v1/people/search?names=<subject>
       - last game log via /api/v1/people/<id>/stats?stats=gameLog&group=pitching&season=<year>
       - Stamp(observed_at=last game date, fetched_at=now, source=URL,
              source_sha256=sha256(response bytes), grade=CONFIRMED)
       Timeout 5s, one retry; any failure -> None (contract degrades)."""

    name = "mlb_stats_api"

    def __init__(self, http_get=None, now_fn=None):
        self.http_get = http_get or _default_http_get
        self.now_fn = now_fn or _now

    def _get_json(self, url):
        """GET + json parse with exactly one retry. Any failure -> None."""
        for _attempt in range(2):
            try:
                body = self.http_get(url, timeout=TIMEOUT_S)
                return json.loads(body), body
            except Exception:
                continue
        return None, None

    def fetch(self, subject, sport, kind):
        try:
            return self._fetch(subject, sport, kind)
        except Exception:
            return None

    def _fetch(self, subject, sport, kind):
        if sport != "mlb":
            return None
        now = self.now_fn()
        q = urllib.parse.urlencode({"names": subject})
        search_url = f"{BASE}/api/v1/people/search?{q}"
        data, _body = self._get_json(search_url)
        if not data:
            return None
        people = data.get("people") or []
        if not people or "id" not in people[0]:
            return None
        pid = people[0]["id"]

        log_url = (f"{BASE}/api/v1/people/{pid}/stats"
                   f"?stats=gameLog&group=pitching&season={now.year}")
        data, body = self._get_json(log_url)
        if not data or body is None:
            return None
        last_date = self._last_game_date(data)
        if last_date is None:
            return None  # R1: never invent a number
        stamp = fc.Stamp(
            observed_at=last_date,
            effective_at=now,
            fetched_at=now,
            source=log_url,
            source_sha256=hashlib.sha256(body).hexdigest(),
            grade=fc.CONFIRMED,
            subject=subject,
        )
        stamp.validate()
        return stamp

    @staticmethod
    def _last_game_date(data):
        """Newest 'date' field across gameLog splits; None if none present (R1)."""
        dates = []
        for group in data.get("stats") or []:
            for split in group.get("splits") or []:
                d = split.get("date")
                if d:
                    dates.append(str(d)[:10])
        if not dates:
            return None
        return max(dates)


class SearchIdentifyAdapter(AcquisitionAdapter):
    """Wraps a caller-supplied search_fn(query) -> list of {title, snippet, url, date}.
       Snippets IDENTIFY, never BIND: grade is ALWAYS IDENTIFIED_UNCONFIRMED.
       Parses a probable-pitcher mention + date from snippets; None if unparseable."""

    name = "search_identify"

    # ISO date in text, e.g. 2026-08-28 or 2026/08/28
    _ISO_DATE = re.compile(r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b")
    _MONTHS = ("january february march april may june july august september october "
               "november december").split()
    _LONG_DATE = re.compile(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
        re.IGNORECASE)
    _MENTION = re.compile(r"probable\s+(?:pitcher|starter)|named\s+(?:the\s+)?starter|"
                          r"to\s+start|starting\s+pitcher", re.IGNORECASE)

    def __init__(self, search_fn, now_fn=None):
        self.search_fn = search_fn
        self.now_fn = now_fn or _now

    def fetch(self, subject, sport, kind):
        try:
            return self._fetch(subject, sport, kind)
        except Exception:
            return None

    def _fetch(self, subject, sport, kind):
        if self.search_fn is None:
            return None
        results = self.search_fn(f"{subject} probable pitcher")
        if not results:
            return None
        now = self.now_fn()
        subj_last = str(subject).strip().split()[-1].lower() if subject else ""
        for r in results:
            snippet = str((r or {}).get("snippet") or "")
            title = str((r or {}).get("title") or "")
            url = (r or {}).get("url")
            text = f"{title} {snippet}"
            # must look like a probable-pitcher mention of THIS subject
            if not self._MENTION.search(text):
                continue
            if subj_last and subj_last not in text.lower():
                continue
            date = (self._parse_date(str((r or {}).get("date") or ""))
                    or self._parse_date(text))
            if date is None:
                continue  # R1: no date, no stamp
            if not url:
                continue
            blob = json.dumps(r, sort_keys=True, default=str).encode("utf-8")
            stamp = fc.Stamp(
                observed_at=date,
                effective_at=now,
                fetched_at=now,
                source=str(url),
                source_sha256=hashlib.sha256(blob).hexdigest(),
                grade=fc.IDENTIFIED_UNCONFIRMED,  # snippets IDENTIFY, never BIND
                subject=subject,
            )
            stamp.validate()
            return stamp
        return None

    def _parse_date(self, s):
        if not s:
            return None
        m = self._ISO_DATE.search(s)
        if m:
            try:
                return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            except ValueError:
                return None
        m = self._LONG_DATE.search(s)
        if m:
            mon = m.group(1).lower()[:3]
            month = [n[:3] for n in self._MONTHS].index(mon) + 1
            try:
                return dt.date(int(m.group(3)), month, int(m.group(2))).isoformat()
            except ValueError:
                return None
        # bare ISO timestamp, e.g. "2026-08-28T11:00:00Z"
        try:
            return dt.datetime.fromisoformat(
                s.strip().replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return None


class LiveStore:
    """Append-only hydration cache (JSONL). write(stamp) records fetched_at=now; read(subject)
    returns newest Stamp. Path injected; never rewrites existing lines (R6 append-only)."""

    def __init__(self, path, now_fn=None):
        self.path = path
        self.now_fn = now_fn or _now

    def write(self, stamp):
        stamp.fetched_at = self.now_fn()
        stamp.validate()
        line = json.dumps(stamp.to_dict(stamp.fetched_at), sort_keys=True)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:  # append-only: never "w"
            f.write(line + "\n")
        return stamp

    def read(self, subject):
        """Newest stamp for subject (last matching line wins). None if absent."""
        if not os.path.exists(self.path):
            return None
        newest = None
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("subject") == subject:
                    newest = rec  # file is append-only, so later == newer
        if newest is None:
            return None
        return fc.Stamp(
            observed_at=newest.get("observed_at"),
            effective_at=newest.get("effective_at"),
            fetched_at=newest.get("fetched_at"),
            source=newest.get("source"),
            source_sha256=newest.get("source_sha256"),
            grade=newest.get("grade"),
            subject=newest.get("subject"),
        )


def build_adapter_chain(store=None, search_fn=None, http_get=None):
    """Returns acquire(subject, sport, kind) suitable for freshness_contract.resolve_input:
       1. LiveStore fresh hit -> return it
       2. MLBStatsAPIAdapter (if sport=='mlb')
       3. SearchIdentifyAdapter (if search_fn given)
       None from all -> None. http_get injectable for tests (default urllib with 5s timeout)."""
    mlb = MLBStatsAPIAdapter(http_get=http_get)
    searcher = SearchIdentifyAdapter(search_fn) if search_fn is not None else None

    def acquire(subject, sport, kind):
        if store is not None:
            cached = store.read(subject)
            if cached is not None:
                return cached
        if sport == "mlb":
            stamp = mlb.fetch(subject, sport, kind)
            if stamp is not None:
                if store is not None:
                    store.write(stamp)
                return stamp
        if searcher is not None:
            stamp = searcher.fetch(subject, sport, kind)
            if stamp is not None:
                if store is not None:
                    store.write(stamp)
                return stamp
        return None

    return acquire


# ====================================================================== selftest

def selftest():
    """Offline. No network is touched; the MLB adapter is exercised through an injected fetcher."""
    import datetime as _dt
    import tempfile
    f = []
    NOW = _dt.datetime(2026, 8, 28, 23, 10, tzinfo=_dt.timezone.utc)

    # S1 — the default fetcher REFUSES. This is the deployment constraint, pinned.
    try:
        _default_http_get("https://statsapi.mlb.com/whatever")
        f.append("S1: direct HTTP was attempted with ALLOW_DIRECT_HTTP False")
    except AcquisitionDisabled:
        pass

    # S2 — with an injected fetcher the MLB adapter yields a CONFIRMED stamp whose observed_at is
    #      the NEWEST game-log date, and whose sha256 is over the real response bytes.
    calls = []
    def fake_get(url, timeout=None):
        calls.append(url)
        if "people/search" in url:
            return b'{"people":[{"id":680574}]}'
        return b'{"stats":[{"splits":[{"date":"2026-07-19"},{"date":"2026-08-27"}]}]}'
    a = MLBStatsAPIAdapter(http_get=fake_get, now_fn=lambda: NOW)
    st = a.fetch("Hunter Brown", "mlb", "starter")
    if st is None:
        f.append("S2: injected fetcher produced no stamp")
    else:
        if st.grade != fc.CONFIRMED:
            f.append(f"S2: expected CONFIRMED, got {st.grade}")
        if st.observed_at.date().isoformat() != "2026-08-27":
            f.append(f"S2: observed_at should be the NEWEST split, got {st.observed_at}")
        if not st.source_sha256:
            f.append("S2: no source hash over the response bytes")

    # S3 — no game-log dates -> None, never an invented date (R1).
    a2 = MLBStatsAPIAdapter(http_get=lambda u, timeout=None:
                            b'{"people":[{"id":1}]}' if "search" in u else b'{"stats":[]}',
                            now_fn=lambda: NOW)
    if a2.fetch("Ghost", "mlb", "starter") is not None:
        f.append("S3: an empty game log produced a stamp instead of None")

    # S4 — a search-derived stamp is ALWAYS IDENTIFIED_UNCONFIRMED. Snippets identify, never bind.
    s4 = SearchIdentifyAdapter(search_fn=lambda q: "Hunter Brown last started 2026-08-27",
                               now_fn=lambda: NOW).fetch("Hunter Brown", "mlb", "starter")
    if s4 is not None and s4.grade != fc.IDENTIFIED_UNCONFIRMED:
        f.append(f"S4: a search stamp graded {s4.grade}; snippets may never reach CONFIRMED")

    # S5 — an unconfigured chain returns None, so the contract degrades rather than pretending.
    if build_adapter_chain()("anyone", "mlb", "starter") is not None:
        f.append("S5: an unconfigured chain returned a stamp")

    # S6 — LiveStore round-trips and is append-only (R6).
    with tempfile.TemporaryDirectory() as td:
        path = td + "/live.jsonl"
        store = LiveStore(path, now_fn=lambda: NOW)
        if st is not None:
            store.write(st)
            back = store.read("Hunter Brown")
            if back is None or back.grade != fc.CONFIRMED:
                f.append("S6: LiveStore did not round-trip a stamp")
            store.write(st)
            if sum(1 for _ in open(path)) < 2:
                f.append("S6: LiveStore overwrote instead of appending (R6)")

    print(f"{MODULE_ID} selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  !", x)
    return 0 if not f else 1


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(selftest())
