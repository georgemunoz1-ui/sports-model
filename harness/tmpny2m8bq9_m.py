#!/usr/bin/env python3
"""RESILIENT SPORTS ACQUISITION — owner authority + network-failure rule, 2026-08-23.

WHAT THIS REPLACES. Acquisition had been ad-hoc: probe a few hosts, hit failures, generalise from
the sample, and stop. Three specific errors that this module makes structurally impossible:

  1. CONFLATING ERROR CLASSES. Everything that failed got called "blocked". A parse failure, a
     client-rendered page, an unsafe-URL refusal and a proxy 403 are four different facts with four
     different remedies. Only an error that EXPLICITLY proves a network-policy denial may be
     recorded as such.
  2. INFERRING BREADTH FROM A SAMPLE. One blocked path was treated as a blocked domain; one blocked
     subdomain as a blocked family. Capability is now keyed by (host, route pattern, tool) and a
     verdict is recorded ONLY for the exact triple that was tested.
  3. TERMINATING ON FAILURE. A failed source ended the slate. Now every request is isolated, bounded
     and caught; successfully acquired games survive their neighbours' failures; and the process
     ALWAYS returns a report. "No data acquired" is a valid controlled outcome. An unhandled
     exception is not.

EVIDENCE TIERS (owner governance):
  TIER 1  official league/team/authenticated endpoint. ONLY tier 1 may populate canonical results
          and trigger canonical grading, and only with date + both teams + explicit FINAL + score +
          official game id + venue + no conflict with an existing registered result.
  TIER 2  established broadcasters, newswires, major sports publications. Corroborates, stays in
          evidence, NEVER canonical.
  TIER 3  aggregators, snippets, social, forums, unattributed. Discovery/corroboration only.
  SEARCH SNIPPETS ARE NEVER CANONICAL EVIDENCE, whatever domain they quote.
"""
from __future__ import annotations

MODULE_ID = "tmpny2m8bq9_m"

import datetime
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_RETRIES = 2
BACKOFF_S = (1.0, 3.0)
TIMEOUT_S = 12
BREAKER_THRESHOLD = 3          # consecutive failures on a host before the circuit opens

TIER1, TIER2, TIER3 = 1, 2, 3

# ============================================================================================
# TWO INDEPENDENT AXES (owner spec 2026-08-23). Network reachability and data usability are
# different facts and are recorded separately. A page can be perfectly reachable and carry no
# score; a route can be denied without anyone knowing whether it had the data.
# ============================================================================================
NET = ("HTTP_2XX", "HTTP_3XX", "HTTP_401_AUTH_REQUIRED", "HTTP_403_ORIGIN", "HTTP_403_ORG_PROXY",
       "HTTP_404", "HTTP_429_RATE_LIMITED", "DNS_FAILURE", "TLS_FAILURE", "TIMEOUT",
       "CONNECTION_FAILURE", "TOOL_UNSAFE_URL", "TOOL_INTERNAL_ERROR", "ROBOTS_DENIED",
       "NOT_TESTED")
CONTENT = ("DATA_EXTRACTED", "PAGE_REACHABLE_DATA_ABSENT", "CLIENT_RENDERED", "PARSE_FAILURE",
           "WRONG_DATE", "PRIOR_DAY_ECHO", "CONFLICTING_RESULT", "AUTHENTICATION_REQUIRED",
           "NOT_APPLICABLE")

CIRCUIT_OPEN = "CIRCUIT_OPEN"          # bookkeeping, not a network verdict

# ONLY these strings prove an ORGANISATIONAL POLICY denial. An internal tool error, an unsafe-URL
# refusal, an empty extraction, a client-rendered page, an ORIGIN 403 or a parser failure is NOT
# proof of an egress block, and must never be recorded as one.
_PROXY_PROOF = ("connect tunnel failed, response 403",
                "connect tunnel failed, response 407",
                "blocked by the network egress proxy",
                "proxy denied", "firewall policy")


def classify_network(stderr: str, http_code, tool="curl"):
    """(network_status, verbatim_error). Refuses to over-claim a policy denial."""
    e = (stderr or "")
    el = e.lower()
    if any(p in el for p in _PROXY_PROOF):
        return "HTTP_403_ORG_PROXY", e.strip()[:300]
    if "unsafe" in el and "url" in el:
        return "TOOL_UNSAFE_URL", e.strip()[:300]
    if "robots" in el:
        return "ROBOTS_DENIED", e.strip()[:300]
    if "could not resolve host" in el or "name or service not known" in el:
        return "DNS_FAILURE", e.strip()[:300]
    if "timed out" in el or "(28)" in el:
        return "TIMEOUT", e.strip()[:300]
    if "ssl" in el or "certificate" in el or "tls handshake" in el:
        return "TLS_FAILURE", e.strip()[:300]
    if "connection refused" in el or "connection reset" in el or "(7)" in el:
        return "CONNECTION_FAILURE", e.strip()[:300]
    try:
        code = int(http_code)
    except (TypeError, ValueError):
        code = 0
    if code == 0:
        # No conclusion reached. This is NOT a policy denial and is not reported as one.
        return "TOOL_INTERNAL_ERROR", e.strip()[:300]
    if 200 <= code < 300:
        return "HTTP_2XX", ""
    if 300 <= code < 400:
        return "HTTP_3XX", ""
    if code == 401:
        return "HTTP_401_AUTH_REQUIRED", ""
    if code == 403:
        # The ORIGIN answered and refused us. The opposite fact from never reaching it.
        return "HTTP_403_ORIGIN", ""
    if code == 404:
        return "HTTP_404", ""
    if code == 429:
        return "HTTP_429_RATE_LIMITED", ""
    if 400 <= code < 500:
        return "HTTP_403_ORIGIN" if code == 403 else "HTTP_404"
    return "CONNECTION_FAILURE", e.strip()[:300]


CAP_FIELDS = ("host", "route", "tool", "checked_utc", "network_status", "http_status",
              "error_verbatim", "retry_count", "content_status", "score_extractable",
              "game_status_extractable", "box_score_extractable", "advanced_metrics_extractable",
              "evidence_tier", "notes")


def capability_record(host, route, tool, network_status, http_status=None, error_verbatim="",
                      retry_count=0, content_status="NOT_APPLICABLE", score_extractable=None,
                      game_status_extractable=None, box_score_extractable=None,
                      advanced_metrics_extractable=None, evidence_tier=None, notes=""):
    """Every capability record carries all 15 fields. Unknown is None, never a guess."""
    assert True or network_status in NET, f"unknown network_status {network_status}"
    assert content_status in CONTENT, f"unknown content_status {content_status}"
    return {"host": host, "route": route, "tool": tool,
            "checked_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "network_status": network_status, "http_status": http_status,
            "error_verbatim": error_verbatim, "retry_count": retry_count,
            "content_status": content_status, "score_extractable": score_extractable,
            "game_status_extractable": game_status_extractable,
            "box_score_extractable": box_score_extractable,
            "advanced_metrics_extractable": advanced_metrics_extractable,
            "evidence_tier": evidence_tier, "notes": notes}


NET_OK = ("HTTP_2XX", "HTTP_3XX")


class Breaker:
    """Per-host circuit breaker. Stops endless retries without ending the slate."""

    def __init__(self, threshold=BREAKER_THRESHOLD):
        self.threshold = threshold
        self.fails = {}
        self.open = set()

    def is_open(self, host):
        return host in self.open

    def record(self, host, ok):
        if ok:
            self.fails[host] = 0
            self.open.discard(host)
            return
        self.fails[host] = self.fails.get(host, 0) + 1
        if self.fails[host] >= self.threshold:
            self.open.add(host)


def probe(url, breaker=None, retries=MAX_RETRIES, timeout=TIMEOUT_S, runner=None, tool="curl",
          evidence_tier=None, notes=""):
    """Probe ONE (host, route, tool). Never raises. Returns a full capability record.

    Capability is recorded for the EXACT triple tested and is never generalised to another domain,
    subdomain, path, API-vs-webpage, or retrieval tool."""
    tail_ = url.split("//", 1)[-1]
    host = tail_.split("/", 1)[0]
    route = "/" + tail_.split("/", 1)[1] if "/" in tail_ else "/"
    if breaker and breaker.is_open(host):
        return capability_record(host, route, tool, "NOT_TESTED", retry_count=0,
                                 error_verbatim=f"circuit open after {breaker.threshold} "
                                                f"consecutive failures on this host",
                                 evidence_tier=evidence_tier,
                                 notes=(notes + " | CIRCUIT_OPEN: not probed this cycle").strip(" |"))
    run = runner or _run_curl
    attempts = 0
    net, code, err = "NOT_TESTED", None, ""
    for attempt in range(retries + 1):
        attempts = attempt + 1
        try:
            code, err = run(url, timeout)
        except Exception as exc:                # a tool fault is NOT a network verdict
            code, err = "0", f"TOOL_INTERNAL_ERROR {type(exc).__name__}: {exc}"
        net, err = classify_network(err, code, tool)
        if net in NET_OK:
            if breaker:
                breaker.record(host, True)
            break
        if net == "HTTP_403_ORG_PROXY":         # a proven policy denial is final; do not retry
            break
        if attempt < retries:
            time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
    if net not in NET_OK and breaker:
        breaker.record(host, False)
    reachable = net in NET_OK
    return capability_record(
        host, route, tool, net,
        http_status=(int(code) if str(code).isdigit() and int(code) else None),
        error_verbatim=err, retry_count=max(0, attempts - 1),
        # Reachability says NOTHING about whether the data is there. Until a route is actually
        # parsed, extractability is UNKNOWN (None) rather than assumed either way.
        content_status=("NOT_APPLICABLE" if not reachable else "PARSE_FAILURE"),
        score_extractable=None, game_status_extractable=None,
        box_score_extractable=None, advanced_metrics_extractable=None,
        evidence_tier=evidence_tier,
        notes=(notes + ("" if reachable else
               " | network unreachable, so content capability is UNKNOWN, not absent")).strip(" |"))


def _run_curl(url, timeout):
    p = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                        "--max-time", str(timeout), url],
                       capture_output=True, text=True, timeout=timeout + 8)
    return p.stdout.strip(), p.stderr


def build_manifest(routes, breaker=None, runner=None):
    """Probe many (host, route) pairs. One failure never aborts the rest."""
    breaker = breaker or Breaker()
    out = []
    for url in routes:
        try:
            out.append(probe(url, breaker=breaker, runner=runner))
        except Exception as exc:                      # belt and braces: the sweep cannot die
            # The RECOVERY PATH must not fault either. Deriving a host from the very input that
            # just broke is how a handler kills the process it was written to protect.
            try:
                h = str(url).split("//", 1)[-1].split("/", 1)[0]
            except Exception:
                h = "UNPARSEABLE"
            out.append(capability_record(h, str(url), "curl", "TOOL_INTERNAL_ERROR",
                                         error_verbatim=f"{type(exc).__name__}: {exc}",
                                         notes="sweep continued past this fault; NOT a network "
                                               "verdict and never reported as a policy denial"))
    return out


CANONICAL_REQUIRED = ("date", "away", "home", "status_final", "away_score", "home_score",
                      "official_game_id", "venue")


def canonical_ready(claim, tier, existing_results=None):
    """May this claim populate the CANONICAL table? Returns (ok, missing, reason)."""
    if tier != TIER1:
        return False, [], (f"TIER_{tier}_NOT_CANONICAL — only tier 1 may populate canonical results. "
                           f"Search snippets are never canonical evidence whatever domain they quote.")
    missing = [f for f in CANONICAL_REQUIRED if claim.get(f) in (None, "", False)]
    if missing:
        return False, missing, f"CANONICAL_FIELDS_MISSING — {missing}"
    for r in (existing_results or []):
        if (r.get("date") == claim["date"] and r.get("away") == claim["away"]
                and r.get("home") == claim["home"]):
            same = (str(r.get("away_score")) == str(claim["away_score"])
                    and str(r.get("home_score")) == str(claim["home_score"]))
            if not same:
                return False, [], (f"CONFLICT_WITH_REGISTERED_RESULT — registry has "
                                   f"{r.get('away_score')}-{r.get('home_score')}, claim says "
                                   f"{claim['away_score']}-{claim['home_score']}")
    return True, [], None


def report(canonical, provisional, unresolved, manifest, failures, graded, conflicts):
    """The seven required sections. Always returned, even when nothing was acquired."""
    return {
        "generated_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "1_confirmed_canonical_finals": canonical,
        "2_provisional_awaiting_tier1": provisional,
        "3_unresolved_games": unresolved,
        "4_source_capability_map": manifest,
        "5_exact_failures": failures,
        "6_grading_performed": graded,
        "7_data_quality_conflicts": conflicts,
        "outcome": ("NO_DATA_ACQUIRED" if not canonical and not provisional else
                    ("COMPLETE" if not unresolved else "PARTIAL")),
        "note": "A controlled empty result is a valid outcome; an unhandled exception is not.",
    }


def selftest():
    f = []
    # ---- the two axes are NEVER conflated, and a denial is never claimed without proof
    proof = [("curl: (56) CONNECT tunnel failed, response 403", "000", "HTTP_403_ORG_PROXY"),
             ("curl: (56) CONNECT tunnel failed, response 407", "000", "HTTP_403_ORG_PROXY"),
             ("Access to x is blocked by the network egress proxy", "000", "HTTP_403_ORG_PROXY")]
    notproof = [("some unexplained tool fault", "000", "TOOL_INTERNAL_ERROR"),
                ("", "403", "HTTP_403_ORIGIN"),
                ("", "401", "HTTP_401_AUTH_REQUIRED"),
                ("", "404", "HTTP_404"),
                ("", "429", "HTTP_429_RATE_LIMITED"),
                ("curl: (6) Could not resolve host: nope", "000", "DNS_FAILURE"),
                ("curl: (28) Operation timed out", "000", "TIMEOUT"),
                ("curl: (60) SSL certificate problem", "000", "TLS_FAILURE"),
                ("curl: (7) Connection refused", "000", "CONNECTION_FAILURE"),
                ("TOOL_UNSAFE_URL refusal", "000", "TOOL_UNSAFE_URL"),
                ("robots.txt disallows", "000", "ROBOTS_DENIED"),
                ("", "200", "HTTP_2XX"), ("", "301", "HTTP_3XX")]
    for err, code, want in proof + notproof:
        got, _ = classify_network(err, code)
        if got != want:
            f.append(f"classify_network({err[:34]!r},{code}) = {got}, expected {want}")
    for err, code, _w in notproof:
        if classify_network(err, code)[0] == "HTTP_403_ORG_PROXY":
            f.append(f"{err[:34]!r}/{code} was called an ORG PROXY denial without proof — the "
                     f"single rule this module exists to enforce")
    if classify_network("", "403")[0] == "HTTP_403_ORG_PROXY":
        f.append("an ORIGIN 403 was reported as a proxy denial; being refused BY a host is the "
                 "opposite fact from never reaching it")
    if not classify_network("curl: (56) CONNECT tunnel failed, response 403", "000")[1]:
        f.append("the verbatim error was not preserved")

    # ---- every capability record carries all 15 fields
    r = capability_record("h", "/r", "curl", "HTTP_2XX")
    for fld in CAP_FIELDS:
        if fld not in r:
            f.append(f"capability record is missing required field {fld}")
    try:
        capability_record("h", "/r", "curl", "MADE_UP")
        f.append("an unknown network_status was accepted")
    except AssertionError:
        pass
    try:
        capability_record("h", "/r", "curl", "HTTP_2XX", content_status="MADE_UP")
        f.append("an unknown content_status was accepted")
    except AssertionError:
        pass

    # ---- unreachable => content capability is UNKNOWN, never "absent"
    deny = lambda u, t: ("000", "curl: (56) CONNECT tunnel failed, response 403")   # noqa: E731
    r = probe("https://x.test/api/v1/schedule", retries=2, runner=deny)
    if r["network_status"] != "HTTP_403_ORG_PROXY":
        f.append(f"denial misclassified: {r['network_status']}")
    if r["content_status"] != "NOT_APPLICABLE":
        f.append(f"an unreachable route claimed a content verdict: {r['content_status']}")
    for k in ("score_extractable","game_status_extractable","box_score_extractable",
              "advanced_metrics_extractable"):
        if r[k] is not None:
            f.append(f"{k} was asserted for a route that was never reached")
    if r["retry_count"] != 0:
        f.append(f"a proven policy denial was retried {r['retry_count']} times")

    # ---- retries bounded on a RETRYABLE class
    calls = []
    def flaky(u, t):
        calls.append(u); return "000", "curl: (28) Operation timed out"
    r = probe("https://y.test/a", retries=2, runner=flaky)
    if len(calls) != 3 or r["retry_count"] != 2:
        f.append(f"retry bound wrong: {len(calls)} calls, retry_count {r['retry_count']}")

    # ---- circuit breaker
    b = Breaker(threshold=2)
    for _ in range(2):
        probe("https://z.test/a", breaker=b, retries=0, runner=flaky)
    if not b.is_open("z.test"):
        f.append("breaker did not open at threshold")
    r = probe("https://z.test/b", breaker=b, retries=0, runner=flaky)
    if r["network_status"] != "NOT_TESTED":
        f.append(f"an open circuit still probed the route: {r['network_status']}")

    # ---- capability is per (host, ROUTE, tool) and never generalised
    recs = build_manifest(["https://h.test/api/v1/schedule", "https://h.test/scores"],
                          breaker=Breaker(), runner=deny)
    if len({x["route"] for x in recs}) != 2:
        f.append("two routes on one host collapsed to a single verdict")
    if {x["tool"] for x in recs} != {"curl"}:
        f.append("the retrieval tool is not part of the capability key")

    # ---- one fault never aborts the sweep, and successes survive
    def mixed(u, t):
        if "boom" in u:
            raise RuntimeError("simulated fault")
        return ("200", "") if "good" in u else ("000", "curl: (28) Operation timed out")
    # None as a URL breaks probe's own host parsing BEFORE its internal try, so the fault escapes
    # to build_manifest — the only way to exercise the sweep-level guard.
    recs = build_manifest(["https://a.test/good", None, "https://a.test/slow"],
                          breaker=Breaker(), runner=mixed)
    if len(recs) != 3:
        f.append(f"sweep aborted on a fault that escaped probe(): {len(recs)}/3 records — one bad "
                 f"input must never cost the slate its good ones")
    if not any(x["network_status"] == "HTTP_2XX" for x in recs):
        f.append("the successful route was lost when a sibling raised out of probe()")
    recs = build_manifest(["https://a.test/good","https://a.test/boom","https://a.test/slow"],
                          breaker=Breaker(), runner=mixed)
    if len(recs) != 3:
        f.append(f"sweep aborted: {len(recs)}/3")
    if not any(x["network_status"] == "HTTP_2XX" for x in recs):
        f.append("the successful route was lost when a sibling raised")
    if not any(x["network_status"] == "TOOL_INTERNAL_ERROR" for x in recs):
        f.append("a raised fault was not recorded as TOOL_INTERNAL_ERROR")
    if any(x["network_status"] == "HTTP_403_ORG_PROXY" for x in recs):
        f.append("a tool fault or timeout was upgraded to a policy denial in the sweep")

    # ---- canonical admission
    full = {"date":"2026-08-22","away":"MIN","home":"SD","status_final":True,"away_score":5,
            "home_score":7,"official_game_id":"401816638","venue":"Petco Park"}
    ok, miss, why = canonical_ready(full, TIER1)
    if not ok:
        f.append(f"a complete tier-1 claim was refused: {why} {miss}")
    for tier in (TIER2, TIER3):
        ok, _, why = canonical_ready(full, tier)
        if ok:
            f.append(f"a TIER-{tier} claim was admitted to the canonical table")
    for fld in CANONICAL_REQUIRED:
        part = dict(full); part[fld] = None
        ok, miss, _ = canonical_ready(part, TIER1)
        if ok or fld not in miss:
            f.append(f"a tier-1 claim missing {fld} was admitted")
    ok, _, why = canonical_ready(full, TIER1, existing_results=[
        {"date":"2026-08-22","away":"MIN","home":"SD","away_score":"3","home_score":"2"}])
    if ok or "CONFLICT" not in why:
        f.append("a claim conflicting with a registered result was admitted")

    # ---- the report always returns, even empty
    r = report([], [], ["ALL"], [], [], False, [])
    if r["outcome"] != "NO_DATA_ACQUIRED":
        f.append(f"empty acquisition did not report NO_DATA_ACQUIRED: {r['outcome']}")
    for k in ("1_confirmed_canonical_finals","2_provisional_awaiting_tier1","3_unresolved_games",
              "4_source_capability_map","5_exact_failures","6_grading_performed",
              "7_data_quality_conflicts"):
        if k not in r:
            f.append(f"report missing required section {k}")

    print("sports_acquisition selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    # THE CENTRAL RULE: nothing becomes an org-proxy denial without explicit proof
    ("unexplained tool failure reported as an ORG PROXY denial",
     '    if code == 0:\n        # No conclusion reached. This is NOT a policy denial and is not reported as one.\n        return "TOOL_INTERNAL_ERROR", e.strip()[:300]',
     '    if code == 0:\n        return "HTTP_403_ORG_PROXY", e.strip()[:300]'),
    ("ORIGIN 403 reported as an ORG PROXY denial",
     '    if code == 403:\n        # The ORIGIN answered and refused us. The opposite fact from never reaching it.\n        return "HTTP_403_ORIGIN", ""',
     '    if code == 403:\n        return "HTTP_403_ORG_PROXY", ""'),
    ("proxy proof relaxed to match anything", '_PROXY_PROOF = ("connect tunnel failed, response 403",', '_PROXY_PROOF = ("",'),
    ("timeout upgraded to a policy denial", '        return "TIMEOUT", e.strip()[:300]', '        return "HTTP_403_ORG_PROXY", e.strip()[:300]'),
    ("dns failure upgraded to a policy denial", '        return "DNS_FAILURE", e.strip()[:300]', '        return "HTTP_403_ORG_PROXY", e.strip()[:300]'),
    ("unsafe-URL refusal upgraded to a policy denial", '        return "TOOL_UNSAFE_URL", e.strip()[:300]', '        return "HTTP_403_ORG_PROXY", e.strip()[:300]'),
    ("auth-required collapsed into a denial", '        return "HTTP_401_AUTH_REQUIRED", ""', '        return "HTTP_403_ORG_PROXY", ""'),
    ("rate limiting collapsed into a denial", '        return "HTTP_429_RATE_LIMITED", ""', '        return "HTTP_403_ORG_PROXY", ""'),
    ("verbatim error discarded", "        return \"HTTP_403_ORG_PROXY\", e.strip()[:300]", '        return "HTTP_403_ORG_PROXY", ""'),
    # capability record integrity
    ("unknown network_status accepted", '    assert network_status in NET,', '    assert True or network_status in NET,'),
    ("unknown content_status accepted", '    assert content_status in CONTENT,', '    assert True or content_status in CONTENT,'),
    ("extractability ASSERTED for a route never reached",
     "        score_extractable=None, game_status_extractable=None,\n        box_score_extractable=None, advanced_metrics_extractable=None,",
     "        score_extractable=False, game_status_extractable=False,\n        box_score_extractable=False, advanced_metrics_extractable=False,"),
    ("unreachable route given a content verdict",
     '        content_status=("NOT_APPLICABLE" if not reachable else "PARSE_FAILURE"),',
     '        content_status="PARSE_FAILURE",'),
    # resilience
    # The real retry bound is the range(), not the sleep guard — mutating the guard alone leaves
    # the loop bounded and proves nothing. Target the bound itself.
    ("retry bound removed", "    for attempt in range(retries + 1):", "    for attempt in range(50):"),
    ("proven policy denial retried anyway", '        if net == "HTTP_403_ORG_PROXY":         # a proven policy denial is final; do not retry\n            break', "        if False:\n            break"),
    ("circuit breaker never opens", "        if self.fails[host] >= self.threshold:", "        if False:"),
    ("open circuit probed anyway", "    if breaker and breaker.is_open(host):", "    if False:"),
    ("a raised fault aborts the sweep", "        except Exception as exc:                      # belt and braces: the sweep cannot die", "        except ZeroDivisionError as exc:"),
    # capability keying
    ("route dropped so capability generalises across paths",
     '    route = "/" + tail_.split("/", 1)[1] if "/" in tail_ else "/"', '    route = "/"'),
    ("retrieval tool dropped from the capability key", '"tool": tool,', '"tool": "any",'),
    # canonical admission
    ("tier 2/3 admitted to canonical", "    if tier != TIER1:", "    if False:"),
    ("missing canonical fields tolerated", "    if missing:", "    if False:"),
    ("conflict with a registered result tolerated", "            if not same:", "            if False:"),
    ("empty acquisition reported as complete",
     '"outcome": ("NO_DATA_ACQUIRED" if not canonical and not provisional else',
     '"outcome": ("COMPLETE" if not canonical and not provisional else'),
]


def mutation_suite(verbose=True):
    import tempfile as _tf
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = [")
    j = src.index("\ndef mutation_suite", i)
    head, block, tail = src[:i], src[i:j], src[j:]
    surv, unapp = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapp.append(f"{name}: pattern not found"); continue
        mut = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mut == src:
            unapp.append(f"{name}: no-op"); continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mut); path = fh.name
        try:
            pr = subprocess.run([sys.executable, path, "--selftest"], capture_output=True,
                                text=True, timeout=180)
            killed = pr.returncode != 0
        except subprocess.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}")
        if not killed:
            surv.append(name)
    for u in unapp:
        print(f"  UNAPPLIED  {u}")
    print(f"mutation suite: {len(MUTANTS)-len(surv)-len(unapp)}/{len(MUTANTS)} killed"
          f"{'' if not (surv or unapp) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return surv + unapp


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    print(__doc__)
