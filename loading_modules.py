#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jul 21 11:06:04 2022

@author: lengletm
"""
import yaml
import os
import argparse
import sys
import torch
import json

import paths

sys.path.insert(1, str(paths.FASTSPEECH2_DIR))
from utils.model import get_model

sys.path.insert(1, str(paths.HIFIGAN_DIR))
from env import AttrDict
from models import Generator

sys.path.insert(1, str(paths.WAVEGLOW_DIR))

# The FastSpeech2 config/output/preprocessed_data archives are gitignored (downloaded from the
# Google Drive links in README.md, never committed) and hardcode paths like
# "FastSpeech2/preprocessed_data/ALL_corpus" -- relative to where FastSpeech2/ used to live at the
# repo root, before the reorg moved it to assets/models/FastSpeech2/ (docs/REORG_PROPOSAL.md Sec6).
# Remap them in memory so a fresh download doesn't need hand-patching every time; values that have
# already been updated (no longer starting with this prefix) are left untouched.
_LEGACY_FASTSPEECH2_PREFIX = "FastSpeech2/"


def _repoint_legacy_fastspeech2_config_paths(preprocess_config, train_config):
    for key in ("preprocessed_path", "output_syn_path"):
        value = preprocess_config["path"].get(key)
        if value and value.startswith(_LEGACY_FASTSPEECH2_PREFIX):
            preprocess_config["path"][key] = str(paths.ROOT / "assets" / "models" / value)

    value = train_config["path"].get("ckpt_path")
    if value and value.startswith(_LEGACY_FASTSPEECH2_PREFIX):
        train_config["path"]["ckpt_path"] = str(paths.ROOT / "assets" / "models" / value)

def load_fastspeech2(tts_model, device):
    global TTS_MODEL
    global CONFIGS
    global FLAUBERT_MODEL
    global FLAUBERT_TOKENIZER
    
    # Read Config
    model_folder = tts_model["folder"]
    default_args = tts_model["default_args"]
    model_ckpt = tts_model["checkpoint_file"]
    
    # Load FastSpeech2 Configs
    os.path.join
    preprocess_config = yaml.load(
        open(os.path.join(model_folder, default_args["preprocess_config"]), "r"), Loader=yaml.FullLoader
    )
    model_config = yaml.load(
        open(os.path.join(model_folder, default_args["model_config"]), "r"), Loader=yaml.FullLoader
    )
    train_config = yaml.load(
        open(os.path.join(model_folder, default_args["train_config"]), "r"), Loader=yaml.FullLoader
    )
    _repoint_legacy_fastspeech2_config_paths(preprocess_config, train_config)
    CONFIGS = (preprocess_config, model_config, train_config)

    # Load model
    args = argparse.Namespace(restore_step=model_ckpt)
    TTS_MODEL, FLAUBERT_MODEL, FLAUBERT_TOKENIZER = get_model(args, CONFIGS, device, train=False, use_bert=model_config["styleTag_encoder"]["use_styleTag_encoder"])
    print("TTS {}/{} loaded".format(model_folder, model_ckpt))
    
def load_hifigan(vocoder_model, device):
    global VOCODER_PATH
    global VOCODER_MODEL
    global H
    global GENERATOR
    
    # Read Config
    model_folder = vocoder_model["folder"]
    model_ckpt = vocoder_model["checkpoint_file"]
    model_config_path = vocoder_model["config_path"]
    
    # Load Hifigan Config
    config_file = os.path.join(model_folder, model_config_path)
    with open(config_file) as f:
        data = f.read()
        
    json_config = json.loads(data)
    H = AttrDict(json_config)
    
    # Parameter Hifigan
    VOCODER_PATH = os.path.join(model_folder, model_ckpt)
    
    # Load model
    VOCODER_MODEL = torch.load(VOCODER_PATH, map_location=device, weights_only=False)
    GENERATOR = Generator(H).to(device)
    GENERATOR.load_state_dict(VOCODER_MODEL['generator'])
    GENERATOR.eval()
    GENERATOR.remove_weight_norm()
    print("Vocoder {}/{} loaded".format(model_folder, model_ckpt))
    
def load_waveglow(vocoder_model, device):
    global VOCODER_PATH
    global VOCODER_MODEL
    
    # Read Config
    model_folder = vocoder_model["folder"]
    model_ckpt = vocoder_model["checkpoint_file"]
    
    # Parameter Waveglow
    VOCODER_PATH = os.path.join(model_folder, model_ckpt)
    VOCODER_MODEL = torch.load(VOCODER_PATH, map_location=device, weights_only=False)['model']
    VOCODER_MODEL = VOCODER_MODEL.remove_weightnorm(VOCODER_MODEL)
    VOCODER_MODEL.eval()
    print("Vocoder {}/{} loaded".format(model_folder, model_ckpt))