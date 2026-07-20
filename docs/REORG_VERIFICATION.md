# Chatterbox Reorg — Verification Protocol

Purpose: close out the two things `docs/REORG_PROPOSAL.md` flags as owed — real interactive GUI
testing and Pi 5 hardware verification — plus a quick regression check anyone can run on a PC
before trusting a fresh checkout. Run Part A first, always; run Part B once Pi 5 access exists.

Record the outcome in `docs/context/CHANGELOG.md` (template at that file's top) and update
`docs/REORG_PROPOSAL.md`'s status line once Part B has actually run — don't just mark it done from
Part A alone.

> **`--gui`, `--benchmark`, and `--p4-sweep` are mutually exclusive top-level modes, not composable
> flags** — run each step below as its own separate command, exactly as written, rather than
> combining their flags into one invocation. `chatterbox/cli.py` checks `--benchmark` first, then
> `--p4-sweep`, then `--gui`; passing more than one together silently runs only the
> highest-priority one (as of 2026-07-20 this now prints an explicit `[do_tts] --gui has no
> effect together with --benchmark...`-style warning instead of doing so silently, but the
> underlying behavior — only one mode runs — is unchanged and pre-dates this reorg).

---

## Part A — PC/Windows sanity check (~5 min)

Run from the repo root, venv activated.

1. **Tests.**
   ```
   .venv/Scripts/python.exe -m pytest tests/
   ```
   Expect: `130 passed`, no errors. (Warnings about pydub/matplotlib deprecations are pre-existing
   and expected.)

2. **Plain synthesis.**
   ```
   echo Bonjour, ceci est un test. | .venv/Scripts/python.exe do_tts.py
   ```
   Expect, in order: `FlauBERT loaded`, `TTS assets/models/FastSpeech2/390000 loaded`,
   `Vocoder assets/models/hifi-gan-master/FR_V2/g_00570000 loaded`, an `Input after
   pre-processing:` line, then `TTS duration` / `Vocoder duration` / `Denoise duration` lines with
   sane values, and a playable `audio_file.wav` in the repo root.

3. **Benchmark + full profiling chain (single pass, no real sampler on Windows).**
   ```
   .venv/Scripts/python.exe do_tts.py --benchmark --repeats 1 --export-xlsx
   ```
   Expect: 11 `[benchmark] n/11 - ...` lines, a `[join] no ... per_sample.csv found (background
   sampler didn't run - e.g. non-Linux...)` note (expected on PC), `Wrote 11 sentence rows, 44
   stage rows`, and `Wrote 1 pass(es) to profile\run_.../exports\chatterbox_paste.xlsx`.
   Clean up the generated `profile/run_*`/`profile/latest` afterward — they're test scratch, not
   meant to be committed (same reasoning as `docs/REORG_PROPOSAL.md` §4).

4. **GUI — actually click through it this time.** Nothing in the reorg's own verification ever
   drove the GUI interactively (no display was available). On a machine with one:
   ```
   .venv/Scripts/python.exe do_tts.py --gui
   ```
   Checklist:
   - [ ] Window opens; a TTS button and a Vocoder button are highlighted yellow (defaults loaded).
   - [ ] Speaker radio buttons, style radio buttons, and all sliders are populated and usable.
   - [ ] Type a sentence, press Enter (or click "Synthèse") — audio plays, the circle indicator
     cycles gray → yellow → green → gray, and the duration labels update.
   - [ ] Click a different TTS or Vocoder button — the previous one un-highlights, the new one
     loads (a few seconds), and a subsequent synthesis still works.
   - [ ] Click "Play" (if `add_play_button` is on in `config_tts.yaml`) — replays the last clip
     with no new synthesis.
   - [ ] On-screen keyboard: click a few phonetic keys — they insert into the text field. If
     `keyboard_options.play_phone` is `true` in `config_tts.yaml`, confirm each key also plays its
     prompt WAV (now at `assets/audio/prompts/Emmanuelle/`, moved in reorg Phase 4).
   - [ ] Close the window cleanly (no traceback on exit).

If all of Part A passes, the reorg is confirmed correct for daily PC/dev use. Part B is what's
still missing.

---

## Part B — Raspberry Pi 5 hardware (the actual gap)

This is the check `docs/REORG_PROPOSAL.md` §7 calls out as the one step that can't be waived — it's
the only thing that ever exercises the Pi-only code paths (the background sampler subprocess,
PMIC/INA226 reads, GPIO/audio-device specifics) at all.

1. **Fresh provisioning.**
   ```
   git clone <repo-url> ~/chatterbox
   cd ~/chatterbox
   ./scripts/setup_pi.sh
   ```
   Expect the script's own `RESULT: PASS` summary. This is the first real test of Phase 1's
   `assets/models/` weight-download retargeting and Phase 3's `paths.py`/config-remap logic on
   genuinely fresh downloads (not this session's already-patched local checkout).

2. **Plain synthesis**, same command and expectations as Part A step 2.

3. **Profiling, with the real sampler this time.**
   ```
   python3 do_tts.py --profile
   ```
   ...then, unlike on Windows, check `profile/run_*/per_sample.csv` actually has rows (10 Hz CPU/
   PMIC/thermal samples) — this is the code path Phase 2 changed
   (`tools.monitoring.profiling.sampler`'s subprocess launch string) and could never be exercised
   without real hardware.

4. **Benchmark, join, export — full chain.**
   ```
   python3 do_tts.py --benchmark --repeats 1 --play --join --export-xlsx
   ```
   Confirm `profile/run_*/per_sample.csv` is non-empty this time (unlike Part A step 3), and that
   `cpu_power_w`/`mem_power_w`/`pmic_power_w` columns in `per_sentence_results.csv` are populated,
   not blank.

5. **GUI, interactively, on the Pi's own display** — repeat Part A step 4's checklist on the actual
   target hardware/touchscreen.

6. **If INA226 is wired**: `i2cdetect -y 1` shows it at `0x40` (IQaudio DAC at `0x4c`, no
   collision); a `--profile` run's `per_sample.csv` has non-empty `ina_*` columns.

7. **Timing sanity check**: compare `--benchmark`'s per-sentence TTS/vocoder/denoise durations and
   overall RTF against a pre-reorg baseline run, if one exists (e.g. an entry in
   `docs/context/CHANGELOG.md` from before 2026-07-20) — the reorg should not have changed
   inference cost, only where the code lives.

---

## Recording the result

Once Part B has actually run on real hardware:
- Append a `docs/context/CHANGELOG.md` entry (what ran, what passed, anything that didn't).
- Update `docs/REORG_PROPOSAL.md`'s status line from "Windows-verified... Pi-unverified" to
  reflect the real outcome.
- If anything in Part B fails, that's a real, undiscovered gap from the reorg — file it the same
  way the reorg's own phases documented their discovered gaps (a §6-style risk note plus a
  CHANGELOG entry), not a silent workaround.
