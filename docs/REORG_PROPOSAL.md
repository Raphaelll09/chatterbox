# Chatterbox — Repository Reorganization Proposal

**Status: Phases 0–2 implemented (branch `reorg/phase-0-path-anchoring`, Windows-verified — see §7).**
Phases 3–4 are still analysis only — no further directories moved, renamed, or deleted beyond
Phases 1–2's moves. Every phase in §7 uses `git mv` on this dedicated branch when executed, each
with its own validation checkpoint. Phases 1 and 2 each surfaced real gaps invisible to static
analysis — see their notes in §7 and the two new §6 risk items (gitignored FastSpeech2 config
YAMLs, now **fixed**; and a directory-depth-assumption bug pattern to watch for in Phase 3).

**No Pi 5 hardware access for this execution round.** Amendment #8 ("Pi 5 hardware run mandatory
before merging each phase") is retired for now — there's no Pi 5 available to run it against. Every
phase below is verified on Windows only; the Pi-specific risk each Verify step calls out (the
`sys.path` import-ordering fragility in §6, `profiling/sampler.py`'s subprocess launch in Phase 2)
is *accepted, not resolved*, until someone with Pi access runs `scripts/setup_pi.sh` /
`do_tts.py --benchmark` on real hardware. Treat every phase merged under this plan as
**Windows-verified, Pi-unverified** until that happens — this is a real risk being knowingly
carried, not a formality being skipped.

Repo: `Raphaelll09/chatterbox` (fork of `MartinLenglet/embedded_tts`; no further upstream merges
planned — see §6 "Upstream merge cost"). Target: Raspberry Pi 5, CPU-only.

---

## Table of contents

1. [Inventory & analysis](#1-inventory--analysis)
2. [Proposed tree & file mapping](#2-proposed-tree--file-mapping)
3. [Rationale per top-level directory](#3-rationale-per-top-level-directory)
4. [Dead / unused / duplicate files](#4-dead--unused--duplicate-files--flagged-not-deleted)
5. [Interface boundaries](#5-interface-boundaries)
6. [Risk & impact notes](#6-risk--impact-notes)
7. [Phased migration plan](#7-phased-migration-plan)

---

## 1. Inventory & analysis

373 tracked files, ~4,900 lines of orchestration Python at the root, three vendored model repos,
and a research tree (`profiling/`, `benchmark/`) that has grown large enough to rival the
application itself.

The repo has **no nested `embedded_tts/` folder** — this directory *is* the working root. Three
vendored model repos (`FastSpeech2/`, `hifi-gan-master/`, `Waveglow/`) and one vendored weights
folder (`flaubert/`) sit alongside a thin orchestration layer of eight root-level `.py` files,
wired together through **module-level globals** (`loading_modules.py`, `tts_utils.py`) rather than
passed objects — see `docs/context/ARCHITECTURE.md` "Global-state loading pattern."

### Entry points

| Entry point | Invoked as | Leads to |
|---|---|---|
| `do_tts.py` | CLI: `python3 do_tts.py [flags]` — wrapped by a Claude Code plugin (`/chatterbox:benchmark` etc.) | free-text loop · `--gui` · `--benchmark` · `--p4-sweep` · `--report-wav` |
| `benchmark/runner.py` | imported by `do_tts.py --benchmark`, not run directly | `audio_utils.syn_audio()`, same call as free-text |
| `benchmark/p4_sweep.py` | imported by `do_tts.py --p4-sweep`; also has its own `__main__` for `--refit` | owns its own profiling sessions per cadence point |
| `profiling/sampler.py` | spawned as a subprocess: `python -m profiling.sampler` | 10 Hz CPU/PMIC/thermal sampler, writes `profile/per_sample.csv` |
| `profiling/calibrate.py` | `python -m profiling.calibrate` | single-state PMIC averaging helper |
| `pmic_calibrate.py` | `python3 pmic_calibrate.py` (root-level, standalone) | guided multi-state wizard, also writes `profile/calibration.json` |
| `benchmark/export_to_xlsx.py` | imported by `do_tts.py --export-xlsx` | reads the join's CSVs, writes `profile/exports/…xlsx` |

`pmic_calibrate.py` and `profiling/calibrate.py` both produce `profile/calibration.json` from
different workflows (guided multi-point wizard vs. single-state helper you run by hand at each
state) — flagged in §4, not treated as a clear duplicate.

### Daily-use path vs. research/maintenance-only

- **Daily use (must always work, minimal deps):** `do_tts.py`, `loading_modules.py`,
  `synthesis_modules.py`, `audio_utils.py`, `audio_postprocess.py`, `gui_utils.py`, `keyboards.py`,
  `tts_utils.py`, `config_tts.yaml`, the three regex-rule CSVs, `audio_keyboards/`, and the vendored
  model repos.
- **Research / measurement (opt-in, off by default):** `profiling/` (10 Hz sampler, per-sentence
  recorder, offline join, calibration), `benchmark/` (fixed sentence set, runner, P4 cadence sweep,
  xlsx export), `pmic_calibrate.py`. Already gated behind `profiling.enabled` / `--profile` /
  `--benchmark` — the gating is sound, only the *location* mixes it with daily-use code.
- **Generated / non-code (currently in the source tree):** `profile/P4 - First Full try/`,
  `profile/Step 7B…7D/` (17 MB of per-run CSV/JSONL/XLSX — see §4), stray demo WAVs at repo root,
  `graphify-out/` (this AI-assistant tool's own cache, 3.7 MB, 80+ JSON files).
- **Vendored (upstream-tracked, don't restructure internals):** `FastSpeech2/`,
  `hifi-gan-master/`, `Waveglow/` — each its own README/LICENSE/requirements.txt. Weights
  themselves are gitignored (~3.7 GB not in git).

### Import / dependency graph — the orchestration layer

Traced directly from `import` statements (not from the stale 2026-07-08 graphify snapshot, which
predates the profiling/benchmark subsystems and the P4 sweep — `graphify query` was checked first
per `CLAUDE.md`, but its BFS surfaced mostly the vendored model internals, not this orchestration
layer, so the dependency edges below are grep-verified).

```
do_tts.py
 ├─ loading_modules.py ──sys.path.insert──▶ FastSpeech2/utils/model.py, hifi-gan-master/{env,models}.py
 ├─ gui_utils.py ─┬─ loading_modules.py
 │                ├─ tts_utils.py
 │                ├─ audio_utils.py
 │                └─ keyboards.py ──▶ gui_utils.py   (circular: keyboards ⇄ gui_utils)
 ├─ audio_utils.py ─┬─ gui_utils.py
 │                  ├─ tts_utils.py
 │                  ├─ synthesis_modules.py
 │                  └─ profiling  (contextvar-published recorder)
 ├─ synthesis_modules.py ─┬─ loading_modules.py
 │                        ├─ profiling
 │                        └─ (bare) synthesize, text, dataset, inference_e2e, inference
 │                            — resolved ONLY because loading_modules.py already pushed
 │                              ./FastSpeech2, ./hifi-gan-master, ./Waveglow onto sys.path
 ├─ profiling/*  (self-contained package; sampler.py runs as its own subprocess)
 └─ benchmark/*  ──▶ audio_utils.py, loading_modules.py, profiling (no parallel synthesis path)
```

> **The load-bearing fact for this whole reorg.** `loading_modules.py` does
> `sys.path.insert(1, "./FastSpeech2")` — relative to the process's **current working directory**,
> not to the file's own location. Every bare import in `synthesis_modules.py` (`from synthesize
> import synthesize`, `from text import text_to_sequence`, `from dataset import …`, `from
> inference_e2e import inference`) resolves only because `loading_modules` is guaranteed to be
> imported first and `do_tts.py` is always launched from the repo root. See §6 for why this is the
> actual constraint the reorg has to satisfy, not the folder names.

---

## 2. Proposed tree & file mapping

The starting hypothesis holds up well for the big-picture split (application vs. tooling vs.
assets vs. docs) but two of its suggested subfolders don't earn their keep once weighed against the
actual file count and coupling — flagged inline below rather than silently adopted.

```
chatterbox/                       ← installable package: daily-use code only
├── cli.py                        real do_tts.py logic (argparse, load_models, warmup)
├── synthesis/
│   ├── base.py                   NEW — Synthesizer ABC (see §5)
│   ├── registry.py               NEW — config-driven backend lookup
│   ├── backends/
│   │   └── fastspeech2_hifigan/
│   │       ├── backend.py        loading_modules.py + syn_fastspeech2/syn_hifigan
│   │       ├── text_pipeline.py  parse_params_from_text, control-tag mini-language
│   │       └── rules/            custom_/symbols_/url_regex_rules.csv
│   ├── audio_postprocess.py      unchanged — stays dependency-light (numpy+scipy)
│   └── subtitles.py              write_subtitles/write_duration_alignements, split out of audio_utils.py
├── audio/
│   ├── playback.py               play_audio() + Windows/pydub platform branch
│   └── denoise.py                noisereduce wrapper, currently inline in audio_utils.py
├── gui/
│   ├── app.py                    gui_utils.py, talks to Synthesizer only (see §5)
│   └── keyboards.py
├── config/
│   ├── config_tts.yaml
│   └── paths.py                  NEW — repo-root-anchored path resolution (kills the CWD-relative sys.path hack)
└── state.py                      tts_utils.py

tools/                            ← research / maintenance, NOT daily-use
├── measurement/
│   ├── benchmark/                benchmark/ package, unchanged internally
│   └── pmic_calibrate.py
└── monitoring/
    └── profiling/                profiling/ package, unchanged internally

assets/
├── audio/
│   ├── reference/                La_bise_Neutre_NEB.wav + siblings — postprocessing before/after
│   │                             demo pairs, reclassified from delete-candidates (see §4)
│   └── prompts/                  audio_keyboards/Emmanuelle/*.wav → Emmanuelle/*.wav (on-screen
│                                 keyboard phoneme prompts)
└── models/                       FastSpeech2/, hifi-gan-master/, Waveglow/, flaubert/ (vendored,
                                  gitignored weights; move-as-is is a lower-effort default now, not
                                  an upstream-merge constraint — see §6)

hardware/                         NEW, empty — needs a .gitkeep or stub README.md to survive the
                                  commit (git doesn't track empty directories); reserved for
                                  BOM/enclosure/wiring (Goal 5), nothing to move yet

docs/
├── context/                      ARCHITECTURE.md, CHANGELOG.md — unchanged
└── assets/
    └── tts_gui.png                only README-referenced image

scripts/
└── setup_pi.sh

tests/                            unchanged — already mirrors the app/tools split via test file names

do_tts.py                          KEPT AT ROOT as a 3-line compat shim → chatterbox.cli.main()
README.md · INSTALL.md · CLAUDE.md stay at root (GitHub/tooling convention)
requirements-dev.txt · requirements-pi.txt · requirements-pi-lock.txt
requirements.txt · minimal_requirements.txt  stay at root, unchanged (see below)
apt-packages-pi.txt
```

> **Where I disagree with the starting hypothesis.**
> **No `requirements/` folder.** Five files, already unambiguously named (`-dev`/`-pi`/`-pi-lock`,
> plus two deprecated ones with deprecation banners already in their first line). Moving them means
> editing `INSTALL.md`, `scripts/setup_pi.sh`, and `CLAUDE.md` path references for zero
> separation-of-concerns gain — the goal ("avoid the `apex` / `requirements.txt` collision") is
> already satisfied by the naming, not by a folder.
>
> **No bare `src/`.** `chatterbox/` doubles as the installable package name — `src/chatterbox/`
> would be more conventional for a publishable PyPI package, but this project is an on-device
> demonstrator invoked as a script/plugin, not installed from an index; the extra nesting buys
> nothing here.

### File-by-file mapping

#### Root orchestration files (8 files — the reorg's actual surface area)

| Old path | New path | Action | Note |
|---|---|---|---|
| `do_tts.py` | `chatterbox/cli.py` + 3-line root shim | move | CLI flags unchanged; shim preserves `python3 do_tts.py …` |
| `loading_modules.py` | `chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py` | move | becomes the `Synthesizer` implementation |
| `synthesis_modules.py` | `…/fastspeech2_hifigan/backend.py` + `text_pipeline.py` | split | text-tag parsing vs. model calls are two responsibilities today |
| `audio_utils.py` | `chatterbox/audio/playback.py` + `chatterbox/audio/denoise.py` + `chatterbox/synthesis/subtitles.py` + `chatterbox/cli.py` (orchestration) | split | `syn_audio()` currently does denoise+postprocess+visual-smoothing+subtitles+playback in one function — four extraction targets, not three; don't lose the denoise split during the move |
| `audio_postprocess.py` | `chatterbox/synthesis/audio_postprocess.py` | move | no internal changes — already dependency-light, own test file |
| `gui_utils.py` | `chatterbox/gui/app.py` | move | stop importing `loading_modules` directly — go through `Synthesizer` (§5) |
| `keyboards.py` | `chatterbox/gui/keyboards.py` | move | circular import with gui_utils persists unless addressed (§6) |
| `tts_utils.py` | `chatterbox/state.py` | move | 14 lines; candidate to fold into registry.py instead — your call |
| `config_tts.yaml` | `chatterbox/config/config_tts.yaml` | move | `do_tts.py --config` default path updates accordingly |
| `custom_/symbols_/url_regex_rules.csv` | `…/fastspeech2_hifigan/rules/*.csv` | move | currently opened via bare CWD-relative filename (§6) — fix path resolution in the same commit |
| `do_normalize_txt.pl` | — | **delete** | already documented dead in `apt-packages-pi.txt`'s own comment; confirmed no references anywhere in the tree |

#### Research / measurement tooling (benchmark/, profiling/, pmic_calibrate.py)

| Old path | New path | Action | Note |
|---|---|---|---|
| `benchmark/*.py, sentences_fr.jsonl` | `tools/measurement/benchmark/*` | move | internal imports (`audio_utils`, `loading_modules`) become absolute `chatterbox.*` imports |
| `profiling/*.py` | `tools/monitoring/profiling/*` | move | `python -m profiling.sampler` becomes `python -m tools.monitoring.profiling.sampler` — update the one subprocess call site in `sampler.py`'s launcher |
| `pmic_calibrate.py` | `tools/measurement/pmic_calibrate.py` | move | standalone script, no internal imports to fix |
| `tests/test_benchmark.py, test_p4_sweep.py, test_export_xlsx.py, test_profiling.py` | `tests/` (unchanged) | keep | update their `import benchmark…` / `import profiling…` to the new dotted paths |

#### Vendored model repos & weights (FastSpeech2/, hifi-gan-master/, Waveglow/, flaubert/)

| Old path | New path | Action | Note |
|---|---|---|---|
| `FastSpeech2/**` | `assets/models/FastSpeech2/**` | move dir | no internal restructuring — now a lower-effort default, not an upstream-merge constraint (§6 is N/A: no further merges from `MartinLenglet/embedded_tts`); update the corresponding `paths.py` entry in the same commit (Phase 1) |
| `hifi-gan-master/**` | `assets/models/hifi-gan-master/**` | move dir | same |
| `Waveglow/**` | `assets/models/Waveglow/**` | move dir, **flag** | currently disabled/unused. Default: move-as-is (safe). If dropping instead: also remove the live `from inference import main as inference_main` bare-import and its `sys.path.insert(1, './Waveglow/tacotron2')` in `synthesis_modules.py` (§6), and confirm the path is runtime-dead, not merely dormant, before deleting. Since the fork no longer tracks upstream, dropping/flattening vendored repos is now a free choice, not constrained by future merge conflicts. |
| `flaubert/**` | `assets/models/flaubert/**` | move dir | the `./flaubert/flaubert_large_cased` hardcode in `FastSpeech2/utils/model.py:16` was fixed in Phase 0 by routing through `paths.py` — its `paths.py` entry must be re-pointed to the new location in the same commit as this move (Phase 1), or FlauBERT silently fails to load post-move |

#### Docs, scripts, requirements, misc top-level files

| Old path | New path | Action | Note |
|---|---|---|---|
| `README.md, INSTALL.md, CLAUDE.md` | (unchanged) | keep in place | update path references inside them (§6) |
| `docs/context/*` | (unchanged) | keep in place | content updated for new layout |
| `tts_gui.png` | `docs/assets/tts_gui.png` | move | only image actually referenced by README |
| `requirements-dev.txt, requirements-pi.txt, apt-packages-pi.txt` | (unchanged) | keep in place | see "where I disagree," above |
| `requirements.txt, minimal_requirements.txt` | (unchanged) | keep in place, **flag** | both already self-documenting as deprecated; candidates to delete outright once you're comfortable losing the training-env reference — your call, not done here |
| `scripts/setup_pi.sh` | (unchanged) | keep in place | weight-download target paths inside it update to `assets/models/…` |
| `tests/**` | (unchanged) | keep in place | import statements only |

#### Non-code artifacts currently inside the source tree (see §4 for full reasoning)

| Old path | New path | Action | Note |
|---|---|---|---|
| `profile/P4 - First/Second Full try/, profile/Step 7B…7D/` | (out of git, or a separate data/results repo) | flag | 17 MB of generated experiment output, currently tracked because git's shallow `profile/*.csv` ignore rule doesn't reach nested run folders |
| `graphify-out/` | (gitignore it) | flag | this AI-assistant tool's own cache/report — build artifact of a dev tool, not project source |

The root demo WAVs previously listed here as delete-candidates have been reclassified — see
"Audio assets" below and §4.

#### Audio assets (reinstated category — reference WAVs, keyboard prompts)

The original brief's hypothesis included an `assets/audio/` category for "registered test signals,
reference and generated WAVs." An earlier pass of this proposal dissolved it — keyboard prompts
folded into `gui/assets/`, reference WAVs left on the delete-candidate list. Reinstated below.

| Old path | New path | Action | Confidence |
|---|---|---|---|
| `La_bise_Neutre_NEB.wav` | `assets/audio/reference/La_bise_Neutre_NEB.wav` | keep, relocate | **confirmed** — crest-factor / operating-level reference sample (FastSpeech2 + HiFi-GAN, 22050 Hz, 31.6 s) |
| `La_Bise_Neutre_NEB_opti.wav` | `assets/audio/reference/` | keep, relocate | **inferred** — same reference sentence, `_opti` suffix reads as its `audio_postprocess.py` before/after counterpart |
| `La_bise_Neutre_NEB_phon.wav` | `assets/audio/reference/` | keep, relocate | **inferred** — same reference sentence, `_phon` suffix reads as a phonetic-input (`{s y z i}`) demo variant |
| `la_bise_NORMAL_AD.wav` | `assets/audio/reference/` | keep, relocate | **inferred** — second reference sentence/speaker (AD, NORMAL style), mirrors the Neutre/NEB pair's naming |
| `la_bise_NORMAL_AD_opti.wav` | `assets/audio/reference/` | keep, relocate | **inferred** — postprocessed counterpart of the row above |
| `audio_keyboards/Emmanuelle/*.wav` | `assets/audio/prompts/Emmanuelle/*.wav` | move | phoneme audio prompts read by `keyboards.py`/`gui_utils.py` for the on-screen keyboard preview |

The four "inferred" rows were on the delete-candidate list in an earlier pass; now that
`La_bise_Neutre_NEB.wav` is confirmed as a kept reference sample, the naming symmetry
(`{sentence}_{speaker}` plus `_opti`/`_phon` variants) reads as a deliberate before/after
demonstration set for two reference sentences, not orphaned output. None are recommended for
deletion here. All six rows relocate in Phase 4 (§7).

---

## 3. Rationale per top-level directory

**`chatterbox/`** — Everything that must run for the demonstrator to speak, every day, on the Pi.
If it's not needed for that, it doesn't belong here — that single test is what makes Goals 2–4
(swappable model, swappable GUI, monitoring-optional) checkable rather than aspirational.

**`tools/`** — Everything that exists to *measure or maintain* the demonstrator, not to run it.
Splitting `measurement/` (benchmark, power sweeps — used in bursts, during evaluation) from
`monitoring/` (would run continuously if ever wired into the daily path) keeps Goal 4's "not a hard
dependency, not shipped in the runtime image" enforceable at the packaging level, not just by
convention.

**`assets/models/`** — ~3.7 GB of vendored weights and code, all gitignored except the code itself.
Isolating it under one path makes the "don't ship this to a lean runtime image" story a single
directory exclusion, and makes clear at a glance which folders are "someone else's repo, vendored"
vs. "ours."

**`assets/audio/`** — Reinstated from the original brief's hypothesis (it had dissolved in an
earlier pass of this proposal, with keyboard prompts folded into `gui/assets/` and the reference
WAVs left as delete-candidates at the repo root). `reference/` holds the postprocessing
before/after demo pairs; `prompts/` holds `audio_keyboards/`'s phoneme WAVs. Both are data the GUI
reads at runtime, not code — they belong under `assets/`, not `chatterbox/gui/`, by the same
code-vs-non-code test as `assets/models/`.

**`hardware/` (new, empty)** — Nothing to move here yet — no BOM/enclosure/wiring files exist in the
current tree. Reserved per Goal 5 for when the open-source hardware release happens; flagged as
aspirational so it isn't mistaken for an oversight in the mapping table.

**`docs/` & `scripts/`** — Unchanged in spirit — `docs/context/` already does exactly what Goal 5
asks. Added `docs/assets/` for the one image the README actually embeds.

**Root-level files** — `README.md`/`INSTALL.md`/`CLAUDE.md`/requirements files/`do_tts.py` shim stay
at the root deliberately — GitHub rendering, pip tooling, and the documented CLI contract all
expect them there. "Clear in 30 seconds" (Goal 1) is about the code, not about maximizing how much
moves.

---

## 4. Dead / unused / duplicate files — flagged, not deleted

| File(s) | Evidence | Confidence |
|---|---|---|
| `do_normalize_txt.pl` | Repo's own `apt-packages-pi.txt` comment states outright: "`do_normalize_txt.pl`, the latter currently unused/dead code." No importers, no shell-out call site found anywhere in the Python tree. | **High** — repo self-documents this |
| `graphify-out/` | Generated cache/report for this AI-assistant's own knowledge-graph tool (80+ AST-cache JSON files, `graph.html`, `manifest.json`) — a build artifact of a dev-time tool, tracked in git. Not consumed by any project code. | **Medium** — gitignore going forward; deleting history is your call |
| `profile/P4 - First/Second Full try/, profile/Step 7B - 2/, …7B - 3/, …7B - 4/, profile/Step 7C - */, profile/Step 7D - */` | 17 MB of per-run experiment output (CSV/JSONL/XLSX), tracked only because git's `profile/*.csv` gitignore rule is shallow and doesn't reach nested `cadence_NN/` subfolders. One straggler, `profile/P4 - First Full try/~$sweep_paste.xlsx` — an Excel lock file — is already showing as deleted in your working tree, i.e. you're mid-cleanup on exactly this category. | **Low confidence on delete** — this is real research data, not junk; flagging the *location*, not the content |
| `requirements.txt`, `minimal_requirements.txt` | Both carry their own deprecation banner as the first lines of the file (per `INSTALL.md` and `CLAUDE.md`, deliberately "kept for reference," not accidental cruft). | Not dead by design — kept on purpose, listed here only for completeness |
| `pmic_calibrate.py` vs. `profiling/calibrate.py` | Both write `profile/calibration.json` via different workflows (guided multi-point wizard vs. single-state manual helper). Functional overlap, but not a strict duplicate — worth asking whether one has been superseded by the other in practice. | Needs your call, not a code-level determination |

*The five root demo WAVs previously listed here have been reclassified as kept reference/comparison
assets — see §2 "Audio assets" and §3. `La_bise_Neutre_NEB.wav` is a confirmed reference sample;
its siblings are inferred comparison pairs by naming symmetry, not confirmed dead.*

---

## 5. Interface boundaries

Two boundaries need to exist that don't today: a **Synthesizer** abstraction (so Matcha-TTS or
FastSpeech2s can be a second backend instead of a rewrite), and a **GUI↔synthesis** API (so the GUI
never imports `loading_modules` or any backend module directly).

### Synthesizer abstraction

```python
# chatterbox/synthesis/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class SynthesisRequest:
    text: str
    speaker: str | None = None
    style: str | None = None            # GST emotion token name
    style_intensity: float = 1.0
    style_tag: str | None = None        # free-text, FlauBERT-conditioned
    control_bias: dict[str, float] = field(default_factory=dict)

@dataclass
class SynthesisResult:
    mel_path: str
    au_path: str | None                 # facial/visual animation params -- optional per backend
    sample_rate: int

class Synthesizer(ABC):
    """One instance == one loaded (acoustic model, vocoder) pair."""

    @abstractmethod
    def load(self, model_config: dict, device) -> None: ...

    @abstractmethod
    def synthesize(self, request: SynthesisRequest) -> SynthesisResult: ...

    @abstractmethod
    def vocode(self, result: SynthesisResult) -> str: ...     # -> wav path

    def describe_controls(self) -> dict:
        """GUI renders sliders/buttons off this instead of special-casing
        the backend by name (kills gui_utils.py's gui_fastspeech2()-style
        branching)."""
        raise NotImplementedError


# chatterbox/synthesis/registry.py -- same load_script/syn_script string
# pattern config_tts.yaml already uses, just formalized as an import path
# instead of a getattr() lookup on a flat module.
BACKENDS = {
    "fastspeech2_hifigan": "chatterbox.synthesis.backends.fastspeech2_hifigan:Backend",
    "matcha_tts":           "chatterbox.synthesis.backends.matcha_tts:Backend",   # future
}
```

This is a smaller change than it looks: `config_tts.yaml`'s `load_script`/`syn_script`/`gui_script`
strings are already a config-driven registry in spirit (`getattr(loading_modules,
entry["load_script"])`). The work is consolidating three free functions per backend into one class
that owns its own globals instead of stashing them on the `loading_modules` module object — which
also directly fixes the "keep this in mind before refactoring toward passed-in objects" warning
already in `ARCHITECTURE.md`.

### How Matcha-TTS would slot in

A new `chatterbox/synthesis/backends/matcha_tts/backend.py` implementing `Synthesizer`, a new
`tts_models` entry in `config_tts.yaml` pointing `load_script`/`syn_script` at it, and nothing else
changes — `do_tts.py`'s `load_models()`, the GUI, and the benchmark runner all already dispatch by
config string, not by hardcoded model name. The one piece that needs to exist first: Matcha-TTS
doesn't produce the `.AU` facial-animation channel FastSpeech2 does, so `SynthesisResult.au_path`
needs to already be `Optional` (as sketched above) before a second backend can land — today's code
assumes an AU file unconditionally in a few places in `audio_utils.py`.

### GUI ↔ synthesis API

`chatterbox/gui/app.py` (today's `gui_utils.py`) should hold a `Synthesizer` instance and call
`describe_controls()` / `.synthesize()` / `.vocode()` — never `import
chatterbox.synthesis.backends.fastspeech2_hifigan` directly, and never reach into a backend's
globals the way `gui_utils.py:355` currently re-opens `tts_config['folder']`'s YAML files itself to
read GST token names for the style picker. That one call site is the GUI's only real
synthesis-internals leak today; folding token metadata into `describe_controls()` closes it.

### Monitoring as a decoupled, optional add-on

`profiling/` already follows the right pattern — module-level `enable()`, a no-op `NullRecorder` by
default, lazy `try/except` import of the Pi-only `smbus2`. Moving it to
`tools/monitoring/profiling/` is a relocation, not a redesign; the only additional step for Goal 4
("ideally not shipped in the runtime image") is making the exclusion enforceable — e.g. a packaging
manifest or a Pi image-build step that omits `tools/` entirely, rather than relying on the flag
being off by default.

---

## 6. Risk & impact notes

### The real import-path risk (not the folder renames)

**High — CWD-relative `sys.path.insert` in loading_modules.py.** `sys.path.insert(1,
"./FastSpeech2")`, `"./hifi-gan-master"`, `"./Waveglow"` — all relative to the process's current
working directory, not `__file__`. Today this "works" only because `do_tts.py` is always launched
with CWD at the repo root. Move `loading_modules.py` into
`chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py` without also fixing this, and it
silently breaks the moment anyone runs the entry point from a different directory (which becomes
likely once `do_tts.py` is a package-relative shim rather than the literal file being executed).

*Fix, as its own early step, independent of any folder move:* anchor these three inserts on a path
computed from the package's own location (`Path(__file__).resolve().parents[N]`) or a single
`CHATTERBOX_ROOT` resolved once in `chatterbox/config/paths.py`. Doing this first actually de-risks
every subsequent move — once path resolution no longer depends on CWD, relocating the orchestration
files around it is mechanical.

**High — same-named modules across three vendored repos sharing one sys.path.** `inference.py`
exists in `hifi-gan-master/`, `Waveglow/`, *and* is bare-imported from `Waveglow/tacotron2/` in
`synthesis_modules.py` (`from inference import main as inference_main`, after its own
`sys.path.insert(1, './Waveglow/tacotron2')`). `models.py` (hifi-gan-master) vs. FastSpeech2's
`model/` package, `env.py`, `dataset.py`, `text/` — all bare top-level module names, resolved purely
by **sys.path insertion order**, which is itself an accumulation of insert calls across two files
(`loading_modules.py` at import time, then `synthesis_modules.py`'s own leftover insert). This is
not hypothetical fragility — it is the actual mechanism keeping today's imports correct, and it has
zero test coverage because it only fails by silently importing the *wrong* same-named module, not
by raising.

*Fix:* this is exactly what the backend-adapter boundary in §5 should own — each backend module
should import its vendored dependencies via `importlib.util.spec_from_file_location` scoped to its
own subtree, or vendor each model repo as a proper installable subpackage, instead of mutating
global `sys.path`. Worth doing regardless of whether the broader reorg proceeds.

**✅ Fixed — gitignored FastSpeech2 config YAMLs hardcode their own repo-root-relative paths,
discovered during Phase 1.** `assets/models/FastSpeech2/config/ALL_corpus/preprocess.yaml`
(`path.preprocessed_path`, `path.output_syn_path`) and `train.yaml` (`path.ckpt_path`) each contain
a literal `"FastSpeech2/…"` string, read directly by `FastSpeech2/model/modules.py` and
`FastSpeech2/utils/model.py` as a path relative to the process's CWD — a third hardcoding mechanism
alongside `sys.path.insert` and the Python-level hardcodes already in this table, and the one that
slipped through the original audit (no leading `./`, so the grep pattern that caught everything
else in this table didn't match it). These YAMLs are **gitignored** — downloaded from the Google
Drive archives named in `README.md`, never committed — so patching the local copy alone doesn't fix
anything for a fresh `scripts/setup_pi.sh` run, which re-downloads and re-unzips the same
stale-path archive.

*Fix (implemented):* `loading_modules.py` now has
`_repoint_legacy_fastspeech2_config_paths()`, called right after the three YAMLs load in
`load_fastspeech2()`. It rewrites `preprocessed_path`/`output_syn_path`/`ckpt_path` **in memory**
to `ROOT/assets/models/<value>` whenever the value still starts with the legacy `"FastSpeech2/"`
prefix — i.e. it re-derives the same `assets/models/` prefix I'd otherwise have to hand-patch into
every fresh download, so it works for `scripts/setup_pi.sh`, a manual README-instructions install,
*and* this checkout, all from the same code path, with zero YAML editing required. Verified by
reverting the local YAMLs to their original stale content and re-running the smoke test — it
picked up the legacy values and remapped them correctly. Chosen over patching
`scripts/setup_pi.sh` with a `sed` step because that would only cover the Pi provisioning path, not
a manual Windows/PC install following the same README instructions.

**Medium — directory-depth assumptions baked into `dirname()`/`parents[N]`-style constants, found
during Phase 2.** `profiling/__init__.py` (now `tools/monitoring/profiling/__init__.py`) had
`_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` — two `dirname()`
hops, correct only because `profiling/` used to sit exactly one level under the repo root. Phase 2
nested it three levels deep (`tools/monitoring/profiling/`), silently breaking the `subprocess.Popen(...,
cwd=_PACKAGE_ROOT)` call that launches the sampler (it would have pointed at `tools/monitoring/`,
not the repo root). Fixed by replacing it with `paths.ROOT` directly — but the general lesson
applies beyond this one constant: **any hardcoded `dirname()`-chain or `Path(__file__).parents[N]`
elsewhere in the codebase is a landmine for Phase 3**, which nests files even deeper
(`chatterbox/synthesis/backends/fastspeech2_hifigan/...`). Grep for `dirname(dirname`,
`parents[`, and similar patterns across the whole tree before executing Phase 3, not just in the
files being moved that phase.

### Hardcoded paths

| Location | What's hardcoded | Fix |
|---|---|---|
| `FastSpeech2/utils/model.py:16` | `modelname = './flaubert/flaubert_large_cased'` — CWD-relative, bypassed `config_tts.yaml` entirely | ✅ fixed in Phase 0 — routed through `paths.FLAUBERT_DIR` |
| `loading_modules.py`'s three `sys.path.insert` calls | `"./FastSpeech2"`, `"./hifi-gan-master"`, `"./Waveglow"` — CWD-relative | ✅ fixed in Phase 0 — routed through `paths.py` |
| `synthesis_modules.py`'s `sys.path.insert(1, './Waveglow/tacotron2')` | a **fourth** CWD-relative insert Phase 0 missed (only the three in `loading_modules.py` were in its checklist) | ✅ fixed during Phase 1 verification, after it broke `pytest` collection post-move — routed through `paths.WAVEGLOW_DIR / "tacotron2"` |
| `synthesis_modules.py` (regex_file, symbols_regex_file, url_regex_file) | bare CWD-relative filenames for the three rule CSVs | ✅ fixed in Phase 0 — routed through `paths.py` |
| `loading_modules.py` (tts_model["folder"], vocoder_model["folder"]) | config-driven from `config_tts.yaml`, base was CWD-relative | ✅ fixed in Phase 1 — `config_tts.yaml`'s `folder` values now read `assets/models/…` |
| `FastSpeech2/config/ALL_corpus/{preprocess,train}.yaml` (`preprocessed_path`, `output_syn_path`, `ckpt_path`) | literal `"FastSpeech2/…"` strings inside **gitignored** config files (downloaded, never committed) | ✅ fixed — `loading_modules._repoint_legacy_fastspeech2_config_paths()` remaps them in memory at load time; works for fresh downloads too, not just this checkout (see §6) |
| `tools/monitoring/profiling/__init__.py`'s `_PACKAGE_ROOT` | `dirname(dirname(__file__))` — assumed `profiling/` was exactly one level under repo root | ✅ fixed in Phase 2 — now just `str(paths.ROOT)` |
| `audio_utils.py:268` | `shutil.copy(path_au, "./")` — copies the AU file to CWD explicitly | make explicit once a real output directory exists, rather than implicitly "wherever you launched from" |
| GPIO / amp-mute, ALSA device selection | **not found** — no GPIO or amp-mute code exists anywhere in the current tree | the starting hypothesis's `config/` description assumes hardware-control code that hasn't been written yet; treat as aspirational, not a migration item |

### Pi runtime vs. Windows dev — what specifically breaks

| Change | Pi 5 (deployment) | Windows (dev) |
|---|---|---|
| `sys.path` CWD-relative fix | no behavior change if `setup_pi.sh` / systemd unit still launches from repo root; becomes required if a console-script entry point is ever added | same — VS Code Remote-SSH launch config already sets CWD, unaffected either way |
| Moving `profiling/` under `tools/monitoring/` | `profiling/sampler.py`'s own subprocess launch (`python -m profiling.sampler`) must update its module path — this is the one runtime-only code path (reads `/proc/stat`, `vcgencmd`) that only executes on the Pi, so a mistake here is invisible on Windows and only surfaces on real hardware | sampler already no-ops with a warning on non-Linux — a broken module path here just changes the warning text on this platform, not a real risk |
| Moving vendored weights under `assets/models/` | `scripts/setup_pi.sh`'s `fetch_and_unzip` target paths and sentinel-file checks must update — currently hardcoded to `$WORKING_ROOT/FastSpeech2` etc. | no weight-download step on Windows (manual per README) — just update the README paths |
| `requirements-pi.txt` staying at root (per this proposal) | zero change | zero change |

**Gitignored-weights caveat for `git mv`.** The ~3.7 GB of model weights live *inside*
`FastSpeech2/`, `hifi-gan-master/`, `Waveglow/`, `flaubert/` but are gitignored, not tracked by
git — `git mv` only renames tracked paths, so on an **existing Pi checkout** (not a fresh clone),
the untracked weight files must be confirmed to have physically relocated along with the directory
rename (a plain filesystem move, which `git mv` performs under the hood, does carry them — but this
needs verifying by hand, not assumed, so we don't silently re-fetch 3.7 GB or leave orphaned copies
at the old path). Phase 1's Verify step below includes this explicitly. Fresh clones are
unaffected — `scripts/setup_pi.sh` downloads weights directly into whatever path
`paths.py`/`config_tts.yaml` point at post-move.

### Upstream merge cost — N/A

**This fork will never merge from `MartinLenglet/embedded_tts` again** — it syncs only to
`Raphaelll09/chatterbox` going forward. Upstream-merge disruption is therefore not a constraint on
this reorg: moving, flattening, or restructuring `FastSpeech2/`, `hifi-gan-master/`, `Waveglow/`
internals is a free choice on cost/benefit grounds alone. The original analysis is kept below for
the record, since it's what justified moving the vendored directories as whole, unrestructured
blocks in §2 — that recommendation now stands as a **lower-effort default**, not a constraint.

> **Original analysis (retained for context, no longer load-bearing):**
>
> Quantifying disruption to future pulls from `MartinLenglet/embedded_tts`: the three vendored
> model directories (`FastSpeech2/`, `hifi-gan-master/`, `Waveglow/`) are the files most likely to
> receive upstream changes, and this proposal moves them as whole directories with **zero internal
> restructuring** — a `git mv FastSpeech2 assets/models/FastSpeech2` is a rename Git tracks cleanly;
> any future `git fetch upstream && git merge` would need the same rename applied to upstream's
> incoming changes (a one-time path-prefix rewrite, not a per-file conflict). The orchestration
> layer (`do_tts.py`, `*_modules.py`, `gui_utils.py`) is this fork's *own* code — upstream has no
> equivalent restructure to conflict with there, since these files don't appear to exist in that
> shape upstream once the fork's own profiling/benchmark/postprocess additions are accounted for.
> **Net assessment: moderate, front-loaded cost** (one rewrite of upstream's next diff against
> three renamed directories), **not a permanent tax** — each subsequent merge is normal once the
> rename is absorbed once.

### Context-file & CLI-contract drift

Every path reference in `CLAUDE.md`, `docs/context/ARCHITECTURE.md`, `README.md`, and `INSTALL.md`
needs updating in the same commit as the move it describes — same discipline the "Maintenance
rules" section of `CLAUDE.md` already mandates for ordinary changes, just at reorg scale. The
`do_tts.py` CLI contract itself (every flag listed in the repo map: `--benchmark`, `--profile`,
`--play`, `--join`, `--repeats`, `--p4-sweep`, `--cadences`, `--duration`, `--export-xlsx`, `--ina`,
`--report-wav`, `--postprocess`) is preserved unchanged by design — the root `do_tts.py` shim means
the Claude Code plugin wrapping these flags needs no changes at all.

---

## 7. Phased migration plan

Ordered so each phase is independently revertible and leaves the tree in a runnable state — the
path-anchoring fix comes *before* any directory move, on purpose, since it's what makes every later
move mechanical instead of risky.

> **Path-anchoring invariant, applies to every phase below.** Phase 0 anchors each path to its
> *current* location in `paths.py`. Every subsequent phase that relocates a file or directory must
> also update that path's entry in `paths.py` in the same commit — the anchoring removes
> CWD-dependence, it does not remove the need to update the path value when the target moves. Treat
> this as a checklist item for every phase, not just the ones that call it out explicitly.

### Phase 0 — De-risk path resolution (no files move) — ✅ done (branch `reorg/phase-0-path-anchoring`)

*Prerequisite for everything below.*

- [x] Added `paths.py` — a temporary root-level module (`chatterbox/` doesn't exist until Phase 3),
  anchored via `ROOT = Path(__file__).resolve().parent`.
- [x] Rewrote the three `sys.path.insert(1, "./…")` calls in `loading_modules.py` to use
  `paths.FASTSPEECH2_DIR` / `paths.HIFIGAN_DIR` / `paths.WAVEGLOW_DIR`, and the regex-rule file
  constants in `synthesis_modules.py` to use `paths.CUSTOM_REGEX_RULES` /
  `paths.SYMBOLS_REGEX_RULES` / `paths.URL_REGEX_RULES`.
- [x] Fixed `FastSpeech2/utils/model.py:16`'s hardcoded FlauBERT path to use `paths.FLAUBERT_DIR`.

**Verify:** `pytest tests/` — 130 passed, unchanged. Real end-to-end smoke test on this Windows
checkout (real weights present locally): `printf 'Bonjour, ceci est un test.\n' | python
do_tts.py` — FlauBERT, FastSpeech2 (`390000`), and HiFi-GAN (`FR_V2/g_00570000`) all loaded via the
new anchored paths, and `audio_file.wav` was produced with normal per-stage timing. **No Pi 5
hardware access this round** (see the note at the top of §7) — this phase is Windows-verified,
Pi-unverified; the `sys.path` rewrite touches the exact import-ordering mechanism flagged in §6 as
having zero test coverage, so a real Pi run is still owed before this is considered fully safe.

### Phase 1 — Move vendored model repos + weights — ✅ done (same branch)

*Goal 5 (code vs. non-code), lowest coupling-risk move.*

- [x] `git mv FastSpeech2 hifi-gan-master Waveglow flaubert assets/models/`
- [x] Updated the three folder paths in `config_tts.yaml` (including the commented-out Waveglow
  entry, for consistency if it's ever re-enabled) and `scripts/setup_pi.sh`'s `fetch_and_unzip`
  targets/sentinels.
- [x] Updated the vendored-dir entries in `paths.py` (`FASTSPEECH2_DIR`, `HIFIGAN_DIR`,
  `WAVEGLOW_DIR`) and the **FlauBERT** entry (`FLAUBERT_DIR`) from `ROOT/<dir>` to
  `ROOT/assets/models/<dir>`.
- [x] Updated `.gitignore` patterns (`FastSpeech2/…` → `assets/models/FastSpeech2/…`, etc.).
- [x] Confirmed on this (existing, Windows) checkout that the gitignored weight files — including
  the 1.4 GB FlauBERT and 1.3 GB Waveglow binaries — physically relocated with the `git mv`
  directory rename, per §6's gitignored-weights caveat.

**Two additional fixes, found only by actually running the pipeline post-move (not by static
analysis — flagging this as a gap in the original §6 audit, not a new problem introduced here):**

1. **A fourth CWD-relative `sys.path.insert` that Phase 0 missed.** Phase 0's checklist only
   named the three inserts in `loading_modules.py`; `synthesis_modules.py` has its own
   `sys.path.insert(1, './Waveglow/tacotron2')` (feeding the disabled-by-default Waveglow path) that
   Phase 0 didn't touch. Post-move it inserted a now-nonexistent path, which meant `Waveglow/tacotron2`'s
   bare-imported sibling modules (`audio_processing`, `layers`, ...) resolved to nothing —
   `ModuleNotFoundError: No module named 'audio_processing'` on `pytest tests/` collection. This is
   the exact "same-named modules / sys.path insertion order" fragility §6 already flagged as
   zero-test-coverage — it just took this move to actually trip it. Fixed: that insert now uses
   `str(paths.WAVEGLOW_DIR / "tacotron2")`.
2. **Gitignored FastSpeech2 config YAMLs hardcode their own repo-root-relative paths, independent
   of `paths.py` and `config_tts.yaml`.** `assets/models/FastSpeech2/config/ALL_corpus/preprocess.yaml`
   (`path.preprocessed_path`, `path.output_syn_path`) and `train.yaml` (`path.ckpt_path`) each
   contained a literal `"FastSpeech2/…"` string — invisible to the original audit because it had no
   leading `./` (the grep pattern that surfaced every other hardcode in §6 only matched
   `"./`/`'./` prefixes). These files are gitignored (downloaded from the Google Drive archives,
   never committed), so hand-editing them on this checkout wouldn't fix anything for anyone else — a
   fresh `scripts/setup_pi.sh` run re-downloads and re-unzips the same archives, restoring the same
   stale value. **✅ Fixed** (as a follow-up, between Phase 1 and Phase 2) — see the updated §6 risk
   item: `loading_modules.py` now remaps these paths in memory at load time, so a fresh download
   works with no manual YAML editing at all, on any install path (Pi script, manual, or this
   checkout).

**Verify:** `pytest tests/` — 130 passed (after fix 1 above). Real end-to-end smoke test on Windows
against the now-relocated weights: FlauBERT, FastSpeech2 (`assets/models/FastSpeech2/390000`), and
HiFi-GAN (`assets/models/hifi-gan-master/FR_V2/g_00570000`) all loaded, and `audio_file.wav` was
produced with normal per-stage timing — re-verified after fix 2 by reverting the local YAMLs to
their stale, as-downloaded content and re-running, confirming the in-memory remap (not a lingering
hand-edit) is what makes it work. **Pi 5 hardware verification is owed, not available this round**
(see the note at the top of §7).

### Phase 2 — Move research/measurement tooling — ✅ done (same branch)

*Goal 4 (monitoring isolated as maintenance-only).*

- [x] `git mv benchmark/ tools/measurement/benchmark/`, `git mv profiling/
  tools/monitoring/profiling/`, `git mv pmic_calibrate.py tools/measurement/`.
- [x] Added `tools/__init__.py`, `tools/measurement/__init__.py`, `tools/monitoring/__init__.py`
  (explicit packages, consistent with the rest of the codebase rather than relying on implicit
  namespace packages).
- [x] Updated every `import benchmark…` / `import profiling…` (and `from benchmark…` / `from
  profiling…`) to `tools.measurement.benchmark…` / `tools.monitoring.profiling…` in: `do_tts.py`,
  `audio_utils.py`, `synthesis_modules.py`, the moved packages' own cross-imports
  (`tools/measurement/benchmark/p4_sweep.py`, `export_to_xlsx.py`, `tools/monitoring/profiling/join.py`),
  and all four `tests/test_*.py` files that import them (aliased as before —
  `as profiling`/`as p4`/`as export_to_xlsx`/`as runner` — so only the import line changed, not
  every call site).
- [x] Updated `tools/monitoring/profiling/__init__.py`'s subprocess launch string
  (`"-m", "profiling.sampler"` → `"-m", "tools.monitoring.profiling.sampler"`) — see the new §6
  finding on `_PACKAGE_ROOT` below, a second bug in the same function this string lives in.
- [x] Updated the self-referential `python -m profiling.…` usage strings inside the moved files'
  own docstrings/comments/error messages (`calibrate.py`, `join.py`, `sampler.py`,
  `export_to_xlsx.py`, `p4_sweep.py`) — left `README.md`/`docs/context/ARCHITECTURE.md`'s much
  larger Profiling/Benchmark sections alone, since a full rewrite there is Phase 4's batched
  doc-consistency pass, not a one-line fix like these.

**Found and fixed one more gap, same class as Phase 1's:** `tools/monitoring/profiling/__init__.py`
had `_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` — a hardcoded
"two levels up" that was correct only because `profiling/` used to sit exactly one level under the
repo root. Nesting it three levels deep broke the `subprocess.Popen(cwd=_PACKAGE_ROOT, ...)` call
that launches the background sampler (silently — it would point at `tools/monitoring/`, not the
repo root). Fixed: `_PACKAGE_ROOT = str(paths.ROOT)`. See the new §6 risk item — this is a *pattern*
to grep for before Phase 3, not just a one-off.

**Verify:** `pytest tests/` — 130 passed. Exercised every moved code path directly on Windows,
against the running `assets/models/` weights: plain synthesis, `--profile` (confirmed a real
`tools.monitoring.profiling` run directory with `meta.json`/`per_sentence.jsonl` was written),
`--benchmark --repeats 1` (all 11 sentences via `tools.measurement.benchmark.runner`), `--join`
(via `tools.monitoring.profiling.join`), and `--export-xlsx` (the trickiest cross-import:
`profiling.join` → `benchmark.export_to_xlsx`) — all succeeded. Test-generated `profile/run_*`
scratch directories were deleted afterward rather than left in the tree (exactly the kind of
generated-output-in-source-tree clutter §4 already flags). **Pi 5 hardware verification is owed,
not available this round** (see the note at the top of §7) — the sampler subprocess launch string
is the one change in this phase that Windows genuinely cannot exercise (the sampler no-ops
off-Linux before ever reaching that code), so it remains the highest-risk item to merge blind.

### Phase 3 — Introduce the Synthesizer abstraction, move orchestration code into chatterbox/

*Goals 2 & 3 (swappable model, swappable GUI).*

- Create `chatterbox/synthesis/base.py` + `registry.py` (§5).
- `git mv loading_modules.py synthesis_modules.py` into
  `chatterbox/synthesis/backends/fastspeech2_hifigan/`, refactor into the `Synthesizer` shape.
- `git mv config_tts.yaml chatterbox/config/config_tts.yaml`; update `do_tts.py`/`chatterbox/cli.py`'s
  `--config` default path.
- `git mv custom_regex_rules.csv symbols_regex_rules.csv url_regex_rules.csv` into
  `chatterbox/synthesis/backends/fastspeech2_hifigan/rules/`; update their `paths.py` entries
  (anchored in Phase 0) to the new location in the same commit.
- `git mv audio_utils.py gui_utils.py keyboards.py tts_utils.py audio_postprocess.py` into their
  target `chatterbox/` subpackages; split `audio_utils.syn_audio()`'s responsibilities per the
  mapping table (four targets: `playback.py`, `denoise.py`, `subtitles.py`, `cli.py` — see §2).
- Replace `do_tts.py`'s contents with `chatterbox/cli.py` plus a 3-line root shim.
- Fix the `gui_utils.py:355` config-reopening leak (§5) as part of this move, not after.
- `git rm do_normalize_txt.pl` (confirmed dead — see §4; no sign-off gate needed, unlike the other
  §4 flags).

**Verify:** free-text mode, `--gui`, and `--benchmark` all run unchanged on Windows; `python3
do_tts.py --help` output is byte-identical to before the reorg. **Pi 5 hardware verification is
owed, not available this round** (see the note at the top of §7) — this phase moves the regex-rule
CSVs and `config_tts.yaml` off their CWD-relative bare-filename opens, which is exactly the kind of
silent path break Windows dev testing alone can miss (§6).

### Phase 4 — Docs, assets, cleanup sign-off

*Goal 1 (30-second clarity) + closing the loop on §4.*

- `git mv La_Bise_Neutre_NEB_opti.wav La_bise_Neutre_NEB.wav La_bise_Neutre_NEB_phon.wav la_bise_NORMAL_AD.wav la_bise_NORMAL_AD_opti.wav assets/audio/reference/`
  (reclassified from delete-candidates to kept reference assets — see §2 "Audio assets").
- `git mv audio_keyboards/Emmanuelle assets/audio/prompts/Emmanuelle`; update the keyboard-prompt
  path resolution in `chatterbox/gui/keyboards.py` (via `paths.py`, per the Phase 0 invariant).
- `git mv tts_gui.png docs/assets/`, update the README image link.
- Create `hardware/.gitkeep` (or a stub `hardware/README.md`) — git doesn't track empty
  directories, so this ensures the placeholder survives the commit.
- Rewrite `CLAUDE.md`'s repo map, `docs/context/ARCHITECTURE.md`, `README.md`, `INSTALL.md` for the
  new paths.
- Bring the remaining §4 flagged items back to you individually for a delete/keep decision
  (`graphify-out/`, the `profile/` experiment directories, the two deprecated requirements files) —
  the demo WAVs are no longer on this list; they're relocated as kept reference assets above, not
  deleted.

**Verify:** a fresh clone + `scripts/setup_pi.sh` run on a real Pi 5, succeeding end-to-end from git
clone to a spoken sentence and matching the pre-reorg baseline timing, is the final confirmation
that every `paths.py` re-pointing across Phases 1–3 actually composed correctly — **this is the one
step in the whole plan that cannot be waived**, since it's the only check that ever exercises the
Pi-only code paths (Phases 1–2) at all. Until Pi access exists, treat Phases 1–3 as merged-but-unverified
on the actual target hardware, and prioritize getting Pi access before compounding further phases on
top. Also confirm, once on the Pi, that the on-screen keyboard (`--gui`) still finds its
phoneme-prompt WAVs at the new path.
