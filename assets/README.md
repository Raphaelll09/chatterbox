# `assets/` — vendored model code and runtime audio

Third-party model source and the audio the interface itself plays. **No trained weights are in git.**

## `models/`

Vendored upstream repositories, kept in-tree because the pipeline imports them directly
(`chatterbox/config/paths.py` puts them on `sys.path`).

| Directory | Upstream | Licence | Role |
|---|---|---|---|
| `FastSpeech2/` | ming024/FastSpeech2, with a GST/StyleTag fork | **MIT** (© 2020 Chung-Ming Chien) | Acoustic model: text → mel + `.AU` |
| `hifi-gan-master/` | jik876/hifi-gan | **MIT** (© 2020 Jungil Kong) | Vocoder: mel → waveform |
| `flaubert/` | FlauBERT | see upstream | Optional free-text style conditioning |
| `Piper/` | not vendored | — | Voice `.onnx` files land here; fetched, never committed |

Waveglow was removed in the release reorganisation: its vocoder entry had been commented out of
`config_tts.yaml` for a long time, making it unreachable, while a module-level import kept the
vendored tree load-bearing anyway.

### Weights are downloads, not commits

None of the following is tracked. A fresh clone needs them before it can speak:

| What | Where it goes | How |
|---|---|---|
| FastSpeech 2 `config/`, `output/`, `preprocessed_data/` (checkpoint `390000`) | `models/FastSpeech2/` | Google Drive link in `README.fr.md` |
| HiFi-GAN `FR_V2/` (`g_00570000` + config) | `models/hifi-gan-master/` | Google Drive link in `README.fr.md` |
| FlauBERT large cased | `models/flaubert/flaubert_large_cased/` | Google Drive link in `README.fr.md` |
| Piper voices (3 `.onnx` + `.json`) | `models/Piper/` | `./scripts/fetch_piper_voices.sh` — verifies sha256 |

`scripts/setup_pi.sh` automates this on a fresh Pi 5.

> ⚠ **Redistribution status of the trained weights is unresolved.** The FastSpeech 2 French
> checkpoint and the fine-tuned HiFi-GAN weights are distributed via personal Google Drive links
> with no stated licence, corpus attribution or speaker-consent statement. This is an open release
> blocker — see `docs/release/STRUCTURE_AUDIT.md` §9.4. Do not assume they are redistributable.

## `audio/prompts/Emmanuelle/`

29 `.wav` files, one per phoneme key on the on-screen Emmanuelle keyboard. **Loaded at runtime**
(via `paths.AUDIO_KEYBOARDS_DIR`) when key audio preview is enabled.

Their licence and the speaker's consent to publication are likewise unresolved.

Reference recordings used for audio analysis are *not* here — they are not needed at runtime and
live in `docs/research/reference-audio/`.
