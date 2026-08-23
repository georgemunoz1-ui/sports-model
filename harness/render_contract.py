#!/usr/bin/env python3
"""RENDER CONTRACT — what a number is allowed to be called, and the ban on truncating a reason.

OWNER AMENDMENTS 6, 7 AND 10 (2026-08-23).

  6. "Rename ambiguous summary fields. CHAMPION SPREAD 5.32pp is cross-game probability SD, not the
     probability range or betting spread. Render it as CROSS_GAME_P_SD."

  7. "Separate uncertainty quantities. WNBA's 8.9pp prior uncertainty and 8.11pp empirical forecast
     uncertainty are different objects. Label each explicitly; never display both as generic SD."

 10. "Fix truncated status rendering. CEILIN and NEUTRA are display truncations. Status tokens must
     render completely because they carry binding reasons."

THE THREE DEFECTS ARE ONE DEFECT. In a betting context "spread" means a handicap; the 8/23 board
used it for the standard deviation of an arm's home probability ACROSS the games of a slate, which
is not a spread, not a range, and not even an uncertainty — it is DISPERSION, a property of the
slate as much as of the model. Directly beneath it, two genuinely different uncertainties (the Beta
posterior sd of a 10-game prior, and the empirical sd of the forecast edge) were both printed as
"SD". And the pill that explains WHY an action is blocked was cut off mid-word: "21 day ceilin",
"out of domain neutra". A blocked action's reason is the binding part of the record. A reader who
cannot read the whole reason cannot check it, and a reason that renders differently from the one
stored is a second source of truth.

SO THIS MODULE ENFORCES THREE THINGS, none of which is a style preference:

  ONE NAME PER QUANTITY. A closed vocabulary with the banned aliases attached to each entry, so the
  ban travels with the definition instead of living in a review comment.

  DISPERSION IS NOT UNCERTAINTY. Every registered quantity declares a FAMILY. Two quantities from
  different families may never share a display label, and neither may two different uncertainty
  kinds — that is the exact WNBA defect, stated as a rule.

  A REASON RENDERS WHOLE. Every canonical status token must appear VERBATIM in the output. A token
  present only as a proper prefix is a truncation, and truncation is refused rather than styled.

API
  label_audit(text)                       -> banned aliases found in rendered output
  quantity_gate(quantities)               -> label collisions and missing/unknown kinds
  truncation_audit(text, tokens)          -> tokens rendered only as a prefix
  render_gate(text, quantities, tokens)   -> all three, and the overall verdict
"""
from __future__ import annotations

import json
import os
import re
import sys

DISPERSION = "DISPERSION"
UNCERTAINTY = "UNCERTAINTY"

# --- the closed vocabulary ------------------------------------------------------------------------
QUANTITIES = {
    "CROSS_GAME_P_SD": {
        "family": DISPERSION,
        "unit": "pp",
        "definition": "standard deviation of one arm's p_home ACROSS the games of one slate — how "
                      "much the arm separates games, not how unsure it is about any one of them",
        "banned_aliases": ["champion spread", "challenger spread", "spread", "probability range",
                           "prob range", "p range"],
    },
    "PRIOR_PARAMETER_SD": {
        "family": UNCERTAINTY,
        "unit": "pp",
        "definition": "posterior standard deviation of the expanding Beta prior's probability "
                      "parameter — shrinks as sqrt(1/n) with the number of finals in the pool",
        "banned_aliases": ["sd", "prior sd", "uncertainty"],
    },
    "EMPIRICAL_FORECAST_EDGE_SD": {
        "family": UNCERTAINTY,
        "unit": "pp",
        "definition": "empirical standard deviation of the realised forecast edge, used to build "
                      "conservative_edge = raw_edge - 1.645 x this",
        "banned_aliases": ["sd", "emp. sd", "emp sd", "uncertainty"],
    },
    "MONTE_CARLO_SD": {
        "family": UNCERTAINTY,
        "unit": "pp",
        "definition": "simulation noise in one arm's probability estimate at its trial count",
        "banned_aliases": ["sd", "sim sd", "uncertainty"],
    },
    "PRIOR_POOL_SD_RUNS": {
        "family": UNCERTAINTY,
        "unit": "runs",
        "definition": "standard deviation of the tier-1 final totals in the expanding scoring prior",
        "banned_aliases": ["sd", "total sd"],
    },
}

# Labels so generic that they identify nothing, whatever they are attached to.
GENERIC_LABELS = {"sd", "s.d.", "σ", "sigma", "uncertainty", "spread", "range", "error", "variance"}

OK = "RENDER_CONTRACT_OK"
REFUSED = "RENDER_CONTRACT_REFUSED"

TRUNCATED = "TRUNCATED_STATUS_TOKEN"
MISSING_TOKEN = "STATUS_TOKEN_ABSENT_FROM_RENDER"
BANNED_ALIAS = "BANNED_ALIAS"
UNKNOWN_KIND = "UNKNOWN_QUANTITY_KIND"
NO_KIND = "QUANTITY_WITHOUT_DECLARED_KIND"
LABEL_COLLISION = "ONE_LABEL_TWO_QUANTITIES"
GENERIC_LABEL = "GENERIC_LABEL_IDENTIFIES_NOTHING"
LABEL_MISNAMES = "LABEL_DOES_NOT_NAME_ITS_KIND"

# Shortest prefix worth treating as evidence of a truncation rather than a coincidence.
MIN_PREFIX = 8


def _strip_markup(text):
    return re.sub(r"<[^>]+>", " ", text)


def _norm(s):
    return re.sub(r"\s+", " ", str(s).replace("&minus;", "-").replace("&ndash;", "-")
                  .replace("&mdash;", "-").replace("&rsquo;", "'").replace("&middot;", " ")).strip().lower()


# =================================================================================================
def label_audit(text):
    """Banned aliases appearing in rendered output."""
    hay = _norm(_strip_markup(text))
    hits = []
    for canon, spec in sorted(QUANTITIES.items()):
        for alias in spec["banned_aliases"]:
            a = _norm(alias)
            # word-boundary match so "spread" does not fire inside "spreadsheet", and so the bare
            # alias "sd" does not fire inside the canonical name CROSS_GAME_P_SD it replaces
            if re.search(r"(?<![a-z0-9_])" + re.escape(a) + r"(?![a-z0-9_])", hay):
                hits.append({"code": BANNED_ALIAS, "alias": alias, "canonical": canon,
                             "definition": spec["definition"]})
    return hits


def quantity_gate(quantities):
    """`quantities`: [{"display_label": str, "kind": str, "value": num}, ...]

    Refuses an undeclared or unknown kind, a generic label, and — the WNBA defect — one label
    covering two different quantities.
    """
    problems, by_label = [], {}
    for q in quantities:
        label, kind = q.get("display_label"), q.get("kind")
        if kind is None:
            problems.append({"code": NO_KIND, "label": label})
            continue
        if kind not in QUANTITIES:
            problems.append({"code": UNKNOWN_KIND, "label": label, "kind": kind})
            continue
        if label is None or _norm(label) in GENERIC_LABELS:
            problems.append({"code": GENERIC_LABEL, "label": label, "kind": kind,
                             "required": kind})
        elif _norm(kind).replace("_", " ") not in _norm(label).replace("_", " "):
            # "Emp. SD" is not in GENERIC_LABELS and still identifies nothing: the reader cannot
            # tell it from the prior's SD two lines above. A label must NAME the kind it carries.
            problems.append({"code": LABEL_MISNAMES, "label": label, "kind": kind,
                             "required": kind})
        by_label.setdefault(_norm(label), set()).add(kind)
    for label, kinds in sorted(by_label.items()):
        if len(kinds) > 1:
            fams = sorted({QUANTITIES[k]["family"] for k in kinds})
            problems.append({"code": LABEL_COLLISION, "label": label, "kinds": sorted(kinds),
                             "families": fams,
                             "note": "different families entirely" if len(fams) > 1
                                     else "two different uncertainties under one heading"})
    return problems


def truncation_audit(text, tokens):
    """A canonical token must appear VERBATIM. Present only as a prefix means truncated."""
    hay = _norm(_strip_markup(text))
    out = []
    for tok in tokens:
        t = _norm(tok)
        if not t:
            continue
        if t in hay:
            continue
        # walk back from the full token: the longest prefix that IS present locates the cut
        cut = None
        for k in range(len(t) - 1, MIN_PREFIX - 1, -1):
            if t[:k] in hay:
                cut = t[:k]
                break
        if cut is not None:
            out.append({"code": TRUNCATED, "token": tok, "rendered_as": cut,
                        "lost": tok[len(cut):],
                        "note": "a blocked action's reason is the binding part of the record"})
        else:
            out.append({"code": MISSING_TOKEN, "token": tok})
    return out


def render_gate(text, quantities=(), tokens=()):
    problems = label_audit(text) + quantity_gate(list(quantities)) + truncation_audit(text, list(tokens))
    return {"status": OK if not problems else REFUSED,
            "n_problems": len(problems),
            "problems": problems,
            "vocabulary": sorted(QUANTITIES)}


# =================================================================================================
def selftest():
    f = []

    # --- 6: the 8/23 board's own header line ------------------------------------------------------
    bad_html = ('<div class="stat"><span>Champion spread</span><b>5.32pp</b>'
                '<i>range 0.431&ndash;0.616</i></div>')
    hits = label_audit(bad_html)
    if not any(h["alias"] == "champion spread" for h in hits):
        f.append("'Champion spread' must be caught as a banned alias")
    if not any(h["canonical"] == "CROSS_GAME_P_SD" for h in hits):
        f.append("the banned alias must name its canonical replacement")
    good_html = '<div class="stat"><span>CROSS_GAME_P_SD</span><b>5.32pp</b></div>'
    if label_audit(good_html):
        f.append(f"the canonical name must pass, got {label_audit(good_html)}")
    if label_audit("the spreadsheet was updated"):
        f.append("'spreadsheet' must not fire the 'spread' alias")

    # --- 7: the WNBA collision --------------------------------------------------------------------
    wnba = [{"display_label": "SD", "kind": "PRIOR_PARAMETER_SD", "value": 8.9},
            {"display_label": "SD", "kind": "EMPIRICAL_FORECAST_EDGE_SD", "value": 8.11}]
    p = quantity_gate(wnba)
    if not any(x["code"] == LABEL_COLLISION for x in p):
        f.append("two different uncertainties under one label must collide")
    coll = [x for x in p if x["code"] == LABEL_COLLISION][0]
    if sorted(coll["kinds"]) != ["EMPIRICAL_FORECAST_EDGE_SD", "PRIOR_PARAMETER_SD"]:
        f.append("the collision must name both kinds")
    if not any(x["code"] == GENERIC_LABEL for x in p):
        f.append("'SD' is a generic label and must be refused on its own")
    # the board's OTHER heading, "Emp. SD", is not in the generic list and is just as unreadable
    emp = quantity_gate([{"display_label": "Emp. SD", "kind": "EMPIRICAL_FORECAST_EDGE_SD",
                          "value": 8.11}])
    if not any(x["code"] == LABEL_MISNAMES for x in emp):
        f.append(f"a label that does not name its kind must be refused, got {emp}")
    if quantity_gate([{"display_label": "EMPIRICAL_FORECAST_EDGE_SD (pp)",
                       "kind": "EMPIRICAL_FORECAST_EDGE_SD", "value": 8.11}]):
        f.append("a label that names its kind, with a unit appended, must pass")
    fixed = [{"display_label": "PRIOR_PARAMETER_SD", "kind": "PRIOR_PARAMETER_SD", "value": 8.9},
             {"display_label": "EMPIRICAL_FORECAST_EDGE_SD", "kind": "EMPIRICAL_FORECAST_EDGE_SD",
              "value": 8.11}]
    if quantity_gate(fixed):
        f.append(f"explicitly labelled quantities must pass, got {quantity_gate(fixed)}")
    # dispersion and uncertainty sharing a heading is the worse case and must name both families
    mixed = [{"display_label": "spread", "kind": "CROSS_GAME_P_SD", "value": 5.32},
             {"display_label": "spread", "kind": "MONTE_CARLO_SD", "value": 0.29}]
    mp = [x for x in quantity_gate(mixed) if x["code"] == LABEL_COLLISION]
    if not mp or mp[0]["families"] != [DISPERSION, UNCERTAINTY]:
        f.append("a dispersion and an uncertainty under one label must report both families")
    if not any(x["code"] == NO_KIND for x in quantity_gate([{"display_label": "Emp. SD", "value": 8.11}])):
        f.append("a quantity with no declared kind must be refused")
    if not any(x["code"] == UNKNOWN_KIND for x in
               quantity_gate([{"display_label": "X", "kind": "VIBES_SD", "value": 1.0}])):
        f.append("a kind outside the vocabulary must be refused")

    # --- 10: the truncated pills ------------------------------------------------------------------
    tokens = ["feature state 32 days stale vs 21 day ceiling",
              "feature state stale and out of domain neutral site"]
    render = ('<span class="pill blk">feature state 32 days stale vs 21 day ceilin</span>'
              '<span class="pill blk">feature state stale and out of domain neutra</span>')
    t = truncation_audit(render, tokens)
    if len(t) != 2 or not all(x["code"] == TRUNCATED for x in t):
        f.append(f"both truncated pills must be caught, got {t}")
    if t[0]["lost"] != "g":
        f.append(f"the audit must report what was lost, got {t[0]['lost']!r}")
    whole = ('<span class="pill blk">feature state 32 days stale vs 21 day ceiling</span>'
             '<span class="pill blk">feature state stale and out of domain neutral site</span>')
    if truncation_audit(whole, tokens):
        f.append("complete tokens must pass")
    # a token that renders complete but is SPLIT BY MARKUP is complete: the reader sees all of it
    split = ('<span class="pill blk"><b>feature state</b> 32 days stale vs <i>21 day ceiling</i></span>'
             '<span class="pill blk">feature state stale and out of domain neutral site</span>')
    if truncation_audit(split, tokens):
        f.append(f"markup inside a complete token is not a truncation, got {truncation_audit(split, tokens)}")
    absent = truncation_audit("<p>nothing to see</p>", tokens)
    if not all(x["code"] == MISSING_TOKEN for x in absent):
        f.append("a token absent entirely is missing, not truncated")
    # a one-character loss at the END is still a truncation, not a rounding
    if not truncation_audit("action blocked: neutral sit", ["action blocked: neutral site"]):
        f.append("losing the final character is still a truncation")

    # --- the gate as a whole ----------------------------------------------------------------------
    g = render_gate(bad_html + render, wnba, tokens)
    if g["status"] != REFUSED:
        f.append("the 8/23 render must be refused by the contract")
    codes = {x["code"] for x in g["problems"]}
    # each of the three amendments must be represented, not just enough problems to trip the verdict
    for need in (BANNED_ALIAS, LABEL_COLLISION, GENERIC_LABEL, TRUNCATED):
        if need not in codes:
            f.append(f"the gate must surface {need}, got {sorted(codes)}")
    clean = render_gate(good_html + whole, fixed, tokens)
    if clean["status"] != OK:
        f.append(f"a corrected render must pass, got {clean['problems']}")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("render_contract selftest: OK")
    return f


MUTANTS = [
    ("banned aliases stop being checked",
     "            if re.search(r\"(?<![a-z0-9_])\" + re.escape(a) + r\"(?![a-z0-9_])\", hay):",
     "            if False:"),
    ("the alias match loses its word boundary, so 'spreadsheet' fires",
     "            if re.search(r\"(?<![a-z0-9_])\" + re.escape(a) + r\"(?![a-z0-9_])\", hay):",
     "            if a in hay:"),
    ("the boundary stops excluding underscores, so the canonical name trips its own alias",
     "            if re.search(r\"(?<![a-z0-9_])\" + re.escape(a) + r\"(?![a-z0-9_])\", hay):",
     "            if re.search(r\"(?<![a-z])\" + re.escape(a) + r\"(?![a-z])\", hay):"),
    ("the banned alias stops naming its replacement",
     '                hits.append({"code": BANNED_ALIAS, "alias": alias, "canonical": canon,',
     '                hits.append({"code": BANNED_ALIAS, "alias": alias, "canonical": None,'),
    ("'Champion spread' is quietly removed from the banned list",
     '"banned_aliases": ["champion spread", "challenger spread", "spread", "probability range",\n                           "prob range", "p range"],',
     '"banned_aliases": ["probability range", "prob range", "p range"],'),
    ("one label may cover two quantities",
     "        if len(kinds) > 1:", "        if False:"),
    ("the collision stops reporting which kinds collided",
     '            problems.append({"code": LABEL_COLLISION, "label": label, "kinds": sorted(kinds),',
     '            problems.append({"code": LABEL_COLLISION, "label": label, "kinds": [],'),
    ("the collision stops distinguishing families",
     '            fams = sorted({QUANTITIES[k]["family"] for k in kinds})', "            fams = []"),
    ("a label need not name the kind it carries",
     '        elif _norm(kind).replace("_", " ") not in _norm(label).replace("_", " "):',
     "        elif False:"),
    ("a generic label passes",
     '        if label is None or _norm(label) in GENERIC_LABELS:', "        if False:"),
    ("the generic list is emptied",
     'GENERIC_LABELS = {"sd", "s.d.", "σ", "sigma", "uncertainty", "spread", "range", "error", "variance"}',
     "GENERIC_LABELS = set()"),
    ("a quantity may omit its kind",
     '        if kind is None:\n            problems.append({"code": NO_KIND, "label": label})\n            continue',
     "        if kind is None:\n            continue"),
    ("an unknown kind is accepted",
     "        if kind not in QUANTITIES:", "        if False:"),
    ("truncation stops being detected",
     "        if cut is not None:", "        if False:"),
    ("a truncated token is reported as merely missing",
     '            out.append({"code": TRUNCATED, "token": tok, "rendered_as": cut,',
     '            out.append({"code": MISSING_TOKEN, "token": tok, "rendered_as": cut,'),
    ("the audit stops reporting what was lost",
     '                        "lost": tok[len(cut):],', '                        "lost": "",'),
    ("a near-complete render counts as complete",
     "        if t in hay:\n            continue", "        if t[:len(t)-2] in hay:\n            continue"),
    ("the prefix floor swallows short reasons whole",
     "MIN_PREFIX = 8", "MIN_PREFIX = 400"),
    ("the gate reports OK regardless of problems",
     '    return {"status": OK if not problems else REFUSED,', '    return {"status": OK,'),
    ("the gate stops running the quantity check",
     "    problems = label_audit(text) + quantity_gate(list(quantities)) + truncation_audit(text, list(tokens))",
     "    problems = label_audit(text) + truncation_audit(text, list(tokens))"),
    ("the gate stops running the truncation check",
     "    problems = label_audit(text) + quantity_gate(list(quantities)) + truncation_audit(text, list(tokens))",
     "    problems = label_audit(text) + quantity_gate(list(quantities))"),
    ("markup is not stripped, so a token split by a tag reads as truncated",
     "    hay = _norm(_strip_markup(text))\n    out = []", "    hay = _norm(text)\n    out = []"),
]


def mutation_suite(verbose=True):
    import subprocess as _sp, tempfile as _tf
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
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=120)
            killed = pr.returncode != 0
        except _sp.TimeoutExpired:
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
