"""Keep docs/CODEMAP.md honest.

CODEMAP.md is a navigational map: it is only useful while its file paths and symbol names still
match the code. This repository has twice shipped documentation that quietly stopped being true --
`chatterbox/synthesis/base.py` was documented as the operative backend contract while nothing
imported it, and `§` was documented as the sub-utterance separator while the code split on `|`.
Prose cannot be tested, but references can, so these tests check the two things that rot first:

  test_codemap_paths_exist    -- every repo-relative path mentioned in the document resolves
  test_codemap_symbols_exist  -- every row of the "Key symbols" table names a symbol that is
                                 actually defined in the file the row points at

A rename or a move then fails the suite instead of silently making the map lie.

The same checks run over the other structural documents that carry lots of paths.
"""
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CODEMAP = REPO_ROOT / "docs" / "CODEMAP.md"

# Documents whose path references should resolve. Kept deliberately short: these are the structural
# maps. Historical records (docs/research/, docs/release/) are excluded on purpose -- they describe
# the tree as it was at the time and are supposed to contain paths that no longer exist.
PATH_CHECKED_DOCS = [
    "docs/CODEMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/README.md",
    "chatterbox/README.md",
    "research/README.md",
    "tests/README.md",
]

# Backticked things that look like repo-relative paths: at least one "/" and a known extension,
# or a directory reference ending in "/".
_PATH_IN_BACKTICKS = re.compile(
    r"`([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+/?)`"
)

# A row of the "Key symbols" table:  | `symbol()` | `path/to/file.py` | description |
_SYMBOL_ROW = re.compile(
    r"^\|\s*`([A-Za-z_][A-Za-z0-9_]*)\(?\)?`\s*\|\s*`([^`]+\.py)`\s*\|",
    re.MULTILINE,
)

# Referenced but deliberately absent from the repository (documented as missing, see
# docs/README.md "Missing documents"). Listing them here keeps the test honest about why.
KNOWN_ABSENT = {
    # --- Downloaded, not committed. Real on a provisioned machine, absent from a fresh clone.
    "config/ALL_corpus/preprocess.yaml",

    # --- Generated at runtime into the gitignored profile/ scratch directory.
    "profile/per_sample.csv",
    "profile/per_sentence_results.csv",
    "profile/per_stage_results.csv",
    "profile/calibration.json",
    "profile/exports/chatterbox_paste.xlsx",

    # --- Deliberately referenced as REMOVED. A document explaining that something was deleted has
    # to be able to name it; these appear only in sentences saying exactly that.
    "chatterbox/synthesis/base.py",
    "synthesis/base.py",
    "deploy/systemd/chatterbox-gui.service",

    # --- Documented under "Not yet implemented" as never built.
    "scripts/hw_check.py",
}


# A backticked token containing "/" is only treated as a repo path if it either ends in a known
# file extension or starts with a real top-level directory. Without this, prose like `try/except`
# and unit expressions like `E/s_Wh` get mistaken for paths -- and padding an exclusion list with
# them would slowly turn this test into a rubber stamp.
_PATH_EXTENSIONS = (
    ".py", ".md", ".yaml", ".yml", ".csv", ".json", ".jsonl", ".sh", ".txt",
    ".xlsx", ".service", ".conf", ".png", ".wav", ".onnx", ".cff", ".toml",
)
_TOP_LEVEL_DIRS = (
    "chatterbox/", "research/", "tests/", "docs/", "assets/", "deploy/", "scripts/", "profile/",
)


def _looks_like_a_repo_path(candidate):
    if candidate.startswith(("http", "/run/", "/dev/", "/etc/", "/home/", "~/")):
        return False
    if candidate.endswith(_PATH_EXTENSIONS):
        return True
    return candidate.startswith(_TOP_LEVEL_DIRS)


def _iter_paths(text):
    for match in _PATH_IN_BACKTICKS.finditer(text):
        candidate = match.group(1)
        if _looks_like_a_repo_path(candidate):
            yield candidate


@pytest.mark.parametrize("doc", PATH_CHECKED_DOCS)
def test_codemap_paths_exist(doc):
    """Every repo-relative path mentioned in a structural document must exist."""
    doc_path = REPO_ROOT / doc
    assert doc_path.is_file(), "{} is missing".format(doc)

    missing = []
    for candidate in _iter_paths(doc_path.read_text(encoding="utf-8")):
        if candidate in KNOWN_ABSENT:
            continue
        # A path may be written relative to the repo root, or relative to the document's directory
        # (e.g. "../README.md" links, already stripped of ../ by the regex not matching them).
        if (REPO_ROOT / candidate).exists():
            continue
        if (doc_path.parent / candidate).exists():
            continue
        missing.append(candidate)

    assert not missing, (
        "{} references paths that do not exist:\n  ".format(doc)
        + "\n  ".join(sorted(set(missing)))
        + "\n\nEither the file moved (update the document) or the reference is a typo."
    )


def test_codemap_symbols_exist():
    """Every row of CODEMAP.md's "Key symbols" table must name a real symbol in a real file."""
    text = CODEMAP.read_text(encoding="utf-8")
    rows = [(m.group(1), m.group(2)) for m in _SYMBOL_ROW.finditer(text)]

    assert len(rows) >= 20, (
        "Only {} symbol rows parsed from CODEMAP.md's Key symbols table -- the table format "
        "probably changed and this test is no longer checking anything.".format(len(rows))
    )

    broken = []
    for symbol, rel_path in rows:
        target = REPO_ROOT / rel_path
        if not target.is_file():
            broken.append("{}: file {} does not exist".format(symbol, rel_path))
            continue
        source = target.read_text(encoding="utf-8")
        # Accept a function, a class, or a module-level assignment.
        defined = re.search(
            r"^\s*(?:def|class)\s+{0}\b|^{0}\s*=".format(re.escape(symbol)),
            source,
            re.MULTILINE,
        )
        if not defined:
            broken.append("{} is not defined in {}".format(symbol, rel_path))

    assert not broken, (
        "CODEMAP.md's Key symbols table is out of date:\n  "
        + "\n  ".join(broken)
        + "\n\nRename in the code means rename in the map."
    )


def test_codemap_covers_the_layer_rule():
    """The layer boundary is the repository's central invariant; the map must state it.

    Cheap guard against someone trimming the document down to a plain file listing.
    """
    text = CODEMAP.read_text(encoding="utf-8")
    assert "research/" in text and "chatterbox/" in text
    assert "instrumentation.py" in text, "CODEMAP.md must point at the L1/L3 seam"
