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
**Reorganized in Phase 3 of `docs/REORG_PROPOSAL.md` (2026-07-20)** — see that doc's §2 tree and §7
for the full rationale/history; `docs/context/ARCHITECTURE.md`'s module-level detail still
describes the pre-reorg layout and is flagged stale pending that doc's own Phase 4 rewrite.

- `do_tts.py` — entry point, now a 3-line shim calling `chatterbox.cli.main()` (CLI contract
  unchanged: same flags, same `--gui`).
- `chatterbox/` — the daily-use application package:
  - `cli.py` — argparse/dispatch (was `do_tts.py`'s body) + `syn_audio()`, now a thin CLI/benchmark
    wrapper around `synth.synthesize()` (below) + console reporting + playback; also `warmup()`
    (module-level, called by both the free-text loop and the GUI's own startup warm-up).
  - `synth.py` — **Tk-free** synthesis compute path (chatterbox_gui_spec_v0.1.md §2.3), extracted
    from `cli.py:syn_audio()` in the GUI refactor: `synthesize(text, tts_idx, voc_idx, tts_config,
    ...) -> AudioResult | None` (TTS → vocoder → denoise/post-process → subtitles →
    `audio/playback.py`'s `AUDIO_EXAMPLE` set). The vocoder call is skipped for a monolithic TTS
    model (`tts_models[i].needs_vocoder: false`) — see "Interchangeable backends" below;
    `AudioResult.stage_durations` is a generic `{stage_key: seconds}` dict (`"vocoder"` simply
    absent in that case), not fixed named fields. No Tk import, no playback call — both `cli.py`
    and the GUI's worker thread call it directly. See `docs/gui/GUI.md`.
  - `synthesis/base.py` — `Synthesizer`/`VocoderBackend` ABCs, `SynthesisRequest`/`SynthesisResult`
    dataclasses (the latter's `wav_path` vs `mel_path` is how a monolithic backend signals "already
    a finished wav, no vocoding needed" — see "Interchangeable backends" below); `registry.py` —
    `BACKEND`, config-driven dispatch (`config_tts.yaml`'s `load_script`/`syn_script`/`gui_script`
    strings, resolved via `getattr(registry.BACKEND, name)`, same as before the Piper integration).
    `BACKEND` is now a small resolving proxy (`_BackendProxy`), not a bare singleton instance —
    added when a second backend (Piper) proved the original bare-singleton design couldn't
    disambiguate `tts()`/`describe_controls()` (identically named on every backend by design) once
    more than one was registered; `activate_tts_backend(name)`, called by `cli.py`/`gui/app.py`
    immediately before resolving a `tts_models[i]` entry's `load_script` (per that entry's new
    `backend` field, e.g. `"piper"` — omitted defaults to `"fastspeech2_hifigan"`), tells the proxy
    which concrete backend colliding names should resolve against. See
    `docs/gui/INTERCHANGEABLE_BACKENDS.md` §3 for the full contract-gap writeup.
  - `synthesis/backends/fastspeech2_hifigan/` — `backend.py` (was `loading_modules.py` +
    `synthesis_modules.py`'s model-calling functions, now a `FastSpeech2HifiGanBackend` class owning
    loaded-model state as instance attributes) + `text_pipeline.py` (was `synthesis_modules.py`'s
    text-processing functions: control-tag parsing, pronunciation/punctuation cleanup) +
    `rules/*.csv` (the regex rule files — heavily FS2-`{phonetic}`-syntax-specific despite the
    substitution mechanism itself being generic regex replace; see `synthesis/backends/piper/`'s
    own note on why it doesn't reuse `parse_pronunciation_mistakes()` unconditionally).
  - `synthesis/backends/piper/` — the second backend (`backend.py`'s `PiperBackend`: `load_piper`,
    `tts`, `describe_controls`; `text_frontend.py`'s own tag-parsing/speaker-resolution, deliberately
    not routed through `fastspeech2_hifigan/text_pipeline.py`'s FS2-specific machinery beyond the
    genuinely orthographic `trim_punctuation_mistakes()`). Monolithic (`needs_vocoder: false`), no
    style dimension, `piper-tts` (optional, GPL-3.0-or-later — install manually, not in
    `requirements-pi.txt`) does its own espeak-ng-based phonemization internally. 3 voices
    (`fr_FR-siwis-medium`/`upmc-medium`/`tom-medium`, fetched by `scripts/fetch_piper_voices.sh`
    into `assets/models/Piper/`, not committed). See its own `README.md` for provenance/licence and
    `docs/gui/INTERCHANGEABLE_BACKENDS.md` §3 for what this integration found and fixed in the
    contract itself (`registry.py`'s proxy above, plus a stale-Tk-variable bug in
    `gui_generic_controls()` — see that section, not repeated here).
  - `synthesis/audio_postprocess.py` — unchanged from pre-reorg `audio_postprocess.py`.
  - `synthesis/subtitles.py` — subtitle/duration-alignment file writers (was part of
    `audio_utils.py`).
  - `audio/playback.py`, `audio/denoise.py` — playback and noise-reduction (was part of
    `audio_utils.py`).
  - `gui/app.py`, `gui/keyboards.py` — Tkinter GUI, on-screen phonetic (Emmanuelle) keyboard, and
    (added in the responsive/accessible refactor, `cc_prompt_gui_refactor.md`) a second soft
    letter keyboard (`app.py:_create_letter_keyboard()`, simplified AZERTY) toggled via a
    Texte/Phonèmes segmented control — both live in one `keyboard_area` container that portrait/
    landscape reflow (`app.py`'s `<Configure>` binding) repositions as a unit. Main-window layout
    is responsive (grid weights, not fixed pixel sizes); the model-options panel
    (`gui_generic_controls()`, see "Interchangeable backends" below) is built entirely from the
    active backend's `describe_controls()` — a wrapped style/GST-token chip grid with unnamed
    placeholder tokens hidden behind an "Styles avancés" toggle is what today's FastSpeech2 backend
    happens to declare, not something `app.py` hardcodes; TTS/vocoder model selection lives in
    Settings → Advanced (see `gui/settings.py` below), not the main window. Synthesis+playback (and,
    since the same refactor, Replay) run on a worker thread, never the Tk thread
    (chatterbox_gui_spec_v0.1.md §2) — see `docs/gui/GUI.md`.
  - `gui/i18n.py` — the GUI's string table (added in the same refactor to replace a hardcoded
    French/English label mix); French-only today, `t(key, **kwargs)` is the lookup. The app-bar's
    Thème/Langue menu entries are intentionally disabled stubs until a second locale/theme table
    exists.
  - `gui/input.py` — the `Action` enum + `dispatch()` + a minimal nav ring driving/driven-by
    physical switches (via powerd) and the Speak/Replay/keyboard/Put-away/Settings controls.
  - `gui/settings.py` — the settings screen (`chatterbox/config/user_prefs.yaml`'s power-timer/
    brightness fields; atomic write; `powerd.reload()` on save), plus an "Avancé" section
    (dependency-injected via `open_settings(..., build_advanced_section=...)`, mirroring
    `gui/input.py`'s no-import-cycle pattern) that `gui/app.py` uses to host the TTS/vocoder model
    pickers — model switches there take effect immediately, unlike the power fields, which need
    "Enregistrer".
  - `state.py` — tiny globals for which TTS/vocoder index is selected (was `tts_utils.py`).
  - `config/config_tts.yaml` — the model registry + GUI + post-processing + profiling config (see
    `docs/context/ARCHITECTURE.md`, stale on paths but not on structure). Each `tts_models[i]` entry
    carries three static capability flags read *before* that model is loaded (see "Interchangeable
    backends" below): `needs_vocoder` (hides the Settings → Advanced Vocodeur picker when false),
    `accepts_phoneme_input` (drives the top-level `GUI_config.phoneme_fallback`:
    `"translate_labels"` or `"hide"`, for when a model doesn't understand the Phonèmes keyboard's
    phone-code syntax), and `supports_subtitles` (added for the Piper backend — `false` skips
    `chatterbox/synth.py`'s subtitle-writing path, which otherwise assumes FastSpeech2's own
    per-symbol `audio_file_duration.npy` output exists; see
    `docs/gui/INTERCHANGEABLE_BACKENDS.md` §3.4). `config/paths.py` — repo-root-anchored path resolution for the vendored
    model dirs (added Phase 0); `config/user_prefs.yaml` — chatterbox-powerd's runtime prefs
    (below), reloadable on SIGHUP.
  - `power/` — **optional**, Pi/Linux-only: `chatterbox-powerd`, the kiosk power-state daemon
    (ACTIVE→DIM→DARK→DEEP, backlight, amplifier SD line, physical switches/touch activity, halt-on-
    DEEP). Run with `python3 -m chatterbox.power.daemon`; every hardware import (`gpiozero`,
    `evdev`) is guarded so this package (and everything importing it) still loads cleanly without
    them. `chatterbox/audio/playback.py` and `chatterbox/gui/app.py` talk to it through the shared
    `chatterbox.power.client.get_client()` singleton, which degrades to a silent no-op whenever
    powerd isn't reachable — see `docs/power/POWERD.md` and `chatterbox-powerd_spec_v0.1.md`.
    `power/battery.py` — independent of powerd/the daemon — reads battery %/voltage from a
    DFRobot FIT0992 UPS HAT over I2C (`smbus2`, guarded/lazy same as the rest of this package);
    `gui/app.py` polls it directly (no daemon involved) to show a battery-percentage label.
- `deploy/systemd/` — `chatterbox-powerd.service` / `chatterbox-gui.service` units, installed by
  `scripts/setup_pi.sh` (see `INSTALL.md` "chatterbox-powerd"). `chatterbox-gui.service` runs the
  GUI under `cage` (finalized kiosk compositor choice — see `docs/kiosk/KIOSK.md`).
- `tools/` — research/maintenance tooling, not daily-use (Goal 4 of the reorg):
  - `measurement/benchmark/` — fixed 10-sentence French benchmark set + runner (was `benchmark/`).
  - `measurement/pmic_calibrate.py` — guided PMIC→meter calibration wizard.
  - `monitoring/profiling/` — background PMIC/CPU/thermal sampler, per-sentence timing recorder,
    offline join/calibration scripts; off by default (was `profiling/`).
- `assets/models/` — vendored model repos (`FastSpeech2/`, `hifi-gan-master/`, `Waveglow/`,
  `flaubert/`; weights not in git — see Install below).
- `tests/` — pytest suite: `test_audio_postprocess.py`, `test_profiling.py`, `test_benchmark.py`,
  `test_p4_sweep.py`, `test_export_xlsx.py`, `test_power_{fsm,config,backlight,amp,ipc}.py`,
  `test_synth.py`, `test_gui_{input,worker,settings}.py`, `test_backend_describe_controls.py`.
- `requirements-dev.txt`, `requirements-pi.txt`, `apt-packages-pi.txt`, `scripts/setup_pi.sh` — PC
  vs Pi 5 dependency split + Pi provisioning script; see `INSTALL.md`.
- `scripts/kiosk_finalize.sh` — **opt-in**, run once a Pi has passed
  `Bring-up_Integration_Test_Protocol_v0.1.md`'s T0-T7: disables `getty@tty1` (which would race
  `chatterbox-gui.service` for the tty), tunes `config.txt`/`cmdline.txt` (backed up, idempotent),
  enables+starts both systemd units. Never touches EEPROM beyond a read-only check. Not part of
  `setup_pi.sh`'s default run. See `docs/kiosk/KIOSK.md`.

## The synthesis pipeline (4 stages)

1. **FlauBERT front-end** (optional, per-utterance) — `text_pipeline.preprocess_styleTag()`, only
   invoked when a `<STYLE_TAG=...>` free-text tag is present in the input text.
2. **FastSpeech2 acoustic** — `FastSpeech2HifiGanBackend.syn_fastspeech2()` →
   `assets/models/FastSpeech2/synthesize.py`. Text → mel-spectrogram + `.AU` (visual/facial
   animation params).
3. **HiFi-GAN vocoder** — `FastSpeech2HifiGanBackend.syn_hifigan()` →
   `assets/models/hifi-gan-master/inference_e2e.py`. Mel → waveform.
4. **Audio write** — `chatterbox.synth.synthesize()`: denoise, optional post-process
   (`chatterbox/synthesis/audio_postprocess.py`), visual smoothing, subtitle write. Playback
   (`chatterbox/audio/playback.py:play_audio()`) is a separate step the caller (`cli.syn_audio()`
   or the GUI's worker thread) triggers afterward.

Full detail (globals-turned-instance-state pattern, control-tag mini-language, config-driven model
registry, weights locations) is in `docs/context/ARCHITECTURE.md` — read it on demand, but note its
module names/paths predate the Phase 3 reorg above; cross-check against this file or
`docs/REORG_PROPOSAL.md` §2 if something doesn't match.

## Interchangeable backends

The GUI/synthesis-result layer is generic, not hardcoded to FastSpeech2 — a backend swap (e.g. a
monolithic state-of-the-art model with no separate vocoder stage) needs **no** changes to
`chatterbox/gui/app.py` or `chatterbox/synth.py`, only its own backend module + `config_tts.yaml`
entry conforming to this contract. **No longer just a design goal**: the Piper (fr_FR) backend
(`chatterbox/synthesis/backends/piper/`) proved this against a real second backend, and found that
`chatterbox/synthesis/registry.py` itself needed a small fix first (a bare-singleton `BACKEND`
couldn't resolve which backend's `tts()`/`describe_controls()` a caller meant once a second one
existed) plus a stale-Tk-variable bug in `gui/app.py`'s `gui_generic_controls()` — both fixed, both
documented in full in `docs/gui/INTERCHANGEABLE_BACKENDS.md` §3, neither required touching
`synth.py`. The contract described below is what actually held up under that test:

- **Model-options panel**: `Synthesizer.describe_controls()` (`chatterbox/synthesis/base.py`,
  docstring has the full return shape) returns `speaker_list`/`default_speaker` plus an ordered
  `controls` list of `chip_grid`/`slider`/`text` descriptors — `gui/app.py:gui_generic_controls()`
  renders one widget per entry generically (no per-backend GUI code) and collects values into a
  dict `get_gui_controls()` returns, keyed by each control's declared `"key"`. FastSpeech2's own
  `describe_controls()` (`synthesis/backends/fastspeech2_hifigan/backend.py`) is what actually
  declares today's style chip grid / 9 sliders / StyleTag entry, reading the same
  `config_tts.yaml` keys (`gst_token_list`, `default_args.*`, `gui_control_bias`, etc.) it always
  has, just translated into the generic schema instead of hand-built widgets.
- **Two-stage vs. monolithic pipeline**: `SynthesisResult.wav_path` (set) vs. `mel_path` (set) is
  how a backend signals "already a finished wav" vs. "still needs vocoding"; the static per-model
  `needs_vocoder` flag (`config_tts.yaml`) tells `chatterbox.synth.synthesize()` whether to call
  `BACKEND.vocoder()` at all, and tells `gui/app.py`'s Settings → Advanced whether to show a
  Vocodeur picker. Denoising/postprocess/subtitles stay universal regardless of pipeline shape.
  `AudioResult.stage_durations` is a generic `{stage_key: seconds}` dict (GUI/CLI reporting iterate
  it, no fixed named fields) — `"vocoder"` is simply absent for a monolithic backend.
- **Phoneme keyboard**: the on-screen "Emmanuelle" Phonèmes keyboard (`gui/keyboards.py`) is
  FastSpeech2's own custom phone-symbol alphabet (there's no G2P step anywhere in this repo) — a
  different backend declares `accepts_phoneme_input: false` (`config_tts.yaml`, per `tts_models`
  entry) if it can't understand that syntax, and `GUI_config.phoneme_fallback`
  (`"translate_labels"`, the default, or `"hide"`) decides what the GUI does about it: substitute
  each key's already-computed plain-French display label, or remove the Phonèmes keyboard/toggle
  entirely. `keyboards.py`'s own mood-shortcut keys and phone-symbol table remain FS2/GST-specific
  by design — a backend wanting phoneme input support of its own would need its own keyboard
  layout, not a reuse of this one.

## Install gotchas

- Use **`requirements-dev.txt`** (PC) or **`requirements-pi.txt`** + **`apt-packages-pi.txt`**
  (Raspberry Pi 5) — see `INSTALL.md`. The legacy `requirements.txt` / `minimal_requirements.txt`
  (deleted 2026-07-20, reorg Phase 4 sign-off — see `docs/context/CHANGELOG.md`) pulled in
  FastSpeech2/Waveglow *training*-only dependencies (`apex`, `tensorflow`, `librosa` transitively,
  `tensor2tensor`, ...) and pinned `apex==0.9.10dev`, which resolves to the wrong PyPI package —
  not needed to run inference against an already-trained checkpoint. If you ever need to retrain
  or re-preprocess FastSpeech2, recover their pins from git history rather than reconstructing them
  by hand.
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
  — runs the fixed 10-sentence set in `tools/measurement/benchmark/sentences_fr.jsonl` through the
  same `chatterbox.cli.syn_audio()` call as free-text mode, with profiling forced on. See
  `docs/context/ARCHITECTURE.md` "Benchmark mode" and README "Benchmark".
- **Profiling** (optional, off by default): `python3 do_tts.py --profile` records per-sentence,
  per-stage timing/CPU/PMIC-power data under `profile/`. See `docs/context/ARCHITECTURE.md`
  "Profiling subsystem" and README "Profilage" for the output files and calibration procedure.
- **Power daemon** (optional, separate process, Pi/Linux-only): `python3 -m chatterbox.power.daemon`
  (or the `chatterbox-powerd` systemd unit) runs the kiosk power-state machine alongside `do_tts.py
  --gui`. See `docs/power/POWERD.md`.
- **GUI** (`--gui`, above): non-blocking (worker-thread synthesis+playback), crash-resistant, and
  a `chatterbox-powerd` client (activity pings, put-away, forwarded switch input, a settings
  screen). See `docs/gui/GUI.md`.

## Testing

```bash
.venv/Scripts/python.exe -m pytest tests/            # all tests
.venv/Scripts/python.exe -m pytest tests/test_audio_postprocess.py -k test_no_clipping  # single test
```

On this checkout, bare `python`/`python3` resolve to the Windows Store stub, not the project
venv — invoke via `.venv/Scripts/python.exe` (Windows) or activate the venv first. Tests need no
pretrained weights: `test_audio_postprocess.py` is pure numpy/scipy, `test_profiling.py`/
`test_benchmark.py` cover pure-parsing/call-ordering logic with synthesis monkeypatched.
`test_power_*.py` similarly need no Pi hardware (fake-injected FSM/backlight/amp) — the one
exception, a live unix-socket loopback test in `test_power_ipc.py`, is `skipif`'d on Windows.
`test_gui_*.py`/`test_synth.py` need no Tk instance or pretrained weights either (fake-injected
widgets/monkeypatched `synth.synthesize`/`playback.play_audio`) — see `docs/gui/GUI.md` for the
separate manual real-weights smoke tests that *do* need loaded models (not part of this suite).

## Conventions

- Keep dependencies minimal — this targets an embedded Pi 5, not a dev workstation.
- The synthesis function is shared, not duplicated — the benchmark mode
  (`tools/measurement/benchmark/runner.py`) calls the same `chatterbox.cli.syn_audio()` /
  `FastSpeech2HifiGanBackend.tts()` path as free-text mode, not a parallel copy. Any future batch
  mode must do the same. Underneath, `cli.syn_audio()` and the GUI's worker thread both call the
  same Tk-free `chatterbox.synth.synthesize()` — don't reintroduce a second compute path for one
  or the other.
- Profiling/instrumentation is opt-in and off by default (mirrors the `postprocess.enabled` pattern
  in `config_tts.yaml`) — see the `tools/monitoring/profiling/` package.

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
