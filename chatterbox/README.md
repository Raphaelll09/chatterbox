# `chatterbox/` — L1 RUN

The application package: everything strictly required to make the demonstrator speak on a
Raspberry Pi 5. If it is not needed to produce audio, it does not belong here.

**This package must never import `research/`.** Enforced by `scripts/check_layers.py` and
`tests/test_layer_boundary.py`. See `instrumentation.py` for the one seam that makes profiling
possible without breaking the rule.

## Entry points

| Command | What runs |
|---|---|
| `python3 do_tts.py` | `cli.main()` — interactive free-text synthesis |
| `python3 do_tts.py --gui` | The Tkinter kiosk interface (`gui/app.py`) |
| `python3 -m chatterbox.power.daemon` | `chatterbox-powerd`, the kiosk power daemon |
| `chatterbox` | Console script installed by `pip install .` |

`do_tts.py` at the repository root is a three-line shim kept for the documented CLI contract and
the systemd units that call it by path.

## Modules

| Path | Responsibility |
|---|---|
| `cli.py` | Argument parsing and mode dispatch, `syn_audio()` (console reporting + playback around the compute path), `warmup()`. The only module that reaches into `research/`, always inside a mode gate. |
| `synth.py` | **The compute path.** `synthesize()` — text → mel → wav → denoise → post-process → subtitles. Tk-free by design, so the GUI's worker thread and the CLI share exactly one implementation. |
| `instrumentation.py` | The L1/L3 seam. Inert profiling no-ops that `research.profiling` replaces at import time. |
| `state.py` | Which TTS/vocoder index is selected. Two module globals. |
| `synthesis/` | Backends, the registry, post-processing, subtitles. **Has its own README documenting the backend contract.** |
| `audio/` | `playback.py` (playback + the `AUDIO_EXAMPLE` handoff), `denoise.py` (noisereduce wrapper). |
| `gui/` | The Tkinter interface: `app.py` (main window, reflow, menus), `keyboards.py` (phoneme + letter keyboards), `settings.py`, `i18n.py` (fr/en strings), `input.py` (action dispatch, switch nav), `theme.py`. |
| `power/` | `chatterbox-powerd`: the ACTIVE→DIM→DARK→DEEP kiosk power state machine, backlight, amplifier SD line, physical switches, UPS battery gauge. **Optional and Pi-only** — every hardware import is guarded, and `power/client.py` degrades to a silent no-op when the daemon is not reachable. |
| `config/` | `config_tts.yaml` (model registry, GUI, post-processing), `user_prefs.yaml` (powerd runtime prefs, reloaded on SIGHUP), `paths.py` (repo-root-anchored paths). |

## The synthesis pipeline

1. **FlauBERT front-end** — optional, only when the input carries a `<STYLE_TAG=…>` tag.
2. **Acoustic model** — FastSpeech 2 → mel + `.AU` visual parameters, *or* Piper → finished wav.
3. **Vocoder** — HiFi-GAN, mel → waveform. Skipped entirely for a monolithic backend.
4. **Write** — denoise, optional post-process, visual smoothing, subtitles.

Playback is a separate step the caller triggers afterwards, never part of `synthesize()`.

## Two things to know before editing

**`config/paths.py` is anchored to this file's own location, not the working directory.** If you
move it, fix the `parents[N]` count *first* — an off-by-one there breaks every path silently.

**Model data paths in `config_tts.yaml` are still relative** (`folder: "assets/models/..."`) and are
joined against the current working directory, so the CLI must be run from the repository root. This
is a known incomplete piece of the path-anchoring work, recorded as follow-up F2 in
`docs/release/REORG_PLAN.md`.
