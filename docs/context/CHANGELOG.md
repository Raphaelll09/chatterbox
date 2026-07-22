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

## 2026-07-22 — Background the startup model load in the GUI (startup-latency phase 2)

- What: `chatterbox/gui/app.py:create_gui()` used to call `_select_tts_model()`/
  `_select_vocoder_model()` for the default models synchronously, before any of the rest of the
  window's widgets were built and before `window.mainloop()` -- so the window never painted until
  FastSpeech2+HiFi-GAN had fully loaded (phase 1 already removed FlauBERT from that wait; this
  phase removes the remainder). Fix: the startup call-site now only does the cheap part
  immediately -- `state.update_selected_tts()`/`update_selected_vocoder()` (so anything below that
  only needs to know which model is selected, e.g. `_apply_keyboard_capabilities()`, already sees
  the right answer) and a "Chargement du modèle…" placeholder label in the options-panel's spot
  (row 2) -- then lets the rest of `create_gui()` build every other widget (menu, entry, keyboard,
  nav, etc.) exactly as before. The actual `loading_script()` calls for both models move to a new
  background thread (`_start_initial_model_load()`/`_initial_model_load_work()`), scheduled via
  `window.after(50, ...)` right before `mainloop()` -- the same pattern already used for warm-up
  (`_start_warmup()`). Its completion (`_finish_initial_model_load()`, run back on the Tk thread via
  the existing `post()`/`_pump()` machinery) destroys the placeholder, builds the real options
  panel (`gui_generic_controls()`, which needs the just-loaded model's config), re-applies keyboard
  capabilities, then chains straight into `_start_warmup()` -- which can no longer be scheduled
  independently since it also needs a loaded model. `busy` goes `True` before a single further
  widget is built (so `on_speak()`/`on_replay()`'s existing busy-guards block any click for the
  whole load, with no gap), then briefly back to `False` right before `_start_warmup()`'s own
  busy-guard sets it `True` again -- both happen synchronously in one Tk-thread callback with no
  event processing in between, so there's no window for a click to slip through either transition.
  `_select_tts_model()`/`_select_vocoder_model()` themselves are unchanged and still run
  synchronously for an interactive Settings -> Advanced model switch -- only the startup path is
  backgrounded.
- Files: `chatterbox/gui/app.py`, `chatterbox/gui/i18n.py` (new `loading_model_label` string).
- Why: continues the "FlauBERT takes forever, GUI appears a while later" fix from phase 1 -- with
  FlauBERT lazy, FastSpeech2's 621 MB checkpoint was still the dominant remaining startup cost, and
  it was still blocking `mainloop()` the same way FlauBERT used to.
- Verify: `pytest tests/` (242 passed, 1 pre-existing skip, unchanged). Manually: launched
  `do_tts.py --gui` with real weights and per-line wall-clock timestamps -- "TTS .../390000 loaded"
  and "Vocoder .../g_00570000 loaded" only print ~4-5s after process start, and since those calls
  only run from inside `_initial_model_load_work()`, itself only reachable via the
  `window.after(50, _start_initial_model_load)` timer callback -- which Tk can only fire once
  `mainloop()` is already pumping events -- the window is structurally guaranteed to have started
  painting before that load completes, not just empirically observed to. No exceptions through the
  full load -> options-panel-build -> keyboard-capability-refresh -> warm-up chain.
- Notes/gotchas: if `_start_warmup()`'s own busy-guard or its call site ever changes, re-check the
  `busy = False` right before `_start_warmup()` in `_finish_initial_model_load()` -- without it,
  warm-up silently no-ops forever (busy stays `True` from the load, `_start_warmup()`'s `if busy:
  return` fires immediately), which is exactly the bug this phase's implementation hit and fixed
  before landing.

---

## 2026-07-22 — Lazy-load FlauBERT (startup-latency phase 1)

- What: `FlaubertModel.from_pretrained()` (a ~1.4 GB checkpoint -- bigger than
  FastSpeech2's own 621 MB checkpoint and HiFi-GAN's 3.7 MB combined) was being
  loaded eagerly on every `do_tts.py`/`--gui` startup as part of
  `get_model()`, even though the FlauBERT encoder it produces is only ever
  used by `preprocess_styleTag()`
  (`chatterbox/synthesis/backends/fastspeech2_hifigan/text_pipeline.py`) when
  a free-text `<STYLE_TAG=...>` tag is present in the input -- a path the GUI
  doesn't expose at all today (`gui_styleTag_control: False` in
  `config_tts.yaml`) and rarely used from the CLI either. This was the
  dominant contributor to the "FlauBERT takes forever to launch, GUI appears a
  while later" complaint: in `chatterbox/gui/app.py:create_gui()`, model
  loading (`_select_tts_model()`) runs synchronously before `window.mainloop()`
  is reached, so the whole load -- FlauBERT included -- blocks the window from
  ever painting.
  Fix: `assets/models/FastSpeech2/utils/model.py`'s `get_model()` now wraps
  the FlauBERT *model* in a `_LazyFlaubertModel` proxy that defers the actual
  `from_pretrained()` checkpoint load until the first real forward call
  (`__call__`/`__getattr__`); the tokenizer stays eager since it only reads
  small vocab/merges files and is fast. No other call site changed --
  `_LazyFlaubertModel` is a drop-in stand-in wherever `flaubert_model` used to
  be passed around.
- Files: `assets/models/FastSpeech2/utils/model.py`.
- Why: cut everyday `do_tts.py`/`--gui` startup latency without touching the
  free-text style-tag feature itself; see the earlier chat's analysis (not a
  separate doc) for the full breakdown of file sizes / load path. This is
  phase 1 of a multi-step plan; phase 2 (backgrounding the remaining model
  load in the GUI so the window paints before `_select_tts_model()` finishes)
  is still open.
- Verify: `pytest tests/` (242 passed, 1 pre-existing skip, unchanged from
  before this change). Manually: `do_tts.py` free-text with a plain sentence
  no longer prints "Loading of FlauBERT"/"FlauBERT loaded" at startup; a
  sentence starting with `<STYLE_TAG=...>` still prints those two lines (now
  at the point of first use, inside that synthesis call) and produces the
  correct `StyleTag: ...` output identical to before.
- Notes/gotchas: only the FlauBERT *model* is proxied, not the tokenizer --
  keep it that way unless tokenizer loading is ever shown to be slow too,
  since a second lazy-proxy class isn't worth the complexity for a sub-second
  load. The standalone `assets/models/FastSpeech2/synthesize.py` script (its
  own `main()`, not part of the chatterbox daily-use path) calls the same
  `get_model()` and gets the same lazy behavior for free.

---

## 2026-07-22 — Interchangeable-backend GUI, phase 1/5: contract formalization

- What: the user wants to be able to swap the FastSpeech2+HiFi-GAN backend for a
  different TTS technology (possibly a monolithic model with no separate
  vocoder stage) without rewriting the GUI. This is the first of a planned
  5-phase refactor (see `C:\Users\rphev\.claude\plans\reflective-shimmying-ember.md`
  for the full design) that makes the *existing* backend conform to a generic
  contract, proving it covers today's needs before any second backend exists.
  No behavior change in this phase -- purely additive contract/config surface.
  1. `SynthesisResult` (`chatterbox/synthesis/base.py`) gains `wav_path:
     Optional[str] = None`. Convention: a two-stage backend (today's FS2+HiFi-
     GAN) fills `mel_path`, leaves `wav_path=None`; a monolithic backend fills
     `wav_path` directly, leaves `mel_path=None`. `chatterbox/synth.py`'s
     `synthesize()` (phase 2) will branch on which one is set to decide whether
     a vocoder call is needed at all.
  2. `Synthesizer.describe_controls()`'s docstring formalizes the dict shape a
     backend returns to drive a *generic* model-options panel: an ordered
     `"controls"` list of `chip_grid`/`slider`/`text` descriptors (key, label
     key, options/min/max/default, optional `hidden_pattern`/`advanced`
     grouping) -- this will replace `gui_fastspeech2()`'s hand-written,
     FS2-specific widget code in phase 4.
  3. `config_tts.yaml`: two new static per-`tts_models`-entry capability flags,
     decidable *before* a model loads (same convention as the existing
     `gui_style_control`/`gui_control_bias`/`gui_styleTag_control` booleans) --
     `needs_vocoder` (will hide the Settings -> Advanced Vocodeur picker for a
     monolithic model, phase 5) and `accepts_phoneme_input` (will drive a new
     `GUI_config.phoneme_fallback: "translate_labels" | "hide"` setting when a
     model doesn't understand the Phonemes keyboard's raw phone-code syntax,
     phase 5). Both default to `True` for the current FastSpeech2 model (no
     behavior change).
- Files: `chatterbox/synthesis/base.py`, `chatterbox/config/config_tts.yaml`.
- Why: user request -- see plan file for the full context/design rationale,
  including two research passes' findings on exactly what's FS2-specific today
  (GUI duration labels/control panel, `AudioResult`, `cli.py` reporting, the
  phoneme-keyboard's "Emmanuelle" custom phone-symbol alphabet with no G2P step).
- Verify: full test suite (233 passed/1 skipped, unchanged -- nothing reads the
  new fields yet).
- Notes/gotchas: this is phase 1 of 5; phases 2-5 (synth.py pipeline, backend.py
  schema, app.py generic panel, app.py keyboard/vocoder gating) are tracked in
  the same plan file and will each get their own changelog entry.

---

## 2026-07-22 — Interchangeable-backend GUI, phase 2/5: conditional vocoder + generic stage timing

- What: second phase of the interchangeable-backend refactor (plan file:
  `C:\Users\rphev\.claude\plans\reflective-shimmying-ember.md`) -- makes
  `chatterbox/synth.py`'s pipeline able to skip the vocoder stage entirely for a
  monolithic backend, and duration reporting generic instead of 3 named fields.
  1. `synth.synthesize()` reads phase 1's `needs_vocoder` config flag to decide
     whether to call `BACKEND.vocoder()` at all -- a monolithic backend's
     `tts()` call is expected to have already written a finished wav under the
     same output-folder/`AUDIO_FILE_NAME` convention `BACKEND.vocoder()` itself
     returns. Denoising stays universal regardless of pipeline shape.
     Visual-smoothing's `.AU`-file read is now guarded by `os.path.exists()`
     (matching the existing `gst_weights`/`path_au` exists-check pattern a few
     lines down) since visual/facial-animation output is backend-optional
     (`SynthesisResult.au_path`, already `Optional`).
  2. `AudioResult.stage_durations` (dict, insertion-ordered) replaces the named
     `tts_duration_s`/`vocoder_duration_s`/`denoiser_duration_s` fields --
     `"vocoder"` is simply absent when `needs_vocoder` is false.
  3. `chatterbox/cli.py`'s console reporting and `chatterbox/gui/app.py`'s
     `_update_audio_info()` updated to read the generic dict (the latter is a
     minimal compatibility shim for now -- `update_audio_infos()`'s own
     hardcoded 3-argument signature gets replaced by a generic pooled-row
     renderer in phase 4).
- Files: `chatterbox/synth.py`, `chatterbox/cli.py`, `chatterbox/gui/app.py`,
  `tests/test_synth.py`, `tests/test_gui_worker.py`.
- Why: see phase 1's entry above for the full user request/context.
- Verify: full test suite (234 passed/1 skipped -- one new test added
  confirming "vocoder" can be legitimately absent from `stage_durations`).
- Notes/gotchas: phase 3 (backend.py's `describe_controls()` schema + dict-keyed
  `gui_control`) and phase 4 (app.py's generic control panel + duration rows)
  are next; `update_audio_infos()`'s signature is intentionally still
  FS2-specific until phase 4.

---

## 2026-07-22 — Interchangeable-backend GUI, phase 3/5: describe_controls() schema, dict gui_control

- What: third phase of the interchangeable-backend refactor (plan file:
  `C:\Users\rphev\.claude\plans\reflective-shimmying-ember.md`).
  `FastSpeech2HifiGanBackend.describe_controls()` now emits the full
  `"controls"` schema mirroring exactly what `gui_fastspeech2()` used to
  hand-build directly from `config_tts.yaml`: style chip grid (`TOKEN13-16`
  placeholders hidden via `hidden_pattern`), style-intensity slider, pitch/
  energy/speed sliders, 5 "bias" sliders, StyleTag free-text entry -- read from
  the same YAML keys it already had (no new YAML schema for the controls
  themselves).
  1. `load_fastspeech2()` now keeps the `config_tts.yaml` model entry itself
     (`self.tts_model_config`) alongside the parsed FastSpeech2 sub-configs
     (`self.configs`) -- `describe_controls()` needs it.
  2. `syn_fastspeech2()`'s `gui_control` unpacking changed from a fixed
     12-element positional list to a dict keyed by the same "key"s
     `describe_controls()` declares -- the fragile part of the old contract a
     different backend couldn't conform to. Uses `.get(key, <yaml default>)`
     throughout so an undeclared control falls back to the model's own
     configured default instead of a `KeyError`, matching today's actual
     behavior (a hidden-but-created slider/entry still contributes its
     default value).
  3. Bias sliders get an `"advanced"` flag from `gui_control_bias` -- phase 4's
     generic panel will add one shared "advanced controls" reveal toggle for
     these, where today there was none at all (`gui_control_bias: False` meant
     permanently absent, no way to reveal from the GUI). A small, low-risk UX
     improvement that falls out of building this generically, not a design
     goal on its own.
- Files: `chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py`,
  `tests/test_backend_describe_controls.py` (new, 7 tests).
- Why: see phase 1's entry above for the full user request/context.
- Verify: full test suite (241 passed/1 skipped -- 7 new).
- Notes/gotchas: phase 4 (`app.py`'s generic control panel + duration rows) is
  next -- until then `gui_fastspeech2()` in `app.py` still builds the panel the
  old, hand-written way and does NOT yet call `describe_controls()["controls"]`
  at all; this phase only prepared the data the backend side will hand over.

---

## 2026-07-22 — Interchangeable-backend GUI, phase 4/5: generic control panel + duration pool

- What: fourth (largest) phase of the interchangeable-backend refactor (plan
  file: `C:\Users\rphev\.claude\plans\reflective-shimmying-ember.md`).
  `gui_fastspeech2()` -- FS2-specific, hand-written widget code -- is replaced
  by `gui_generic_controls()`, which renders the panel entirely from the
  active backend's `describe_controls()`: a speaker dropdown (skipped for a
  backend with no `speaker_list`) plus one widget per `"controls"` entry,
  dispatched by `"type"` (`chip_grid`/`slider`/`text`) to small builder
  helpers reusing the exact logic `gui_fastspeech2()` used to hand-write
  (stable-sort-default-first, dynamic 4-row chip columns, `hidden_pattern`-
  gated placeholders).
  1. `get_gui_controls()` returns a dict (was a fixed 12-element positional
     list) assembled from `_generic_control_widgets`.
  2. `describe_controls()` gained `"default_speaker"` (the backend's own
     configured default speaker index) -- `app.py` no longer reads
     `config_tts.yaml`'s `default_args` directly at all for the speaker
     dropdown, keeping it fully generic.
  3. Bias sliders' `"advanced"` flag now drives one new shared "Contrôles
     avancés" toggle in the generic panel -- reveals/hides them together
     instead of `gui_control_bias: False` meaning permanently absent with no
     way to show them from the GUI (a small, low-risk UX improvement, not a
     design goal on its own).
  4. Duration display: the 3 hardcoded tts/vocoder/denoiser labels are
     replaced by a pool of 3 generic rows, assigned to whichever
     `stage_durations` keys are present at synthesis time via one shared i18n
     template (`stage_duration_label`) + a display-name lookup, instead of 3
     separate pre-written i18n keys -- hides any pool row a synthesis didn't
     use (e.g. no `"vocoder"` for a monolithic backend). The "Afficher les
     données de synthèse" menu checkbox now tracks how many pool rows are
     actually active so re-enabling it doesn't reveal an unused row.
  5. `config_tts.yaml`'s `gui_script` now points at `gui_generic_controls`.
- Files: `chatterbox/gui/app.py`, `chatterbox/gui/i18n.py`,
  `chatterbox/synthesis/base.py`, `chatterbox/synthesis/backends/
  fastspeech2_hifigan/backend.py`, `chatterbox/config/config_tts.yaml`,
  `tests/test_backend_describe_controls.py`.
- Why: see phase 1's entry above for the full user request/context.
- Verify: full test suite (242 passed/1 skipped, unchanged). New ad hoc Tk
  smoke test (mocked `describe_controls()`, no pretrained weights) confirmed
  pixel-identical FS2 layout (speaker dropdown defaults correctly, style grid
  still 4 rows x 3 cols for 12 named tokens, all 9 sliders present with
  matching ranges/resolutions/defaults), the new advanced-controls toggle
  correctly shows/hides bias sliders, `get_gui_controls()`'s keys match what
  `backend.py`'s `syn_fastspeech2()` reads, and the duration pool correctly
  handles both a 2-stage (monolithic-shaped) and 3-stage (today's FS2) result.
- Notes/gotchas: phase 5 (`needs_vocoder`-gated Vocodeur picker + phoneme-
  keyboard fallback) is last -- until then the Vocodeur picker always shows
  and the Phonèmes keyboard has no fallback behavior wired up yet even though
  the capability flags/config setting exist (phase 1).

---

## 2026-07-22 — Interchangeable-backend GUI, phase 5/5: vocoder gating + phoneme fallback

- What: fifth and final phase of the interchangeable-backend refactor (plan
  file: `C:\Users\rphev\.claude\plans\reflective-shimmying-ember.md`) -- wires
  up the two static per-model capability flags from phase 1 (`needs_vocoder`,
  `accepts_phoneme_input`) to actual GUI behavior.
  1. Settings -> Advanced's Vocodeur picker row is skipped entirely when the
     selected TTS model's `needs_vocoder` is false (a monolithic model has
     nothing to pick).
  2. `_keyboard_emit()` checks the active model's `accepts_phoneme_input`:
     when false, a phoneme keypress inserts the key's already-computed display
     label (ordinary French spelling, e.g. "CH"/"ON") instead of the raw phone
     code (this backend's own custom phone-symbol alphabet -- no G2P step
     exists anywhere in this pipeline for a different backend to fall back
     on). Per the user's explicit choice, the fallback itself is a config
     setting (`GUI_config.phoneme_fallback`): `"translate_labels"` (default)
     keeps the Phonemes keyboard usable with that substitution;
     `"hide"` removes the Texte/Phonemes toggle and the phoneme keyboard
     entirely, forcing Texte-only mode.
  3. `_apply_keyboard_capabilities()`/`_refresh_keyboard_capabilities` (new,
     mirrors the existing `_refresh_orientation` pattern) re-evaluates
     `accepts_phoneme_input` whenever the TTS model is switched live from
     Settings -> Advanced, not just once at startup.
  4. Compat fix found via smoke testing: `chatterbox/gui/keyboards.py`'s
     "Emmanuelle" phoneme keyboard has its own hardcoded mood-shortcut keys
     (`:D`/`:p`/`:(`/`:O`) that resolve the literal global name
     `"gst_token_selection"` via `app.py`'s `globals()` to temporarily
     override the GST style selection around a quick styled phrase. Phase 4
     removed that global entirely, which broke GUI startup outright (a
     `KeyError` at button-creation time, not even requiring a keypress).
     Fixed by keeping `gst_token_selection` as a compat alias, set to the
     "style" chip_grid's `IntVar` whenever `gui_generic_controls()` builds
     one (module-level default `None` otherwise, so a backend with no
     "style" control degrades to a no-op on those keys instead of crashing).
- Files: `chatterbox/gui/app.py`.
- Why: see phase 1's entry above for the full user request/context. This
  closes out the 5-phase refactor -- FastSpeech2+HiFi-GAN now conforms fully
  to the generic contract; a future backend needs only its own module +
  `config_tts.yaml` entry, no `app.py`/`synth.py` changes.
- Verify: full test suite (242 passed/1 skipped, unchanged). New ad hoc Tk
  smoke test (two fake TTS models -- monolithic/no-phonemes vs two-stage/
  phonemes-ok, mocked `describe_controls()`, no pretrained weights) confirmed:
  Vocodeur picker absent for the monolithic model, present after switching to
  the two-stage model; a phoneme keypress inserts "CH " for the no-phonemes
  model and "s^ " after live-switching to the phonemes-capable one;
  `phoneme_fallback="hide"` un-maps the Phonemes mode radio button entirely.
- Notes/gotchas: `keyboards.py`'s "Emmanuelle" mood-shortcut keys and phoneme
  symbol table remain FS2/GST-specific by design (documented, not touched) --
  a future backend that also wants phoneme input support would need its own
  keyboard layout/symbol table, not a reuse of this one.

---

## 2026-07-22 — Seventh feedback round: keyboard fills available height, denser style chips

- What: real-hardware landscape screenshots (800x480-ish) showed the keyboard -- "the most
  important aspect of the GUI" -- sitting small and anchored to the top of its column, with a lot
  of dead space below it, while the Style chip grid read as comparatively large.
  1. The landscape keyboard now grids with `sticky=tk.NSEW` instead of `sticky=tk.N`. The
     previously-computed `natural_height` (via `grid_propagate(False)` + explicit `height=`,
     sixth round) is still the *minimum* -- still protects against the earlier "huge letters"
     regression -- but the frame now stretches to fill however much height its row span actually
     has, instead of anchoring at its own natural minimum and leaving blank space below.
     `keyboard_area`'s own weighted internal row (and each keyboard's own weighted button rows/
     columns) grow to fill that, so the keys themselves get physically bigger.
  2. Style chips: width capped at 9 characters (was sized to fit the single longest option name,
     "RECONFORTANT"/"ENTHOUSIASTE" at 12 chars, forcing every chip that wide), smaller font (8pt)
     and padding, with each chip's label bound to wrap to its own actual rendered width (the
     existing letter-keyboard "Tout effacer" wraplength-on-`<Configure>` fix extracted into a
     shared `_wrap_label_to_width()` helper) so a name past the cap wraps onto two lines instead
     of forcing an oversized button or silently clipping.
  3. Duration-info pool rows (added in the interchangeable-backend refactor, phase 4) now start
     `grid_remove()`'d instead of gridded-with-blank-text -- they previously still claimed their
     row height before any synthesis had run, leaving a dead, empty-looking gap and denying that
     height to the options panel's own weighted row. Real-hardware feedback: "as the synthesis
     data has been reduced, it may be useful to extend the upper window" -- this reclaims that
     space for the options panel automatically via the existing weight mechanism.
- Files: `chatterbox/gui/app.py`.
- Why: seventh real-hardware feedback round (landscape, 800x480-ish kiosk screen).
- Verify: full test suite (242 passed/1 skipped, unchanged). New ad hoc Tk smoke test at a real
  800x480 landscape geometry confirmed: keyboard height now matches the full window height (480,
  was capped at its ~263px natural minimum); duration pool rows unmapped before any synthesis, all
  three mapped after a 3-stage result; a 12-char style-chip label is capped at `width=9` with a
  nonzero `wraplength` instead of forcing a wide button.

---

## 2026-07-22 — Eighth feedback round: fixed 0.6 keyboard share both orientations, bigger chips

- What: real-hardware feedback on the previous round's fixes. Landscape: "the right share of
  keyboard seems to be between 1/2 and 2/3 of the screen. Disable the option to choose the share
  in parameters and find an optimal share." Portrait: "the keyboard is very small compared to the
  window... the share [is] far below the landscape orientation. Make the keyboard bigger." Also:
  "Style boxes can be slightly bigger to match the range of the pitch and energy cursors" (the
  previous round's chip-shrink read as a bit too aggressive once seen next to the sliders).
  1. `_keyboard_landscape_fraction` (user-configurable via Settings -> Advanced, three presets
     1/2 through 3/4) replaced by a single fixed module constant, `_KEYBOARD_SCREEN_SHARE = 0.6`
     -- inside the requested range. The Settings -> Advanced picker section and
     `_set_keyboard_landscape_fraction()` removed; i18n's now-unused `keyboard_width_*` keys
     removed too.
  2. Portrait now applies the *same* mechanism landscape already used (measure natural size with
     `grid_propagate(True)`, then `grid_propagate(False)` + explicit width/height + `sticky=NSEW`)
     but on **height** instead of width: the keyboard's height floor is now
     `max(natural_height, window_height * 0.6)`, giving portrait the same ~60% share landscape
     already had -- previously portrait's keyboard row had no weight of its own (unlike row 2, the
     options panel), so it only ever got its own small natural minimum.
  3. Style chips sized back up slightly: width cap 9->10, font 8->9pt, padding 2/4->3/6.
- Files: `chatterbox/gui/app.py`, `chatterbox/gui/i18n.py`.
- Why: eighth real-hardware feedback round.
- Verify: full test suite (242 passed/1 skipped, unchanged). New ad hoc Tk smoke test confirms:
  landscape keyboard width is exactly 0.6x window width; portrait keyboard height is exactly 0.6x
  window height after a genuine orientation flip (matching landscape's ratio); the Settings
  keyboard-width picker is gone; a 12-char style-chip label is capped at `width=10` with font
  size 9.
- Notes/gotchas: `_apply_current_orientation()` only recomputes sizing on an actual
  portrait<->landscape flip (an existing, intentional optimization, not new) -- a same-orientation
  resize (e.g. portrait window just getting taller) won't re-derive the keyboard's height from the
  new dimensions until the orientation actually flips at least once. Not addressed here; flagged
  in case a future round needs it (e.g. by also reacting to `<Configure>` size deltas within the
  same orientation, not just flips).

---

## 2026-07-22 — Ninth feedback round: stale scrollregion, cropped Synthèse, chip columns per orientation

- What: real-hardware feedback on the previous round.
  1. Landscape: clicking "Contrôles avancés" made the checkbox itself disappear and "Biais de
     hauteur" render partly out of frame. Root cause: `canvas.config(scrollregion=canvas.bbox(
     "all"))` was computed once at build time and never recomputed -- revealing more rows below
     the fold (via `grid()`/`grid_remove()`) grows `frame_options`' actual content height, but the
     canvas's scrollbar range stayed capped at the original, smaller size, so the newly-revealed
     rows became genuinely unreachable by scrolling. Fixed by binding `frame_options`' own
     `<Configure>` to recompute the scrollregion whenever its rendered size actually changes (the
     standard Tkinter scrollable-frame idiom) instead of a one-time computation.
  2. Landscape: "Synthèse is partly hidden by 'Texte à saisir'." That label's own unweighted
     column left too little of the row's remaining width for the weighted Synthèse-button column,
     clipping it to "nthè". Shortened the label to "Saisie" per the user's own suggestion.
  3. Landscape: "Rejouer and Mettre en veille buttons can be placed slightly upper." The status/
     error label (row 13) permanently reserved a blank row between the duration info and those two
     buttons even with nothing to show. Now `grid_remove()`'d whenever there's no error (`_set_ui_
     state()`), matching the same hide-when-empty idiom already used for the duration-info pool.
  4. Portrait: "Styles and cursors can take more space in vertical, there can be 4 styles per
     row." The chip grid's "target ~4 rows" column computation (introduced for landscape, where
     the keyboard shares screen width) was being applied in portrait too, where there's no such
     constraint. `_build_chip_grid_control()` now takes a `landscape` flag (decided once at GUI
     build time from the window's actual on-screen shape): landscape keeps the narrower ~3-per-row
     computation, portrait uses a flat 4-per-row (the original, pre-adaptive default).
- Files: `chatterbox/gui/app.py`, `chatterbox/gui/i18n.py`.
- Why: ninth real-hardware feedback round.
- Verify: full test suite (242 passed/1 skipped, unchanged). New ad hoc Tk smoke test confirms:
  the canvas scrollregion's height grows after revealing the bias sliders; the "Saisie" label
  renders; the status label starts unmapped, maps on an error, unmaps again back to idle; the
  style chip grid renders 3 columns at a landscape-shaped (900x480) window and 4 columns at a
  portrait-shaped (440x800) one.
- Notes/gotchas: the chip-grid orientation choice is decided once at build time, not live-
  reactive to a later manual orientation override in Settings -> Advanced -- consistent with this
  app's "portrait is native, landscape is maintenance-only" design, not expected to flip mid-
  session in normal use.

---

## 2026-07-22 — Sixth feedback round: landscape row-0 collision, keyboard label clipping

- What: real-hardware screenshots (800x480-ish landscape kiosk screen) showed the entire
  speaker/style options panel gone and "Mettre en veille" cut off past the bottom edge. Root
  cause, confirmed with a reproduction script driving the real `create_gui()` at 800x480: the
  landscape keyboard was gridded at a single row (`row=0`), but Tk's grid row height is shared
  across every column at that row index -- placing the ~263px-tall keyboard there forced row 0 to
  be ~263px tall for EVERY column, including column 0 where only a small battery label lives. That
  stole the vertical budget from row 2 (the options panel, the only weighted row), collapsing it
  from a healthy size to 7px, while the fixed rows below it (Texte a saisir, duree labels, Rejouer,
  Mettre en veille) kept their natural size and overflowed past the window's bottom edge.
  Fixed by spanning the keyboard across the same row range the main content stack already
  occupies (`rowspan=18+index_gst_token`) instead of a single row, so its height gets absorbed by
  row 2 (still the only weighted row in that span) instead of inflating row 0 alone.
- Also fixed: the letter keyboard's "Tout effacer" button rendered as "out effacer" -- clipped
  once the landscape width cap (Settings -> Advanced fraction) made its column narrower than the
  label's natural width, same class of bug as the earlier GST-token chip clipping. Its control-row
  buttons (Espace/Effacer/Tout effacer/Play) now bind `wraplength` to their own actual
  `<Configure>` width, so labels wrap instead of clipping regardless of the chosen fraction.
- Files: `chatterbox/gui/app.py` (`_apply_current_orientation()`, `_create_letter_keyboard()`).
- Why: sixth real-hardware feedback round (800x480-ish kiosk screen).
- Verify: full test suite (233 passed/1 skipped, unchanged). New ad hoc Tk reproduction at a real
  800x480 geometry confirmed: options-panel frame height went from 7px (collapsed) to 270px;
  "Mettre en veille" (row 17) still ends exactly at the window's bottom edge (480), no longer past
  it; "Tout effacer" now reports a nonzero `wraplength` (66px) matching its actual rendered width
  instead of clipping.
- Notes/gotchas: row 17 (Mettre en veille) still ends EXACTLY at the window's bottom edge with no
  slack on an 800x480 screen -- any future addition to the fixed-row stack (another always-visible
  label/button) will need either more vertical budget or to go behind a toggle, the same way
  audio-info rows already do.

---

## 2026-07-22 — Fifth feedback round: landscape keyboard zero-height bug, style grid rows

- What: user reported "both keyboards disappeared, whatever dimension we chose" (the landscape
  keyboard-width fraction from the fourth round) and asked for the style chip grid to use 4 rows
  so every style fits once the keyboard takes half the screen.
  1. Root cause of the disappearing keyboards: `grid_propagate(False)` stops Tk deriving BOTH
     width and height from a frame's children, not just width -- the landscape reflow
     (`_apply_current_orientation()`) only ever called `.config(width=...)`, never `height=`, so
     `keyboard_area` silently collapsed to ~0px tall the moment propagate was turned off,
     regardless of the configured fraction (the fraction only ever changed the width that was
     being applied to an invisible frame). Fixed by measuring `winfo_reqheight()` with propagate
     still on (so it reflects the actual keyboard content) immediately before locking the frame's
     size, and passing that as an explicit `height=` alongside `width=`.
  2. GST-style chip grid: columns-per-row was a fixed 4, giving 3 rows for the 12 named tokens --
     real-hardware feedback was that 4-wide rows overflowed the narrower options column once the
     landscape keyboard ate half the screen's width. Chips-per-row is now derived from the named
     (non-`TOKEN*`-placeholder) token count via ceiling division targeting 4 rows, giving 3
     columns x 4 rows for the current 12-token config instead of 4x3.
- Files: `chatterbox/gui/app.py` (`_apply_current_orientation()`, `gui_fastspeech2()`'s style
  chip-grid block).
- Why: fifth real-hardware/PC feedback round.
- Verify: full test suite (233 passed/1 skipped, unchanged). New ad hoc Tk smoke test (mocked
  model loading, no pretrained weights) confirmed: landscape `keyboard_area` height is 263px (not
  ~0) after a resize + fraction change; the 12 named style chips land on grid rows 0-3 (4 rows)
  across columns 0-2 (3 columns).
- Notes/gotchas: `_CHIPS_PER_ROW` is no longer shared between the speaker dropdown and the style
  grid -- it now only sizes the speaker dropdown's columnspan; the style grid computes its own
  `_style_chips_per_row`. If the named-token count changes (a new style trained, or a placeholder
  promoted to real), the column count reflows automatically to keep ~4 rows rather than needing a
  manual constant update.

---

## 2026-07-21 — Power-timer presets: eliminate overlap between adjacent ranges

- What: user clarified the ambiguous "timer before assombrissement" comment from the fourth
  feedback round: the old preset ranges overlapped enough that a nonsensical combination (2min
  dim + 30s screen-off) was directly pickable. `_DIM_PRESETS` now tops out at 2min,
  `_DARK_PRESETS` starts at 2min and tops out at 30min, `_DEEP_PRESETS`'s shortest real option
  (excluding "Désactivé"/0) now starts at 30min (same pattern applied to dark/deep for
  consistency; added a 4h option since 5min/15min no longer fit that range).
- Files: `chatterbox/gui/settings.py`.
- Why: direct user clarification -- see the fourth feedback round's changelog entry for the
  original ambiguous comment.
- Verify: full test suite (233 passed/1 skipped, unchanged -- `validate_power_settings()`'s own
  `>` check is untouched, still the actual enforcement at save time) plus a re-run of the settings
  smoke test confirming the dark-timer dropdown reflects the new range with a custom loaded value
  still correctly inserted ("20 min (actuel)" for 1200s).
- Notes/gotchas: the exact boundary case (dim=2min AND dark=2min, both now valid preset picks) is
  still only caught by save-time validation, not prevented by the preset ranges themselves --
  narrowing how far off an accidental pick can be, not a replacement for that check.

---

## 2026-07-21 — Fourth feedback round: powerd reload bug, settings scroll, keyboard sizing

- What: nine fixes from a fourth feedback pass, across three commits:
  1. **Real daemon bug**: `PowerFSM.set_config()` only swapped the config dict -- brightness only
     re-applied on the NEXT actual state transition, which might never come soon after a Settings
     save (daemon usually already sitting in ACTIVE/DIM). Now re-runs the current state's entry
     actions immediately (skipped in DEEP, terminal). 3 new FSM tests.
  2. Preset-dropdown custom ("actuel") values now format in the same s/min/h units as the presets
     (1200s showed as "1200 s (actuel)" next to "10 min"/"30 min" presets -- now "20 min (actuel)").
  3. Settings dialog: scrollable content area + a FIXED footer (error text + Enregistrer/Annuler)
     -- this round's added fields (timer dropdowns, percent scales, Avancé section) could push the
     window taller than the actual screen with nothing to scroll it.
  4. Added an inline warning when `chatterbox-powerd` isn't reachable -- "mettre en veille
     ineffective"/"brightness doesn't change"/"enregistrer=annuler" most likely all trace to this.
  5. Orientation radios now `indicatoron=0`+`selectcolor` (chip style) instead of a plain radio
     dot -- likely why the current selection wasn't visibly registering.
  6. Speaker chip grid replaced with a dropdown beside "Locuteur :" -- speakers don't change often
     and some future backends may have only one voice; frees width for the style chip grid.
  7. Added a "Tout effacer" (clear all) button to the letter keyboard -- only backspace existed.
  8. **Root-caused** "keyboard huge/takes all the space" in landscape: `rowspan=20` pulled in the
     options panel's own large weighted row height, inflating the keyboard's internal weighted
     buttons vertically too, with no width cap at all. Replaced with natural-height/top-anchored
     placement + an explicit pixel-width cap (`grid_propagate(False)`), now a configurable
     Settings -> Advanced fraction (1/2 default, 2/3, 3/4), applied live.
- Files: `chatterbox/power/fsm.py`, `chatterbox/gui/settings.py`, `chatterbox/gui/app.py`,
  `chatterbox/gui/i18n.py`, `tests/test_power_fsm.py`.
- Why: direct user feedback after a fourth testing round.
- Verify: `.venv/Scripts/python.exe -m pytest tests/` -- 233 passed/1 skipped (230 + 3 new FSM
  tests), unchanged otherwise. Multiple mocked smoke runs confirmed: FSM re-applies brightness
  immediately in ACTIVE/DIM and leaves DEEP alone; settings dialog's scroll canvas and footer are
  separate grid rows; a 1200s custom value shows as "20 min (actuel)"; the powerd warning appears
  (this checkout has none reachable); the speaker dropdown shows AD first and updates the correct
  underlying index; "Tout effacer" empties the entry; the landscape keyboard measures exactly
  500px in a 1000px window at 1/2 default and exactly 750px after switching to 3/4 live.
- Notes/gotchas: two items from this round were deliberately NOT implemented, pending user
  input -- (a) an ambiguous "timer before assombrissement can't be lower than the time it takes
  for the screen to dim" comment (asked the user for clarification rather than guess), and (b)
  whether orientation override should rotate the WHOLE screen (terminal included) vs. just the
  GUI's own layout (today's behavior) -- presented trade-offs, awaiting the user's decision.

---

## 2026-07-21 — Third feedback round: settings modal bug, chip defaults, landscape crop root cause

- What: six fixes from a third feedback pass, split across two commits:
  1. **Real bug**: the Réglages Toplevel was never made modal (no `transient()`/`grab_set()`), so
     clicks landed on the main window behind it. Fixed with `transient()`+`grab_set()`+
     `focus_set()`, `grab_release()` added to `close()`.
  2. Power-timer sliders (assombrissement/extinction/veille profonde) replaced with preset
     dropdowns scoped to each field's role; a non-preset loaded value shows as its own
     "(actuel)" option rather than silently snapping.
  3. Brightness sliders now show 0-100% instead of raw 1-255 -- conversion only at the GUI
     boundary, `write_settings()`/powerd/backlight driver untouched.
  4. Default speaker (AD)/style (NEUTRE) chips now render at grid position [0,0] via a stable
     sort of `enumerate(...)` by "is this the default" -- the chip's `value` stays each item's
     ORIGINAL index (the real model speaker ID / the index `keyboards.py`'s hardcoded mood-
     shortcuts depend on), only draw order changes. Reverted the previous round's
     `gst_token_list` YAML reorder (unnecessary now) back to alphabetical/stable order,
     `gst_token_index` back to 8.
  5. All 9 sliders now `sticky=W` -- previously centered in their cell, so position shifted
     unpredictably between portrait/landscape.
  6. **Root-caused** "Synthèse cropped in landscape": the options-panel canvas's one-time
     `width=`/`height=` hint (440x400) was a hard grid MINIMUM regardless of weight -- in a
     landscape window shorter than 400px, that minimum forced the window taller than the actual
     screen, pushing everything below the options panel off-screen. Replaced with a
     `<Configure>` binding on the surrounding frame that keeps canvas's size matched to whatever
     the grid actually allocates it.
- Files: `chatterbox/gui/settings.py`, `chatterbox/gui/app.py`, `chatterbox/config/config_tts.yaml`.
- Why: direct user feedback after a third round of testing (mix of PC and Pi 5).
- Verify: `.venv/Scripts/python.exe -m pytest tests/` -- 230 passed/1 skipped, unchanged
  (`validate_power_settings()`/`write_settings()` signatures untouched). Two mocked smoke runs:
  settings dialog holds the modal grab, a non-preset value shows as "45 s (actuel)", brightness
  204/255 shows as 80% and saving at 50% writes back 128; AD/NEUTRE chips render at row=0/col=0
  and are selected by default, sliders report `sticky="w"`, and the options canvas shrinks to
  279px (well below the old 400px floor) in a short 350px-tall landscape window.

---

## 2026-07-21 — Orientation override + kiosk maintenance-recovery docs

- What: the two items deferred from the second feedback round:
  1. Settings -> Advanced gains an Auto/Portrait/Paysage orientation override (`_orientation_override`
     module global + `_set_orientation_override()`/`_refresh_orientation` in `gui/app.py`). "Auto"
     keeps the `<Configure>`-based detection; forcing Portrait/Paysage applies immediately and
     makes further real resize events a no-op until set back to Auto.
  2. `docs/kiosk/KIOSK.md` gained a "Maintenance / recovery access" section (manual SSH-over-
     Ethernet, config.txt dtoverlay restore, getty@tty1 re-enable steps) instead of an in-GUI
     feature -- both radios and getty are boot-time config, not live-toggleable, and a kiosk-escape
     control needs real access-control design not yet done.
- Files: `chatterbox/gui/app.py`, `chatterbox/gui/i18n.py`, `docs/kiosk/KIOSK.md`.
- Why: user asked for a persisted-feeling manual orientation override (kiosk windows may never
  actually resize at runtime, defeating pure auto-detection) and a way back into a locked-down
  kiosk Pi once `scripts/kiosk_finalize.sh` disables wifi/bluetooth/console login.
- Verify: `.venv/Scripts/python.exe -m pytest tests/` -- 230 passed/1 skipped, unchanged. Two
  mocked `create_gui()` smoke runs: forcing landscape/portrait moves `keyboard_area` with no real
  window resize, switching back to Auto restores real detection; the radio buttons render in
  Settings -> Advanced and clicking one sets the override correctly.
- Notes/gotchas: the user picked the Settings -> Advanced *location* explicitly; persistence
  wasn't separately confirmed, so this implementation defaulted to **runtime-only** (resets to
  Auto on GUI restart, not persisted to `user_prefs.yaml`) as the smaller/reversible choice.
  Flagged back to the user -- revisit if they actually want it to survive a restart.

---

## 2026-07-21 — Second real-hardware feedback round: landscape width, chip labels, apostrophe

- What: six fixes from a second Pi/PC feedback pass (landscape crop persisted after the first
  round's fixes; new issues surfaced):
  1. Landscape keyboard column no longer weighted (was competing with the options panel for
     extra width -- "keyboard takes a lot of space"); stays at natural/minimum width now.
  2. Added a horizontal scrollbar to the options-panel canvas as an explicit fallback (still no
     way to reach horizontally-overflowing content in landscape).
  3. Speaker/style labels moved to their own row above the chip grid instead of a column to its
     left -- frees horizontal space for the grid itself.
  4. Chip width now computed from the longest label in each grid instead of a fixed `width=11` --
     "RECONFORTANT"/"ENTHOUSIASTE" (12 chars) were being clipped.
  5. Added an apostrophe key to the letter keyboard -- missing but essential for French.
  6. Renamed the replay button "Lire" -> "Rejouer" -- was confusable with the keyboards' own "▶"
     play button (that one re-synthesizes; this one only replays the last audio).
- Files: `chatterbox/gui/app.py`, `chatterbox/gui/i18n.py`.
- Why: direct user feedback after testing on the Pi 5 a second time.
- Verify: `.venv/Scripts/python.exe -m pytest tests/` -- 230 passed/1 skipped, unchanged. Mocked
  `create_gui()` smoke run confirmed: landscape keyboard column weight is 0 (was 1), the options
  canvas has a horizontal scrollbar, style label/chip-grid are on consecutive (not shared) rows,
  the "RECONFORTANT" chip is wide enough (13) not to clip, the apostrophe key inserts `'`
  correctly, and the replay button reads "Rejouer".
- Notes/gotchas: three items from this same feedback round are NOT yet addressed, deliberately --
  they need more than a mechanical fix: (a) "Mettre en veille doesn't seem to be effective" --
  most likely `chatterbox-powerd` isn't running/reachable on the user's Pi (the client silently
  no-ops if it can't connect at GUI startup, and doesn't retry), not a code bug in anything
  touched this session; needs the user to confirm powerd's status before further action. (b) A
  settings toggle to force portrait/landscape manually (as a persisted override, not just live
  `<Configure>`-based auto-detection) -- open design question on where it lives / how it's
  persisted. (c) A "Maintenance access" entry to re-enable wifi/bluetooth/terminal once the kiosk
  is boot-locked (`scripts/kiosk_finalize.sh`) -- a security-sensitive feature (`dtoverlay=disable-
  wifi/-bt` in `config.txt` needs a reboot to take effect, isn't a runtime toggle; a kiosk-escape
  terminal needs real access-control thought) that needs a design conversation, not blind
  implementation.

---

## 2026-07-21 — PC-GUI feedback: menu reorg, settings auto-size, style/speaker defaults

- What: five corrections from user testing on PC (not the Pi):
  1. Moved "Réglages" from a physical main-window button (sat directly above the keyboard area)
     into a "Paramètres" menu entry -- drops Settings from the switch-driven NavRing, deemed
     acceptable since physical switches aren't wired/validated on any real deployment yet.
  2. "À propos" moved to the far right (last) of the menu bar.
  3. Removed the settings dialog's hardcoded `win.geometry("420x420")` -- didn't scale to actual
     content (worse once the "Avancé" model-picker section existed); Tk now auto-sizes it.
  4. Reordered `config_tts.yaml`'s `gst_token_list` so NEUTRE sits at index 6 (middle of the 3x4
     chip grid) instead of 8, chosen to not disturb `keyboards.py`'s hardcoded mood-shortcut
     indices; `default_args.gst_token_index` 8->6 to keep pointing at NEUTRE.
  5. Confirmed (no change needed) that the default speaker (AD, `speaker_id: 4`) and default style
     (NEUTRE) were already correct, against `assets/models/FastSpeech2/preprocessed_data/
     ALL_corpus/speakers.json`.
- Files: `chatterbox/gui/app.py`, `chatterbox/gui/i18n.py`, `chatterbox/gui/settings.py`,
  `chatterbox/config/config_tts.yaml`.
- Why: direct user feedback after testing the real-hardware-bugfix session's GUI on PC.
- Verify: `.venv/Scripts/python.exe -m pytest tests/` -- 230 passed/1 skipped, unchanged. A mocked
  `create_gui()` smoke run confirmed: menu order/labels, no physical Réglages button, settings
  dialog auto-sizes (562x461 observed vs. the old fixed 420x420), NEUTRE chip position + default
  selection, AD default selection.
- Notes/gotchas: item 1 is a deliberate accessibility trade-off (Settings no longer reachable via
  the physical switch-driven NavRing) -- revisit if `user_prefs.yaml`'s `switches:` list is ever
  populated for a real deployment.

---

## 2026-07-21 — Battery percentage display (DFRobot FIT0992 UPS HAT)

- What: new `chatterbox/power/battery.py` reads battery voltage/percentage over I2C (i2c-1 @
  0x36, a Maxim/Analog-Devices MAX17048-style fuel gauge) for the DFRobot FIT0992 Raspberry Pi 5
  UPS HAT. `gui/app.py` polls it every 30s and shows a "🔋 NN%" label (row 0 -- the space freed up
  when model selection moved into Settings -> Advanced), red under 20%, hidden entirely whenever
  no reading is available (no hardware/no `smbus2` -- the normal case for any other checkout).
  New `add_battery_info` config flag (default `True`).
- Files: new `chatterbox/power/battery.py`, `tests/test_power_battery.py`; modified
  `chatterbox/gui/app.py`, `chatterbox/config/config_tts.yaml`, `requirements-pi.txt` (comment
  only -- `smbus2` now has a second consumer), `CLAUDE.md`.
- Why: user request, mid-session, once the exact SKU (FIT0992) was confirmed. Register
  addresses/scaling (VCELL @ 0x02, SOC @ 0x04, byte-swap-then-scale) were verified against the
  exact reference driver DFRobot's own FIT0992 wiki page links to
  (github.com/suptronics/x120x/bat.py) rather than guessed -- wrong I2C register addresses sent to
  real hardware was an explicit thing to avoid here.
- Verify: `tests/test_power_battery.py` (byte-swap pure-function round-trip against a known value;
  `read_battery()` degrades to `None` on this checkout, which has no `smbus2` installed -- the
  same guarded-optional-hardware posture as `chatterbox/power/amp.py`). GUI wiring verified with a
  mocked `create_gui()` smoke run (shortened poll interval, `battery.read_battery` monkeypatched):
  label starts hidden, shows the right text/color for a healthy and a low reading, hides again
  once the reading goes back to `None`. Full suite: 230 passed/1 skipped (227 + 3 new).
- Notes/gotchas: **not yet verified against the real FIT0992 on Pi hardware** -- the register
  map/scaling is taken on faith from the vendor-linked reference driver (same chip family,
  different product line: X1200/X1201/X1202 UPS shields, not the FIT0992 itself), not confirmed
  against this exact board. First real-hardware run should sanity-check the reported percentage
  against the board's own behavior (e.g. does it read ~100% on a freshly charged cell, does it
  track a charge/discharge cycle sensibly) before trusting it further.

---

## 2026-07-21 — GUI real-hardware bug-report fixes (post Phase 3)

- What: seven fixes from user testing of the Phase 3 refactor (below) on real Pi 5 hardware:
  1. Column-weight loop covered one column past the widest actual content (max_buttons+2, not
     +1), so a dead column soaked up width in landscape that should've gone to the options panel.
  2. Speaker picker was still a single unwrapped row (only the GST style picker got the chip-grid
     treatment) -- overflowed the canvas viewport with more than 2-3 speakers, no horizontal
     scrollbar to reach the rest. Same wrapped chip-grid treatment as the style picker now.
  3. Replay/Ranger/Réglages sat in grid rows *after* `keyboard_area` (16/18/19 vs its 17) -- on a
     screen too short to show every row, they fell off-screen below the (now taller, two-
     keyboards-in-one) keyboard, in both orientations. Reordered so keyboard_area is last.
  4. Removed the menu's "Paramètres" entry (opened the identical dialog the physical "Réglages"
     button already does; that button has to stay regardless -- it's in the switch-driven
     `NavRing`, which the menu bar isn't reachable from).
  5. Renamed "Ranger" -> "Mettre en veille" (states what it actually does: powerd put-away/dim).
  6. `config_tts.yaml`'s `add_play_button` was `False` -- the earlier replay-button crash fix was
     invisible since the button never showed up. Flipped to `True`.
  7. Added a menu checkbutton to hide/show the 5 synthesis-duration labels (reclaims vertical
     space; the status circle stays visible regardless, separate from the timing breakdown).
- Files: `chatterbox/gui/app.py`, `chatterbox/gui/i18n.py`, `chatterbox/config/config_tts.yaml`.
- Why: direct user bug reports after testing the Phase 3 refactor's 7 commits on a real Pi 5 --
  landscape crop, missing buttons in both orientations, duplicate settings entry point, an
  unclear button label, and an invisible feature toggle.
- Verify: `.venv/Scripts/python.exe -m pytest tests/` -- 227 passed/1 skipped, unchanged. Each fix
  had a one-off mocked-`create_gui()` smoke script (real Tk, no pretrained weights) run manually
  during the session confirming the specific claim (dead column gone, speakers wrap into 2+ rows,
  Replay/Ranger/Réglages rows all precede keyboard_area's row, menu entry counts/labels, toggle
  visibility) -- not checked into `tests/`, same carve-out as the rest of `docs/gui/GUI.md`.
- Notes/gotchas: none of these seven has been re-verified on the Pi yet as of this entry (the
  session ended mid-verification) -- flagged for the next session/user check. A separate,
  not-yet-started request came in mid-session: a battery-percentage display for a DFRobot
  FIT0xxx UPS/fuel-gauge HAT reportedly installed on the Pi 5 -- blocked on the user providing the
  exact SKU (register map/vendor library unknown, didn't want to guess and send wrong I2C
  commands to real hardware).

---

## 2026-07-21 — GUI responsive/accessible refactor (cc_prompt_gui_refactor.md, Phase 3)

- What: seven incremental commits against `cc_prompt_gui_refactor.md`'s Phase 1 audit list (Phase
  0 discovery found the reliability item, #9, already solved in an earlier session — worker
  thread + busy-guard + exception-swallowing were already in place per `docs/gui/GUI.md`):
  1. Responsive grid: `window`/options-panel `columnconfigure`/`rowconfigure` weights replace the
     fixed-pixel `grid_propagate(False)` pinning, so content tracks window size.
  2. Fixed a real latent bug in the "Play" replay button (crashed on click before any synthesis,
     ran unguarded on the Tk thread) by routing it through a new `Action.REPLAY` + `on_replay()`
     on the same worker/busy-guard machinery as Speak.
  3. Portrait/landscape reflow: a `<Configure>` binding moves the embedded keyboard area into a
     second column in landscape (maintenance use) and back in portrait (native orientation).
  4. GST-token style picker: one-radio-per-row column → a wrapped 4-per-row chip grid;
     `TOKEN13`-`16` placeholders (unnamed/untrained LST directions) hidden behind an "Styles
     avancés" toggle.
  5. Added an app-bar menu (Paramètres/À propos wired up; Thème/Langue honest disabled stubs) and
     `chatterbox/gui/i18n.py`, a French string table replacing a hardcoded French/English label
     mix. Caught `tk.Menu()`'s default tearoff entry shifting every menu index.
  6. Demoted the TTS/vocoder model-selector buttons out of the main window into a new "Avancé"
     section of the settings dialog (dependency-injected via `open_settings(...,
     build_advanced_section=...)`, mirroring `gui/input.py`'s no-import-cycle pattern) — kept
     rather than deleted since Matcha-TTS/FastSpeech2s are still being benchmarked.
  7. Added a Texte/Phonèmes segmented toggle and a new simplified-AZERTY soft letter keyboard
     (`app.py:_create_letter_keyboard()`) alongside the existing phonetic grid — both keyboards
     live in one `keyboard_area` container that landscape reflow (item 3) now repositions as a
     unit.
- Files: `chatterbox/gui/app.py`, `chatterbox/gui/input.py`, `chatterbox/gui/settings.py`, new
  `chatterbox/gui/i18n.py`; `CLAUDE.md` (repo map updated for the above).
- Why: `cc_prompt_gui_refactor.md` — Objective 5 (accessible interface) of the project report,
  which flagged the GUI as buggy/slow-to-wake/touchscreen-bound; user confirmed on real Pi 5
  hardware mid-session that the portrait/landscape reflow (item 3) works correctly.
- Verify: `.venv/Scripts/python.exe -m pytest tests/` — 227 passed/1 skipped, unchanged by every
  commit. Each commit additionally has a one-off mocked-`create_gui()` smoke script (real Tk, no
  pretrained weights, `registry.BACKEND` model-loading monkeypatched) run manually during the
  session, not checked into `tests/` — same "needs real weights/Tk, not part of pytest" carve-out
  `docs/gui/GUI.md` already documents for the worker-thread responsiveness check.
- Notes/gotchas: manual on-hardware test checklists were given per-commit in-session; only the
  portrait/landscape reflow (item 3) has been confirmed by the user on a real Pi 5 so far. Chip
  grid touch-target size, French menu label accent rendering, and the new letter keyboard still
  need real-hardware eyes-on. `docs/gui/GUI.md` itself was not updated in this session (still
  accurate on the pre-existing worker-thread/dispatch architecture; the new pieces layer on top
  without changing it) — flagged here in case it drifts further from `app.py`'s actual layout.

---

## 2026-07-21 — Kiosk finalization (step 3): cage decided, opt-in unattended-boot script

- What: `Bring-up_Integration_Test_Protocol_v0.1.md`'s T0-T7 passed on real Pi 5 hardware (per the
  user) — powerd alone, GUI alone, full integration, reliability/fault-injection, and power
  measurement all green. That's the gate for step 3 of `README_power_gui_workstream.md`'s build
  sequence: wrapping the now-known-good stack in an actual unattended kiosk boot.
  - Compositor decision (previously open in the workstream README): **cage**, confirmed with the
    user, matching what `deploy/systemd/chatterbox-gui.service` already assumed. Added `cage`+
    `xwayland` to `apt-packages-pi.txt` (were missing — the unit referenced `/usr/bin/cage` but
    nothing installed it).
  - New `scripts/kiosk_finalize.sh`: the one opt-in script (not part of `setup_pi.sh`'s default
    run) that commits a verified Pi to unattended kiosk boot — read-only EEPROM
    `POWER_OFF_ON_HALT` check, backed-up/idempotent `config.txt`/`cmdline.txt` tuning
    (`dtoverlay=disable-wifi/-bt`, `arm_freq_min=500`, quiet-boot tokens), disables
    `getty@tty1.service` (which would otherwise race `chatterbox-gui.service`'s
    `TTYPath=/dev/tty1` for the same tty — the standard systemd kiosk pattern), and enables+starts
    both systemd units. Deliberately never writes EEPROM (same boot-config brick-risk posture
    already established for the powerd task).
  - New `docs/kiosk/KIOSK.md` (what each step does + how to undo it); `INSTALL.md` gained a
    "Finalizing the kiosk" section pointing at it.
- Files: new `scripts/kiosk_finalize.sh`, `docs/kiosk/KIOSK.md`; modified `apt-packages-pi.txt`,
  `deploy/systemd/chatterbox-gui.service` (comment only — states cage as decided, not open),
  `INSTALL.md`, `CLAUDE.md`, `docs/context/ARCHITECTURE.md` (also updated its stale "unverified on
  hardware" notes for powerd/GUI now that T0-T7 passed).
- Why: the bring-up protocol's own closing line names this as the explicit next gate once T0-T7
  are green.
- Verify: `bash -n scripts/kiosk_finalize.sh` (syntax) + manual review of the idempotent-append
  logic (exact-line/whole-token matching, backup-before-write, never a blind `sed`/rewrite). Not
  runnable from this checkout — no `pytest` coverage applies (all bash/systemd/boot-config, same
  as the powerd task's systemd units) and no SSH access to the Pi this session.
- Notes/gotchas: **not yet run on the Pi** — the user needs to run `scripts/kiosk_finalize.sh`
  and reboot to confirm unattended boot actually works before this is considered done end-to-end.
  Explicitly out of scope (see `docs/kiosk/KIOSK.md`): any EEPROM *write* automation,
  `scripts/hw_check.py` (T1/T2 tooling, already done manually), and wake→interactive boot-time
  measurement (needs a real reboot + stopwatch, feeds `power.t_deep_s`).

---

## 2026-07-21 — Fix the first free-text prompt going invisible (warmup()'s stdout redirect race)

- What: on real Pi 5 hardware, `python3 do_tts.py` (free-text mode) loaded models fine but then
  looked hung — no `"Input Text (Ctrl+C to exit): "` prompt appeared. Typing blind and pressing
  Enter worked anyway, and every prompt *after* the first one displayed correctly, which pinned
  it down: a race between the background warm-up thread (started right before the first
  `input()` call, per the existing "overlap warm-up with the user's first keystrokes" design) and
  `input()`'s own prompt-printing. `warmup()` wraps its throwaway synthesis in
  `contextlib.redirect_stdout(io.StringIO())` to keep it quiet -- but `sys.stdout` is one
  process-wide object, not per-thread. If that redirect is still active (likely: warm-up takes
  ~0.2-0.5s, and starts a hair before the main thread reaches `input()`) at the moment `input()`
  writes its prompt, the prompt text lands in warm-up's throwaway buffer instead of the terminal.
  `input()`'s stdin read is unaffected by stdout redirection, which is why blind-typing still
  worked and why every subsequent prompt (warm-up long since finished) was fine.
  Fix: print the prompt to `sys.__stdout__` (the real stdout stream, captured once at interpreter
  startup -- `contextlib.redirect_stdout` only ever reassigns `sys.stdout`, never touches this)
  instead of through `input()`'s own prompt argument, then call bare `input()` to read the line.
- Files: `chatterbox/cli.py` (free-text loop in `main()`).
- Why: bug report from real Pi 5 usage (once the earlier FastSpeech2-weights setup issue was
  cleared) -- this predates this session's GUI/powerd work (same `contextlib.redirect_stdout`
  pattern existed in the pre-refactor `_warmup_synthesis` closure too) but only actually got
  exercised/noticed now.
- Verify: `.venv/Scripts/python.exe -m pytest tests/` still 227 passed/1 skipped (no test exercises
  the free-text interactive loop directly). The fix itself follows directly from documented Python
  semantics (`sys.__stdout__` is never reassigned by `contextlib.redirect_stdout`/`sys.stdout =
  ...`), not empirically re-tested against the race on real hardware from this session -- **not
  re-run on the Pi**, no SSH access.
- Notes/gotchas: **this fix is on `reorg/phase-0-path-anchoring`, not `master`** -- the Pi that
  reported this bug is running `master`, which has none of this session's power-daemon/GUI-refactor
  work and still has the pre-refactor `_warmup_synthesis` closure (same bug, different code shape).
  This fix needs to reach `master` separately (either a small standalone fix there, or merging this
  branch) before the Pi actually sees it — flagged to the user, not resolved unilaterally.

---

## 2026-07-21 — Harden setup_pi.sh's FastSpeech2 weight check (single-sentinel gave a false PASS)

- What: on real Pi 5 hardware, `python3 do_tts.py` (and `--benchmark`) failed at model load with
  `FileNotFoundError: assets/models/FastSpeech2/config/ALL_corpus/preprocess.yaml`, even though
  `scripts/setup_pi.sh` had reported "pretrained weights present: PASS" earlier. Root cause:
  `fetch_and_unzip()`'s FastSpeech2 call only ever checked one sentinel file
  (`output/ckpt/ALL_corpus/390000.pth.tar`) to decide both "skip re-download" and "download
  succeeded" — but that Drive folder bundles `output/`, `config/`, and `preprocessed_data/`
  separately, so a `gdown --folder` run that fetched the (large) checkpoint but missed the
  (small) config/preprocessed_data files still passed the single-sentinel check and reported
  success, deferring the actual failure to a confusing runtime traceback deep inside
  `backend.py:load_fastspeech2()` instead of surfacing loudly at setup time.
  Changed `fetch_and_unzip()` to accept multiple sentinels (all must exist to skip a re-download;
  all must exist after extraction to report success) and pass it every file
  `load_fastspeech2()`/`describe_controls()` actually open: the checkpoint, all three
  `config/ALL_corpus/*.yaml` files, and `preprocessed_data/ALL_corpus/speakers.json`.
- Files: `scripts/setup_pi.sh`.
- Why: bug report from the first real `do_tts.py --benchmark` run on Pi 5 hardware (this repo's
  power daemon / GUI refactor work so far had only been verified on this PC dev checkout).
- Verify: `bash -n scripts/setup_pi.sh` (syntax) + a standalone bash unit-check of the new
  multi-sentinel skip/report logic (present/missing/all-present cases) confirmed correct exit
  codes; `.venv/Scripts/python.exe -m pytest tests/` still 227 passed/1 skipped (unrelated to this
  bash-only change, run as a sanity check). **Not re-run on the actual Pi** — this session has no
  SSH access to it.
- Notes/gotchas: this fixes the check going forward, but does **not** retroactively fix the
  reporting user's already-partial `~/chatterbox/assets/models/FastSpeech2/` — they need to either
  delete that directory and re-run `./scripts/setup_pi.sh` (now that the sentinel is stronger, a
  re-run will correctly detect the incomplete config/ and retry the whole folder download), or
  manually download the Drive folder per `README.md` and place `config/`/`preprocessed_data/`
  under `assets/models/FastSpeech2/` themselves. `fetch_and_unzip()` re-downloads the *entire*
  Drive folder on any missing sentinel (no incremental/partial fetch), so a retry re-pulls the
  large checkpoint too, not just the missing pieces — acceptable for a one-time setup step, not
  optimized further since download bandwidth wasn't the bottleneck this was fixing.

---

## 2026-07-21 — Refactor the Tkinter GUI: worker thread, Tk-free synth(), input dispatcher, settings

- What: per `chatterbox_gui_spec_v0.1.md` §9 (step 2 of `README_power_gui_workstream.md`'s build
  sequence, after chatterbox-powerd). Fixed the GUI freezing the whole window for every synthesis
  (it called `cli.syn_audio()` directly on the Tk thread, with no `try/except`):
  - Extracted the Tk-free compute path out of `cli.py:syn_audio()` into new `chatterbox/synth.py:
    synthesize()`; `cli.syn_audio()` (kept for CLI/benchmark, exact same signature/behavior) and
    the GUI's worker thread both call it now.
  - `chatterbox/gui/app.py`: synthesis+playback moved to a daemon worker thread
    (`on_speak()`/`_work()`/`_done()`/`_fail()`), guarded by a `busy` flag and `try/except` around
    both calls (exceptions now show an "error" UI state instead of reaching Tk's event loop). One
    `ui_queue`/`post()`/`_pump()` marshaling queue carries both worker results *and*
    powerd-forwarded switch input (unifying/replacing last session's bespoke
    `_power_event_queue`).
  - New `chatterbox/gui/input.py`: `Action` enum + dependency-injected `dispatch()` + a minimal
    `NavRing` — the Speak button, `<Return>`, and the on-screen keyboard route through it now;
    powerd-forwarded switch presses (`handle_power_input`'s old logging stub) are now fully wired
    to real actions.
  - New `chatterbox/gui/settings.py`: edits `chatterbox/config/user_prefs.yaml`'s power-timer/
    brightness fields, range-validated, atomic `.tmp`+`os.replace` write, `powerd.reload()` on
    save. Added `PowerdClient.send_reload()` (`chatterbox/power/client.py` had no reload method
    yet).
  - `cli.py`'s warm-up (previously a closure inside `main()`) is now module-level `cli.warmup()`
    so the GUI can call it too, on startup, through the same busy/worker machinery as real
    synthesis.
- Files: new `chatterbox/synth.py`, `chatterbox/gui/{input,settings}.py`, `docs/gui/GUI.md`,
  `tests/test_synth.py`, `tests/test_gui_{input,worker,settings}.py`; modified `chatterbox/cli.py`
  (shrunk a lot), `chatterbox/gui/{app,keyboards}.py`, `chatterbox/power/client.py`
  (+`send_reload`), `chatterbox/config/config_tts.yaml` (+`add_settings_button`), `CLAUDE.md`,
  `docs/context/ARCHITECTURE.md`.
- Why: the spec's own audit anchor — a hung/blocking GUI and an unguarded synthesis call are the
  two things standing between this demonstrator and being trustworthy for unattended/AAC use.
- Verify: `.venv/Scripts/python.exe -m pytest tests/` — 227 passed, 1 skipped (same platform-gated
  powerd IPC test as before). Unlike the powerd task, this checkout has real pretrained weights, so
  two manual real-weights checks were actually run (not just written) while building this — see
  `docs/gui/GUI.md` "Testing" for how to reproduce:
  1. `chatterbox.synth.synthesize()` called directly (no Tk) against loaded models — correct
     `AudioResult`, `playback.AUDIO_EXAMPLE` set, matching the pre-refactor pipeline's output shape.
  2. A scripted `create_gui()` run with a `window.after(50, tick)` counter running throughout a
     real `dispatch(Action.SPEAK)` (real synthesis + playback, 5.37s total): **138 ticks, max gap
     0.077s** — direct, quantitative proof the Tk thread never blocked during a real call. Window
     closed cleanly afterward, no crash.
- Notes/gotchas: found and fixed one real bug while writing `tests/test_gui_worker.py` — `except
  Exception as exc: post(lambda: _fail(exc))` referenced `exc` from inside a lambda queued for
  *later* execution, but Python implicitly `del`s an `except ... as name` binding at the end of the
  except block, so the lambda raised `NameError` once actually run via `post()`/drain. Fixed with a
  default-arg capture (`lambda exc=exc: _fail(exc)`) in both spots. Also deviated from the spec's
  own §2.2 pseudocode, which has a `finally: post(_done)` after the playback `try/except` — taken
  literally that re-queues `_done` right after `_fail` on the exception path, silently erasing the
  error state ~30ms after showing it; implemented as mutually-exclusive `_done`/`_fail` posting
  instead. Not verified on real Pi hardware (this is a PC dev checkout) or with a human physically
  dragging/resizing the window during synthesis, or with real physical switches (none configured in
  `user_prefs.yaml` yet) — see `docs/context/ARCHITECTURE.md` "Not yet implemented".

---

## 2026-07-21 — Implement chatterbox-powerd (kiosk power-state daemon)

- What: built the `chatterbox-powerd` daemon per `chatterbox-powerd_spec_v0.1.md` §9's build task
  — a new `chatterbox/power/` package (FSM, backlight, amp+watchdog, evdev/switch inputs, unix-
  socket IPC server+client, config loader, `daemon.py` entry point), wired into the existing
  pipeline at two points: `chatterbox/audio/playback.py`'s `play_audio()` now runs an amp-on→ack→
  settle+preroll→play→tail→amp-off handshake around the existing platform playback, and
  `chatterbox/gui/app.py` sends `activity`/`put_away` and receives forwarded switch presses (via a
  logging-stub `handle_power_input()` — the real dispatcher is a separately specced, not-yet-
  written component). Both integration points go through one shared `chatterbox.power.client`
  singleton that degrades to a permanent silent no-op if powerd isn't reachable.
  Also added: `deploy/systemd/{chatterbox-powerd,chatterbox-gui}.service`, a `scripts/setup_pi.sh`
  install step (units + socket group, non-fatal if it fails), an `INSTALL.md` section, and
  `docs/power/POWERD.md` (run/configure/test).
- Files: new `chatterbox/power/{__init__,config,fsm,backlight,amp,inputs,ipc,client,daemon}.py`,
  `chatterbox/config/user_prefs.yaml`, `deploy/systemd/*.service`, `docs/power/POWERD.md`,
  `tests/test_power_{fsm,config,backlight,amp,ipc}.py`; modified `chatterbox/config/paths.py`
  (+`USER_PREFS_PATH`), `chatterbox/audio/playback.py`, `chatterbox/gui/app.py`,
  `chatterbox/config/config_tts.yaml` (+`add_put_away_button`), `requirements-pi.txt`
  (+gpiozero/lgpio/evdev), `scripts/setup_pi.sh`, `INSTALL.md`, `CLAUDE.md`,
  `docs/context/ARCHITECTURE.md`.
- Why: `chatterbox-powerd_spec_v0.1.md` — an unattended AAC kiosk needs the display/amp to sleep
  and the amp to never be left silently drawing power, without adding failure modes to the TTS
  pipeline itself.
- Verify: `.venv/Scripts/python.exe -m pytest tests/` — 193 passed, 1 skipped (the one live unix-
  socket test in `test_power_ipc.py`, `skipif`'d on Windows). Manually confirmed on this Windows
  checkout: all `chatterbox.power.*` submodules import cleanly with no `gpiozero`/`evdev`
  installed and degrade to logged no-ops (`amp.Amp._device is None`,
  `backlight.Backlight.node is None`); `PowerdClient.request_amp()` returns `False` in ~15 ms (not
  a blocking hang) when powerd isn't running; `playback.play_audio()` end-to-end with a synthetic
  clip completes with no exception and no added latency versus before this change.
- Notes/gotchas: **nothing here has been run on real Pi 5 hardware** — GPIO/backlight/evdev/
  systemd/halt behavior (spec §5/§8/§10) is implemented per spec but entirely unverified; that
  needs the spec's own §10 test pass on actual hardware (see `docs/context/ARCHITECTURE.md` "Not
  yet implemented"). Deliberate deviations from the spec's literal text, all flagged in code
  comments where they land: no real `chatterbox-powerd` console script (this repo has no
  packaging, so it's `python -m chatterbox.power.daemon`, matching the spec's own systemd
  `ExecStart`); both systemd units' `ExecStart` was changed from the spec's `/usr/bin/python3` to
  the venv `scripts/setup_pi.sh` actually creates (`~/chatterbox/venv/bin/python3`) — the bare
  system interpreter has none of `requirements-pi.txt` installed; the spec's prose "settle 80ms +
  silence pre-roll"/"tail" are implemented as configurable sleeps
  (`amp.settle_ms`/`preroll_ms`/`tail_ms` in `user_prefs.yaml`, not in the spec's original YAML
  schema) rather than literal silence-audio injection; EEPROM/`config.txt` changes are documented
  in `INSTALL.md` only, never auto-applied (boot-config edits carry a brick-on-mistake risk this
  repo's tooling avoids elsewhere too); the client does not auto-reconnect after a connection
  drop (v0.1 scope — restart the GUI/CLI process). The companion `GUI_Power_Controller_Architecture`
  doc and the switch-press→GUI-action input dispatcher this spec references are not part of this
  session — `handle_power_input()` in `chatterbox/gui/app.py` is a logging stub for that boundary.

---

## 2026-07-20 — Fix silent --gui override by --benchmark/--p4-sweep, found via Part A verification

- What: running `docs/REORG_VERIFICATION.md`'s Part A, the user combined `--gui --benchmark
  --export-xlsx` into one command (rather than the separate commands the protocol actually lists)
  and got the benchmark, not the GUI, with zero indication `--gui` had been ignored. Root cause:
  `chatterbox/cli.py`'s mode dispatch is an `if args.benchmark: ... elif args.p4_sweep: ... elif
  args.gui: ...` chain — pre-existing behavior, unchanged from the original pre-reorg `do_tts.py`,
  not a reorg regression — but silent, so nothing told the user which mode actually ran.
  - Added an explicit stderr warning, printed before dispatch, whenever `--gui` is combined with
    `--benchmark` or `--p4-sweep`: `[do_tts] --gui has no effect together with --benchmark --
    running --benchmark instead. Launch the interface on its own with \`do_tts.py --gui\`.`
    Behavior (which mode wins) is unchanged; only the silence is fixed.
  - Updated `--gui`'s `--help` text to document the precedence.
  - Added a note to `docs/REORG_VERIFICATION.md` clarifying `--gui`/`--benchmark`/`--p4-sweep` are
    mutually exclusive top-level modes, not composable flags — run each protocol step as its own
    separate command.
- Files: `chatterbox/cli.py`, `docs/REORG_VERIFICATION.md`.
- Why: confusing, silent flag-precedence behavior that real testing (the exact purpose of Part A)
  surfaced immediately — worth fixing even though it predates the reorg, since the reorg's own
  verification protocol is what prompted testing this combination in the first place.
- Verify: `pytest tests/` — 130 passed (no test covers CLI argument dispatch directly). Manually
  reproduced the user's exact command (`do_tts.py --gui --benchmark --repeats 1`) — the new
  warning now prints first, before any model loading, then the benchmark runs exactly as before.
- Notes/gotchas: this is a UX fix (visibility), not a behavior change — `--benchmark` still wins
  over `--gui` when both are given, matching the pre-existing, pre-reorg precedence order
  (`--benchmark` > `--p4-sweep` > `--gui` > free-text). If that precedence itself is ever felt to
  be wrong (e.g. `--gui` should instead error out, or the flags should be an argparse
  mutually-exclusive group), that's a separate, larger decision — not made here.

---

## 2026-07-20 — Reorg §4 sign-off: delete graphify-out/ and the two deprecated requirements files

- What: `docs/REORG_PROPOSAL.md` §4 flagged four items for an explicit keep/delete decision rather
  than deciding unilaterally (Phase 4 CHANGELOG entry below); this session brought them back and
  got answers:
  - `git rm -r graphify-out/` (this AI-assistant tool's own knowledge-graph cache, a build
    artifact, not project source) and added `graphify-out/` to `.gitignore` so it doesn't return.
  - `git rm requirements.txt minimal_requirements.txt` — both fully superseded by
    `requirements-dev.txt`/`requirements-pi.txt`, kept "for reference" only, now deleted per
    explicit sign-off. Updated every doc that referenced them as present files: `CLAUDE.md`'s
    "Install gotchas", `INSTALL.md`'s "Why not the old requirements.txt?" section,
    `requirements-dev.txt`'s own header comment (also fixed stale `Waveglow/`/`FastSpeech2/` paths
    in that comment to `assets/models/Waveglow/`/`assets/models/FastSpeech2/`, missed during
    Phase 1 since it's a comment, not a functional import), and `README.md`'s French install
    instructions, which were pointing at the now-deleted `requirements.txt` (a real, user-facing
    break, not just a stale comment).
  - The `profile/` experiment directories (17 MB, tracked only because of a shallow `.gitignore`
    rule): decision was to move them to a separate data/results repo, but **that migration is
    flagged as follow-up work, not executed in this pass** — extracting history and re-pointing
    anything that reads these paths deserves its own deliberate session, not a drive-by move
    bundled into this cleanup.
  - Also fixed a second stale `.gitignore` entry found while touching this file:
    `profiling/__pycache__/` (from before Phase 2 moved `profiling/` to
    `tools/monitoring/profiling/`) → `tools/monitoring/profiling/__pycache__/`.
- Files: `.gitignore`, `CLAUDE.md`, `INSTALL.md`, `README.md`, `requirements-dev.txt`,
  `docs/REORG_PROPOSAL.md`; deleted `graphify-out/` (entire tree), `requirements.txt`,
  `minimal_requirements.txt`.
- Why: closing out `docs/REORG_PROPOSAL.md` §4's three explicitly-deferred sign-off items, the
  last open piece of the reorg plan.
- Verify: `pytest tests/` — 130 passed (none of these files were imported by code, so this was
  never expected to affect tests — confirmed anyway).
- Notes/gotchas: the `profile/` experiment-directory migration is a real, tracked follow-up, not
  forgotten — see `docs/REORG_PROPOSAL.md` §4's table for the exact decision and reasoning. If you
  ever need the deleted `requirements.txt`'s training-environment pins, they're recoverable from
  git history (any commit before this one).

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
