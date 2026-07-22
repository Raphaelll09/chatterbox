#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Synthesizer / VocoderBackend abstractions.

See docs/REORG_PROPOSAL.md Sec5 for the original sketch and Sec7/Phase 3 for why this file has two
ABCs instead of the single "Synthesizer.load()" originally sketched: config_tts.yaml's
`tts_models`/`vocoder_models` are two independently selectable lists today (the GUI has separate
TTS and Vocoder buttons, and `do_tts.py --default_tts`/`--default_vocoder` pick each independently)
-- an acoustic-model swap and a vocoder swap are two different operations in practice, not one. A
single bundled `Synthesizer` covering both would either force them to always change together
(breaking that today's a real, working feature) or need its own internal sub-dispatch, which is
just this split moved one level down. Splitting them here matches the system's actual shape.

A single concrete class can't cleanly subclass *both* ABCs below: Synthesizer.load() and
VocoderBackend.load() take different config shapes (a tts_models entry vs. a vocoder_models entry)
and Python doesn't let one class implement two same-named abstract methods differently. These ABCs
are the target shape a *new, from-scratch* backend (e.g. Matcha-TTS) should implement directly.
chatterbox/synthesis/backends/fastspeech2_hifigan/backend.py is a *converted* backend, not a
from-scratch one -- it keeps its existing method names (load_fastspeech2, load_hifigan,
load_waveglow, tts, vocoder, ...) so config_tts.yaml's load_script/syn_script string dispatch needs
zero changes, and conforms to this same contract in spirit (documented per-method) rather than via
literal Python inheritance.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SynthesisRequest:
    text: str
    speaker: Optional[str] = None
    style: Optional[str] = None
    style_intensity: float = 1.0
    style_tag: Optional[str] = None
    control_bias: dict = field(default_factory=dict)
    linking_utt: bool = False


@dataclass
class SynthesisResult:
    mel_path: Optional[str]
    au_path: Optional[str]  # facial/visual animation params -- optional per backend (Matcha-TTS
                             # won't produce one; see docs/REORG_PROPOSAL.md Sec5)
    sample_rate: Optional[int] = None
    # A monolithic/end-to-end backend (text -> wav directly, no separate vocoder stage) fills this
    # in and leaves mel_path=None; a two-stage backend (this repo's FastSpeech2+HiFi-GAN) fills
    # mel_path and leaves this None. chatterbox/synth.py's synthesize() branches on which one is
    # set to decide whether to call VocoderBackend.vocode() at all -- see its module docstring.
    wav_path: Optional[str] = None


class Synthesizer(ABC):
    """One instance == one loaded acoustic-model (text -> mel) backend."""

    @abstractmethod
    def load(self, model_config: dict, device: Any) -> None:
        ...

    @abstractmethod
    def synthesize(self, request: SynthesisRequest, model_config: dict) -> SynthesisResult:
        ...

    def describe_controls(self) -> dict:
        """GUI renders its model-options panel off this instead of special-casing the backend by
        name (kills gui_utils.py's gui_fastspeech2()-style branching and its config-reopening leak
        -- see docs/REORG_PROPOSAL.md Sec5). Called once per load, on the loaded instance (so
        `speaker_list` etc. can depend on which checkpoint is actually loaded) --  for capability
        flags a caller needs *before* loading a model (whether it needs a separate vocoder, or
        understands phoneme input), see the static per-`tts_models` entry YAML flags
        (`needs_vocoder`/`accepts_phoneme_input` in config_tts.yaml) instead.

        Return shape (all keys optional, default: no extra controls beyond a bare "Synthèse"
        button):
            {
                "speaker_list": [str, ...],   # None/omitted if this backend has only one voice
                "default_speaker": int,       # index into speaker_list pre-selected in the GUI;
                                               # omitted/ignored when speaker_list is empty
                "controls": [                 # ordered list of control descriptors; gui/app.py's
                                               # gui_generic_controls() renders one widget per
                                               # entry, in order, and collects values into a dict
                                               # keyed by "key" (get_gui_controls()'s return value)
                    {
                        "type": "chip_grid" | "slider" | "text",
                        "key": str,            # dict key the collected value is stored under
                        "label_key": str,      # chatterbox.gui.i18n key for the widget's label
                        # chip_grid only:
                        "options": [str, ...], # displayed in stable order, default option first
                        "default": <value>,    # for chip_grid/slider: the option/value pre-selected
                        "hidden_pattern": <regex str, optional>,  # options matching this start
                                                # hidden behind an "advanced" toggle (chip_grid only)
                        # slider only:
                        "min": float, "max": float,
                        "advanced": bool,       # optional; groups this control behind an
                                                # "advanced"-style show/hide toggle, same idea as
                                                # hidden_pattern but for sliders/any control type
                    },
                    ...
                ],
            }
        Default: no extra controls."""
        return {}


class VocoderBackend(ABC):
    """One instance == one loaded vocoder (mel -> wav) backend. Swapped independently of the
    acoustic model -- see the module docstring above."""

    @abstractmethod
    def load(self, vocoder_config: dict, device: Any) -> None:
        ...

    @abstractmethod
    def vocode(self, result: SynthesisResult, vocoder_config: dict) -> str:
        """Returns the base path of the produced wav (no .wav suffix), matching the
        existing syn_hifigan()/syn_waveglow() return convention."""
        ...
