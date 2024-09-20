#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jul 21 15:40:09 2022

@author: lengletm
"""

import os
import numpy as np
import argparse
import sys
import yaml
import json
import re

import loading_modules
from scipy.io import loadmat
from tqdm import tqdm

#sys.path.insert(1, "./FastSpeech2")
from synthesize import synthesize
from text import text_to_sequence
from dataset import load_free_styleTags_embedding

#sys.path.insert(1, "./hifi-gan-master")
from inference_e2e import inference

sys.path.insert(1, './Waveglow/tacotron2')
from inference import main as inference_main

audio_file_name = "audio_file"
regex_file = "custom_regex_rules.csv"
symbols_regex_file = "symbols_regex_rules.csv"
url_regex_file = "url_regex_rules.csv"

def tts(text_to_syn, tts_config, gui_control, linking_utt):
    syn_script = tts_config['syn_script']
    
    # Get pre-loaded model
    loaded_tts_model = getattr(loading_modules, "TTS_MODEL")

    # Parse Style and Speaker From Text if provided
    (text_to_syn, speaker_index, style_index, style_intensity, styleTag) = parse_params_from_text(text_to_syn, tts_config)
    text_tags = [speaker_index, style_index, style_intensity, styleTag]

    # Parse common pronunciation mistakes
    text_to_syn = parse_pronunciation_mistakes(text_to_syn)

    # Trim spaces before punctuation marks to make it match training
    text_to_syn = trim_punctuation_mistakes(text_to_syn)
    
    print('Input after pre-processing: "{}"'.format(text_to_syn))
    
    # Generate Mel
    output_location = globals()[syn_script](tts_config, loaded_tts_model, text_to_syn, gui_control, text_tags, linking_utt)
    
    return output_location, text_to_syn

def vocoder(location_mel_file, vocoder_config):
    syn_script = vocoder_config['syn_script']
    
    # Get pre-loaded model
    loaded_vocoder_model = getattr(loading_modules, "VOCODER_MODEL")
    
    # Generate Wav
    output_location = globals()[syn_script](vocoder_config, loaded_vocoder_model, location_mel_file)
    
    return output_location
    
def syn_fastspeech2(tts_config, loaded_tts_model, text_to_syn, gui_control, text_tags, linking_utt):
    # Read FastSpeech2 Config
    model_folder = tts_config["folder"]
    output_location = tts_config["output_location"]
    args = tts_config["default_args"].copy()
    nbr_gst_tokens = len([*tts_config["gst_token_list"]])

    if not (gui_control is None):
        args['speaker_id'] = gui_control[0]
        args['pitch_control'] = gui_control[1]
        args['energy_control'] = gui_control[2]
        args['duration_control'] = gui_control[3]
        args['pitch_control_bias'] = gui_control[4]
        args['energy_control_bias'] = gui_control[5]
        args['duration_control_bias'] = gui_control[6]
        args['pause_control_bias'] = gui_control[7]
        args['liaison_control_bias'] = gui_control[8]
        args['gst_token_index'] = gui_control[9]
        args['style_intensity'] = gui_control[10]
        styleTag = gui_control[11]

    pitch_control = args["pitch_control"]
    energy_control = args["energy_control"]
    duration_control = args["duration_control"]
    control_values = pitch_control, energy_control, duration_control
    
    control_bias_array = [
        args["duration_control_bias"],
        args["pitch_control_bias"],
        args["f1_control_bias"],
        args["f2_control_bias"],
        args["f3_control_bias"],
        args["spectral_tilt_control_bias"],
        args["energy_control_bias"],
        args["relative_pos_control_bias"],
        args["pfitzinger_control_bias"],
        args["cog_control_bias"],
        args["sb1k_control_bias"],
    ]

    # Contest with text-tags
    [speaker_index, style_index, style_intensity, styleTag_from_text] = text_tags
    if speaker_index is not None:
        args['speaker_id'] = speaker_index
    if style_index is not None:
        args['gst_token_index'] = style_index

    if style_intensity is not None:
        args['style_intensity'] = style_intensity
    elif gui_control is None:
        args['style_intensity'] = list(tts_config["gst_token_list"].values())[args['gst_token_index']]

    # Get preloaded parameters
    configs = getattr(loading_modules, "CONFIGS")

    # Handling StyleTag
    if styleTag_from_text is not None:
        styleTag = styleTag_from_text
    styleTag_emb = preprocess_styleTag(styleTag, use_styleTag_encoder=configs[1]["styleTag_encoder"]["use_styleTag_encoder"])

    if args["silence_control_bias"]:
        rounded_silence_proportion = round(18.98 * args["duration_control_bias"] - 12.01) # from GT distribution
        rounded_silence_proportion = min(rounded_silence_proportion, 100)
        rounded_silence_proportion = max(rounded_silence_proportion, 0)
        load_ablation = loadmat(configs[1]["bias_vector"]["ablation_silence_proportion"])
        args['pause_control_bias'] = load_ablation['ablation_silence_proportion'][rounded_silence_proportion]

    
    categorical_control_bias_array = [
        args["pause_control_bias"],
        args["liaison_control_bias"],
    ]

    # Handle multiple syn
    configs[1]["inter_utterance_punctuation"]["enforce_duration"] = args["enforce_linking_duration"] and linking_utt
    
    # Single Utt processing
    id_audio_file = [audio_file_name]
    raw_texts = [text_to_syn]
    speakers = np.array([args["speaker_id"]])
    texts = np.array([np.array(np.array(text_to_sequence(text_to_syn, args["text_cleaners"])))])
    text_lens = np.array([len(texts[0])])
    phon_align = -1*np.ones([1,len(texts[0])])
    emotion_weights = np.zeros(nbr_gst_tokens)

    # emotion_weights[args["gst_token_index"]] = 1
    emotion_weights[args["gst_token_index"]] += args['style_intensity']
    emotion_weights[nbr_gst_tokens-1] += 1.0 - args['style_intensity']
    emotion_weights[nbr_gst_tokens-1] = max(emotion_weights[nbr_gst_tokens-1], 0.0)

    batchs = [(id_audio_file, raw_texts, speakers, texts, text_lens, max(text_lens), phon_align, np.array([emotion_weights]), styleTag_emb)]

    # Logs synthesis infos
    speakers_location = os.path.join(configs[0]['path']['preprocessed_path'], "speakers.json")
    with open(speakers_location, "r") as f:
        speaker_list = json.load(f)

    print('Speaker: "{}", Style: "{}", Style intensity: "{}"'.format(
        list(speaker_list.keys())[args['speaker_id']], 
        list(tts_config["gst_token_list"].keys())[args['gst_token_index']], 
        args['style_intensity']
    ))
    print("StyleTag: {}".format(styleTag))
    
    synthesize(
        loaded_tts_model, 
        tts_config["checkpoint_file"], 
        configs, 
        args["vocoder"], 
        batchs, 
        control_values, 
        control_bias_array,
        categorical_control_bias_array,
    )
    
    return os.path.join(model_folder, output_location)

def syn_hifigan(vocoder_config, loaded_vocoder_model, location_mel_file):
    # Read HifiGan Config
    output_location = vocoder_config["output_location"]
    vocoder_args = argparse.Namespace(
        checkpoint_file=vocoder_config["checkpoint_file"],
        output_dir=output_location,
        input_mels_dir=location_mel_file,
    )
    
    # Get preloaded parameters
    h = getattr(loading_modules, "H")
    generator = getattr(loading_modules, "GENERATOR")
    
    inference(
        vocoder_args,
        loaded_vocoder_model,
        h,
        generator,
    )
    
    return os.path.join(output_location, audio_file_name)

def syn_waveglow(vocoder_config, loaded_vocoder_model, location_mel_file):
    # Read Waveglow Config
    vocoder_folder = vocoder_config["folder"]
    output_location = vocoder_config["output_location"]
    default_args = vocoder_config["default_args"]
    filelist_path = default_args["filelist_path"]
    
    # Write .txt to generate Wav files
    cmd = "ls {}/*.WAVEGLOW > {}/{}".format(location_mel_file, vocoder_folder, filelist_path)
    os.system(cmd)
    
    inference_main(
        os.path.join(vocoder_folder, filelist_path), 
        loaded_vocoder_model, 
        default_args["sigma"], 
        vocoder_config["output_location"],
        default_args["sampling_rate"], 
        default_args["is_fp16"], 
        default_args["denoiser_strengh"], 
        default_args["speed_factor"], 
        default_args["gain"], 
        default_args["negative_gain"],
    )
    
    return os.path.join(output_location, audio_file_name)

def parse_params_from_text(text, tts_config):
    style = None
    speaker = None
    style_intensity = None
    styleTag = None

    open_bracket = -1
    close_bracket = -1

    for _ in range(4):
        open_bracket = text.find('<')
        close_bracket = text.find('>')

        if open_bracket >= 0 and close_bracket >= 0:
            index_comma = text.find(';', open_bracket, close_bracket)
            index_speaker = text.find('SPEAKER=', open_bracket, close_bracket)
            index_style = text.find('STYLE=', open_bracket, close_bracket)
            index_style_intensity = text.find('STYLE_INTENSITY=', open_bracket, close_bracket)
            index_style_tag = text.find('STYLE_TAG=', open_bracket, close_bracket)

            if index_speaker >= 0:
                if index_comma>index_speaker:
                    speaker = text[index_speaker+8:index_comma].strip()
                else:
                    speaker = text[index_speaker+8:close_bracket].strip()

            if index_style >= 0:
                if index_comma>index_style:
                    style = text[index_style+6:index_comma].strip()
                else:
                    style = text[index_style+6:close_bracket].strip()

            if index_style_intensity >= 0:
                if index_comma>index_style_intensity:
                    style_intensity = text[index_style_intensity+16:index_comma].strip()
                else:
                    style_intensity = text[index_style_intensity+16:close_bracket].strip()

            if index_style_tag >= 0:
                if index_comma>index_style_tag:
                    styleTag = text[index_style_tag+10:index_comma].strip()
                else:
                    styleTag = text[index_style_tag+10:close_bracket].strip()

            # Short Version for style control
            if index_speaker == -1 and index_style == -1 and index_style_intensity == -1:
                style = text[open_bracket+1:close_bracket].strip()

            text = (text[:open_bracket] + text[close_bracket+1:]).strip()

    # Find indexes for Speaker and Style if found
    if style is not None:
        style_list = [*tts_config["gst_token_list"]]

        try:
            style_index = style_list.index(style)
        except ValueError:
            print("Le STYLE '{}' n'existe pas.".format(style))
            style_index = None
    else:
        style_index = None

    if speaker is not None:
        preprocess_config = yaml.load(
            open(os.path.join(tts_config['folder'], tts_config["default_args"]["preprocess_config"]), "r"), Loader=yaml.FullLoader
        )
        speakers_location = os.path.join(preprocess_config['path']['preprocessed_path'], "speakers.json")
        with open(speakers_location, "r") as f:
            speaker_list = json.load(f)

        try:
            speaker_index = speaker_list[speaker]
        except KeyError:
            print("Le Locuteur '{}' n'existe pas.".format(speaker))
            speaker_index = None
    else:
        speaker_index = None

    if style_intensity is not None:
        style_intensity = float(style_intensity)

    # StyleTag are processed latter no trimming here

    return (text, speaker_index, style_index, style_intensity, styleTag)

def parse_pronunciation_mistakes(text_to_syn):

    # Spell url and mail
    text_to_syn = re.sub("(https?\:[^ \,]+)", do_adr, text_to_syn, flags=re.IGNORECASE) # url https?
    text_to_syn = re.sub("(www.[^ \,]+)", do_adr, text_to_syn, flags=re.IGNORECASE) # url www.
    text_to_syn = re.sub("([^ \@]+\@[\w\d]+\.[^ \,]+)", do_adr, text_to_syn, flags=re.IGNORECASE) # mail

    # Symbols are replace regardless of their surrounding
    with open(symbols_regex_file, encoding="utf-8") as f:
        for line in tqdm(f):
            parts = line.strip().rsplit("|", 1)
            text_to_syn = re.sub(parts[0], " {} ".format(parts[1]), text_to_syn, flags=re.IGNORECASE)

    # other regex are replaced only as isolated words
    with open(regex_file, encoding="utf-8") as f:
        for line in tqdm(f):
            parts = line.strip().split("|")
            
            ortho = '([ \"\',?;.:!§\(\)\[\]])(' + parts[0] + ')([ \"\',?;.:!§\(\)\[\]])' # \p{P} does not seem to work
            phonetic = '\\1{}\\3'.format(parts[1])

            text_to_syn = re.sub(ortho, phonetic, text_to_syn, flags=re.IGNORECASE)
    return text_to_syn

def trim_punctuation_mistakes(text_to_syn):
    # Trim start and end spaces
    text_to_syn = text_to_syn.strip(' ')
    # Avoid multiple spaces
    text_to_syn = re.sub(' {2,}', ' ', text_to_syn)

    punctuation_to_correct = np.array([
        (' ?', '?'),
        (' !', '!'),
        (' :', ':'),
        (' ;', ';'),
        ('§ ', '§'),
    ])
    for pattern in punctuation_to_correct:
        old = pattern[0]
        new = pattern[1]
        text_to_syn = text_to_syn.replace(old, new)

    return text_to_syn

def do_adr(match):         
    url = match.group(0)

    with open(url_regex_file, encoding="utf-8") as f:
        for line in tqdm(f):
            parts = line.strip().rsplit("|", 1)
            url = re.sub(parts[0], " {} ".format(parts[1]), url, flags=re.IGNORECASE)

    return f"{url}"

def preprocess_styleTag(styleTags, use_styleTag_encoder):
    if styleTags == '':
        return None

    # output format: adjectif1,adjectif2,...
    split_styleTags = styleTags.split(',')

    # Strip spaces from each element and join them back together
    trimmed_styleTag = ','.join([styleTag.strip() for styleTag in split_styleTags])

    if use_styleTag_encoder:
        # Get pre-loaded FlauBERT model
        loaded_flauBERT_model = getattr(loading_modules, "FLAUBERT_MODEL")
        loaded_flauBERT_tokenizer = getattr(loading_modules, "FLAUBERT_TOKENIZER")

        return np.array([load_free_styleTags_embedding(trimmed_styleTag, loaded_flauBERT_model, loaded_flauBERT_tokenizer)])
    else:
        print("StyleTag Encoder not supported by this model.")
        return None