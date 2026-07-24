# Piper backend (fr_FR + en_US)

## Software

`piper-tts==1.5.0` — the [OHF-voice/piper1-gpl](http://github.com/OHF-voice/piper1-gpl) fork
(Home Assistant Authors), licensed **GPL-3.0-or-later**. The original MIT-licensed
`rhasspy/piper` repository is archived; this fork is the actively maintained successor. Not
vendored into this repo — install separately (`pip install piper-tts==1.5.0`, see `INSTALL.md`)
so this project's own licensing stays unaffected; a user who doesn't want a GPL dependency simply
never installs it, and every other backend keeps working.

Confirmed live on a Raspberry Pi 5 during this integration's Phase A/B (see
`docs/context/CHANGELOG.md`): installs from a single prebuilt aarch64 wheel
(`manylinux_2_17_aarch64...`), no source build, no separate `piper-phonemize`/`espeakng-loader`
dependency — 1.5.0 bundles its own compiled `espeakbridge.so` + `espeak-ng-data` directly in the
wheel, independent of any system-installed `espeak-ng`.

## Voices

All downloaded from the [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)
HuggingFace dataset (`<lang>/<lang_region>/<voice>/medium/` -- the locale path segment differs per
voice, e.g. `fr/fr_FR` vs `en/en_US`), CC0/public-domain-adjacent per that dataset's own licensing
-- see the dataset page for the authoritative statement per voice. Fetch with
`./scripts/fetch_piper_voices.sh` from the repo root (verifies sha256 against the values below,
captured from a real download during this integration -- fr_FR during Phase B, en_US when the
English voice/live language switch were added, docs/context/CHANGELOG.md for both).

Sample rate: **22050 Hz** for all three (the `medium` quality tier) — matches the existing
FastSpeech2+HiFi-GAN output exactly, so the shared playback/denoise/postprocess path in
`chatterbox/synth.py` needs no resampling step regardless of which backend produced the audio.

| Voice | Language | Speakers | `.onnx` sha256 | `.onnx.json` sha256 |
|---|---|---|---|---|
| `fr_FR-siwis-medium` | fr_FR | 1 (default) | `641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99` | `39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959` |
| `fr_FR-upmc-medium` | fr_FR | 2 (`jessica`, `pierre`) | `9abb3800c199148897a9ed64e100d224f3de83579f100044174ad19418f1786f` | `e8636ec15dfd5d72db37a02cb5320a20f2b8d339f2a0e4337da64c58a33a5868` |
| `en_US-lessac-medium` | en_US | 1 (default) | `5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f` | `efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0` |

`fr_FR-tom-medium` was evaluated alongside the two fr_FR voices and removed (`docs/context/
CHANGELOG.md`): real-hardware listening found it noticeably lower quality and slower to
synthesize than either remaining fr_FR voice, with no offsetting benefit. `scripts/
fetch_piper_voices.sh` no longer fetches it.

`fr_FR-upmc-medium`'s 2 speakers (`jessica`: id 0, `pierre`: id 1, confirmed live via
`PiperVoice.config.speaker_id_map`) surface as `describe_controls()`'s `speaker_list`, giving it a
speaker dropdown in the GUI — `siwis`/`lessac` are single-speaker and omit that control entirely,
per `base.py`'s documented default for a one-voice backend.

`en_US-lessac-medium` is `config_tts.yaml`'s first non-`"fr"` `tts_models` entry (`language: "en"`)
-- selecting English from the GUI's "Langue" menu (`chatterbox/gui/app.py`'s `create_gui()`)
switches onto it, since it's the first entry whose `language` field matches `"en"`. No backend
code changes were needed for this voice -- `PiperBackend`/`text_frontend.py` are already voice-
and (in practice) language-agnostic: `apply_custom_regex_rules` already defaults to `false`
(French-specific regex data never touches this voice), and `trim_punctuation_mistakes()` is
generic whitespace/punctuation cleanup, not French-keyed.

## Contract notes specific to this backend

See the Phase B plan (`docs/context/CHANGELOG.md`, and `docs/gui/INTERCHANGEABLE_BACKENDS.md` for
the contract-gap writeup) for the full detail. In short:

- Monolithic (`needs_vocoder: false`) — `tts()` writes a finished `audio_file.wav` directly to
  `<folder>/<output_location>/`, no separate mel/vocoder stage.
- No style dimension — `describe_controls()` declares no `"style"` control, which is also what
  keeps `gui/app.py`'s `gst_token_selection` compat global at `None` while Piper is active (the
  Emmanuelle keyboard's mood-shortcut keys correctly no-op instead of touching a style control
  that doesn't exist here).
- `accepts_phoneme_input: false` — the Emmanuelle keyboard's phone-code syntax is FastSpeech2-
  checkpoint-specific; Piper's own phonemizer (internal, espeak-ng-based) doesn't understand it.
- Text preprocessing is Piper's own (`text_frontend.py`), not routed through
  `text_pipeline.py`'s FS2-specific machinery beyond the two genuinely orthographic, backend-
  agnostic helpers (`parse_pronunciation_mistakes`/`trim_punctuation_mistakes`).
