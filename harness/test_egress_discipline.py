#!/usr/bin/env python3
"""Regression: no module may reach the network by DEFAULT.

WHY THIS EXISTS. Three separate deliveries have now shipped a live outbound HTTP call as the
default path:

  1. acquisition_adapters, urlopen against statsapi.mlb.com  -- fixed, ALLOW_DIRECT_HTTP = False
  2. an MLB adapter revision, live urlopen                   -- caught in review, never merged
  3. the FU-1 feed layer, requests.get in feed_espn and feed_mlb_statsapi as the DEFAULT
     value of the injected `get` parameter -- fixed 2026-08-30

Each was dependency-injected and each had passing selftests, because every test injected a
stub. A test suite that only ever exercises the injected path proves nothing about the
default path, and the default path is the one production takes.

Per the falsification finding of 2026-08-30, these are NOT one defect with one fix; they are
independent bugs sharing a shape. What a shared CHECK can do is stop the shape from shipping
again, which is all this file claims to do.
"""

MODULE_ID = "test_egress_discipline"
import importlib, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: modules whose fetch entry points must refuse when nothing is injected
GUARDED = {
    "acquisition_adapters": ["_default_http_get"],
    "feed_espn": ["_default_get"],
    "feed_mlb_statsapi": ["_default_get"],
}

#: modules that reach the network ONLY behind an explicit deployment secret. A missing key is
#: an acceptable gate, but it must raise rather than fall through to a live call.
KEY_GATED = {
    "market_sportsgameodds": ("fetch_events", "StubModeNoKey"),
    "market_theoddsapi": ("fetch_odds", "StubModeNoKey"),
}


def selftest():
    f = []

    for mod, fns in sorted(GUARDED.items()):
        m = importlib.import_module(mod)
        flag = getattr(m, "ALLOW_DIRECT_HTTP", None)
        if flag is not True and flag is not False:
            f.append(f"{mod}: no ALLOW_DIRECT_HTTP flag — nothing declares the posture")
            continue
        if flag:
            f.append(f"{mod}: ALLOW_DIRECT_HTTP is True; this deployment forbids direct HTTP")
        for fn in fns:
            try:
                getattr(m, fn)("https://example.invalid/should-never-be-fetched")
                f.append(f"{mod}.{fn}: DID NOT REFUSE — it attempted a live fetch")
            except Exception as e:
                if type(e).__name__ != "AcquisitionDisabled":
                    f.append(f"{mod}.{fn}: raised {type(e).__name__}, not AcquisitionDisabled "
                             f"({str(e)[:80]}) — a network error is not a refusal")

    for mod, (fn, exc) in sorted(KEY_GATED.items()):
        m = importlib.import_module(mod)
        if m.have_key():
            continue                      # a key IS configured; the gate is not under test here
        try:
            getattr(m, fn)()
            f.append(f"{mod}.{fn}: returned with no API key — a stub must never fabricate")
        except Exception as e:
            if type(e).__name__ != exc:
                f.append(f"{mod}.{fn}: raised {type(e).__name__}, expected {exc}")

    # A mutant proves the check can fail. Without this, a check that always passes reads
    # exactly like a check that works -- the 8/27 lesson about counters that cannot fail.
    m = importlib.import_module("feed_espn")
    saved = m.ALLOW_DIRECT_HTTP
    try:
        m.ALLOW_DIRECT_HTTP = True
        caught = False
        try:
            selftest_inner = getattr(m, "_default_get")
            selftest_inner("https://example.invalid/x")
        except Exception as e:
            caught = type(e).__name__ != "AcquisitionDisabled"
        if not caught:
            f.append("MUTANT SURVIVED: flipping ALLOW_DIRECT_HTTP to True still refused, so the "
                     "flag is not what gates the fetch and this check proves nothing")
    finally:
        m.ALLOW_DIRECT_HTTP = saved

    for x in f:
        print("  FAIL:", x)
    print(f"test_egress_discipline selftest: {'OK' if not f else 'FAIL'}")
    return not f


if __name__ == "__main__":
    sys.exit(0 if selftest() else 1)
