# Chatterbox — Reorganisation Plan (proposal, not executed)

**Written:** 2026-08-17 · **Deadline:** 2026-08-31 (14 calendar days)
**Companion:** `docs/release/STRUCTURE_AUDIT.md` — read §0 and §4 before this document.
**Status:** nothing in this plan has been executed. No file was moved, renamed, deleted or edited.

---

## 1. Read this first — three things that should change your mind

### 1.1 This is not a file-move task

The audit's headline finding (`STRUCTURE_AUDIT.md` §4.2–4.3) is that four L1 modules import
`tools.monitoring.profiling` **at module scope**, including `chatterbox/synth.py` — the core compute
path. Verified empirically: with `tools` made unimportable, `chatterbox.synth`, `chatterbox.cli`,
`chatterbox.synthesis.registry` and `chatterbox.synthesis.backends.piper.backend` all fail to import.

Moving `tools/` to `research/` changes the name in the `ImportError` and nothing else. **The
invariant requires a dependency inversion (Step 3), which is a code change.** Every ordering
decision below follows from that.

### 1.2 "Behaviour-preserving only" and the invariant are in tension — here is how I resolved it

Your brief says no refactoring bundled into the move. But the invariant cannot be reached by moves
alone. I read "behaviour-preserving" as *observable behaviour is identical*, not *no code changes*,
and resolved it as follows:

- Steps 3 and 4 are **code changes**, isolated into their own steps, each landing **before** any file
  moves, each independently verifiable, each with an explicit "observable behaviour is unchanged"
  test. Nothing else is bundled with them.
- Every other step is a pure move.
- Everything else I found that should be fixed — the path anchoring, the dead ABCs, the tautological
  tests, the `|`-separator crash — is in §8 Follow-up, **not** in the plan.

If you disagree, the alternative is to keep `tools/` inside the shipped package and accept that the
invariant is documentation rather than a mechanical guarantee. I do not recommend that: it is the
status quo, and the enforcement check in Step 8 is the main thing that keeps the boundary from
rotting again after August.

### 1.3 The release blockers are not engineering problems

`STRUCTURE_AUDIT.md` §9.4 and §10.1: the repository has **no licence**, and its central asset — the
French FastSpeech 2 checkpoint — has **no established redistribution status**, as do the five
committed reference recordings of identifiable speakers. `assets/models/flaubert/flaubert_large_cased`
is a **gitlink with no `.gitmodules`**, so every public clone breaks.

None of these is fixed by reorganising directories, and the licence questions depend on people who
are not you (Gipsa-lab, Martin Lenglet, whoever holds the corpus consent). **Start those conversations
today, in parallel with Step 0** — they have the longest lead time and they gate publication
absolutely. A perfectly reorganised repository that cannot legally be published is worth nothing on
31 August.

---

## 2. Target tree

Every currently tracked path maps to a destination. Unplaceable files are in §9.

```
chatterbox/                                    ← repository root (rename optional)
│
├── LICENSE                                    NEW — §9 Q1 decides which
├── README.md                                  ← README.md (English rewrite; see §8-F9)
├── README.fr.md                               ← README.md (current French text preserved)
├── INSTALL.md                                 ← INSTALL.md
├── CITATION.cff                               NEW — lab research output
├── CONTRIBUTING.md                            NEW
├── pyproject.toml                             NEW — Step 7
├── .gitignore                                 ← .gitignore (patterns fixed, Step 6)
├── .gitmodules                                NEW or removed — Step 2
├── do_tts.py                                  ← do_tts.py  (unchanged; CLI contract)
│
├── chatterbox/                                ══ L1 RUN ══
│   ├── __init__.py                            ← chatterbox/__init__.py
│   ├── cli.py                                 ← chatterbox/cli.py            (imports rewritten)
│   ├── synth.py                               ← chatterbox/synth.py          (imports rewritten)
│   ├── state.py                               ← chatterbox/state.py
│   ├── instrumentation.py                     NEW — Step 3, the L1/L3 seam
│   ├── audio/       __init__.py, denoise.py, playback.py          ← unchanged
│   ├── config/      __init__.py, paths.py, config_tts.yaml, user_prefs.yaml
│   ├── gui/         __init__.py, app.py, i18n.py, input.py,
│   │                keyboards.py, settings.py, theme.py           ← unchanged
│   ├── power/       __init__.py, amp.py, backlight.py, battery.py,
│   │                client.py, config.py, daemon.py, fsm.py,
│   │                inputs.py, ipc.py                             ← unchanged
│   └── synthesis/
│       ├── __init__.py, registry.py, subtitles.py, audio_postprocess.py
│       ├── base.py                            ← KEPT IN PLACE (dead; see §9 Q4)
│       └── backends/
│           ├── fastspeech2_hifigan/  backend.py (imports rewritten),
│           │                         text_pipeline.py, rules/*.csv
│           └── piper/                backend.py (imports rewritten),
│                                     text_frontend.py, README.md
│
├── assets/                                    ══ L1 runtime assets ══
│   ├── audio/prompts/Emmanuelle/*.wav         ← unchanged (29 files)
│   └── models/
│       ├── FastSpeech2/                       ← unchanged  (MIT)
│       ├── hifi-gan-master/                   ← unchanged  (MIT)
│       └── flaubert/flaubert_large_cased/     ← gitlink FIXED (Step 2)
│
├── scripts/         setup_pi.sh, kiosk_finalize.sh, fetch_piper_voices.sh   ← unchanged
├── deploy/
│   ├── xorg-kiosk/  README.md, xinitrc, bash_profile_snippet.sh,
│   │                getty-tty1-autologin.conf                     ← unchanged
│   └── systemd/     chatterbox-powerd.service                     ← unchanged
│
├── hardware/                                  ══ L2 BUILD ══ (empty today, §9 Q2)
│   └── .gitkeep                               ← hardware/.gitkeep
│
├── research/                                  ══ L3 STUDY ══  (was tools/)
│   ├── __init__.py                            ← tools/__init__.py
│   ├── profiling/                             ← tools/monitoring/profiling/
│   │   __init__.py, sampler.py, recorder.py, parsing.py, join.py, calibrate.py
│   ├── benchmark/                             ← tools/measurement/benchmark/
│   │   __init__.py, runner.py, p4_sweep.py, export_to_xlsx.py,
│   │   compare_runs.py, sentences_fr.jsonl
│   ├── calibration/
│   │   pmic_calibrate.py                      ← tools/measurement/pmic_calibrate.py  (§9 Q5)
│   ├── legacy/
│   │   waveglow/                              ← assets/models/Waveglow/**  (Step 4; §9 Q6)
│   └── data/                                  ← profile/**  (§9 Q3 — or drop from git)
│
├── tests/                                     ══ L3 ══  (24 files, unchanged content)
│   conftest.py (extended, Step 7), test_*.py
│   └── test_layer_boundary.py                 NEW — Step 8, the enforcement check
│
└── docs/
    ├── release/     STRUCTURE_AUDIT.md, REORG_PLAN.md              ← these two documents
    ├── kiosk/KIOSK.md, power/POWERD.md                             ← L1, unchanged
    └── research/                                                   ══ L3 ══
        ├── ARCHITECTURE.md, CHANGELOG.md,
        │   PIPER_INTEGRATION_SUMMARY.md                            ← docs/context/
        ├── GUI.md, INTERCHANGEABLE_BACKENDS.md                     ← docs/gui/
        ├── REORG_PROPOSAL.md, REORG_VERIFICATION.md                ← docs/
        ├── assets/tts_gui.png                                      ← docs/assets/
        └── reference-audio/*.wav                                   ← assets/audio/reference/ (§9 Q7)
```

**Deliberately not moved:**

| Path | Why it stays |
|---|---|
| `do_tts.py` | Documented CLI contract; a shim costs nothing and breaking it breaks the Pi units. |
| `chatterbox/` internal layout | Every move multiplies import-rewrite risk for zero boundary gain. |
| `chatterbox/synthesis/base.py` | Dead (audit §7.1), but deleting it is a judgement call — §9 Q4. |
| `deploy/systemd/chatterbox-gui.service` | Dead but documents a rejected approach — §9 Q8. |
| `CLAUDE.md` | §9 Q9. |

---

## 3. Prerequisite — Step 0

**Nothing below may start until this is done.** The `pre-release-audit` tag your brief refers to
**does not exist**: `git tag -l` returns empty (audit §10.7). There is currently no rollback anchor.

```bash
git status --porcelain                      # must be empty
git tag -a pre-release-audit -m "State audited 2026-08-17, commit c8a0a2e"
git tag -l                                  # confirm
```

Then record the **baseline behaviour** every later step is verified against. Run on the Pi 5, with
real weights — not on the PC, and not pytest:

```bash
# B-1  free text
python3 do_tts.py                           # type "Bonjour, comment allez-vous ?" → audible speech
# B-2  GUI
python3 do_tts.py --gui                     # loads, speaks, keyboard works, settings open
# B-3  benchmark + join, both backends
python3 do_tts.py --benchmark --repeats 1 --join
python3 do_tts.py --default_tts 1 --benchmark --repeats 1 --join
# B-4  capture
cp -r profile/<latest-run> ~/baseline-run/
python3 -m pytest tests/ -q | tee ~/baseline-pytest.txt
```

Keep `~/baseline-run/` — Steps 3 and 5 are verified by diffing against it.

**Cost: 2 h** (mostly waiting on benchmark runs).

---

## 4. The steps

Ordered. Each is independently verifiable and independently revertable. Steps 1–4 are prerequisites
for the moves; Steps 5–6 are the moves; Steps 7–8 are packaging and enforcement.

---

### Step 1 — Resolve licensing and provenance ⚠ BLOCKING, START FIRST

**No code. Pure people-work, and the longest lead time in the plan.** Runs in parallel with everything else.

| Item | Question to answer | Who |
|---|---|---|
| Repository licence | Which licence, and who is the copyright holder? | You + Gipsa-lab + M. Lenglet |
| FastSpeech 2 FR checkpoint | Redistributable? Which corpus? Speaker consent? | Corpus owner |
| HiFi-GAN `FR_V2` weights | Redistributable? Provenance? | Model trainer |
| FlauBERT copy | Unmodified upstream (MIT)? If so, link upstream instead of Drive. | Verify by hash |
| `assets/audio/reference/*.wav` | Consent to publish recordings of NEB / AD? | Speakers / lab |
| `assets/audio/prompts/Emmanuelle/*.wav` | Same, for "Emmanuelle" — **required at runtime** | Speaker / lab |
| Piper voices | Per-voice licence for siwis / upmc / lessac | Check dataset page |

**Verification:** a written `LICENSE` file plus a `docs/release/PROVENANCE.md` stating, per asset, the
licence and the evidence for it. Every "unknown" that remains unknown must become either *not
published* or *published with an explicit caveat*.

**Cost: 2 h of your time; days to weeks of other people's.** ⚠ Not under your control.

---

### Step 2 — Fix the broken FlauBERT gitlink

**What changes:** `assets/models/flaubert/flaubert_large_cased` stops being a mode-160000 gitlink.

Three options, in order of preference:

| Option | Action | Trade-off |
|---|---|---|
| **A (recommended)** | `git rm --cached` the gitlink; add the path to `.gitignore`; document the download in `INSTALL.md` — treat it exactly like the FS2/HiFi-GAN weights, which are already handled this way. | Consistent with every other weight. Requires a doc line. |
| B | Add a real `.gitmodules` pointing at the upstream FlauBERT repo. | Only valid if commit `a5fdc16` exists in a public repo — **verify before choosing**. |
| C | Fetch from HuggingFace in `setup_pi.sh` like `fetch_piper_voices.sh` does. | Best long-term; more work. |

**Consequence:** none for imports — `paths.FLAUBERT_DIR` already points at the directory and does not
care how it got there.

**Verification:**
```bash
git ls-files -s assets/models/flaubert/          # no 160000 entries
git submodule status                             # no fatal error
cd /tmp && git clone <repo> clone-test && cd clone-test && git submodule status   # clean
```
Then, in the real checkout, confirm a StyleTag synthesis still works (FlauBERT is only loaded when
`<STYLE_TAG=…>` is present):
```bash
python3 do_tts.py     # input:  <STYLE_TAG=joyeux>Bonjour.
```

**On the Pi:** Option A means `git pull` will **delete the local `flaubert_large_cased/` directory**
if git considers it tracked-then-removed. **Back it up first** — it is 1.5 GB and re-downloading it
over the Pi's network is slow:
```bash
# ON THE PI, BEFORE PULLING
mv assets/models/flaubert/flaubert_large_cased ~/flaubert-backup
git pull
mkdir -p assets/models/flaubert && mv ~/flaubert-backup assets/models/flaubert/flaubert_large_cased
```

**Cost: 1.5 h** (3 h if Option C).

---

### Step 3 — Invert the profiling dependency ⚠ CODE CHANGE, the heart of the plan

**What changes:** L1 stops importing `tools.*`. It imports a new L1-owned no-op seam instead; L3
installs the real implementation into it.

The coupling surface is small and already enumerated (audit §4.4): nine module functions and three
recorder methods. Add **`chatterbox/instrumentation.py`**:

```python
"""L1-owned instrumentation seam. Default implementation is a no-op.

L1 never imports research code. research/profiling installs the real
implementation here via install(); until it does, every call below is inert --
which is exactly the shipped default (config_tts.yaml: profiling.enabled=false).
"""

class _NullRecorder:
    def set(self, **kwargs): pass
    def stage(self, name): return self          # context manager
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def finalize(self): pass


_NULL = _NullRecorder()
_impl = None


def install(impl):
    """Called by research.profiling at import time."""
    global _impl
    _impl = impl


def enable():                    return _impl.enable() if _impl else None
def set_output_dir(path):        return _impl.set_output_dir(path) if _impl else None
def start_session(**kw):         return _impl.start_session(**kw) if _impl else None
def start_session_at(*a, **kw):  return _impl.start_session_at(*a, **kw) if _impl else None
def stop_session(*a, **kw):      return _impl.stop_session(*a, **kw) if _impl else None
def get_run_dir():               return _impl.get_run_dir() if _impl else None
def set_current(rec):            return _impl.set_current(rec) if _impl else None
def current():                   return _impl.current() if _impl else _NULL
def begin_sentence(text, complexity_tag=None, sentence_id=None):
    if _impl is None:
        return _NULL
    return _impl.begin_sentence(text, complexity_tag=complexity_tag, sentence_id=sentence_id)
```

Then, mechanically:

| File:line | From | To |
|---|---|---|
| `chatterbox/synth.py:31` | `import tools.monitoring.profiling as profiling` | `import chatterbox.instrumentation as profiling` |
| `chatterbox/cli.py:25` | same | same |
| `…/fastspeech2_hifigan/backend.py:25` | same | same |
| `…/piper/backend.py:22` | same | same |

`tools/monitoring/profiling/__init__.py` gains, at the end:
`import chatterbox.instrumentation as _seam; _seam.install(sys.modules[__name__])`

`cli.py`'s four **mode-gated** imports (V5–V8) stay function-local and are rewritten to `research.*`
in Step 5. They are acceptable: they only execute inside `if args.benchmark/--p4-sweep`, which are L3
modes. Step 8's checker whitelists exactly these four call sites, by line, with a comment.

**Why this is behaviour-preserving.** Shipped default is `profiling.enabled: false`, so today's calls
already no-op internally. With profiling *on*, `cli.py` imports the benchmark/p4_sweep modules, which
import `research.profiling`, which calls `install()` — the real implementation is live before any
sentence is recorded. The one ordering risk is free-text `--profile` (no benchmark import): handle it
by having `cli.py`'s existing `if prof_cfg.get("enabled")` block import `research.profiling` before
calling `profiling.enable()`. That import is already inside a mode gate.

**Verification — this is the step that must not silently break profiling:**
```bash
# 3a  L1 no longer imports L3, mechanically
python -c "
import sys, importlib.abc
class B(importlib.abc.MetaPathFinder):
    def find_spec(s,n,p=None,t=None):
        if n=='tools' or n.startswith('tools.'): raise ImportError(n)
import chatterbox.synth, chatterbox.cli, chatterbox.synthesis.registry
print('L1 imports clean without tools')" 
# (insert the finder before the imports — see docs/release/STRUCTURE_AUDIT.md §4.3)

# 3b  profiling OFF still speaks
python3 do_tts.py                       # → audible speech

# 3c  profiling ON still produces IDENTICAL data shape
python3 do_tts.py --benchmark --repeats 1 --join
diff <(head -1 profile/<new>/per_sentence_results.csv) \
     <(head -1 ~/baseline-run/per_sentence_results.csv)      # headers identical
wc -l profile/<new>/per_sentence.jsonl                        # same row count as baseline
python3 -m pytest tests/ -q                                   # matches ~/baseline-pytest.txt
```
3c is the one that matters. If `per_sentence.jsonl` is empty or short, `install()` ran too late.

**On the Pi:** `git pull` then delete stale bytecode — a stale `__pycache__` for the old import graph
is the most likely source of a confusing failure:
```bash
find . -name __pycache__ -type d -exec rm -rf {} +
sudo systemctl restart chatterbox-powerd
```

**Cost: 5 h** (2 h to write, 3 h to verify 3c properly on hardware).

---

### Step 4 — Make the Waveglow import lazy

**What changes:** three lines in `…/fastspeech2_hifigan/backend.py`.

Audit §7.2: Waveglow is unreachable via config (its `vocoder_models` entry is commented out) but
**load-bearing at import time** — `backend.py:38-40` does `sys.path.insert(...)` plus
`from inference import main as inference_main` at module scope. The vendored tree cannot move while
that holds.

Move those three lines into `syn_waveglow()` (`backend.py:377`), the only consumer.

**Verification:**
```bash
python -c "import chatterbox.synthesis.backends.fastspeech2_hifigan.backend; print('ok')"
mv assets/models/Waveglow /tmp/wg-test          # temporarily
python3 do_tts.py                               # still speaks
python3 do_tts.py --gui                         # still loads
mv /tmp/wg-test assets/models/Waveglow          # restore
```
The temporary `mv` is the real proof; do it locally, never on the Pi.

**On the Pi:** nothing breaks — Waveglow was never reachable.

**Cost: 1.5 h.**

---

### Step 5 — Move `tools/` → `research/`

**What moves:** the whole tree, per §2. Use `git mv` so history follows.

```bash
git mv tools research
git mv research/monitoring/profiling research/profiling
git mv research/measurement/benchmark research/benchmark
mkdir research/calibration && git mv research/measurement/pmic_calibrate.py research/calibration/
git rm research/monitoring/__init__.py research/measurement/__init__.py   # now-empty layers
```

**What must change as a consequence:**

| Location | Change |
|---|---|
| `chatterbox/cli.py:249,333,387,396` | `tools.measurement.benchmark.*` → `research.benchmark.*`; `tools.monitoring.profiling.join` → `research.profiling.join` |
| `research/benchmark/{runner,p4_sweep}.py` | internal `tools.` references → `research.` |
| `research/profiling/*.py` | internal cross-imports |
| `research/profiling/__init__.py:30` | `import chatterbox.config.paths` — **keep**, L3→L1 is permitted |
| `tests/test_*.py` | every `tools.` import (test_profiling, test_benchmark, test_p4_sweep, test_export_xlsx, test_compare_runs) |
| `chatterbox/config/config_tts.yaml` | comments referencing `tools/…` paths |
| `cli.py` `--help` strings | lines 191, 208, 214 name `tools/…` paths |
| `README.md`, `INSTALL.md`, `CLAUDE.md`, `docs/**` | path references |

**Verification:**
```bash
grep -rn "tools\." --include=*.py chatterbox research tests    # expect zero
grep -rn "tools/" --include=*.md . | grep -v docs/release      # expect zero
python3 -m pytest tests/ -q                                    # matches baseline
python3 do_tts.py --benchmark --repeats 1 --join --export-xlsx  # full L3 chain
python3 -m research.profiling.join profile/<run>                # standalone entry point
python3 -m research.benchmark.compare_runs --help
```

**On the Pi — this is the step most likely to bite.** `git pull` leaves the old `tools/` directory
present if it contains untracked `__pycache__`, and a stale `tools/` **shadows nothing but confuses
everything**:
```bash
git pull
find . -name __pycache__ -type d -exec rm -rf {} +
rm -rf tools                     # only after confirming git no longer tracks it
python3 do_tts.py --benchmark --repeats 1   # real verification, not pytest
```
If the Pi is updated by `scp` rather than `git pull`, `tools/` will **not** be removed by the copy —
delete it by hand or you will have two copies of the profiling code on disk.

**Cost: 4 h.**

---

### Step 6 — Move docs and research data; fix `.gitignore`

**What moves:**
```bash
mkdir -p docs/research
git mv docs/context docs/gui docs/REORG_PROPOSAL.md docs/REORG_VERIFICATION.md docs/research/
git mv docs/assets docs/research/assets
git mv assets/audio/reference docs/research/reference-audio        # pending §9 Q7
git mv profile research/data                                       # pending §9 Q3
```

**`.gitignore` fix (audit §10.3)** — current patterns are one level short:
```diff
-profile/*.csv
-profile/*.jsonl
-profile/sampler.pid
-profile/exports/
+research/data/**/*.csv
+research/data/**/*.jsonl
+research/data/**/*.xlsx
+research/data/**/sampler.pid
+research/data/**/exports/
+.claude/
```

**Consequence:** `README.md`'s screenshot link (`docs/assets/tts_gui.png`) and every cross-doc link
must be updated. `profiling.output_dir: "profile"` in `config_tts.yaml:77` — decide whether run output
still lands in `profile/` (recommended: **yes**, leave the default alone; only the committed
historical data moves).

**Verification:** `python3 do_tts.py --profile` writes to the expected directory; `git status` clean
after a profiling run (no new tracked files); every markdown link resolves
(`grep -o '](\S*\.md)' docs/**/*.md` spot-check).

**On the Pi:** if `profile/` on the Pi holds runs you care about, they are untracked — `git mv` on
your machine does not touch them. Confirm before pulling.

**Cost: 3 h.**

---

### Step 7 — Packaging: `pyproject.toml` with `[dev]` / `[research]` extras

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "chatterbox-tts"
version = "0.1.0"
description = "Embedded neural French TTS demonstrator for AAC, on Raspberry Pi 5"
readme = "README.md"
requires-python = ">=3.10"
license = { file = "LICENSE" }              # Step 1 decides the identifier
authors = [{ name = "..." }]                # §9 Q1

# L1 ONLY. Mirrors requirements-pi.txt. piper-tts is deliberately absent
# (GPL-3.0-or-later, user-installed -- see docs/release/STRUCTURE_AUDIT.md §9.3).
dependencies = [
  "torch>=2.4.1", "PyYAML>=6.0.2", "numpy>=2.0.2", "unidecode>=1.3.8",
  "inflect>=7.4.0", "regex>=2024.9.11", "scipy>=1.14.1", "matplotlib>=3.9.2",
  "transformers>=4.45.1", "noisereduce>=3.0.2", "librosa>=0.10.2",
  "pydub>=0.25.1", "g2p_en>=2.1.0", "pypinyin>=0.53.0", "sacremoses>=0.1.1",
]

[project.optional-dependencies]
pi       = ["smbus2>=0.4.3", "gpiozero>=2.0.1", "lgpio>=0.2.2.0", "evdev>=1.7.1"]
research = ["openpyxl>=3.1.5", "smbus2>=0.4.3"]
dev      = ["pytest>=8", "chatterbox-tts[research]"]

[project.scripts]
chatterbox = "chatterbox.cli:main"

[tool.setuptools.packages.find]
include = ["chatterbox*"]                    # research/ and tests/ NOT packaged

[tool.setuptools.package-data]
"chatterbox.config" = ["*.yaml"]
"chatterbox.synthesis.backends.fastspeech2_hifigan" = ["rules/*.csv"]
```

Two decisions embedded above, both worth challenging:

- **`unicode>=2.9` is dropped** (audit §9.5): abandoned PyPI package, unclear licence, no consumer
  found. Verify with `grep -rn "^import unicode\|from unicode " --include=*.py .` before removing.
- **`assets/` is not package data.** It is 40 MB of vendored model code plus weights that are not in
  git anyway. `pip install .` gives you the package; `INSTALL.md` still governs assets. Packaging
  `assets/` would make the wheel enormous and still not include the weights.

`tests/conftest.py` should gain a repo-root marker so the suite can run against either a source
checkout or an installed package.

**Verification:**
```bash
python -m build && python -m twine check dist/*
python -m venv /tmp/v && /tmp/v/bin/pip install .
/tmp/v/bin/python -c "import chatterbox.synth, chatterbox.cli; print('L1 installs clean')"
/tmp/v/bin/python -c "import research" 2>&1 | grep ModuleNotFound   # research NOT packaged
/tmp/v/bin/chatterbox --help
```

**On the Pi: change nothing yet.** The Pi runs from a source checkout at
`/home/chatterbox/chatterbox` with a venv at `$HOME/chatterbox/venv`, and both systemd units use
absolute paths to `do_tts.py`. Switching the Pi to an installed package is a **separate migration**
(§8-F8) — do not bundle it into the release. `pyproject.toml` is for external users in August.

**Cost: 4 h.**

---

### Step 8 — Enforce "L1 does not import L3" mechanically

Two layers: a standalone script and a test that runs it.

**`scripts/check_layers.py`** — AST-based, no imports executed:

```python
#!/usr/bin/env python3
"""Fail if any L1 module imports L3. See docs/release/STRUCTURE_AUDIT.md Sec4."""
import ast, pathlib, sys

L1_ROOT = pathlib.Path("chatterbox")
L3_PREFIXES = ("research", "tests", "tools")

# The only tolerated exceptions: function-local, mode-gated imports in cli.py that
# fire solely inside `if args.benchmark / --p4-sweep / --export-xlsx`.
ALLOWED = {("chatterbox/cli.py", "research.benchmark.p4_sweep"),
           ("chatterbox/cli.py", "research.benchmark.runner"),
           ("chatterbox/cli.py", "research.profiling.join"),
           ("chatterbox/cli.py", "research.benchmark.export_to_xlsx")}


def violations():
    for path in sorted(L1_ROOT.rglob("*.py")):
        rel = path.as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        # module-scope statements only, for the "unconditional" check
        toplevel = {id(n) for n in tree.body}
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                if name.split(".")[0] not in L3_PREFIXES:
                    continue
                if (rel, name) in ALLOWED and id(node) not in toplevel:
                    continue                      # gated, function-local: tolerated
                scope = "module-scope" if id(node) in toplevel else "function-scope"
                yield f"{rel}:{node.lineno}: L1 imports L3 ({scope}): {name}"


if __name__ == "__main__":
    found = list(violations())
    print("\n".join(found) or "OK: no L1 -> L3 imports")
    sys.exit(1 if found else 0)
```

**`tests/test_layer_boundary.py`** — so `pytest` catches regressions:

```python
def test_no_l1_imports_l3():
    from scripts.check_layers import violations
    assert list(violations()) == []


def test_l1_imports_without_research_package(monkeypatch):
    """The deletion test: L1 must import with research/ absent."""
    import sys, importlib, importlib.abc

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in ("research", "tools"):
                raise ImportError(f"L3 package {name!r} removed (simulated)")
            return None

    monkeypatch.setattr(sys, "meta_path", [Block()] + sys.meta_path)
    for mod in ("chatterbox.synth", "chatterbox.cli",
                "chatterbox.synthesis.registry",
                "chatterbox.synthesis.backends.piper.backend"):
        sys.modules.pop(mod, None)
        importlib.import_module(mod)
```

The second test is the one that actually encodes your invariant — it is the automated form of the
manual check in audit §4.3, and it fails today.

**Verification:** `python scripts/check_layers.py` exits 0; `pytest tests/test_layer_boundary.py`
passes; then deliberately add `import research.profiling` to `chatterbox/state.py`, confirm both fail,
and revert.

**Cost: 3 h.**

---

## 5. Functioning-only verification recipe

The proof that L1 stands alone. Run on a **clean clone**, not your working tree.

```bash
git clone <repo> /tmp/l1-only && cd /tmp/l1-only

# Delete every L3 artefact
rm -rf research/ tests/ docs/research/ scripts/check_layers.py

# Install L1 only
python3 -m venv .venv && . .venv/bin/activate
pip install .

# Assets (not in git -- per INSTALL.md)
#   FastSpeech2 config/ + output/ + preprocessed_data/, HiFi-GAN FR_V2/, FlauBERT
./scripts/fetch_piper_voices.sh          # optional, needs `pip install piper-tts==1.5.0`

# 1. L1 imports with no L3 present
python -c "import chatterbox.synth, chatterbox.cli, chatterbox.synthesis.registry; print('OK')"

# 2. It speaks  -- FastSpeech2 + HiFi-GAN
python do_tts.py            # "Bonjour, comment allez-vous ?" -> audible speech

# 3. It speaks  -- Piper (monolithic backend)
python do_tts.py --default_tts 1

# 4. The GUI launches and speaks
python do_tts.py --gui

# 5. L3 modes fail CLEANLY, not with a stack trace at import time
python do_tts.py --benchmark ; echo "exit=$?"    # expect a clear "research extra not installed"
```

Item 5 is worth designing for: with `research/` gone, `cli.py`'s gated imports raise
`ModuleNotFoundError`. Wrap those four call sites in `try/except ModuleNotFoundError` with a message
pointing at `pip install chatterbox-tts[research]`. That is a **behaviour change** for a mode that
cannot work anyway — I have listed it as §8-F1 rather than smuggling it into Step 5.

**Success criterion:** items 1–4 pass with `research/`, `tests/` and `docs/research/` deleted.

---

## 6. Risk table

| # | Risk | Likelihood | How you notice | Rollback |
|---|---|---|---|---|
| R1 | **Step 3 breaks profiling silently** — `install()` runs after the first sentence, so records are empty but nothing errors. | **High** | `per_sentence.jsonl` shorter than baseline, or `per_sentence_results.csv` empty. **Only** caught by Step 3's check 3c — pytest will not catch it. | `git revert` Step 3; the seam is one file plus 4 import lines. |
| R2 | **Stale `tools/` + `__pycache__` on the Pi after Step 5** — two copies of profiling on disk, imports resolve unpredictably. | **High** | Benchmark writes to an unexpected directory, or `ImportError` naming `tools`. | `rm -rf tools __pycache__` on the Pi; re-pull. |
| R3 | **FlauBERT 1.5 GB re-download** after Step 2's `git pull` deletes the directory. | Medium | `<STYLE_TAG=…>` synthesis raises `FileNotFoundError`. | Restore from the backup taken in Step 2's Pi procedure. |
| R4 | **Path anchoring (B3/B4) surfaces during a move** — a step changes the effective cwd and model loading breaks. | Medium | `FileNotFoundError` on `config/ALL_corpus/preprocess.yaml`. | Run from the repo root; the real fix is §8-F2. |
| R5 | **Licence answers never arrive** before 31 August. | **Medium-High** | Step 1 stalls. | Publish L1+L2 code under a chosen licence with weights as documented downloads only; see §7. |
| R6 | **Waveglow lazy import (Step 4) breaks an unnoticed consumer.** | Low | `NameError: inference_main` inside `syn_waveglow()`. | Revert 3 lines. Waveglow is unreachable by config anyway. |
| R7 | **`pip install .` omits `rules/*.csv` or `*.yaml`** — package-data misconfigured. | Medium | `FileNotFoundError` on `custom_regex_rules.csv` in the clean-clone test. | Fix `[tool.setuptools.package-data]`; caught by §5 item 2. |
| R8 | **Doc links rot** after Step 6. | High | Broken links in the published repo. | Cosmetic; fix forward. |
| R9 | **Reference-audio move (Step 6) publishes recordings anyway** — moving is not removing; history retains them. | Medium | Discovered post-publication. | Requires history rewrite. **Decide in Step 1, before Step 6.** |

Global rollback: `git reset --hard pre-release-audit` (after Step 0 creates it).

---

## 7. Cost and what fits before 31 August

14 calendar days from 2026-08-17.

| Step | Description | Hours | Depends on |
|---|---|---|---|
| 0 | Tag + baseline capture | 2 | — |
| 1 | **Licence + provenance** | 2 + external | — |
| 2 | Fix FlauBERT gitlink | 1.5 | 0 |
| 3 | **Invert profiling dependency** | 5 | 0 |
| 4 | Waveglow lazy import | 1.5 | 0 |
| 5 | `tools/` → `research/` | 4 | 3, 4 |
| 6 | Docs + data moves, `.gitignore` | 3 | 5 |
| 7 | `pyproject.toml` + extras | 4 | 5 |
| 8 | Layer-boundary enforcement | 3 | 5 |
| — | Clean-clone verification (§5) | 3 | 7 |
| — | Pi re-verification after each step | 4 | — |
| | **Total** | **33 h** | |

**Does it fit?** The engineering does: 33 hours over 14 days is comfortable. **Step 1 is the risk** —
it is the only item not under your control, and it gates publication absolutely.

### Minimum credible public release

If time compresses, this subset delivers a repository that is honest, installable and legally
publishable:

| Priority | Steps | Hours | Why it is the minimum |
|---|---|---|---|
| **Must** | 0, 1, 2 | 5.5 + external | Without a licence and a working clone there is no release at all. |
| **Must** | 3, 8 | 8 | The invariant is the point of the exercise. Step 3 without Step 8 rots by Christmas. |
| **Should** | 5, 7 | 8 | `research/` naming + `pip install .` is what a newcomer actually sees. |
| **Nice** | 4, 6 | 4.5 | Internal tidiness; no external visibility. |

**Cut first:** Step 6's data move (leave `profile/` where it is and just fix `.gitignore`) and Step 4.
**Never cut:** Steps 1, 2, 3, 8.

If Step 1 stalls past ~25 August, publish the **code** under your chosen licence with **all weights
and audio as documented external downloads**, and ship `docs/release/PROVENANCE.md` stating plainly
which assets have unresolved licensing. That is a credible, honest release. Publishing weights of
unknown provenance is not.

---

## 8. Follow-up work (explicitly NOT in the plan above)

Real problems found during the audit. None is bundled into a move.

| # | Item | Evidence | Severity |
|---|---|---|---|
| **F1** | Wrap `cli.py`'s four L3 imports in `try/except ModuleNotFoundError` with an actionable message. | §5 item 5 | High (release polish) |
| **F2** | **Complete the Phase 0 path anchoring.** `config_tts.yaml`'s `folder:` values are relative and used raw via `os.path.join` (`backend.py:113,137`); `--config` default is relative (`cli.py:94`). The repo must be the cwd. | audit §6.3 B3/B4 | **High** |
| **F3** | `synth.py:254` `shutil.copy(path_au, "./")` and the root-level `audio_file.*` outputs write into the cwd. | audit §6.3 B5/B6 | **High** |
| **F4** | **`chatterbox/synthesis/base.py` is dead** — nothing subclasses or imports it. Either wire the backends to it or delete it. `CLAUDE.md` documents it as operative; it is not. | audit §5.1, §7.1 | **High (doc correctness)** |
| **F5** | **`test_synth.py`'s 3 `AudioResult` tests are tautologies** — they build the object they assert on and never call `synthesize()`. Exactly the failure mode you warned about. | audit §8.2 | **High** |
| **F6** | The `\|` multi-utterance branch crashes any monolithic backend (`FileNotFoundError`). Documented in-place at `synth.py:138-144`, unfixed. | audit §5.4 | Medium |
| **F7** | Circular import `cli.py:22` ↔ `gui/app.py:39`; Tkinter is a hard dependency of headless modes. | audit §4.1 | Medium |
| **F8** | Migrate the Pi from source-checkout to `pip install .` + a `chatterbox` console script; update both systemd units off `/home/chatterbox/chatterbox`. | audit §6.3 B1/B2 | Medium |
| **F9** | `README.md` is French-only. Add an English README for an international audience. | audit §10.7 | Medium |
| **F10** | The six missing spec documents (§10.2) — restore, or strip every reference. `INSTALL.md:112` depends on one. | audit §10.2 | **High** |
| **F11** | `registry.py` hardcodes the backend table; `_BackendProxy` silently mis-dispatches on name collision; `gui_script` resolves via `globals()`, not the registry. | audit §5.3 | Medium |
| **F12** | Dead config keys: `syn_script: "syn_piper"` (no such method), `gst_token_list: {}` on Piper, unused `control_width`/`control_height`. | audit §7.5 | Low |
| **F13** | Stale comment in `requirements-pi.txt:20-22` referencing `audio_utils.py`/`gui_utils.py`, deleted in Phase 3. | audit §7.7 | Low |
| **F14** | `git log` leaks `laptop-295.gipsa-lab.grenoble-inp.fr` and two personal addresses. History rewrite or accept. | audit §10.4 | **Your call** |

---

## 9. Questions — I need your answers before executing anything

Numbered for reply. Q1–Q3 block the plan; the rest block individual steps.

1. **Licence and copyright holder.** Which licence, and who holds copyright — you, Martin Lenglet,
   Gipsa-lab, Grenoble INP, or several jointly? Everything in Step 1 and Step 7 waits on this.
   (My recommendation: a permissive licence — MIT or Apache-2.0 — since all vendored code is MIT/BSD
   and `piper-tts` is not vendored, so nothing forces GPL. See audit §9.3.)

2. **Model weights and recorded audio.** For each of: FastSpeech 2 FR checkpoint `390000`, HiFi-GAN
   `FR_V2/g_00570000`, the FlauBERT copy, `assets/audio/reference/*.wav` (5 files, committed,
   speaker initials NEB/AD), `assets/audio/prompts/Emmanuelle/*.wav` (29 files, committed, **required
   at runtime**) — is it redistributable, and under what terms? Do the speakers consent to
   publication? This is the single biggest release blocker.

3. **`profile/` — ~180 committed run files, ~40 MB** (audit §10.3). Keep as published research data,
   move to `research/data/`, or remove from tracking (history retained)? If the numbers back a
   report or thesis, keeping them is defensible; if they are scratch runs, they are noise.

4. **`chatterbox/synthesis/base.py`** — dead (audit §7.1). Delete it, or wire the two backends to it
   for real? `CLAUDE.md` currently documents it as the operative contract, which is inaccurate either
   way. My recommendation: delete, and document the tuple contract that actually exists.

5. **`tools/measurement/pmic_calibrate.py`** (246 lines, no importer) vs
   `tools/monitoring/profiling/calibrate.py` (64 lines, referenced from `join.py`). Is the former
   superseded, or a distinct interactive wizard you still use? DEAD or L3?

6. **`assets/models/Waveglow/`** — ~30 vendored files including a full NVIDIA tacotron2 training copy,
   unreachable via config. Delete entirely, or keep as `research/legacy/waveglow/`? (Step 4 must land
   either way, since the import is load-bearing.)

7. **`assets/audio/reference/*.wav`** — L3 research reference, or L1 runtime asset? I found no code
   reading them; I have provisionally classified them L3. Confirm they are not needed at runtime.

8. **`deploy/systemd/chatterbox-gui.service`** — the cage/Wayland unit, ruled out by the wlroots
   SIGSEGV. Delete, or keep as documentation of a rejected approach?

9. **`CLAUDE.md`** — publish it (it is a genuinely good architecture guide), or strip it as
   AI-assistant scaffolding? Note it contains at least one claim the code contradicts (audit §5.1),
   which must be corrected either way.

10. **The six missing spec documents** (audit §10.2): `chatterbox_gui_spec_v0.1.md`,
    `chatterbox-powerd_spec_v0.1.md`, `Bring-up_Integration_Test_Protocol_v0.1.md`, and three
    `cc_prompt_*.md`. Do they exist somewhere? `INSTALL.md:112` sends installers to the bring-up
    protocol as the procedure that catches silent hardware failures. Restore them, or rewrite the
    references?

11. **`hardware/` (L2) is empty** — just a `.gitkeep`. Does the BOM / wiring / enclosure / acoustic
    material exist elsewhere and need importing, or is L2 genuinely empty for this release? Your
    three-layer model has nothing in its middle layer today.

12. **Pi deployment model.** Keep the Pi on a source checkout updated by `git pull` (my
    recommendation for August — lowest risk), or migrate it to `pip install .` with a console script
    and rewritten systemd units? The latter is §8-F8 and I would not attempt it before the deadline.

13. **Git history** (audit §10.4): accept the lab-internal hostname and personal email addresses in
    125 commits, or rewrite history before publishing? Rewriting invalidates the
    `pre-release-audit` tag and every existing clone — decide before Step 0, not after.
