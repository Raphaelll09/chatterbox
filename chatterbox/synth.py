#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Tk-free synthesis compute path (chatterbox_gui_spec_v0.1.md Sec2.3).

Extracted from chatterbox/cli.py:syn_audio() so it can run on a worker thread from the GUI without
ever touching Tk -- no `chatterbox.gui.app` import, no `use_gui` branching, no playback call. Both
`chatterbox.cli.syn_audio()` (CLI/benchmark) and `chatterbox.gui.app`'s worker thread call
synthesize() directly; the caller is responsible for playback (chatterbox.audio.playback.
play_audio()) and any UI/console reporting, using the returned AudioResult.

This is a logic *move*, not a rewrite -- the file I/O below (np.memmap/np.fromfile on the mel/.AU
files HiFi-GAN/FastSpeech2 write to disk) is unchanged from the pre-refactor syn_audio(); see
tools/measurement/... 's tests and the manual real-weights smoke test in docs/gui/GUI.md for how
this was verified against real models.
"""
import os
import shutil
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.signal import butter, filtfilt
from scipy.io import wavfile, loadmat
from pydub import AudioSegment

import chatterbox.audio.denoise as denoise
import chatterbox.audio.playback as playback
import chatterbox.synthesis.registry as registry
import chatterbox.synthesis.subtitles as subtitles
import tools.monitoring.profiling as profiling


@dataclass
class AudioResult:
    """Everything callers need to report on a synthesis -- the actual audio clip itself is handed
    off via the existing chatterbox.audio.playback.AUDIO_EXAMPLE global (unchanged mechanism).

    stage_durations replaces separate tts_duration_s/vocoder_duration_s/denoiser_duration_s fields
    (interchangeable-backend GUI refactor, phase 2 -- see docs/context/CHANGELOG.md): a dict,
    insertion-ordered, keyed by stage name ("tts", "vocoder", "denoiser" today). "vocoder" is
    present only when the selected TTS model's needs_vocoder flag (config_tts.yaml) is true --
    a monolithic backend produces a finished wav directly and has no separate vocoder stage to
    time. Callers (chatterbox/cli.py, chatterbox/gui/app.py) iterate this generically instead of
    reading named fields, so they don't need to change when a backend's stage set differs."""
    audio_duration_s: float
    stage_durations: dict
    gst_weights: Optional[np.ndarray] = None


def butter_lowpass_filter(data, cutoff, fs, order):
    nyq = 0.5 * fs  # Nyquist Frequency
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    return filtfilt(b, a, data)


def synthesize(text, tts_idx, voc_idx, tts_config, gui_control=None,
               sentence_id=None, complexity_tag=None):
    """Text -> mel (FastSpeech2) -> wav (HiFi-GAN) -> denoise/postprocess/visual-smoothing ->
    subtitles written to disk -> playback.AUDIO_EXAMPLE set. Returns None for empty/whitespace-only
    input (nothing to do, same as the pre-refactor early return), otherwise an AudioResult.

    tts_idx/voc_idx select tts_config['tts_models'][tts_idx] / ['vocoder_models'][voc_idx] -- pass
    these explicitly (a snapshot of chatterbox.state.TTS_INDEX/VOCODER_INDEX taken by the caller
    before starting any worker thread) rather than reading the state globals in here, so a model
    switch mid-synthesis on another thread can't change which model an in-flight call uses.
    """
    if tts_config["GUI_config"]["online_phon_input"]:
        text = "{{{}}}.".format(text)

    text = text.strip(' ')
    if not text:
        return None

    _punctuation = list("[]§«»¬~!'(),.:;?#")
    if text[0] not in _punctuation:
        text = "{}{}".format(tts_config["default_start_punctuation"], text)
    if text[-1] not in _punctuation:
        text = "{}{}".format(text, tts_config["default_end_punctuation"])

    text_to_syn = text

    # Static per-model capability flag (config_tts.yaml, decidable before any model is loaded --
    # see chatterbox/synthesis/base.py's describe_controls() docstring): a monolithic backend
    # produces a finished wav directly during the "tts" call below and has no separate mel->wav
    # stage to run.
    needs_vocoder = tts_config['tts_models'][tts_idx].get('needs_vocoder', True)

    # Profiling: one recorder per top-level input line (shared across any "§" sub-utterances
    # synthesized below). No-op when profiling is disabled.
    profiling_rec = profiling.begin_sentence(text_to_syn, complexity_tag=complexity_tag, sentence_id=sentence_id)
    profiling_rec.set(char_count=len(text_to_syn), word_count=len(text_to_syn.split()))
    profiling.set_current(profiling_rec)

    start_tts = time.time()

    # audio_file_duration.npy (per-symbol duration data) is FastSpeech2-specific output -- its own
    # duration predictor writes it alongside the mel/.AU files; no other backend produces it. The
    # top-level subtitles.create_file flag was the only gate here, so selecting a backend without
    # this data (Piper) crashed with FileNotFoundError the first time this was actually exercised
    # end-to-end (Piper integration, docs/context/CHANGELOG.md) -- not caught by unit/smoke tests
    # that call registry.BACKEND.tts()/PiperBackend.tts() directly, bypassing this code entirely.
    # supports_subtitles (new static per-model flag, same "read before that model is loaded"
    # pattern as needs_vocoder/accepts_phoneme_input, config_tts.yaml) defaults True -- every
    # existing FS2 entry's real behavior -- and is false on Piper's entries.
    subtitles_supported = tts_config['tts_models'][tts_idx].get('supports_subtitles', True)
    write_subtitles = tts_config["subtitles"]["create_file"] and subtitles_supported

    if write_subtitles:
        input_text_subtitles = ''
        processed_input_text_subtitles = ''
        duration_by_symbol_subtitles = []
        duration_by_frame = tts_config["subtitles"]["duration_by_frame"]["hop_length"] / tts_config["subtitles"]["duration_by_frame"]["sampling_rate"]

    # Parse Multiple utterances with "§"
    sub_utterance_separator = '|'
    first_end_of_utt = text_to_syn.find(sub_utterance_separator)
    if first_end_of_utt > 1:
        text_to_syn_splitted = text_to_syn.split(sub_utterance_separator)
        for index_sub_utt, sub_utt in enumerate(text_to_syn_splitted):
            if index_sub_utt > 0:
                sub_utt = "{}{}".format(linking_pct, sub_utt)
                linking_utt = True
            else:
                linking_utt = False

            linking_pct = sub_utt[-1]

            location_mel_file, processed_sub_text = registry.BACKEND.tts(sub_utt, tts_config['tts_models'][tts_idx], gui_control, linking_utt)

            if write_subtitles:
                sub_duration_by_symbol = (np.load(os.path.join(location_mel_file, 'audio_file_duration.npy')) * duration_by_frame).tolist()
                duration_by_symbol_subtitles += sub_duration_by_symbol
                input_text_subtitles = "{}{}".format(input_text_subtitles, sub_utt[1:])
                processed_input_text_subtitles = "{}{}".format(processed_input_text_subtitles, processed_sub_text)

            # NOTE: this whole "|"-separated multi-utterance branch concatenates mel/.AU data in
            # FastSpeech2's own binary format below, unconditionally (not gated by write_subtitles
            # or needs_vocoder) -- it remains FS2-specific and unsupported by a monolithic backend
            # like Piper regardless of supports_subtitles; a Piper user including "|" in free text
            # will still hit a FileNotFoundError here. Not fixed as part of the Piper integration
            # (docs/context/CHANGELOG.md) -- out of scope, a real remaining gap, documented rather
            # than silently left for someone to rediscover the hard way.
            shape_mel = tuple(np.fromfile(os.path.join(location_mel_file, 'audio_file.WAVEGLOW'), count=2, dtype=np.int32))
            shape_au = tuple(np.fromfile(os.path.join(location_mel_file, 'audio_file.AU'), count=4, dtype=np.int32))
            au_len = shape_au[0]
            if index_sub_utt == 0:
                mel_len = shape_mel[0]
                mel_dim = shape_mel[1]

                au_len_concat = au_len
                au_dim = shape_au[1]
                au_num = shape_au[2]
                au_den = shape_au[3]

                mel_file_concat = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.WAVEGLOW'), offset=8, dtype=np.float32, shape=shape_mel))
                au_file_concat = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.AU'), offset=16, dtype=np.float32, shape=(au_len, au_dim)))
            else:
                mel_file_sub_utt = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.WAVEGLOW'), offset=8, dtype=np.float32, shape=shape_mel))
                au_file_sub_utt = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.AU'), offset=16, dtype=np.float32, shape=(au_len, au_dim)))

                mel_file_concat = np.concatenate((mel_file_concat, mel_file_sub_utt))
                au_file_concat = np.concatenate((au_file_concat, au_file_sub_utt))

                mel_len += shape_mel[0]
                au_len_concat += au_len

        fp = open(os.path.join(location_mel_file, 'audio_file.WAVEGLOW'), 'wb')
        fp.write(np.asarray((mel_len, mel_dim), dtype=np.int32))
        fp.write(mel_file_concat.copy(order='C'))
        fp.close()

        fp = open(os.path.join(location_mel_file, 'audio_file.AU'), 'wb')
        fp.write(np.asarray((au_len_concat, au_dim, au_num, au_den), dtype=np.int32))
        fp.write(au_file_concat.copy(order='C'))
        fp.close()
    else:
        location_mel_file, processed_text_to_syn = registry.BACKEND.tts(text_to_syn, tts_config['tts_models'][tts_idx], gui_control, False)

        if write_subtitles:
            duration_by_symbol_subtitles = (np.load(os.path.join(location_mel_file, 'audio_file_duration.npy')) * duration_by_frame).tolist()
            input_text_subtitles = text_to_syn[1:]
            processed_input_text_subtitles = processed_text_to_syn

    if write_subtitles:
        duration_by_frame = tts_config["subtitles"]["duration_by_frame"]["hop_length"] / tts_config["subtitles"]["duration_by_frame"]["sampling_rate"]
        subtitles.write_duration_alignements(input_text_subtitles, processed_input_text_subtitles, duration_by_symbol_subtitles)
        subtitles.write_subtitles(input_text_subtitles, processed_input_text_subtitles, duration_by_symbol_subtitles, tts_config["subtitles"]["max_nbr_char"])

    end_tts = time.time()
    stage_durations = {"tts": end_tts - start_tts}

    # Vocoder generates wav -- skipped for a monolithic backend (needs_vocoder: False in
    # config_tts.yaml), which already wrote a finished wav during the "tts" call above, under the
    # same output-folder/AUDIO_FILE_NAME convention BACKEND.vocoder() itself returns.
    if needs_vocoder:
        start_vocoder = time.time()
        with profiling_rec.stage("vocoder"):
            location_wav_file = registry.BACKEND.vocoder(location_mel_file, tts_config['vocoder_models'][voc_idx])
        stage_durations["vocoder"] = time.time() - start_vocoder
    else:
        location_wav_file = os.path.join(location_mel_file, "audio_file")

    # Denoise signal
    start_denoise = time.time()
    with profiling_rec.stage("write"):
        wav_path = "{}.wav".format(location_wav_file)
        rate, data = wavfile.read(wav_path)

        if tts_config["use_denoiser"]:
            data = denoise.denoise(data, rate)

        _pp_cfg = tts_config.get("postprocess", {})
        if _pp_cfg.get("enabled", False):
            import chatterbox.synthesis.audio_postprocess as _app
            data, _pp_report = _app.normalize_and_limit(
                data, rate,
                target_crest_db=float(_pp_cfg.get("target_crest_db", 14.0)),
                target_peak_dbfs=float(_pp_cfg.get("target_peak_dbfs", -1.0)),
            )
            _app.print_report(_pp_report)

        if _pp_cfg.get("analyze", False):
            import chatterbox.synthesis.audio_postprocess as _app
            _app.report_wav(wav_path, save_json=True, save_figure=True, preloaded=(data, rate))

        wavfile.write(wav_path, rate, data)

        # Visual/facial-animation params are backend-specific and optional (SynthesisResult.au_path
        # docstring, chatterbox/synthesis/base.py) -- a backend that doesn't produce an .AU file
        # (e.g. a monolithic model with no visual output) just skips this block instead of crashing.
        path_au_for_smoothing = os.path.join(location_mel_file, 'audio_file.AU')
        if tts_config["visual_smoothing"]["activate"] and os.path.exists(path_au_for_smoothing):
            shape_au = tuple(np.fromfile(os.path.join(location_mel_file, 'audio_file.AU'), count=4, dtype=np.int32))
            au_len = shape_au[0]
            au_dim = shape_au[1]
            au_num = shape_au[2]
            au_den = shape_au[3]
            au_data = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.AU'), offset=16, dtype=np.float32, shape=(au_len, au_dim)))
            for i_au in range(6):  # 6 first parameters are for the head movements
                au_data[:, i_au] = butter_lowpass_filter(au_data[:, i_au], tts_config["visual_smoothing"]["cutoff"], au_num / au_den, 1)

            fp = open(os.path.join(location_mel_file, 'audio_file.AU'), 'wb')
            fp.write(np.asarray((au_len, au_dim, au_num, au_den), dtype=np.int32))
            fp.write(au_data.copy(order='C'))
            fp.close()

        end_denoise = time.time()
        stage_durations["denoiser"] = end_denoise - start_denoise

        path_au = os.path.join(tts_config['tts_models'][tts_idx]["folder"], tts_config['tts_models'][tts_idx]["output_location"], "audio_file.AU")
        if os.path.exists(path_au):
            shutil.copy(path_au, "./")

        channels = data.shape[1] if data.ndim == 2 else 1
        playback.AUDIO_EXAMPLE = AudioSegment(
            np.ascontiguousarray(data).tobytes(),
            sample_width=data.dtype.itemsize,
            frame_rate=rate,
            channels=channels,
        )
        audio_duration = len(playback.AUDIO_EXAMPLE) / 1000

    profiling_rec.set(
        n_samples=int(playback.AUDIO_EXAMPLE.frame_count()),
        sample_rate=playback.AUDIO_EXAMPLE.frame_rate,
        audio_duration_s=audio_duration,
    )
    profiling_rec.finalize()
    profiling.set_current(None)

    gst_weights = None
    path_gst_weights = os.path.join(tts_config['tts_models'][tts_idx]["folder"], tts_config['tts_models'][tts_idx]["output_location"], "audio_file_styleTag_gst_weight.mat")
    if os.path.exists(path_gst_weights):
        gst_weights = loadmat(path_gst_weights)['styleTag_gst_weight']

    return AudioResult(
        audio_duration_s=audio_duration,
        stage_durations=stage_durations,
        gst_weights=gst_weights,
    )
