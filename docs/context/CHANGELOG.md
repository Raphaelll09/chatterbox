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

## 2026-07-16 — Fix INA226 power derivation, per-run profiling output isolation

- What:
  1. **INA226 power (`profiling/sampler.py`)**: `_read_ina226()` now computes `ina_power_w`
     in software (`bus_v * current_a`) instead of decoding the hardware POWER register
     (0x03). That register is unsigned and undefined when CURRENT is negative — the "409.6 W
     constant, current pinned at -1 LSB" symptom is POWER/CURRENT both saturated at 0xFFFF.
     Bus voltage and (signed) current are each independently well-defined, so their product
     is trustworthy where the raw register isn't. **Note**: CONFIG (0x4527) and CALIBRATION
     (10240) were already being written at sampler init in this codebase (`_init_ina226()`)
     — exactly matching the values the source prompt suggested as the fix — so if the Pi is
     still seeing garbage after pulling this, the most likely explanation is that the Pi was
     running an older revision of `sampler.py` predating those writes, not a config/cal gap in
     the current code. Added defense-in-depth regardless: a `INA226_SETTLE_S` (60ms) delay
     after CONFIG+CALIBRATION before the first read (AVG=16 needs ~35ms for the first valid
     conversion), and a startup sanity check (`abs(current_a) < 0.001` or `bus_v < 4.5`) that
     prints a `[profiling] WARNING: ...` and disables the sensor for the rest of the run
     instead of silently logging bad data.
  2. **`throttled` column**: `sampler.py` now writes it as a hex string (`"0x50000"`, matching
     `vcgencmd get_throttled`'s own format) instead of a plain decimal int; `join.py`'s
     `load_samples()` parses it with `int(x, 0)` (auto-detects the `0x` prefix, still accepts
     old plain-decimal files). `_throttled_any()`'s logic was already correct (`any(v != 0
     ...)` on the parsed int) — the column just wasn't human-legible before.
  3. **`phoneme_count`**: confirmed it was a duplicate of `char_count`, not a real phoneme
     count — see `synthesis_modules.py:206`. `text_to_sequence()`
     (`FastSpeech2/text/__init__.py`) maps one symbol per character for ordinary orthographic
     text; there's no G2P front-end for French in this pipeline (only the opt-in `{phonetic
     bracket}` syntax produces a token-per-phoneme sequence, and there's no way to tell from
     the recording site whether a given input used it). Now reports `null`
     (`profiling_rec.set(phoneme_count=None)`) instead of the misleading duplicate.
  4. **Per-run output isolation**: every profiled session now gets its own
     `profile/run_YYYYMMDD_HHMMSS/` directory (collision-disambiguated with a `_2`/`_3`
     suffix if two sessions start in the same second), containing `per_sample.csv`,
     `per_sentence.jsonl`, and (once `--join`/`--export-xlsx` run) `per_sentence_results.csv`,
     `per_stage_results.csv`, `exports/chatterbox_paste.xlsx`. `profile/latest` points at the
     most recent run (a symlink where supported, else a `latest.txt` pointer file — both
     handled by `profiling/join.py`'s new default-dir resolution). Previously
     `per_sample.csv` was overwritten every run while `per_sentence.jsonl` was appended to
     forever, so after N runs the join only matched records from the last run against a
     `per_sentence.jsonl` containing all N runs' records mixed together.
     `profiling/__init__.py::start_session()` creates the run dir and writes its initial
     `meta.json` (`sample_hz`, `pmic_hz`, `core`, `niceness`, `ina_requested`, `governor`
     read from sysfs, a `calibration.json` snapshot, plus `meta_extra` — `do_tts.py` passes
     `{"play": ..., "repeats": ...}` for `--benchmark`); `sampler.py`'s own process patches in
     `ina_detected` and `profiler_pid` once it's actually probed the I2C bus (the only two
     fields it alone knows). `calibration.json` itself stays a base-dir-level, cross-run file
     (`load_calibration()` now checks the run dir first, then falls back to its parent).
     `do_tts.py`'s end-of-benchmark `--join`/`--export-xlsx` calls now use
     `profiling.get_run_dir()` instead of the base `output_dir`.
  5. **Join safety net**: `run_join()` now drops any `per_sentence.jsonl` record whose
     synthesis window falls entirely outside the sample stream's `t_mono` range before
     building results, printing `[join] WARNING: N records outside the sample window (stale
     data?) - skipped` instead of emitting rows with empty energy columns. With per-run
     isolation this shouldn't normally trigger — it's a defense-in-depth backstop for
     hand-mixed or pre-existing (pre-this-fix) logs.
- Files: `profiling/sampler.py`, `profiling/__init__.py`, `profiling/join.py`, `do_tts.py`,
  `synthesis_modules.py`, `tests/test_profiling.py`
- Why: the 7B dry run found the INA226 columns reading constant, physically-impossible values
  (power pegged at the register's all-ones value) and `profile/per_sentence.jsonl` holding 318
  records from 9 separate runs against a `per_sample.csv` with only the last run's ~39s of
  samples, so the join matched 11/318 records and the rest were emitted with empty energy.
- Verify: `python3 -m pytest tests/` (83 passed — 12 new tests covering the run-dir
  naming/collision handling, `meta.json` writing and patching, `profile/latest` resolution,
  `calibration.json`'s parent-dir fallback, and the hex/legacy-decimal `throttled` parsing;
  none of this needs real hardware). Manually exercised on this dev checkout (no Pi/I2C/PMIC
  available here): `profiling._new_run_dir()` creates a real timestamped directory with a
  correctly-populated `meta.json`; `Sampler._patch_meta_json()` correctly read-modify-writes
  `ina_detected`/`profiler_pid` into an existing `meta.json` without clobbering other fields;
  `join._resolve_default_profile_dir()` correctly follows both the symlink and `.txt`-pointer
  forms of `profile/latest`; `join.load_calibration()` correctly finds `calibration.json` in a
  run dir's parent; `int(x, 0)` correctly parses both `"0x50005"` and legacy `"327685"`.
- Notes/gotchas: **the INA226 fix's actual effect on real hardware could not be verified from
  this Windows PC** — no I2C bus, no INA226, no `vcgencmd`. On the Pi, after pulling this and
  running a **short profiler-only session** (per the constraint: no need to re-run the full
  benchmark) with the amp powered and idle, `ina_current_a` should read ≈0.0637 A and
  `ina_power_w` ≈0.32 W in the new run's `per_sample.csv`, matching `ina226_logger.py` on the
  same rail within a few percent — compare directly. If it's still garbage, check whether the
  Pi had actually pulled the CONFIG/CALIBRATION-writing revision of `sampler.py` before this
  session (see note above) — that would point at a different bug than the one fixed here.
  Similarly, a real throttle event and the new per-run `profile/run_.../` layout (with
  `profile/latest` resolving correctly) should be spot-checked on the Pi's real filesystem —
  symlink creation in particular behaves differently across platforms and this was only
  exercised via the `latest.txt` fallback path implicitly (symlinks did work in the ad hoc
  check on this Windows dev machine, since Developer Mode is enabled here, but that isn't
  guaranteed on every Windows setup and is moot on the Pi's Linux filesystem where symlinks
  are unconditionally supported).

---

## 2026-07-16 — Fix NumPy 2.0 join crash, standalone join entry point, subtitle-split print explained

- What:
  1. `profiling/join.py::_integrate_energy_j`: `trapezoid = getattr(np, "trapezoid",
     np.trapz)` crashes on NumPy versions where `np.trapz` has actually been removed,
     because the default-argument expression `np.trapz` is evaluated eagerly (before
     `getattr` runs) regardless of whether the lookup would've succeeded — the
     "fallback" line is what raises `AttributeError`. Replaced with
     `np.trapezoid if hasattr(np, "trapezoid") else np.trapz`, which short-circuits
     before ever touching the possibly-missing attribute. Repo-wide search for the same
     eager-`getattr` pattern and other removed-in-2.0 aliases (`np.float_`, `np.int_`,
     `np.NaN`, `np.alltrue`, `np.product`, `np.cumproduct`, `np.round_`) found no other
     occurrences. (This dev venv pins numpy 2.0.2, where `np.trapz` still exists — the
     crash doesn't reproduce here, but the eager-evaluation bug is real regardless, and
     `requirements-pi.txt`'s loose `numpy>=2.0.2` floor is exactly what let the Pi
     resolve a newer numpy that already dropped it.)
  2. `profiling/join.py::load_sentences`: missing `per_sentence.jsonl` now raises a
     clear `SystemExit` message instead of a raw `FileNotFoundError` traceback.
  3. `profiling/join.py::main`: added `--export-xlsx` (calls
     `benchmark.export_to_xlsx.export` after the join, matching `do_tts.py
     --benchmark --export-xlsx`'s behavior) and a description string. The module
     already had `if __name__ == "__main__": main()` and a working `--profile-dir`
     flag, so `python3 -m profiling.join [--profile-dir DIR] [--export-xlsx]` was
     already usable standalone — verified by running it against local `profile/`
     logs (no re-synthesis).
- Files: `profiling/join.py`
- Why: `python3 do_tts.py --benchmark --profile --join --repeats 3` completed the full
  33-sentence benchmark on the Pi but crashed in the join step (NumPy 2.0 removed
  `np.trapz`) — the raw per-sentence/per-sample logs were already written correctly,
  only the post-processing failed, so the fix needed to be re-runnable against
  existing logs rather than requiring a ~10-minute re-benchmark.
- Verify: `python3 -m pytest tests/` (71 passed, unaffected — no test covers
  `profiling/join.py` directly). Manually: `python3 -m profiling.join --help` shows
  the new flag; `python3 -m profiling.join --profile-dir /nonexistent` exits 1 with
  the clear message instead of a traceback; `python3 -m profiling.join` against this
  checkout's local `profile/` (2 stray `EX1` records, no `per_sample.csv`) writes
  `per_sentence_results.csv`/`per_stage_results.csv` with the timing columns
  populated and the power columns empty (expected — no PMIC sampler data on this
  machine) instead of crashing.
- Notes/gotchas: **the real verification (33 records, populated `ina_power_w`/
  `cpu_power_w`) still needs to be run on the Pi**, against the logs already sitting
  in `~/chatterbox/profile/` from the crashed run — `profile/*.csv`/`*.jsonl` are
  gitignored (never synced via git), and this dev checkout only has 2 unrelated stray
  records with no `per_sample.csv` at all, so that specific check couldn't be
  performed from here. On the Pi: `cd ~/chatterbox && git pull && python3 -m
  profiling.join` (after pulling this fix) should produce the real
  `per_sentence_results.csv` from the already-completed benchmark run without
  re-synthesizing anything.

  Also investigated (no code change, per the "explain, don't change behavior yet"
  instruction): the debug print seen for inputs over ~58-60 characters (e.g. `[87,
  102]` for the B2 benchmark sentence, `[39, 138, 138]` for C1 — reproduced exactly
  by calling `audio_utils.find_separators_subtitles()` directly on those sentences)
  is `print(separators_indexes)` at `audio_utils.py:390`, inside `write_subtitles()`
  (only reached when `config_tts.yaml`'s `subtitles.create_file: True`, which is the
  default, and only for text over `subtitles.max_nbr_char: 60` chars after
  preprocessing). **This is not synthesis-time chunking** — it's a post-hoc split of
  the *already-synthesized* subtitle text into ≤60-char `.vtt` cue lines, using the
  per-symbol durations FastSpeech2 already produced, purely for subtitle display
  timing. It runs after the full mel-spectrogram + vocoder pass for the whole
  sentence has already completed, so it is **not** a usable hook for streaming
  synthesis (chunking here doesn't reduce time-to-first-audio at all). The existing
  `§` sub-utterance marker (`audio_utils.syn_audio()`'s `sub_utterance_separator`
  handling, synthesizing each `§`-delimited piece separately then concatenating) is
  the actual pre-synthesis chunking mechanism already in the pipeline, and would be
  the real starting point for streaming synthesis if that's wanted later. The print
  itself has no descriptive label (unlike every other print in the codebase, e.g.
  `"Speaker: ..."`, `"TTS duration: ..."`) and reads as leftover debug output rather
  than an intentional user-facing message, but this repo has no existing debug/
  verbosity flag anywhere to gate it behind (`grep -r "debug\|verbose"` over the
  active pipeline code found nothing) — left unchanged, since Task 5's instruction
  to gate it was conditional on such a flag already existing, and inventing one
  wasn't asked for.

  Task 4 (benchmark warm-up) from the source prompt was intentionally skipped: an
  equivalent warm-up already exists for free-text mode (see the entry directly
  below), and `--benchmark` deliberately excludes it — its REF-first/REF-last
  sentences exist specifically to *measure* the cold-start effect for this project's
  power-profiling work, so adding a silent pre-benchmark warm-up would defeat that.

---

## 2026-07-16 — Background warm-up synthesis in free-text mode

- What: `do_tts.py`'s free-text branch now fires a throwaway warm-up synthesis
  ("Bonjour.", `play=False`, stdout suppressed) on a background daemon thread
  right after `load_models()`, instead of paying first-call cost on the
  user's first real sentence. The main thread immediately shows the `Input
  Text` prompt, so the warm-up overlaps with the time spent typing. On the
  *first* real submission only, the main thread `warmup_thread.join()`s
  before calling `audio_utils.syn_audio()` — this serializes warm-up and the
  first real synthesis (they'd otherwise both write the same fixed-path
  FastSpeech2/HiFi-GAN output files and contend for the same CPU cores).
  Subsequent inputs skip the join (thread is already finished by then).
  Tagged `sentence_id="WARMUP"` / `complexity_tag="warmup"` so it's
  identifiable if profiling happens to be enabled during interactive use.
- Files: `do_tts.py`
- Why: measured on the Pi 5 (see the two preceding sessions), the very first
  synthesis in a process runs noticeably slower than steady-state even though
  model *weights* are already loaded before the prompt appears — the
  remaining cost is first-call setup (torch's CPU thread pool, the CPU
  governor ramping up from idle, noisereduce's internal FFT setup), which
  this pays for once, off the user's critical path.
- Verify: `python3 do_tts.py`, type the first sentence somewhat slowly —
  synthesis prints/timings should not appear until you press Enter (warm-up
  output is suppressed), and the first real `TTS duration` / `Vocoder
  duration` percentages should already be near steady-state instead of the
  inflated first-call numbers seen previously.
- Notes/gotchas: scoped to free-text (`do_tts.py`, no `--gui`, no
  `--benchmark`) only. Deliberately *not* added to `--benchmark` mode — its
  REF-first/REF-last sentences exist specifically to measure this exact
  warm-up/drift effect for the power-profiling work, so pre-warming there
  would corrupt what it's designed to capture. GUI mode (`--gui`) doesn't
  block the same way `input()` does (Tkinter's loop isn't blocked by typing),
  so the same background-thread approach wasn't added there — worth a
  separate look if GUI first-synthesis latency turns out to matter too.
  Correction to a claim made earlier in this session: HiFi-GAN's
  `meldataset.py` `mel_basis`/`hann_window` lazy caches (mentioned as a
  suspected warm-up cost) are **not** actually exercised by the active
  `inference_e2e.py` runtime path — only `MAX_WAV_VALUE` is imported from
  that module. The warm-up fix here doesn't depend on that specific
  mechanism; running one real end-to-end call pays whatever the actual
  first-call costs are, wherever they live.

---

## 2026-07-15 — Normalize curly apostrophes before symbol filtering

- What: `parse_pronunciation_mistakes()` now replaces `’`/`‘` (U+2019/U+2018) with the straight
  `'` as its first step, before URL/mail parsing and the `symbols_regex_rules.csv` loop.
  FastSpeech2's symbol set (`FastSpeech2/text/symbols.py` `_punctuation`) only includes the
  straight apostrophe, so curly ones (routinely produced by word processors/mobile keyboards)
  were being silently dropped by `_should_keep_symbol()` (`FastSpeech2/text/__init__.py`),
  printing `The Character: '...' is not in the symbols list` and losing the elision entirely
  (e.g. "qu’il" synthesized as if written "quil"). Deliberately *not* added as a
  `symbols_regex_rules.csv` row: that loop pads every replacement with spaces
  (`" {} ".format(...)`), which would have turned "qu'il" into "qu ' il" and introduced an
  audible gap — a direct, unpadded `str.replace` avoids that.
- Files: `synthesis_modules.py`
- Why: found by comparing two back-to-back CPU-timing runs on the Pi 5 that both logged
  repeated "not in the symbols list" warnings for the same French fable text (rich in
  apostrophe elisions typed with curly quotes).
- Verify: `python3 do_tts.py` with text containing "qu’il"/"s’est"/etc. (curly apostrophe) no
  longer prints the symbols-list warning, and `Input after pre-processing:` shows the straight
  `'` in place.
- Notes/gotchas: only U+2019/U+2018 are handled. Curly double quotes (`“`/`”`) have the same
  underlying gap (also absent from `_punctuation`) but weren't hit by the observed input — same
  fix pattern would apply if they come up.

---

## 2026-07-15 — Pin missing `librosa` dependency in requirements-pi.txt

- What: `requirements-pi.txt` left `librosa` unpinned on the assumption that `noisereduce`
  pulls it in transitively (true for the exact `noisereduce==3.0.2` pin in
  `requirements-dev.txt`, per that file's own comment). On a real Pi 5 provisioning run, the
  loose `noisereduce>=3.0.2` floor resolved to a newer noisereduce release whose dependency
  metadata no longer requires librosa (moved to a torch-based STFT), so librosa was never
  installed — even though it's a hard, direct import of the active vocoder code
  (`hifi-gan-master/meldataset.py`: `from librosa.util import normalize`,
  `librosa.filters.mel`). Surfaced as `ModuleNotFoundError: No module named 'librosa'` at
  `import gui_utils` → ... → `inference_e2e` → `meldataset` on `python3 do_tts.py`, despite
  `scripts/setup_pi.sh`'s own end-to-end smoke test having passed earlier in the same
  provisioning run (presumably a slightly different noisereduce resolution at that moment, or
  librosa was present then and removed/never-added by a later `pip` operation — exact trigger
  unconfirmed, but the missing explicit pin is the root cause either way).
- Files: `requirements-pi.txt`
- Why: make librosa's dependency explicit and pinned instead of relying on an incidental
  transitive resolution that isn't guaranteed to hold as noisereduce's own dependencies drift.
- Verify: on the Pi, `pip install librosa` unblocks the immediate failure; re-running
  `pip install -r requirements-pi.txt` (or a fresh `scripts/setup_pi.sh`) now installs librosa
  directly regardless of what noisereduce resolves to.
- Notes/gotchas: `requirements-pi-lock.txt` on already-provisioned Pi units won't reflect this
  until `pip install -r requirements-pi.txt` (or `setup_pi.sh`) is re-run there.

---

## 2026-07-10 — Inference-time micro-optimizations (I/O caching + inference_mode)

- What: Four targeted, code-only latency fixes identified by a hot-path review, no new
  dependencies:
  1. `audio_utils.syn_audio()`: the post-synthesis "write" stage (denoise → optional
     postprocess → optional analyze → final `AudioSegment` for playback/duration) used to
     read the wav back from disk at every step and re-read it a final time via
     `AudioSegment.from_wav()`. Now the array is kept in memory across all steps, written to
     disk exactly once, and `AudioSegment` is built directly from the in-memory samples.
     `audio_postprocess.report_wav()` gained an optional `preloaded=(data, rate)` kwarg so the
     `analyze` path can reuse the same in-memory samples instead of re-reading the file
     (backward-compatible — the standalone `--report-wav` CLI path still reads from disk).
  2. `synthesis_modules.py`: `parse_pronunciation_mistakes()`/`do_adr()` used to re-open and
     `tqdm`-iterate `symbols_regex_rules.csv`/`custom_regex_rules.csv`/`url_regex_rules.csv`
     (123 lines total) on *every* synthesis call. Now parsed once into module-level caches
     (`_get_symbols_regex_rules()`/`_get_custom_regex_rules()`/`_get_url_regex_rules()`) —
     the `tqdm` import is gone too, since the per-call iteration it wrapped no longer exists.
  3. `synthesis_modules.py`: `syn_fastspeech2()` (and the `<SPEAKER=...>` text-tag path in
     `parse_params_from_text()`) re-read+re-parsed `speakers.json` on every call just to print
     the speaker's display name. Now cached per-path in `_get_speaker_list()`.
  4. Swapped `torch.no_grad()` → `torch.inference_mode()` (strictly cheaper — skips autograd
     view-tracking bookkeeping entirely) in the four hot forward-pass call sites:
     `FastSpeech2/synthesize.py:process_per_batch`, `FastSpeech2/utils/model.py:vocoder_infer`,
     `hifi-gan-master/inference_e2e.py:inference`, `FastSpeech2/dataset.py:load_FlauBERT_embedding_from_styleTag`.
- Files: `audio_utils.py`, `audio_postprocess.py`, `synthesis_modules.py`,
  `FastSpeech2/synthesize.py`, `FastSpeech2/utils/model.py`, `FastSpeech2/dataset.py`,
  `hifi-gan-master/inference_e2e.py`.
- Why: A code-only (no new deps) pass over the synthesis hot path for the Pi 5 embedded
  target, requested to shave per-utterance latency without touching model architecture or
  audio quality. Full options list (including ones *not* applied, e.g. reverting the denoiser
  to its cheaper `stationary=True` mode — a quality/speed trade-off left for a separate
  decision) was written up as a report before any change was made.
- Verify: `tests/` (71 tests, all passing, unchanged pass count). Manual before/after
  benchmark on the dev machine (`do_tts.py --benchmark --sentences <1-sentence file>
  --repeats 10`, git-stashing the fix commit to get a clean A/B): output `audio_file.wav` is
  **byte-identical** (same SHA-256) before and after across 40 total synthesis calls — zero
  functional/quality regression. Console output confirms fix 2 structurally: the `tqdm`
  progress-bar lines (40 of them across 20 baseline calls, from re-reading the two CSVs each
  time) disappear entirely after the fix. `write`-stage per-sentence profiling timing (fix 1's
  target) improved slightly (~-12% mean / ~-2% median) but within run-to-run noise on this
  dev machine — small wav files mean the redundant reads mostly hit the OS page cache here;
  expect a clearer win on the Pi 5's slower storage. `vocoder`/`acoustic` stage timings showed
  no clean signal either way (a mid-run slowdown-then-recovery pattern in one A/B pass points
  to host-machine noise, e.g. background scanning of just-modified files, not a code-caused
  regression — `inference_mode` cannot add per-call overhead over `no_grad`).
- Notes/gotchas: This Windows dev checkout is not the target platform and has enough
  measurement noise (shared machine, no core pinning, small files fit in OS cache) that only
  the structural fixes (3, and to a lesser extent 1) could be confirmed with clean evidence
  here. Re-measure on an actual Pi 5 with `--benchmark --profile --join` (+ PMIC calibration)
  for a trustworthy energy/latency read before drawing conclusions about the on-device impact.
  The denoiser parameter question (non-stationary vs. the commented-out `stationary=True`
  config) was flagged but deliberately left untouched — it's a quality/speed trade-off, not a
  free win, and needs a listening comparison before deciding.

---

## 2026-07-10 — Per-rail PMIC power + paste-ready Excel export

- What: Extended the profiler and offline join (not duplicated) with explicit per-rail PMIC power,
  and added a new Excel exporter for the benchmark results.
  1. `profiling/parsing.py`: `parse_pmic_rails()` (extracted from the old `parse_pmic_power_w()`
     body) parses one `vcgencmd pmic_read_adc` call into a `{rail: {A, V}}` dict; `PMIC_RAILS` is
     now an explicit list of the 12 internally-metered rails (excludes `EXT5V`/`BATT`, which are
     voltage-only). New `rails_total_power_w()`/`rails_cpu_power_w()` (`VDD_CORE`)/
     `rails_mem_power_w()` (`DDR_VDD2`+`DDR_VDDQ`+`1V1_SYS`)/`rails_ext5v_v()` derive all four
     signals from one parse. `parse_pmic_power_w(text)` keeps its old signature as a thin wrapper.
  2. `profiling/sampler.py`: `_read_pmic()` → `_read_pmic_all()`, one `vcgencmd` call per tick now
     yields `pmic_power_w`/`cpu_power_w`/`mem_power_w`/`ext5v_v` together; `_interpolate_and_write()`
     generalized from a single scalar to `PMIC_FIELDS` (a list of 4 keys), same interpolation
     scheme as before. Three new `per_sample.csv` columns.
  3. `profiling/join.py`: `load_samples()` parses `cpu_power_w`/`mem_power_w`; both result builders
     gain `cpu_energy_wh`/`cpu_mean_w` and `mem_energy_wh`/`mem_mean_w` via the already-generalized
     `_integrate_energy_j(window, power_key)`, plus a new `_mean_power_w()` helper (also used to
     de-duplicate the existing `amp_mean_w` computation).
  4. `benchmark/export_to_xlsx.py` (new): reads `per_sentence_results.csv`/`per_stage_results.csv`,
     writes `profile/exports/chatterbox_paste.xlsx` — sheet `P2P3_Synthesis` (cols A-U, header row
     1, data rows 2-12) matching the master workbook `Chatterbox_Power_Measurements_final.xlsx`'s
     paste target exactly, plus a `per_stage` reference sheet. `--repeats N` runs (multiple
     11-sentence passes in the CSVs) each get their own sheet (`P2P3_Synthesis`,
     `P2P3_Synthesis_pass2`, ...) rather than only exporting the first pass — this was a deliberate
     change from the original one-pass-only spec, per explicit request. Wired into `do_tts.py` via
     `--export-xlsx` (opt-in, implies `--join`).
- Files: `profiling/parsing.py`, `profiling/sampler.py`, `profiling/join.py`, `do_tts.py`,
  `benchmark/export_to_xlsx.py` (new), `tests/test_profiling.py` (rail-parsing + join cpu/mem
  tests), `tests/test_export_xlsx.py` (new), `requirements-dev.txt`/`requirements-pi.txt` (added
  `openpyxl`), `.gitignore` (added `profile/exports/`), `README.md` ("Puissance par rail PMIC" +
  "Export Excel" sections), `docs/context/ARCHITECTURE.md`.
- Why: The PMIC's summed total conflates CPU and memory draw; splitting `VDD_CORE` (compute) from
  the DDR/1V1 rails (memory) lets a per-stage view show whether a given pipeline stage is CPU-bound
  or memory-bound. The Excel exporter removes a manual copy/reformat step before results can be
  pasted into the lab's master power-measurement workbook.
- Verify: `tests/` (71 tests, all passing) covers rail parsing (explicit list, missing-rail
  robustness, `EXT5V`/`BATT` exclusion), the join's new `cpu_*`/`mem_*` columns, and
  `export_to_xlsx`'s row-mapping/pass-splitting/REF-relabeling logic plus one real `openpyxl`
  round-trip (skipped cleanly if `openpyxl` isn't installed). End-to-end smoke test: synthetic
  `per_sample.csv` (11-sentence pass, all PMIC/rail/INA226 columns populated) through
  `profiling.join.run_join()` → `benchmark.export_to_xlsx.export()` — confirmed correct A-U values,
  `REF_start`/`REF_end` relabeling, and derived-column formulas (`RTF`, `synthP_W`, `E/s_Wh`,
  `cpuP_W`). Also verified the exporter degrades gracefully (prints an install hint, returns `None`,
  doesn't crash) with `openpyxl` uninstalled.
- Notes/gotchas:
  - `pmic_power_w`'s *value* is unchanged by making the rail list explicit — `EXT5V`/`BATT` were
    already excluded implicitly (they never have a current channel to pair with their voltage
    line). The explicit list guards against a future/unexpected rail silently joining the sum.
  - The paste-ready sheet layout assumes exactly 11 rows per pass; a trailing partial pass
    (interrupted run) is dropped with a printed warning rather than exported incomplete.
  - Not tested against real Pi 5 hardware (no PMIC/INA226 available in this dev environment) —
    `sampler.py`'s actual `vcgencmd`/I2C reads are excluded from the unit-tested surface, same as
    the existing PMIC/sysfs reads.

---

## 2026-07-10 — INA226 amp-branch telemetry in the profiler

- What: Extended the existing profiling subsystem (not a parallel logger) to capture the
  amplifier's 5V branch power alongside system PMIC power, so one `--benchmark --play` run
  measures both simultaneously, on the same shared `time.monotonic()` clock.
  1. `profiling/sampler.py`: auto-detects an INA226 at `i2c-1 @ 0x40` on startup
     (`_init_ina226()`, best-effort, never crashes the sampler); one 6-byte I2C block read per
     10 Hz tick (`_read_ina226()`, contiguous bus-voltage/power/current registers `0x02`-`0x04`);
     appends `ina_bus_v`, `ina_current_a`, `ina_power_w` to `profile/per_sample.csv`. New
     `--ina`/`--no-ina` CLI flag (default on; absence of the sensor just leaves the columns empty).
  2. `profiling/parsing.py`: pure, hardware-free INA226 register decode
     (`decode_ina226_bus_voltage_v`/`_current_a`/`_power_w`) plus the register/constant map
     (address `0x40`, `R_SHUNT=0.002`, `CURRENT_LSB=0.00025`, `CAL=10240`, config `0x4527`).
  3. `profiling/join.py`: generalized `_integrate_energy_j()` to take a `power_key` parameter
     (default `pmic_power_w`, unchanged for existing callers) and reused it for `ina_power_w`.
     `per_sentence_results.csv`/`per_stage_results.csv` gain `amp_energy_j`, `amp_energy_wh`,
     `amp_mean_w`, `amp_peak_w` alongside the untouched PMIC-derived system-energy columns.
  4. `profiling/__init__.py` (`start_session(ina=...)`) and `do_tts.py` (`--ina`/`--no-ina`,
     merged into `config_tts.yaml`'s new `profiling.ina226` key) wire the flag through, same
     pattern as `--postprocess`.
- Files: `profiling/sampler.py`, `profiling/parsing.py`, `profiling/join.py`,
  `profiling/__init__.py`, `do_tts.py`, `config_tts.yaml`, `requirements-pi.txt` (added
  `smbus2`, Pi-only, lazily imported inside `sampler.py`), `apt-packages-pi.txt` (added
  `i2c-tools` for `i2cdetect`), `tests/test_profiling.py` (INA226 decode tests + join `amp_*`
  column tests), `README.md` ("Profilage" section), `docs/context/ARCHITECTURE.md` (profiling
  subsystem section).
- Why: The PMIC (`vcgencmd pmic_read_adc`) only reports system-wide Pi power; a second INA226
  sensor was wired directly on the Pi's own I2C bus to isolate the amplifier breadboard's 5V
  branch draw, so compute cost and amplifier cost can be attributed separately per sentence.
- Verify: `tests/test_profiling.py` (52 tests, all passing) covers the register decode math and
  the join's `amp_*` aggregation with both present and absent INA226 samples. End-to-end smoke
  test: ran `profiling.join.run_join()` against a synthetic `per_sample.csv` with both
  `pmic_power_w` and `ina_power_w` populated — confirmed system and amp energies compute
  correctly and independently, per sentence and per stage. Not tested against real INA226
  hardware (no Pi/sensor available in this dev environment) — `sampler.py`'s actual I2C reads
  are excluded from the unit-tested surface, same as its existing PMIC/sysfs reads.
- Notes/gotchas:
  - No standalone `ina226_logger.py` reference file existed in the repo to match scaling
    against, despite an original task prompt assuming one did — implemented directly from the
    prompt's own register spec instead.
  - INA226 registers `0x02` (bus voltage), `0x03` (power), `0x04` (current) are contiguous, so a
    single 6-byte block read covers all three — this is what keeps the added per-tick I2C work to
    "one block read" as required, rather than three separate transactions.
  - Must not collide with the IQaudio DAC at `0x4c` on the same `i2c-1` bus — verify with
    `i2cdetect -y 1` before a session (documented in README).

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
