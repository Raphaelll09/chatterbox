#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jul  1 16:20:38 2022

@author: lengletm
"""

import os
import sys
import io
import contextlib
import threading
import torch
import yaml
import argparse
import loading_modules
import gui_utils
import tts_utils
import audio_utils
import profiling

device = torch.device("cpu")

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=str,
        default="config_tts.yaml",
        help="Configuration File",
    )
    parser.add_argument(
        "--gui",
        required=False,
        action='store_true',
        help="User Interface",
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
             "(profiling/join.py) to produce per_sentence_results.csv / per_stage_results.csv.",
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
             "(benchmark/export_to_xlsx.py). Implies --join. Requires openpyxl.",
    )
    args = parser.parse_args()

    # --report-wav: standalone analysis, no synthesis required
    if args.report_wav is not None:
        import audio_postprocess as _app
        _app.report_wav(args.report_wav, save_json=True, save_figure=True)
        raise SystemExit(0)

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
    if args.profile or args.benchmark or os.environ.get("CHATTERBOX_PROFILE") == "1":
        prof_cfg["enabled"] = True
    if args.ina is not None:
        prof_cfg["ina226"] = args.ina
    if prof_cfg.get("enabled", False):
        profiling.enable()
        profiling.set_output_dir(prof_cfg.get("output_dir", "profile"))
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
        tts_utils.update_selected_tts(args.default_tts+1)
        tts_loading_script = getattr(loading_modules, default_tts["load_script"])
        tts_loading_script(default_tts, device)

        # Load Vocoder
        default_vocoder = tts_config["vocoder_models"][args.default_vocoder]
        tts_utils.update_selected_vocoder(args.default_vocoder+1)
        vocoder_loading_script = getattr(loading_modules, default_vocoder["load_script"])
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
                audio_utils.syn_audio(
                    False, tts_config, "Bonjour.",
                    sentence_id="WARMUP", complexity_tag="warmup", play=False,
                )
        except Exception as exc:
            print("[warmup] skipped: {}".format(exc), file=sys.stderr)

    try:
        if args.benchmark:
            import benchmark.runner as benchmark_runner
            load_models()
            benchmark_runner.run_benchmark(
                tts_config,
                sentences_path=args.sentences or benchmark_runner.DEFAULT_SENTENCES_PATH,
                play=args.play,
                repeats=args.repeats,
            )
        elif args.gui:
            gui_config = tts_config['GUI_config']
            gui_utils.create_gui(tts_config, device, args.default_tts, args.default_vocoder)
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
                audio_utils.syn_audio(False, tts_config, txt_input)
    finally:
        profiling.stop_session()

    if args.benchmark and (args.join or args.export_xlsx):
        from profiling.join import run_join
        # profiling.get_run_dir() is this session's profile/run_.../ (set by
        # start_session(), still valid after stop_session() -- see its
        # docstring). Falls back to the base output_dir only if profiling was
        # somehow enabled without a session ever starting.
        run_dir = profiling.get_run_dir() or prof_cfg.get("output_dir", "profile")
        run_join(run_dir)

    if args.benchmark and args.export_xlsx:
        from benchmark.export_to_xlsx import export as export_xlsx
        export_xlsx(run_dir)