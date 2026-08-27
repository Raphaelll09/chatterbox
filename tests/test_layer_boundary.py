"""The layer boundary: chatterbox/ (L1 RUN) must never import research/ (L3 STUDY).

Two independent checks, because they fail for different reasons:

  test_no_l1_imports_l3            -- static, AST-based. Catches a new import the moment it is
                                      written, even one guarded by a mode flag that never runs
                                      under pytest.
  test_l1_imports_without_research -- dynamic. Actually removes the research package and imports
                                      the runtime modules. Catches anything static analysis
                                      misses: a __getattr__ hook, an importlib call, a transitive
                                      import through a third module.

Both of these FAILED before the release reorganisation (docs/release/STRUCTURE_AUDIT.md Sec4.3):
chatterbox.synth, chatterbox.cli, chatterbox.synthesis.registry and the Piper backend all raised
ImportError with tools/ absent. They are the regression tests for that.
"""
import importlib
import importlib.abc
import importlib.util
import os
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# The runtime modules that must stand alone. chatterbox.gui.app is deliberately absent: it needs a
# Tk installation, which is a separate concern from the layer boundary.
L1_MODULES = [
    "chatterbox.synth",
    "chatterbox.cli",
    "chatterbox.state",
    "chatterbox.instrumentation",
    "chatterbox.synthesis.registry",
    "chatterbox.synthesis.subtitles",
    "chatterbox.synthesis.backends.piper.backend",
    "chatterbox.synthesis.backends.fastspeech2_hifigan.backend",
]


def _load_checker():
    """Import scripts/check_layers.py, which is a standalone script, not a package module."""
    path = REPO_ROOT / "scripts" / "check_layers.py"
    spec = importlib.util.spec_from_file_location("check_layers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_l1_imports_l3():
    """Static check: no import of research/tests/tools from chatterbox/, except the
    function-scope, mode-gated call sites whitelisted in scripts/check_layers.py."""
    checker = _load_checker()
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        found = list(checker.violations())
    finally:
        os.chdir(cwd)
    assert found == [], "L1 -> L3 import(s):\n  " + "\n  ".join(found)


def test_checker_detects_a_real_violation(tmp_path):
    """The checker must fail on a violation -- otherwise the test above proves nothing.

    Guards against the failure mode the audit found elsewhere in this suite: a test that asserts
    on something it constructed itself and would pass even if the code under test were deleted.
    """
    checker = _load_checker()
    fake_l1 = tmp_path / "chatterbox"
    fake_l1.mkdir()
    (fake_l1 / "clean.py").write_text("import os\nfrom chatterbox import state\n", encoding="utf-8")
    assert list(checker.violations(fake_l1)) == []

    (fake_l1 / "dirty.py").write_text("import research.profiling\n", encoding="utf-8")
    found = list(checker.violations(fake_l1))
    assert len(found) == 1
    assert "dirty.py" in found[0] and "research.profiling" in found[0]


@pytest.mark.parametrize("module_name", L1_MODULES)
def test_l1_imports_without_research(module_name):
    """Dynamic check: the runtime package imports with the research package absent.

    This is the deletion test from the brief -- "deleting research/ and tests/ still leaves a
    working demonstrator" -- reduced to the part that can run in CI.
    """

    class BlockL3(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in ("research", "tools"):
                raise ImportError("L3 package %r removed (simulated)" % name)
            return None

    blocker = BlockL3()
    # Drop the module and its submodules so the import is really re-executed.
    saved = {k: v for k, v in sys.modules.items() if k == module_name or k.startswith(module_name + ".")}
    for k in saved:
        del sys.modules[k]
    sys.meta_path.insert(0, blocker)
    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        pytest.fail(
            "{} does not import without the research package: {}\n"
            "Route the profiling call through chatterbox/instrumentation.py.".format(module_name, exc)
        )
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(saved)
