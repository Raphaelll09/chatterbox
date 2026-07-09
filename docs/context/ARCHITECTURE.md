# Architecture

Read this when you need module-level detail beyond what's in the root `CLAUDE.md`. Not loaded
automatically — read on demand.

## Repository layout

The repo root (where `CLAUDE.md` lives) is the working root for running scripts, tests, and
installing dependencies — there is no nested `embedded_tts/` subfolder inside it. It bundles three
vendored model repos, each with its own README/LICENSE, wired together by a thin orchestration
layer at the repo root:

- `FastSpeech2/` — TTS acoustic model (text → mel-spectrogram + visual/AU params).
  Vendored FastSpeech2 fork with custom style/GST (Global Style Token) and StyleTag (FlauBERT-based
  free-text emotion) conditioning, plus per-phoneme prosody "control bias" vectors.
- `hifi-gan-master/` — vocoder (mel-spectrogram → waveform). Default vocoder is
  `FR_V2` (French, fine-tuned on multi-speaker FastSpeech2 mel spectrograms).
- `Waveglow/` — alternative vocoder, currently disabled in `config_tts.yaml` (commented
  out under `vocoder_models`).
- `flaubert/` — pretrained FlauBERT-large model/tokenizer, loaded whenever the active
  TTS model's `styleTag_encoder.use_styleTag_encoder` is `True` (it is, in the shipped
  `ALL_corpus` config), but only actually run per-utterance when a `<STYLE_TAG=...>` free-text tag
  is present in the input.

Pretrained checkpoints are **not** in git — they're downloaded separately per `README.md`
(Google Drive links) and unzipped into `FastSpeech2/{config,output,preprocessed_data}`,
`flaubert/flaubert_large_cased`, `hifi-gan-master/FR_V2`, and `Waveglow/`. Do not expect the app to
run end-to-end without these. `scripts/setup_pi.sh` automates this download/unzip step
on a fresh Raspberry Pi 5 (see `INSTALL.md`); Waveglow is skipped by that script since
it's not part of the active pipeline (see below).

## Synthesis pipeline — four stages

`do_tts.py` reads `config_tts.yaml`, picks one entry from `tts_models` and one from `vocoder_models`
(by index, `--default_tts`/`--default_vocoder`), and dispatches to loader functions named in each
entry's `load_script` (in `loading_modules.py`). Everything below is orchestrated per-utterance by
`audio_utils.syn_audio()`.

1. **FlauBERT front-end** (optional, per-utterance) — `synthesis_modules.parse_params_from_text()`
   pulls a `<STYLE_TAG=...>` free-text tag out of the input if present, then
   `synthesis_modules.preprocess_styleTag()` embeds it via the pre-loaded
   `loading_modules.FLAUBERT_MODEL` / `FLAUBERT_TOKENIZER` (using
   `FastSpeech2/dataset.py:load_free_styleTags_embedding`). If no styleTag is given, this returns
   `None` and the model instead uses the GST emotion-token vector (`gst_token_index` /
   `style_intensity`) selected via `<STYLE=...>` / `<STYLE_INTENSITY=...>` or GUI controls.
2. **FastSpeech2 acoustic** — `synthesis_modules.syn_fastspeech2()` builds the control-value /
   control-bias arrays, resolves speaker/style/styleTag from text tags vs. GUI controls (text tags
   win — see "Contest with text-tags" in that function), then calls
   `FastSpeech2/synthesize.py:synthesize()` against the pre-loaded `loading_modules.TTS_MODEL`. Output
   is a mel-spectrogram plus `.AU` (37-parameter facial/visual animation) file written to disk under
   `FastSpeech2/output/audio`.
3. **HiFi-GAN vocoder** — `synthesis_modules.vocoder()` calls the model-specific `syn_script`
   (default `syn_hifigan`, which wraps `hifi-gan-master/inference_e2e.py:inference()` against the
   pre-loaded `loading_modules.GENERATOR`) to turn the mel file into a `.wav`. `syn_waveglow` is the
   alternate path, currently disabled in config.
4. **Audio write / post-process / playback** — back in `audio_utils.syn_audio()`: denoise via
   `noisereduce` (if `use_denoiser`), optional loudness post-processing
   (`audio_postprocess.normalize_and_limit`, if `postprocess.enabled`), low-pass filter the first 6
   (head-movement) `.AU` channels for `visual_smoothing`, write subtitle/alignment files, then play
   the result back (`play_audio()`).

Models are swapped from disk files, never held resident as multiple simultaneous instances — this
keeps memory low enough for CPU-only, embedded-style deployment (see "Performances" in
`README.md`: inference ≈ 20% of audio duration on CPU with recommended settings).

## Global-state loading pattern

Loaded models are stashed as **module-level globals** on `loading_modules` (`TTS_MODEL`, `CONFIGS`,
`FLAUBERT_MODEL`, `FLAUBERT_TOKENIZER`, `VOCODER_MODEL`, `GENERATOR`, `H`, `VOCODER_PATH`, ...) and on
`tts_utils` (`TTS_INDEX`, `VOCODER_INDEX`) — there is no model/session object passed around;
everything downstream fetches state via `getattr(loading_modules, "...")`. Switching models at
runtime (from the GUI) means re-running the loader, which overwrites these globals. Keep this in
mind before refactoring toward passed-in objects — a lot of code assumes these globals exist by the
time synthesis runs.

## Inline control-tag mini-language

Input text can carry synthesis controls inline, parsed by
`synthesis_modules.parse_params_from_text()`:
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
  `audio_utils.syn_audio()` before vocoding as a single file.

Text tags override the GUI/CLI control values (`gui_control` positional list in
`synthesis_modules.syn_fastspeech2`) when both are present.

## Config-driven model registry (config_tts.yaml)

`tts_models` and `vocoder_models` are lists of dicts, not a schema with a fixed shape — each entry
names its own `load_script`/`syn_script` (functions dynamically looked up via `getattr`), its own
`folder`, and its own `default_args`. Adding a new TTS or vocoder backend means adding a config entry
plus a `load_*`/`syn_*` function pair in `loading_modules.py`/`synthesis_modules.py`; nothing else
needs to change. `gui_utils.py` reads `gui_script` similarly to render model-specific controls (e.g.
`gui_fastspeech2`).

## Audio post-processing (audio_postprocess.py)

Standalone, dependency-light module (numpy + scipy only) with no globals — safe to unit test in
isolation (see `tests/test_audio_postprocess.py`). Two independent operations:
- `analyze()` — read-only loudness/crest-factor/clipping report.
- `normalize_and_limit()` — peak-normalizes and applies a feedforward soft limiter (look-ahead min +
  one-pole attack/release smoothing) to hit a target crest factor and peak level, then asserts its
  own invariants (`_verify`) before returning. It iterates the threshold up to 3 times to converge
  crest factor within ±1 dB.

This module is opt-in (`postprocess.enabled: false` by default in `config_tts.yaml`) and wired into
the pipeline only in `audio_utils.syn_audio()`; `do_tts.py --report-wav` also calls it standalone for
analysis without touching the synthesis pipeline.

## Platform-specific playback

Audio playback branches on `platform.system()` in both `audio_utils.py` and `gui_utils.py`: Windows
prefers `simpleaudio`, falling back to `sounddevice`/`soundfile` if unavailable; other platforms use
`pydub.playback.play`. When editing playback code, keep both paths in sync.

## Weights and config locations

- FastSpeech2 checkpoint: `FastSpeech2/output/ckpt/<checkpoint_file>` (config value
  `checkpoint_file: "390000"` by default), configs under
  `FastSpeech2/config/ALL_corpus/{preprocess,model,train}.yaml`, preprocessed speaker list at
  `<preprocessed_path>/speakers.json`.
- HiFi-GAN checkpoint: `hifi-gan-master/FR_V2/g_00570000`, config
  `hifi-gan-master/FR_V2/config.json`.
- FlauBERT: `flaubert/flaubert_large_cased/`.
- Waveglow (disabled by default): `Waveglow/waveglow_NEB.pt`.

## Profiling subsystem (profiling/)

Added 2026-07-08. Optional, off by default (`CHATTERBOX_PROFILE=1` env var, `do_tts.py --profile`,
or `profiling.enabled: true` in `config_tts.yaml`) — zero files written and near-no-op marks when
disabled. Three components share one `time.monotonic()` clock:

- `profiling/sampler.py` — background 10 Hz CPU/PMIC/thermal sampler, run as its own OS subprocess
  (`python -m profiling.sampler`) via `profiling.start_session()`/`stop_session()` (called from
  `do_tts.py`), pinned to one core (`os.sched_setaffinity`) and de-prioritised (`os.nice`). Reads
  `/proc/stat`, `/sys/.../scaling_cur_freq`, `/sys/class/thermal/thermal_zone0/temp`,
  `/proc/meminfo`, and `vcgencmd pmic_read_adc`/`get_throttled` (the only power source available —
  no external current sensor on the Pi's 5V rail). Writes `profile/per_sample.csv`. Linux-only; on
  other platforms (e.g. this Windows dev checkout) it no-ops with a warning while per-sentence
  marks still work. Pure-text parsing (`/proc/stat`, PMIC output, throttled bitmask) lives in
  `profiling/parsing.py`, unit-tested without needing real hardware.
- `profiling/recorder.py` — `Recorder`/`NullRecorder`, holding one `Recorder` per top-level input
  line. `audio_utils.syn_audio()` creates it (`profiling.begin_sentence()`) and publishes it via
  `profiling.set_current()` (a `contextvars.ContextVar`) so `synthesis_modules.syn_fastspeech2()`
  can reach it with `profiling.current()` without threading a parameter through every call in the
  chain. `Recorder.stage(name)` is a context manager wrapping the four pipeline stages
  (`front_end`, `acoustic` — both marked inside `syn_fastspeech2()`; `vocoder`, `write` — marked in
  `audio_utils.syn_audio()`); durations *accumulate* across repeated calls so the "§" sub-utterance
  loop in `syn_audio()` (which calls `synthesis_modules.tts()` once per sub-utterance) still yields
  one correct per-sentence record. Appends one JSON line per sentence to `profile/per_sentence.jsonl`.
- `profiling/join.py` — offline, not time-critical. Joins `per_sample.csv` + `per_sentence.jsonl`
  into `profile/per_sentence_results.csv` and `profile/per_stage_results.csv` (trapezoidal energy
  integration per sentence/stage window, mean/peak CPU, peak temp, throttled-any), applying a
  PMIC→external-meter linear calibration from `profile/calibration.json` if present (identity
  otherwise, produced by `profiling/calibrate.py` — see README "Profilage").

Tests: `tests/test_profiling.py` covers `parsing.py`, `recorder.py`, and `join.py`'s pure functions
(not `sampler.py`'s actual sysfs/vcgencmd reads, which need a real Pi).

## Benchmark mode (benchmark/)

Added 2026-07-08, on top of the profiling subsystem above. `do_tts.py --benchmark` runs a fixed
10-sentence French set (`benchmark/sentences_fr.jsonl`, one JSON object per line: `id`, `text`,
`tag`, `word_count`) through the exact same synthesis call as free-text mode —
`audio_utils.syn_audio()` — via `benchmark/runner.py:run_benchmark()`. No parallel synthesis path;
`do_tts.py` just loads models once (factored into a local `load_models()` closure shared with the
free-text branch) then calls `run_benchmark()` instead of the `input()` loop.

Order: REF, then the file's remaining entries in file order, then REF again (anchors both ends —
a drift check across one run), repeated `--repeats N` times, with a fixed 2 s `time.sleep()`
between every synthesis call so `profile/per_sample.csv` has clear idle baselines to slice around.
`--benchmark` forces `profiling.enabled` on in `do_tts.py`'s existing CLI/env merge (same code path
`--profile` uses); `--play` (default off) toggles `syn_audio()`'s `play` parameter — default
`play=True` in `syn_audio()` keeps free-text/GUI behavior unchanged, benchmark defaults to
`play=False` to isolate compute cost. `--join` calls `profiling.join.run_join()` (a plain callable,
not `join.py`'s own argparse `main()` — that would collide with `do_tts.py`'s own `sys.argv`)
after `profiling.stop_session()` so `per_sample.csv` is fully flushed first.

`audio_utils.syn_audio()` gained three optional, default-preserving parameters to support this:
`sentence_id`/`complexity_tag` (passed to `profiling.begin_sentence()`, which now accepts an
explicit `sentence_id` override instead of always auto-incrementing — so per-sentence records in
`per_sentence.jsonl` are labelled `"REF"`/`"A1"`/... instead of a meaningless counter) and `play`.
Existing call sites (`do_tts.py` free-text loop, `gui_utils.py`, `keyboards.py`) all use keyword
args already and don't pass these, so their behavior is untouched.

Tests: `tests/test_benchmark.py` covers sentence loading and call ordering (`audio_utils.syn_audio`
monkeypatched — real synthesis needs loaded models).

## Not yet implemented

Nothing tracked here as of 2026-07-08 — free-text (`--gui` optional), the profiling subsystem, and
benchmark mode above are all implemented. Update this section if a future session adds something
new and unfinished.
