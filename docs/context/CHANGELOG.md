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

## 2026-07-20 — Reorg Phase 4: assets/docs cleanup — the four-phase reorg is functionally complete

- What: Phase 4 of `docs/REORG_PROPOSAL.md`'s migration plan, the last one.
  - `git mv` the five root demo WAVs (reclassified from delete-candidates to kept reference assets
    in an earlier review pass) into `assets/audio/reference/`.
  - `git mv audio_keyboards/Emmanuelle assets/audio/prompts/Emmanuelle`; updated
    `chatterbox/config/paths.py`'s `AUDIO_KEYBOARDS_DIR` constant to the new location — no code
    change needed in `chatterbox/gui/app.py` (the actual home of `play_prerecorded_phone()`,
    correcting `docs/REORG_PROPOSAL.md`'s original text which said `keyboards.py`), since it
    already read this path via `paths.py`.
  - `git mv tts_gui.png docs/assets/tts_gui.png`; updated the README image link.
  - Created `hardware/.gitkeep` (git doesn't track empty directories).
  - Full rewrite of `docs/context/ARCHITECTURE.md` (deferred since Phase 0's stale-banner
    workaround) — every module path, function name, and `profiling/`/`benchmark/`/`FastSpeech2/`
    reference updated to the post-reorg `chatterbox/`/`tools/`/`assets/models/` layout, technical
    substance (pipeline stages, control-tag mini-language, profiling/benchmark design) preserved
    unchanged. `README.md`'s path-bearing lines fixed the same way (Google Drive install targets,
    profiling/benchmark module paths, the image link). `CLAUDE.md` needed no further changes
    (already rewritten in Phase 3, verified still accurate). `INSTALL.md` needed no changes at all
    — it never hardcoded the paths that moved.
  - Brought the three items `docs/REORG_PROPOSAL.md` §4 flagged but didn't resolve
    (`graphify-out/`, the `profile/` experiment directories, the two deprecated requirements files)
    back to the user for an explicit keep/delete decision rather than deciding unilaterally.
- Files: `assets/audio/{reference,prompts}/` (new, via `git mv`), `chatterbox/config/paths.py`,
  `docs/assets/tts_gui.png` (new, via `git mv`), `hardware/.gitkeep` (new),
  `docs/context/ARCHITECTURE.md`, `README.md`, `docs/REORG_PROPOSAL.md`.
- Why: `docs/REORG_PROPOSAL.md` Phase 4 (Goal 1: 30-second clarity) — the last phase of the
  four-phase reorg plan.
- Verify: `pytest tests/` — 130 passed. Confirmed `paths.AUDIO_KEYBOARDS_DIR` resolves to the new
  location and a sample phoneme WAV exists there. Real end-to-end synthesis smoke test on Windows,
  unchanged from Phase 3.
- Notes/gotchas: **the reorg described across all four phases is now functionally complete**, but
  two things remain genuinely unverified because no session on this machine could ever check them:
  real interactive GUI testing (only a non-interactive, no-display `--gui` launch was possible —
  see the Phase 3 entry) and Pi 5 hardware verification (no Pi access at any point across all four
  phases). Treat the whole reorg as implemented and Windows-verified, not field-verified, until a
  real Pi 5 run happens — this is explicitly called out in `docs/REORG_PROPOSAL.md` §7 as the one
  verification step that can't be waived.

---

## 2026-07-20 — Reorg Phase 3: chatterbox/ package, class-based Synthesizer, GUI leak fix

- What: Phase 3 of `docs/REORG_PROPOSAL.md`'s migration plan — the largest and riskiest phase: a
  real behavioral refactor (module-level globals → class-owned state), not just file relocation,
  executed in full (not scoped down) despite touching the Tkinter GUI code this session has no way
  to test interactively (no display) — an explicit, disclosed risk tradeoff, not an oversight.
  1. **New `chatterbox/` package.** `chatterbox/synthesis/base.py` defines two ABCs, `Synthesizer`
     (acoustic model) and `VocoderBackend` (vocoder) — two, not one as originally sketched, because
     `config_tts.yaml`'s `tts_models`/`vocoder_models` are independently selectable today (the
     GUI's separate TTS/Vocoder buttons) and a single bundled `load()` would break that.
     `chatterbox/synthesis/registry.py` exposes `BACKEND`, a singleton
     `FastSpeech2HifiGanBackend` instance.
  2. **`loading_modules.py` + `synthesis_modules.py` → `backend.py` + `text_pipeline.py`.**
     `chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py`'s `FastSpeech2HifiGanBackend`
     class owns `tts_model`/`configs`/`flaubert_model`/`flaubert_tokenizer`/`vocoder_model`/
     `generator`/`h`/`vocoder_path` as instance attributes instead of module globals, but keeps its
     pre-Phase-3 method names (`load_fastspeech2`, `syn_hifigan`, etc.) so `config_tts.yaml`'s
     string-based dispatch needs zero changes. Does **not** literally subclass either ABC (Python
     can't have one class implement two same-named `load()` methods with different signatures) —
     the ABCs are the target shape for a future from-scratch backend (Matcha-TTS), documented in
     `base.py`'s own docstring. `text_pipeline.py` turned out not to be purely stateless as
     originally planned: `preprocess_styleTag()` needs the loaded FlauBERT model, and
     `parse_params_from_text()` was **re-reading `preprocess.yaml` from disk on every
     `<SPEAKER=name>` tag** instead of reusing the already-loaded config — the same leak
     `gui_utils.py:355` had for the GUI's speaker list, undiscovered until this file was read in
     full. Fixed identically in both places: pass the loaded config/model state in as explicit
     parameters instead of re-fetching it.
  3. **`audio_utils.py` → four files.** `chatterbox/audio/playback.py` (`play_audio()` +
     `AUDIO_EXAMPLE`, kept as a module attribute rather than eliminated since the GUI's "Play"
     button is a zero-argument Tkinter callback), `chatterbox/audio/denoise.py` (the inline
     `nr.reduce_noise()` call, now a real function), `chatterbox/synthesis/subtitles.py` (the five
     subtitle/alignment functions, unchanged), `chatterbox/cli.py` (`syn_audio()` orchestration +
     `butter_lowpass_filter()`).
  4. **`gui_utils.py` → `chatterbox/gui/app.py`, `keyboards.py` → `chatterbox/gui/keyboards.py`,
     `tts_utils.py` → `chatterbox/state.py`, `audio_postprocess.py` →
     `chatterbox/synthesis/audio_postprocess.py`.** `gui_utils.py:355`'s leak (see point 2) is
     closed: `gui_fastspeech2()` now calls `registry.BACKEND.describe_controls()["speaker_list"]`
     instead of re-parsing YAML.
  5. **`do_tts.py` → `chatterbox/cli.py` + a 3-line root shim.** All argparse/dispatch logic now
     lives in `chatterbox/cli.py:main()`; the CLI contract (every flag) is unchanged.
  6. **`config_tts.yaml`, the three regex-rule CSVs, and `paths.py` itself** moved into
     `chatterbox/config/` (paths.py) and `chatterbox/synthesis/backends/fastspeech2_hifigan/rules/`
     (CSVs).
  7. `git rm do_normalize_txt.pl` (confirmed dead, see the Phase 1 entry below / `docs/
     REORG_PROPOSAL.md` Sec4).
  8. Preventive fix before the big refactor started: `gui_utils.py`'s
     `os.path.join("audio_keyboards", ...)` hardcode now routes through a new
     `paths.AUDIO_KEYBOARDS_DIR`.
  - **Two more gaps found while executing this phase, same failure classes as Phases 1-2:**
    - `paths.py`'s own `ROOT = Path(__file__).resolve().parent` broke the moment `paths.py` moved
      into `chatterbox/config/` (two levels deeper) — caught immediately after the `git mv`, before
      it could break anything downstream, and fixed: `ROOT = Path(__file__).resolve().parents[2]`.
    - Phase 2 left six stale `-m benchmark.*` / `import audio_utils` references in
      `tools/measurement/benchmark/{p4_sweep,export_to_xlsx}.py`'s own docstrings/comments/error
      messages, plus a stale monkeypatch target (`runner.audio_utils`) in `tests/test_benchmark.py`
      — missed because Phase 2's cleanup checked for `-m profiling.*` patterns but not
      `-m benchmark.*`. Found via a repo-wide grep sweep done specifically because this session was
      asked to close out remaining Phase 2 concerns before starting Phase 3.
- Files: new `chatterbox/` package (synthesis/{base,registry}.py,
  synthesis/backends/fastspeech2_hifigan/{backend,text_pipeline}.py, audio/{playback,denoise}.py,
  synthesis/{subtitles,audio_postprocess}.py, gui/{app,keyboards}.py, state.py, cli.py,
  config/{paths,config_tts.yaml}.py, synthesis/backends/fastspeech2_hifigan/rules/*.csv); removed
  `loading_modules.py`, `synthesis_modules.py`, `audio_utils.py`, `gui_utils.py`, `keyboards.py`,
  `tts_utils.py`, `audio_postprocess.py`, `do_normalize_txt.pl`; `do_tts.py` reduced to a 3-line
  shim; `tools/measurement/benchmark/{runner,p4_sweep,export_to_xlsx}.py`,
  `tests/{test_benchmark,test_audio_postprocess,conftest}.py` updated for the new import paths.
- Why: `docs/REORG_PROPOSAL.md` Phase 3 (Goals 2 & 3: swappable acoustic-model backend, swappable
  GUI) — the interface boundaries §5 called for, plus closing out the config-reopening leaks found
  while implementing them.
- Verify: `pytest tests/` — 130 passed (the `SyntaxWarning`s from `synthesis_modules.py`'s non-raw
  regex escapes are also gone, an incidental behavior-neutral cleanup from rewriting that file with
  raw strings). Real end-to-end runs on Windows against the fully refactored backend: plain
  synthesis, `--benchmark --repeats 1 --export-xlsx` (benchmark → profiling → join → xlsx export in
  one pass), and a timed `--gui` launch — no display to see it, but the entire GUI creation path
  (model loading via the GUI buttons, the `describe_controls()`-based speaker list, every slider/
  radio-button widget, the on-screen keyboard) ran with zero tracebacks and reached
  `window.mainloop()`, blocking as expected until the timeout killed it.
- Notes/gotchas: this is the strongest GUI confirmation available without an interactive display,
  but **not equivalent to actually clicking through it** — real interactive GUI testing is still
  owed, on top of the standing no-Pi-5-access caveat from Phases 0-2. See `docs/REORG_PROPOSAL.md`
  Sec5 for the two design deviations (two ABCs not one; text_pipeline.py needing model state) in
  full, and Sec7/Phase 3 for the complete checklist. One known remaining gap, not yet fixed: a
  from-scratch backend without an `.AU` visual-animation channel (e.g. Matcha-TTS) would need
  `chatterbox/cli.py`'s `syn_audio()` changed to not assume one unconditionally — flagged as future
  work for whenever a second backend actually lands.

---

## 2026-07-20 — Reorg Phase 2: move benchmark/profiling into tools/, plus fixing Phase 1's open follow-up

- What: Two pieces of work.
  1. Closed the one open follow-up from Phase 1 (gitignored FastSpeech2 config YAMLs hardcoding
     `"FastSpeech2/…"` paths): `loading_modules.py` gained
     `_repoint_legacy_fastspeech2_config_paths()`, called right after `preprocess_config`/
     `train_config` load in `load_fastspeech2()`. It rewrites `preprocessed_path`/
     `output_syn_path`/`ckpt_path` in memory to `ROOT/assets/models/<value>` whenever the value
     still carries the legacy `"FastSpeech2/"` prefix — fixes this for a fresh
     `scripts/setup_pi.sh` download, a manual install, and this checkout alike, with no YAML
     hand-editing needed. Chosen over patching `setup_pi.sh` with a `sed` step because that would
     only cover the Pi provisioning path, not a manual install following the same README
     instructions.
  2. Phase 2 of `docs/REORG_PROPOSAL.md`'s migration plan: `git mv benchmark/
     tools/measurement/benchmark/`, `git mv profiling/ tools/monitoring/profiling/`, `git mv
     pmic_calibrate.py tools/measurement/`. Added `tools/__init__.py`,
     `tools/measurement/__init__.py`, `tools/monitoring/__init__.py`. Updated every
     `import`/`from` reference to the new dotted paths across `do_tts.py`, `audio_utils.py`,
     `synthesis_modules.py`, the moved packages' own cross-imports, and all four
     `tests/test_*.py` files that import them (existing aliases like `as profiling`/`as p4` kept,
     so only import lines changed).
  3. Found and fixed a second gap of the exact same class as Phase 1's (a directory-depth
     assumption baked into a path constant, broken by nesting the directory deeper):
     `tools/monitoring/profiling/__init__.py`'s `_PACKAGE_ROOT = os.path.dirname(os.path.dirname(
     os.path.abspath(__file__)))` assumed `profiling/` sat exactly one level under the repo root.
     Nesting it three levels deep silently broke the `subprocess.Popen(cwd=_PACKAGE_ROOT, ...)`
     call that launches the background sampler. Fixed: `_PACKAGE_ROOT = str(paths.ROOT)`.
- Files: `loading_modules.py`; `do_tts.py`, `audio_utils.py`, `synthesis_modules.py`; the `git mv`
  of `benchmark/` → `tools/measurement/benchmark/` and `profiling/` → `tools/monitoring/profiling/`
  and `pmic_calibrate.py` → `tools/measurement/pmic_calibrate.py`; new `tools/__init__.py`,
  `tools/measurement/__init__.py`, `tools/monitoring/__init__.py`; the moved packages' own
  cross-imports and self-referential usage strings; `tests/test_benchmark.py`,
  `tests/test_p4_sweep.py`, `tests/test_export_xlsx.py`, `tests/test_profiling.py`;
  `docs/REORG_PROPOSAL.md`.
- Why: `docs/REORG_PROPOSAL.md` Phase 2 (Goal 4, monitoring isolated as maintenance-only); the
  config-path fix closes the one thing Phase 1 explicitly left unresolved.
- Verify: `pytest tests/` — 130 passed. Re-verified the config-path fix by reverting the local
  YAMLs to their original stale, as-downloaded content and re-running a synthesis — confirmed the
  in-memory remap (not a lingering hand-edit) does the work. Exercised every Phase 2 code path
  directly: plain synthesis, `--profile` (a real `tools.monitoring.profiling` run directory was
  written with correct `per_sentence.jsonl`), `--benchmark --repeats 1` (all 11 sentences),
  `--join`, and `--export-xlsx` (the trickiest cross-import, `profiling.join` →
  `benchmark.export_to_xlsx`) — all succeeded. Deleted the test-generated `profile/run_*`
  directories afterward rather than leaving them in the tree.
- Notes/gotchas: no Pi 5 hardware access this round — the sampler subprocess launch string is the
  one Phase 2 change Windows genuinely cannot exercise (the sampler no-ops off-Linux before
  reaching that code), so it's the highest-risk item to merge blind, per
  `docs/REORG_PROPOSAL.md`'s retired amendment #8 note. Flagging the general pattern for Phase 3
  (nests files even deeper, under `chatterbox/synthesis/backends/fastspeech2_hifigan/...`): grep
  for other `dirname(dirname(...))`/`Path(__file__).parents[N]`-style constants across the whole
  tree before executing it, not just in the files being moved that phase — this is the second time
  a directory move has broken one.

---

## 2026-07-20 — Reorg Phase 1: move vendored model repos + weights under `assets/models/`

- What: Phase 1 of `docs/REORG_PROPOSAL.md`'s migration plan.
  - `git mv FastSpeech2 hifi-gan-master Waveglow flaubert assets/models/` — all four vendored
    dirs, including their gitignored weight files (~3.7 GB: FlauBERT `pytorch_model.bin`,
    Waveglow's `waveglow_NEB.pt`, HiFi-GAN's `g_00570000`), which the directory rename carried
    along automatically (confirmed present at the new paths after the move).
  - Re-pointed `config_tts.yaml`'s `folder` values (both TTS/vocoder entries and the
    commented-out Waveglow one), `scripts/setup_pi.sh`'s `fetch_and_unzip` targets/sentinels,
    `paths.py`'s vendored-dir + FlauBERT constants, and `.gitignore`'s FastSpeech2/hifi-gan-master/
    Waveglow/flaubert patterns to the new `assets/models/…` prefix.
  - Found and fixed two gaps only visible by actually running the pipeline post-move (not caught
    by the original static-analysis audit):
    1. `synthesis_modules.py` had a fourth CWD-relative `sys.path.insert(1,
       './Waveglow/tacotron2')` that Phase 0's checklist missed (it only named the three inserts
       in `loading_modules.py`). Post-move this broke `pytest tests/` collection with
       `ModuleNotFoundError: No module named 'audio_processing'` — the exact "same-named modules
       / sys.path insertion order" fragility already flagged in the proposal's §6, tripped for
       real. Fixed: routed through `paths.WAVEGLOW_DIR / "tacotron2"`.
    2. `assets/models/FastSpeech2/config/ALL_corpus/preprocess.yaml`
       (`path.preprocessed_path`, `path.output_syn_path`) and `train.yaml` (`path.ckpt_path`) each
       hardcode a literal `"FastSpeech2/…"` string, read as CWD-relative by
       `FastSpeech2/model/modules.py` / `utils/model.py`. These YAMLs are **gitignored**
       (downloaded from the Google Drive archives in `README.md`, never committed) — patched on
       this checkout only, to unblock verification. **Not a real fix**: a fresh
       `scripts/setup_pi.sh` run re-downloads the same stale-path archive and will hit this again.
       Left as an open follow-up in `docs/REORG_PROPOSAL.md` §6 (needs a decision: patch
       `scripts/setup_pi.sh` to `sed` these keys post-unzip, or make the FastSpeech2 code resolve
       them relative to `paths.FASTSPEECH2_DIR` instead of trusting them as full paths).
- Files: `paths.py`, `synthesis_modules.py`, `config_tts.yaml`, `scripts/setup_pi.sh`,
  `.gitignore`, plus the `git mv` of `FastSpeech2/`, `hifi-gan-master/`, `Waveglow/`, `flaubert/`
  into `assets/models/`. (Also two gitignored, untracked local edits — see above — that do not
  show up in `git status` and are not part of this commit.)
- Why: `docs/REORG_PROPOSAL.md` Phase 1 — code vs. non-code separation (Goal 5), lowest
  coupling-risk directory move in the reorg.
- Verify: `pytest tests/` — 130 passed (after fix 1). Real end-to-end smoke test on this Windows
  checkout (after fix 2): FlauBERT, FastSpeech2 (`assets/models/FastSpeech2/390000`), and HiFi-GAN
  (`assets/models/hifi-gan-master/FR_V2/g_00570000`) all loaded via the moved paths;
  `audio_file.wav` produced with normal per-stage timing.
- Notes/gotchas: no Pi 5 hardware access this round — Windows-verified only, per
  `docs/REORG_PROPOSAL.md`'s retired amendment #8 note. The config-YAML issue (gap 2 above) is the
  one item in this phase that isn't actually resolved yet, just worked around locally — flag it
  before Phase 4 closes the reorg out, since it will bite a fresh Pi provisioning run exactly the
  same way it bit this one.

---

## 2026-07-20 — Reorg Phase 0: repo-root-anchored path resolution (`paths.py`)

- What: Phase 0 of `docs/REORG_PROPOSAL.md`'s migration plan — de-risk path resolution before any
  directory moves. Added a temporary root-level `paths.py` module (`ROOT =
  Path(__file__).resolve().parent`, i.e. anchored to the file's own location, not the process's
  CWD) and routed every CWD-relative path through it:
  - `loading_modules.py`'s three `sys.path.insert(1, "./FastSpeech2")` / `"./hifi-gan-master"` /
    `"./Waveglow"` calls now use `paths.FASTSPEECH2_DIR` / `paths.HIFIGAN_DIR` /
    `paths.WAVEGLOW_DIR`.
  - `synthesis_modules.py`'s three regex-rule file constants (`regex_file`,
    `symbols_regex_file`, `url_regex_file`) now resolve via `paths.CUSTOM_REGEX_RULES` /
    `paths.SYMBOLS_REGEX_RULES` / `paths.URL_REGEX_RULES` instead of bare CWD-relative filenames.
  - `FastSpeech2/utils/model.py`'s hardcoded `modelname = './flaubert/flaubert_large_cased'`
    (bypassed `config_tts.yaml` entirely, CWD-relative) now uses `paths.FLAUBERT_DIR`.
  No directories moved yet — this phase only changes how existing paths are computed, so
  `do_tts.py` still must be run with the repo as the working directory today; the payoff is that
  Phase 1+'s directory moves become a matter of updating `paths.py`'s constants instead of hunting
  down scattered CWD-relative strings.
- Files: `paths.py` (new), `loading_modules.py`, `synthesis_modules.py`,
  `FastSpeech2/utils/model.py`.
- Why: `docs/REORG_PROPOSAL.md` §6 flagged CWD-relative `sys.path.insert` as the highest-risk item
  in the whole reorg — every subsequent phase that moves `FastSpeech2/`, `hifi-gan-master/`,
  `Waveglow/`, `flaubert/`, or the regex-rule CSVs would silently break without this fix landing
  first.
- Verify: `pytest tests/` (130 passed, unchanged). Real end-to-end smoke test on this Windows
  checkout (real weights present locally): `printf 'Bonjour, ceci est un test.\n' | python
  do_tts.py` — FlauBERT, FastSpeech2 (`390000`), and HiFi-GAN (`FR_V2/g_00570000`) all loaded via
  the new anchored paths, text normalization (which reads the regex-rule CSVs) ran correctly, and
  `audio_file.wav` was produced with normal timing (TTS 0.291s / vocoder 0.507s / denoise 0.117s
  for the one sentence).
- Notes/gotchas: no Pi 5 hardware access for this session, so this phase is **Windows-verified,
  Pi-unverified** — real hardware validation is still needed before this is considered fully safe,
  per `docs/REORG_PROPOSAL.md`'s note on the retired "Pi-mandatory" amendment. `paths.py` is
  intentionally a temporary root-level module (not yet under a `chatterbox/` package, which doesn't
  exist until Phase 3) — see the proposal doc for the full phased plan.

---

## 2026-07-17 — Compare the two full P4 sweeps: reproducible P_idle, thermal-dependent k

- What: ran a full 6-point P4 sweep twice back-to-back on real Pi 5 hardware
  (`profile/P4 - First Full try/`, `profile/P4 - Second Full try/`, ~40 min apart, same
  `calibration.json`/governor/brightness/duration/sentence set). Compared them point-by-point
  to check the experiment is reproducible before trusting either fit.
  - **Idle/low load (cadence 0, 1, 2/min) reproduces tightly**: `p_use_profiler_w` and
    `p_use_meter_w` agree within ≤1.7% between the two runs — the protocol itself is solid.
  - **A real thermal effect at higher load (cadence 5, 10, max)**: run 2 measured
    consistently *cooler* (`peak_temp` −3.4% to −4.9%) and drew correspondingly *less* power
    (`p_use_profiler_w`/`p_use_meter_w` −4% to −7.5%) than run 1 at the same cadence points,
    with `mean_arm_freq_khz` essentially identical between runs (rules out frequency scaling
    as the cause) and `amp_mean_w` barely moving (rules out the amplifier). Consistent with
    CPU leakage current dropping with die temperature at a fixed clock/workload, not a
    protocol or code fault — `n_utterances`/`duty_active` matched to 3 decimals between runs,
    so the two runs drove genuinely identical workloads.
  - Consequence: the fitted **intercept `P_idle` is reproducible** (profiler 5.549 W vs
    5.590 W, meter 5.437 W vs 5.454 W — within ~1%), but the fitted **slope `k` is not**
    (profiler 0.190 vs 0.139 W/(utt/min), meter 0.231 vs 0.177 W/(utt/min) — ~25-30% apart)
    despite both individual fits reporting R² ≥ 0.996. A single sweep's R² does not capture
    this run-to-run thermal variance.
  - Pooled fit across all 12 points (both runs together):
    **profiler P_idle=5.570 W, k=0.164 W/(utt/min), R²=0.955**;
    **meter P_idle=5.446 W, k=0.204 W/(utt/min), R²=0.963** — still clears the 0.95 flag
    threshold and matches each run's individual intercept closely; recommended as the working
    number over either single run's `k`.
  - Also noted (same sign pattern in both runs, so systematic not noise): `discrepancy_pct`
    is positive (profiler > meter) at low cadence and negative (profiler < meter) at high
    cadence in both runs — likely the 4-point static-load PMIC→meter calibration curve
    mildly under/over-fitting outside its calibration range, not a bug.
- Files: no code changes; analysis of `profile/P4 - First Full try/` and
  `profile/P4 - Second Full try/` (`sweep_summary.csv`, `meta.json`, `per_sample.csv` row
  counts). Both directories' `sweep_paste.xlsx` already use the fixed 16-column layout from
  the entry below.
- Why: before trusting a single sweep's `P_use = P_idle + k·N` formula for the daily energy
  budget, wanted to confirm it's reproducible run-to-run rather than a one-off fit.
- Verify: per-point diff table computed directly from both `sweep_summary.csv` files;
  `mean_arm_freq_khz` cross-checked to rule out frequency scaling; pooled fit computed by
  concatenating both runs' rows and reusing `benchmark.p4_sweep._linear_fit()` unmodified.
  Sampler health double-checked (~6000 `per_sample.csv` rows at 10 Hz over 600 s, no dropped
  samples, `throttled_any=False`) at every point in both runs.
- Notes/gotchas: **the master `P4_Conversational` sheet's fixed 6-row template (one block per
  sweep) can only hold one run's block as literal values at a time.** To merge both runs into
  one more-robust estimate: either (a) stack both 6-row blocks (12 rows total) and re-point
  the sheet's fit formulas at the combined range, or (b) if the sheet only accepts exactly 6
  rows, average each matching cadence pair row-by-row before pasting — but (b) hides exactly
  the signal that matters here (that `k` is thermal-state-dependent), so (a) is preferred if
  the sheet can be adapted. Either way, the ~25-30% k spread should be flagged in the sheet
  (e.g. a note on the cadence 5/10/max rows) rather than silently presenting a single run's
  `k` as the final number. If a third sweep is run, record ambient/room temperature (not just
  screen brightness) alongside each point, and consider randomizing cadence order across
  sweeps to decorrelate within-sweep thermal soak from the cadence variable itself.

---

## 2026-07-17 — Fix `sweep_paste.xlsx` column layout (didn't match the master tracking workbook)

- What: the first full real sweep (`--cadences 0,1,2,5,10,max --duration 600`, all 6 points,
  ~1h on real Pi hardware) completed cleanly end-to-end with sane data throughout (peak temp
  rising 49→79°C with load, `throttled_any` false at every point, `cadence_achieved` tracking
  `cadence_requested` closely up to 5/min and visibly saturating at 10 and `max` as expected,
  profiler/meter `p_use` agreeing within ±4.25%) — no bug in the measurement pipeline itself.
  But `sweep_paste.xlsx` was unusable for its actual purpose: the user's pre-built master
  "P4_Conversational" tracking sheet expects a 16-column block (`A:P` — `cadence_req`,
  `cad_achiev`, `dur_h`, `n_utt`, `totalis_Wh`, `P_use_met_W`, `P_use_prof_W`, `discrep_%`,
  `duty_synth`, `duty_play`, `duty_active`, `amp_mean_W`, `cpu_mean_W`, `mem_mean_W`, `peak_C`,
  `throttled`), while `_write_paste_xlsx()` only ever wrote the 6-column
  `["run", "cadence_achieved", "duration_h", "totaliser_wh", "p_use_w", "duty_active"]` layout
  from the original implementation — a scope reduction I made during the initial `--p4-sweep`
  build that never matched what the downstream master workbook actually needed. Not a data
  problem, not user error: `sweep_summary.csv` already had every column needed, it just wasn't
  the file being pasted.
  Rewrote `PASTE_COLUMNS` and `_write_paste_xlsx()` to emit exactly the master sheet's 16
  columns, in order, one-to-one off `sweep_summary.csv`'s fields (unit conversions only for
  `dur_h`/`totalis_Wh`, same as before). Dropped the old merged `p_use_w`
  meter-falls-back-to-profiler column — no longer needed now that `P_use_met_W` and
  `P_use_prof_W` are separate columns matching the sheet, so a skipped totaliser reading now
  correctly leaves only `P_use_met_W` blank instead of silently substituting the profiler
  value into a column labeled "meter". Also dropped the `run` column (not present in the
  master sheet at all).
- Files: `benchmark/p4_sweep.py`, `tests/test_p4_sweep.py`
- Why: `sweep_paste.xlsx` exists solely to be copy-pasted as one block into the master
  workbook; a column mismatch makes every number land in the wrong field silently (no error,
  just wrong data if pasted as-is), which is worse than a crash.
- Verify: `python3 -m pytest tests/` (130 passed — `test_write_paste_xlsx_column_layout_matches_master_workbook`
  rewritten for the 16-column layout, asserts the header row, column count, and the
  no-fallback blank-totaliser behavior). Regenerated `sweep_paste.xlsx` for the real
  `profile/P4 - First Full try/` run via `python -m benchmark.p4_sweep --refit "profile/P4 -
  First Full try"` (the existing `--refit` re-entry point doubles as the "rebuild
  sweep_paste.xlsx from already-collected results" tool — no new script needed) and confirmed
  by hand: 16 columns, 6 data rows (`A2:P7`), values correctly split between `P_use_met_W` and
  `P_use_prof_W`.
- Notes/gotchas: the fitted `P_idle` from this first full sweep: profiler 5.549 W (k=0.190 W
  per utt/min, R²=0.9995), meter 5.437 W (k=0.231 W per utt/min, R²=0.9994) — both series fit
  well and agree with each other within ~2%, a good sign the additive model
  `P_use = P_idle + k·N` holds for this system. No flags raised (R² well above 0.95, fitted
  intercept within 5% of the direct cadence=0 measurement on both series).

---

## 2026-07-17 — Fix P4 sweep crash on the cadence=0 idle point

- What: the first real dry run (`--p4-sweep --cadences 0,30 --duration 30`) crashed
  immediately on the very first point:
  `[join] profile/p4_sweep_.../cadence_00/per_sentence.jsonl not found - nothing to join.`
  Root cause: `cadence=0` (the pure-idle anchor) synthesizes nothing at all, so
  `per_sentence.jsonl` is never created (`Recorder` only writes it from `finalize()`, never
  called with zero utterances) — but `run_p4_sweep()` unconditionally called `run_join()` for
  every point, and `profiling/join.py`'s `load_sentences()` treats a missing
  `per_sentence.jsonl` as a hard `SystemExit` by design (a deliberate choice from an earlier
  session, correct for the *standalone* `python -m profiling.join` case where it really does
  mean "nothing was profiled"). Uncaught, this killed the entire sweep on point 1 — before
  cadence=30 (the actual thing under test in that dry run) ever ran.
  Extracted the join-or-skip decision into `_join_cadence_point(cadence, cadence_dir)`:
  skips the (sentence-only) join entirely for `cadence == 0` (expected, not an error —
  `join_full_session()`, called separately right after, doesn't touch `per_sentence.jsonl` at
  all, so the point's whole-session power/energy aggregates are unaffected), and wraps the
  non-zero-cadence case in `try/except SystemExit` as a backstop — an hour-long unattended
  sweep should degrade one point's `synth_time_total_s` to 0 with a printed warning rather
  than crash and lose every point after it.
- Files: `benchmark/p4_sweep.py`, `tests/test_p4_sweep.py`
- Why: this exact crash would have hit every real sweep, since `0` is cadence #1 in the
  documented example (`--cadences 0,1,2,5,10,max`) and in the dry-run recipe I gave after
  implementing the feature — untested against real hardware from the dev machine, so this
  surfaced on the first actual run rather than in review.
- Verify: `python3 -m pytest tests/` (130 passed — 3 new:
  `test_join_cadence_point_skips_join_for_cadence_zero` confirms no `SystemExit` and no
  `per_sentence_results.csv` written for `cadence=0` with no data;
  `test_join_cadence_point_still_raises_join_for_nonzero_cadence_with_no_data` confirms the
  backstop still warns loudly for the *unexpected* case of a non-zero cadence somehow
  producing zero utterances; `test_join_cadence_point_runs_normally_when_data_exists` confirms
  normal joins are unaffected).
- Notes/gotchas: **still not verified end-to-end on real hardware** — this fixes the specific
  crash observed, but the `cadence=30` point (which never ran in the reported dry run) is
  still unverified. Traced through it by hand: with real `benchmark/sentences_fr.jsonl`
  sentences and a 2s slot (60/30), several sentences' synth+playback time will legitimately
  exceed 2s, so the `warn_once` "cadence not achievable" message firing during that point is
  *expected*, not a bug. Re-run the same dry run
  (`--p4-sweep --cadences 0,30 --duration 30`) to confirm both points now complete and
  `sweep_summary.csv`/`sweep_paste.xlsx` land correctly (2 points → `R²` will read exactly
  1.0, per the note in the previous entry — expected for a 2-point fit, not a bug).

**Follow-up, same session**: the re-run (`--cadences 0,30 --duration 30`) completed end to
end on real Pi hardware — both points, the fit, and `sweep_paste.xlsx` all produced.
Cross-checked the printed numbers independently (recomputed `p_use_meter_w`'s implied
`duration_s` from the raw totaliser entries, recomputed `cadence_achieved` from
`n_utterances`/`duration_s`, refit the line from the raw values) — everything reproduces
exactly. One point header text was misleading rather than wrong: `"expected ~15
utterances"` for the `cadence=30` point (which only reached 7, since 30/min was never
achievable for this sentence set at ~4-5s synth+playback each — same fact the
`cadence not achievable` warning already reported) read like a broken prediction rather than
a best-case ceiling. Reworded to `"up to N utterances if fully achievable"` in
`benchmark/p4_sweep.py`, with a comment explaining `cadence_achieved` (not this figure) is
what actually gets fitted. No behavior change, no new test needed for a print string.

---

## 2026-07-16 — Add P4 cadence sweep (`--p4-sweep`)

- What: new experiment measuring how average system power `P_use` varies with conversational
  rate (utterances/minute), fitting `P_use(N) = P_idle + k·N`. Ran the design through a Plan
  subagent review against the actual files before implementing; it found and this fixes four
  real correctness gaps beyond the original spec:
  1. **Calibration lookup would have silently gone uncalibrated.** `profiling/join.py`'s
     `load_calibration()` only checks one directory up from wherever it's asked to join.
     `profile/calibration.json` is two levels above a cadence dir
     (`profile/p4_sweep_.../cadence_02/`), so it would have missed it entirely and silently
     fallen back to identity scale/offset for every sweep point, with no error. Fixed by
     copying `calibration.json` into the sweep root once at sweep start, not by touching
     `join.py`'s lookup (kept `run_join()` fully unmodified).
  2. **`mean_arm_freq_khz` (a spec'd summary column) was unparseable.** `load_samples()` never
     read `arm_freq_hz` from `per_sample.csv` at all, despite the sampler always writing it.
     Added as an additive, `None`-safe column parse alongside the existing ones.
  3. **An hour-long, unattended, human-in-the-loop sweep must not lose completed points on a
     later Ctrl-C.** `sweep_summary.csv` is now appended to after every point, not buffered to
     a single write at the end; each point's profiling session is wrapped in its own
     `try/finally` so `profiling.stop_session()` always runs even if a point is interrupted
     mid-cycle.
  4. **Meter-vs-profiler window mismatch is structural** (the totaliser is reset before the
     sampler subprocess launches and read after it stops, so its bracket is always slightly
     wider) — not fixable without fighting the "human reads an external meter" constraint;
     documented in the README instead of engineered around.
  - `profiling/__init__.py`: factored `_new_run_dir()`'s meta.json-writing into `_write_meta()`
    and `start_session()`'s sampler-subprocess launch into `_launch_sampler()` (both reused,
    behavior-preserving — existing `start_session()`/`_new_run_dir()` tests pass unchanged).
    New `start_session_at(run_dir, ...)`: like `start_session()` but writes into a
    caller-specified directory instead of auto-generating a `run_YYYYMMDD_HHMMSS` name, and
    deliberately never touches `profile/latest` (that pointer means "the last single
    benchmark/free-text run", not a sweep sub-point). `calibration_base_dir` is passed
    explicitly to `_write_meta()` rather than derived from `run_dir`'s path — the fix for gap
    #1's root cause at the `meta.json`-informational-field level.
  - `profiling/join.py`: `load_samples()` now also parses `arm_freq_hz` (gap #2). New
    `join_full_session(profile_dir)`: like `run_join()` but integrates the *whole*
    `per_sample.csv` window (first to last `t_mono`) instead of per-sentence windows, reusing
    the same calibration/integration helpers (`_integrate_energy_j`, `_mean_power_w`,
    `_stat_or_none`, `_throttled_any`) — this is what makes `cadence=0` (zero sentences, no
    `per_sentence.jsonl` at all) work uniformly with every other point.
  - New `benchmark/p4_sweep.py` (mirrors `benchmark/runner.py`'s style): `parse_cadences()`,
    `cadence_dir_name()`, `run_p4_sweep()` (the per-point cycle loop, prompts, summary-row
    computation, linear fit + R² + flagging, `sweep_paste.xlsx` writer), plus a standalone
    `--refit SWEEP_DIR` re-entry point (re-reads an existing `sweep_summary.csv` and redoes
    only the fit + xlsx write, no hardware re-run — matches the same "expensive measurement
    pass vs. re-runnable offline analysis pass" convention already used by `profiling/join.py`
    and `benchmark/export_to_xlsx.py`'s own standalone `main()`s).
  - `do_tts.py`: new `--p4-sweep`/`--cadences`/`--duration` flags, dispatched next to
    `--benchmark`. `--cadences`/`--duration` are validated eagerly right after `argparse`
    (same spot as the existing `--report-wav` early-exit) — a malformed value fails before
    `load_models()` and the first interactive prompt, not deep into an unattended hour. The
    existing top-level `profiling.start_session()` call is skipped for `--p4-sweep` (the sweep
    manages its own per-point sessions via `start_session_at()`) but `profiling.enable()`/
    `set_output_dir()` still run, since `start_session_at()` depends on both.
  - `play_time_total_s` (not separately timestamped anywhere in the existing `Recorder`, and
    intentionally not added there per "do not touch synthesis logic") is derived as
    `sum(busy_i) - synth_time_total_s`, where `busy_i` is the sweep loop's own
    `time.monotonic()` bracket around each whole `syn_audio(..., play=True)` call (confirmed
    `play_audio()` blocks on every platform branch, so this genuinely covers synth+playback).
    Guarded with a defensive length check against `per_sentence_results.csv`'s row count —
    `None` + a printed warning on a mismatch, never a silent mis-sum.
- Files: `profiling/__init__.py`, `profiling/join.py`, `benchmark/p4_sweep.py` (new),
  `do_tts.py`, `tests/test_p4_sweep.py` (new), `tests/test_profiling.py`, `README.md`
- Why: last power experiment in the measurement suite — no longer choosing a battery board
  (decided: DFRobot FIT0992), now characterising each process's power contribution for later
  optimisation and producing a formula that converts any usage model into a daily energy
  budget.
- Verify: `python3 -m pytest tests/` (full suite green — 24 new tests in `test_p4_sweep.py`
  covering cadence parsing/naming, the synth/play time split, the linear fit + R² + flagging
  against synthetic series, the `sweep_paste.xlsx` column layout and meter-vs-profiler
  precedence, and the `--refit` round-trip; 9 new tests in `test_profiling.py` covering
  `start_session_at()`'s calibration resolution two levels deep and that it never touches
  `profile/latest`, plus `join_full_session()` against synthetic `per_sample.csv` including
  the empty/single-sample edge cases). Manually verified end-to-end with real (non-hardware)
  data: `parse_cadences`/`cadence_dir_name`/`_linear_fit` recover the spec's own sanity-check
  formula (`P_use = 5.73 + 0.072·N`) exactly from synthetic points; `_build_summary_row` →
  `_append_summary_row` → `_load_summary_rows` → `_refit_from_summary` round-trips correctly
  through a real CSV + xlsx write. `do_tts.py --help` and eager `--cadences` validation
  (`do_tts.py --p4-sweep --cadences 0,foo --duration 600`) both confirmed to fail fast with a
  clear message, before any model loading.
- Notes/gotchas: **cannot be verified against real hardware from this dev machine** (no I2C
  bus, no Pi, no actual amplifier/meter) — the cycle loop, `profiling.start_session_at()`
  launching the real sampler subprocess, and the full interactive prompt flow all still need a
  real run on the Pi. Suggested first real test: a short `--duration 30 --cadences 0,30` dry
  run (covers both the pure-idle and a numeric-cadence code path in under a minute) before
  committing to a full multi-hour sweep.

---

## 2026-07-16 — Fix export_to_xlsx.py for per-run profile/ directories

- What: `benchmark/export_to_xlsx.py` still defaulted `--profile-dir` to the base `profile`
  and read `profile/per_sentence_results.csv` directly — missed when per-run output
  isolation (`profile/run_YYYYMMDD_HHMMSS/`) was added, since that change only updated
  `profiling/join.py`'s standalone entry point and `do_tts.py`'s in-process call, not this
  script's own separate CLI. Standalone `python -m benchmark.export_to_xlsx` therefore raised
  a raw `FileNotFoundError` (the file has never lived directly under `profile/` since that
  change) instead of finding the actual run.
  1. `load_per_sentence_rows()`: missing `per_sentence_results.csv` now raises a clear
     `SystemExit` instead of a raw traceback.
  2. `main()`'s `--profile-dir` now defaults to `None` and resolves via the new
     `_resolve_profile_dir()`: follows `profile/latest` (symlink or the `latest.txt`
     Windows-without-symlinks fallback) if it points at a run that actually has
     `per_sentence_results.csv` (i.e. was `--join`'d, not just profiled).
  3. If `profile/latest` isn't usable (missing, stale, or points at an unjoined run),
     `_resolve_profile_dir()` lists every `profile/run_.../` directory that *does* have
     results (most recent first, via the new `profiling.list_run_dirs()`) and interactively
     prompts which one to export — the "ask for the name of the file" behavior requested,
     rather than failing outright when there's more than one candidate or no usable default.
     `export()` itself (the programmatic entry point `do_tts.py --export-xlsx` calls
     in-process, always with an explicit resolved dir) is untouched and never prompts.
- Files: `benchmark/export_to_xlsx.py`, `profiling/__init__.py` (new `list_run_dirs()`,
  shared with the picker), `tests/test_export_xlsx.py`
- Why: closes the same class of gap as the `profiling/join.py` fix from earlier today, in
  the one standalone entry point that was missed at the time.
- Verify: `python3 -m pytest tests/` (94 passed — 9 new: explicit-arg passthrough, following
  both forms of the `latest` pointer, rejecting a `latest` that points at an unjoined run,
  the interactive prompt (via `monkeypatch` on `builtins.input`) including its
  most-recent-first default and skipping unjoined runs, the no-runs-at-all error, and the
  missing-file `SystemExit`). `python -m benchmark.export_to_xlsx --help` shows the updated
  flag description.
- Notes/gotchas: `_resolve_profile_dir()` is only wired into `main()` (the CLI), not
  `export()` — deliberately, since `export()` is also called in-process by `do_tts.py`
  right after a benchmark run and must never block on `input()` there.

---

## 2026-07-16 — INA226 fix verified on real Pi hardware, both run modes

- What: the register-read fix (two separate single-register reads instead of one combined
  6-byte block read — see the entry directly below) confirmed working end-to-end on the Pi,
  across two separate runs:
  1. `python3 do_tts.py --profile` (idle, no synthesis): `ina_current_a` held at
     0.0625/0.06375 A throughout ~2000 samples, `ina_bus_v` tracked load realistically
     (5.00-5.19V), `ina_power_w` matched `ina226_logger.py`'s reference reading (~0.32 W)
     almost exactly. Zero occurrences of the old stuck `-0.00025` (-1 LSB) value.
  2. `python3 do_tts.py --benchmark --profile --join --repeats 1` (real synthesis, CPU
     spiking to 90-100% repeatedly, no `--play`): same idle-band current throughout — correct,
     since without `--play` the amp is never actually driven, so it's expected to stay flat
     while `pmic_power_w`/`cpu_power_w` swing widely from the synthesis load. Spot-checked the
     software power derivation directly against several rows: `5.045 * 0.065 = 0.327925`,
     `5.055 * 0.065 = 0.328575`, `5.05875 * 0.06375 = 0.3224953125` — each matches the logged
     `ina_power_w` exactly, confirming `bus_v * current_a` is wired correctly on real hardware,
     not just in the `_FakeInaBus` unit tests.
- Files: none (verification only, no code changes this entry)
- Why: closes out the INA226 investigation started with Blocker 1 of the original profiler
  prompt — three sessions (software power derivation, register read-back diagnostic, then the
  actual root-cause fix) needed real hardware to confirm, which wasn't available from the dev
  machine that wrote the fixes.
- Verify: already done — see "What" above. No further action needed on the INA226 side.
- Notes/gotchas: none outstanding. If amp-branch current/power ever looks wrong again, the
  regression tests in `tests/test_profiling.py` (`_FakeInaBus`, asserting every INA226 read is
  a single 2-byte transaction) should catch a reintroduction of the combined-block-read bug
  before it reaches hardware again.

---

## 2026-07-16 — Actual INA226 root cause found: no cross-register auto-increment

- What: root-caused by diffing `_read_ina226()` against `ina226_logger.py` (the standalone
  reference script, user-provided, confirmed correct on real hardware -
  `test_repair.csv` shows steady 0.0625 A / 0.319 W at idle). `ina226_logger.py` reads bus
  voltage, current, and power as **three separate single-register transactions**, each its
  own `read_i2c_block_data(addr, reg, 2)`. `_read_ina226()` instead did **one combined 6-byte
  block read** starting at BUS_V (0x02), assuming the INA226 auto-increments its internal
  register pointer across BUS_V -> POWER -> CURRENT within a single transaction. It doesn't.
  That's the entire bug, in both this session's data and every prior session's: bus voltage
  (the first, correctly-addressed register) always decoded fine and tracked load, because
  it's the only register actually being read correctly; the bytes assumed to be POWER and
  CURRENT are the chip's over-read filler, which happens to decode to exactly 0xFFFF,
  regardless of actual current - explaining both the original "409.6 W constant" symptom
  *and* the "current frozen at -1 LSB" symptom that survived the previous session's software
  power-derivation fix (which only changed how an unread, always-0xFFFF current value got
  turned into a power number). The write side was never the problem - both scripts write
  CONFIG/CALIBRATION identically - so the read-back diagnostic added last session was a
  reasonable diagnostic to add but wasn't pointing at the actual bug; left in place since it's
  still a legitimate sanity check, just not the one that mattered here.
  `_read_ina226()` now calls `_read_ina226_reg()` (added last session for the read-back check)
  twice - once for BUS_V, once for CURRENT - instead of one combined block read. POWER is
  still not read from hardware at all (software `bus_v * current_a`, from the prior session,
  is still correct and cheaper than a third register read).
- Files: `profiling/sampler.py`, `tests/test_profiling.py`
- Why: the previous two sessions' fixes addressed real but secondary issues (power-register
  reliability, diagnostic messaging) without touching the actual read-path bug, because
  neither could be tested against real I2C hardware from this dev machine. Having the
  known-working reference script to diff against made the real cause immediately visible.
- Verify: `python3 -m pytest tests/` (85 passed - 2 new). Added
  `test_read_ina226_reads_bus_voltage_and_current_as_separate_registers` and
  `test_read_ina226_decodes_negative_current`, using a fake I2C bus
  (`_FakeInaBus`) that serves each register independently and **asserts any read call has
  length 2** - a regression back to a combined block read fails the test loudly instead of
  silently reintroducing the bug. Confirmed the fake-bus call log shows exactly two
  single-register reads, not one wider one.
- Notes/gotchas: still needs confirmation on the Pi with real hardware - the fake-bus test
  proves the *code* now does two separate reads and decodes them correctly, not that the
  physical sensor responds as expected end-to-end. Run a short `--profile`-only session and
  check `ina_current_a`/`ina_power_w` land near 0.0625 A / ~0.32 W at idle, matching
  `ina226_logger.py` on the same rail.

---

## 2026-07-16 — INA226 still broken after the previous fix; add register read-back diagnostic

- What: a real `--benchmark --profile --join` run on the Pi (the "7B" dry run, 11 records,
  `profile/run_20260716_162448/`) confirmed the previous session's INA226 fix did **not**
  resolve the root cause: `ina_current_a` is still frozen at exactly `-0.00025` (-1 LSB /
  0xFFFF) on every one of ~2000 samples across the whole run, regardless of load, even though
  `ina_bus_v` reads correctly and dynamically (5.03-5.19V, sags under load - that channel
  genuinely works). The startup sanity check added last session did correctly fire (`[profiling]
  WARNING: INA226 reads ~0 A ...`), which disproves the previous CHANGELOG entry's guess that
  the Pi might have been running a stale pre-fix revision - this **is** the current code, and
  the sensor communication issue is real. Also found and fixed a bug in that sanity-check
  message itself: it passed 5 positional args to a 4-placeholder format string, so `.format()`
  silently dropped the trailing `CAL` argument and the bare `{}` placeholder printed
  `INA226_CONFIG` (0x4527) in **decimal** (17703), mislabeled as the calibration value at
  register 0x05 - actively misleading for exactly the debugging this message exists for.
  Fixed the message, and added a real diagnostic instead of more guessing: `_write_ina226_reg`/
  `_read_ina226_reg` helpers, with a read-back of CONFIG and CALIBRATION immediately after
  writing them, logging `[profiling] WARNING: INA226 register read-back mismatch ...` if what's
  actually stored on the chip doesn't match what was intended. This turns "is the write even
  taking effect?" from a guess into a directly observable fact on the next run.
- Files: `profiling/sampler.py`
- Why: the previous fix (software power derivation from bus_v*current_a) only changed how an
  already-invalid current reading gets turned into a power number - it never addressed why
  CURRENT itself never produces a valid conversion. Needed a way to actually see whether the
  CONFIG/CALIBRATION writes are landing on the chip rather than continuing to guess between
  read-timing, wrong smbus2 API framing for this device, bus contention, etc.
- Verify: `python3 -m pytest tests/` (83 passed, unaffected - this is real-hardware-only code,
  no unit coverage possible without an actual INA226). Manually reproduced the exact
  malformed-message bug from the Pi's terminal output on this dev machine by replaying the same
  `.format()` call with the same arguments - confirmed byte-for-byte match to the observed
  "17703 @ reg 0x05" text, and confirmed the corrected messages render sensibly.
- Notes/gotchas: **still unresolved, needs a short profiler-only run on the Pi** to read the new
  read-back diagnostic. If it reports a mismatch, the write itself is the problem (candidates:
  `write_i2c_block_data`'s exact wire framing for this device vs. what `ina226_logger.py` - the
  known-working reference script - does; worth diffing the two directly). If CONFIG/CALIBRATION
  *do* read back correctly and current is still frozen, the bug is downstream of configuration
  entirely (e.g. conversion never actually triggering in continuous mode) and the read-back
  check won't be enough on its own - would need scoping further with `ina226_logger.py`'s
  working register sequence as the reference.

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
