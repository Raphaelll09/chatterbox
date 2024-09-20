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
    args = parser.parse_args()
    
    tts_config = yaml.load(
        open(args.config, "r"), Loader=yaml.FullLoader
    )
    
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
            txt_input = input("Input Text: ")
            audio_utils.syn_audio(False, tts_config, txt_input)
