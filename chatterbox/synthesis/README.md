# `chatterbox/synthesis/` — the synthesis layer and its backend contract

This package turns text into a finished `.wav` on disk. It owns the **backend contract**: the set of
rules a TTS engine must satisfy to be selectable from `config_tts.yaml` and driven by the GUI and
the CLI without either of them knowing which engine is running.

Two backends implement it today:

| Backend | Directory | Shape | Vocoder? |
|---|---|---|---|
| FastSpeech 2 + HiFi-GAN | `backends/fastspeech2_hifigan/` | two-stage (text → mel → wav) | yes |
| Piper | `backends/piper/` | monolithic (text → wav) | no |

## Layout

| Path | What it is |
|---|---|
| `registry.py` | Backend registration and name dispatch. `BACKEND` is the proxy every caller resolves against. |
| `audio_postprocess.py` | Peak normalisation + soft limiter + the `--analyze` crest/loudness report. Backend-agnostic. |
| `subtitles.py` | `.vtt` subtitle and duration-alignment writers. Only runs for a backend declaring `supports_subtitles: true`. |
| `backends/fastspeech2_hifigan/` | The FS2 backend, its FS2-specific text pipeline, and its regex rule CSVs. |
| `backends/piper/` | The Piper backend and its own (deliberately separate) text front-end. |

---

## The backend contract

> **This contract is convention, not interface.** There is no ABC and no runtime validation. A
> backend that gets a detail wrong fails at synthesis time, usually with `AttributeError` or
> `FileNotFoundError`, not at load time.
>
> An earlier `base.py` declared `Synthesizer`/`VocoderBackend` ABCs and `SynthesisRequest`/
> `SynthesisResult` dataclasses. **Nothing ever subclassed, imported or constructed them** — neither
> backend inherited from them, and `chatterbox/synth.py` never saw a `SynthesisResult`. The file was
> aspirational documentation that had drifted from the code it claimed to describe, so it was
> deleted in the release reorganisation (`docs/release/REORG_PLAN.md`) and replaced by this
> document, which describes what the code actually requires. If you reintroduce an ABC, make the
> backends inherit from it — a contract nothing implements is worse than none.

### 1. Registration

`registry.py` holds a hardcoded table:

```python
_BACKENDS_BY_NAME = {
    "fastspeech2_hifigan": FastSpeech2HifiGanBackend(),
    "piper": PiperBackend(),
}
```

Adding a backend means editing this table. One shared instance per backend class: models are
swapped from disk, never held resident as several simultaneous instances.

A `tts_models[i]` entry selects its backend with `backend: "<name>"`. Omitting the key defaults to
`"fastspeech2_hifigan"`, which is what every entry predating the Piper integration relies on.

### 2. Name dispatch, and its sharp edge

`config_tts.yaml` names methods as strings (`load_script`, `syn_script`, `gui_script`), resolved with
`getattr(registry.BACKEND, name)`. `BACKEND` is a `_BackendProxy` with two-tier lookup:

1. the **currently activated** TTS backend (set by `activate_tts_backend(name)`, which callers invoke
   immediately before resolving a model entry's `load_script`);
2. failing that, a **linear scan** over every registered backend, first match wins.

Tier 1 exists because `tts()` and `describe_controls()` are defined identically on every backend by
design — a bare `getattr` could not tell which one a caller meant once a second backend existed.

> ⚠ **Tier 2 silently mis-dispatches.** If a name is missing from the active backend but present on
> another, the proxy returns the *other* backend's method with no warning. `_BACKENDS_BY_NAME`
> insertion order decides the winner. Unique names (`load_fastspeech2`, `load_piper`, `load_hifigan`)
> are safe by construction; shared helper names are not.

### 3. What a TTS backend must provide

**`load_<something>(model_config, device)`** — named by the entry's `load_script`.
`model_config` is the `tts_models[i]` dict; `device` is a `torch.device` (a backend that does not use
torch accepts and ignores it). Should leave the instance ready to synthesise, warm-up included.

**`tts(text_to_syn, tts_config, gui_control, linking_utt)`** → **`(output_dir, processed_text)`**

This tuple is the load-bearing part of the contract:

- `output_dir` **must be the output *directory***, not a file path or a path prefix.
  `chatterbox/synth.py` appends the filename itself (`os.path.join(output_dir, "audio_file")`, then
  `".wav"`). Returning a prefix double-joins and yields a nonexistent path — this was a real crash
  on hardware during the Piper integration, not a hypothetical.
- `processed_text` is the text after the backend's own cleanup, used for subtitles and console
  output.
- `gui_control` is the dict `chatterbox/gui/app.py` collected from `describe_controls()`, keyed by each
  control's `"key"`. May be `None`.
- `linking_utt` is `True` for the second and later parts of a `|`-separated multi-utterance input.

**`describe_controls()`** → dict, called once per load, on the loaded instance. Drives the GUI's
model-options panel generically. All keys optional:

```python
{
  "speaker_list":    {name: id, ...},   # or omitted for a single-voice backend
  "default_speaker": <id>,
  "controls": [                          # ordered; one widget rendered per entry
    {"type": "chip_grid", "key": ..., "label_key": ..., "options": [...],
     "default": ..., "hidden_pattern": <regex>, "icons": {opt: glyph}},
    {"type": "slider",    "key": ..., "label_key": ...,
     "min": ..., "max": ..., "resolution": ..., "default": ..., "advanced": bool},
    {"type": "text",      "key": ..., "label_key": ...},
  ],
}
```

`label_key` indexes `chatterbox/gui/i18n.py`. **Always set `resolution` on a slider** — the generic
builder defaults to `1`, which on a 0.5–2.0 range leaves only two selectable values (a real
user-reported bug).

### 4. What a vocoder backend must provide

Only for a two-stage backend (`needs_vocoder: true`):

- **`load_<something>(vocoder_config, device)`** — named by the `vocoder_models[i]` `load_script`.
- **`vocoder(location_mel_file, vocoder_config)`** → the produced wav's base path, no `.wav` suffix.

### 5. Output file conventions

`chatterbox/synth.py` reads these by fixed name from `output_dir`:

| File | Written by | Required? |
|---|---|---|
| `audio_file.wav` | monolithic backend's `tts()`, or the vocoder | **always** |
| `audio_file_duration.npy` | acoustic model | only if `supports_subtitles: true` |
| `audio_file.AU` | acoustic model | optional (visual/facial animation; skipped if absent) |
| `audio_file.WAVEGLOW` | acoustic model | only for the `\|` multi-utterance path (see §7) |
| `audio_file_styleTag_gst_weight.mat` | acoustic model | optional (GST weights for the GUI) |

`audio_file.WAVEGLOW` is a **mel container format name**, not a reference to the Waveglow vocoder
(removed in the release reorganisation).

### 6. Capability flags — declared in YAML, not by the backend

Three static flags live on each `tts_models[i]` entry. They are read **before the model is loaded**,
which is why they are config rather than `describe_controls()` output.

| Flag | Default | Effect when false |
|---|---|---|
| `needs_vocoder` | `true` | No vocoder is loaded or called; the GUI hides the Vocodeur picker. |
| `supports_subtitles` | `true` | The subtitle/duration-alignment write is skipped. |
| `accepts_phoneme_input` | `true` | The GUI applies `GUI_config.phoneme_fallback` (`translate_labels` / `hide` / `disable`) to the Phonèmes keyboard. |

> ⚠ **A backend cannot declare its own capabilities.** These are user-editable YAML. Setting one
> wrongly — `supports_subtitles: true` on a backend that writes no `.npy` — crashes at synthesis
> time. Nothing validates them.

### 7. Known gaps

- **`|` multi-utterance input is FastSpeech 2-only.** That branch in `chatterbox/synth.py`
  concatenates mel and `.AU` data in FS2's binary format *unconditionally* — it is gated by neither
  `needs_vocoder` nor `supports_subtitles`. A Piper user typing `|` gets `FileNotFoundError`.
- **`syn_script` is FS2-internal.** `FastSpeech2HifiGanBackend.tts()` self-dispatches on it.
  `PiperBackend.tts()` ignores it entirely; its entries' `syn_script: "syn_piper"` names a method
  that does not exist and would raise if anything resolved it.
- **`gui_script` does not go through the registry.** `chatterbox/gui/app.py` resolves it against its *own*
  module globals (`globals()[...]`), so a backend cannot ship its own GUI function.
- **The phoneme keyboard is FS2-specific.** `chatterbox/gui/keyboards.py`'s phone-symbol alphabet and mood
  shortcuts belong to the FS2 checkpoint. There is no G2P step anywhere in this repository.

---

## Adding a backend: checklist

1. Create `backends/<name>/backend.py` with a class providing `load_*()`, `tts()` and
   `describe_controls()`.
2. Register it in `registry.py`'s `_BACKENDS_BY_NAME`.
3. Add a `tts_models` entry to `chatterbox/config/config_tts.yaml` with `backend:`, `load_script:`,
   `folder:`, `output_location:`, and the three capability flags set **honestly**.
4. Write `audio_file.wav` into the directory your `tts()` returns.
5. Add a `README.md` in your backend directory recording provenance, licence and any checkpoint
   hashes — see `backends/piper/README.md`.
6. Verify on real hardware. The unit tests mock the backend and will not catch a contract violation.
