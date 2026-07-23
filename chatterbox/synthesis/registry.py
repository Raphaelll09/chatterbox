#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config-driven backend registry.

config_tts.yaml's `load_script`/`syn_script`/`gui_script` string values are still resolved via
getattr(), exactly as before Phase 3 -- the only change is what they're resolved *against*: a
Synthesizer/VocoderBackend instance instead of the flat `loading_modules` module. See
docs/REORG_PROPOSAL.md Sec5.

Two backends exist as of the Piper integration (docs/context/CHANGELOG.md, Phase B): FastSpeech2+
HiFi-GAN and Piper. `BACKEND` used to be a bare singleton instance -- fine for one backend, but
`tts()`/`describe_controls()` are defined identically-named on *every* backend (that's the whole
point of the shared contract), so a plain `getattr(BACKEND, name)` can no longer tell which
backend's `tts()` a caller means once two are registered. `_BackendProxy` below resolves colliding
names against whichever TTS backend was most recently activated (via `activate_tts_backend()`,
called explicitly by cli.py/gui/app.py at the same 3 places they already resolve `load_script` --
see those call sites), and falls back to a plain name search across every registered backend for
uniquely-named methods (`load_script`/`syn_script` strings, e.g. "load_piper" vs
"load_fastspeech2", which never collide by construction and must resolve even before any backend
has been activated yet).

Vocoder resolution (`vocoder()`, `load_hifigan`) needs no such activation step: only
FastSpeech2HifiGanBackend defines a vocoder today (Piper is monolithic, needs_vocoder: false), so
those names are unique and always resolve via the fallback path regardless of which TTS backend is
currently active.
"""
from chatterbox.synthesis.backends.fastspeech2_hifigan.backend import FastSpeech2HifiGanBackend
from chatterbox.synthesis.backends.piper.backend import PiperBackend

# Models are swapped from disk files, never held resident as multiple simultaneous instances (see
# docs/context/ARCHITECTURE.md "Synthesis pipeline") -- one shared instance per backend class
# mirrors that.
_BACKENDS_BY_NAME = {
    "fastspeech2_hifigan": FastSpeech2HifiGanBackend(),
    "piper": PiperBackend(),
}

# Which TTS backend colliding entry points (tts/describe_controls) currently resolve against.
# Defaults to fastspeech2_hifigan, matching every tts_models[i] entry that doesn't declare its own
# "backend" key (i.e. every entry that existed before this field was introduced).
_active_tts_backend = _BACKENDS_BY_NAME["fastspeech2_hifigan"]


def activate_tts_backend(name):
    """Called by cli.py/gui/app.py immediately before resolving a tts_models[i] entry's
    load_script, with tts_model.get("backend", "fastspeech2_hifigan") -- see those call sites."""
    global _active_tts_backend
    _active_tts_backend = _BACKENDS_BY_NAME[name]


class _BackendProxy:
    def __getattr__(self, name):
        if hasattr(_active_tts_backend, name):
            return getattr(_active_tts_backend, name)
        for backend in _BACKENDS_BY_NAME.values():
            if hasattr(backend, name):
                return getattr(backend, name)
        raise AttributeError(name)


# Every load_script/syn_script/gui_script/tts/vocoder/describe_controls getattr() call resolves
# against this proxy -- see its class docstring above for the two-tier dispatch rule.
BACKEND = _BackendProxy()
