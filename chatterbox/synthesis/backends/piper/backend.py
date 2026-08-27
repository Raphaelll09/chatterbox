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

import chatterbox.instrumentation as profiling
from chatterbox.synthesis.backends.piper import text_frontend

logger = logging.getLogger(__name__)

# default_args.prepend_leading_pause (English Piper, real-hardware feedback: "the first word/
# sound is always mispronounced") went through two attempted fixes, both abandoned -- see
# docs/context/CHANGELOG.md's 2026-08-20 entries for the full investigation, not repeated in full
# here:
#   1. Prepending a bare ". " (text_frontend.py) -- confirmed a complete no-op: piper-tts's
#      bundled espeak-ng silently discards a leading "." with nothing before it, so it never
#      changed the synthesized audio at all.
#   2. Priming with a real leading word ("Well,", comma-joined into the same sentence) then
#      cropping it back off using a measured pause in the resulting audio (an RMS-envelope dip
#      detector, since this checkpoint has no phoneme/audio alignment output to crop against
#      precisely). Confirmed via a real batch test (16 runs/sentence, Whisper ASR transcription
#      as ground truth, not just eyeballing waveforms) that this made things WORSE, not better:
#      the un-primed baseline only mispronounces ~6% of the time (1/16 runs), while the primed+
#      crop path left the "Well," filler audible in ~75% of runs (12/16) -- the crop detector
#      kept firing on a false-early dip inside "Well," itself rather than its real trailing
#      pause, and "Well," itself doesn't render reliably enough on this checkpoint to prime
#      against at all. What a live Pi5 test reported as an extra "don't" at the start was this
#      failure mode -- a garbled rendering of the un-cropped "Well," -- not the original bug.
# No working fix exists yet -- default_args.prepend_leading_pause is currently unset/False
# everywhere (matching every French voice) and PiperBackend.tts() below always calls
# synthesize_wav() directly, un-primed. If revisiting this: a different English voice/checkpoint
# is more promising than further tuning this one's priming, since the instability shown above
# looks like a property of this specific ONNX export, not of the priming *approach* in the
# abstract.


class PiperBackend:
    def __init__(self):
        self._voices = {}  # checkpoint_file -> loaded PiperVoice, so switching between speakers
                            # backed by different checkpoints within one session doesn't re-load a
                            # voice already loaded (also serves same-checkpoint speakers, e.g.
                            # Jessica/Pierre sharing upmc, at zero extra cost after the first load)
        self._active_voice = None
        self._active_checkpoint_file = None
        self._active_model_config = None

    # ---- Loading ------------------------------------------------------

    def _load_voice(self, folder, checkpoint_file):
        if checkpoint_file not in self._voices:
            from piper import PiperVoice
            model_path = os.path.join(folder, checkpoint_file)
            self._voices[checkpoint_file] = PiperVoice.load(model_path, model_path + ".json")
        return self._voices[checkpoint_file]

    def load_piper(self, model_config, device):
        """Matches load_script. `device` is accepted for call-site symmetry with the FS2 backend's
        load_fastspeech2(device)/load_hifigan(device) but ignored -- piper-tts's onnxruntime
        session is CPU-only by construction on this project's target (no CUDA path requested)."""
        try:
            from piper import PiperVoice  # noqa: F401 -- import-availability check only
        except ImportError as exc:
            raise RuntimeError(
                "Piper backend selected but piper-tts is not installed in this venv. "
                "Install it with: pip install piper-tts==1.5.0 (see INSTALL.md)."
            ) from exc

        self._active_model_config = model_config

        # speakers: (new, unified multi-checkpoint voice -- e.g. "Piper-tts (Français)" spanning
        # Siwis/Jessica/Pierre) preloads its first (default) entry's checkpoint here; tts()'s own
        # _resolve_speaker() may swap to a different cached/newly-loaded checkpoint on a later call
        # once the GUI selects a different speaker. A legacy single-checkpoint voice (e.g. the
        # English lessac entry, no speakers: key) just loads its own checkpoint_file directly, as
        # before this schema existed.
        speakers = model_config.get("speakers")
        if speakers:
            default_entry = speakers[0]
            checkpoint_file = default_entry["checkpoint_file"]
        else:
            checkpoint_file = model_config["checkpoint_file"]
        self._active_voice = self._load_voice(model_config["folder"], checkpoint_file)
        self._active_checkpoint_file = checkpoint_file

        # Warm-up: one throwaway synthesis, discarded. Required, not optional -- mirrors
        # chatterbox.cli.warmup()'s rationale for the FS2 path (first-call cost of the ONNX
        # session/CPU thread pool spinning up shouldn't be paid serially in front of the user).
        self.tts("Bonjour.", model_config, None, False)

    # ---- Synthesis ------------------------------------------------------

    def _resolve_speaker(self, tts_config, gui_control, tag_speaker_name):
        """Returns (voice, speaker_id) for this call. speakers: (see config_tts.yaml's "Piper-tts
        (Français)" entry) lets one tts_models entry's speakers live in DIFFERENT onnx checkpoints
        (Siwis's own single-speaker checkpoint; Jessica/Pierre sharing upmc's) -- gui_control's
        "speaker" is an index into that list (not a raw per-voice speaker_id, unlike the legacy
        path below), and a <SPEAKER=name> text tag overrides it the same way FS2's own tag
        handling overrides its GUI controls. Swaps self._active_voice to whichever checkpoint the
        resolved entry needs, loading (or reusing an already-cached, chatterbox/synthesis/backends/
        piper/backend.py's self._voices) it as needed -- this always runs on the synthesis worker
        thread (chatterbox/synth.py -> chatterbox/gui/app.py's worker), never the Tk thread, so a
        first-time switch to a not-yet-loaded checkpoint costs a moment of synthesis time, not a
        UI freeze. Falls back to the legacy single-checkpoint per-voice speaker_id_map (e.g. the
        English lessac entry, which has no speakers: list) when this model has none."""
        speakers = tts_config.get("speakers")
        if speakers:
            entry = None
            if gui_control and "speaker" in gui_control:
                index = gui_control["speaker"]
                if 0 <= index < len(speakers):
                    entry = speakers[index]
            if tag_speaker_name is not None:
                tag_entry = next((s for s in speakers if s["name"] == tag_speaker_name), None)
                if tag_entry is not None:
                    entry = tag_entry
                else:
                    logger.debug("Piper: <SPEAKER=%s> not found among this model's speakers, "
                                 "ignoring", tag_speaker_name)
            if entry is None:
                entry = speakers[0]
            voice = self._load_voice(tts_config["folder"], entry["checkpoint_file"])
            self._active_voice = voice
            self._active_checkpoint_file = entry["checkpoint_file"]
            return voice, entry["speaker_id"]

        voice = self._active_voice
        speaker_map = voice.config.speaker_id_map
        speaker_id = voice.config.default_speaker_id
        if gui_control and "speaker" in gui_control and speaker_map:
            speaker_id = gui_control["speaker"]
        if tag_speaker_name is not None and speaker_map and tag_speaker_name in speaker_map:
            speaker_id = speaker_map[tag_speaker_name]
        return voice, speaker_id

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

        clean_text, tag_speaker_name = text_frontend.prepare(text_to_syn, tts_config)
        voice, speaker_id = self._resolve_speaker(tts_config, gui_control, tag_speaker_name)

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
                voice.synthesize_wav(clean_text, wav_file, syn_config=syn_config)

        return out_dir, clean_text

    # ---- GUI model-options panel ------------------------------------------------------

    def describe_controls(self):
        """describe_controls() shape (chatterbox/synthesis/README.md), rendered
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

        # speakers: (new, unified multi-checkpoint voice) builds an ordinary {name: index}
        # speaker_list/int default_speaker from the config list itself -- gui/app.py needs no
        # changes at all, it already renders any speaker_list/default_speaker generically. Falls
        # back to the legacy per-voice speaker_id_map (confirmed live on the Pi against
        # fr_FR-upmc-medium.onnx.json: {"jessica": 0, "pierre": 1}; empty {} for a single-speaker
        # voice) for a model with no speakers: list (e.g. English lessac) -- empty/no speaker_list
        # in that case matches README.md's documented default and FastSpeech2HifiGanBackend's own
        # dict-shaped (not list-shaped) speaker_list (Finding #2 in the Phase B plan).
        speakers = model_config.get("speakers")
        if speakers:
            result["speaker_list"] = {entry["name"]: index for index, entry in enumerate(speakers)}
            result["default_speaker"] = 0
        else:
            speaker_map = self._active_voice.config.speaker_id_map
            if speaker_map:
                result["speaker_list"] = dict(speaker_map)
                result["default_speaker"] = self._active_voice.config.default_speaker_id
        return result
