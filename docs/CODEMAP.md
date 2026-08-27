# Code map

**A navigational map for people (and AI assistants) working on Chatterbox.** It answers "where do I
go and what am I editing", not "how does the system work" — that is
[ARCHITECTURE.md](ARCHITECTURE.md).

One fact lives in one place. This file links rather than restates.

| If you want | Read |
|---|---|
| To install or run it | [`README.md`](../README.md) |
| How a subsystem works internally | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| To add or change a synthesis backend | [`chatterbox/synthesis/README.md`](../chatterbox/synthesis/README.md) |
| GUI threading and testing detail | [`GUI.md`](GUI.md) |
| Why something is the way it is | [`research/CHANGELOG.md`](research/CHANGELOG.md) |
| **Where the code for X lives** | **this file** |

Reading order for a newcomer: this file → `ARCHITECTURE.md` → the one subsystem README you need.
Do not read `CHANGELOG.md` front to back; grep it.

---

## 1. Orientation in 60 seconds

French (and English) text-to-speech for AAC users, running on CPU on a Raspberry Pi 5. Type, and
the device speaks. Two interchangeable synthesis backends. An optional daemon makes it behave like
an appliance rather than a computer.

**Two layers, and the boundary is enforced by a test:**

```
chatterbox/   L1 RUN     must NEVER import research/
research/     L3 STUDY   may import chatterbox/ freely
tests/        L3
```

Deleting `research/` and `tests/` leaves a working device. `scripts/check_layers.py` and
`tests/test_layer_boundary.py` enforce this. The only bridge is `chatterbox/instrumentation.py`.

**Everything is Python.** There is no compiled component, no web stack, no JavaScript, no database.

---

## 2. Which language or format governs which aspect

This is what to open for a given kind of change.

| Aspect | Language / format | Where | Notes |
|---|---|---|---|
| Application logic, CLI, synthesis orchestration | **Python 3.10+** | `chatterbox/` | No type annotations in most modules; no async except powerd's socket server. |
| Graphical interface | **Python + Tkinter** (Tcl/Tk underneath) | `chatterbox/gui/` | Plain Tk widgets plus hand-drawn `Canvas` icons. No Qt, no web view, no `.ui` files, no CSS. Layout is grid weights, not fixed pixels. |
| Interface text (fr/en) | **Python dict** | `chatterbox/gui/i18n.py` | Not gettext, not `.po`. `t("key")` reads from the active locale dict. |
| Model registry, GUI options, post-processing, profiling config | **YAML** | `chatterbox/config/config_tts.yaml` | The main knob file. Read once at startup, never reloaded. |
| Runtime power/display preferences | **YAML** | `chatterbox/config/user_prefs.yaml` | Written by the settings screen, reloaded by powerd on `SIGHUP`. |
| Pronunciation and text-cleanup rules | **CSV** (regex → replacement) | `chatterbox/synthesis/backends/fastspeech2_hifigan/rules/` | FastSpeech 2-specific: full of `{p h o n}` bracket syntax. Piper does **not** apply them by default. |
| Acoustic model / vocoder weights | **PyTorch checkpoints** + FS2's own YAML configs | `assets/models/FastSpeech2/`, `assets/models/hifi-gan-master/` | Not in git. Downloaded. |
| Piper voices | **ONNX** + `.json` sidecar | `assets/models/Piper/` | Not in git. `scripts/fetch_piper_voices.sh`, sha256-verified. |
| Style conditioning model | **HuggingFace transformers** checkpoint | `assets/models/flaubert/` | Only loaded when a `<STYLE_TAG=…>` is present. |
| Provisioning, deployment, voice download | **Bash** | `scripts/` | All resolve their own location; runnable from anywhere. |
| Service definition | **systemd unit** | `deploy/systemd/` | Hardcodes `/home/chatterbox/chatterbox`; edit after install. |
| Kiosk display startup | **Xorg** + shell + systemd drop-in | `deploy/xorg-kiosk/` | Plain X, no compositor. `.xinitrc`, `getty@tty1` override. |
| GPIO (amplifier, switches) | **Python, gpiozero + lgpio** | `chatterbox/power/amp.py`, `inputs.py` | `lgpio`, not `RPi.GPIO` — the Pi 5's RP1 chip needs it. Guarded imports. |
| I2C (battery gauge, current monitor) | **Python, smbus2** | `chatterbox/power/battery.py`, `research/profiling/sampler.py` | UPS at `0x36`, INA226 at `0x40`, DAC at `0x4c`, all on `i2c-1`. |
| Touch / key activity detection | **Python, evdev** | `chatterbox/power/inputs.py` | Reads `/dev/input` directly. Linux only. |
| GUI ↔ daemon IPC | **Newline-delimited JSON over a unix stream socket** | `chatterbox/power/ipc.py` | Not D-Bus, not HTTP. `/run/chatterbox/powerd.sock`. |
| Audio playback | **pydub → `ffplay`** | `chatterbox/audio/playback.py` | Needs `ffmpeg` installed. Wav I/O is `scipy.io.wavfile`. |
| Subtitles | **WebVTT** + a JSON alignment file | `chatterbox/synthesis/subtitles.py` | FastSpeech 2 only. |
| Facial animation output | **Custom binary** (`.AU`) | written by FastSpeech 2 | Header of 4 `int32`, then `float32` frames. |
| Profiling output | **CSV + JSONL**, optional **XLSX** | `research/profiling/`, `research/benchmark/` | XLSX via `openpyxl`, lazily imported. |
| Tests | **pytest** | `tests/` | No fixtures framework beyond pytest built-ins. |

---

## 3. The three invented syntaxes

Nobody guesses these. They are not standard anything.

### 3.1 Control tags — typed by the *user*, in the text to be spoken

Parsed in `chatterbox/synthesis/backends/fastspeech2_hifigan/text_pipeline.py`
(`parse_params_from_text()`), and for Piper in
`chatterbox/synthesis/backends/piper/text_frontend.py` (`prepare()`, `<SPEAKER=…>` only).

| Syntax | Meaning |
|---|---|
| `<SPEAKER=AD>` | Pick the voice |
| `<STYLE=ENTHOUSIASTE>` | Pick the GST style |
| `<STYLE_INTENSITY=0.6>` | Style strength 0–1 |
| `<STYLE_TAG=free text>` | Free-text style, routed through FlauBERT |
| `{s y z i}` | Phonetic pronunciation |
| `#word#` | Emphasis |
| `\|` | Sub-utterance separator (FastSpeech 2 only) |

⚠ The separator is `\|`, **not** `§`, despite what older comments said. `§` is ordinary punctuation.

### 3.2 The Emmanuelle phoneme alphabet — the on-screen phonetic keyboard

The key table is `keys["Emmanuelle"]` in `chatterbox/gui/keyboards.py`. It is FastSpeech 2's own
symbol set, tied to that checkpoint; **there is no G2P step anywhere in this repository**. A backend
that cannot read it declares `accepts_phoneme_input: false` and the GUI falls back per
`GUI_config.phoneme_fallback`. Reference: <https://zenodo.org/record/4580406>.

### 3.3 Config-string dispatch — YAML naming Python methods

`config_tts.yaml` entries carry method *names as strings*, resolved with `getattr` at runtime:

```yaml
backend: "piper"            # -> registry.activate_tts_backend("piper")
load_script: "load_piper"   # -> getattr(registry.BACKEND, "load_piper")
gui_script: "gui_generic_controls"
```

So **renaming a backend method silently breaks a YAML entry** — no import error, an `AttributeError`
at load time. `gui_script` is the odd one out: it resolves against `chatterbox/gui/app.py`'s module
globals, not the backend. Full rules in
[`chatterbox/synthesis/README.md`](../chatterbox/synthesis/README.md).

---

## 4. One synthesis, end to end

```
do_tts.py
  └─ chatterbox/cli.py         main()          parse args, load config, merge flags
                               load_models()   activate backend, run its load_script
                               syn_audio()     CLI wrapper: compute + report + play
       │                                       (the GUI skips this and calls synthesize directly)
       ▼
     chatterbox/synth.py       synthesize()    THE COMPUTE PATH. Tk-free.
       │  1. add default start/end punctuation
       │  2. read needs_vocoder / supports_subtitles from the model's YAML entry
       │  3. registry.BACKEND.tts(...)  -> (output_dir, processed_text)
       │  4. if needs_vocoder: registry.BACKEND.vocoder(...)
       │  5. read the wav, denoise, optional post-process
       │  6. optional visual smoothing of the .AU file
       │  7. set playback.AUDIO_EXAMPLE
       ▼
     chatterbox/audio/playback.py  play_audio()   caller's job, never synthesize()'s
```

Backend dispatch inside step 3:

```
registry.BACKEND  ──►  _BackendProxy.__getattr__
                        1. the currently activated backend  (activate_tts_backend)
                        2. otherwise: linear scan of all backends, first match wins  ⚠
```

The GUI runs steps above on a worker thread (`chatterbox/gui/app.py`, `_work()`), then posts UI
updates back through `ui_queue`. It never touches Tk off the main thread.

---

## 5. Invariants — break these and it fails quietly

| # | Rule | Symptom if violated |
|---|---|---|
| 1 | `chatterbox/` must not import `research/` | `tests/test_layer_boundary.py` fails; a deployed device that lost `research/` cannot import at all |
| 2 | Run from the repository root | `FileNotFoundError` on `config/ALL_corpus/preprocess.yaml` — model paths in YAML are relative to the working directory |
| 3 | Never touch Tk off the main thread | Intermittent hangs and crashes, not clean errors. Post through `ui_queue` |
| 4 | `chatterbox/synth.py` must stay Tk-free | The GUI worker thread imports it; a Tk import there re-introduces the bug the split fixed |
| 5 | Backend method names are public API — they are named in YAML | `AttributeError` at model load, not at import |
| 6 | `tts()` must return the output **directory**, not a file prefix | `FileNotFoundError` from a doubled `audio_file` path segment (a real Pi bug) |
| 7 | Capability flags in YAML must match backend reality | Crash mid-synthesis; nothing validates them |
| 8 | `chatterbox/config/paths.py` derives everything from `parents[2]` | Move that file and every path silently resolves wrong |
| 9 | Slider descriptors must set `resolution` | Only two selectable values on a 0.5–2.0 range |
| 10 | One synthesis path only | Do not add a second compute path for CLI or GUI — both call `synthesize()` |

---

## 6. "I want to change X"

| Task | Files to touch |
|---|---|
| **Add a Piper voice** | `scripts/fetch_piper_voices.sh` (URL + sha256), `chatterbox/config/config_tts.yaml` (`speakers:` list), `chatterbox/synthesis/backends/piper/README.md` |
| **Add a whole new backend** | New `chatterbox/synthesis/backends/<name>/backend.py`; register in `chatterbox/synthesis/registry.py`; add a `tts_models` entry. Follow [`chatterbox/synthesis/README.md`](../chatterbox/synthesis/README.md) |
| **Change a GUI label** | `chatterbox/gui/i18n.py` — both `"fr"` and `"en"` |
| **Add a GUI control for a backend** | That backend's `describe_controls()`. **Do not edit `app.py`** — controls are declarative |
| **Change how a control renders** | `chatterbox/gui/app.py`, `gui_generic_controls()` / `_build_chip_grid_control()` |
| **Change the letter keyboard layout** | `chatterbox/gui/app.py`, `_LETTER_LAYOUTS` |
| **Change the phoneme keyboard** | `chatterbox/gui/keyboards.py`, the `keys["Emmanuelle"]` table |
| **Add an interface language** | `chatterbox/gui/i18n.py` (new locale dict), `config_tts.yaml` `GUI_config.languages`, and a model with a matching `language:` field |
| **Change synthesis defaults** (speed, pitch, style) | `chatterbox/config/config_tts.yaml`, the model's `default_args` |
| **Fix a mispronunciation** | `chatterbox/synthesis/backends/fastspeech2_hifigan/rules/custom_regex_rules.csv` |
| **Change audio post-processing** | `chatterbox/synthesis/audio_postprocess.py`; defaults in `config_tts.yaml` `postprocess:` |
| **Change power timings / brightness** | `chatterbox/config/user_prefs.yaml`, or the GUI settings screen |
| **Add a power state or transition** | `chatterbox/power/fsm.py`, then `chatterbox/power/daemon.py` for the entry actions |
| **Add a powerd command** | `chatterbox/power/ipc.py` (`_COMMANDS`), `daemon.py`, `client.py` |
| **Record a new profiling metric** | `research/profiling/recorder.py` (per sentence) or `sampler.py` (time series), then `join.py` to surface it |
| **Add a benchmark sentence** | `research/benchmark/sentences_fr.jsonl` |
| **Change the kiosk boot** | `deploy/xorg-kiosk/`, then `scripts/kiosk_finalize.sh` |
| **Add a runtime dependency** | `pyproject.toml` **and** `requirements-pi.txt` — keep both in step |

---

## 7. Where mutable state lives

There is no dependency-injection container and no application object. State is deliberately few,
explicit globals plus per-backend instance attributes.

| State | Location | Notes |
|---|---|---|
| Selected TTS / vocoder index | `chatterbox/state.py` | Two module globals. Snapshot them before starting a worker thread — never read them inside one |
| Loaded models | Backend instance attributes | `FastSpeech2HifiGanBackend`, `PiperBackend`. One shared instance each, in `registry.py` |
| Which backend colliding names resolve to | `registry.py`, `_active_tts_backend` | Set by `activate_tts_backend()` |
| Most recent audio clip | `chatterbox/audio/playback.py`, `AUDIO_EXAMPLE` | How `synthesize()` hands audio to the caller. A module global, not a return value |
| Profiling implementation | `chatterbox/instrumentation.py`, `_impl` | `None` until `research.profiling` installs itself |
| Current profiling recorder | `research/profiling/__init__.py` | A `contextvars.ContextVar` |
| GUI widget references | `chatterbox/gui/app.py` module globals | Main-thread only |
| Power state | `chatterbox/power/fsm.py`, `PowerFSM.state` | Daemon process, not the GUI process |

---

## 8. Key symbols

Start here when grepping. *(Verified by `tests/test_codemap.py` — if a rename lands without updating
this table, the suite fails.)*

| Symbol | File | What it is |
|---|---|---|
| `main()` | `chatterbox/cli.py` | Argument parsing and mode dispatch |
| `syn_audio()` | `chatterbox/cli.py` | CLI wrapper: compute, report, play |
| `warmup()` | `chatterbox/cli.py` | Throwaway first synthesis, run in the background |
| `synthesize()` | `chatterbox/synth.py` | **The compute path.** Start here |
| `AudioResult` | `chatterbox/synth.py` | What `synthesize()` returns |
| `install()` | `chatterbox/instrumentation.py` | How `research/` arms the profiling seam |
| `NullRecorder` | `chatterbox/instrumentation.py` | Inert profiling object; keeps call sites branch-free |
| `activate_tts_backend()` | `chatterbox/synthesis/registry.py` | Selects which backend names resolve against |
| `FastSpeech2HifiGanBackend` | `chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py` | The two-stage backend |
| `PiperBackend` | `chatterbox/synthesis/backends/piper/backend.py` | The monolithic backend |
| `parse_params_from_text()` | `chatterbox/synthesis/backends/fastspeech2_hifigan/text_pipeline.py` | Control-tag parsing |
| `normalize_and_limit()` | `chatterbox/synthesis/audio_postprocess.py` | Peak normalisation + soft limiter |
| `write_subtitles()` | `chatterbox/synthesis/subtitles.py` | WebVTT output |
| `play_audio()` | `chatterbox/audio/playback.py` | Playback; reads `AUDIO_EXAMPLE` |
| `create_gui()` | `chatterbox/gui/app.py` | GUI entry point; wraps the restart loop |
| `gui_generic_controls()` | `chatterbox/gui/app.py` | Renders a backend's declared controls |
| `t()` | `chatterbox/gui/i18n.py` | Translated string lookup |
| `dispatch()` | `chatterbox/gui/input.py` | Action routing (switches, buttons) |
| `PowerFSM` | `chatterbox/power/fsm.py` | ACTIVE → DIM → DARK → DEEP |
| `get_client()` | `chatterbox/power/client.py` | GUI-side powerd client; no-ops when absent |
| `run_benchmark()` | `research/benchmark/runner.py` | The fixed 10-sentence set |
| `run_join()` | `research/profiling/join.py` | Merges samples and sentences into results |
| `violations()` | `scripts/check_layers.py` | The layer-boundary check |

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **L1 / RUN**, **L3 / STUDY** | The two layers. See §1 |
| **GST** | Global Style Token — FastSpeech 2's style embedding. The 12 named emotions are GST tokens |
| **StyleTag** | Free-text style conditioning through FlauBERT, distinct from GST |
| **`.AU`** | Custom binary facial-animation output. Not the Sun audio format |
| **`.WAVEGLOW`** | A mel-spectrogram **container format**, not the Waveglow vocoder (removed) |
| **Backend** | A TTS engine implementing the contract in `chatterbox/synthesis/README.md` |
| **Monolithic backend** | Text → wav in one step, `needs_vocoder: false` (Piper) |
| **RTF** | Real-time factor: synthesis time ÷ audio duration. Below 1.0 is faster than real time |
| **PMIC** | The Pi's power management IC. Read via `vcgencmd`; a proxy needing calibration |
| **INA226** | I2C current/voltage sensor on the amplifier branch |
| **SD line** | The amplifier's shutdown pin, driven by powerd to avoid idle draw and pops |
| **powerd** | `chatterbox-powerd`, the power daemon. A separate process |
| **Put away** | User action sending the device straight to DEEP (halt) |
| **Emmanuelle** | The phonetic keyboard layout and its symbol alphabet |
| **Kiosk mode** | Autologin → Xorg → fullscreen GUI, no desktop |

---

## 10. Before you commit

```bash
python3 -m pytest tests/            # includes the layer and codemap checks
python3 scripts/check_layers.py     # exit 0 = boundary intact
```

Then **verify on real hardware** if you touched the synthesis path. The suite mocks synthesis, so a
green run does not mean the device still speaks — see [`tests/README.md`](../tests/README.md).

Append a `docs/research/CHANGELOG.md` entry for anything non-trivial, and update this file if you
moved, renamed or added a key symbol.
