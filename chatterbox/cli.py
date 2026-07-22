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
import argparse

import torch
import yaml

import chatterbox.synthesis.registry as registry
import chatterbox.state as state
import chatterbox.gui.app as app
import chatterbox.audio.playback as playback
import chatterbox.synth as synth
import tools.monitoring.profiling as profiling

device = torch.device("cpu")

# Console display name per AudioResult.stage_durations key (chatterbox/synth.py) -- falls back to
# the raw key.title() for a stage name a future backend introduces that isn't listed here, so a
# new backend's stages still get *some* readable console line without a code change here.
_STAGE_DISPLAY_NAMES = {"tts": "TTS", "vocoder": "Vocoder", "denoiser": "Denoise"}


def syn_audio(use_gui, tts_config, txt_input="", gui_control=None,
              sentence_id=None, complexity_tag=None, play=True):
    """CLI/benchmark entry point. Delegates the actual compute to chatterbox.synth.synthesize()
    (chatterbox_gui_spec_v0.1.md Sec2.3) and prints the duration report to the console.

    `use_gui` is kept only for call-site compatibility with tools/measurement/benchmark/
    {runner,p4_sweep}.py, the free-text loop below, and tests/test_benchmark.py's fake -- all of
    which already pass False positionally. It no longer branches on anything: the GUI stopped
    calling this function in the GUI refactor (chatterbox_gui_spec_v0.1.md) -- it calls
    chatterbox.synth.synthesize() + chatterbox.audio.playback.play_audio() directly from its own
    worker thread instead, so it can post UI updates back itself.

    sentence_id/complexity_tag label the profiling per-sentence record (used
    by tools/measurement/benchmark/runner.py; free-text callers leave them None). play=False
    skips playback (synthesise-only, used by the benchmark's default mode to
    isolate compute cost).
    """
    TTS_INDEX = getattr(state, "TTS_INDEX")
    VOCODER_INDEX = getattr(state, "VOCODER_INDEX")

    result = synth.synthesize(
        txt_input, TTS_INDEX, VOCODER_INDEX, tts_config,
        gui_control=gui_control, sentence_id=sentence_id, complexity_tag=complexity_tag,
    )
    if result is None:
        return  # empty input, same as the pre-refactor early return

    for stage_key, stage_duration in result.stage_durations.items():
        display_name = _STAGE_DISPLAY_NAMES.get(stage_key, stage_key.title())
        print("{} duration: {:.3f}s | {:.0f}% of audio".format(
            display_name, stage_duration, 100 * stage_duration / result.audio_duration_s))

    if play:
        playback.play_audio()


def warmup(tts_config):
    """One throwaway synthesis, meant to run in the background (a daemon thread) so its
    first-call cost (torch's CPU thread pool spinning up, the Pi's CPU frequency governor ramping
    up from idle, noisereduce's own FFT setup, etc.) overlaps with the user typing/settling in
    instead of being paid serially in front of them. Used by both the CLI free-text loop (below)
    and the GUI's own startup warm-up (chatterbox/gui/app.py, chatterbox_gui_spec_v0.1.md Sec6) --
    module-level (not a closure) specifically so the GUI can call it too.
    """
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            syn_audio(
                False, tts_config, "Bonjour.",
                sentence_id="WARMUP", complexity_tag="warmup", play=False,
            )
    except Exception as exc:
        print("[warmup] skipped: {}".format(exc), file=sys.stderr)


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
            warmup_thread = threading.Thread(target=warmup, args=(tts_config,), daemon=True)
            warmup_thread.start()

            first_input = True
            while True:
                # Print the prompt straight to sys.__stdout__ (the real stdout stream, captured
                # once at interpreter startup) rather than through input()'s own prompt-printing,
                # which goes via the current sys.stdout -- a single process-wide object. The
                # warm-up thread above temporarily redirects sys.stdout globally (warmup()'s
                # contextlib.redirect_stdout) to keep its throwaway synthesis quiet; on the very
                # first loop iteration that redirect can still be active for the ~0.2-0.5s it
                # takes warm-up to run, silently swallowing this prompt into warm-up's discarded
                # buffer instead of the terminal (input() still reads stdin fine either way, so
                # this only ever looked like a missing prompt, not a hang -- see
                # docs/context/CHANGELOG.md 2026-07-21 "Fix the first free-text prompt...").
                print("Input Text (Ctrl+C to exit): ", end="", flush=True, file=sys.__stdout__)
                txt_input = input()
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
