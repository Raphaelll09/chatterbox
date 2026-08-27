#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enforce the layer boundary: the runtime package must never import the research package.

    L1 RUN    chatterbox/   everything needed to make the demonstrator speak
    L3 STUDY  research/     profiling, benchmarking, power measurement
              tests/

    L1 must never import L3.   L3 may import L1 freely.

Run it directly, or via tests/test_layer_boundary.py:

    python scripts/check_layers.py          # exit 0 = clean, 1 = violations found

Why this exists
---------------
Before the release reorganisation, chatterbox/synth.py, chatterbox/cli.py and both synthesis
backends imported the research package at module scope. Deleting research/ did not disable
profiling -- it made the runtime package unimportable. chatterbox/instrumentation.py is the seam
that fixed it; this script is what stops the boundary rotting again.

See docs/release/STRUCTURE_AUDIT.md Sec4 and chatterbox/instrumentation.py.

The tolerated exceptions
------------------------
chatterbox/cli.py imports research code in five places, every one of them *inside a function* and
inside a mode gate (--benchmark, --p4-sweep, --join, --export-xlsx, --profile). Those modes are
research modes: they cannot do anything useful without the research package, and each import is
wrapped so its absence produces an actionable message rather than a traceback.

They are whitelisted by (file, module) pair below, and ONLY at function scope -- moving any of them
to module scope makes this script fail, which is the point.
"""
import ast
import os
import pathlib
import sys

L1_ROOT = pathlib.Path("chatterbox")
L3_TOPLEVEL = ("research", "tests", "tools")

# (L1 file, imported module) pairs allowed at FUNCTION scope only. Keep this list short and
# justified; every entry is a hole in the boundary.
ALLOWED_FUNCTION_SCOPE = {
    ("chatterbox/cli.py", "research.profiling"),
    ("chatterbox/cli.py", "research.profiling.join"),
    ("chatterbox/cli.py", "research.benchmark.runner"),
    ("chatterbox/cli.py", "research.benchmark.p4_sweep"),
    ("chatterbox/cli.py", "research.benchmark.export_to_xlsx"),
}


def _imports(tree):
    """Yield (node, module_name) for every import statement in the tree."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node, alias.name
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import, which can never reach another top-level package
            if node.module and node.level == 0:
                yield node, node.module


def violations(root=None):
    """Yield a human-readable line per boundary violation."""
    root = pathlib.Path(root) if root else L1_ROOT
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            yield "{}: could not parse: {}".format(rel, exc)
            continue

        # Statements directly in the module body are module scope; everything else is nested
        # inside a function or class, i.e. only executed when that code runs.
        module_scope = {id(n) for n in ast.walk(tree)} - {
            id(n) for fn in ast.walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            for n in ast.walk(fn) if n is not fn
        }

        for node, module in _imports(tree):
            if module.split(".")[0] not in L3_TOPLEVEL:
                continue
            at_module_scope = id(node) in module_scope
            if not at_module_scope and (rel, module) in ALLOWED_FUNCTION_SCOPE:
                continue
            scope = "module scope" if at_module_scope else "function scope, not whitelisted"
            yield "{}:{}: L1 imports L3 ({}): {}".format(rel, node.lineno, scope, module)


def main():
    # Run from the repository root regardless of where the script was invoked from.
    os.chdir(pathlib.Path(__file__).resolve().parents[1])
    found = list(violations())
    if found:
        print("Layer boundary VIOLATED -- chatterbox/ (L1) must not import research/ (L3):\n")
        for line in found:
            print("  " + line)
        print("\nRoute the call through chatterbox/instrumentation.py, or move the code to "
              "research/.\nSee docs/release/STRUCTURE_AUDIT.md Sec4.")
        return 1
    print("OK: no L1 -> L3 imports (chatterbox/ does not import research/)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
