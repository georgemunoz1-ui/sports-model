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
# Header depth is pinned DELIBERATELY at 1-6 (every markdown heading level). An earlier bound of
# 1-3 meant `#### 2026-08-23` was invisible while `## 2026-08-23` failed on a byte-identical tree —
# a rule nobody could predict from outside. Fixtures now pin both sides of the bound.
DATE_HEADER = re.compile(r"^#{1,6}\s*(\d{4}-\d{2}-\d{2})", re.M)
# Directories searched for journal-SHAPED files (not just files literally named progress.md). Kept
# shallow on purpose: docs/lessons, docs/experiments and docs/audits hold dated records that are
# NOT handoff journals, and sweeping them in would make rule 1 fire constantly and get disabled.
JOURNAL_DIRS = ("", "docs")
JOURNAL_SHAPE_MIN_ENTRIES = 3
# Widening discovery from "named progress.md" to "journal-shaped" catches a renamed rival journal,
# and also catches legitimate dated RECORDS that are not handoff journals at all (AUTHORIZATIONS.md
# is a standing-decisions log). Rather than guess, a file DECLARES itself. A shape-matched file with
# no declaration FAILS — so the rule cannot be evaded by renaming, and a real record costs one line
# once. The declaration is deliberately NOT honoured on the canonical journal: pointing it at the
# handoff file would disable every rule here in a single edit.
NOT_A_JOURNAL_MARKERS = ("NOT A HANDOFF JOURNAL",)
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
        return None, DEFAULT_LOADER_LINES, None, "NO_SPEC_TEXT"
    cands = []
    for line in spec_text.splitlines():
        if "progress.md" not in line or "read" not in line.lower():
            continue
        m = re.search(r"`([^`]*progress\.md)`", line) or re.search(r"([\w./-]*progress\.md)", line)
        if not m:
            continue
        n = re.search(r"last\s*~?\s*(\d+)\s*lines", line, re.I)
        numbered = bool(re.match(r"\s*\d+[.)]", line))
        cands.append((numbered, m.group(1), int(n.group(1)) if n else DEFAULT_LOADER_LINES,
                      line.strip()))
    if not cands:
        return None, DEFAULT_LOADER_LINES, None, "NO_CANDIDATE_LINE"
    # A NUMBERED bootstrap step beats loose prose. First-line-wins let any earlier mention shadow
    # the real step — including the "the journal used to live at X" note a migration leaves behind,
    # i.e. the parse was weakest exactly when it mattered most.
    steps = [c for c in cands if c[0]]
    pool = steps or cands
    paths = {c[1].lstrip("./") for c in pool}
    if len(paths) > 1:
        return pool[0][1], pool[0][2], pool[0][3], f"AMBIGUOUS_INSTRUCTION:{sorted(paths)}"
    return pool[0][1], pool[0][2], pool[0][3], None


def find_journals(root=None, reader=None):
    """Every journal-SHAPED file, not merely every file named progress.md.

    The name test alone was both the documented and the implemented behaviour, and it makes rule 1
    trivially evadable: a live rival journal called docs/handoff.md or docs/journal.md is invisible,
    and noticing handoff state accumulating where nothing reads it is the whole point of rule 1. So
    a markdown file in the searched directories ALSO counts as a journal when it carries at least
    JOURNAL_SHAPE_MIN_ENTRIES dated section headers.

    Content comes from `reader` (committed bytes by default), for the same reason every other rule
    here uses committed content: a cold clone sees commits, not a working tree."""
    root = root or BASE
    read = reader or committed_text
    out = set()
    for d in JOURNAL_DIRS:
        full = os.path.join(root, d) if d else root
        if not os.path.isdir(full):
            continue
        for fn in sorted(os.listdir(full)):
            path = os.path.join(full, fn)
            if not os.path.isfile(path) or not fn.lower().endswith(".md"):
                continue
            rel = os.path.relpath(path, root)
            if fn.lower() == "progress.md":
                out.add(rel)
                continue
            try:
                txt = read(rel)
            except Exception:
                txt = None
            if txt and len(DATE_HEADER.findall(txt)) >= JOURNAL_SHAPE_MIN_ENTRIES:
                out.add(rel)
    # a file literally named progress.md ANYWHERE still counts, wherever it is hiding
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [x for x in dirnames if x not in (".git", "node_modules", "__pycache__")]
        for fn in filenames:
            if fn.lower() == "progress.md":
                out.add(os.path.relpath(os.path.join(dirpath, fn), root))
    return sorted(out)


def is_redirect(text):
    return bool(text) and any(m in text for m in REDIRECT_MARKERS)


def declares_not_a_journal(text):
    """A dated file that states it is not a handoff journal. One line, committed, auditable."""
    return bool(text) and any(m in text for m in NOT_A_JOURNAL_MARKERS)


def redirect_state_after_marker(text):
    """Dated entries appearing AFTER the redirect marker — i.e. the closed file is live again.

    POSITION-DEPENDENT BY CONSTRUCTION, and therefore NOT sufficient on its own: put the marker at
    the BOTTOM of the file and every live entry sits above it, so this returns nothing while the
    file is being actively written. `check` therefore ALSO compares each redirect's newest entry
    date against the canonical journal's, which no marker placement can dodge."""
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
    def _class(j, t):
        if t is None:
            return "UNCOMMITTED"
        if is_redirect(t):
            return "REDIRECT"
        # the canonical journal can NEVER declare itself out of its own rules
        if j != canonical and declares_not_a_journal(t):
            return "DECLARED_NOT_A_JOURNAL"
        return "LIVE"
    detail["journals"] = {j: _class(j, t) for j, t in texts.items()}
    live = [j for j, t in texts.items() if _class(j, t) == "LIVE"]
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
    if date is not None and idx is not None:
        body = [l for l in ctext.splitlines()[idx + 1:]
                if l.strip() and not DATE_HEADER.match(l)]
        detail["latest_entry_body_lines"] = len(body)
        if not body:
            fails.append(f"EMPTY_LATEST_ENTRY — the newest dated section ({date}) has no body. A "
                         f"bare header satisfies every structural rule here AND holds the staleness "
                         f"age at 0 forever, silencing the only freshness signal indefinitely")
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
    lpath, llines, lraw, lwhy = parse_loader(spec)
    detail["loader"] = {"spec_file": loader_spec or LOADER_SPEC, "path": lpath,
                        "lines": llines, "instruction": lraw, "parse_note": lwhy}
    if lwhy and lwhy.startswith("AMBIGUOUS_INSTRUCTION"):
        fails.append(f"AMBIGUOUS_LOADER_INSTRUCTION — {loader_spec or LOADER_SPEC} names more than "
                     f"one journal to read ({lwhy.split(':', 1)[1]}); which file a cold session "
                     f"bootstraps from must not depend on which line a reader notices first")
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
    # POSITION-INDEPENDENT: a closed journal whose newest dated entry is NEWER than the canonical
    # journal's is being written to, wherever its marker sits. This is the rule that actually holds;
    # the marker scan above is a more specific signal kept for its better message.
    stale_canon = {}
    for j, t in texts.items():
        if j == canonical or not is_redirect(t):
            continue
        rdate, _ = latest_entry(t)
        if rdate and date and rdate > date:
            stale_canon[j] = rdate
    detail["redirects_newer_than_canonical"] = stale_canon
    for j, rdate in stale_canon.items():
        fails.append(f"REDIRECT_NEWER_THAN_CANONICAL — closed journal {j} carries an entry dated "
                     f"{rdate}, NEWER than the canonical journal's {date}. Handoff state is being "
                     f"written to a file nothing reads, which is the 2026-08-22 defect; marker "
                     f"placement cannot hide this because no marker position is consulted")
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

    # --- INDEPENDENT REVIEW 2026-08-22, blocker 1: a redirect whose MARKER SITS AT THE BOTTOM has
    #     every live entry above it, so the marker scan returns nothing while the file is being
    #     actively written. Position-independent rule: a redirect newer than canonical FAILS.
    rogue_bottom = ("## 2026-08-25\n- live entries written here\n\n"
                    "## JOURNAL SPLIT CLOSED\nDo not append here again.")
    if redirect_state_after_marker(rogue_bottom):
        fails.append("the marker fixture is wrong — this shape must be invisible to the scan, which "
                     "is the whole point of the position-independent rule below")
    ok, f, d = run(dict(base, **{"docs/progress.md": "## 2026-08-20\n- old canonical entry",
                                 "progress.md": rogue_bottom}),
                   ["docs/progress.md", "progress.md"])
    if ok or not any("REDIRECT_NEWER_THAN_CANONICAL" in x for x in f):
        fails.append(f"a closed redirect dated FIVE DAYS NEWER than the canonical journal passed "
                     f"because its marker sat at the bottom: {f}")
    if not d.get("redirects_newer_than_canonical"):
        fails.append("the newer-redirect detail was not recorded")
    # ... and a redirect OLDER than canonical is fine — a closed journal keeps its past (R6)
    ok, f, _ = run(base, ["docs/progress.md", "progress.md"])
    if not ok:
        fails.append(f"a redirect older than canonical was rejected: {f}")

    # --- blocker 2: find_journals is executed by the suite, against the REAL implementation.
    import tempfile as _tf2
    with _tf2.TemporaryDirectory() as _td3:
        os.makedirs(os.path.join(_td3, "docs"))
        os.makedirs(os.path.join(_td3, "docs", "lessons"))
        open(os.path.join(_td3, "docs", "progress.md"), "w").write(good_journal)
        open(os.path.join(_td3, "progress.md"), "w").write(redirect)
        # a journal-SHAPED file under another NAME — invisible to a name-only search
        open(os.path.join(_td3, "docs", "handoff.md"), "w").write(
            "## 2026-08-20\n- a\n## 2026-08-21\n- b\n## 2026-08-22\n- c\n")
        # a dated RECORD that is not a handoff journal must NOT be swept in
        open(os.path.join(_td3, "docs", "lessons", "07-x.md"), "w").write(
            "## 2026-08-20\n## 2026-08-21\n## 2026-08-22\n")
        found = find_journals(_td3, reader=lambda rel: open(os.path.join(_td3, rel)).read())
        if "docs/handoff.md" not in found:
            fails.append(f"find_journals missed a journal-SHAPED file under another name — rule 1 "
                         f"is evadable by renaming: {found}")
        if "progress.md" not in found or "docs/progress.md" not in found:
            fails.append(f"find_journals missed a file literally named progress.md: {found}")
        if "docs/lessons/07-x.md" in found:
            fails.append(f"find_journals swept in a dated RECORD that is not a handoff journal: "
                         f"{found}")
        # a nested progress.md is still found wherever it hides
        os.makedirs(os.path.join(_td3, "notes", "deep"))
        open(os.path.join(_td3, "notes", "deep", "progress.md"), "w").write(good_journal)
        if "notes/deep/progress.md" not in find_journals(
                _td3, reader=lambda rel: open(os.path.join(_td3, rel)).read()):
            fails.append("a nested progress.md escaped discovery")

    # --- the NOT-A-JOURNAL declaration: explicit, one line, and NOT usable on the canonical file
    record = "# STANDING RECORD\n\nNOT A HANDOFF JOURNAL.\n## 2026-08-20\n- a\n## 2026-08-21\n- b\n"
    ok, f, d = run(dict(base, **{"AUTHORIZATIONS.md": record}),
                   ["docs/progress.md", "progress.md", "AUTHORIZATIONS.md"])
    if not ok:
        fails.append(f"a dated RECORD that declares itself not a handoff journal was counted as a "
                     f"rival journal: {f}")
    if d["journals"].get("AUTHORIZATIONS.md") != "DECLARED_NOT_A_JOURNAL":
        fails.append(f"the declaration was not recorded: {d['journals']}")
    # ... an UNDECLARED dated file IS a rival, so renaming cannot evade rule 1
    undecl = "# SOMETHING\n## 2026-08-20\n- a\n## 2026-08-21\n- b\n## 2026-08-22\n- c\n"
    ok, f, _ = run(dict(base, **{"docs/handoff.md": undecl}),
                   ["docs/progress.md", "progress.md", "docs/handoff.md"])
    if ok or not any("NOT_EXACTLY_ONE_CANONICAL_JOURNAL" in x for x in f):
        fails.append(f"an UNDECLARED journal-shaped rival passed — rule 1 evadable by renaming: {f}")
    # ... and the canonical journal cannot declare ITSELF out of its own rules
    ok, f, d = run(dict(base, **{"docs/progress.md": "NOT A HANDOFF JOURNAL.\n" + good_journal,
                                 "progress.md": undecl}),
                   ["docs/progress.md", "progress.md"])
    if d["journals"].get("docs/progress.md") == "DECLARED_NOT_A_JOURNAL":
        fails.append("the CANONICAL journal declared itself out of its own rules — one line would "
                     "then disable every check in this module")
    if ok:
        fails.append("a tree with the canonical journal self-excluded and a live rival passed")

    # --- an EMPTY newest entry silences staleness forever
    ok, f, d = run(dict(base, **{"docs/progress.md": good_journal.rsplit("- newest entry", 1)[0]}),
                   ["docs/progress.md", "progress.md"])
    if ok or not any("EMPTY_LATEST_ENTRY" in x for x in f):
        fails.append(f"a dated header with NO BODY passed every rule and pinned the age at 0: {f}")
    if run(base, ["docs/progress.md", "progress.md"])[2].get("latest_entry_body_lines", 0) < 1:
        fails.append("a real entry was reported as having no body")

    # --- DATE_HEADER depth is PINNED on both sides of its bound
    if latest_entry("#### 2026-08-23\n- x")[0] != "2026-08-23":
        fails.append("an H4 dated header was invisible — the depth bound must be pinned, and a "
                     "rule nobody can predict from outside is worse than either bound")
    if latest_entry("####### 2026-08-23\n- x")[0] is not None:
        fails.append("seven hashes is not a markdown heading and must not read as one")
    if latest_entry("2026-08-23 — not a header\n")[0] is not None:
        fails.append("a bare date line was read as a section header")

    # 6. helper-level pins
    if latest_entry("## 2026-08-01\n## 2026-08-22\n## 2026-08-10")[0] != "2026-08-22":
        fails.append("latest_entry does not return the NEWEST date (order-independent)")
    if latest_entry("")[0] is not None:
        fails.append("latest_entry invented a date from nothing")
    if parse_loader(AG) != ("docs/progress.md", 30, AG.strip(), None):
        fails.append(f"parse_loader wrong: {parse_loader(AG)}")
    # a NUMBERED bootstrap step beats an earlier prose mention (the migration-note shadow)
    shadowed = ("Historical note: the journal used to live at `notes/progress.md`; read that only "
                "for archaeology.\n" + AG)
    if parse_loader(shadowed)[0] != "notes/progress.md" and parse_loader(shadowed)[0] != "docs/progress.md":
        fails.append(f"parse_loader picked neither candidate: {parse_loader(shadowed)}")
    if parse_loader(shadowed)[0] != "docs/progress.md":
        fails.append(f"an earlier PROSE mention shadowed the numbered bootstrap step: "
                     f"{parse_loader(shadowed)[0]!r} — the parse is weakest exactly when a journal "
                     f"migration has left a stale note behind")
    # two NUMBERED steps naming DIFFERENT journals is ambiguous, and ambiguity is a failure
    amb = "3. Read `docs/progress.md` (last ~30 lines)\n4. Read `docs/other_progress.md` first"
    if not (parse_loader(amb)[3] or "").startswith("AMBIGUOUS_INSTRUCTION"):
        fails.append(f"two numbered steps naming different journals were not flagged ambiguous: "
                     f"{parse_loader(amb)}")
    ok, f, _ = run(dict(base, **{"AGENTS.md": amb}), ["docs/progress.md", "progress.md"])
    if ok or not any("AMBIGUOUS_LOADER_INSTRUCTION" in x for x in f):
        fails.append(f"an ambiguous bootstrap instruction passed: {f}")
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
    ("redirects counted as live", '        if is_redirect(t):\n            return "REDIRECT"',
     '        if False:\n            return "REDIRECT"'),
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
    # --- INDEPENDENT REVIEW 2026-08-22
    ("position-independent redirect rule removed (marker at the bottom hides live entries)",
     "        if rdate and date and rdate > date:", "        if False:"),
    ("redirect-newer comparison inverted", "        if rdate and date and rdate > date:",
     "        if rdate and date and rdate < date:"),
    ("find_journals: shape clause removed, name-only search restored",
     "            if txt and len(DATE_HEADER.findall(txt)) >= JOURNAL_SHAPE_MIN_ENTRIES:",
     "            if False:"),
    ("find_journals: shallow scope widened to sweep in dated records",
     'JOURNAL_DIRS = ("", "docs")', 'JOURNAL_DIRS = ("", "docs", "docs/lessons")'),
    ("find_journals: nested progress.md no longer discovered",
     "            if fn.lower() == \"progress.md\":\n                out.add(os.path.relpath(os.path.join(dirpath, fn), root))",
     "            if False:\n                out.add(os.path.relpath(os.path.join(dirpath, fn), root))"),
    ("parse_loader: first-line-wins restored (a stale migration note shadows the real step)",
     "    steps = [c for c in cands if c[0]]\n    pool = steps or cands", "    pool = cands"),
    ("parse_loader: ambiguity no longer a failure", "    if len(paths) > 1:", "    if False:"),
    ("empty newest entry tolerated", "        if not body:", "        if False:"),
    ("DATE_HEADER depth silently narrowed", 'r"^#{1,6}\\s*(\\d{4}-\\d{2}-\\d{2})"',
     'r"^#{1,3}\\s*(\\d{4}-\\d{2}-\\d{2})"'),
    ("DATE_HEADER matches a bare date line", 'r"^#{1,6}\\s*(\\d{4}-\\d{2}-\\d{2})"',
     'r"^#{0,6}\\s*(\\d{4}-\\d{2}-\\d{2})"'),
    ("not-a-journal declaration honoured on the CANONICAL journal (disables everything)",
     "        if j != canonical and declares_not_a_journal(t):", "        if declares_not_a_journal(t):"),
    ("not-a-journal declaration ignored, so real records read as rival journals",
     "        if j != canonical and declares_not_a_journal(t):", "        if False:"),
    ("undeclared shape-matched rival treated as declared",
     "    return bool(text) and any(m in text for m in NOT_A_JOURNAL_MARKERS)", "    return True"),
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
