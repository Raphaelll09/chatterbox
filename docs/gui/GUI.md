# Chatterbox GUI

The Tkinter GUI (`chatterbox/gui/app.py`), refactored per `chatterbox_gui_spec_v0.1.md` so
synthesis + playback never freeze the window, exceptions never crash it, and it speaks to
`chatterbox-powerd` (`docs/power/POWERD.md`) as a client. Companion doc:
`README_power_gui_workstream.md`.

## Running

```bash
python3 do_tts.py --gui
```

Same launch as before this refactor — no new flags. `chatterbox-powerd` is optional; the GUI is
fully usable (synthesis, playback, touch, on-screen keyboard) with it not running, only power
management (screen sleep, amp handshake) and physical-switch input are unavailable in that case.

## Threading model

**Rule: Tk is only ever touched from the Tk thread.** Synthesis and playback run on a daemon
worker thread; everything the worker needs to hand back to the UI goes through one marshaling
queue:

- `post(fn)` — callable from any thread, queues a widget-safe closure.
- `ui_queue` / `_pump()` — `window.after(30, _pump)` drains the queue on the Tk thread. This is
  the **same** queue used for powerd-forwarded switch presses (`{"type":"input",...}` messages),
  not a separate mechanism — see `chatterbox_gui_spec_v0.1.md` §2.1.

`on_speak()` (Tk thread) snapshots the text, the currently-selected model indices
(`chatterbox.state.TTS_INDEX`/`VOCODER_INDEX`), and the slider values *before* starting the
worker, so clicking a different model button mid-synthesis can't change which model an in-flight
call uses. The worker (`_work()`, no Tk calls) calls `chatterbox.synth.synthesize()` then
`chatterbox.audio.playback.play_audio()`, both wrapped in `try/except` — any exception posts an
"error" UI state instead of propagating into Tk's event loop or crashing the process. A `busy`
flag (mutated only on the Tk thread, via the posted `_done`/`_fail` closures) makes overlapping
Speak triggers a no-op while a job is running; the GUI's own startup warm-up
(`cli.warmup()`, see `chatterbox/cli.py`) runs through this exact same machinery, so a Speak click
during warm-up is naturally ignored rather than needing separate handling.

UI states (idle/synthesising/initialising/playing/error) reuse the existing status-circle widget
(gray/yellow/yellow/green, plus a new red for error) plus one status/error label.

## `chatterbox/synth.py` — the Tk-free compute path

`synthesize(text, tts_idx, voc_idx, tts_config, gui_control=None, sentence_id=None,
complexity_tag=None) -> AudioResult | None` is the extracted compute path (text normalization →
FastSpeech2 → HiFi-GAN → denoise/postprocess → subtitles → `playback.AUDIO_EXAMPLE` set), with no
Tk import and no playback call. Both `chatterbox.cli.syn_audio()` (CLI/benchmark path) and the
GUI's worker call it directly. `chatterbox/cli.py:syn_audio()` keeps its exact old signature
(every other caller — `tools/measurement/benchmark/{runner,p4_sweep}.py`, the free-text loop,
`tests/test_benchmark.py`'s fake — already passed `use_gui=False`) but no longer branches on
`use_gui` internally; the GUI stopped calling it.

## Input dispatch (`chatterbox/gui/input.py`)

`Action` enum (`SPEAK, PUT_AWAY, NEXT, PREV, SELECT, BACK, KEY`) shares its member names with
powerd's `switches:` config (`chatterbox/config/user_prefs.yaml` — a switch's `action: SPEAK`
maps onto `Action.SPEAK` by name lookup). `dispatch(action, payload=None)` — built once in
`create_gui()` via `make_dispatcher()`, dependency-injected (no import of `app.py`, so no import
cycle) — routes every action, pings powerd `activity` on every call, and never lets an exception
escape into a Tk callback.

The Speak button, `<Return>`, the on-screen keyboard's phoneme buttons, and the "▶"/mood-shortcut
keys (`chatterbox/gui/keyboards.py`) all go through `dispatch()` now instead of calling synthesis
directly.

**Nav ring** (`NavRing`, in the same file): a small, intentionally minimal ring —
`[ent_text_input, btn_syn_audio, btn_put_away, btn_settings]` — that `NEXT`/`PREV`/`SELECT` move
through and activate. This is the seam physical switches will drive once configured; **not
hardware-validated** — `chatterbox/config/user_prefs.yaml`'s `switches: []` is empty by default
(per `README_power_gui_workstream.md`'s own open items), so nothing currently triggers
NEXT/PREV/SELECT/BACK interactively in a real deployment yet. `dispatch()`/`NavRing` are unit
tested (`tests/test_gui_input.py`) with fake widgets, not real hardware.

## Settings screen (`chatterbox/gui/settings.py`)

A `Toplevel` editing `chatterbox/config/user_prefs.yaml`'s `power.{t_dim_s,t_dark_s,t_deep_s,
deep_manual_only}` and `display.{brightness_active,brightness_dim}` — the same file/schema
`chatterbox-powerd` reads. No volume (analogue/out-of-band). Range-validated
(`validate_power_settings()`, pure, unit-tested) before writing; write is a full
read-modify-write through `chatterbox.power.config.load_config()` (so the `amp`/`switches`/
`evdev`/`socket` sections this screen doesn't edit survive untouched) with an atomic
`.tmp` + `os.replace()` (`write_settings()`, also unit-tested against a `tmp_path`). On success,
calls `chatterbox.power.client.get_client().send_reload()` so powerd picks up the change
immediately. **Trade-off**: `yaml.safe_dump` does not preserve hand-written comments — the first
GUI-driven save rewrites `user_prefs.yaml` without them.

## Testing

**Runs anywhere, no models/Tk needed** (headless-safe like the rest of this suite — fake
duck-typed widgets, no real `tk.Tk()`):

```bash
.venv/Scripts/python.exe -m pytest tests/test_gui_input.py tests/test_gui_worker.py tests/test_synth.py tests/test_gui_settings.py -v
```

- `test_gui_input.py` — `NavRing`/`dispatch()` routing, wraparound, error-swallowing.
- `test_gui_worker.py` — the worker/busy-guard/post-pump machinery, with
  `chatterbox.synth.synthesize`/`chatterbox.audio.playback.play_audio` monkeypatched.
- `test_synth.py` — `synthesize()`'s empty-input guard and `AudioResult`'s shape (not a mocked
  full pipeline — see the file's own docstring for why, same reasoning `test_benchmark.py` already
  documents for not faking `cli.syn_audio`'s real pipeline).
- `test_gui_settings.py` — range validation and the atomic read-modify-write, against a
  `tmp_path`.

**Needs real models, run manually (not part of the pytest suite)** — this checkout happens to have
real pretrained weights (`assets/models/...`), so both of these were actually run, not just
written, while building this refactor:

1. `synth.synthesize()` called directly (no Tk) against loaded models — confirmed a correct
   `AudioResult` and that `playback.AUDIO_EXAMPLE` got set, proving the extraction from
   `cli.py:syn_audio()` preserved real-pipeline behavior.
2. A scripted Tk responsiveness check: `create_gui()` launched for real, a `window.after(50, tick)`
   counter running throughout, a real `dispatch(Action.SPEAK)` triggered a few seconds in. Result:
   **138 ticks over the run, max gap 77ms** (scheduled every 50ms) **while a real 5.37s
   synthesis+playback call ran** — the Tk thread never stalled. This is the direct, quantitative
   version of the spec's "window stays responsive" test plan item, run without needing a human to
   drag the window during synthesis.

Neither of these two scripts is checked into `tests/` (they need real weights and, for #2, a real
Tk instance / measurable wall-clock time) — reproduce by loading models the same way
`chatterbox/cli.py:main()`'s `load_models()` does, then calling `chatterbox.synth.synthesize(...)`
directly, or `chatterbox.gui.app.create_gui(...)` with your own `window.after()` probes.

## Known gaps (stated, not hidden)

- NEXT/PREV/SELECT/BACK/KEY are implemented and unit-tested but **not hardware-validated** — no
  physical switches are configured in this checkout (`README_power_gui_workstream.md`'s own open
  item: "Switch pins/actions: Empty until you wire buttons").
- No scanning engine, no co-design, no visual redesign — explicitly out of scope per the spec's
  "Scope discipline."
- Settings screen has no dedicated nav sub-ring; it's reachable/closeable via `BACK`, but its
  internal widgets use ordinary Tk tab order, not the switch-driven nav ring.
