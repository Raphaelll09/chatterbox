# Chatterbox

**An embedded neural text-to-speech demonstrator for AAC**, running entirely on CPU on a
Raspberry Pi 5.

Chatterbox is a speaking aid for people with augmentative and alternative communication (AAC)
needs: you type — with a physical keyboard, an on-screen letter keyboard, or a phonetic keyboard —
and the device speaks, expressively, in French or English. It is designed to run as a self-contained
kiosk appliance on battery, with no network connection and no GPU.

> 🇫🇷 **Documentation en français :** [README.fr.md](README.fr.md) contains the original French
> guide, with the fullest reference on the control-tag mini-language, the benchmark and the
> profiling procedure.

---

## Table of contents

1. [What it does](#1-what-it-does)
2. [Repository structure](#2-repository-structure)
3. [Installation](#3-installation)
4. [The TTS models](#4-the-tts-models)
5. [Running it](#5-running-it)
6. [The GUI](#6-the-gui)
7. [Writing for the synthesiser: control tags](#7-writing-for-the-synthesiser-control-tags)
8. [Power management on the Pi](#8-power-management-on-the-pi)
9. [Maintenance and monitoring](#9-maintenance-and-monitoring)
10. [Development](#10-development)
11. [Known limitations](#11-known-limitations)
12. [Licensing status](#12-licensing-status)

---

## 1. What it does

The default pipeline has four stages, all on CPU:

```
text ──► [FlauBERT]  ──► [FastSpeech 2] ──► [HiFi-GAN] ──► [post-process] ──► audio
          optional,        acoustic model     vocoder        denoise, normalise,
          style tags       text → mel         mel → wav      subtitles
          only
```

A second backend, **Piper**, is monolithic: text goes straight to a waveform, with no separate
vocoder. Which pipeline runs is decided per model by configuration, not by code — see
[The TTS models](#4-the-tts-models).

Alongside speech, the FastSpeech 2 backend emits `.AU` facial-animation parameters and WebVTT
subtitles with per-symbol timing, for driving a virtual avatar.

**Target hardware:** Raspberry Pi 5 (16 GB), IQaudio DAC, amplifier and speaker, touchscreen,
DFRobot FIT0992 UPS HAT, optional physical accessibility switches. It also runs fine on a
Windows or Linux desktop for development.

---

## 2. Repository structure

The repository is split into two layers, and **the split is mechanically enforced**:

| Layer | Directories | Contents |
|---|---|---|
| **RUN** | `chatterbox/`, `assets/`, `deploy/`, `scripts/` | Everything strictly required to make the device speak. |
| **STUDY** | `research/`, `tests/`, `docs/research/` | Everything that exists because this is research: profiling, benchmarks, power measurement, the development log. |

> **`chatterbox/` must never import `research/`. `research/` may import `chatterbox/` freely.**
> Deleting `research/` and `tests/` leaves a fully working demonstrator.

This is checked by `scripts/check_layers.py` and `tests/test_layer_boundary.py`, not merely
documented. The single point of contact — profiling timestamps on the synthesis hot path — goes
through `chatterbox/instrumentation.py`, a seam whose functions are inert no-ops until
`research.profiling` installs itself into them at import time.

```
chatterbox/          the application package            → chatterbox/README.md
  cli.py               argument parsing, mode dispatch
  synth.py             the compute path (Tk-free, shared by CLI and GUI)
  instrumentation.py   the RUN/STUDY seam
  synthesis/           backends + the backend contract  → chatterbox/synthesis/README.md
  gui/                 Tkinter interface, keyboards, i18n, settings
  power/               chatterbox-powerd (Pi only, optional)
  config/              config_tts.yaml, user_prefs.yaml, paths.py
assets/              vendored model code + keyboard audio → assets/README.md
deploy/              systemd units + Xorg kiosk autostart → deploy/README.md
scripts/             Pi provisioning, voice download, layer check → scripts/README.md
research/            profiling, benchmarks, archived data → research/README.md
tests/               pytest suite                        → tests/README.md
docs/                documentation index                 → docs/README.md
```

Every top-level directory has its own `README.md` explaining what it is and what to know before
touching it.

---

## 3. Installation

Pretrained weights are **not in this repository**. Every install path downloads them separately.

### 3.1 Raspberry Pi 5 (deployment)

```bash
# 1. Flash Raspberry Pi OS 64-bit, enable SSH, boot, then:
git clone https://github.com/Raphaelll09/chatterbox.git ~/chatterbox
cd ~/chatterbox
./scripts/setup_pi.sh
```

That is the whole first-run path: `setup_pi.sh` installs the apt packages, creates a venv at
`~/chatterbox/venv`, installs the Python requirements, downloads the weights, smoke-tests the
install, and sets up the kiosk autostart and the powerd unit. It is idempotent — safe to re-run
if a step fails — and prints a PASS/FAIL summary.

> **Building a device rather than trying it out?** [`INSTALL.md`](INSTALL.md) is the deployment
> guide: what each step does, the manual hardware steps `setup_pi.sh` deliberately leaves to you
> (amplifier pin polarity, backlight node, unit paths), the bring-up protocol that gates
> unattended boot, and how to mass-produce units from a golden image.

### 3.2 Windows or Linux desktop (development)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux:    source .venv/bin/activate
python -m pip install --upgrade pip setuptools
pip install -r requirements-dev.txt
```

Or install as a package, which gives you the `chatterbox` console script:

```bash
pip install -e '.[dev]'          # runtime + tests + research tooling
pip install .                    # runtime only
```

Extras: `[pi]` (GPIO, I2C, evdev), `[research]` (profiling, spreadsheet export), `[dev]`
(pytest + research).

**Linux GUI** also needs Tk: `sudo apt-get install python3-tk` (already in
`apt-packages-pi.txt`).

**Audio playback** goes through `pydub`, which shells out to `ffplay` — install `ffmpeg` if
playback is silent.

### 3.3 Pretrained weights (all platforms)

Download from the Google Drive links in [README.fr.md](README.fr.md#modèles-pré-entrainés-et-configuration)
and unpack into:

| Model | Destination |
|---|---|
| FastSpeech 2 (`config`, `output`, `preprocessed_data`; checkpoint `390000`) | `assets/models/FastSpeech2/` |
| FlauBERT large cased | `assets/models/flaubert/flaubert_large_cased/` |
| HiFi-GAN (`FR_V2`, `g_00570000`) | `assets/models/hifi-gan-master/` |

### 3.4 Optional: the Piper backend

Piper is a separate, optional backend under **GPL-3.0-or-later**. It is deliberately not vendored
and not in any requirements file, so this project's own licensing is unaffected — skip this section
entirely if you only want FastSpeech 2 + HiFi-GAN.

```bash
pip install piper-tts==1.5.0
./scripts/fetch_piper_voices.sh      # downloads 3 voices, verifies sha256
```

A single prebuilt wheel, no source build, no separate `espeak-ng` system dependency.

---

## 4. The TTS models

Configured in `chatterbox/config/config_tts.yaml`. Three selectable models today:

| # | Model | Backend | Language | Voices | Vocoder | Styles |
|---|---|---|---|---|---|---|
| 0 | **Multi Speaker/Style** | FastSpeech 2 + HiFi-GAN | fr | NEB, AD, IZ, RO (female), DG (male) | HiFi-GAN | 12 named + 4 unnamed |
| 1 | **Piper-tts (Français)** | Piper | fr | Siwis, Jessica, Pierre | none | — |
| 2 | **Piper en_US (lessac, medium)** | Piper | en | lessac | none | — |

**FastSpeech 2** is the expressive one: 12 named GST styles (`NEUTRE`, `ENTHOUSIASTE`, `COLERE`,
`PENSIF`, `ETONNE`, `INCREDULE`, `EVIDENCE`, `RECONFORTANT`, `DESOLE`, `DETERMINE`, `ESPIEGLE`,
`SUPPLIANT`) with adjustable intensity, plus pitch/energy/speed controls and free-text style
conditioning via FlauBERT. It is the only backend that accepts phonetic input and produces
subtitles and facial-animation data. `AD` is recommended for audio-visual synthesis.

**Piper** is faster and lighter but has no style dimension, no phoneme input, and no subtitles. Its
two entries share a `menu_group`, so the GUI shows *one* "Piper-tts" entry and resolves French vs
English from the active interface language.

Vocoder: **HiFi-GAN V2 FR 570000** (only used by model 0).

Each model declares three capability flags read before it loads — `needs_vocoder`,
`accepts_phoneme_input`, `supports_subtitles` — which is how the GUI adapts without knowing
anything about the backend. Adding a backend is documented in
[`chatterbox/synthesis/README.md`](chatterbox/synthesis/README.md).

---

## 5. Running it

> **Run from the repository root.** Model paths in `config_tts.yaml` are relative to the working
> directory. See [Known limitations](#11-known-limitations).

### Interactive free text

```bash
python3 do_tts.py
```

Prompts on stdin, synthesises, plays. `Ctrl+C` to exit.

### Graphical interface

```bash
python3 do_tts.py --gui
```

### Choosing a model at startup

```bash
python3 do_tts.py --default_tts 1        # Piper French
python3 do_tts.py --default_tts 2 --gui  # Piper English, in the GUI
```

### Useful flags

| Flag | Effect |
|---|---|
| `--config FILE` | Alternative config (default `chatterbox/config/config_tts.yaml`) |
| `--default_tts N` / `--default_vocoder N` | Preselect model by index |
| `--postprocess` / `--no-postprocess` | Peak normalisation + soft limiter |
| `--target-crest-db DB` / `--target-peak-dbfs DBFS` | Post-processing targets (14.0 / −1.0) |
| `--analyze` | Write a crest/loudness report per synthesis |
| `--report-wav PATH` | Analyse an existing wav and exit |
| `--profile` | Enable profiling (same as `CHATTERBOX_PROFILE=1`) |
| `--benchmark` | Run the fixed 10-sentence set instead of free text |
| `--p4-sweep` | Run the power/cadence sweep |

`--gui`, `--benchmark` and `--p4-sweep` are mutually exclusive; combining them prints a warning and
runs the non-GUI one.

---

## 6. The GUI

Launch with `python3 do_tts.py --gui`. It is designed for touch, reflows between portrait and
landscape, and runs synthesis on a worker thread so the interface never freezes.

### Layout

- **App bar** — model, language, theme, tools and settings menus, status light, battery percentage.
  There is no on-screen power button: the device dims, then blanks, then goes to a resumable
  low-power sleep on its own after the idle timers; full power-off for storage is the Pi's hardware
  button.
- **Text area** — what will be spoken. Can be hidden via *Tools → Show input area* for users who
  only use the keyboard.
- **Keyboard area** — a segmented control switches between:
  - **Texte** — an on-screen letter keyboard, layout switchable between simplified AZERTY (default)
    and QWERTY, independently of the TTS language. Punctuation keys: `,` `'` `?` `!` (no `.` — a
    final `.` is added automatically).
  - **Phonèmes** — the "Emmanuelle" phonetic keyboard, for precise pronunciation control, with
    `? ! . ;` and `,` for prosody. Only FastSpeech 2 understands it; with a Piper model selected the
    GUI falls back per `GUI_config.phoneme_fallback` (`translate_labels` by default — keys insert
    their plain-French label instead of the raw phone code). The phone runs are wrapped in `{…}` for
    FastSpeech 2 automatically (punctuation stays outside, so `?`/`!` shape the intonation) — you
    don't type the braces.
  - The **▶ button** on the keyboard triggers synthesis and playback. It leaves the text in place,
    so pressing it again replays the phrase; clear with the **C** / **Tout effacer** keys.
- **Emotion bar** — for FastSpeech 2, the 12 named styles as emoji chips; four unnamed tokens hide
  behind an "advanced" toggle. Absent for Piper, which has no styles.
- **Sliders** — *Tools → Synthesis sliders* opens speed, pitch, energy and the bias controls. Which
  sliders exist is declared by the active backend, not hardcoded.

### Menus

| Menu | Contents |
|---|---|
| **Modèle TTS** | Pick the model. Grouped entries (both Pipers) collapse to one item. |
| **Langue** | Switches interface language **and** loads the matching model. Restarts the window. |
| **Thème** | Light/dark. Currently a stub — only one theme table exists. |
| **Outils** | Show/hide the input area; open the synthesis sliders; **Recharger le modèle** (reloads the active model's weights from disk — recovery if synthesis wedges and the buttons grey out). |
| **Réglages** | Power timers, brightness, and an *Avancé* section with the TTS/vocoder pickers, the letter-keyboard layout, a separate **interface language** setting (run the English voice with a French interface), and **Maintenance** buttons that open a terminal / the Wi-Fi setup (`nmtui`) on the kiosk screen. |

Model changes in *Réglages → Avancé* apply immediately; power settings need **Enregistrer**.

Both language controls persist to `gui.language` in `user_prefs.yaml`; whichever was used last wins
at next launch.

---

## 7. Writing for the synthesiser: control tags

These work in the text field and on stdin. Full reference (in French) in
[README.fr.md](README.fr.md).

| Tag | Meaning | Backend |
|---|---|---|
| `<SPEAKER=AD>` | Choose the voice | both |
| `<STYLE=ENTHOUSIASTE>` | Choose the style | FastSpeech 2 |
| `<STYLE_INTENSITY=0.6>` | Style strength, 0–1 (decimal point, not comma) | FastSpeech 2 |
| `<STYLE_TAG=...>` | Free-text style description, routed through FlauBERT | FastSpeech 2 |
| `{s y z i}` | Phonetic pronunciation | FastSpeech 2 |
| `#word#` | Emphasis | FastSpeech 2 |
| `\|` | Sub-utterance separator: synthesise separately, concatenate, ~260 ms silence | FastSpeech 2 only |

Tags must have no spaces around `<`, the keyword or `=`, and the keyword must be uppercase. An
unknown speaker or style is ignored rather than erroring.

Initial and final punctuation are added automatically, so you do not need to type them.

> ⚠ **The separator is `|` (pipe), not `§`.** [README.fr.md](README.fr.md) and a comment in
> `chatterbox/synth.py` both say `§`; the code splits on `|`. `§` is treated as ordinary
> punctuation. Also note this feature is FastSpeech 2 only — using `|` with a Piper model raises
> `FileNotFoundError`.

Example:

```
<STYLE=ENTHOUSIASTE><STYLE_INTENSITY=0.6>Je peux être {t r e z} #enthousiaste#.
```

---

## 8. Power management on the Pi

`chatterbox-powerd` is an optional, Pi-only daemon that makes the device behave like an appliance
rather than a computer. It is a separate process from the GUI, and the GUI degrades silently to
normal behaviour when it is not running.

### States

```
ACTIVE ──30s──► DIM ──180s──► DARK ──1200s──► DOZE          DEEP
  full          backlight     backlight        screen+amp    systemctl halt
  brightness    dimmed        off, amp off     off, CPU      (PUT_AWAY only,
                                               powersave      no GUI button)
```

Any touch, keypress or physical switch returns to ACTIVE. `DOZE` is resident and wakes instantly.
The idle timer never halts — `DEEP` (`systemctl halt`) is only reached by the `PUT_AWAY` command
(e.g. a physical switch); there is no on-screen power button.

### Running it

```bash
python3 -m chatterbox.power.daemon        # foreground, for testing
sudo systemctl start chatterbox-powerd    # as a service
sudo systemctl enable chatterbox-powerd   # at boot
```

### Configuration — `chatterbox/config/user_prefs.yaml`

Reloaded on `SIGHUP`; the GUI's settings screen writes it atomically and signals the daemon.

| Key | Default | Meaning |
|---|---|---|
| `power.t_dim_s` / `t_dark_s` / `t_deep_s` | 30 / 180 / 1200 | Idle seconds before DIM / DARK / DOZE. `t_deep_s: 0` or `null` leaves DARK as the deepest idle state. |
| `power.deep_manual_only` | `false` | If true, the idle timer stops at DARK — nothing reaches DOZE automatically. Hand-edit only (no GUI control). |
| `display.backlight` | `auto` | sysfs node name, or auto-detect. |
| `display.brightness_active` / `brightness_dim` | 255 / 60 | Clamped to `[1, max]` — never 0, which means "dimmest", not "off". |
| `amp.sd_pin` | 23 | GPIO controlling the amplifier shutdown line. |
| `amp.enable_active_high` | `true` | SD-line polarity. |
| `amp.on_watchdog_s`, `settle_ms`, `preroll_ms`, `tail_ms` | 30, 80, 50, 50 | Amp timing — tune to eliminate switching pops. |
| `switches` | `[]` | Physical accessibility switches. |
| `socket.path` / `group` | `/run/chatterbox/powerd.sock`, `chatterbox` | IPC socket. |

> ⚠ **`amp.sd_pin`, `amp.enable_active_high` and `display.backlight` fail silently if wrong.** The
> daemon logs and disables that one control rather than crashing. Verify them on a new board before
> trusting the amp or backlight.

### Battery

The GUI polls the DFRobot FIT0992 UPS HAT directly over I2C (`0x36` on `i2c-1`) every 30 s and shows
a percentage. Absent hardware just hides the indicator.

---

## 9. Maintenance and monitoring

### Kiosk mode

Once a Pi has been verified working, `scripts/kiosk_finalize.sh` turns it into an appliance:
disables `getty@tty1`, tunes `config.txt`/`cmdline.txt` (backed up, idempotent), enables and starts
the units. It never writes EEPROM. **Opt-in — not part of `setup_pi.sh`.** See
[docs/KIOSK.md](docs/KIOSK.md).

The kiosk boots via console autologin → `~/.bash_profile` → `~/.xinitrc` → plain Xorg. A Wayland
compositor (`cage`) was the original design but hit a reproducible `libwlroots` SIGSEGV on real Pi 5
hardware; see [deploy/README.md](deploy/README.md).

### Checking on a running device

```bash
systemctl status chatterbox-powerd
journalctl -u chatterbox-powerd -f            # follow the daemon log
journalctl -b -u chatterbox-powerd            # this boot only

vcgencmd measure_temp                          # SoC temperature
vcgencmd get_throttled                         # 0x0 = never throttled
i2cdetect -y 1                                 # 0x36 UPS, 0x40 INA226, 0x4c DAC
aplay -l                                       # sound cards
```

### Profiling a run

Off by default, zero cost when off.

```bash
python3 do_tts.py --profile                    # instrument a free-text session
python3 do_tts.py --benchmark --repeats 3 --join --export-xlsx
python3 do_tts.py --p4-sweep --cadences 0,1,2,5,10,max --duration 600
```

Output lands in `profile/` (gitignored scratch):

| File | Contents |
|---|---|
| `per_sample.csv` | Background time series: PMIC power, CPU load/frequency, temperature, INA226 |
| `per_sentence.jsonl` | Per-sentence stage timings, character/word counts, audio duration |
| `per_sentence_results.csv` | The two joined: energy, mean/peak power, real-time factor |
| `per_stage_results.csv` | Same, split by pipeline stage |

Standalone tools:

```bash
python3 -m research.profiling.join --profile-dir profile/<run>
python3 -m research.benchmark.export_to_xlsx
python3 -m research.benchmark.compare_runs RUN_A RUN_B --out compare.csv
python3 research/calibration/pmic_calibrate.py     # PMIC → wattmeter calibration
```

Archived historical runs and what each measured: [research/data/README.md](research/data/README.md).

> **Power figures need calibration.** PMIC readings are a proxy, recalibrated against an external
> wattmeter. The calibration's offset absorbs screen, amplifier and unmetered draw, so it is valid
> only for the exact hardware configuration it was captured in.

### Updating a deployed Pi

```bash
cd ~/chatterbox
git pull
find . -name __pycache__ -type d -exec rm -rf {} +    # avoid stale bytecode
sudo systemctl restart chatterbox-powerd
```

Then verify with a real synthesis, not just the test suite — see
[Known limitations](#11-known-limitations).

---

## 10. Development

```bash
python3 -m pytest tests/                 # full suite
python3 scripts/check_layers.py          # RUN/STUDY boundary (exit 0 = intact)
```

On a Windows checkout, bare `python` may resolve to the Store stub — use
`.venv/Scripts/python.exe`.

Tests need no weights and no Tk instance. **They also do not tell you the device still speaks** —
read [tests/README.md](tests/README.md) before treating a green run as reassurance.

**Going to change code?** Start with [docs/CODEMAP.md](docs/CODEMAP.md) — which language governs
which aspect of the program, where everything lives, the invariants that break things quietly, and
an index from "I want to change X" to the files involved. It is written for humans and AI
assistants alike, and `tests/test_codemap.py` verifies its paths and symbol names against the code
so it cannot rot silently.

Further reading: [docs/README.md](docs/README.md) is the documentation index;
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) the deep dive;
[chatterbox/synthesis/README.md](chatterbox/synthesis/README.md) the backend contract;
[docs/research/CHANGELOG.md](docs/research/CHANGELOG.md) the development log.

---

## 11. Known limitations

Honest list. Details and follow-up numbering in
[docs/release/REORG_PLAN.md](docs/release/REORG_PLAN.md) §8.

- **Must be run from the repository root.** Model paths in `config_tts.yaml` are joined against the
  current working directory. `chatterbox/config/paths.py` anchors imports but not model data.
- **Synthesis writes into the working directory** — `audio_file.wav`, `.AU`, `.vtt` and the
  duration-alignment JSON land at the repository root.
- **`|` multi-utterance input is FastSpeech 2 only**, and the documentation says `§`
  (see [§7](#7-writing-for-the-synthesiser-control-tags)).
- **Tkinter is required even for headless modes** — `cli.py` imports the GUI module
  unconditionally.
- **Capability flags are user-editable YAML.** A backend cannot declare its own; setting one wrongly
  crashes at synthesis time with no validation.
- **The core compute path is barely tested.** No test executes `chatterbox/synth.py` past its
  empty-input guard.
- **Six specification documents referenced from the code and `INSTALL.md` are not in this
  repository** — including the bring-up test protocol `INSTALL.md` points you at. See
  [docs/README.md](docs/README.md#missing-documents).

---

## 12. Licensing status

**This repository does not yet carry a licence, and the model weights' redistribution status is
unresolved.** Treat it as "all rights reserved" until that is settled.

| Component | Status |
|---|---|
| Chatterbox source | **No LICENSE file yet** |
| FastSpeech 2 (vendored code) | MIT © 2020 Chung-Ming Chien |
| HiFi-GAN (vendored code) | MIT © 2020 Jungil Kong |
| FastSpeech 2 / HiFi-GAN **French weights** | **Unresolved** — no stated licence, corpus attribution or speaker consent |
| Keyboard prompt audio, reference recordings | **Unresolved** — recordings of identifiable speakers |
| Piper voices | Downloaded, not redistributed here; verify per voice |
| `piper-tts` | GPL-3.0-or-later — **not vendored**, user-installed, so it does not constrain this project |

Full inventory: [docs/release/STRUCTURE_AUDIT.md](docs/release/STRUCTURE_AUDIT.md) §9.

---

## Credits

Developed at **Gipsa-lab**, Grenoble, as an AAC speech-synthesis demonstrator.
Contributors: Evrard Raphaël, Martin Lenglet.

The phonetic alphabet used by the Emmanuelle keyboard is documented at
<https://zenodo.org/record/4580406>.
