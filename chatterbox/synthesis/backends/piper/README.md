# Piper (fr_FR) backend

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

Both downloaded from the [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)
HuggingFace dataset (`fr/fr_FR/<voice>/medium/`), CC0/public-domain-adjacent per that dataset's own
licensing — see the dataset page for the authoritative statement per voice. Fetch with
`./scripts/fetch_piper_voices.sh` from the repo root (verifies sha256 against the values below,
captured from a real download during this integration).

Sample rate: **22050 Hz** for both (the `medium` quality tier) — matches the existing
FastSpeech2+HiFi-GAN output exactly, so the shared playback/denoise/postprocess path in
`chatterbox/synth.py` needs no resampling step regardless of which backend produced the audio.

| Voice | Speakers | `.onnx` sha256 | `.onnx.json` sha256 |
|---|---|---|---|
| `fr_FR-siwis-medium` | 1 (default) | `641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99` | `39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959` |
| `fr_FR-upmc-medium` | 2 (`jessica`, `pierre`) | `9abb3800c199148897a9ed64e100d224f3de83579f100044174ad19418f1786f` | `e8636ec15dfd5d72db37a02cb5320a20f2b8d339f2a0e4337da64c58a33a5868` |

`fr_FR-tom-medium` was evaluated alongside these two and removed (`docs/context/CHANGELOG.md`):
real-hardware listening found it noticeably lower quality and slower to synthesize than either
remaining voice, with no offsetting benefit. `scripts/fetch_piper_voices.sh` no longer fetches it.

`fr_FR-upmc-medium`'s 2 speakers (`jessica`: id 0, `pierre`: id 1, confirmed live via
`PiperVoice.config.speaker_id_map`) surface as `describe_controls()`'s `speaker_list`, giving it a
speaker dropdown in the GUI — `siwis` is single-speaker and omits that control entirely, per
`base.py`'s documented default for a one-voice backend.

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
