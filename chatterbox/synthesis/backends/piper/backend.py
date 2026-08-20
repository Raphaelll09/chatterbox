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

import numpy as np

import tools.monitoring.profiling as profiling
from chatterbox.synthesis.backends.piper import text_frontend

logger = logging.getLogger(__name__)

# Leading-context priming for default_args.prepend_leading_pause (see _prime_and_crop() below) --
# a short, common word+comma, not bare punctuation: confirmed live (2026-08-20) that a bare
# leading "." with nothing before it is silently discarded by piper-tts's bundled espeak-ng
# phonemizer before synthesis (voice.phonemize(". Hello...") == voice.phonemize("Hello...")),
# which is why the original prepend_leading_pause implementation (text_frontend.py, now removed)
# never actually did anything. A real word survives phonemization and gives the VITS decoder
# genuine preceding phonetic/prosodic context (confirmed: "Well, hello..." produces a leading
# "wˈɛl," phoneme block, one merged sentence chunk, not a separately-normalized one) -- the
# tradeoff is it must be cropped back off afterward (_find_post_filler_crop_sample() below).
_LEADING_CONTEXT_FILLER = "Well,"


def _find_post_filler_crop_sample(audio, sample_rate):
    """Locates the sample index where real content likely resumes after `_LEADING_CONTEXT_FILLER`
    and its own natural comma-pause, using a coarse RMS-envelope dip detector -- NOT a fixed/
    guessed duration: prototyped and confirmed live (2026-08-20) against a handful of real
    lessac syntheses that a fixed crop is unsafe here, since piper-tts's per-checkpoint ONNX
    export doesn't expose phoneme/audio alignment output (voice.synthesize(...,
    include_alignments=True) returned None for this model) -- there is no exact, model-reported
    boundary to crop at, only the audio's own measured shape.

    Returns None if no clear pause is found in the expected window -- the caller
    (PiperBackend._prime_and_crop()) must then fall back to synthesizing the real text alone
    (today's un-primed behavior) rather than risk cutting into real speech on a bad guess."""
    win_samples = max(1, int(sample_rate * 0.010))  # 10ms analysis windows
    n_windows = len(audio) // win_samples
    if n_windows < 10:
        return None

    envelope = np.sqrt(np.array(
        [np.mean(audio[i * win_samples:(i + 1) * win_samples].astype(np.float64) ** 2)
         for i in range(n_windows)]
    ))
    peak = envelope.max()
    if peak <= 1e-6:  # near-silent output entirely -- nothing to find a pause in
        return None

    threshold = peak * 0.06
    guard_windows = 8         # skip ~80ms -- the filler word's own onset, never mistake it for
                               # the pause that follows it
    search_limit = min(n_windows, 70)  # don't search past ~700ms in -- a short filler word plus
                               # its pause should resolve well inside this on any real sentence;
                               # if not found by here, treat it as not found (see docstring)
    min_run_windows = 3       # consecutive low-energy windows required to call it a real pause,
                               # not just one quiet 10ms slice inside otherwise-voiced audio

    run = 0
    for i in range(guard_windows, search_limit):
        if envelope[i] < threshold:
            run += 1
            if run >= min_run_windows:
                pause_start_window = i - run + 1
                return pause_start_window * win_samples
        else:
            run = 0
    return None


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

    def _prime_and_crop(self, voice, real_text, syn_config):
        """default_args.prepend_leading_pause support (see _LEADING_CONTEXT_FILLER's module
        comment for why this exists and why it's not a simple text prepend). Synthesizes
        `_LEADING_CONTEXT_FILLER + " " + real_text` as ONE utterance -- giving the VITS decoder
        genuine preceding phonetic context for real_text's own first word -- then locates and
        crops the filler + its trailing pause back off the front of the FIRST audio chunk only
        (a multi-sentence real_text's later chunks, if any, are each their own independently-
        synthesized/normalized sentence -- untouched, appended as-is, exactly matching
        synthesize_wav()'s own normal behavior for them).

        Returns (audio_float_array, sample_rate) on success, or None if no safe crop point was
        found -- the caller must then fall back to synthesizing real_text alone."""
        primed_text = _LEADING_CONTEXT_FILLER + " " + real_text
        chunks = list(voice.synthesize(primed_text, syn_config=syn_config))
        if not chunks:
            return None

        first_audio = chunks[0].audio_float_array
        sample_rate = chunks[0].sample_rate
        crop_at = _find_post_filler_crop_sample(first_audio, sample_rate)
        # Sanity bound: a crop point past 80% of the first chunk's own length would mean the
        # "pause" detector found something implausibly late (e.g. inside real_text itself for an
        # unusually short first chunk) -- refuse rather than risk cropping into real speech.
        if crop_at is None or crop_at >= len(first_audio) * 0.8:
            return None

        cropped_first = first_audio[crop_at:].copy()
        # Short fade-in, not a hard cut -- the crop point sits inside a low-energy dip (not
        # necessarily exact digital silence), so this is cheap insurance against a residual click
        # right at the new start of the file.
        fade_samples = min(len(cropped_first), max(1, int(sample_rate * 0.005)))  # 5ms
        cropped_first[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)

        rest = [c.audio_float_array for c in chunks[1:]]
        full_audio = np.concatenate([cropped_first] + rest) if rest else cropped_first
        return full_audio, sample_rate

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
            primed = None
            if default_args.get("prepend_leading_pause", False) and clean_text:
                primed = self._prime_and_crop(voice, clean_text, syn_config)
            with wave.open(wav_path, "wb") as wav_file:
                if primed is not None:
                    audio, sample_rate = primed
                    wav_file.setframerate(sample_rate)
                    wav_file.setsampwidth(2)
                    wav_file.setnchannels(1)
                    int16 = np.clip(audio * 32767.0, -32767.0, 32767.0).astype(np.int16)
                    wav_file.writeframes(int16.tobytes())
                else:
                    # Either prepend_leading_pause isn't set (every French voice today), or it is
                    # but _prime_and_crop() couldn't find a safe crop point -- same call as
                    # always, no priming attempted/left half-applied.
                    voice.synthesize_wav(clean_text, wav_file, syn_config=syn_config)

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

        # speakers: (new, unified multi-checkpoint voice) builds an ordinary {name: index}
        # speaker_list/int default_speaker from the config list itself -- gui/app.py needs no
        # changes at all, it already renders any speaker_list/default_speaker generically. Falls
        # back to the legacy per-voice speaker_id_map (confirmed live on the Pi against
        # fr_FR-upmc-medium.onnx.json: {"jessica": 0, "pierre": 1}; empty {} for a single-speaker
        # voice) for a model with no speakers: list (e.g. English lessac) -- empty/no speaker_list
        # in that case matches base.py's docstring default and FastSpeech2HifiGanBackend's own
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
