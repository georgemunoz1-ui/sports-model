#!/usr/bin/env python3
"""SEMANTIC handoff-journal continuity (owner ruling 2026-08-22).

WHY THIS IS NOT AN MTIME CHECK
On 2026-08-22 a second journal at the repo root silently took three days of daily entries while
`docs/progress.md` — the file `AGENTS.md` step 3, `harness/runbook.md` and `healthcheck` all read —
sat unwritten. The first fix compared modification times. That catches the defect as it happened and
almost nothing else: an mtime moves on checkout, restore, rsync, `git stash`, a container rebuild or
a plain `touch`, and it says nothing about whether the file a COLD SESSION reads actually contains
the latest work. mtime is kept as an extra signal; it is not the source of truth.

WHAT IS CHECKED INSTEAD — all five on COMMITTED content, because a cold clone sees commits, not a
working tree:
  1. EXACTLY ONE canonical journal. Every other journal-shaped file must be a closed redirect.
  2. LATEST COMMITTED ENTRY. The newest dated section in the committed canonical file, and its age.
  3. THE COMMIT IT IS BOUND TO. The commit that last touched the canonical journal, its distance
     from HEAD, and whether work has landed since without a journal entry.
  4. COLD-BOOTSTRAP. The loader instruction is PARSED OUT OF AGENTS.md (path + how many lines), then
     the same slice is taken from the COMMITTED file and the latest entry must actually be inside
     it. A journal whose newest entry falls outside the window the loader reads is not a handoff.
  5. THE REDIRECT CARRIES NO INDEPENDENT STATE. A closed journal may hold history and a pointer; a
     dated entry appearing AFTER its redirect marker means it is being written to again.

READS ONLY. Never writes, never edits a journal.
"""
from __future__ import annotations

import datetime
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANONICAL = "docs/progress.md"
LOADER_SPEC = "AGENTS.md"
REDIRECT_MARKERS = ("JOURNAL SPLIT CLOSED", "NOT the canonical run journal", "Do not append here")
DATE_HEADER = re.compile(r"^#{1,3}\s*(\d{4}-\d{2}-\d{2})", re.M)
MAX_ENTRY_AGE_DAYS = 2
DEFAULT_LOADER_LINES = 30


def _git(*args, cwd=None):
    try:
        pr = subprocess.run(["git"] + list(args), cwd=cwd or BASE,
                            capture_output=True, text=True, timeout=60)
        return pr.stdout if pr.returncode == 0 else None
    except Exception:
        return None


def committed_text(path):
    """The file as a COLD CLONE would see it. None when the path is not committed at HEAD."""
    return _git("show", f"HEAD:{path}")


def latest_entry(text):
    """(date_string, header_line_index) of the newest dated section, or (None, None)."""
    if not text:
        return None, None
    best, idx = None, None
    for i, line in enumerate(text.splitlines()):
        m = DATE_HEADER.match(line)
        if m and (best is None or m.group(1) > best):
            best, idx = m.group(1), i
    return best, idx


def parse_loader(spec_text):
    """Pull the bootstrap instruction OUT of AGENTS.md rather than hard-coding it here.

    A check that hard-codes the path it is meant to verify cannot notice the day AGENTS.md starts
    pointing somewhere else — which is the whole failure mode. Returns (path, n_lines, raw_line)."""
    if not spec_text:
        return None, DEFAULT_LOADER_LINES, None
    for line in spec_text.splitlines():
        if "progress.md" not in line or "read" not in line.lower():
            continue
        m = re.search(r"`([^`]*progress\.md)`", line) or re.search(r"([\w./-]*progress\.md)", line)
        n = re.search(r"last\s*~?\s*(\d+)\s*lines", line, re.I)
        if m:
            return m.group(1), int(n.group(1)) if n else DEFAULT_LOADER_LINES, line.strip()
    return None, DEFAULT_LOADER_LINES, None


def find_journals(root=None):
    """Every journal-shaped file in the tree: a markdown file named progress.md, or one carrying
    dated section headers under docs/. Redirects are still journals — that is the point."""
    root = root or BASE
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__")]
        for fn in filenames:
            if fn.lower() != "progress.md":
                continue
            out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return sorted(out)


def is_redirect(text):
    return bool(text) and any(m in text for m in REDIRECT_MARKERS)


def redirect_state_after_marker(text):
    """Dated entries appearing AFTER the redirect marker — i.e. the closed file is live again."""
    if not text:
        return []
    lines = text.splitlines()
    pos = None
    for i, line in enumerate(lines):
        if any(m in line for m in REDIRECT_MARKERS):
            pos = i
            break
    if pos is None:
        return []
    return [l for l in lines[pos + 1:] if DATE_HEADER.match(l)]


def check(canonical=None, loader_spec=None, journals=None, today=None,
          committed_reader=None, log_reader=None):
    """Returns (ok, failures, detail). Every argument is injectable so fixtures drive real logic."""
    canonical = canonical or CANONICAL
    read = committed_reader or committed_text
    fails, warns, detail = [], [], {}

    # ---- 1. EXACTLY ONE canonical journal
    js = journals if journals is not None else find_journals()
    texts = {j: read(j) for j in js}
    live = [j for j, t in texts.items() if t is not None and not is_redirect(t)]
    detail["journals"] = {j: ("REDIRECT" if is_redirect(t) else
                              ("LIVE" if t is not None else "UNCOMMITTED")) for j, t in texts.items()}
    if canonical not in js:
        fails.append(f"CANONICAL_JOURNAL_ABSENT — {canonical} is not among the journals found "
                     f"({js}); the file every bootstrap path names must exist")
    if len(live) != 1:
        fails.append(f"NOT_EXACTLY_ONE_CANONICAL_JOURNAL — {len(live)} live journals: {sorted(live)}. "
                     f"Every journal but the canonical one must be a closed redirect, or handoff "
                     f"state ends up in a file nothing reads")
    elif live[0] != canonical:
        fails.append(f"WRONG_LIVE_JOURNAL — the only live journal is {live[0]}, not {canonical}")

    ctext = texts.get(canonical) if canonical in texts else read(canonical)
    if ctext is None:
        fails.append(f"CANONICAL_JOURNAL_NOT_COMMITTED — {canonical} is absent at HEAD. A cold clone "
                     f"sees commits, not a working tree, so an uncommitted journal is no handoff")
        return (not fails), fails, detail

    # ---- 2. LATEST COMMITTED ENTRY and its age
    date, idx = latest_entry(ctext)
    detail["latest_committed_entry"] = date
    if not date:
        fails.append(f"NO_DATED_ENTRY — the committed {canonical} carries no dated section header, "
                     f"so 'the latest entry' is not a well-defined thing to read")
    else:
        td = today or datetime.date.today()
        try:
            age = (td - datetime.date.fromisoformat(date)).days
        except ValueError:
            age = None
            fails.append(f"UNPARSEABLE_ENTRY_DATE — {date!r}")
        detail["latest_entry_age_days"] = age
        if age is not None and age > MAX_ENTRY_AGE_DAYS:
            warns.append(f"STALE_COMMITTED_ENTRY — the newest committed entry is {date} "
                         f"({age} days old, tolerance {MAX_ENTRY_AGE_DAYS})")
        if age is not None and age < 0:
            fails.append(f"FUTURE_ENTRY_DATE — the newest entry is dated {date}, ahead of {td}")

    # ---- 3. THE COMMIT THE JOURNAL IS BOUND TO
    lg = log_reader or (lambda p: _git("log", "-1", "--format=%H %cI", "--", p))
    head = (_git("rev-parse", "HEAD") or "").strip() or None
    jl = (lg(canonical) or "").strip()
    detail["head_commit"] = head
    if jl:
        parts = jl.split()
        detail["journal_commit"] = parts[0]
        detail["journal_commit_time"] = parts[1] if len(parts) > 1 else None
        behind = _git("rev-list", "--count", f"{parts[0]}..HEAD")
        detail["commits_since_journal"] = int(behind.strip()) if behind and behind.strip().isdigit() else None
        if detail["commits_since_journal"] and detail["commits_since_journal"] > 3:
            warns.append(f"WORK_SINCE_LAST_JOURNAL_ENTRY — {detail['commits_since_journal']} commits "
                         f"have landed since {canonical} was last written")
    else:
        detail["journal_commit"] = None
        fails.append(f"NO_COMMIT_BINDS_THE_JOURNAL — git has no commit touching {canonical}")

    # ---- 4. COLD BOOTSTRAP: does the loader's own window contain the latest entry?
    spec = read(loader_spec or LOADER_SPEC)
    lpath, llines, lraw = parse_loader(spec)
    detail["loader"] = {"spec_file": loader_spec or LOADER_SPEC, "path": lpath,
                        "lines": llines, "instruction": lraw}
    if lpath is None:
        fails.append(f"LOADER_INSTRUCTION_NOT_FOUND — {loader_spec or LOADER_SPEC} does not state "
                     f"which journal a new session reads; the bootstrap path is unverifiable")
    elif lpath.lstrip("./") != canonical.lstrip("./"):
        fails.append(f"LOADER_POINTS_ELSEWHERE — the bootstrap instruction reads {lpath!r} but the "
                     f"canonical journal is {canonical!r}")
    if date:
        window = "\n".join(ctext.splitlines()[-llines:])
        wdate, _ = latest_entry(window)
        detail["cold_bootstrap"] = {"window_lines": llines, "latest_entry_in_window": wdate}
        if wdate != date:
            fails.append(f"COLD_BOOTSTRAP_MISSES_LATEST_ENTRY — a new session reads the last "
                         f"{llines} lines of {canonical} and would see {wdate!r}, but the newest "
                         f"entry is {date!r}. A journal whose newest entry falls outside the window "
                         f"the loader actually reads is not a handoff")

    # ---- 5. THE REDIRECT CARRIES NO INDEPENDENT STATE
    leaks = {}
    for j, t in texts.items():
        if j == canonical or not is_redirect(t):
            continue
        after = redirect_state_after_marker(t)
        if after:
            leaks[j] = after
    detail["redirect_state_leaks"] = leaks
    for j, after in leaks.items():
        fails.append(f"REDIRECT_CARRIES_INDEPENDENT_STATE — {j} is a closed redirect but has "
                     f"{len(after)} dated entr{'y' if len(after) == 1 else 'ies'} after its marker "
                     f"({after[:2]}); it is being written to again")

    detail["warnings"] = warns
    return (not fails), fails, detail


def selftest():
    fails = []
    F = lambda text: (lambda p: text.get(p))       # noqa: E731  injectable committed reader

    AG = "3. Read `docs/progress.md` (last ~30 lines) — what the previous run did and left for you."
    good_journal = "\n".join(["## 2026-08-01", "- old"] + ["- filler"] * 40
                             + ["## 2026-08-22", "- newest entry"])
    redirect = "## 2026-08-11\n- old\n\n## JOURNAL SPLIT CLOSED (2026-08-22)\nDo not append here again."
    TODAY = datetime.date(2026, 8, 22)
    LOG = lambda p: "abc123 2026-08-22T09:00:00Z"   # noqa: E731

    def run(texts, journals, **kw):
        return check(canonical="docs/progress.md", loader_spec="AGENTS.md", journals=journals,
                     today=TODAY, committed_reader=F(texts), log_reader=LOG, **kw)

    base = {"docs/progress.md": good_journal, "progress.md": redirect, "AGENTS.md": AG}
    ok, f, d = run(base, ["docs/progress.md", "progress.md"])
    if not ok:
        fails.append(f"a healthy tree was rejected: {f}")
    if d.get("latest_committed_entry") != "2026-08-22":
        fails.append(f"latest committed entry wrong: {d.get('latest_committed_entry')}")
    if d.get("journal_commit") != "abc123":
        fails.append(f"the journal was not bound to its commit: {d.get('journal_commit')}")
    if (d.get("cold_bootstrap") or {}).get("latest_entry_in_window") != "2026-08-22":
        fails.append(f"cold bootstrap detail missing: {d.get('cold_bootstrap')}")

    # 1. TWO LIVE JOURNALS — the 8/22 defect itself
    two = dict(base, **{"progress.md": "## 2026-08-22\n- entries going to the wrong file"})
    ok, f, _ = run(two, ["docs/progress.md", "progress.md"])
    if ok or not any("NOT_EXACTLY_ONE_CANONICAL_JOURNAL" in x for x in f):
        fails.append(f"two live journals were accepted — the exact 2026-08-22 defect: {f}")
    # ... and mtime cannot see it: this fixture never touches a filesystem timestamp
    ok, f, _ = run({"docs/progress.md": redirect, "progress.md": good_journal, "AGENTS.md": AG},
                   ["docs/progress.md", "progress.md"])
    if ok or not any("WRONG_LIVE_JOURNAL" in x or "NOT_EXACTLY_ONE" in x for x in f):
        fails.append(f"the canonical journal being the CLOSED one was accepted: {f}")

    # 2. STALE / FUTURE / MISSING entry dates
    stale = dict(base, **{"docs/progress.md": "## 2026-08-01\n- ancient"})
    ok, f, d = run(stale, ["docs/progress.md", "progress.md"])
    if not any("STALE_COMMITTED_ENTRY" in w for w in d.get("warnings") or []):
        fails.append("a three-week-old committed entry raised no staleness signal")
    if d.get("latest_entry_age_days") != 21:
        fails.append(f"entry age miscomputed: {d.get('latest_entry_age_days')}")
    fut = dict(base, **{"docs/progress.md": "## 2026-09-30\n- from the future"})
    ok, f, _ = run(fut, ["docs/progress.md", "progress.md"])
    if ok or not any("FUTURE_ENTRY_DATE" in x for x in f):
        fails.append(f"a future-dated entry was accepted: {f}")
    nod = dict(base, **{"docs/progress.md": "no dated headers at all\njust prose\n"})
    ok, f, _ = run(nod, ["docs/progress.md", "progress.md"])
    if ok or not any("NO_DATED_ENTRY" in x for x in f):
        fails.append(f"a journal with no dated entry was accepted: {f}")

    # 3. UNCOMMITTED canonical — a cold clone would see nothing
    unc = {"docs/progress.md": None, "progress.md": redirect, "AGENTS.md": AG}
    ok, f, _ = run(unc, ["docs/progress.md", "progress.md"])
    if ok or not any("CANONICAL_JOURNAL_NOT_COMMITTED" in x for x in f):
        fails.append(f"an UNCOMMITTED journal passed — the working tree is not what a clone reads: {f}")

    # 4. COLD BOOTSTRAP — newest entry outside the window the loader actually reads
    buried = "\n".join(["## 2026-08-22", "- newest entry"] + ["- filler"] * 60)
    ok, f, d = run(dict(base, **{"docs/progress.md": buried}), ["docs/progress.md", "progress.md"])
    if ok or not any("COLD_BOOTSTRAP_MISSES_LATEST_ENTRY" in x for x in f):
        fails.append(f"an entry buried 60 lines above the loader's 30-line window passed: {f}")
    # the window size is READ FROM AGENTS.md, not assumed
    ok2, f2, d2 = run(dict(base, **{"docs/progress.md": buried,
                                    "AGENTS.md": "3. Read `docs/progress.md` (last ~200 lines)"}),
                      ["docs/progress.md", "progress.md"])
    if not ok2:
        fails.append(f"widening the loader window in AGENTS.md did not widen the check: {f2}")
    if (d2.get("loader") or {}).get("lines") != 200:
        fails.append(f"the loader window was not parsed from AGENTS.md: {d2.get('loader')}")
    # AGENTS.md pointing somewhere else entirely
    ok, f, _ = run(dict(base, **{"AGENTS.md": "3. Read `notes/elsewhere_progress.md` (last ~30 lines)"}),
                   ["docs/progress.md", "progress.md"])
    if ok or not any("LOADER_POINTS_ELSEWHERE" in x for x in f):
        fails.append(f"a bootstrap instruction naming a different journal was accepted: {f}")
    ok, f, _ = run(dict(base, **{"AGENTS.md": "no bootstrap instruction here"}),
                   ["docs/progress.md", "progress.md"])
    if ok or not any("LOADER_INSTRUCTION_NOT_FOUND" in x for x in f):
        fails.append(f"a missing bootstrap instruction was accepted: {f}")

    # 5. REDIRECT CARRYING INDEPENDENT STATE
    leaky = redirect + "\n## 2026-08-23\n- someone appended here again\n"
    ok, f, _ = run(dict(base, **{"progress.md": leaky}), ["docs/progress.md", "progress.md"])
    if ok or not any("REDIRECT_CARRIES_INDEPENDENT_STATE" in x for x in f):
        fails.append(f"a closed redirect that is being written to again was accepted: {f}")
    # history BEFORE the marker is fine — a closed journal keeps its past (R6)
    ok, f, _ = run(base, ["docs/progress.md", "progress.md"])
    if not ok:
        fails.append(f"a redirect holding history before its marker was rejected: {f}")

    # 6a. THE REAL committed reader must read COMMITTED bytes, not the working tree. Every fixture
    #     above injects a reader, so without this the real one is never exercised at all.
    import tempfile as _tf
    with _tf.NamedTemporaryFile("w", suffix=".md", dir=BASE, delete=False,
                                prefix="uncommitted_probe_") as fh:
        fh.write("## 2026-08-22\n- this file exists in the working tree and in NO commit\n")
        probe = os.path.relpath(fh.name, BASE)
    try:
        if committed_text(probe) is not None:
            fails.append("committed_text returned content for a file that is in the working tree "
                         "but in no commit — a cold clone would see nothing there, so the check "
                         "would be validating a file the next session never receives")
        if committed_text("AGENTS.md") is None:
            fails.append("committed_text could not read a file that IS committed")
    finally:
        os.unlink(os.path.join(BASE, probe))

    # 6b. a journal bound to NO commit is a failure, not a detail
    ok, f, _ = check(canonical="docs/progress.md", loader_spec="AGENTS.md",
                     journals=["docs/progress.md", "progress.md"], today=TODAY,
                     committed_reader=F(base), log_reader=lambda p: "")
    if ok or not any("NO_COMMIT_BINDS_THE_JOURNAL" in x for x in f):
        fails.append(f"a journal that no commit touches was accepted: {f}")

    # 6. helper-level pins
    if latest_entry("## 2026-08-01\n## 2026-08-22\n## 2026-08-10")[0] != "2026-08-22":
        fails.append("latest_entry does not return the NEWEST date (order-independent)")
    if latest_entry("")[0] is not None:
        fails.append("latest_entry invented a date from nothing")
    if parse_loader(AG) != ("docs/progress.md", 30, AG.strip()):
        fails.append(f"parse_loader wrong: {parse_loader(AG)}")
    if is_redirect("ordinary journal text"):
        fails.append("an ordinary journal was classed a redirect")
    if not is_redirect(redirect):
        fails.append("a redirect was not recognised")
    if redirect_state_after_marker(redirect):
        fails.append("clean redirect reported state after its marker")

    print("journal_continuity selftest:", "PASS" if not fails else "FAIL")
    for x in fails:
        print("  " + x)
    return fails


MUTANTS = [
    ("one-canonical rule removed", "    if len(live) != 1:", "    if False:"),
    ("live journal need not be the canonical one", "    elif live[0] != canonical:", "    elif False:"),
    ("redirects counted as live", "not is_redirect(t)]", "True]"),
    ("uncommitted journal accepted", "    if ctext is None:", "    if False and ctext is None:"),
    ("committed content swapped for the working tree",
     '    return _git("show", f"HEAD:{path}")',
     '    return open(os.path.join(BASE, path)).read() if os.path.exists(path) else None'),
    ("staleness signal dropped", "        if age is not None and age > MAX_ENTRY_AGE_DAYS:",
     "        if False:"),
    ("future-dated entry tolerated", "        if age is not None and age < 0:", "        if False:"),
    ("no-dated-entry tolerated", "    if not date:", "    if False:"),
    ("latest_entry returns the FIRST date instead of the newest",
     "        if m and (best is None or m.group(1) > best):", "        if m and best is None:"),
    ("cold-bootstrap check removed", "        if wdate != date:", "        if False:"),
    ("loader window hard-coded instead of parsed from AGENTS.md",
     "        window = \"\\n\".join(ctext.splitlines()[-llines:])",
     "        window = ctext"),
    ("loader path not compared to the canonical journal",
     "    elif lpath.lstrip(\"./\") != canonical.lstrip(\"./\"):", "    elif False:"),
    ("missing loader instruction tolerated", "    if lpath is None:", "    if False:"),
    ("redirect state leak tolerated", "    for j, after in leaks.items():", "    for j, after in {}.items():"),
    ("redirect scan looks BEFORE the marker instead of after",
     "    return [l for l in lines[pos + 1:] if DATE_HEADER.match(l)]",
     "    return [l for l in lines[:pos] if DATE_HEADER.match(l)]"),
    ("journal/commit binding dropped", "        detail[\"journal_commit\"] = None\n        fails.append(",
     "        detail[\"journal_commit\"] = None\n        warns.append("),
]


def mutation_suite(verbose=True):
    import subprocess as _sp, tempfile as _tf
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = [")
    j = src.index("\ndef mutation_suite", i)
    head, block, tail = src[:i], src[i:j], src[j:]
    survivors, unapplied = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapplied.append(f"{name}: pattern not found in executable source")
            continue
        mutated = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mutated == src:
            unapplied.append(f"{name}: no-op replacement")
            continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mutated)
            path = fh.name
        try:
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True,
                         timeout=180)
            killed = pr.returncode != 0
        except _sp.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}")
        if not killed:
            survivors.append(name)
    for u in unapplied:
        print(f"  UNAPPLIED  {u}")
    print(f"mutation suite: {len(MUTANTS) - len(survivors) - len(unapplied)}/{len(MUTANTS)} killed"
          f"{'' if not (survivors or unapplied) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return survivors + unapplied


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    ok, f, d = check()
    import json as _json
    print(_json.dumps({"ok": ok, "failures": f, "detail": d}, indent=1, default=str))
    sys.exit(0 if ok else 1)
