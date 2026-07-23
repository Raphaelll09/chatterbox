#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piper (fr_FR) backend -- piper-tts==1.5.0 (OHF-voice/piper1-gpl, GPL-3.0-or-later), pinned and
verified live on the Pi 5 during Phase A/B of this integration (docs/context/CHANGELOG.md). A
monolithic text->wav backend (needs_vocoder: false in config_tts.yaml) -- no separate mel/vocoder
stage, no FlauBERT, phonemization is internal to piper-tts (bundled espeakbridge.so +
espeak-ng-data, confirmed NOT a separate piper-phonemize/espeakng-loader dependency).

`piper` is imported lazily inside load_piper(), not at module level (same guarded pattern as
chatterbox/power/{amp,battery,inputs}.py's gpiozero/smbus2/evdev imports) -- piper-tts is an
optional, separately-installed backend (see INSTALL.md), not a hard requirements-pi.txt entry, so
this module (and chatterbox/synthesis/registry.py, which imports PiperBackend unconditionally at
module level to register it) must still import cleanly on a checkout that never installed it.
Unlike the power daemon's hardware imports, a missing piper-tts is not silently degraded to a
no-op here -- selecting a Piper tts_models[i] entry without it installed is a real
misconfiguration, not an optional-hardware-absent case, so load_piper() raises loudly instead.
"""
import logging
import os
import wave

import tools.monitoring.profiling as profiling
from chatterbox.synthesis.backends.piper import text_frontend

logger = logging.getLogger(__name__)


class PiperBackend:
    def __init__(self):
        self._voices = {}  # checkpoint_file -> loaded PiperVoice, so switching between siwis/
                            # upmc within one session doesn't re-load a voice already loaded
        self._active_voice = None
        self._active_model_config = None

    # ---- Loading ------------------------------------------------------

    def load_piper(self, model_config, device):
        """Matches load_script. `device` is accepted for call-site symmetry with the FS2 backend's
        load_fastspeech2(device)/load_hifigan(device) but ignored -- piper-tts's onnxruntime
        session is CPU-only by construction on this project's target (no CUDA path requested)."""
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise RuntimeError(
                "Piper backend selected but piper-tts is not installed in this venv. "
                "Install it with: pip install piper-tts==1.5.0 (see INSTALL.md)."
            ) from exc

        key = model_config["checkpoint_file"]
        if key not in self._voices:
            model_path = os.path.join(model_config["folder"], key)
            self._voices[key] = PiperVoice.load(model_path, model_path + ".json")
        self._active_voice = self._voices[key]
        self._active_model_config = model_config

        # Warm-up: one throwaway synthesis, discarded. Required, not optional -- mirrors
        # chatterbox.cli.warmup()'s rationale for the FS2 path (first-call cost of the ONNX
        # session/CPU thread pool spinning up shouldn't be paid serially in front of the user).
        self.tts("Bonjour.", model_config, None, False)

    # ---- Synthesis ------------------------------------------------------

    def tts(self, text_to_syn, tts_config, gui_control, linking_utt):
        """Matches syn_script's caller contract (chatterbox/synth.py calls this exactly like
        FastSpeech2HifiGanBackend.tts()): returns (location_mel_file, processed_text), where
        location_mel_file must be the output *directory* -- exactly like FS2's own tts() return
        value (fastspeech2_hifigan/backend.py:330's os.path.join(model_folder, output_location)),
        not a file-path prefix. This matters specifically because needs_vocoder: false is set:
        chatterbox/synth.py's needs_vocoder=False branch builds the base wav path itself via
        os.path.join(location_mel_file, "audio_file") and appends ".wav" at synth.py's write step
        -- returning anything other than the bare directory here double-joins "audio_file" and
        produces a wrong, nonexistent path (confirmed live: a real --benchmark run on the Pi
        crashed with FileNotFoundError on .../audio_file/audio_file.wav before this was fixed --
        docs/context/CHANGELOG.md). PiperBackend still *writes* the real file at
        <location_mel_file>/audio_file.wav itself, same as always -- only the returned tuple
        element changed."""
        from piper.config import SynthesisConfig

        clean_text, speaker_id = text_frontend.prepare(
            text_to_syn, tts_config, gui_control, self._active_voice)

        # Fixed-directory convention, matching FastSpeech2HifiGanBackend.syn_fastspeech2()'s own
        # os.path.join(model_folder, output_location) (chatterbox/synthesis/backends/
        # fastspeech2_hifigan/backend.py:330) -- confirmed during Phase A.3(a): no per-run/
        # timestamped subfolder, so both backends' output trees stay directly comparable.
        out_dir = os.path.join(tts_config["folder"], tts_config["output_location"])
        os.makedirs(out_dir, exist_ok=True)

        default_args = tts_config["default_args"]
        gui_control = gui_control or {}
        syn_config = SynthesisConfig(
            speaker_id=speaker_id,
            length_scale=gui_control.get("length_scale", default_args["length_scale"]),
            noise_scale=gui_control.get("noise_scale", default_args["noise_scale"]),
            noise_w_scale=gui_control.get("noise_w_scale", default_args["noise_w_scale"]),
        )

        profiling_rec = profiling.current()
        wav_path = os.path.join(out_dir, "audio_file.wav")
        # A single "synth" stage, not separate "phonemize"/"synth" stages as originally sketched:
        # confirmed live (Phase B) that PiperVoice.synthesize_wav() calls self.synthesize()
        # internally, which re-phonemizes the raw text itself regardless -- there is no public,
        # non-redundant way to time phonemization as a step distinct from the rest of this call
        # without phonemizing twice. cli.py's console line for Piper therefore reads a single
        # "TTS" line (stage_durations' wall-clock "tts" entry, chatterbox/synth.py:172-173) same
        # as FS2's -- see Finding #5 in the Phase B plan for the fuller reasoning.
        with profiling_rec.stage("synth"):
            with wave.open(wav_path, "wb") as wav_file:
                self._active_voice.synthesize_wav(clean_text, wav_file, syn_config=syn_config)

        return out_dir, clean_text

    # ---- GUI model-options panel ------------------------------------------------------

    def describe_controls(self):
        """base.py's describe_controls() shape (chatterbox/synthesis/base.py:64-102), rendered
        generically by gui/app.py's gui_generic_controls() -- config_tts.yaml's Piper entries all
        declare gui_script: "gui_generic_controls" (the same shared function FS2 uses), not a
        bespoke per-backend GUI function. No "style"/"style_intensity" controls -- Piper has no
        style dimension, which is also what keeps gui/app.py's gst_token_selection compat global
        (app.py:116) at None while Piper is active, so the Emmanuelle keyboard's mood-shortcut keys
        correctly no-op instead of touching a style control that doesn't exist here."""
        model_config = self._active_model_config
        default_args = model_config["default_args"]
        result = {
            "controls": [
                # "resolution" must be set explicitly -- gui/app.py's gui_generic_controls() (the
                # generic tk.Scale builder) defaults to resolution=1 when a control doesn't
                # specify one, which on a 0.5-2.0 range only leaves 0.5/1.5 selectable (confirmed
                # live: user-reported "cursor only has two values" -- docs/context/CHANGELOG.md).
                # FS2's own sliders (fastspeech2_hifigan/backend.py's describe_controls()) all set
                # this explicitly; these three were the oversight, not a gap in the generic
                # contract itself.
                {"type": "slider", "key": "length_scale", "label_key": "speed_label",
                 "min": 0.0, "max": 2.0, "resolution": 0.1, "default": default_args["length_scale"]},
                {"type": "slider", "key": "noise_scale", "label_key": "variability_label",
                 "min": 0.0, "max": 1.0, "resolution": 0.05,
                 "default": default_args["noise_scale"], "advanced": True},
                {"type": "slider", "key": "noise_w_scale",
                 "label_key": "phoneme_duration_variability_label",
                 "min": 0.0, "max": 1.0, "resolution": 0.05,
                 "default": default_args["noise_w_scale"], "advanced": True},
            ],
        }

        # speaker_id_map/default_speaker_id are real PiperConfig fields (confirmed live on the Pi
        # against fr_FR-upmc-medium.onnx.json: {"jessica": 0, "pierre": 1}) -- empty {} for a
        # single-speaker voice (siwis), in which case speaker_list/default_speaker are omitted
        # entirely, matching base.py's docstring default and FastSpeech2HifiGanBackend's own
        # dict-shaped (not list-shaped) speaker_list (Finding #2 in the Phase B plan).
        speaker_map = self._active_voice.config.speaker_id_map
        if speaker_map:
            result["speaker_list"] = dict(speaker_map)
            result["default_speaker"] = self._active_voice.config.default_speaker_id
        return result
