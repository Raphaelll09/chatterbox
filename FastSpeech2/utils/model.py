import os
import json

import torch
import numpy as np

from model import FastSpeech2, ScheduledOptim

from transformers import FlaubertModel, FlaubertTokenizer

def get_model(args, configs, device, train=False, mode_batch=False, use_bert=False):
    (preprocess_config, model_config, train_config) = configs

    if use_bert:
        # Load FlauBERT pre-trained model
        modelname = './flaubert/flaubert_large_cased'

        print("Loading of FlauBERT")
        # Load pretrained model and tokenizer
        flaubert, log = FlaubertModel.from_pretrained(modelname, output_loading_info=True)
        flaubert_tokenizer = FlaubertTokenizer.from_pretrained(modelname, do_lowercase=True)
        print("FlauBERT loaded")

        flaubert.requires_grad_ = False
        flaubert_tokenizer.requires_grad_ = False
    else:
        flaubert = None
        flaubert_tokenizer = None

    model = FastSpeech2(preprocess_config, model_config, mode_batch).to(device)
    if args.restore_step:
        if mode_batch:
            config_train_path = train_config["path"]["ckpt_path_batch"]
        else:
            config_train_path = train_config["path"]["ckpt_path"]

        ckpt_path = os.path.join(
            config_train_path,
            "{}.pth.tar".format(args.restore_step),
        )
        ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model"], strict=False) # avoid error when not loading the BERT for styleTag

    if train:
        scheduled_optim = ScheduledOptim(
            model, train_config, model_config, args.restore_step
        )
        if args.restore_step:
            scheduled_optim.load_state_dict(ckpt["optimizer"])
        model.train()
        return model, scheduled_optim

    model.eval()
    # model.train()
    model.requires_grad_ = False
    return model, flaubert, flaubert_tokenizer

def get_param_num(model):
    num_param = sum(param.numel() for param in model.parameters())
    return num_param


def get_vocoder(config, device):
    name = config["vocoder"]["model"]
    speaker = config["vocoder"]["speaker"]

    if name == "MelGAN":
        if speaker == "LJSpeech":
            vocoder = torch.hub.load(
                "descriptinc/melgan-neurips", "load_melgan", "linda_johnson"
            )
        elif speaker == "universal":
            vocoder = torch.hub.load(
                "descriptinc/melgan-neurips", "load_melgan", "multi_speaker"
            )
        vocoder.mel2wav.eval()
        vocoder.mel2wav.to(device)
    elif name == "HiFi-GAN":
        with open("hifigan/config.json", "r") as f:
            config = json.load(f)
        config = hifigan.AttrDict(config)
        vocoder = hifigan.Generator(config)
        if speaker == "LJSpeech":
            ckpt = torch.load("hifigan/generator_LJSpeech.pth.tar")
        elif speaker == "universal":
            ckpt = torch.load("hifigan/generator_universal.pth.tar")
        vocoder.load_state_dict(ckpt["generator"])
        vocoder.eval()
        vocoder.remove_weight_norm()
        vocoder.to(device)

    return vocoder


def vocoder_infer(mels, vocoder, model_config, preprocess_config, lengths=None):
    name = model_config["vocoder"]["model"]
    with torch.no_grad():
        if name == "MelGAN":
            wavs = vocoder.inverse(mels / np.log(10))
        elif name == "HiFi-GAN":
            wavs = vocoder(mels).squeeze(1)

    wavs = (
        wavs.cpu().numpy()
        * preprocess_config["preprocessing"]["audio"]["max_wav_value"]
    ).astype("int16")
    wavs = [wav for wav in wavs]

    for i in range(len(mels)):
        if lengths is not None:
            wavs[i] = wavs[i][: lengths[i]]

    return wavs
