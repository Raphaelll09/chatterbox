# Chatterbox — Structure Audit (pre-open-source release)

**Audit date:** 2026-08-17
**Commit audited:** the tip of `reorg/phase-0-path-anchoring`, working tree clean — tagged
`pre-release-audit`. (An earlier draft of this line named `c8a0a2e`; that was a misread of the log,
and in any case every SHA below that tag was rewritten on 2026-08-27 by a mailmap history rewrite.
Use the tag, not a SHA.)
**Scope:** read-only inventory of the repository as it actually exists. No file was created, moved,
renamed, deleted or edited to produce this document, and no state-modifying git command was run.

**Method note.** Everything below was verified against the code. Where `CLAUDE.md`,
`docs/context/CHANGELOG.md` or `docs/gui/INTERCHANGEABLE_BACKENDS.md` make a claim that the code
does not support, this document records the code's behaviour and flags the discrepancy explicitly.
Three such discrepancies were found (§5.1, §5.3, §7.1).

---

## 0. Headline findings

Ordered by how much they should change the reorganisation plan.

| # | Finding | Evidence |
|---|---|---|
| **H1** | **The L1/L3 split does not exist even approximately.** Four L1 modules import `tools.monitoring.profiling` at module scope, including the core compute path. Deleting `tools/` makes the demonstrator unimportable — not degraded, *unimportable*. | §4.2, verified empirically |
| **H2** | **The declared backend contract (`chatterbox/synthesis/base.py`) is dead code.** No class subclasses it, nothing imports it, `SynthesisResult`/`SynthesisRequest` are never constructed. The real contract is an undocumented tuple return plus three YAML flags. | §5 |
| **H3** | **The repository has no licence at all**, and its central asset (the French FastSpeech 2 checkpoint, plus committed recordings of identifiable speakers) has no established redistribution status. | §9 |
| **H4** | `assets/models/flaubert/flaubert_large_cased` is a **gitlink (mode 160000) with no `.gitmodules`**. A fresh `git clone` produces an empty directory and `git submodule` errors out. | §10.1 |
| **H5** | **Six specification documents referenced throughout code docstrings and docs are not in the repository.** Every reference becomes a dead pointer on publication. | §10.2 |

---

## 1. Directory tree

### 1.1 Tracked tree (359 tracked files)

```
embedded_tts/
├── CLAUDE.md, README.md, INSTALL.md, .gitignore
├── requirements-dev.txt, requirements-pi.txt, apt-packages-pi.txt
├── do_tts.py                             # entry point (3-line shim)
│
├── chatterbox/                           # the application package
│   ├── __init__.py, state.py, synth.py, cli.py
│   ├── audio/        __init__.py, denoise.py, playback.py
│   ├── config/       __init__.py, paths.py, config_tts.yaml, user_prefs.yaml
│   ├── gui/          __init__.py, app.py, i18n.py, input.py, keyboards.py,
│   │                 settings.py, theme.py
│   ├── power/        __init__.py, amp.py, backlight.py, battery.py, client.py,
│   │                 config.py, daemon.py, fsm.py, inputs.py, ipc.py
│   └── synthesis/
│       ├── __init__.py, base.py, registry.py, subtitles.py, audio_postprocess.py
│       └── backends/
│           ├── fastspeech2_hifigan/  __init__.py, backend.py, text_pipeline.py,
│           │                         rules/{custom,symbols,url}_regex_rules.csv
│           └── piper/                __init__.py, backend.py, text_frontend.py, README.md
│
├── tools/                                # research/measurement tooling
│   ├── measurement/  benchmark/{runner,p4_sweep,export_to_xlsx,compare_runs}.py,
│   │                 benchmark/sentences_fr.jsonl, pmic_calibrate.py
│   └── monitoring/   profiling/{__init__,sampler,recorder,parsing,join,calibrate}.py
│
├── tests/                                # 24 files, 303 test functions
├── deploy/
│   ├── systemd/      chatterbox-gui.service (legacy), chatterbox-powerd.service
│   └── xorg-kiosk/   README.md, xinitrc, bash_profile_snippet.sh,
│                     getty-tty1-autologin.conf
├── scripts/          setup_pi.sh, kiosk_finalize.sh, fetch_piper_voices.sh
│
├── assets/
│   ├── audio/
│   │   ├── prompts/Emmanuelle/   29 .wav  (phoneme keyboard key audio)
│   │   └── reference/            5 .wav   (research reference recordings)
│   └── models/
│       ├── FastSpeech2/          ~35 vendored .py + 3 lexicons + 5 img/
│       ├── hifi-gan-master/      ~10 vendored .py + 3 configs
│       ├── Waveglow/             ~30 vendored .py incl. full tacotron2/ copy
│       └── flaubert/flaubert_large_cased   ← GITLINK, no .gitmodules (see §10.1)
│
├── docs/
│   ├── REORG_PROPOSAL.md, REORG_VERIFICATION.md
│   ├── assets/tts_gui.png
│   ├── context/  ARCHITECTURE.md, CHANGELOG.md, PIPER_INTEGRATION_SUMMARY.md
│   ├── gui/      GUI.md, INTERCHANGEABLE_BACKENDS.md
│   ├── kiosk/    KIOSK.md
│   └── power/    POWERD.md
│
├── hardware/     .gitkeep                 ← the entire L2 layer, empty
└── profile/      .gitkeep + ~180 COMMITTED run-data files (see §10.3)
```

### 1.2 Paths that exist locally but are **not** tracked

Recorded because they affect what a fresh clone actually gets.

| Path | Status | Notes |
|---|---|---|
| `assets/models/FastSpeech2/config/` | gitignored | **Required to run.** From Google Drive. |
| `assets/models/FastSpeech2/output/` | gitignored | **Required to run** (checkpoint `390000`). |
| `assets/models/FastSpeech2/preprocessed_data/` | gitignored | Required by the FS2 config loader. |
| `assets/models/hifi-gan-master/FR_V2/` | gitignored | **Required to run** (`g_00570000` + config). |
| `assets/models/flaubert/flaubert_large_cased/` | gitlink | 1.49 GB `pytorch_model.bin` present locally. |
| `assets/models/Piper/` | gitignored | 3 voices, fetched by `scripts/fetch_piper_voices.sh`. |
| `assets/models/Waveglow/waveglow_NEB.pt` | gitignored | Unreachable via config (§7.2). |
| `audio_keyboards/` | untracked, empty | Leftover from the pre-Phase-4 layout. |
| `profile/per_sentence.jsonl`, `profile/compare_fs2_siwis_upmc.csv` | gitignored | Loose run output at `profile/` root. |
| `audio_file.{wav,AU,fr.vtt}`, `audio_file_duration_alignment.json` | gitignored | **Synthesis output written to the repo root** (§6.3). |
| `.venv/`, `__pycache__/`, `.pytest_cache/`, `.claude/` | gitignored | Tooling. |
| `graphify-out/` | gitignored | AI-assistant knowledge-graph cache. |
| `requirements-pi-lock.txt` | **absent** | `scripts/setup_pi.sh:28` expects it; never generated. |

---

## 2. Per-file inventory

`LOC` = line count. `Last` = last commit date touching the file. Layer per the brief:
L1 RUN / L2 BUILD / L3 STUDY / DEAD / UNCLEAR.

### 2.1 Root & packaging

| Path | Purpose | LOC | Last | Layer |
|---|---|---|---|---|
| `do_tts.py` | Entry-point shim → `chatterbox.cli.main()` | 9 | 07-20 | **L1** |
| `README.md` | French user doc; weight download links | 297 | 07-20 | **L1** |
| `INSTALL.md` | PC + Pi install procedure | 161 | 07-31 | **L1** |
| `CLAUDE.md` | AI-assistant repo guide | 333 | 07-31 | **UNCLEAR** — publish or strip? |
| `.gitignore` | — | 46 | 07-23 | **L1** |
| `requirements-dev.txt` | PC pins | 46 | 07-20 | **L3** (dev/research env) |
| `requirements-pi.txt` | Pi runtime floors | 62 | 07-21 | **L1** |
| `apt-packages-pi.txt` | Pi system packages | 77 | 07-31 | **L1** |

### 2.2 `chatterbox/` — application package

| Path | Purpose | LOC | Last | Layer |
|---|---|---|---|---|
| `__init__.py` | empty | 0 | 07-20 | L1 |
| `cli.py` | argparse/dispatch, `syn_audio()`, `warmup()` | 397 | 07-23 | **L1** ⚠ imports L3 |
| `synth.py` | Tk-free compute path — the core | 282 | 07-23 | **L1** ⚠ imports L3 |
| `state.py` | selected TTS/vocoder index globals | 14 | 07-20 | L1 |
| `audio/denoise.py` | noisereduce wrapper | 24 | 07-20 | L1 |
| `audio/playback.py` | `play_audio()`, `AUDIO_EXAMPLE` global | 160 | 07-24 | L1 |
| `config/paths.py` | repo-root-anchored paths | 32 | 07-21 | L1 |
| `config/config_tts.yaml` | model registry + GUI + profiling config | 293 | 07-29 | L1 (⚠ L3 keys inside) |
| `config/user_prefs.yaml` | powerd runtime prefs | 22 | 07-22 | L1 |
| `gui/app.py` | Tkinter GUI — **largest file in the repo** | 2346 | 07-31 | **L1** |
| `gui/settings.py` | settings screen + Advanced section | 398 | 07-31 | L1 |
| `gui/i18n.py` | fr/en string table | 166 | 07-28 | L1 |
| `gui/input.py` | `Action` enum, `dispatch()`, nav ring | 113 | 07-28 | L1 |
| `gui/keyboards.py` | Emmanuelle phoneme keyboard | 103 | 07-23 | L1 |
| `gui/theme.py` | colour tables | 69 | 07-24 | L1 |
| `power/daemon.py` | powerd main | 115 | 07-21 | L1 |
| `power/fsm.py` | ACTIVE→DIM→DARK→DEEP | 138 | 07-22 | L1 |
| `power/config.py` | user_prefs load/save, SIGHUP | 302 | 07-24 | L1 |
| `power/client.py` | GUI-side powerd client (no-op degrade) | 228 | 07-21 | L1 |
| `power/ipc.py` | unix-socket protocol | 166 | 07-21 | L1 |
| `power/inputs.py` | evdev activity/switches | 121 | 07-21 | L1 |
| `power/backlight.py` | sysfs backlight | 94 | 07-21 | L1 |
| `power/amp.py` | amplifier SD line (gpiozero) | 71 | 07-21 | L1 |
| `power/battery.py` | FIT0992 UPS HAT over I2C | 52 | 07-21 | L1 |
| `synthesis/registry.py` | `BACKEND` proxy, `activate_tts_backend()` | 63 | 07-23 | **L1** |
| `synthesis/base.py` | ABCs + dataclasses | 125 | 07-24 | **DEAD** (§7.1) |
| `synthesis/audio_postprocess.py` | normalise + limiter + report | 463 | 07-20 | L1 (analysis parts →L3?) |
| `synthesis/subtitles.py` | `.vtt` + duration alignment writers | 103 | 07-20 | L1 |
| `…/fastspeech2_hifigan/backend.py` | FS2+HiFi-GAN(+Waveglow) backend | 471 | 07-24 | **L1** ⚠ imports L3 |
| `…/fastspeech2_hifigan/text_pipeline.py` | tag parsing, pronunciation rules | 225 | 07-20 | L1 |
| `…/fastspeech2_hifigan/rules/*.csv` | 3 regex rule files | 123 | 07-20 | L1 |
| `…/piper/backend.py` | `PiperBackend` | 226 | 07-24 | **L1** ⚠ imports L3 |
| `…/piper/text_frontend.py` | Piper text cleanup + `<SPEAKER=>` | 116 | 07-29 | L1 |
| `…/piper/README.md` | provenance/licence/sha256 | 83 | 07-24 | L1 |

### 2.3 `tools/` — research tooling (all L3)

| Path | Purpose | LOC | Last | Layer |
|---|---|---|---|---|
| `monitoring/profiling/__init__.py` | session/recorder public API | 300 | 07-20 | **L3** ⚠ imported by L1 |
| `monitoring/profiling/sampler.py` | background PMIC/CPU/thermal sampler | 397 | 07-20 | L3 |
| `monitoring/profiling/recorder.py` | per-sentence timing record | 131 | 07-23 | L3 |
| `monitoring/profiling/parsing.py` | sysfs/vcgencmd parsers | 199 | 07-20 | L3 |
| `monitoring/profiling/join.py` | offline join → results CSVs | 395 | 07-23 | L3 |
| `monitoring/profiling/calibrate.py` | PMIC calibration factor | 64 | 07-20 | L3 |
| `measurement/benchmark/runner.py` | 10-sentence benchmark runner | 56 | 07-20 | L3 |
| `measurement/benchmark/p4_sweep.py` | cadence sweep, P_use(N) fit | 527 | 07-20 | L3 |
| `measurement/benchmark/export_to_xlsx.py` | paste-ready Excel export | 322 | 07-23 | L3 |
| `measurement/benchmark/compare_runs.py` | cross-run comparison | 312 | 07-24 | L3 |
| `measurement/benchmark/sentences_fr.jsonl` | fixed benchmark set | 10 | 07-20 | L3 |
| `measurement/pmic_calibrate.py` | guided PMIC→meter wizard | 246 | 07-20 | **UNCLEAR** (§7.3) |
| `{tools,measurement,monitoring,benchmark}/__init__.py` | empty | 0 | 07-20 | L3 |

### 2.4 `tests/` — all L3

303 test functions across 24 files. Full breakdown in §8.

### 2.5 Deployment & scripts

| Path | Purpose | LOC | Last | Layer |
|---|---|---|---|---|
| `scripts/setup_pi.sh` | Pi provisioning | 380 | 07-31 | **L1** |
| `scripts/kiosk_finalize.sh` | opt-in kiosk hardening | 195 | 07-31 | **L1** |
| `scripts/fetch_piper_voices.sh` | Piper voice download + sha256 | 67 | 07-31 | **L1** |
| `deploy/xorg-kiosk/*` (4 files) | current kiosk mechanism | 99 | 07-31 | **L1** |
| `deploy/systemd/chatterbox-powerd.service` | powerd unit | 32 | 07-31 | **L1** |
| `deploy/systemd/chatterbox-gui.service` | cage/Wayland GUI unit | 43 | 07-31 | **DEAD** (§7.4) |

### 2.6 Docs & assets

| Path | Purpose | LOC/size | Last | Layer |
|---|---|---|---|---|
| `docs/context/ARCHITECTURE.md` | architecture ref (stale on paths) | 466 | 07-31 | L3 |
| `docs/context/CHANGELOG.md` | development log | **3806** | 07-31 | **L3** |
| `docs/context/PIPER_INTEGRATION_SUMMARY.md` | Piper write-up | 178 | 07-24 | L3 |
| `docs/gui/GUI.md` | GUI design + manual smoke tests | 144 | 07-22 | L3 |
| `docs/gui/INTERCHANGEABLE_BACKENDS.md` | contract write-up | 471 | 07-24 | L3 |
| `docs/kiosk/KIOSK.md` | kiosk mechanism | 105 | 07-31 | **L1** |
| `docs/power/POWERD.md` | powerd doc | 102 | 07-21 | **L1** |
| `docs/REORG_PROPOSAL.md` | previous reorg plan | 843 | 07-20 | L3 (historical) |
| `docs/REORG_VERIFICATION.md` | its verification record | 131 | 07-20 | L3 (historical) |
| `docs/assets/tts_gui.png` | README screenshot | — | 07-20 | L1 |
| `assets/audio/prompts/Emmanuelle/*.wav` (29) | keyboard key audio | ~1 MB | — | **L1** |
| `assets/audio/reference/*.wav` (5) | reference recordings | 6.3 MB | — | **L3** ⚠ §9.4 |
| `assets/models/FastSpeech2/**` | vendored FS2 (MIT) | ~35 py | — | **L1** |
| `assets/models/hifi-gan-master/**` | vendored HiFi-GAN (MIT) | ~10 py | — | **L1** |
| `assets/models/Waveglow/**` | vendored Waveglow+tacotron2 (BSD-3) | ~30 py | — | **DEAD-but-load-bearing** (§7.2) |
| `hardware/.gitkeep` | placeholder | 0 | 07-20 | **L2** (empty layer) |
| `profile/**` (~180 files) | committed run data | ~40 MB | — | **L3** ⚠ §10.3 |

---

## 3. Entry points

Every way a human or machine starts this software.

| # | Entry point | Invocation | Layer |
|---|---|---|---|
| 1 | CLI / free-text | `python3 do_tts.py` | L1 |
| 2 | GUI | `python3 do_tts.py --gui` | L1 |
| 3 | Benchmark | `python3 do_tts.py --benchmark [--play --repeats N --join --export-xlsx]` | L3 via L1 |
| 4 | P4 sweep | `python3 do_tts.py --p4-sweep --cadences … --duration …` | L3 via L1 |
| 5 | Wav report | `python3 do_tts.py --report-wav PATH` (exits before loading models) | L1/L3 |
| 6 | Power daemon | `python3 -m chatterbox.power.daemon` | L1 |
| 7 | powerd unit | `systemd: chatterbox-powerd.service` | L1 |
| 8 | GUI unit (legacy) | `systemd: chatterbox-gui.service` (cage) — **not installed** | DEAD |
| 9 | Kiosk autostart | `agetty --autologin` → `~/.bash_profile` → `~/.xinitrc` → `startx` | L1 |
| 10 | Pi provisioning | `./scripts/setup_pi.sh` | L1 |
| 11 | Kiosk finalize | `./scripts/kiosk_finalize.sh` (opt-in, post-bring-up) | L1 |
| 12 | Piper voices | `./scripts/fetch_piper_voices.sh` | L1 |
| 13 | Profiling join | `python -m tools.monitoring.profiling.join` | L3 |
| 14 | PMIC calibrate | `python -m tools.monitoring.profiling.calibrate` | L3 |
| 15 | Sampler (direct) | `python -m tools.monitoring.profiling.sampler` | L3 |
| 16 | Excel export | `python -m tools.measurement.benchmark.export_to_xlsx` | L3 |
| 17 | Run comparison | `python -m tools.measurement.benchmark.compare_runs` | L3 |
| 18 | PMIC wizard | `python3 tools/measurement/pmic_calibrate.py` | L3 |
| 19 | Tests | `.venv/Scripts/python.exe -m pytest tests/` | L3 |

There is **no** `pyproject.toml`, `setup.py`, `setup.cfg`, `Makefile`, `tox.ini`, or CI configuration
(`.github/`, `.gitlab-ci.yml`) anywhere in the repository. Entry points 1–5 are reachable only by
running `do_tts.py` from the repository root (§6.3); there are no installed console scripts.

---

## 4. Import graph

### 4.1 L1-internal structure

```
do_tts.py
  └── chatterbox.cli
        ├── chatterbox.synthesis.registry ──┬── …backends.fastspeech2_hifigan.backend
        │                                   │        └── chatterbox.config.paths
        │                                   │        └── …fastspeech2_hifigan.text_pipeline
        │                                   └── …backends.piper.backend
        │                                            └── …piper.text_frontend
        ├── chatterbox.state
        ├── chatterbox.audio.playback ── chatterbox.power.client
        ├── chatterbox.synth ──┬── chatterbox.audio.denoise
        │                      ├── chatterbox.audio.playback
        │                      ├── chatterbox.synthesis.registry
        │                      └── chatterbox.synthesis.subtitles
        └── chatterbox.gui.app ──┬── chatterbox.cli          ← CIRCULAR (see below)
                                 ├── chatterbox.synth
                                 ├── chatterbox.gui.{keyboards,input,settings,i18n,theme}
                                 └── chatterbox.power.battery
```

Two structural issues inside L1 itself:

- **Circular import.** `chatterbox/cli.py:22` imports `chatterbox.gui.app`; `chatterbox/gui/app.py:39`
  imports `chatterbox.cli`. It resolves today only because attribute access is deferred to call time.
- **Tkinter is a hard dependency of every mode.** `cli.py:22` imports `chatterbox.gui.app`
  unconditionally, and `gui/app.py:18-20` imports `tkinter` at module scope. A headless install
  cannot run `--benchmark` or free-text mode without Tk present.

### 4.2 L1 → L3 violations (the invariant)

**Every one of these is a violation of "L1 must never import L3".**

| # | File:line | Statement | Scope |
|---|---|---|---|
| V1 | `chatterbox/synth.py:31` | `import tools.monitoring.profiling as profiling` | **module** |
| V2 | `chatterbox/cli.py:25` | `import tools.monitoring.profiling as profiling` | **module** |
| V3 | `chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py:25` | `import tools.monitoring.profiling as profiling` | **module** |
| V4 | `chatterbox/synthesis/backends/piper/backend.py:22` | `import tools.monitoring.profiling as profiling` | **module** |
| V5 | `chatterbox/cli.py:249` | `import tools.measurement.benchmark.p4_sweep` | function, mode-gated |
| V6 | `chatterbox/cli.py:333` | `import tools.measurement.benchmark.runner` | function, mode-gated |
| V7 | `chatterbox/cli.py:387` | `from tools.monitoring.profiling.join import run_join` | function, mode-gated |
| V8 | `chatterbox/cli.py:396` | `from tools.measurement.benchmark.export_to_xlsx import export` | function, mode-gated |

V1–V4 are the blocking ones: they are unconditional, module-scope, and V1/V3/V4 sit on the core
synthesis path. V5–V8 are inside `if args.<mode>:` branches and only fire in L3 modes.

**L3 → L1 (permitted, and present):**

| File:line | Statement |
|---|---|
| `tools/measurement/benchmark/runner.py:17` | `import chatterbox.cli as cli` |
| `tools/measurement/benchmark/p4_sweep.py:28` | `import chatterbox.cli as cli` |
| `tools/monitoring/profiling/__init__.py:30` | `import chatterbox.config.paths as paths` |

The last one closes a **mutual import cycle across the layer boundary**: `chatterbox.synth` →
`tools.monitoring.profiling` → `chatterbox.config.paths`.

### 4.3 Empirical verification

A read-only simulation installed a `sys.meta_path` finder that raises `ImportError` for `tools` and
`tools.*`, then attempted to import L1's core modules:

```
BROKEN    chatterbox.synth                              -> ImportError: L3 package 'tools' removed
BROKEN    chatterbox.cli                                -> ImportError: L3 package 'tools' removed
BROKEN    chatterbox.synthesis.registry                 -> ImportError: L3 package 'tools' removed
BROKEN    chatterbox.synthesis.backends.piper.backend   -> ImportError: L3 package 'tools' removed
```

**Conclusion:** the target invariant is currently violated at the strongest possible level. Deleting
`research/`+`tests/` from a checkout today does not leave a working demonstrator — it leaves one that
cannot import. The stated goal is not a tidy-up; it is a dependency inversion.

### 4.4 The API surface to be inverted

The coupling is narrow, which is the good news. L1 uses exactly nine module functions and three
recorder methods:

```
profiling.enable()              profiling.set_output_dir(path)
profiling.start_session(...)    profiling.stop_session()
profiling.get_run_dir()         profiling.begin_sentence(text, complexity_tag=, sentence_id=)
profiling.set_current(rec)      profiling.current()
                                (start_session_at appears in an L1 comment only; real callers are L3)

rec.set(**kwargs)               rec.stage(name)  # context manager      rec.finalize()
```

---

## 5. The backend contract as it exists in code

### 5.1 `base.py` is aspirational, not operative — **DEAD**

`chatterbox/synthesis/base.py` defines `SynthesisRequest`, `SynthesisResult`, `Synthesizer(ABC)`
and `VocoderBackend(ABC)`. A repository-wide search for those four names returns **only docstring and
comment mentions**. Specifically:

- No class anywhere subclasses `Synthesizer` or `VocoderBackend`.
  `FastSpeech2HifiGanBackend` and `PiperBackend` are plain classes.
- `SynthesisRequest` and `SynthesisResult` are **never constructed, imported or returned** anywhere.
- **No module imports `chatterbox.synthesis.base` at all.**

`base.py:14-22` is candid that FS2 conforms "in spirit … rather than via literal Python inheritance",
but the practical effect is that the file constrains nothing. Removing it would change no behaviour.

**Discrepancy with `CLAUDE.md`.** `CLAUDE.md`'s "Interchangeable backends" section states:
`SynthesisResult.wav_path (set) vs. mel_path (set) is how a backend signals "already a finished wav"
vs. "still needs vocoding"`. This is **not what the code does**. `chatterbox/synth.py:88` reads the
static YAML flag `needs_vocoder`; `SynthesisResult` plays no part.

### 5.2 The contract that is actually enforced

A backend must satisfy the following, none of which is checked by any interface:

| Requirement | Where consumed | Enforcement |
|---|---|---|
| `tts(text, tts_config, gui_control, linking_utt)` → `(output_dir, processed_text)` tuple | `synth.py:130`, `synth.py:179` | **convention only** — positional tuple unpack |
| the returned path must be a **directory**, not a file prefix | `synth.py:203` builds `<dir>/audio_file` | **convention only**; violating it produced a live `FileNotFoundError` (documented in `piper/backend.py:126-139`) |
| a method named by `load_script` accepting `(model_config, device)` | `cli.py:300`, `gui/app.py:1249,1755` | `getattr` → `AttributeError` at runtime |
| `describe_controls()` → dict per `base.py:64-109` | `gui/app.py:gui_generic_controls()` | **convention only** |
| `vocoder(location_mel_file, vocoder_config)` → wav base path | `synth.py:200` | only if `needs_vocoder` |
| writes `<dir>/audio_file.wav` | `synth.py:208` | **convention only** |
| writes `<dir>/audio_file_duration.npy` | `synth.py:133,182` | gated by `supports_subtitles` |
| writes `<dir>/audio_file.WAVEGLOW` + `.AU` | `synth.py:145-177` | **ungated** in the `\|` branch (§5.4) |

The three capability flags are read **from `config_tts.yaml`, not from the backend object**:

| Flag | Read at | Default | Effect |
|---|---|---|---|
| `needs_vocoder` | `synth.py:88`, `cli.py:316`, `gui/app.py` | `True` | skip vocoder load + call; hide Vocodeur picker |
| `supports_subtitles` | `synth.py:107` | `True` | skip subtitle writing |
| `accepts_phoneme_input` | `gui/app.py` | `True` | drives `GUI_config.phoneme_fallback` |

Because they live in YAML, **a backend cannot declare its own capabilities**; a user editing
`config_tts.yaml` can assert a false one and crash the run. There is no validation step.

### 5.3 Where a third backend breaks

1. **`registry.py:33-36` hardcodes the backend table.** Adding a backend requires editing L1 source.
   The docstring's "config-driven" applies to *method names*, not to backend registration.
2. **`_BackendProxy.__getattr__` (registry.py:51-58) silently mis-dispatches.** If the requested name
   is absent on the active backend, it returns the first match found by iterating
   `_BACKENDS_BY_NAME.values()` — dict insertion order. A third backend sharing a helper name with
   FS2 but not defining it itself gets FS2's implementation, with no warning.
3. **`activate_tts_backend()` raises a bare `KeyError`** on an unknown `backend:` value.
4. **`gui_script` does not resolve through the registry at all.** `gui/app.py:1263,1786` uses
   `globals()[tts_model["gui_script"]]` — the name must exist as a module-level function *in
   `gui/app.py`*. A backend shipping its own GUI function cannot be referenced from config.
   This contradicts `registry.py:61`, which lists `gui_script` among names resolved via the proxy.
5. **`syn_script` is FS2-internal.** `FastSpeech2HifiGanBackend.tts()` self-dispatches on it
   (`backend.py:170,190`). `PiperBackend.tts()` ignores it entirely — and there is **no `syn_piper`
   method**, so `syn_script: "syn_piper"` on both Piper entries in `config_tts.yaml:212,250` is dead
   configuration that would raise `AttributeError` if anything ever resolved it.
6. **Waveglow is imported unconditionally** (`backend.py:38-40`), so a third backend inherits that
   import cost and dependency even though Waveglow is unreachable (§7.2).

### 5.4 Known unfixed gap

`synth.py:138-144` documents it in place: the `|` multi-utterance branch concatenates mel/`.AU` data
in FastSpeech 2's binary format **unconditionally** — not gated by `needs_vocoder` or
`supports_subtitles`. A Piper user typing `|` in free text hits `FileNotFoundError`. Confirmed by
reading the branch; the guard at line 119 is `first_end_of_utt > 1` only.

---

## 6. Configuration, paths and machine-specific assumptions

### 6.1 Configuration files

| File | Consumer | Reload |
|---|---|---|
| `chatterbox/config/config_tts.yaml` | `cli.py:257` (`--config`, default **relative**) | startup only |
| `chatterbox/config/user_prefs.yaml` | `power/config.py` via `paths.USER_PREFS_PATH` | SIGHUP |
| `assets/models/FastSpeech2/config/ALL_corpus/{preprocess,model,train}.yaml` | `backend.py:117-125` | startup |
| `assets/models/hifi-gan-master/FR_V2/config.json` | `backend.py:141` | startup |
| `assets/models/Piper/*.onnx.json` | `PiperVoice.load` | per voice load |
| `requirements-pi-lock.txt` | `setup_pi.sh:28` | **file does not exist** |

`config_tts.yaml` mixes layers: `profiling:` (lines 75-84) is pure L3 configuration living in the L1
config file.

### 6.2 Environment variables

| Variable | Read at | Effect |
|---|---|---|
| `CHATTERBOX_PROFILE` | `cli.py:274` | `=1` enables profiling (L3 switch in L1 code) |
| `SUDO_USER`, `USER`, `HOME` | `setup_pi.sh:27,262,301` | install user/venv location |

No secrets, tokens, API keys or credentials were found in the tree or in git history.

### 6.3 Hardcoded paths and machine assumptions — **release blockers**

| # | Location | Value | Impact |
|---|---|---|---|
| **B1** | `deploy/systemd/chatterbox-powerd.service:16,17` | `/home/chatterbox/chatterbox`, `…/venv/bin/python3` | Unit fails on any other user/location. Documented in `INSTALL.md:99-106` as a manual edit. |
| **B2** | `deploy/systemd/chatterbox-gui.service:36,38` | same + `/usr/bin/cage` | Same, plus references the ruled-out compositor. |
| **B3** | `cli.py:94` | `--config` default `"chatterbox/config/config_tts.yaml"` | **relative** — running from any other cwd fails. |
| **B4** | `backend.py:113,118,121,124,137,141,148` | `os.path.join(tts_model["folder"], …)` with `folder: "assets/models/FastSpeech2"` | **relative** — model/weight loading is cwd-dependent. `paths.py` anchors `sys.path` but **not** data loading. Phase 0 anchoring is incomplete. |
| **B5** | `synth.py:254` | `shutil.copy(path_au, "./")` | Writes `audio_file.AU` into the **current working directory** on every synthesis. |
| **B6** | `synth.py` / `playback.py` | `audio_file.wav`, `audio_file.fr.vtt`, `audio_file_duration_alignment.json` | Synthesis output lands in the **repository root** (all four are gitignored, §1.2). |
| **B7** | `config_tts.yaml:146-148` | `"config/ALL_corpus/preprocess.yaml"` | Ties the config to one corpus layout; `backend.py:76-84` exists solely to rewrite stale `FastSpeech2/` prefixes at runtime. |
| **B8** | `profiling` config | `core: 3`, `i2c-1 @ 0x40`, `0x36`, `vcgencmd` | Pi-5-specific; degrade safely but are undeclared assumptions. |
| **B9** | `user_prefs.yaml` / `INSTALL.md:107-112` | `amp.sd_pin`, `amp.enable_active_high`, `display.backlight` | Board-wiring-specific; wrong values fail **silently** (log + disable). |

No IP addresses, hostnames or usernames beyond `chatterbox` appear in tracked source. `ssh pi5`
appears only in `docs/context/CHANGELOG.md` prose (a developer-machine SSH alias).

---

## 7. Dead and orphaned code

Listed with evidence. Nothing was deleted.

### 7.1 `chatterbox/synthesis/base.py` (125 lines) — DEAD
Evidence: repository-wide search for `Synthesizer|VocoderBackend|SynthesisRequest|SynthesisResult`
returns only docstrings/comments; no module imports `chatterbox.synthesis.base`. See §5.1.

### 7.2 Waveglow — DEAD BY CONFIG, LOAD-BEARING BY IMPORT
- `config_tts.yaml:280-294`: the `Waveglow NEB` vocoder entry is **commented out** → unreachable.
- `backend.py:157` `load_waveglow()` and `backend.py:377` `syn_waveglow()` have no reachable caller.
- `assets/models/Waveglow/` vendors ~30 files including a **complete copy of NVIDIA tacotron2**
  (`train.py`, `logger.py`, `loss_scaler.py`, `data_utils.py`, `Dockerfile`, `inference.ipynb` — all
  training-only).
- **But** `backend.py:38-40` runs `sys.path.insert(WAVEGLOW_DIR)`, `sys.path.insert(WAVEGLOW_DIR/tacotron2)`
  and `from inference import main as inference_main` **at module import time**. Deleting the
  vendored tree breaks the FS2 backend import.

So Waveglow is simultaneously unreachable and undeletable. Untangling it is a code change, not a move.

### 7.3 `tools/measurement/pmic_calibrate.py` (246 lines) — UNCLEAR
No importer; not referenced by `cli.py`. Overlaps in purpose with
`tools/monitoring/profiling/calibrate.py` (64 lines), which *is* referenced from `join.py:19,34` and
`parsing.py:150`. Possibly superseded, possibly a distinct interactive wizard. **Needs your answer.**

### 7.4 `deploy/systemd/chatterbox-gui.service` — DEAD (deliberately retained)
`INSTALL.md:93-97` and `deploy/xorg-kiosk/README.md` record that cage/wlroots was ruled out by a
reproducible `libwlroots` SIGSEGV; `setup_pi.sh` step 9 installs the Xorg mechanism instead. Retained
as documentation of a rejected approach.

### 7.5 Dead configuration keys
- `syn_script: "syn_piper"` — `config_tts.yaml:212,250`. No such method exists (§5.3 #5).
- `gst_token_list: {}` on both Piper entries — Piper has no style dimension.
- `GUI_config.main_panel.control_width/control_height/input_width` — no consumer found in `gui/app.py`.

### 7.6 Orphaned files
- `audio_keyboards/` — untracked empty directory at the repo root, superseded by
  `assets/audio/prompts/` (`paths.py:26-28` records the move).
- `hardware/.gitkeep` — placeholder; **the entire L2 layer is empty**.
- `profile/.gitkeep` — alongside ~180 committed data files (§10.3).

### 7.7 Windows-only dead code
`requirements-pi.txt:20-22` states `simpleaudio`/`sounddevice` are imported only under
`if platform.system() == "Windows":` in `audio_utils.py` and `gui_utils.py` — **both of those files no
longer exist** (Phase 3 renamed them). The comment is stale; `simpleaudio==1.0.4` is still pinned in
`requirements-dev.txt:43`.

---

## 8. Test suite shape

**303 test functions across 24 files.** Reported sceptically, per your instruction.

### 8.1 Distribution by layer

| Area | Files | Tests | Share |
|---|---|---|---|
| **L3 research tooling** (`profiling`, `p4_sweep`, `export_xlsx`, `compare_runs`, `benchmark`) | 5 | **127** | **42 %** |
| **L1 power daemon** | 6 | 77 | 25 % |
| **L1 GUI** | 6 | 48 | 16 % |
| **L1 synthesis + audio** | 7 | 51 | 17 % |

Nearly half the suite tests code that is not required to make the device speak.

### 8.2 The core runtime path is effectively untested

`chatterbox/synth.py` is 282 lines and is the entire compute path. `tests/test_synth.py` has 5 tests.
Reading them:

- `test_synthesize_returns_none_for_empty_string` / `…whitespace_only` — genuine, but exercise only
  the guard at `synth.py:72-74`.
- `test_audio_result_field_shape`, `test_audio_result_gst_weights_defaults_to_none`,
  `test_audio_result_stage_durations_omits_vocoder_for_monolithic_backend` — **all three construct an
  `AudioResult` by hand and assert on the object they just built. None calls `synthesize()`.**

The third is worth quoting, because it is precisely the failure mode you warned about. Its comment
says it verifies that `synthesize()` "only adds `vocoder` to `stage_durations` when the active TTS
model's `needs_vocoder` flag is true". What it does (`test_synth.py:47-49`) is build
`{"tts": 0.5, "denoiser": 0.1}` and assert `"vocoder" not in` it. **It is a tautology.** It would pass
unchanged if `synth.py` were deleted.

**No test executes any code in `synth.py` past line 74.**

### 8.3 Modules with no dedicated test file

`chatterbox/cli.py` (397) · `chatterbox/gui/app.py` (**2346 — the largest file in the repo**) ·
`chatterbox/audio/playback.py` (160) · `chatterbox/audio/denoise.py` (24) ·
`chatterbox/synthesis/subtitles.py` (103) · `chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py` (471) ·
`…/text_pipeline.py` (225) · `…/piper/text_frontend.py` (116) · `chatterbox/config/paths.py` (32) ·
`chatterbox/state.py` (14)

`gui/app.py` is touched indirectly by `test_gui_{worker,input,settings,letter_layout}.py` via injected
fakes, but its 2346 lines of layout/reflow/menu logic are not covered.

### 8.4 Structural caveats

- `tests/conftest.py` is 5 lines: it prepends the repo root to `sys.path`. The suite therefore tests
  a **source checkout, never an installed package** — it cannot detect packaging or path-anchoring
  regressions (B3/B4), which is exactly the class of bug the reorganisation risks introducing.
- Every synthesis-touching test monkeypatches `synth.synthesize` or the backend, by design (no
  weights in CI). The real pipeline is covered only by the manual smoke tests in `docs/gui/GUI.md`.
- `test_power_ipc.py`'s live-socket test is `skipif`'d on Windows — the audit platform.

**Assessment:** green pytest tells you the research tooling and the powerd FSM still work. It tells
you almost nothing about whether the device still speaks. Every reorganisation step needs a real
run-level verification.

---

## 9. Licence and redistribution inventory

### 9.1 The repository itself

**There is no `LICENSE`, `COPYING` or `NOTICE` file at the repository root, and no licence header in
any first-party source file.** The only licence files present belong to vendored third parties. As it
stands the repository is "all rights reserved" by default and cannot be published as open source.
No copyright holder is declared — and given `git log` shows two authors across two institutions
(§10.4), authorship is a question you must answer, not one the repository answers.

### 9.2 Vendored code (redistributable)

| Component | Licence | Status |
|---|---|---|
| `assets/models/FastSpeech2/` | **MIT** (© 2020 Chung-Ming Chien) | OK — licence file retained |
| `assets/models/hifi-gan-master/` | **MIT** (© 2020 Jungil Kong) | OK — licence file retained |
| `assets/models/Waveglow/` | **BSD-3-Clause** (© 2018 NVIDIA) | OK, but see §7.2 |
| `assets/models/Waveglow/tacotron2/` | **BSD-3-Clause** (© 2018 NVIDIA) | OK |
| `assets/models/Waveglow/tacotron2/text/` | **MIT** (© 2017 Keith Ito) | OK |

All three are permissive and compatible with an MIT/BSD/Apache release of Chatterbox.

### 9.3 `piper-tts` — GPL question answered

`piper-tts==1.5.0` is the **OHF-voice/piper1-gpl** fork, **GPL-3.0-or-later**
(`chatterbox/synthesis/backends/piper/README.md:5-10`).

**Verified: nothing from it is vendored into this repository.** No `piper` source is present;
`chatterbox/synthesis/backends/piper/backend.py` imports it lazily inside methods
(`backend.py:42,52,140`), and it is deliberately absent from `requirements-pi.txt` — the user installs
it themselves.

**Consequence:** Chatterbox is *not* forced to GPL. It may carry a permissive licence. The Piper
backend is an optional adapter against a GPL library the user installs; you should state this
explicitly in the release licence notes, and keep `piper-tts` out of every dependency list and extra.

### 9.4 Model weights and audio — **the real blockers**

| Asset | Distributed how | Licence | Verdict |
|---|---|---|---|
| **FastSpeech 2 FR checkpoint `390000`** (voices NEB, AD, IZ, RO, DG) | Google Drive link, `README.md:41` | **UNKNOWN** | **BLOCKER.** The core asset. Trained on a French corpus; no licence, no corpus attribution, no speaker-consent statement anywhere in the repo. |
| **HiFi-GAN `FR_V2/g_00570000`** | Google Drive, `README.md:43` | **UNKNOWN** | **BLOCKER.** Fine-tuned FR weights, provenance unstated. |
| **FlauBERT large cased** | Google Drive, `README.md:42` | **UNKNOWN as distributed** | Upstream FlauBERT is MIT, but this is a re-hosted copy behind a personal Drive link. Verify it is unmodified, then link upstream. |
| **Waveglow `waveglow_NEB.pt`** | Google Drive, `README.md:44` | **UNKNOWN** | Unreachable via config (§7.2); simplest fix is to drop it. |
| **`assets/audio/reference/*.wav`** (5 files, 6.3 MB, **committed**) | in git | **UNKNOWN** | **BLOCKER.** Filenames (`La_bise_Neutre_NEB.wav`, `la_bise_NORMAL_AD.wav`) key to speaker initials — these are recordings of identifiable people. Publishing without a consent/licence statement is both a licensing and a personal-data issue. |
| **`assets/audio/prompts/Emmanuelle/*.wav`** (29, **committed**) | in git | **UNKNOWN** | Phoneme key audio, apparently one named speaker ("Emmanuelle"). Same question, smaller scope. Required at runtime. |
| **Piper voices** (siwis, upmc, lessac) | downloaded, gitignored | claimed CC0-adjacent, **unverified** | Not redistributed by you (good). `piper/README.md:22-23` defers to the dataset page rather than stating a per-voice licence. siwis/upmc/lessac derive from datasets with **differing** terms — verify each. |
| **`assets/models/FastSpeech2/lexicon/*`** (3 files, 5.4 MB) | in git | UNKNOWN | librispeech/mailabs/pinyin lexicons — English/Chinese, unused by the French pipeline. Inherited from upstream FS2. |
| **`assets/models/FastSpeech2/img/*`, `Waveglow/waveglow_logo.png`, `tacotron2/tensorboard.png`** | in git | upstream repo figures | Covered by the respective MIT/BSD licences. |

### 9.5 Python dependencies

All runtime dependencies in `requirements-pi.txt` are permissive (BSD/MIT/Apache-2.0): torch, PyYAML,
numpy, scipy, matplotlib, transformers, noisereduce, librosa, pydub, unidecode, inflect, regex,
g2p_en, pypinyin, sacremoses, smbus2, gpiozero, lgpio, evdev, openpyxl. `unicode>=2.9` (line 26) is a
long-abandoned PyPI package with unclear licensing and no obvious consumer — worth removing.
Two runtime deps are **LGPL-adjacent via system packages**, not Python: `ffmpeg` (pydub's playback
backend, `apt-packages-pi.txt`) and `espeak-ng` data bundled inside the `piper-tts` wheel.

---

## 10. Repository hygiene for public release

### 10.1 Broken submodule — **blocker**
`assets/models/flaubert/flaubert_large_cased` is recorded as a **gitlink, mode `160000`**, commit
`a5fdc16154e92c75d7adde577e183793ad19d040`. There is **no `.gitmodules` file**:

```
$ git submodule status
fatal: no submodule mapping found in .gitmodules for path
       'assets/models/flaubert/flaubert_large_cased'
```

A fresh clone yields an empty directory and any `git submodule` command errors. The local checkout
has real content (1.49 GB `pytorch_model.bin` + tokenizer files) that git is not tracking. Every
public clone will hit this on the first FlauBERT-enabled synthesis.

### 10.2 Dangling document references — **blocker for docs**
Six documents are cited repeatedly in code docstrings and in `docs/`, and **none exists in the
repository or on disk**:

`chatterbox_gui_spec_v0.1.md` · `chatterbox-powerd_spec_v0.1.md` ·
`Bring-up_Integration_Test_Protocol_v0.1.md` · `cc_prompt_gui_refactor.md` ·
`cc_prompt_gui_landscape_v2.md` · `cc_prompt_piper_backend.md`

They are load-bearing: `INSTALL.md:112` sends the installer to
`Bring-up_Integration_Test_Protocol_v0.1.md`'s T0–T7 as the procedure that catches silent hardware
failures (B9). A reader of the published repository cannot follow the install instructions.

### 10.3 Committed research data — ~40 MB
`profile/` contains roughly **180 committed files** across 13 run directories (`P4 - First Full try/`,
`Step 7B - 2/`, `Step 7C - ondemand 257mWh/`, …): `per_sample.csv`, `per_sentence.jsonl`,
`per_stage_results.csv`, `meta.json`, **`sampler.pid`**, and **`.xlsx` binaries**.

The `.gitignore` rules meant to prevent this (`profile/*.csv`, `profile/*.jsonl`,
`profile/sampler.pid`, `profile/exports/`) match **only the top level of `profile/`**, never
`profile/<run>/…`. The intent was right; the patterns are one level short. Stale `sampler.pid` files
and paste-ready spreadsheets are committed artefacts, not sources.

Directory names contain spaces, which complicates scripting and tooling.

### 10.4 Personal and lab-internal information in history
`git log` (125 commits, 2023-06-14 → 2026-07-31) shows four author identities for two people:

```
Evrard Raphaël <Raphael.Evrard@grenoble-inp.org>
Martin Lenglet <lengletm@laptop-295.gipsa-lab.grenoble-inp.fr>   ← internal hostname
Martin Lenglet <martinlenglet@gmail.com>
MartinLenglet   <martinlenglet@gmail.com>
```

`lengletm@laptop-295.gipsa-lab.grenoble-inp.fr` leaks a lab-internal machine name. Two personal
addresses appear throughout. Removing these requires history rewriting; the alternative is accepting
them. This is your call, and Martin Lenglet's — not one to decide silently.

### 10.5 Large blobs in history
Largest tracked blobs, all legitimate content rather than accidents:

```
5.37 MB  assets/models/FastSpeech2/lexicon/librispeech-lexicon.txt
1.33 MB  assets/audio/reference/La_Bise_Neutre_NEB_opti.wav   (×5 reference wavs)
~1.1 MB  profile/P4 …/per_sample.csv                          (×many)
```

No model weights were ever committed. **No secrets, tokens, keys or credentials were found** in the
tree or in history.

### 10.6 Files that should be gitignored and are not
- `profile/**/*.{csv,jsonl,xlsx}`, `profile/**/sampler.pid` (§10.3)
- `.claude/` is ignored locally but the pattern is absent from `.gitignore`
- `graphify-out/` is ignored — correct, but it is AI-tooling state worth noting before publication

### 10.7 Missing for a public release
No `LICENSE` · no `pyproject.toml`/`setup.py` · no `CONTRIBUTING.md` · no `CODE_OF_CONDUCT.md` ·
no CI configuration · no `CITATION.cff` (this is lab research output) · no issue/PR templates ·
`README.md` is French-only, with no English entry point · **no `pre-release-audit` tag** —
`git tag -l` is empty, so the rollback anchor referenced in the task brief does not exist yet.

---

## 11. Summary of layer assignment

| Layer | Content | Files (approx.) |
|---|---|---|
| **L1 RUN** | `chatterbox/**` (minus `base.py`), `do_tts.py`, `assets/models/{FastSpeech2,hifi-gan-master,flaubert}`, `assets/audio/prompts/`, `scripts/`, `deploy/xorg-kiosk/`, `deploy/systemd/chatterbox-powerd.service`, `requirements-pi.txt`, `apt-packages-pi.txt`, `README.md`, `INSTALL.md`, `docs/{kiosk,power}/` | ~120 |
| **L2 BUILD** | `hardware/.gitkeep` — **empty; nothing to move** | 1 |
| **L3 STUDY** | `tools/**`, `tests/**`, `profile/**`, `docs/{context,gui}/`, `docs/REORG_*.md`, `assets/audio/reference/`, `requirements-dev.txt` | ~230 |
| **DEAD** | `chatterbox/synthesis/base.py`, `assets/models/Waveglow/**` (load-bearing, §7.2), `deploy/systemd/chatterbox-gui.service`, dead config keys (§7.5), `audio_keyboards/` | ~35 |
| **UNCLEAR** | `tools/measurement/pmic_calibrate.py`, `CLAUDE.md`, `assets/models/FastSpeech2/lexicon/*`, `synthesis/audio_postprocess.py`'s analysis half, `docs/context/ARCHITECTURE.md` | 6 |

Open questions arising from every `UNCLEAR` and `DEAD` row are collected in
`docs/release/REORG_PLAN.md` §9.
