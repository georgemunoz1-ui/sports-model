"""A unique (path, module_id) registry. Creating over an occupied path is refused.

WHY A BANNER WAS NOT ENOUGH. On 2026-08-25 I overwrote harness/acquisition_ladder.py with a
different module and every gate stayed green, because "the selftest at that path exits zero" is true
of ANY module living there. I added a banner check — each selftest names its own file — which
catches a replacement that forgets to rename its own output string. It does not catch a replacement
that renames everything consistently, which is exactly what a careful clobber looks like.

What actually distinguishes "this file changed" from "a different file now lives here" is IDENTITY,
declared by the module and registered once:

    MODULE_ID = "route_ladder_v1"        # stable, unique, never reused

The manifest maps path -> module_id. Three rules:

  1. A path may hold exactly one module_id, forever. A file whose declared id differs from its
     registered id is a CLOBBER, not an edit, and is refused.
  2. A module_id may appear at exactly one path. Two files claiming one identity is a DUPLICATE,
     and it is how a fork silently becomes the original.
  3. Creating at an occupied path requires an explicit REPLACEMENT operation naming what is being
     replaced and why. Absent that, the write is refused — the point is that clobbering must be a
     decision someone made, not a side effect of choosing a natural filename.
"""

import json
import hashlib
import os
import re
import sys

MANIFEST_PATH = "data/registry/module_manifest.json"

OK = "MANIFEST_OK"
CLOBBER = "REFUSED_CLOBBER_DIFFERENT_MODULE_AT_A_REGISTERED_PATH"
DUPLICATE = "REFUSED_DUPLICATE_MODULE_ID"
UNDECLARED = "MODULE_DECLARES_NO_MODULE_ID"
OCCUPIED = "REFUSED_CREATE_OVER_AN_OCCUPIED_PATH"
UNREGISTERED = "MODULE_NOT_IN_MANIFEST"
MISSING_FILE = "REGISTERED_PATH_HAS_NO_FILE"

CREATE = "CREATE"
REPLACE = "REPLACE"
OPERATIONS = (CREATE, REPLACE)

_ID_RE = re.compile(r'^MODULE_ID\s*=\s*["\']([A-Za-z0-9_]+)["\']', re.M)


def declared_id(path_or_text, is_text=False):
    """The MODULE_ID a file declares, or None."""
    try:
        text = path_or_text if is_text else open(path_or_text).read()
    except OSError:
        return None
    m = _ID_RE.search(text)
    return m.group(1) if m else None


EXEMPT_PATH = "data/registry/module_manifest_exempt.json"


def load_exempt(path=EXEMPT_PATH):
    """Paths deliberately outside the manifest, each with a stated reason.

    The only current exemption class is a PINNED MODEL SOURCE. Those files are frozen by
    harness/model_registry.py, which hashes their bytes against an authorized pin — a strictly
    stronger guarantee than a declared identity, and one that a MODULE_ID line would break by
    changing the very bytes it protects. An exemption must be listed and justified; not declaring an
    id is not an exemption.
    """
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return json.load(fh).get("exempt", {})


def load(manifest_path=MANIFEST_PATH):
    if not os.path.exists(manifest_path):
        return {}
    with open(manifest_path) as fh:
        return json.load(fh).get("modules", {})


def save(modules, manifest_path=MANIFEST_PATH):
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    document = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {}
    document.update(schema="ops.module_manifest.v1", modules=modules)
    with open(manifest_path, "w") as fh:
        json.dump(document, fh, indent=1, sort_keys=True)


def check_write(path, new_module_id, operation, modules, replaces=None, reason=None):
    """May this write proceed? The whole point is that a clobber must be a decision, not a default."""
    if operation not in OPERATIONS:
        return False, {"code": "UNKNOWN_OPERATION", "operation": operation}
    if not new_module_id:
        return False, {"code": UNDECLARED, "path": path}
    # rule 2: one identity, one path
    for p, mid in (modules or {}).items():
        if mid == new_module_id and p != path:
            return False, {"code": DUPLICATE, "module_id": new_module_id, "registered_at": p,
                           "attempted_at": path,
                           "note": "two files claiming one identity is how a fork silently becomes "
                                   "the original"}
    registered = (modules or {}).get(path)
    if registered is None:
        return True, {"code": OK, "path": path, "module_id": new_module_id, "operation": CREATE}
    # rule 1 + 3: the path is occupied
    if registered == new_module_id:
        return True, {"code": OK, "path": path, "module_id": new_module_id, "operation": "EDIT",
                      "note": "same identity at the same path: an edit, which needs no ceremony"}
    if operation != REPLACE:
        return False, {"code": OCCUPIED, "path": path, "registered_module_id": registered,
                       "attempted_module_id": new_module_id,
                       "note": "a different module already lives here. Creating over it is refused; "
                               "an explicit REPLACE naming what is being replaced is required."}
    if replaces != registered:
        return False, {"code": CLOBBER, "path": path, "registered_module_id": registered,
                       "declared_replaces": replaces,
                       "note": "a REPLACE must name the exact module it displaces, so the record "
                               "shows what was lost rather than only what arrived"}
    if not reason:
        return False, {"code": CLOBBER, "path": path,
                       "note": "a REPLACE must state why the displaced module is no longer wanted"}
    return True, {"code": OK, "path": path, "module_id": new_module_id, "operation": REPLACE,
                  "replaces": registered, "reason": reason}


def audit(manifest_path=MANIFEST_PATH, root="harness", exempt_path=None):
    """Every registered path still holds its registered module, and no id appears twice."""
    modules = load(manifest_path)
    problems, seen = [], {}
    for path, mid in sorted(modules.items()):
        if mid in seen:
            problems.append({"code": DUPLICATE, "module_id": mid, "paths": [seen[mid], path]})
        seen[mid] = path
        if not os.path.exists(path):
            problems.append({"code": MISSING_FILE, "path": path, "module_id": mid})
            continue
        actual = declared_id(path)
        if actual is None:
            problems.append({"code": UNDECLARED, "path": path, "registered": mid})
        elif actual != mid:
            problems.append({"code": CLOBBER, "path": path, "registered": mid, "declares": actual,
                             "note": "the file at this path is a DIFFERENT module from the one "
                                     "registered here"})
    # Capability registration carries a content pin as well as an identity.
    document = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {}
    capabilities = document.get("capabilities", {})
    required = {"harness/current_sports_data.py"} & set(modules)
    for path in sorted(required | set(capabilities)):
        entry = capabilities.get(path, {})
        fields = ("module_id", "version", "owner", "source_repository", "source_base_commit",
                  "sha256", "interface", "access_method", "license", "allowed_usage", "runtime_role")
        if any(not entry.get(field) for field in fields):
            problems.append({"code": "CAPABILITY_METADATA_INCOMPLETE", "path": path})
            continue
        if entry["module_id"] != modules.get(path):
            problems.append({"code": "CAPABILITY_ID_MISMATCH", "path": path})
        if not os.path.exists(path) or hashlib.sha256(open(path, "rb").read()).hexdigest() != entry["sha256"]:
            problems.append({"code": "CAPABILITY_DIGEST_MISMATCH", "path": path})
    # AN UNDECLARED FILE MUST NOT ESCAPE. Checking only files that declare an id would let any
    # module opt out of the manifest by simply not declaring one — the manifest would then police
    # exactly the files that were already cooperating.
    exempt = set(load_exempt(exempt_path or EXEMPT_PATH))
    on_disk = sorted(f"{root}/{f}" for f in os.listdir(root)
                     if f.endswith(".py")) if os.path.isdir(root) else []
    for path in on_disk:
        if path in exempt or path in modules:
            continue
        problems.append({"code": UNREGISTERED, "path": path, "declares": declared_id(path),
                         "note": "every module under harness/ is either registered with a "
                                 "MODULE_ID or explicitly exempt. Silence is not an exemption."})
    return {"status": OK if not problems else "MANIFEST_REFUSED", "n_modules": len(modules),
            "n_problems": len(problems), "problems": problems}


MODULE_ID = "module_manifest"


# =================================================================================================
def selftest():
    f = []
    M = {"harness/a.py": "alpha", "harness/b.py": "beta"}

    # a fresh path is a plain CREATE
    ok, d = check_write("harness/c.py", "gamma", CREATE, M)
    if not ok or d["operation"] != CREATE:
        f.append(f"a fresh path must accept a CREATE, got {d}")

    # THE ACTUAL DEFECT: creating over an occupied path is refused
    ok2, d2 = check_write("harness/a.py", "route_ladder_v1", CREATE, M)
    if ok2 or d2["code"] != OCCUPIED:
        f.append(f"CREATE over an occupied path must be refused, got {d2}")
    if d2.get("registered_module_id") != "alpha":
        f.append("the refusal must name the module already there")

    # an explicit REPLACE that names what it displaces AND why is allowed
    ok3, d3 = check_write("harness/a.py", "route_ladder_v1", REPLACE, M,
                          replaces="alpha", reason="superseded by the v1.0 route ladder")
    if not ok3 or d3["operation"] != REPLACE or d3.get("replaces") != "alpha":
        f.append(f"a complete REPLACE must be allowed, got {d3}")
    # ...and an incomplete one is not
    for kw in ({"replaces": None}, {"replaces": "something_else"}, {"reason": None},
               {"reason": ""}):
        args = dict(replaces="alpha", reason="because")
        args.update(kw)
        okb, db = check_write("harness/a.py", "route_ladder_v1", REPLACE, M, **args)
        if okb or db["code"] != CLOBBER:
            f.append(f"an incomplete REPLACE must be refused: {kw} -> {db}")

    # editing in place under the SAME identity needs no ceremony
    ok4, d4 = check_write("harness/a.py", "alpha", CREATE, M)
    if not ok4 or d4["operation"] != "EDIT":
        f.append(f"same id at same path is an edit, got {d4}")

    # one identity, one path
    ok5, d5 = check_write("harness/z.py", "alpha", CREATE, M)
    if ok5 or d5["code"] != DUPLICATE:
        f.append(f"a duplicate module id must be refused, got {d5}")
    if d5.get("registered_at") != "harness/a.py":
        f.append("the duplicate refusal must name where the id already lives")
    # ...even under REPLACE
    if check_write("harness/z.py", "alpha", REPLACE, M, replaces="x", reason="y")[0]:
        f.append("REPLACE must not launder a duplicate identity")

    # a module that declares no identity cannot be registered at all
    ok6, d6 = check_write("harness/q.py", None, CREATE, M)
    if ok6 or d6["code"] != UNDECLARED:
        f.append("a module with no MODULE_ID must be refused")

    # declared_id parses a declaration and only a declaration
    if declared_id('MODULE_ID = "route_ladder_v1"\n', is_text=True) != "route_ladder_v1":
        f.append("a declared id must be readable")
    if declared_id("MODULE_ID = 'x_y_1'\n", is_text=True) != "x_y_1":
        f.append("single quotes are a declaration too")
    for txt in ("# MODULE_ID = \"commented\"\n", "MY_MODULE_ID = \"nested\"\n", "", "x = 1\n"):
        if declared_id(txt, is_text=True) is not None:
            f.append(f"not a declaration: {txt!r} -> {declared_id(txt, is_text=True)}")
    if declared_id("/nonexistent/path/xyz.py") is not None:
        f.append("an unreadable file declares nothing")

    # an undeclared file must not escape the manifest by declining to declare
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "declared.py"), "w").write('MODULE_ID = "declared"\n')
        open(os.path.join(td, "silent.py"), "w").write("x = 1\n")
        mp = os.path.join(td, "m.json")
        save({f"{td}/declared.py": "declared"}, mp)
        r = audit(mp, root=td)
        unreg = [x for x in r["problems"] if x["code"] == UNREGISTERED]
        if not any(x["path"].endswith("silent.py") for x in unreg):
            f.append("a module that declares no id must still be reported as unregistered")
        if any(x["path"].endswith("declared.py") for x in unreg):
            f.append("a registered module must not be reported unregistered")
        # ...and an explicit exemption removes it, while silence does not
        with open(os.path.join(td, "ex.json"), "w") as fh:
            json.dump({"exempt": {f"{td}/silent.py": "pinned model source"}}, fh)
        r2 = audit(mp, root=td, exempt_path=os.path.join(td, "ex.json"))
        if any(x["code"] == UNREGISTERED for x in r2["problems"]):
            f.append("an explicitly exempt path must not be reported unregistered")

    print("module_manifest selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("a module escapes the manifest by not declaring an id",
     '        if path in exempt or path in modules:', "        if True:"),
    ("silence becomes an exemption",
     "    exempt = set(load_exempt(exempt_path or EXEMPT_PATH))", "    exempt = set()"),
    ("creating over an occupied path is allowed again",
     "    if operation != REPLACE:", "    if False:"),
    ("a REPLACE need not name what it displaces",
     "    if replaces != registered:", "    if False:"),
    ("a REPLACE need not give a reason",
     "    if not reason:", "    if False:"),
    ("two files may claim one module identity",
     "        if mid == new_module_id and p != path:", "        if False:"),
    ("a duplicate identity is launderable through REPLACE",
     "    for p, mid in (modules or {}).items():", "    for p, mid in {}.items():"),
    ("a module may be registered with no declared identity",
     "    if not new_module_id:", "    if False:"),
    ("a commented-out declaration counts as a declaration",
     "re.compile(r'^MODULE_ID", "re.compile(r'MODULE_ID"),
    ("the occupied-path refusal stops naming the module already there",
     '        return False, {"code": OCCUPIED, "path": path, "registered_module_id": registered,',
     '        return False, {"code": OCCUPIED, "path": path, "registered_module_id": None,'),
    ("the duplicate refusal stops naming where the id already lives",
     '            return False, {"code": DUPLICATE, "module_id": new_module_id, "registered_at": p,',
     '            return False, {"code": DUPLICATE, "module_id": new_module_id, "registered_at": None,'),
]


def mutation_suite():
    src = open(__file__).read()
    # BASELINE FIRST. A failing selftest makes every mutant look killed, so a broken fixture reports
    # a perfect score. Caught 2026-08-25 when module_manifest printed 11/11 while its own selftest
    # was failing.
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        _base = selftest()
    if not _base:
        print("  BASELINE_FAILING  the unmutated selftest does not pass; every 'kill' below is "
              "meaningless until it does")
        print(_b.getvalue().strip())
        return False
    body = src[:src.index("MUTANTS = [")]
    killed = 0
    for name, old, new in MUTANTS:
        if old not in src:
            print("  UNAPPLIED ", name + ": pattern not found")
            continue
        if old not in body:
            print("  SELF_TARGETED ", name + ": pattern occurs only inside the MUTANTS list")
            continue
        ns = {"__file__": __file__, "__name__": "mutant"}
        try:
            exec(compile(src.replace(old, new, 1), "<mutant>", "exec"), ns)
            ok = ns["selftest"]()
        except Exception:
            ok = False
        print(("  KILLED    " if not ok else "  SURVIVED  ") + name)
        killed += not ok
    print(f"mutation suite: {killed}/{len(MUTANTS)} killed"
          + ("" if killed == len(MUTANTS) else "  — SURVIVORS MEAN DECORATIVE FIXTURES"))
    return killed == len(MUTANTS)


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if "--audit" in sys.argv:
        r = audit()
        print(json.dumps(r, indent=1))
        sys.exit(0 if r["status"] == OK else 1)
    print(__doc__)
