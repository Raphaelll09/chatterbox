#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config-driven backend registry.

config_tts.yaml's `load_script`/`syn_script`/`gui_script` string values are still resolved via
getattr(), exactly as before Phase 3 -- the only change is what they're resolved *against*: a
Synthesizer/VocoderBackend instance instead of the flat `loading_modules` module. See
docs/REORG_PROPOSAL.md Sec5.

Only one backend exists today. A second backend (e.g. Matcha-TTS, see
docs/REORG_PROPOSAL.md Sec5 "How Matcha-TTS would slot in") would add its own module here and its
own config_tts.yaml `tts_models` entry pointing at it -- nothing else in the CLI/GUI/benchmark
layer would need to change, since they already dispatch by config string, not by hardcoded name.
"""
from chatterbox.synthesis.backends.fastspeech2_hifigan.backend import FastSpeech2HifiGanBackend

# Singleton: models are swapped from disk files, never held resident as multiple simultaneous
# instances (see docs/context/ARCHITECTURE.md "Synthesis pipeline") -- one shared instance mirrors
# that, and is what every load_script/syn_script/gui_script getattr() call resolves against.
BACKEND = FastSpeech2HifiGanBackend()
