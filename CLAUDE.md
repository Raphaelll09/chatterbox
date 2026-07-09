# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

This repo is a fork of `embedded_tts`, the TTS engine for **Chatterbox**: an embedded neural TTS
demonstrator for AAC (augmentative and alternative communication) users, targeting a **Raspberry
Pi 5 (16 GB)**. It's a French text-to-speech pipeline: FlauBERT-large (optional free-text style
conditioning) + FastSpeech 2 (acoustic model, custom GST/StyleTag fork) + HiFi-GAN (vocoder),
running fully on CPU.

## Tech stack

Python 3 (tested on 3.8/3.10, repo has a 3.11 `.venv`), PyTorch, PyYAML config, Tkinter GUI
(optional). No GPU required or targeted — inference runs on CPU by design, for the Pi 5 target.

## Repo map

This file lives at the repo root, alongside the code below — run all commands below from here.

- `do_tts.py` — entry point; loads a TTS + vocoder pair from `config_tts.yaml` and runs the
  synthesis loop (CLI or `--gui`).
- `synthesis_modules.py` — per-utterance text parsing/normalization + calls into the acoustic model
  and vocoder.
- `loading_modules.py` — model loaders; stashes loaded models as module-level globals.
- `audio_utils.py` — top-level orchestration of one synthesis call (TTS → vocoder → denoise →
  post-process → playback).
- `audio_postprocess.py` — standalone loudness analysis + peak-normalize/soft-limit (no other repo
  dependencies; has its own pytest suite).
- `gui_utils.py`, `keyboards.py` — Tkinter GUI and on-screen phonetic keyboard.
- `tts_utils.py` — tiny globals for which TTS/vocoder index is currently selected.
- `config_tts.yaml` — the model registry + GUI + post-processing + profiling config; see
  `docs/context/ARCHITECTURE.md` for its structure.
- `profiling/` — optional profiling subsystem (background PMIC/CPU/thermal sampler, per-sentence
  timing recorder, offline join/calibration scripts); off by default. See
  `docs/context/ARCHITECTURE.md` "Profiling subsystem" and README "Profilage".
- `benchmark/` — fixed 10-sentence French benchmark set (`sentences_fr.jsonl`) + runner
  (`runner.py`) reusing `audio_utils.syn_audio()`; see `docs/context/ARCHITECTURE.md` "Benchmark
  mode" and README "Benchmark".
- `FastSpeech2/`, `hifi-gan-master/`, `Waveglow/`, `flaubert/` — vendored model repos (weights not
  in git — see Install below).
- `tests/` — pytest suite: `test_audio_postprocess.py`, `test_profiling.py`, `test_benchmark.py`.
- `requirements-dev.txt`, `requirements-pi.txt`, `apt-packages-pi.txt`, `scripts/setup_pi.sh` — PC
  vs Pi 5 dependency split + Pi provisioning script; see `INSTALL.md`.

## The synthesis pipeline (4 stages)

1. **FlauBERT front-end** (optional, per-utterance) — `synthesis_modules.preprocess_styleTag()`,
   only invoked when a `<STYLE_TAG=...>` free-text tag is present in the input text.
2. **FastSpeech2 acoustic** — `synthesis_modules.syn_fastspeech2()` → `FastSpeech2/synthesize.py`.
   Text → mel-spectrogram + `.AU` (visual/facial animation params).
3. **HiFi-GAN vocoder** — `synthesis_modules.syn_hifigan()` → `hifi-gan-master/inference_e2e.py`.
   Mel → waveform.
4. **Audio write** — `audio_utils.syn_audio()`: denoise, optional post-process
   (`audio_postprocess.py`), visual smoothing, subtitle write, playback.

Full detail (globals pattern, control-tag mini-language, config-driven model registry, weights
locations) is in `docs/context/ARCHITECTURE.md` — read it on demand, don't assume it's loaded here.

## Install gotchas

- Use **`requirements-dev.txt`** (PC) or **`requirements-pi.txt`** + **`apt-packages-pi.txt`**
  (Raspberry Pi 5) — see `INSTALL.md`. The legacy `requirements.txt` / `minimal_requirements.txt`
  are deprecated but kept for reference (deprecation note at the top of each): `requirements.txt`
  is the one that pulls FastSpeech2/Waveglow *training*-only dependencies (`apex`, `tensorflow`,
  `librosa` transitively, `tensor2tensor`, ...) and pins `apex==0.9.10dev`, which resolves to the
  wrong PyPI package — despite an earlier version of this doc saying the opposite,
  `minimal_requirements.txt` is actually the lean, working set (now `requirements-dev.txt`).
- Pretrained weights are **not in git** — download manually from the Google Drive links in
  `README.md`: FastSpeech2 checkpoint `390000`, FlauBERT large, HiFi-GAN
  `FR_V2/g_00570000`. `scripts/setup_pi.sh` automates this on a fresh Pi 5.
- Linux GUI needs `apt-get install python-tk` / `pip3 install python3-tk` in addition to the
  runtime requirements (already in `apt-packages-pi.txt` for the Pi).

## Run modes

- **Free-text (default)**: `python3 do_tts.py [--gui]` — prompts for text on stdin (or via GUI) and
  synthesizes/plays it. See `do_tts.py --help` for post-processing/analysis flags
  (`--postprocess`, `--target-crest-db`, `--analyze`, `--report-wav`) and the profiling flag
  (`--profile`, or `CHATTERBOX_PROFILE=1` — see below).
- **Benchmark**: `python3 do_tts.py --benchmark [--play] [--repeats N] [--join] [--sentences FILE]`
  — runs the fixed 10-sentence set in `benchmark/sentences_fr.jsonl` through the same
  `audio_utils.syn_audio()` call as free-text mode, with profiling forced on. See
  `docs/context/ARCHITECTURE.md` "Benchmark mode" and README "Benchmark".
- **Profiling** (optional, off by default): `python3 do_tts.py --profile` records per-sentence,
  per-stage timing/CPU/PMIC-power data under `profile/`. See `docs/context/ARCHITECTURE.md`
  "Profiling subsystem" and README "Profilage" for the output files and calibration procedure.

## Testing

```bash
.venv/Scripts/python.exe -m pytest tests/            # all tests
.venv/Scripts/python.exe -m pytest tests/test_audio_postprocess.py -k test_no_clipping  # single test
```

On this checkout, bare `python`/`python3` resolve to the Windows Store stub, not the project
venv — invoke via `.venv/Scripts/python.exe` (Windows) or activate the venv first. Tests need no
pretrained weights: `test_audio_postprocess.py` is pure numpy/scipy, `test_profiling.py`/
`test_benchmark.py` cover pure-parsing/call-ordering logic with synthesis monkeypatched.

## Conventions

- Keep dependencies minimal — this targets an embedded Pi 5, not a dev workstation.
- The synthesis function is shared, not duplicated — the benchmark mode (`benchmark/runner.py`)
  calls the same `audio_utils.syn_audio()` / `synthesis_modules.tts()` path as free-text mode, not a
  parallel copy. Any future batch mode must do the same.
- Profiling/instrumentation is opt-in and off by default (mirrors the `postprocess.enabled` pattern
  in `config_tts.yaml`) — see the `profiling/` package.

## Maintenance rules (IMPORTANT)

- At the start of a task, read `docs/context/ARCHITECTURE.md` and the top entry of
  `docs/context/CHANGELOG.md` for the current state and recent history.
- After completing any change, append a `docs/context/CHANGELOG.md` entry (template at the top of
  that file), and update `docs/context/ARCHITECTURE.md` / this file if the structure or run commands
  changed.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
