# Architecture

Read this when you need module-level detail beyond what's in the root `CLAUDE.md`. Not loaded
automatically — read on demand.

Reflects the repo layout after the 2026-07-20 reorganization (`docs/REORG_PROPOSAL.md`, Phases
0–4). See that doc for the full rationale, the phase-by-phase history, and what's still owed
(real interactive GUI testing, Pi 5 hardware verification — no Pi access was available during the
reorg itself).

## Repository layout

The repo root (where `CLAUDE.md` lives) is the working root for running scripts, tests, and
installing dependencies — there is no nested `embedded_tts/` subfolder inside it.

- `chatterbox/` — the daily-use application package (synthesis, audio, GUI, config).
- `tools/` — research/maintenance tooling, not daily-use (`measurement/benchmark/`,
  `measurement/pmic_calibrate.py`, `monitoring/profiling/`).
- `assets/models/` — three vendored model repos, each with its own README/LICENSE:
  - `FastSpeech2/` — TTS acoustic model (text → mel-spectrogram + visual/AU params).
    Vendored FastSpeech2 fork with custom style/GST (Global Style Token) and StyleTag
    (FlauBERT-based free-text emotion) conditioning, plus per-phoneme prosody "control bias" vectors.
  - `hifi-gan-master/` — vocoder (mel-spectrogram → waveform). Default vocoder is
    `FR_V2` (French, fine-tuned on multi-speaker FastSpeech2 mel spectrograms).
  - `Waveglow/` — alternative vocoder, currently disabled in `config_tts.yaml` (commented
    out under `vocoder_models`).
  - `flaubert/` — pretrained FlauBERT-large model/tokenizer, loaded whenever the active
    TTS model's `styleTag_encoder.use_styleTag_encoder` is `True` (it is, in the shipped
    `ALL_corpus` config), but only actually run per-utterance when a `<STYLE_TAG=...>` free-text
    tag is present in the input.
- `assets/audio/` — `reference/` (postprocessing before/after demo WAVs) and `prompts/` (on-screen
  keyboard phoneme WAVs, read by `chatterbox/gui/app.py`).

Pretrained checkpoints are **not** in git — they're downloaded separately per `README.md`
(Google Drive links) and unzipped into `assets/models/FastSpeech2/{config,output,preprocessed_data}`,
`assets/models/flaubert/flaubert_large_cased`, `assets/models/hifi-gan-master/FR_V2`, and
`assets/models/Waveglow/`. Do not expect the app to run end-to-end without these.
`scripts/setup_pi.sh` automates this download/unzip step on a fresh Raspberry Pi 5 (see
`INSTALL.md`); Waveglow is skipped by that script since it's not part of the active pipeline (see
below).

## Synthesis pipeline — four stages

`do_tts.py` (a 3-line shim) calls `chatterbox.cli.main()`, which reads `config_tts.yaml`, picks one
entry from `tts_models` and one from `vocoder_models` (by index, `--default_tts`/
`--default_vocoder`), and dispatches to loader methods named in each entry's `load_script`, resolved
via `getattr(registry.BACKEND, load_script)` — `registry.BACKEND` is a singleton
`FastSpeech2HifiGanBackend` instance (`chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py`).
Everything below is orchestrated per-utterance by `chatterbox.cli.syn_audio()`.

1. **FlauBERT front-end** (optional, per-utterance) — `text_pipeline.parse_params_from_text()`
   pulls a `<STYLE_TAG=...>` free-text tag out of the input if present, then
   `text_pipeline.preprocess_styleTag()` embeds it via the backend's already-loaded
   `flaubert_model`/`flaubert_tokenizer` instance attributes (passed in explicitly by
   `backend.py`'s `syn_fastspeech2()`, using `assets/models/FastSpeech2/dataset.py:
   load_free_styleTags_embedding`). If no styleTag is given, this returns `None` and the model
   instead uses the GST emotion-token vector (`gst_token_index` / `style_intensity`) selected via
   `<STYLE=...>` / `<STYLE_INTENSITY=...>` or GUI controls.
2. **FastSpeech2 acoustic** — `FastSpeech2HifiGanBackend.syn_fastspeech2()` builds the
   control-value / control-bias arrays, resolves speaker/style/styleTag from text tags vs. GUI
   controls (text tags win — see "Contest with text-tags" in that method), then calls
   `assets/models/FastSpeech2/synthesize.py:synthesize()` against the backend's own `tts_model`
   attribute. Output is a mel-spectrogram plus `.AU` (37-parameter facial/visual animation) file
   written to disk under `assets/models/FastSpeech2/output/audio`.
3. **HiFi-GAN vocoder** — `FastSpeech2HifiGanBackend.vocoder()` calls the model-specific
   `syn_script` (default `syn_hifigan`, which wraps
   `assets/models/hifi-gan-master/inference_e2e.py:inference()` against the backend's own
   `generator` attribute) to turn the mel file into a `.wav`. `syn_waveglow` is the alternate path,
   currently disabled in config.
4. **Audio write / post-process / playback** — back in `chatterbox.cli.syn_audio()`: denoise via
   `chatterbox.audio.denoise.denoise()` (if `use_denoiser`), optional loudness post-processing
   (`chatterbox.synthesis.audio_postprocess.normalize_and_limit`, if `postprocess.enabled`),
   low-pass filter the first 6 (head-movement) `.AU` channels for `visual_smoothing`, write
   subtitle/alignment files (`chatterbox.synthesis.subtitles`), then play the result back
   (`chatterbox.audio.playback.play_audio()`).

Models are swapped from disk files, never held resident as multiple simultaneous instances — this
keeps memory low enough for CPU-only, embedded-style deployment (see "Performances" in
`README.md`: inference ≈ 20% of audio duration on CPU with recommended settings).

## Class-owned state (was: global-state loading pattern)

Before the 2026-07-20 reorg, loaded models were stashed as module-level globals on
`loading_modules`/`tts_utils`, fetched everywhere via `getattr(loading_modules, "...")`. Phase 3 of
the reorg converted this into a single `FastSpeech2HifiGanBackend` instance
(`chatterbox.synthesis.registry.BACKEND`) that owns `tts_model`/`configs`/`flaubert_model`/
`flaubert_tokenizer`/`vocoder_model`/`generator`/`h`/`vocoder_path` as **instance attributes**, plus
`chatterbox.state` (was `tts_utils.py`) for the tiny `TTS_INDEX`/`VOCODER_INDEX` selection globals.
The backend keeps its pre-reorg method names (`load_fastspeech2`, `syn_hifigan`, etc.) so
`config_tts.yaml`'s `load_script`/`syn_script`/`gui_script` string-based dispatch needed zero
changes — only what those strings resolve *against* changed (an object instead of a flat module).
See `docs/REORG_PROPOSAL.md` §5 for the full interface design, including why there are two ABCs
(`Synthesizer` for the acoustic model, `VocoderBackend` for the vocoder — `chatterbox/synthesis/
base.py`) rather than one: TTS and vocoder are independently swappable today (separate GUI
buttons), so a single bundled `load()` would break that.

Switching models at runtime (from the GUI) means re-running the loader method, which overwrites
those instance attributes — same semantics as the old globals, just owned by an object instead of a
module. Keep this in mind before assuming per-request isolation: this is still one shared backend
instance, not one object per synthesis call.

## Inline control-tag mini-language

Input text can carry synthesis controls inline, parsed by
`chatterbox.synthesis.backends.fastspeech2_hifigan.text_pipeline.parse_params_from_text()`:
- `<SPEAKER=name>` — override the speaker for the whole utterance (or sub-utterance).
- `<STYLE=NAME>` — select a GST emotion token (e.g. `COLERE`, `ENTHOUSIASTE`, `NARRATION`, ...; full
  list in `README.md`).
- `<STYLE_INTENSITY=0.0-1.0>` — blend weight between the selected style and neutral.
- `<STYLE_TAG=...>` (free text adjectives) — only honored when the model's `styleTag_encoder` is
  enabled; embedded via FlauBERT instead of a fixed GST index (see stage 1 above).
- `#word#` — adds emphasis on a word.
- `{s y z i}` — literal phonetic input for a word (phonetic alphabet documented in
  `README.md`, linked to a Zenodo reference).
- `§` — sub-utterance separator: text is split, each part synthesized independently (as a "linking
  utterance" so prosody/duration matches training), then the mel/`.AU` outputs are concatenated in
  `chatterbox.cli.syn_audio()` before vocoding as a single file.

Text tags override the GUI/CLI control values (`gui_control` positional list in
`FastSpeech2HifiGanBackend.syn_fastspeech2`) when both are present.

`parse_params_from_text()` takes the backend's already-loaded `configs` tuple as an explicit
parameter (added in the Phase 3 reorg) rather than re-reading `preprocess.yaml` from disk on every
`<SPEAKER=name>` tag, as the pre-reorg code did — the same class of leak `gui_utils.py:355` had for
the GUI's speaker list (see next section), found and fixed in both places at once.

## Config-driven model registry (config_tts.yaml)

`tts_models` and `vocoder_models` are lists of dicts, not a schema with a fixed shape — each entry
names its own `load_script`/`syn_script` (methods on `registry.BACKEND`, dynamically looked up via
`getattr`), its own `folder`, and its own `default_args`. Adding a new TTS or vocoder backend that
reuses the existing `FastSpeech2HifiGanBackend` class means adding a config entry plus a
`load_*`/`syn_*` method pair on that class; adding a genuinely new *kind* of backend (e.g.
Matcha-TTS) means a new class implementing `chatterbox.synthesis.base.Synthesizer` and a new
`chatterbox/synthesis/backends/<name>/` package — see `docs/REORG_PROPOSAL.md` §5 "How Matcha-TTS
would slot in". `chatterbox/gui/app.py` reads `gui_script` similarly to render model-specific
controls (e.g. `gui_fastspeech2`), and calls `registry.BACKEND.describe_controls()` for the speaker
list instead of re-parsing config YAML directly (the leak mentioned above, now closed).

## Audio post-processing (chatterbox/synthesis/audio_postprocess.py)

Standalone, dependency-light module (numpy + scipy only) with no globals — safe to unit test in
isolation (see `tests/test_audio_postprocess.py`), unchanged internally by the reorg (moved as a
whole file). Two independent operations:
- `analyze()` — read-only loudness/crest-factor/clipping report.
- `normalize_and_limit()` — peak-normalizes and applies a feedforward soft limiter (look-ahead min +
  one-pole attack/release smoothing) to hit a target crest factor and peak level, then asserts its
  own invariants (`_verify`) before returning. It iterates the threshold up to 3 times to converge
  crest factor within ±1 dB.

This module is opt-in (`postprocess.enabled: false` by default in `config_tts.yaml`) and wired into
the pipeline only in `chatterbox.cli.syn_audio()`; `do_tts.py --report-wav` also calls it standalone
for analysis without touching the synthesis pipeline.

`report_wav()` takes an optional `preloaded=(data, rate)` kwarg (added 2026-07-10) so
`chatterbox.cli.syn_audio()` can pass it the in-memory samples it already has mid-pipeline instead
of making it re-read the wav from disk; the standalone `--report-wav` CLI path (no samples in
memory yet) omits it and reads from disk as before.

`chatterbox.cli.syn_audio()`'s "write" stage (denoise → optional postprocess → optional analyze →
final `AudioSegment` for playback/duration) keeps the waveform in memory across all of those steps
and writes it to disk exactly once, instead of round-tripping the wav file through disk at each
step (a change made 2026-07-10 for latency, not correctness — see CHANGELOG).

## Platform-specific playback

Audio playback branches on `platform.system()` in `chatterbox/audio/playback.py` (was
`audio_utils.py`) and `chatterbox/gui/app.py` (was `gui_utils.py`): Windows prefers `simpleaudio`,
falling back to `sounddevice`/`soundfile` if unavailable; other platforms use
`pydub.playback.play`. When editing playback code, keep both paths in sync.
`chatterbox.audio.playback.AUDIO_EXAMPLE` holds the most recently synthesized clip as a module
attribute (not eliminated in the reorg) so `play_audio()` can still be called with no arguments —
needed because the GUI's "Play" replay button is wired as a zero-argument Tkinter callback.

## Weights and config locations

- FastSpeech2 checkpoint: `assets/models/FastSpeech2/output/ckpt/<checkpoint_file>` (config value
  `checkpoint_file: "390000"` by default), configs under
  `assets/models/FastSpeech2/config/ALL_corpus/{preprocess,model,train}.yaml`, preprocessed speaker
  list at `<preprocessed_path>/speakers.json`.
- HiFi-GAN checkpoint: `assets/models/hifi-gan-master/FR_V2/g_00570000`, config
  `assets/models/hifi-gan-master/FR_V2/config.json`.
- FlauBERT: `assets/models/flaubert/flaubert_large_cased/`.
- Waveglow (disabled by default): `assets/models/Waveglow/waveglow_NEB.pt`.

`chatterbox/config/paths.py` anchors all of the above to its own file location
(`Path(__file__).resolve().parents[2]`, i.e. two levels up — this file lives at
`chatterbox/config/paths.py`, so `parents[2]` is the repo root; **check this parent count first if
the file ever moves again**, since an off-by-one here breaks every path in the module silently —
this has already happened twice during the reorg, see `docs/REORG_PROPOSAL.md` §6), not the
process's current working directory. `chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py`'s
three `sys.path.insert` calls (`FastSpeech2/`, `hifi-gan-master/`, `Waveglow/`, all under
`assets/models/`), the same file's three regex-rule CSV paths (now under
`chatterbox/synthesis/backends/fastspeech2_hifigan/rules/`), and
`assets/models/FastSpeech2/utils/model.py`'s FlauBERT path all resolve through it, instead of bare
CWD-relative strings — see `docs/REORG_PROPOSAL.md` §6/Phase 0 for why (a future package move only
needs `paths.py`'s constants updated, not every scattered path string). It also anchors
`assets/audio/prompts/` (the on-screen keyboard's phoneme WAVs, `chatterbox/gui/app.py`'s
`AUDIO_KEYBOARDS_DIR`). `do_tts.py` must still be launched with the repo as the working directory
today; `paths.py` only removes the *hidden* CWD dependency in the vendored-import machinery, it
doesn't make the entry point location-independent.

Two config files inside `assets/models/FastSpeech2/config/ALL_corpus/` (`preprocess.yaml`,
`train.yaml`) are **gitignored** (downloaded from the Google Drive archives in `README.md`, never
committed) and historically hardcoded their own `"FastSpeech2/..."`-prefixed paths, predating the
reorg's move to `assets/models/`. `backend.py`'s `_repoint_legacy_fastspeech2_config_paths()`
remaps these in memory at load time, so a fresh download (from the unchanged archive) still works
without hand-editing — see `docs/REORG_PROPOSAL.md` §6 for the full story.

## Profiling subsystem (tools/monitoring/profiling/)

Added 2026-07-08; moved from `profiling/` to `tools/monitoring/profiling/` in the 2026-07-20 reorg
(Phase 2 — Goal 4, monitoring isolated as maintenance-only). Optional, off by default
(`CHATTERBOX_PROFILE=1` env var, `do_tts.py --profile`, or `profiling.enabled: true` in
`config_tts.yaml`) — zero files written and near-no-op marks when disabled. Three components share
one `time.monotonic()` clock:

- `tools/monitoring/profiling/sampler.py` — background 10 Hz CPU/PMIC/thermal sampler, run as its
  own OS subprocess (`python -m tools.monitoring.profiling.sampler`) via `profiling.start_session()`/
  `stop_session()` (called from `chatterbox/cli.py`), pinned to one core (`os.sched_setaffinity`)
  and de-prioritised (`os.nice`). Reads `/proc/stat`, `/sys/.../scaling_cur_freq`,
  `/sys/class/thermal/thermal_zone0/temp`, `/proc/meminfo`, and `vcgencmd
  pmic_read_adc`/`get_throttled`. Writes `profile/per_sample.csv`. Linux-only; on other platforms
  (e.g. this Windows dev checkout) it no-ops with a warning while per-sentence marks still work.
  Pure-text parsing (`/proc/stat`, PMIC output, throttled bitmask) lives in
  `tools/monitoring/profiling/parsing.py`, unit-tested without needing real hardware.
  - **Per-rail PMIC power** (added 2026-07-10): `pmic_read_adc` exposes a current *and* voltage
    channel per internally-metered rail, but `EXT5V_V`/`BATT_V` are voltage-only (no current) — so
    there is no single "input power" reading; `pmic_power_w` sums V×I over an *explicit* rail list
    (`parsing.PMIC_RAILS`), which is Pi-internal power (excludes regulator losses and anything
    drawn off the 5V GPIO pins — the external USB-C meter remains ground truth for total power).
    `tools.monitoring.profiling.parsing.parse_pmic_rails()` parses one `vcgencmd` call into a
    `{rail: {A, V}}` dict; `rails_total_power_w()`/`rails_cpu_power_w()` (`VDD_CORE`)/
    `rails_mem_power_w()` (`DDR_VDD2`+`DDR_VDDQ`+`1V1_SYS`)/`rails_ext5v_v()` all derive from that
    single parse, so one `vcgencmd pmic_read_adc` call per tick yields all four
    `per_sample.csv` columns (`pmic_power_w`, `cpu_power_w`, `mem_power_w`, `ext5v_v`).
    `Sampler._read_pmic_all()` + `_interpolate_and_write()` (generalized from a single scalar to
    `sampler.PMIC_FIELDS`, a list of 4 keys) carry all four through the same
    slower-than-10Hz-tick interpolation the PMIC total already used.
  - **INA226 amp-branch monitor** (optional, added 2026-07-10): a separate current/power sensor
    wired on the Pi's own `i2c-1` bus at address `0x40` (2 mΩ shunt), measuring the 5V branch that
    feeds the amplifier breadboard — distinct from the PMIC's system-wide reading. Auto-detected at
    `Sampler.run()` startup (`_init_ina226()`); absent sensor or a failed read never raises, it just
    leaves `ina_bus_v`/`ina_current_a`/`ina_power_w` empty for that row. One 6-byte I2C block read
    per tick (registers `0x02`–`0x04` are contiguous: bus voltage, power, current), decoded by pure
    functions in `tools/monitoring/profiling/parsing.py` (`decode_ina226_*`, unit-tested without
    hardware). Gated by `profiling.ina226` in `config_tts.yaml` / `--ina`/`--no-ina` on `do_tts.py`
    and `tools/monitoring/profiling/sampler.py`, threaded through `profiling.start_session(ina=...)`.
    Requires `smbus2` (Pi-only dependency, `requirements-pi.txt`; imported lazily inside
    `sampler.py` so a PC dev checkout without it is unaffected).
- `tools/monitoring/profiling/recorder.py` — `Recorder`/`NullRecorder`, holding one `Recorder` per
  top-level input line. `chatterbox.cli.syn_audio()` creates it (`profiling.begin_sentence()`) and
  publishes it via `profiling.set_current()` (a `contextvars.ContextVar`) so
  `FastSpeech2HifiGanBackend.syn_fastspeech2()` can reach it with `profiling.current()` without
  threading a parameter through every call in the chain. `Recorder.stage(name)` is a context
  manager wrapping the four pipeline stages (`front_end`, `acoustic` — both marked inside
  `syn_fastspeech2()`; `vocoder`, `write` — marked in `chatterbox.cli.syn_audio()`); durations
  *accumulate* across repeated calls so the "§" sub-utterance loop in `syn_audio()` (which calls
  `registry.BACKEND.tts()` once per sub-utterance) still yields one correct per-sentence record.
  Appends one JSON line per sentence to `profile/per_sentence.jsonl`.
- `tools/monitoring/profiling/join.py` — offline, not time-critical. Joins `per_sample.csv` +
  `per_sentence.jsonl` into `profile/per_sentence_results.csv` and `profile/per_stage_results.csv`
  (trapezoidal energy integration per sentence/stage window, mean/peak CPU, peak temp,
  throttled-any), applying a PMIC→external-meter linear calibration from `profile/calibration.json`
  if present (identity otherwise, produced by `tools/monitoring/profiling/calibrate.py` — see
  README "Profilage"). `_integrate_energy_j()` takes a `power_key` parameter (default
  `pmic_power_w`) so the same trapezoidal integration is reused for the INA226 amp-branch reading:
  each row also gets `amp_energy_j`/`amp_energy_wh` (integrated `ina_power_w`, no calibration
  applied — it's a direct reading) and `amp_mean_w`/`amp_peak_w`, and again for the per-rail PMIC
  signals: `cpu_energy_wh`/`cpu_mean_w` (from `cpu_power_w`) and `mem_energy_wh`/`mem_mean_w` (from
  `mem_power_w`) — all alongside the unchanged PMIC-total-derived system-energy columns.
  `_mean_power_w(window, power_key)` factors out the repeated mean-of-a-power-column pattern shared
  by `amp_mean_w`/`cpu_mean_w`/`mem_mean_w`.

Tests: `tests/test_profiling.py` covers `parsing.py`, `recorder.py`, and `join.py`'s pure functions
(not `sampler.py`'s actual sysfs/vcgencmd/I2C reads, which need a real Pi).

## Excel export (tools/measurement/benchmark/export_to_xlsx.py)

Added 2026-07-10; moved from `benchmark/` to `tools/measurement/benchmark/` in the 2026-07-20
reorg. Reads the join's own output (`per_sentence_results.csv`/`per_stage_results.csv`) — no
synthesis/profiling logic of its own — and writes `profile/exports/chatterbox_paste.xlsx`
(dedicated output subfolder, gitignored like the rest of `profile/`'s generated files), formatted
to paste directly into the master workbook `Chatterbox_Power_Measurements_final.xlsx`, sheet
`P2P3_Synthesis`, cell `A12` (columns A-U, header row 1, one 11-row data block per benchmark pass
in rows 2-12). `--repeats N` produces `N` back-to-back 11-sentence passes in the CSVs (in recorded
order, no re-sorting anywhere in the pipeline); `export_to_xlsx._split_into_passes()` chunks them
and `write_workbook()` gives each its own sheet (`P2P3_Synthesis`, `P2P3_Synthesis_pass2`, ...,
all with the same `A2:U12` layout so any one of them can be pasted individually). A trailing
partial pass (interrupted run) is dropped with a warning rather than written incomplete.

`runner.py`'s `REF` anchor sentence shares its literal id (`"REF"`) between the first and last
entry of each pass — `_relabel_ref(sentence_id, position)` distinguishes them by **position**
within the pass (`0` → `REF_start`, `10` → `REF_end`), not by id.

Derived columns (`RTF`, `synthP_W`, `E/s_Wh`, `cpuP_W`) are computed directly in Python from the
join's columns per the formulas in the original spec (e.g. `synthP_W = pmicE_Wh*3.6e6/synth_ms`)
so the pasted block is self-contained (plain values, no Excel formulas). `openpyxl` is imported
lazily inside `write_workbook()`; if missing, `export()` prints an install hint and returns `None`
without touching the CSVs — never crashes a `--benchmark` run. Wired into `do_tts.py` via
`--export-xlsx` (opt-in, implies `--join`, matching the existing "every profiling feature is an
explicit switch" convention — nothing runs automatically).

Tests: `tests/test_export_xlsx.py` covers the pure row-mapping/pass-splitting/REF-relabeling logic,
plus one `openpyxl` round-trip (`pytest.importorskip`'d — skips cleanly if `openpyxl` isn't
installed, since it's an optional dependency).

## Benchmark mode (tools/measurement/benchmark/)

Added 2026-07-08, on top of the profiling subsystem above; moved from `benchmark/` to
`tools/measurement/benchmark/` in the 2026-07-20 reorg. `do_tts.py --benchmark` runs a fixed
10-sentence French set (`tools/measurement/benchmark/sentences_fr.jsonl`, one JSON object per
line: `id`, `text`, `tag`, `word_count`) through the exact same synthesis call as free-text mode —
`chatterbox.cli.syn_audio()` — via `tools/measurement/benchmark/runner.py:run_benchmark()`. No
parallel synthesis path; `chatterbox.cli.main()` just loads models once (factored into a local
`load_models()` closure shared with the free-text branch) then calls `run_benchmark()` instead of
the `input()` loop.

Order: REF, then the file's remaining entries in file order, then REF again (anchors both ends —
a drift check across one run), repeated `--repeats N` times, with a fixed 2 s `time.sleep()`
between every synthesis call so `profile/per_sample.csv` has clear idle baselines to slice around.
`--benchmark` forces `profiling.enabled` on in `chatterbox.cli.main()`'s existing CLI/env merge
(same code path `--profile` uses); `--play` (default off) toggles `syn_audio()`'s `play` parameter
— default `play=True` in `syn_audio()` keeps free-text/GUI behavior unchanged, benchmark defaults
to `play=False` to isolate compute cost. `--join` calls `profiling.join.run_join()` (a plain
callable, not `join.py`'s own argparse `main()` — that would collide with `do_tts.py`'s own
`sys.argv`) after `profiling.stop_session()` so `per_sample.csv` is fully flushed first.

`chatterbox.cli.syn_audio()` has three optional, default-preserving parameters to support this:
`sentence_id`/`complexity_tag` (passed to `profiling.begin_sentence()`, which accepts an explicit
`sentence_id` override instead of always auto-incrementing — so per-sentence records in
`per_sentence.jsonl` are labelled `"REF"`/`"A1"`/... instead of a meaningless counter) and `play`.
Existing call sites (`chatterbox/cli.py`'s free-text loop, `chatterbox/gui/app.py`,
`chatterbox/gui/keyboards.py`) all use keyword args already and don't pass these, so their
behavior is untouched.

Tests: `tests/test_benchmark.py` covers sentence loading and call ordering
(`chatterbox.cli.syn_audio` monkeypatched — real synthesis needs loaded models).

## Not yet implemented

- A from-scratch backend without an `.AU` visual-animation channel (e.g. Matcha-TTS) would need
  `chatterbox/cli.py`'s `syn_audio()` changed to not assume one unconditionally (reading
  `audio_file.AU`, visual smoothing, subtitle timing from `audio_file_duration.npy`) — flagged
  during the Phase 3 reorg, not attempted speculatively; see `docs/REORG_PROPOSAL.md` §5.
- Real interactive GUI testing and Pi 5 hardware verification for the whole 2026-07-20 reorg — no
  Pi access or interactive display was available while executing it; see `docs/REORG_PROPOSAL.md`
  §7 for what was verified instead (CLI battery + a timed `--gui` launch reaching
  `window.mainloop()` with zero tracebacks) and what remains owed.

Otherwise nothing tracked here — free-text (`--gui` optional), the profiling subsystem, and
benchmark mode above are all implemented. Update this section if a future session adds something
new and unfinished.
