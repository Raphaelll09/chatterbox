# Piper TTS backend — integration & evaluation summary

This document is a narrative summary of the work covered in detail, session-by-session, in
`docs/context/CHANGELOG.md` (search that file for "Piper") and `docs/gui/INTERCHANGEABLE_BACKENDS.md`
§3. Read those two for exact file:line detail; read this one for the overall story and the final
numbers. Written 2026-07-24.

## TL;DR

Piper (fr_FR) is now a real, working second TTS backend alongside FastSpeech2+HiFi-GAN — two
voices selectable today (`siwis`, `upmc`), verified end-to-end on real Pi 5 kiosk hardware,
GUI and CLI both working, FS2 confirmed unaffected throughout. Measured performance, on a
statistically solid (10 sentences × 3 repeats) benchmark: **Piper is ~2x faster and ~2x more
energy-efficient than FS2+HiFi-GAN**, consistently, across both remaining voices. A third voice,
`tom`, was evaluated and dropped for noticeably worse quality and slower inference.

## 1. Why this happened

The GUI/synthesis layer had already been refactored (a separate, earlier body of work — see
`docs/gui/INTERCHANGEABLE_BACKENDS.md` §1-§2) to be backend-agnostic *in theory*: a new TTS engine
should plug in via its own module + a `config_tts.yaml` entry, with zero changes needed to
`chatterbox/gui/app.py` or `chatterbox/synth.py`. That claim had never been tested against a real
second backend. Piper was deliberately chosen to test it — maximally different from FS2 along
every axis that matters: monolithic (no separate vocoder stage) vs. two-stage, ONNX Runtime vs.
PyTorch, an internal espeak-ng phonemizer vs. no G2P step at all, no style/emotion dimension,
per-voice speaker maps instead of a shared `speakers.json`.

## 2. What was built

- **`piper-tts==1.5.0`** (the OHF-voice/piper1-gpl fork, GPL-3.0-or-later — the original MIT
  `rhasspy/piper` is archived). Confirmed live on the Pi 5: installs from a single prebuilt
  aarch64 wheel, no source build, no separate `piper-phonemize`/`espeakng-loader` dependency
  (1.5.0 bundles its own compiled phonemizer). Not vendored or added to `requirements-pi.txt` —
  it's a whole optional *backend* selected by config, installed manually per `INSTALL.md`.
- **`chatterbox/synthesis/backends/piper/`** — `backend.py` (`PiperBackend`), `text_frontend.py`
  (Piper's own tag-parsing/speaker-resolution, deliberately not routed through FS2's text
  pipeline beyond the two genuinely orthographic helpers), `README.md` (voice provenance/licence).
- **Two voices**, both 22050 Hz/16-bit/mono (matching FS2+HiFi-GAN exactly, so the shared
  playback path needs no resampling): `fr_FR-siwis-medium` (default, single-speaker) and
  `fr_FR-upmc-medium` (2 speakers: `jessica`/`pierre`, surfaced as a GUI speaker dropdown).
  Fetched via `scripts/fetch_piper_voices.sh` (sha256-verified, not committed).
- Selectable exactly like FS2: `do_tts.py --default_tts <idx>` on the CLI, or Settings → Advanced
  in the GUI.

## 3. The architectural gap this integration found

`chatterbox/synthesis/registry.py`'s `BACKEND` was a hardcoded singleton
(`FastSpeech2HifiGanBackend()`) — fine for one backend, but unable to resolve `tts()`/
`describe_controls()` (identically named on every backend by design) once a second one existed.
Fixed with a small resolving proxy (`_BackendProxy` + `activate_tts_backend()`), reviewed and
chosen over a self-registering alternative for explicitness. `chatterbox/synth.py` needed **zero**
changes; `cli.py`/`gui/app.py` each got one new line activating the right backend before resolving
`load_script`. Full write-up: `docs/gui/INTERCHANGEABLE_BACKENDS.md` §3.1.

## 4. Real-hardware bugs found and fixed

None of these were caught by the pytest suite, a backend-level smoke test, or a Tk repro script
with mocked backends — every one needed either a real `do_tts.py --benchmark` run, the real GUI on
the physical kiosk screen, or actually listening to/timing the output. In the order they surfaced:

1. **Stale GUI globals.** `gst_token_selection`/`speaker_selection` (`gui/app.py`) were only ever
   *set*, never *reset*, between backend switches — left pointing at FS2's torn-down widgets after
   switching to a style-less Piper voice. Found only by driving a real `tk.Tk()` instance through
   an actual backend switch.
2. **Subtitle-writing assumed FS2-only output.** `chatterbox/synth.py`'s subtitle path
   unconditionally expected FastSpeech2's own `audio_file_duration.npy` — crashed the very first
   real `--benchmark` run against Piper. Fixed with a third static capability flag,
   `supports_subtitles`, alongside `needs_vocoder`/`accepts_phoneme_input`.
3. **`PiperBackend.tts()`'s return value violated the contract it was supposed to follow** —
   returned a file-prefix instead of the directory `synth.py`'s monolithic-backend branch expects,
   crashing every sentence. The unit test written for this at the time asserted the same wrong
   value and passed alongside the bug — only a real run through the unmodified `synth.py` caught
   it.
4. **Profiling subsystem silently dropped Piper's stage data.** `tools/monitoring/profiling/
   recorder.py`'s `Recorder.finalize()` only ever serialized 4 hardcoded FS2 stage names; Piper's
   `"synth"` stage was computed correctly then discarded, no error — a *plausible-looking, silently
   wrong* result, not a crash, found only by opening the CSV directly. Generalized properly
   (`recorder.py`'s new `"stages"` field, `join.py`'s `_stage_windows()`), not just worked around;
   `export_to_xlsx.py` was deliberately left FS2-only (bound to an external spreadsheet template)
   but now refuses a non-FS2 export loudly instead of silently corrupting it.
5. **Main window and Settings dialog both opened off-screen in landscape**, on the real kiosk
   display. `.geometry("WxH")` sizes content only; the window manager draws the title bar
   *outside* that. Main window now tries `-zoomed` (X11 maximize) first, falling back to a
   centered-with-margin geometry; Settings is explicitly positioned near the left edge with a
   title-bar margin, per explicit preference over centering again.
6. **Piper's GUI sliders only had 2 selectable values.** `gui_generic_controls()`'s slider builder
   defaults to `resolution=1` when unset; all three of Piper's sliders omitted it (every FS2
   slider sets it explicitly — a plain oversight). Fixed, with a regression test asserting every
   slider declares a resolution.
7. **"Piper sounds super slow" traced to a labeling problem, not a synthesis bug.** Default
   `length_scale=1.0` (untouched slider) produces audio duration matching FS2 almost exactly; what
   got reported as slow was the slider pushed toward its old max. FS2's own "Vitesse" slider
   already has the same "higher = slower" direction (confirmed in FastSpeech2's own code) — a
   pre-existing ambiguity. Fixed the shared label text, not the values.
8. **`fr_FR-tom-medium` removed.** Real-hardware listening (all 3 voices heard directly on the
   Pi) found it noticeably lower quality and slower than either `siwis` or `upmc`, with no
   offsetting benefit. Removed everywhere: config, fetch script, docs, actual voice files.

## 5. Benchmark tooling built along the way

- **`scripts/fetch_piper_voices.sh`** — sha256-verified voice download, voice count now computed
  dynamically (won't go stale again if the voice list changes).
- **`tools/measurement/benchmark/compare_runs.py`** — side-by-side comparison of two or more
  joined `profile/run_.../` directories. Went through its own real bug-finding cycle:
  - First version compared runs by raw row position — worked, but a **single benchmark pass
    turned out not to be reliable on this hardware at all**: one single-run FS2 measurement came
    out ~2x slower than a later repeated-average; a different single run came out roughly tied
    with Piper. Confirmed root cause: the Pi's CPU frequency governor is `"ondemand"`, not
    `"performance"` — already recorded in every run's `meta.json`, just never surfaced.
  - Rewritten to aggregate by `sentence_id` with mean±std across however many times each sentence
    was repeated (`--repeats N`), to print each run's CPU governor with a loud warning when it
    isn't `"performance"`, and to state explicitly that `total_synth_ms`/`rtf` already cover the
    *whole* pipeline (front_end/acoustic/vocoder/write for FS2, synth/write for Piper — real user
    confusion about whether HiFi-GAN/FlauBERT time was being excluded, when it wasn't).
  - One more real bug, found only by running it against real 10-sentence data: the summary's
    `n_repeats` read whichever sentence happened to be first in file order — almost always `"REF"`,
    which the benchmark deliberately anchors at *both* the start and end of every pass (its own
    drift-check design), giving it double the occurrence count of every other sentence. Fixed to
    use the mode across all sentences instead.

## 6. Final performance results

10-sentence benchmark set, 3 repeats each, both remaining Piper voices vs. FS2 — the numbers to
trust (small, consistent per-sentence std values; CPU governor was `"ondemand"` for all three, so
this is the *conservative*, noisier-than-ideal case — a `"performance"` governor would very likely
tighten the std values further without changing the relative ordering):

| Backend | mean RTF | total synth time | total energy |
|---|---|---|---|
| FS2 (FastSpeech2 + HiFi-GAN) | 0.325 | 11.88 s | 0.0321 Wh |
| Piper `siwis` | 0.153 | 5.79 s | 0.0148 Wh |
| Piper `upmc` | 0.153 | 6.04 s | 0.0157 Wh |

- **`siwis`**: 48.7% of FS2's total synth time, 46.1% of its energy.
- **`upmc`**: 50.8% of FS2's total synth time, 48.9% of its energy.
- `siwis` and `upmc` perform almost identically to each other (mean RTF 0.153 vs 0.153) — the ~2x
  advantage over FS2 is a property of Piper's monolithic architecture (no separate vocoder stage),
  not specific to one voice.

Raw data: `profile/compare_fs2_siwis_upmc.csv` (gitignored, not committed — regenerate with
`tools.measurement.benchmark.compare_runs` against fresh `--repeats 3` runs if needed later).

## 7. Current state

- Two Piper voices selectable in both CLI (`--default_tts 1` = siwis, `--default_tts 2` = upmc)
  and GUI (Settings → Advanced), alongside the original FS2 entry (`--default_tts 0`, no flag
  needed for the GUI's default).
- Test suite grew from 246 (pre-Piper baseline) to 271 passing tests, all green throughout.
- FS2's own behavior confirmed unchanged at every step (byte-identical console output pattern,
  re-verified after every single fix in this arc).

## 8. What's not done / left for later

- **Nothing is committed to git yet.** Every change in this whole arc exists locally and was
  `scp`'d to the Pi for live testing — not `git commit`/`push`. Review the diff and commit when
  ready; `git pull` on the Pi afterward to make it permanent there (currently only the working
  tree, not the Pi's git history, has these changes).
- **CPU governor is warned about, not fixed.** `compare_runs.py` flags `"ondemand"` loudly but
  doesn't change it. If more benchmarking is planned, switching to `"performance"` before a run
  (and restoring it after) would tighten the numbers further — not done, since it wasn't asked for.
- **The "§" multi-utterance linking syntax remains FS2-only.** `chatterbox/synth.py`'s
  multi-utterance branch unconditionally manipulates FS2's raw `.WAVEGLOW`/`.AU` binary format;
  a Piper user including `"|"` in free text will still hit a `FileNotFoundError`. Documented as a
  known, deliberately out-of-scope gap in `synth.py` itself (would need real work — WAV-level
  audio concatenation instead of mel-level — not a quick fix).
- **`export_to_xlsx.py`'s paste-ready spreadsheet export stays FS2-only**, by design (bound to an
  external template, `Chatterbox_Power_Measurements_final.xlsx`) — it now refuses a non-FS2 run
  loudly instead of silently corrupting the export, but doesn't produce a Piper-shaped equivalent.

## 9. Key references

- `docs/context/CHANGELOG.md` — search "Piper" for the full session-by-session log, in far more
  file:line detail than this summary.
- `docs/gui/INTERCHANGEABLE_BACKENDS.md` §3 — the contract-gap write-up (what the interchangeable-
  backend design got right vs. wrong, tested against a real second backend).
- `chatterbox/synthesis/backends/piper/README.md` — voice provenance, licence, sha256.
- `CLAUDE.md`'s "Interchangeable backends" section — the current, accurate narrative for anyone
  building a *third* backend.
