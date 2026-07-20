#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI entry point + top-level synthesis orchestration.

Combines do_tts.py's argparse/dispatch logic and audio_utils.py's syn_audio() (the parts that
didn't move to chatterbox/audio/{playback,denoise}.py or chatterbox/synthesis/subtitles.py) in
Phase 3 (docs/REORG_PROPOSAL.md). The root-level do_tts.py is now a 3-line shim calling main()
here, preserving the documented CLI contract (every flag below) unchanged.
"""
import os
import sys
import io
import contextlib
import threading
import time
import shutil
import argparse

import torch
import yaml
import numpy as np
from scipy.signal import butter, filtfilt
from scipy.io import wavfile, loadmat
from pydub import AudioSegment

import chatterbox.synthesis.registry as registry
import chatterbox.state as state
import chatterbox.gui.app as app
import chatterbox.audio.playback as playback
import chatterbox.audio.denoise as denoise
import chatterbox.synthesis.subtitles as subtitles
import tools.monitoring.profiling as profiling

device = torch.device("cpu")


def butter_lowpass_filter(data, cutoff, fs, order):
    nyq = 0.5 * fs  # Nyquist Frequency

    normal_cutoff = cutoff / nyq
    # Get the filter coefficients
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    y = filtfilt(b, a, data)
    return y


def syn_audio(use_gui, tts_config, txt_input="", gui_control=None,
              sentence_id=None, complexity_tag=None, play=True):
    """Synthesize text with input text
    Uses global parameters set during model loading (chatterbox.synthesis.registry.BACKEND)

    sentence_id/complexity_tag label the profiling per-sentence record (used
    by tools/measurement/benchmark/runner.py; free-text/GUI callers leave them None). play=False
    skips playback (synthesise-only, used by the benchmark's default mode to
    isolate compute cost).
    """
    # Get global parameters
    TTS_INDEX = getattr(state, "TTS_INDEX")
    VOCODER_INDEX = getattr(state, "VOCODER_INDEX")

    canvas_circle, canvas_circle_figure = None, None
    if use_gui:
        canvas_circle, canvas_circle_figure = app.get_canvas_circle()
        app.update_circle_color("yellow", canvas_circle, canvas_circle_figure)

        ent_text_input = getattr(app, "ent_text_input")
        text_to_syn = ent_text_input.get()
    else:
        text_to_syn = txt_input

    # Debug Synthesis with empty input
    if text_to_syn == "":
        return

    if tts_config["GUI_config"]["online_phon_input"]:
        # Online phonetic input
        text_to_syn = "{{{}}}.".format(text_to_syn)

    # Use default punctuation if not given in text
    # Trim start and end spaces
    text_to_syn = text_to_syn.strip(' ')
    _punctuation = list("[]§«»¬~!'(),.:;?#")
    if text_to_syn[0] not in _punctuation:
        text_to_syn = "{}{}".format(tts_config["default_start_punctuation"], text_to_syn)
    if text_to_syn[-1] not in _punctuation:
        text_to_syn = "{}{}".format(text_to_syn, tts_config["default_end_punctuation"])

    # Profiling: one recorder per top-level input line (shared across any "§"
    # sub-utterances synthesized below). No-op when profiling is disabled.
    profiling_rec = profiling.begin_sentence(text_to_syn, complexity_tag=complexity_tag, sentence_id=sentence_id)
    profiling_rec.set(char_count=len(text_to_syn), word_count=len(text_to_syn.split()))
    profiling.set_current(profiling_rec)

    # TTS generates mel
    start_tts = time.time()

    # Concat sub utterances for subtitles
    if tts_config["subtitles"]["create_file"]:
        input_text_subtitles = ''
        processed_input_text_subtitles = ''
        duration_by_symbol_subtitles = []

        duration_by_frame = tts_config["subtitles"]["duration_by_frame"]["hop_length"] / tts_config["subtitles"]["duration_by_frame"]["sampling_rate"]

    # Parse Multiple utterances with "§"
    sub_utterance_separator = '|'
    sub_utterance_pct = '§'
    first_end_of_utt = text_to_syn.find(sub_utterance_separator)
    if first_end_of_utt > 1:
        text_to_syn_splitted = text_to_syn.split(sub_utterance_separator)
        # print(text_to_syn_splitted)
        for index_sub_utt, sub_utt in enumerate(text_to_syn_splitted):

            # With linking pct
            if index_sub_utt > 0:
                sub_utt = "{}{}".format(linking_pct, sub_utt)
                linking_utt = True
            else:
                linking_utt = False

            linking_pct = sub_utt[-1]

            location_mel_file, processed_sub_text = registry.BACKEND.tts(sub_utt, tts_config['tts_models'][TTS_INDEX], gui_control, linking_utt)

            if tts_config["subtitles"]["create_file"]:
                sub_duration_by_symbol = (np.load(os.path.join(location_mel_file, 'audio_file_duration.npy')) * duration_by_frame).tolist()
                duration_by_symbol_subtitles += sub_duration_by_symbol
                input_text_subtitles = "{}{}".format(input_text_subtitles, sub_utt[1:])
                processed_input_text_subtitles = "{}{}".format(processed_input_text_subtitles, processed_sub_text)

            shape_mel = tuple(np.fromfile(os.path.join(location_mel_file, 'audio_file.WAVEGLOW'), count = 2, dtype = np.int32))
            shape_au = tuple(np.fromfile(os.path.join(location_mel_file, 'audio_file.AU'), count = 4, dtype = np.int32))
            au_len = shape_au[0]
            if index_sub_utt == 0:
                mel_len = shape_mel[0]
                mel_dim = shape_mel[1]


                au_len_concat = au_len
                au_dim = shape_au[1]
                au_num = shape_au[2]
                au_den = shape_au[3]

                mel_file_concat = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.WAVEGLOW'),offset=8,dtype=np.float32,shape=shape_mel))
                au_file_concat = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.AU'),offset=16,dtype=np.float32,shape=(au_len, au_dim)))
            else:
                mel_file_sub_utt = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.WAVEGLOW'),offset=8,dtype=np.float32,shape=shape_mel))
                au_file_sub_utt = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.AU'),offset=16,dtype=np.float32,shape=(au_len, au_dim)))

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
        location_mel_file, processed_text_to_syn = registry.BACKEND.tts(text_to_syn, tts_config['tts_models'][TTS_INDEX], gui_control, False)

        if tts_config["subtitles"]["create_file"]:
            duration_by_symbol_subtitles = (np.load(os.path.join(location_mel_file, 'audio_file_duration.npy')) * duration_by_frame).tolist()
            input_text_subtitles = text_to_syn[1:]
            processed_input_text_subtitles = processed_text_to_syn

    if tts_config["subtitles"]["create_file"]:
        duration_by_frame = tts_config["subtitles"]["duration_by_frame"]["hop_length"] / tts_config["subtitles"]["duration_by_frame"]["sampling_rate"]

        subtitles.write_duration_alignements(input_text_subtitles, processed_input_text_subtitles, duration_by_symbol_subtitles)
        subtitles.write_subtitles(input_text_subtitles, processed_input_text_subtitles, duration_by_symbol_subtitles, tts_config["subtitles"]["max_nbr_char"])

    end_tts = time.time()

    # Vocoder generates wav
    start_vocoder = time.time()
    with profiling_rec.stage("vocoder"):
        location_wav_file = registry.BACKEND.vocoder(location_mel_file, tts_config['vocoder_models'][VOCODER_INDEX])
    end_vocoder = time.time()

    # Denoise signal
    start_denoise = time.time()
    with profiling_rec.stage("write"):
        # Read the wav HiFi-GAN just wrote once, keep it in memory through
        # denoise/postprocess/analyze, and write it back to disk exactly once
        # below -- avoids re-reading/re-writing the same file at every step.
        wav_path = "{}.wav".format(location_wav_file)
        rate, data = wavfile.read(wav_path)

        if tts_config["use_denoiser"]:
            data = denoise.denoise(data, rate)

        # ------------------------------------------------------------------ #
        # Optional post-processing: peak normalisation + soft limiter          #
        # Configured via config_tts.yaml postprocess section or CLI flags.     #
        # ------------------------------------------------------------------ #
        _pp_cfg = tts_config.get("postprocess", {})
        if _pp_cfg.get("enabled", False):
            import chatterbox.synthesis.audio_postprocess as _app
            data, _pp_report = _app.normalize_and_limit(
                data,
                rate,
                target_crest_db=float(_pp_cfg.get("target_crest_db", 14.0)),
                target_peak_dbfs=float(_pp_cfg.get("target_peak_dbfs", -1.0)),
            )
            _app.print_report(_pp_report)

        if _pp_cfg.get("analyze", False):
            import chatterbox.synthesis.audio_postprocess as _app
            _app.report_wav(
                wav_path,
                save_json=True,
                save_figure=True,
                preloaded=(data, rate),
            )

        # Single write-back of the fully processed audio.
        wavfile.write(wav_path, rate, data)

        if tts_config["visual_smoothing"]["activate"]:
            shape_au = tuple(np.fromfile(os.path.join(location_mel_file, 'audio_file.AU'), count = 4, dtype = np.int32))
            au_len = shape_au[0]
            au_dim = shape_au[1]
            au_num = shape_au[2]
            au_den = shape_au[3]
            au_data = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.AU'),offset=16,dtype=np.float32,shape=(au_len, au_dim)))
            for i_au in range(6): # 6 first parameters are for the head movements
                au_data[:, i_au] = butter_lowpass_filter(au_data[:, i_au], tts_config["visual_smoothing"]["cutoff"], au_num/au_den, 1) # cutoff = tts_config["visual_smoothing"]["cutoff"]Hz / order = 1

            fp = open(os.path.join(location_mel_file, 'audio_file.AU'), 'wb')
            fp.write(np.asarray((au_len, au_dim, au_num, au_den), dtype=np.int32))
            fp.write(au_data.copy(order='C'))
            fp.close()

        end_denoise = time.time()

        # Patch for .AU
        path_au = os.path.join(tts_config['tts_models'][TTS_INDEX]["folder"], tts_config['tts_models'][TTS_INDEX]["output_location"], "audio_file.AU")
        if os.path.exists(path_au):
            # Copy file in a platform-independent way
            shutil.copy(path_au, "./")  # Copy to current directory

        # Update audio infos -- built directly from the in-memory samples
        # (same ones just written to wav_path) instead of re-reading the file.
        channels = data.shape[1] if data.ndim == 2 else 1
        playback.AUDIO_EXAMPLE = AudioSegment(
            np.ascontiguousarray(data).tobytes(),
            sample_width=data.dtype.itemsize,
            frame_rate=rate,
            channels=channels,
        )
        audio_duration = len(playback.AUDIO_EXAMPLE)/1000

    profiling_rec.set(
        n_samples=int(playback.AUDIO_EXAMPLE.frame_count()),
        sample_rate=playback.AUDIO_EXAMPLE.frame_rate,
        audio_duration_s=audio_duration,
    )
    profiling_rec.finalize()
    profiling.set_current(None)

    tts_inference_duration = end_tts-start_tts
    vocoder_inference_duration = end_vocoder-start_vocoder
    denoiser_inference_duration = end_denoise-start_denoise

    if use_gui:
        app.update_circle_color("green", canvas_circle, canvas_circle_figure)
        app.update_audio_infos(audio_duration, tts_inference_duration, vocoder_inference_duration, denoiser_inference_duration)

        path_gst_weights = os.path.join(tts_config['tts_models'][TTS_INDEX]["folder"], tts_config['tts_models'][TTS_INDEX]["output_location"], "audio_file_styleTag_gst_weight.mat")
        if os.path.exists(path_gst_weights):
            GST_weights = loadmat(path_gst_weights)['styleTag_gst_weight']
            app.update_GST_infos(GST_weights)
    else:
        print("TTS duration: {:.3f}s | {:.0f}% of audio".format(end_tts-start_tts, 100*(end_tts-start_tts)/audio_duration))
        print("Vocoder duration: {:.3f}s | {:.0f}% of audio".format(end_vocoder-start_vocoder, 100*(end_vocoder-start_vocoder)/audio_duration))
        print("Denoise duration: {:.3f}s | {:.0f}% of audio".format(end_denoise-start_denoise, 100*(end_denoise-start_denoise)/audio_duration))

    # Play Audio
    if play:
        playback.play_audio()
    if use_gui:
        app.update_circle_color("gray", canvas_circle, canvas_circle_figure)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=str,
        default="chatterbox/config/config_tts.yaml",
        help="Configuration File",
    )
    parser.add_argument(
        "--gui",
        required=False,
        action='store_true',
        help="User Interface. Ignored (with a warning) if --benchmark or --p4-sweep is also "
             "given -- those are mutually exclusive top-level modes, not composable with --gui.",
    )
    parser.add_argument(
        "--default_tts",
        type=int,
        default=0,
        help="Use first TTS as default",
    )
    parser.add_argument(
        "--default_vocoder",
        type=int,
        default=0,
        help="Use first Vocoder as default",
    )
    parser.add_argument(
        "--postprocess",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable/disable audio post-processing (peak normalisation + soft limiter). "
             "Overrides config_tts.yaml postprocess.enabled.",
    )
    parser.add_argument(
        "--target-crest-db",
        type=float,
        default=None,
        metavar="DB",
        help="Target active crest factor in dB (default: 14.0). Requires --postprocess.",
    )
    parser.add_argument(
        "--target-peak-dbfs",
        type=float,
        default=None,
        metavar="DBFS",
        help="Target output peak in dBFS (default: -1.0). Requires --postprocess.",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        default=False,
        help="Print a crest-factor / loudness report for each synthesised .wav.",
    )
    parser.add_argument(
        "--report-wav",
        type=str,
        default=None,
        metavar="PATH",
        help="Analyse an existing .wav file and exit (no synthesis).",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        default=False,
        help="Enable the profiling subsystem (per-sentence timing + background "
             "PMIC/CPU/thermal sampling). Off by default. Overrides "
             "config_tts.yaml profiling.enabled. Same effect as CHATTERBOX_PROFILE=1.",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        default=False,
        help="Run the fixed benchmark sentence set (benchmark/sentences_fr.jsonl) "
             "instead of interactive free-text mode. Implies --profile.",
    )
    parser.add_argument(
        "--sentences",
        type=str,
        default=None,
        metavar="FILE",
        help="Override the default benchmark sentence set (JSONL). Requires --benchmark.",
    )
    parser.add_argument(
        "--play",
        action="store_true",
        default=False,
        help="Also play back synthesised audio during --benchmark (default: "
             "synthesise only, to isolate compute cost). No effect outside --benchmark.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        metavar="N",
        help="Run the benchmark sentence set N times. Requires --benchmark.",
    )
    parser.add_argument(
        "--join",
        action="store_true",
        default=False,
        help="After --benchmark finishes, run the offline profiling join "
             "(tools/monitoring/profiling/join.py) to produce per_sentence_results.csv / per_stage_results.csv.",
    )
    parser.add_argument(
        "--ina",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Auto-detect and log the INA226 amp-branch current/power monitor "
             "(i2c-1 @ 0x40) alongside PMIC telemetry. On by default when profiling "
             "is enabled; absent sensor just leaves ina_* columns empty. Overrides "
             "config_tts.yaml profiling.ina226. Use --no-ina to skip the I2C probe.",
    )
    parser.add_argument(
        "--export-xlsx",
        action="store_true",
        default=False,
        help="After --benchmark finishes, export per_sentence_results.csv / "
             "per_stage_results.csv to a paste-ready profile/exports/chatterbox_paste.xlsx "
             "(tools/measurement/benchmark/export_to_xlsx.py). Implies --join. Requires openpyxl.",
    )
    parser.add_argument(
        "--p4-sweep",
        action="store_true",
        default=False,
        help="Run the P4 cadence sweep (tools/measurement/benchmark/p4_sweep.py): a series of fixed-cadence "
             "points (--cadences), profiling+playback on throughout, prompting to read an "
             "external power meter between points, fitting P_use(N) = P_idle + k*N at the "
             "end. Implies profiling; always plays back regardless of --play/--profile "
             "(both accepted as harmless no-ops alongside --p4-sweep).",
    )
    parser.add_argument(
        "--cadences",
        type=str,
        default="0,1,2,5,10,max",
        metavar="LIST",
        help="Comma-separated utterances/minute for --p4-sweep, e.g. '0,1,2,5,10,max'. "
             "0 = pure idle anchor (no synthesis). max = back-to-back, no sleep. "
             "Requires --p4-sweep.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=600,
        metavar="SECONDS",
        help="Seconds per cadence point for --p4-sweep (default: 600). Requires --p4-sweep.",
    )
    args = parser.parse_args()

    # --report-wav: standalone analysis, no synthesis required
    if args.report_wav is not None:
        import chatterbox.synthesis.audio_postprocess as _app
        _app.report_wav(args.report_wav, save_json=True, save_figure=True)
        raise SystemExit(0)

    # --p4-sweep: validate --cadences/--duration eagerly, before load_models()
    # and the first interactive prompt -- an hour-long, human-in-the-loop
    # procedure shouldn't fail on a typo deep into it.
    p4_cadences = None
    if args.p4_sweep:
        import tools.measurement.benchmark.p4_sweep as p4_sweep_module
        try:
            p4_cadences = p4_sweep_module.parse_cadences(args.cadences)
        except ValueError as exc:
            parser.error("--cadences: {}".format(exc))
        if args.duration <= 0:
            parser.error("--duration must be > 0, got {}".format(args.duration))

    tts_config = yaml.load(
        open(args.config, "r"), Loader=yaml.FullLoader
    )

    # Merge CLI post-processing flags into tts_config
    pp = tts_config.setdefault("postprocess", {})
    if args.postprocess is not None:
        pp["enabled"] = args.postprocess
    if args.target_crest_db is not None:
        pp["target_crest_db"] = args.target_crest_db
    if args.target_peak_dbfs is not None:
        pp["target_peak_dbfs"] = args.target_peak_dbfs
    if args.analyze:
        pp["analyze"] = True

    # Merge CLI/env profiling flags into tts_config
    prof_cfg = tts_config.setdefault("profiling", {})
    if args.profile or args.benchmark or args.p4_sweep or os.environ.get("CHATTERBOX_PROFILE") == "1":
        prof_cfg["enabled"] = True
    if args.ina is not None:
        prof_cfg["ina226"] = args.ina
    if prof_cfg.get("enabled", False):
        profiling.enable()
        profiling.set_output_dir(prof_cfg.get("output_dir", "profile"))
        # --p4-sweep manages its own per-cadence-point sessions via
        # profiling.start_session_at() (tools/measurement/benchmark/p4_sweep.py) -- it still
        # needs enable()/set_output_dir() above, just not this single
        # top-level session.
        if not args.p4_sweep:
            profiling.start_session(
                core=prof_cfg.get("core", 3),
                niceness=prof_cfg.get("niceness", 10),
                sample_hz=prof_cfg.get("sample_hz", 10),
                pmic_hz=prof_cfg.get("pmic_hz", 10),
                ina=prof_cfg.get("ina226", True),
                meta_extra={"play": args.play, "repeats": args.repeats} if args.benchmark else None,
            )

    def load_models():
        # Load TTS
        default_tts = tts_config["tts_models"][args.default_tts]
        state.update_selected_tts(args.default_tts+1)
        tts_loading_script = getattr(registry.BACKEND, default_tts["load_script"])
        tts_loading_script(default_tts, device)

        # Load Vocoder
        default_vocoder = tts_config["vocoder_models"][args.default_vocoder]
        state.update_selected_vocoder(args.default_vocoder+1)
        vocoder_loading_script = getattr(registry.BACKEND, default_vocoder["load_script"])
        vocoder_loading_script(default_vocoder, device)

    def _warmup_synthesis():
        # Model weights are already loaded by this point -- what's left is
        # first-call cost (torch's CPU thread pool spinning up, the Pi's CPU
        # frequency governor ramping up from idle, noisereduce's own FFT setup,
        # etc.), paid once by whichever synthesis call happens to go first.
        # Run one throwaway synthesis now, in the background, so that cost
        # overlaps with the time the user spends typing their first real
        # sentence instead of being paid serially in front of them.
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                syn_audio(
                    False, tts_config, "Bonjour.",
                    sentence_id="WARMUP", complexity_tag="warmup", play=False,
                )
        except Exception as exc:
            print("[warmup] skipped: {}".format(exc), file=sys.stderr)

    # --gui, --benchmark, and --p4-sweep are mutually exclusive top-level modes (checked in this
    # priority order below) -- previously a silent override with no indication --gui had been
    # ignored; make that explicit now that manual testing surfaced how confusing it was.
    if args.gui and (args.benchmark or args.p4_sweep):
        winning_flag = "--benchmark" if args.benchmark else "--p4-sweep"
        print(
            "[do_tts] --gui has no effect together with {0} -- running {0} instead. "
            "Launch the interface on its own with `do_tts.py --gui`.".format(winning_flag),
            file=sys.stderr,
        )

    try:
        if args.benchmark:
            import tools.measurement.benchmark.runner as benchmark_runner
            load_models()
            benchmark_runner.run_benchmark(
                tts_config,
                sentences_path=args.sentences or benchmark_runner.DEFAULT_SENTENCES_PATH,
                play=args.play,
                repeats=args.repeats,
            )
        elif args.p4_sweep:
            load_models()
            p4_sweep_module.run_p4_sweep(
                tts_config,
                cadences=p4_cadences,
                duration=args.duration,
                output_dir=prof_cfg.get("output_dir", "profile"),
            )
        elif args.gui:
            gui_config = tts_config['GUI_config']
            app.create_gui(tts_config, device, args.default_tts, args.default_vocoder)
        else:
            # No GUI, free text
            load_models()

            # Start the warm-up in the background right away, so it overlaps
            # with the user typing their first sentence. If they submit before
            # it finishes, join() blocks until it's done -- this keeps the
            # warm-up and the first real synthesis from running concurrently
            # (they'd otherwise race on the fixed-path FastSpeech2/HiFi-GAN
            # output files and contend for the same CPU cores).
            warmup_thread = threading.Thread(target=_warmup_synthesis, daemon=True)
            warmup_thread.start()

            first_input = True
            while True:
                txt_input = input("Input Text (Ctrl+C to exit): ")
                if first_input:
                    warmup_thread.join()
                    first_input = False
                syn_audio(False, tts_config, txt_input)
    finally:
        profiling.stop_session()

    if args.benchmark and (args.join or args.export_xlsx):
        from tools.monitoring.profiling.join import run_join
        # profiling.get_run_dir() is this session's profile/run_.../ (set by
        # start_session(), still valid after stop_session() -- see its
        # docstring). Falls back to the base output_dir only if profiling was
        # somehow enabled without a session ever starting.
        run_dir = profiling.get_run_dir() or prof_cfg.get("output_dir", "profile")
        run_join(run_dir)

    if args.benchmark and args.export_xlsx:
        from tools.measurement.benchmark.export_to_xlsx import export as export_xlsx
        export_xlsx(run_dir)
