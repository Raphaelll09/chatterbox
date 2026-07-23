# The Chatterbox GUI: refactor history and the interchangeable-backend contract

This document exists to hand off full context — not just *what* changed, but *why* and *how* it
was approached — to another assistant/session picking this work up (it was written for a
Claude Desktop handoff, but is kept here as permanent project documentation since the same
context is useful to any future contributor). It assumes no memory of the work described below;
everything needed to understand and continue it is here or in the cited files.

Two things happened in this line of work, in order:

1. **Six rounds of real-hardware/PC feedback on the existing Tkinter GUI** (bugs, layout fixes,
   small feature requests) — see §1 below, brief, for orientation.
2. **A 5-phase refactor making the GUI/synthesis-result layer backend-agnostic** — see §2, the
   main subject of this document, in full detail including the process used to design it.

## 1. GUI feedback rounds (context, not the main subject)

The GUI (`chatterbox/gui/app.py`) went through an initial phased build (`cc_prompt_gui_refactor.md`
Phases 0-3: audit → assessment → plan → implementation), then six rounds of real-hardware/PC
testing feedback, each analyzed and fixed as its own set of commits. In rough order:

- **Round 1**: landscape content cropped, duplicate Réglages/Paramètres entry points, unclear
  "Ranger" button, keyboard-mode/text-mode mismatch, no visible Replay button, no way to hide
  synthesis timing data, portrait crop. Fixed with a responsive grid layout, an app-bar menu
  (Paramètres/À propos), a Texte/Phonèmes keyboard toggle, a Replay button, a
  show/hide-synthesis-data menu checkbox.
- **Battery feature** (separate ask, same session): battery % from a DFRobot FIT0992 UPS HAT —
  researched the actual register map (MAX17048-style fuel gauge, I2C bus 1 @ 0x36) before writing
  `chatterbox/power/battery.py`, rather than guessing.
- **Round 2**: default style/speaker should draw first in their pickers, sliders should stick left
  (not center) so they're visible when cropped, Settings dialog became unclickable (a real
  `grab_set()` bug), power-timer sliders replaced with preset dropdowns, brightness moved to a
  0–100% scale.
- **Round 3**: landscape keyboard "taking all the space" (needed a configurable width cap),
  dim/dark timer validation (dark must exceed dim), seconds displayed where the unit should be
  minutes, Settings dialog needed a scrollbar, whole-screen vs. GUI-only orientation rotation
  (a real trade-off, answered with a recommendation: GUI-only, not full-screen rotation — touch-
  input remapping risk wasn't worth it for a rare maintenance case), orientation radio not
  reflecting current state on open, a **real PowerFSM bug** (brightness changes not re-applying
  without a state transition — fixed in `chatterbox/power/fsm.py`), a **real Settings bug**
  ("Enregistrer"/"Annuler" both saved — the close-button path bypassed validation), speaker
  chip grid replaced with a dropdown, keyboard clear-all/backspace split into two buttons.
- **Preset non-overlap fix**: dim now tops out at 2 min, dark starts at 2 min, no overlapping
  invalid combination is directly selectable from the dropdowns anymore.
- **Rounds 4–6** (landscape layout, mostly root-cause chases):
  - Both keyboards disappeared entirely, regardless of the configured width fraction. Root cause:
    `grid_propagate(False)` stops Tk deriving *both* width and height from a frame's children, but
    the landscape reflow code only ever set `width=` — height silently collapsed to ~0.
  - Style chip grid changed from 4-per-row to a computed column count targeting 4 rows, so it
    still fits when the keyboard eats half the screen width.
  - The options panel (speaker/style/sliders) disappeared entirely and "Mettre en veille" ran off
    the bottom of the screen on a real 800×480 kiosk display. Root cause, found by writing a
    reproduction script that drives `create_gui()` at that exact resolution and inspects actual
    widget geometry (`winfo_height()`/`winfo_y()`): the landscape keyboard was gridded at `row=0`
    only, but **Tk's grid row height is shared across every column at that row index** — placing
    a ~263px-tall keyboard there forced row 0 to be 263px tall *everywhere*, stealing the budget
    from row 2 (the only weighted/flexible row, holding the options panel) and collapsing it to
    7px, while the fixed rows below kept their full size and overflowed past the window edge.
    Fixed by spanning the keyboard across the same row range the main content stack already
    occupies, so its height gets absorbed by the flexible row instead of inflating one row alone.
  - The letter keyboard's "Tout effacer" button rendered as "out effacer" (clipped) at a narrow
    landscape width — fixed by binding `wraplength` to the button's own actual `<Configure>` width.

Every fix in this phase followed the same discipline: read the actual code to find the root
cause (never guess), write a small ad hoc Tk reproduction script when a real-hardware screenshot
was the only evidence, verify the fix with that same script, run the full pytest suite, then one
commit per fix plus a `docs/context/CHANGELOG.md` entry. These ad hoc scripts (mocked model
loading via monkeypatched `registry.BACKEND` methods, no pretrained weights needed, a real
`tk.Tk()` instance driven from a background probe thread) are not checked into `tests/` — they
live only in the session's scratch directory — but the pattern is worth reusing: it is the only
way to catch real Tk geometry-manager bugs (row/column weight interactions, `grid_propagate`
quirks) that a widget-mocking unit test cannot see at all.

## 2. The interchangeable-backend refactor (main subject)

### 2.1 The problem, in the user's own framing

> "Styles and Pitch, Energy, Duration, etc. are specific to the FS2 version developed by Martin
> Lenglet and Olivier Perrotin. If we change for a State of the Art TTS Model in the next days,
> the GUI should be made so the TTS technology is fully interchangeable, with the specificity of
> FS2. This also concerns the synthesis data that might not be accessible the same way for every
> TTS Model."

Mid-discussion the user added a second, related concern: the on-screen keyboards (the core AAC
interaction, more important than any style/pitch control) also assume FS2-specific things — the
"Phonèmes" keyboard authors input in FS2's own custom phone-symbol alphabet, and a future backend
might not understand that syntax at all, requiring some kind of translation or fallback.

### 2.2 Methodology used

This was treated as a genuine architecture task, not a quick edit, for a concrete reason: the
codebase already had *partial*, unused scaffolding for exactly this problem
(`chatterbox/synthesis/base.py`'s `Synthesizer.describe_controls()` hook, and a two-ABC
`Synthesizer`/`VocoderBackend` split), but the actual GUI code (`gui_fastspeech2()`) didn't use it
— it read FS2-specific YAML keys (`gst_token_list`, `default_args.pitch_control`, etc.) directly.
Understanding *how much* of that scaffolding already fit, and where the real seams were, required
reading code before designing anything.

**Step 1 — parallel research, not sequential guessing.** Two research agents were run
concurrently (not touching the same files), each with a narrow, factual mandate and instructions
to report file:line citations, not recommendations:

- Agent A: trace the *entire* phoneme-keyboard data flow — `chatterbox/gui/keyboards.py`'s
  "Emmanuelle" key table, how a keypress reaches `ent_text_input`, whether any G2P (grapheme-to-
  phoneme) conversion exists anywhere in the pipeline. Finding: there is **no G2P step at all** —
  the "Phonèmes" keyboard lets the user directly author FS2's own custom phone-symbol tokens
  (matching a repurposed ARPAbet table in `assets/models/FastSpeech2/text/cmudict.py`); each key
  already computes a *second*, unused value too — a display label (e.g. "CH", "ON") that happens
  to read as ordinary French spelling, currently only used to mirror into a readonly display entry.
- Agent B: inventory *every* place the GUI/synthesis-result code assumes FS2-specific concepts —
  the duration-breakdown labels, `gui_fastspeech2()`'s hand-built widgets, `AudioResult`'s fields,
  `cli.py`'s console reporting, the full `config_tts.yaml` schema. Finding: `get_gui_controls()`
  returned a **fixed 12-element positional list** consumed by index in `backend.py` — the single
  most fragile part of the existing contract, and `AudioResult` hardcoded
  `tts_duration_s`/`vocoder_duration_s`/`denoiser_duration_s` as named fields, assuming a two-stage
  pipeline structurally.

**Step 2 — ask before assuming, on the two genuine design forks.** Two questions were put to the
user directly (not guessed) because they had real, opposite-direction consequences:

1. *Phoneme fallback mechanism*: reuse the keyboard's already-computed display label as a "good
   enough" plain-text approximation, or hide the Phonèmes keyboard entirely for an incompatible
   backend? **Answer: both** — a backend declares whether it supports phoneme input at all; a
   separate config setting decides what the GUI does when it doesn't.
2. *Pipeline shape*: will the next backend still be acoustic-model-plus-separate-vocoder (like
   today), or could it be a single monolithic model? **Answer: could be monolithic** — this
   meant the refactor had to touch `chatterbox/synth.py`'s actual pipeline structure, not just the
   GUI/control layer, materially increasing scope from the original assumption.

**Step 3 — a written, reviewed plan before any code.** Given the scope (5+ files, a public
contract change, a real behavior change to verify), a plan was written and presented for approval
before implementation, covering: the exact new data shapes, which file changes in which order,
and how each step would be verified. The plan explicitly scoped the work as *"make the existing
FastSpeech2 backend conform to a generic contract and re-derive today's exact behavior through
it"* — not *"build a second backend"* — so success is measurable (pixel-identical behavior for
the one real backend, proven by smoke test) without needing a second backend to exist yet.

**Step 4 — implement in 5 independently-committed, independently-tested phases**, each keeping
the full pytest suite green before moving to the next, each verified with a fresh ad hoc Tk smoke
test (same pattern as §1's), each documented with its own `CHANGELOG.md` entry. This phasing paid
for itself: a real regression (below) was caught between phases precisely because each phase was
verified in isolation rather than all at once.

### 2.3 What the contract actually looks like

**`Synthesizer.describe_controls()`** (`chatterbox/synthesis/base.py`) is the generic hook a
backend implements to describe its own GUI. Full docstring has the exact shape; summary:

```python
{
    "speaker_list": [...],        # omitted/empty if the backend has only one voice
    "default_speaker": int,       # index into speaker_list, pre-selected in the dropdown
    "controls": [                 # ordered list — gui/app.py renders one widget per entry
        {"type": "chip_grid", "key": "style", "label_key": "style_label",
         "options": [...], "default": 8, "hidden_pattern": r"^TOKEN\d+$"},
        {"type": "slider", "key": "pitch_bias", "label_key": "pitch_bias_label",
         "min": -6.0, "max": 6.0, "resolution": 0.5, "default": 0.0, "advanced": True},
        {"type": "text", "key": "style_tag", "label_key": "styletag_label"},
        ...
    ],
}
```

`gui/app.py:gui_generic_controls()` (renamed from `gui_fastspeech2()`) reads this and dispatches
per `"type"` to small builder functions (`_build_chip_grid_control` for chip grids; inline
handling for sliders/text) that reuse the *exact* widget logic the old hand-written code used —
stable-sort-default-first ordering, dynamic chip-grid column count, `hidden_pattern`-gated
placeholders behind a toggle. `get_gui_controls()` (the function the synthesis call reads from)
now returns a **dict keyed by each control's declared `"key"`**, not a positional list.
`FastSpeech2HifiGanBackend.describe_controls()` (`chatterbox/synthesis/backends/
fastspeech2_hifigan/backend.py`) is what actually declares today's exact panel — style chip grid,
style-intensity slider, pitch/energy/speed sliders, 5 "bias" sliders, StyleTag entry — reading the
same `config_tts.yaml` keys (`gst_token_list`, `default_args.*`, `gui_control_bias`, etc.) it
always read, just translated into this schema instead of hand-built widgets.

**Two-stage vs. monolithic pipeline.** `SynthesisResult.wav_path` (set) vs. `mel_path` (set) is
how a backend signals "I already produced a finished wav" vs. "still needs vocoding." A new
static, per-model YAML flag, `needs_vocoder` (alongside the existing `gui_style_control`/
`gui_control_bias`/`gui_styleTag_control` booleans in each `tts_models[i]` entry), tells
`chatterbox.synth.synthesize()` whether to call `BACKEND.vocoder()` at all, and tells
`gui/app.py`'s Settings → Advanced whether to show a Vocodeur picker row (nothing to pick for a
monolithic model). Denoising/postprocess/subtitles stay universal regardless of pipeline shape —
only the vocoder call itself is conditional. `AudioResult.stage_durations` is now a generic
`{stage_key: seconds}` dict (e.g. `{"tts": 0.8, "vocoder": 0.9, "denoiser": 0.3}`) instead of
three named fields; `"vocoder"` is simply absent for a monolithic backend. The GUI's duration
display uses a small pre-allocated pool of 3 generic label rows, assigned to whichever stage keys
are actually present at synthesis time (via one shared i18n template + a display-name lookup),
hiding any pool row a given synthesis didn't use.

**Phoneme keyboard fallback.** A second new static per-model flag, `accepts_phoneme_input`,
combined with a new top-level `GUI_config.phoneme_fallback` setting
(`"translate_labels"` default, or `"hide"`): when the active model doesn't accept phoneme input,
`_keyboard_emit()` either substitutes each key's already-computed display label for the raw phone
code (no new dependency, no G2P library — reuses data the keyboard already computed and discarded
before), or the Texte/Phonèmes toggle and the phoneme keyboard are removed entirely, forcing
Texte-only mode. A new `_refresh_keyboard_capabilities()` function (mirroring the existing
`_refresh_orientation` rebindable-callback pattern already in the codebase) re-evaluates this
live whenever the TTS model is switched from Settings → Advanced, not just once at startup.

### 2.4 The five commits, in order

1. **Contract formalization** (`chatterbox/synthesis/base.py`, `config_tts.yaml`) — `wav_path`
   added, `describe_controls()`'s docstring formalized, the two new capability flags + the
   `phoneme_fallback` setting added. Purely additive; nothing reads the new fields yet.
2. **`synth.py` pipeline** — conditional vocoder call, generic `stage_durations`, generic `cli.py`
   console reporting. `_update_audio_info()` in `app.py` got a minimal compatibility shim here
   (`.get(key, 0.0)` reads) so the test suite stayed green before the GUI's real generic renderer
   existed yet (phase 4).
3. **`backend.py`** — the full `describe_controls()` schema; `syn_fastspeech2()`'s control
   unpacking changed from positional indices to dict keys, with `.get(key, <yaml default>)`
   fallbacks throughout so an undeclared control (a future backend with fewer controls) degrades
   to that model's own configured default instead of a `KeyError`. New test file:
   `tests/test_backend_describe_controls.py` (7 cases, no model load needed — `tts_model_config`/
   `configs` set directly on a fresh instance, `text_pipeline.get_speaker_list` monkeypatched).
4. **`app.py` generic panel** (the largest commit) — `gui_generic_controls()` replaces
   `gui_fastspeech2()`; `get_gui_controls()` returns a dict; the duration-label pool replaces the
   3 hardcoded rows. Verified with a Tk smoke test asserting pixel-identical layout against a fake
   `describe_controls()` reproducing today's exact schema (speaker defaults to the configured
   speaker, style grid still 4 rows × 3 cols for 12 named tokens, all 9 sliders present with
   matching ranges).
5. **`app.py` vocoder/phoneme gating** — the Vocodeur picker hide, the phoneme fallback logic,
   `_refresh_keyboard_capabilities()`. **A real regression was caught here**: smoke-testing this
   phase immediately raised `KeyError('gst_token_selection')` at GUI *build* time (not even
   requiring a keypress). Root cause: `chatterbox/gui/keyboards.py`'s "Emmanuelle" keyboard has
   its own hardcoded mood-shortcut keys (`:D`/`:p`/`:(`/`:O`) that resolve the *literal string*
   `"gst_token_selection"` against `chatterbox.gui.app`'s `globals()` dict
   (`create_keyboard()`'s special-case key handling, unrelated code, untouched by this refactor)
   — a global that phase 4 had removed entirely in favor of `_generic_control_widgets`. Fixed by
   keeping `gst_token_selection` as a compatibility alias, set to the "style" chip grid's `IntVar`
   whenever `gui_generic_controls()` builds one (and defaulting to `None` at module level
   otherwise, so a backend with no "style" control degrades those keys to a no-op instead of
   crashing at build time). This is exactly the kind of bug the phased-and-verified approach is
   meant to catch — it would have been much harder to isolate if all 5 phases had landed as one
   commit.

Each phase has its own `docs/context/CHANGELOG.md` entry (search that file for "interchangeable-
backend GUI, phase" to find all five) with the full rationale, files touched, and verification
detail — this document summarizes them, but the changelog entries are the authoritative per-phase
record.

### 2.5 Current state / explicitly not done

- **A second backend has since been implemented and exercised — see §3.** This section originally
  said the contract had never been tested against a real second backend; the Piper fr_FR
  integration (`docs/context/CHANGELOG.md`) did exactly that and found two real gaps the 5-phase
  refactor above missed. The scope of *this* section (2.1-2.4) was deliberately "make the existing
  backend conform to a generic contract and prove it fits" — read §3 for what happened when that
  claim was actually tested.
- **`docs/context/ARCHITECTURE.md` was intentionally left untouched** — it was already flagged
  stale (module names/paths predate the Phase 3 reorg) pending its own separately-tracked
  rewrite; re-describing the interchangeable-backend contract there was out of scope for this
  refactor. `CLAUDE.md` gained a new "Interchangeable backends" section instead, which is the
  up-to-date narrative reference until `ARCHITECTURE.md` gets its own pass.
- **`gst_weights`** (`AudioResult`, GST-style per-token debug weights) stayed FS2-specific and
  `Optional` — it's already gated behind an off-by-default `add_GST_infos` config flag, and was
  explicitly scoped out as low-priority in the plan rather than generalized further.
- **`keyboards.py`'s "Emmanuelle" phone-symbol table and mood-shortcut keys remain FS2/GST-
  specific by design** — a backend wanting phoneme-input support of its own would need its own
  keyboard layout and symbol table, not a reuse of this one.
- The 5 phases add one new capability the old code never had: bias sliders (`gui_control_bias:
  False`) are now revealable via a shared "Contrôles avancés" toggle, where before they were
  permanently invisible with no way to show them from the GUI. This was a deliberate, low-risk,
  called-out side effect of building the panel generically, not a design goal in itself.

### 2.6 Key files to read first, for anyone continuing this work

- `chatterbox/synthesis/base.py` — the contract itself; read the `describe_controls()` docstring
  in full before touching anything else.
- `chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py`'s `describe_controls()` — the
  reference implementation of the contract.
- `chatterbox/gui/app.py`'s `gui_generic_controls()`, `_build_chip_grid_control()`,
  `get_gui_controls()`, `_apply_keyboard_capabilities()` — the GUI-side consumer.
  `chatterbox/synth.py`'s `synthesize()` — the conditional-vocoder pipeline.
- `chatterbox/config/config_tts.yaml` — see the comments directly above `needs_vocoder`/
  `accepts_phoneme_input` (per `tts_models` entry) and `phoneme_fallback` (top-level `GUI_config`).
- `docs/context/CHANGELOG.md` — search "interchangeable-backend GUI, phase" for the five
  detailed per-phase entries.
- `tests/test_backend_describe_controls.py`, `tests/test_synth.py`, `tests/test_gui_worker.py` —
  the pytest coverage added/updated for this refactor.

## 3. Piper integration — the acid test (docs/context/CHANGELOG.md has the full session log)

`cc_prompt_piper_backend.md` set out to add Piper (fr_FR, `piper-tts==1.5.0`) as a second backend
specifically to test whether §2's contract actually holds for a backend that's maximally different
from FastSpeech2+HiFi-GAN along every axis (monolithic vs. two-stage, ONNX Runtime vs. PyTorch, no
G2P frontend of its own vs. an internal espeak-ng phonemizer, no style dimension, per-voice speaker
maps instead of a shared `speakers.json`). It found two real gaps — one blocking, one silent.

### 3.1 Gap 1 (blocking): `registry.BACKEND` was a hardcoded singleton, not a dispatcher

`chatterbox/synthesis/registry.py`'s original `BACKEND = FastSpeech2HifiGanBackend()` — a single
concrete instance — was fine with one backend but couldn't actually resolve a second one:
`tts()`/`describe_controls()` are defined identically-named on every backend by design (that's the
whole point of the shared contract), so a bare `getattr(BACKEND, name)` had no way to tell *which*
backend's `tts()` a caller meant once two were registered. §2.2/§2.3 above describe the contract
correctly, but registry.py's own docstring claim — "nothing else... would need to change" for a
second backend — was untested and turned out to only be true once registry.py itself became a
small resolving proxy: `_BackendProxy.__getattr__` resolves colliding names (`tts`,
`describe_controls`) against whichever backend was most recently activated via the new
`activate_tts_backend(name)`, called explicitly from `cli.py:load_models()` and
`gui/app.py:_select_tts_model()`/`_initial_model_load_work()` (one new line each, immediately
before their existing `getattr(registry.BACKEND, tts_model["load_script"])`) — and falls back to a
plain name search for uniquely-named methods (`load_script`/`syn_script` strings, which never
collide by construction). `chatterbox/synth.py` needed **zero** changes — all 3 of its
`registry.BACKEND` call sites still just resolve through the proxy transparently.

A `backend` field was added to each `config_tts.yaml` `tts_models[i]` entry (`"piper"` for each
Piper voice; omitted — defaults to `"fastspeech2_hifigan"` — on the original FS2 entry, so it
needed no yaml edit). Piper started with 3 voices; a 3rd, `tom`, was evaluated and removed after
real-hardware listening found it noticeably lower quality and slower than the other two
(`docs/context/CHANGELOG.md`) — 2 remain today.

### 3.2 Gap 2 (silent, found only by driving a real `tk.Tk()` instance, not by reading the code): stale `gst_token_selection`/`speaker_selection`

`gui/app.py`'s `gst_token_selection` (§2.3's own compat shim for `keyboards.py`'s mood-shortcut
keys) and `speaker_selection` were only ever *set* to a real Tk variable inside
`gui_generic_controls()` when the active backend's `describe_controls()` actually declared a
`"style"` control / non-empty `speaker_list` — never *reset* to `None` otherwise. Static reading
made this look safe (their module-level default is `None`), but in the realistic sequence — FS2
(which always loads first, `default_tts: 0`) sets a real variable, user later switches to a
style-less/single-speaker Piper voice via Settings → Advanced — both globals were left pointing at
FS2's now-torn-down widgets instead of resetting to `None`. Not a crash (a `tk.IntVar` can still
have `.set()` called after its owning frame is destroyed; Piper's `gui_control` dict simply never
reads a `"style"` key either way), but stale state that contradicted the shim's own documented
intent. **Only surfaced by building an ad hoc script that drives a real `tk.Tk()` instance through
an actual FS2→Piper→FS2 switch and inspects the globals afterward** — a widget-mocking unit test,
or reading `gui_generic_controls()`'s code in isolation, cannot see this (exactly the class of bug
§1's own closing paragraph already flagged this project's ad hoc-Tk-script convention for). Fixed
by resetting both globals to `None` at the top of every `gui_generic_controls()` call, before the
controls loop, so each call starts clean regardless of what the previous backend left behind.

### 3.3 Smaller corrections (API drift / doc inaccuracies, not contract gaps)

- `base.py`'s `describe_controls()` docstring says `speaker_list` is `[str, ...]` (a list) with
  `default_speaker` as a list-index — the real `FastSpeech2HifiGanBackend` implementation returns
  a **dict** `{name: index}` with `default_speaker` as a raw id. `PiperBackend` matches the real
  shape, not the docstring — the docstring itself is now known-stale on this point.
- `text_pipeline.parse_pronunciation_mistakes()`'s substitution *mechanism* (regex replace) is
  genuinely backend-agnostic, but the *data* it substitutes (`custom_regex_rules.csv`,
  `url_regex_rules.csv`, part of `symbols_regex_rules.csv`) is heavily laden with FS2's own
  `{phonetic}` bracket syntax that Piper's phonemizer can't interpret — found by actually running a
  synthesis (`"test"` → literal `{t e^ s t}` in Piper's input text), not by reading the regex
  mechanism alone. Piper's own `text_frontend.py` therefore keeps this opt-in and off by default.

### 3.4 Three more gaps — found only by an actual `do_tts.py --benchmark` run on the Pi 5, none of them caught by §3.1-§3.3's own tests/repro script

(A fourth, found by then actually *inspecting the CSV output* of that run rather than trusting the
console — see §3.5 — brings the real total to four.)

The pattern across all three: they only manifest when `cli.py`'s `load_models()` and
`chatterbox.synth.synthesize()` run together, end to end, with a real `needs_vocoder: false`
model selected — something no unit test, backend-level smoke test, or the Tk repro script
actually exercises (they each call `PiperBackend.tts()`/`describe_controls()` directly, or mock
`registry.BACKEND`'s methods entirely). This is the concrete argument for treating a real
`--benchmark` run on real hardware as part of "done," not an optional afterthought — see
`cc_prompt_piper_backend.md`'s own Definition of Done, which already listed it.

1. **`chatterbox.state.VOCODER_INDEX` went unset.** `cli.py:syn_audio()` reads it unconditionally
   (`getattr(state, "VOCODER_INDEX")`); an earlier version of the `needs_vocoder` optimization (§
   above, "Non-blocking follow-on finding") skipped `state.update_selected_vocoder()` itself, not
   just the heavy load call, for a monolithic model → `AttributeError` on the very first
   synthesis. `gui/app.py`'s equivalent path was already correct (`create_gui()` sets both state
   indices unconditionally at build time, well before any loading work runs) — only `cli.py`
   needed the fix, and the fix is to keep the *state* update unconditional while still skipping
   only the actual weight-loading call.
2. **`chatterbox/synth.py`'s subtitle path assumed FastSpeech2's own `audio_file_duration.npy`
   output exists for any backend** — gated only by the top-level `subtitles.create_file` config
   flag, with no per-model capability check at all. Added `supports_subtitles` (`false` on all 3
   Piper entries) to the *same family* of static per-model flags as `needs_vocoder`/
   `accepts_phoneme_input` (§2.3) — a contract addition, not just a Piper-side workaround, since
   any future backend without duration-alignment output will need it too. The `"|"`-separated
   multi-utterance ("§") branch a few lines away is a related, *still-open* gap: it unconditionally
   reads/writes FS2's raw `.WAVEGLOW`/`.AU` binary format regardless of `supports_subtitles` or
   `needs_vocoder`, so a Piper user who includes `"|"` in free text will still hit a
   `FileNotFoundError` — deliberately left unfixed (would need real work: WAV-level audio
   concatenation instead of mel-level, backend-specific either way) and documented in `synth.py`
   itself rather than silently left for a future session to rediscover.
3. **`PiperBackend.tts()`'s own return value violated the contract its own docstring described.**
   `synth.py`'s `needs_vocoder=False` branch treats whatever `tts()` returns as a *directory* and
   builds the wav path itself (`os.path.join(location_mel_file, "audio_file")`) — exactly
   matching what §2.3/`fastspeech2_hifigan/backend.py:330` already established FS2's own `tts()`
   returns. The implementation returned `os.path.join(out_dir, "audio_file")` instead — a
   file-prefix, not a directory — producing a nonexistent double-nested path and crashing every
   sentence. The unit test written for this *at the time* asserted the wrong (buggy) value and
   passed, because it was written by re-deriving the expectation from the same (wrong)
   implementation instead of independently from `synth.py`'s actual code — a caution about what
   a same-session unit test can and can't catch: it can catch a regression from *this* behavior,
   but not a version of the contract that was wrong from the start. Only a real run through the
   unmodified `synth.py` — which has its own, independent opinion about the shape — caught it.

### 3.5 Gap 4 — found by inspecting the CSV output of a *successful* run, not by reading code or trusting the console

Everything above was caught by a crash. This one wasn't — the fixed Piper run's console output
looked completely correct (`TTS`/`Denoise` lines, sensible durations, `"Wrote 11 sentence rows, 44
stage rows"`), and it was only inspecting `per_stage_results.csv` directly that showed something
wrong: every stage column read `front_end_ms: 0.0, acoustic_ms: 0.0, vocoder_ms: 0.0, write_ms:
74.4` — FS2's own 4 stage names, despite Piper never running any of them, with no `synth` column
anywhere. `tools/monitoring/profiling/recorder.py`'s `Recorder.stage(name)` genuinely accumulates
any name into `self.durations`/`self.timestamps` — but `Recorder.finalize()` only ever read back
4 **hardcoded** names into the JSON record it writes; a `"synth"` stage was computed correctly,
then silently discarded at serialization. Pre-existing profiling-subsystem behavior — Piper was
just the first caller to ever pass `.stage()` a 5th name.

This is a genuinely different class of bug than §3.1-§3.4: those all crashed, forcing the gap to
be found. This one produced a *plausible-looking, silently wrong* result — the kind that could
have shipped into an actual research dataset unnoticed if the CSV hadn't been opened and read.

Fixed properly (not just worked around for Piper — the user was asked and chose the full fix over
a one-line rename), spanning three files with three different scopes:

- `recorder.py`: `Recorder.finalize()` now also writes a generic, order-preserving `"stages"`
  list (`[{"name", "t_end", "duration_ms"}, ...]`) covering every stage actually recorded — the 4
  fixed fields stay byte-identical alongside it, for backward compatibility.
- `tools/monitoring/profiling/join.py`: `build_per_stage_results()` now derives each sentence's
  stage rows from that generic list (a new `_stage_windows()`, chaining each stage's start from
  the previous stage's end), falling back to the old fixed 4-stage chain only for historical
  records with no `"stages"` field — re-joining old data (this module's own documented use case)
  still works unchanged.
- `tools/measurement/benchmark/export_to_xlsx.py` was **deliberately left un-generalized** — its
  entire layout is bound to a specific external spreadsheet template
  (`Chatterbox_Power_Measurements_final.xlsx`), not something to redesign as a side effect of a
  backend integration. Instead it gained a loud guard (`_check_stage_shape()`): a stage name
  outside the fixed 4 now raises `SystemExit` with a clear message, rather than silently
  mis-slicing rows into misaligned blocks — the same silent-wrongness class of bug as the one this
  gap started as, now made structurally impossible for this tool instead of just fixed once.

Re-verified on the Pi: a fresh Piper run now reports `"Wrote 11 sentence rows, 22 stage rows"`
(the real `synth`+`write` shape), `per_stage_results.csv` has real `synth` rows with energy/CPU
data, and re-running FS2 afterward still reports `44` stage rows with its original 4 names —
confirms the generalization is additive, not a behavior change for the backend it was designed
around.
