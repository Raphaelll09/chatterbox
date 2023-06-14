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

sys.path.insert(1, "./FastSpeech2")
from utils.model import get_model

sys.path.insert(1, "./hifi-gan-master")
from env import AttrDict
from models import Generator

sys.path.insert(1, "./Waveglow")

def load_fastspeech2(tts_model, device):
    global TTS_MODEL
    global CONFIGS
    
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
    CONFIGS = (preprocess_config, model_config, train_config)

    # Load model
    args = argparse.Namespace(restore_step=model_ckpt)
    TTS_MODEL = get_model(args, CONFIGS, device, train=False)
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
    VOCODER_MODEL = torch.load(VOCODER_PATH, map_location=device)
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
    VOCODER_MODEL = torch.load(VOCODER_PATH, map_location=device)['model']
    VOCODER_MODEL = VOCODER_MODEL.remove_weightnorm(VOCODER_MODEL)
    VOCODER_MODEL.eval()
    print("Vocoder {}/{} loaded".format(model_folder, model_ckpt))