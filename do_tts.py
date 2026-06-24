#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jul  1 16:20:38 2022

@author: lengletm
"""

import torch
import yaml
import argparse
import loading_modules 
import gui_utils
import tts_utils
import audio_utils

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
    
    if args.gui:
        gui_config = tts_config['GUI_config']
        gui_utils.create_gui(tts_config, device, args.default_tts, args.default_vocoder)
    else:
        # No GUI
        
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
        
        while True:
            txt_input = input("Input Text (Ctrl+C to exit): ")
            audio_utils.syn_audio(False, tts_config, txt_input)