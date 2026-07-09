# Changelog

Reverse-chronological log of modification sessions. One entry per session, using the template below.
Read on demand (not loaded into every session's context) — check the top entry for the most recent
state before starting new work.

```
## YYYY-MM-DD — <short title>
- What: <what changed, 1-3 bullets>
- Files: <files added / modified>
- Why: <purpose / linked experiment>
- Verify: <how to check it works>
- Notes/gotchas: <anything future-me needs>
```

---

## 2026-07-09 — Split PC/Pi5 dependencies + Pi5 provisioning script

- What: Restructured dependency management into a PC/Pi5 split and added a repeatable Pi5
  provisioning script.
  1. `requirements-dev.txt` (PC exploration env) and `requirements-pi.txt` +
     `apt-packages-pi.txt` (Raspberry Pi 5 CPU-only inference env), replacing the ambiguous
     `requirements.txt` / `minimal_requirements.txt` pair (both kept, deprecated with a pointer
     comment at the top of each — not deleted).
  2. `scripts/setup_pi.sh`: idempotent, guards on Linux/aarch64, installs apt + pip deps, creates
     `~/chatterbox/venv`, downloads the FastSpeech2/FlauBERT/HiFi-GAN weights (README's Drive
     links) into the exact paths `docs/context/ARCHITECTURE.md` documents, runs a torch-CPU smoke
     test (fatal) and a best-effort one-sentence end-to-end synthesis smoke test (non-fatal), then
     writes `requirements-pi-lock.txt` via `pip freeze`.
  3. `INSTALL.md`: PC vs Pi5 split, fresh-Pi5 setup steps, golden-image mass-deployment note,
     `pip-tools`/`pip-compile` flagged as a future option (not implemented).
- Files: `requirements-dev.txt`, `requirements-pi.txt`, `apt-packages-pi.txt`,
  `scripts/setup_pi.sh`, `INSTALL.md` (all added); `requirements.txt`, `minimal_requirements.txt`
  (deprecation header only, contents otherwise unchanged); `CLAUDE.md` (repo map entry + corrected
  "Install gotchas"); `docs/context/ARCHITECTURE.md` (weights section now points at the script).
- Why: PC and Pi5 need different dependency sets (`apex` mis-resolves on PyPI and is CUDA/Waveglow
  training-only; several other pins are FastSpeech2 training-only), and there was no repeatable way
  to provision a new Pi5 unit.
- Verify: `bash -n scripts/setup_pi.sh` (syntax only — not run against real Pi5 hardware, per
  constraints: this session only authors files, it doesn't SSH into or execute anything on a
  physical Pi). Content of all three requirements files traced against actual imports (see
  Notes/gotchas) rather than guessed.
- Notes/gotchas:
  - **Found and fixed a stale doc bug**: `CLAUDE.md`'s old "Install gotchas" said `requirements.txt`
    was the lean runtime set and `minimal_requirements.txt` pulled training-only deps — reading
    both files directly showed the opposite (`requirements.txt` has `apex`/`tensorflow`/
    `tensor2tensor`/etc.; `minimal_requirements.txt` is the lean, working set). Corrected in
    `CLAUDE.md`; `requirements-dev.txt` is built from `minimal_requirements.txt`'s contents.
  - `apex` is only imported by `Waveglow/train.py`, `Waveglow/tacotron2/train.py`, and
    `Waveglow/inference.py` — Waveglow's vocoder entry is commented out in `config_tts.yaml` and
    not part of the active FastSpeech2+HiFi-GAN pipeline, so `requirements-pi.txt` excludes `apex`
    entirely (flagged in a comment, not silently dropped) and `setup_pi.sh` skips downloading
    Waveglow weights by default.
  - `simpleaudio`/`sounddevice` are imported only under `if platform.system() == "Windows":` in
    `audio_utils.py`/`gui_utils.py` — dead code on Linux, so excluded from `requirements-pi.txt`;
    Pi playback goes through `pydub.playback.play()` → `ffplay` (hence `ffmpeg` in
    `apt-packages-pi.txt`).
  - `librosa` is not pinned directly anywhere but is a hard transitive dependency of `noisereduce`
    (confirmed via `noisereduce`'s own `Requires-Dist`) — it still gets installed.
  - `espeak-ng` was considered for `apt-packages-pi.txt` (the original task prompt suggested it
    "if the phonemizer needs it") but this pipeline has no phonemizer — French text uses this
    repo's own regex-based normalization and user-typed literal `{s y z i}` phonetic input, not
    auto G2P — so it was left out, with the reasoning documented inline in the file.
  - On this dev checkout, the already-downloaded weight archives show a one-level self-duplicated
    directory artifact (e.g. `hifi-gan-master/FR_V2/FR_V2/...`,
    `FastSpeech2/preprocessed_data/preprocessed_data/...`), consistent with the source zips having
    a top-level folder matching the extraction target name. `setup_pi.sh`'s `fetch_and_unzip`
    flattens that case automatically; not verified against a fresh real download since this
    session had no network access to the Drive links.
  - Placed the new files inside `embedded_tts/` (next to the existing `requirements.txt`/
    `README.md`), not at the outer repo root, per this repo's own working-root/repo-root
    distinction (see `CLAUDE.md` repo map) — the task prompt said "repo root" but the existing
    requirements files already live one level down.

## 2026-07-09 — Verify profiling + benchmark end-to-end; fix two bugs found doing so

- What: Ran both features for real (weights are present in this checkout: FastSpeech2 `390000`,
  HiFi-GAN `FR_V2/g_00570000`, FlauBERT), not just unit tests. `--profile` on a single sentence
  produced a correct `per_sentence.jsonl` record (durations, RTF, audio metrics all sane). Found
  and fixed two bugs in the process:
  1. `audio_utils.syn_audio()` called `gui_utils.update_circle_color("gray", ...)` unconditionally
     (not gated by `if use_gui:`, unlike the "yellow"/"green" calls) — this crashed with
     `AttributeError: 'NoneType' object has no attribute 'itemconfig'` at the end of *every*
     non-GUI synthesis call. Pre-existing bug (confirmed present in `HEAD` before this session's
     changes), but it directly blocked `--benchmark` from getting past sentence 1 of 11, so fixed
     it here rather than filing it separately: wrapped that call in `if use_gui:` too, matching the
     existing pattern.
  2. `profiling/join.py`'s `load_samples()` assumed `profile/per_sample.csv` always exists, but the
     background sampler is optional and Linux-only — running `--join` on a machine without it (or
     if the sampler didn't start) crashed with `FileNotFoundError` instead of degrading to
     timing-only results. Fixed: returns `[]` with a printed note when the file is missing;
     downstream aggregation already handles empty sample windows (all energy/CPU/temp fields come
     out `None`, timing/RTF fields unaffected).
  After both fixes, `do_tts.py --benchmark --repeats 1 --join` ran the full REF→A1..C2→REF
  sequence and produced correct `per_sentence_results.csv`/`per_stage_results.csv` (11 sentence
  rows, 44 stage rows; `sentence_id`/`complexity_tag` correctly labelled per entry; `energy_j`
  empty since no PMIC sampler ran on this Windows dev box, as expected).
- Files: `audio_utils.py` (one-line `if use_gui:` guard), `profiling/join.py`
  (`load_samples()` missing-file guard), `tests/test_profiling.py` (2 new regression tests for the
  `join.py` fix).
- Why: User asked to verify both prompts' features actually work as specified, not just that they
  compile/pass mocked unit tests.
- Verify: `python -m pytest tests/` (45 passed). Manually: `printf "Bonjour, ceci est un
  test.\n" | python do_tts.py --profile` (single-sentence, real synthesis + profiling record);
  `python do_tts.py --benchmark --repeats 1 --join` (full 11-call sequence + join, real synthesis).
- Notes/gotchas:
  - This session generated `profile/per_sentence.jsonl` and result CSVs as verification artifacts;
    deleted them afterwards (`profile/.gitkeep` is the only tracked file there) so a fresh clone
    doesn't ship stale sample data.
  - The circle-color bug means anyone running plain free-text CLI mode today (`do_tts.py` with no
    `--gui`) already crashes after the *first* sentence synthesized in the process (looping back to
    `input()` never happens) — this was true before this session's changes too, it just went
    unnoticed until a multi-sentence non-GUI loop (the benchmark) exercised it.

## 2026-07-08 — Add benchmark mode (fixed 10-sentence routine)

- What: Added `do_tts.py --benchmark`, running a fixed 10-sentence French set through the exact
  same synthesis call as free-text mode (`audio_utils.syn_audio()`), with profiling forced on, so
  power/RTF are comparable across sentences of varying length/complexity and across runs.
- Files: new `benchmark/` package (`__init__.py`, `sentences_fr.jsonl` — the 10 sentences,
  `runner.py` — `load_sentences()`/`run_benchmark()`); new `tests/test_benchmark.py`; edited
  `do_tts.py` (`--benchmark`/`--sentences`/`--play`/`--repeats`/`--join` flags, `load_models()`
  factored out of the free-text branch and reused by the benchmark branch, `--join` calls
  `profiling.join.run_join()` after `profiling.stop_session()`); edited `audio_utils.py`
  (`syn_audio()` gained optional `sentence_id`/`complexity_tag`/`play` params, all
  default-preserving); edited `profiling/__init__.py` (`begin_sentence()` accepts an explicit
  `sentence_id` override instead of always auto-incrementing); refactored `profiling/join.py`
  (`main()` split into a plain `run_join(profile_dir)` callable + a thin argparse `main()`, so
  `do_tts.py` can call it without an `sys.argv` collision); README "Benchmark" section;
  `docs/context/ARCHITECTURE.md` "Benchmark mode".
- Why: Need a repeatable, labelled sentence set (varying length/liaisons/numbers/prosody/proper
  nouns/homographs, one REF anchor at each end for drift) to compare compute/energy cost across
  sentence types without hand-typing free text each time, while keeping exactly one synthesis path.
- Verify: `python -m pytest tests/test_benchmark.py` (order REF→A1..C2→REF, `--repeats` behavior,
  `play` propagation, empty-file error — `audio_utils.syn_audio` monkeypatched, no real models
  needed). Full suite (`python -m pytest tests/`) green (43 passed). `python -m py_compile` on all
  touched files.
- Notes/gotchas:
  - `--benchmark` forces `profiling.enabled = True` in the same CLI/env merge block `--profile`
    already uses in `do_tts.py` — no separate start/stop logic was needed in `benchmark/runner.py`
    itself, it just calls `audio_utils.syn_audio()` in a loop.
  - `profiling/join.py`'s old `main()` parsed `sys.argv` directly; calling it from `do_tts.py` would
    have collided with `do_tts.py`'s own args. Split into `run_join(profile_dir)` (no argv access)
    plus a thin `main()` CLI wrapper around it.
  - The prompt's sentence text had mis-encoded accents (UTF-8 bytes read as Latin-1, e.g. `Ã©`
    for `é`); reconstructed each sentence from context and verified by round-tripping through
    `json.load` and checking Unicode codepoints (0xe9=é, 0xe7=ç, 0xe0=à, 0xe8=è, 0xfb=û,
    0x2026=…) rather than trusting a terminal echo (Git Bash's codepage renders them as `�`
    even when the file bytes are correct UTF-8).
  - `sentence_id` in `per_sentence.jsonl` is a free-text-mode auto-incrementing int by default but
    now an explicit string (`"REF"`, `"A1"`, ...) when the benchmark passes one — `profiling/join.py`
    treats it as an opaque label either way, so no changes were needed there.

## 2026-07-08 — Add optional profiling subsystem

- What: Added an opt-in profiling subsystem to measure per-sentence, per-stage CPU/energy/timing
  cost of synthesis on the Pi 5 target, using the PMIC (`vcgencmd pmic_read_adc`) as the only
  available continuous power source (no external current sensor on the 5V rail). Off by default,
  zero overhead when disabled.
- Files: new `profiling/` package (`__init__.py` public API/session control, `recorder.py`
  per-sentence `Recorder`/`NullRecorder`, `sampler.py` background 10 Hz CPU/PMIC/thermal subprocess,
  `parsing.py` pure text parsing for `/proc/stat`/PMIC/throttled output, `join.py` offline
  energy/CPU aggregation, `calibrate.py` PMIC→external-meter calibration helper); new
  `tests/test_profiling.py`; new `profile/` output dir (gitignored contents, `.gitkeep` tracked);
  edited `do_tts.py` (`--profile` flag, session start/stop), `audio_utils.py` (recorder creation +
  `vocoder`/`write` stage marks + audio metrics capture), `synthesis_modules.py` (`front_end`/
  `acoustic` stage marks + phoneme count, inside `syn_fastspeech2()`); added `profiling:` section to
  `config_tts.yaml`; added README "Profilage" section; `.gitignore` updated.
- Why: Need per-sentence, per-pipeline-stage power/timing data to analyse compute and energy cost
  on the Pi 5, without perturbing the synthesis it measures (profiler runs on the same machine).
- Verify: `python -m pytest tests/test_profiling.py` (19 tests, pure-Python parsing/recorder/join
  logic only — `sampler.py`'s actual sysfs/vcgencmd reads need a real Pi to exercise). Full suite
  (`python -m pytest tests/`) still green (38 passed). `python -m py_compile` on all touched files.
- Notes/gotchas:
  - The FlauBERT front-end has no separate boundary in `audio_utils.py` — it's nested inside
    `synthesis_modules.syn_fastspeech2()` (the `preprocess_styleTag()` call), so `front_end`/
    `acoustic` marks had to go there, reached via `profiling.current()` (a contextvar) rather than
    threading a parameter through `tts()` → `syn_fastspeech2()`.
  - The "§" sub-utterance loop in `syn_audio()` calls `synthesis_modules.tts()` once per
    sub-utterance, so `Recorder.stage()` *accumulates* durations across repeated calls (see
    `durations` dict) instead of overwriting — a single per-sentence record still comes out
    correct whether or not the input contains "§".
  - `t_audio_write_end` is marked *before* `play_audio()` deliberately — including playback would
    inflate `total_synth_ms`/RTF with real-time audio duration, which isn't compute cost.
  - Background sampler is gated to Linux only (checks `platform.system()`); this dev checkout is
    Windows, so the sampler subprocess itself is untested end-to-end here — only its parsing logic
    (`profiling/parsing.py`) and the per-sentence recorder path are exercised by the test suite.
  - Unrelated discovery while reading `requirements.txt`/`minimal_requirements.txt`: their actual
    contents are the *opposite* of both this doc's and the previous changelog entry's claim —
    `requirements.txt` currently contains the heavy training deps (`apex`, `tensorflow`,
    `tensor2tensor`, `librosa`), and `minimal_requirements.txt` has the lean runtime set. Flagged to
    the user; not fixed in this session since it's unrelated to profiling — worth a follow-up pass
    on `CLAUDE.md`'s "Install gotchas" section.

## 2026-07-08 — Add persistent project-context docs

- What: Ran `/init` to generate a baseline `CLAUDE.md`, then split it into a lean root `CLAUDE.md` +
  detailed `docs/context/ARCHITECTURE.md` + this changelog, per the three-file context design (short
  file loaded every session vs. on-demand detail).
- Files: `CLAUDE.md` (rewritten), `docs/context/ARCHITECTURE.md` (new), `docs/context/CHANGELOG.md`
  (new, this file).
- Why: Keep every-session context budget small while letting modification history and deep
  architecture notes grow indefinitely without re-exploring the codebase each session.
- Verify: n/a (docs only, no code changed).
- Notes/gotchas: A draft prompt for this task described a benchmark mode (`--benchmark`), a 10 Hz
  profiling subsystem, and an inverted claim about `requirements.txt` vs. `minimal_requirements.txt`
  (that `apex` lives in `requirements.txt` — it actually lives in `minimal_requirements.txt`, which
  also pulls `tensorflow`/`librosa`/`tensor2tensor`, i.e. full training deps not needed for the demo
  pipeline). None of that benchmark/profiling code exists in this checkout — confirmed by grepping
  the whole tree for `benchmark|profile|profiling` outside `.venv`. Left out of these docs
  deliberately; add it here (and to `CLAUDE.md`'s run-modes section) once it's actually implemented.
