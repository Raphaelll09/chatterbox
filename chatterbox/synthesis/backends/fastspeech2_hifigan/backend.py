#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FastSpeech2 + HiFi-GAN (+ optional Waveglow) backend.

Converted from loading_modules.py + synthesis_modules.py's model-loading/model-calling functions
in Phase 3 (docs/REORG_PROPOSAL.md). Owns loaded model state as instance attributes instead of
module-level globals (loading_modules.py's pre-Phase-3 design, documented in
docs/context/ARCHITECTURE.md "Global-state loading pattern") -- see
chatterbox/synthesis/base.py's docstring for why this class doesn't literally subclass
Synthesizer/VocoderBackend. Keeps its pre-Phase-3 method names (load_fastspeech2/load_hifigan/
load_waveglow/tts/vocoder/syn_fastspeech2/syn_hifigan/syn_waveglow) so config_tts.yaml's
load_script/syn_script string-based dispatch (getattr(registry.BACKEND, name)) needs zero changes.
"""
import os
import sys
import json
import argparse

import numpy as np
import torch
import yaml
from scipy.io import loadmat

import chatterbox.config.paths as paths
import tools.monitoring.profiling as profiling
from chatterbox.synthesis.backends.fastspeech2_hifigan import text_pipeline

sys.path.insert(1, str(paths.FASTSPEECH2_DIR))
from utils.model import get_model
from text import text_to_sequence
from synthesize import synthesize

sys.path.insert(1, str(paths.HIFIGAN_DIR))
from env import AttrDict
from models import Generator
from inference_e2e import inference

sys.path.insert(1, str(paths.WAVEGLOW_DIR))
sys.path.insert(1, str(paths.WAVEGLOW_DIR / "tacotron2"))
from inference import main as inference_main

AUDIO_FILE_NAME = "audio_file"

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


class FastSpeech2HifiGanBackend:
    """One instance holds one loaded (acoustic model, vocoder) pair -- see
    docs/context/ARCHITECTURE.md: models are swapped from disk files, never held resident as
    multiple simultaneous instances, so a single shared instance (chatterbox.synthesis.registry.
    BACKEND) is the right granularity, matching the pre-Phase-3 module-globals design it replaces.
    """

    def __init__(self):
        self.tts_model = None
        self.tts_model_config = None
        self.configs = None
        self.flaubert_model = None
        self.flaubert_tokenizer = None
        self.vocoder_path = None
        self.vocoder_model = None
        self.h = None
        self.generator = None

    # ---- Loading (was loading_modules.py) --------------------------------

    def load_fastspeech2(self, tts_model, device):
        # Kept for describe_controls() below (interchangeable-backend GUI refactor) -- the config_
        # tts.yaml model entry itself, not just the parsed FastSpeech2 preprocess/model/train
        # configs self.configs already holds.
        self.tts_model_config = tts_model

        model_folder = tts_model["folder"]
        default_args = tts_model["default_args"]
        model_ckpt = tts_model["checkpoint_file"]

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
        self.configs = (preprocess_config, model_config, train_config)

        args = argparse.Namespace(restore_step=model_ckpt)
        self.tts_model, self.flaubert_model, self.flaubert_tokenizer = get_model(
            args, self.configs, device, train=False,
            use_bert=model_config["styleTag_encoder"]["use_styleTag_encoder"],
        )
        print("TTS {}/{} loaded".format(model_folder, model_ckpt))

    def load_hifigan(self, vocoder_model, device):
        model_folder = vocoder_model["folder"]
        model_ckpt = vocoder_model["checkpoint_file"]
        model_config_path = vocoder_model["config_path"]

        config_file = os.path.join(model_folder, model_config_path)
        with open(config_file) as f:
            data = f.read()

        json_config = json.loads(data)
        self.h = AttrDict(json_config)

        self.vocoder_path = os.path.join(model_folder, model_ckpt)

        self.vocoder_model = torch.load(self.vocoder_path, map_location=device, weights_only=False)
        self.generator = Generator(self.h).to(device)
        self.generator.load_state_dict(self.vocoder_model['generator'])
        self.generator.eval()
        self.generator.remove_weight_norm()
        print("Vocoder {}/{} loaded".format(model_folder, model_ckpt))

    def load_waveglow(self, vocoder_model, device):
        model_folder = vocoder_model["folder"]
        model_ckpt = vocoder_model["checkpoint_file"]

        self.vocoder_path = os.path.join(model_folder, model_ckpt)
        self.vocoder_model = torch.load(self.vocoder_path, map_location=device, weights_only=False)['model']
        self.vocoder_model = self.vocoder_model.remove_weightnorm(self.vocoder_model)
        self.vocoder_model.eval()
        print("Vocoder {}/{} loaded".format(model_folder, model_ckpt))

    # ---- Synthesis (was synthesis_modules.py) ----------------------------

    def tts(self, text_to_syn, tts_config, gui_control, linking_utt):
        syn_script = tts_config['syn_script']

        # Pre-loaded model
        loaded_tts_model = self.tts_model

        # Parse Style and Speaker From Text if provided
        (text_to_syn, speaker_index, style_index, style_intensity, styleTag) = text_pipeline.parse_params_from_text(
            text_to_syn, tts_config, self.configs
        )
        text_tags = [speaker_index, style_index, style_intensity, styleTag]

        # Parse common pronunciation mistakes
        text_to_syn = text_pipeline.parse_pronunciation_mistakes(text_to_syn)

        # Trim spaces before punctuation marks to make it match training
        text_to_syn = text_pipeline.trim_punctuation_mistakes(text_to_syn)

        print('Input after pre-processing: "{}"'.format(text_to_syn))

        # Generate Mel
        output_location = getattr(self, syn_script)(tts_config, loaded_tts_model, text_to_syn, gui_control, text_tags, linking_utt)

        return output_location, text_to_syn

    def vocoder(self, location_mel_file, vocoder_config):
        syn_script = vocoder_config['syn_script']

        # Pre-loaded model
        loaded_vocoder_model = self.vocoder_model

        # Generate Wav
        output_location = getattr(self, syn_script)(vocoder_config, loaded_vocoder_model, location_mel_file)

        return output_location

    def syn_fastspeech2(self, tts_config, loaded_tts_model, text_to_syn, gui_control, text_tags, linking_utt):
        # Read FastSpeech2 Config
        model_folder = tts_config["folder"]
        output_location = tts_config["output_location"]
        args = tts_config["default_args"].copy()
        nbr_gst_tokens = len([*tts_config["gst_token_list"]])

        # Default: empty styleTag → preprocess_styleTag returns None → model uses
        # inference_gst_token_vector (the GUI-selected emotion token).
        styleTag = ""

        if not (gui_control is None):
            # gui_control is a dict keyed by the same "key"s describe_controls() declares below
            # (interchangeable-backend GUI refactor -- was a fixed 12-element positional list,
            # too fragile for a different backend to conform to; see docs/context/CHANGELOG.md).
            # .get(key, <yaml default>) so a control describe_controls() doesn't declare (e.g. a
            # differently-configured model that hides style entirely) falls back to this model's
            # own configured default instead of a KeyError -- matches today's actual behavior,
            # where a hidden-but-still-created slider/entry contributes its default value.
            args['speaker_id'] = gui_control.get('speaker', args['speaker_id'])
            args['pitch_control'] = gui_control.get('pitch', args['pitch_control'])
            args['energy_control'] = gui_control.get('energy', args['energy_control'])
            args['duration_control'] = gui_control.get('speed', args['duration_control'])
            args['pitch_control_bias'] = gui_control.get('pitch_bias', args['pitch_control_bias'])
            args['energy_control_bias'] = gui_control.get('energy_bias', args['energy_control_bias'])
            args['duration_control_bias'] = gui_control.get('speed_bias', args['duration_control_bias'])
            args['pause_control_bias'] = gui_control.get('pause_bias', args['pause_control_bias'])
            args['liaison_control_bias'] = gui_control.get('liaison_bias', args['liaison_control_bias'])
            args['gst_token_index'] = gui_control.get('style', args['gst_token_index'])
            args['style_intensity'] = gui_control.get('style_intensity', args['style_intensity'])
            styleTag = gui_control.get('style_tag', styleTag)

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
        configs = self.configs

        # Handling StyleTag: text tag takes priority; otherwise keep styleTag as-is.
        # When styleTag is "" (default or gui_styleTag_control=False), preprocess_styleTag
        # returns None and the model uses inference_gst_token_vector (GST emotion tokens).
        if styleTag_from_text is not None:
            styleTag = styleTag_from_text

        profiling_rec = profiling.current()
        with profiling_rec.stage("front_end"):
            styleTag_emb = text_pipeline.preprocess_styleTag(
                styleTag,
                use_styleTag_encoder=configs[1]["styleTag_encoder"]["use_styleTag_encoder"],
                flaubert_model=self.flaubert_model,
                flaubert_tokenizer=self.flaubert_tokenizer,
            )

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
        id_audio_file = [AUDIO_FILE_NAME]
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

        # text_lens[0] is the FastSpeech2 input SYMBOL sequence length, not a
        # true phoneme count: text_to_sequence() (FastSpeech2/text/__init__.py)
        # maps one symbol per character for ordinary orthographic text -- there's
        # no G2P front-end for French in this pipeline (see CLAUDE.md) - so this
        # was silently duplicating char_count under a misleading name (confirmed:
        # equal on every record). Only the opt-in {phonetic bracket} syntax
        # produces a token-per-phoneme sequence distinct from character count,
        # and there's no reliable way to tell from here whether a given input
        # used it. Report null rather than a sometimes-correct, sometimes-
        # duplicate number.
        profiling_rec.set(phoneme_count=None)

        # Logs synthesis infos
        speakers_location = os.path.join(configs[0]['path']['preprocessed_path'], "speakers.json")
        speaker_list = text_pipeline.get_speaker_list(speakers_location)

        print('Speaker: "{}", Style: "{}", Style intensity: "{}"'.format(
            list(speaker_list.keys())[args['speaker_id']],
            list(tts_config["gst_token_list"].keys())[args['gst_token_index']],
            args['style_intensity']
        ))
        print("StyleTag: {}".format(styleTag))

        with profiling_rec.stage("acoustic"):
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

    def syn_hifigan(self, vocoder_config, loaded_vocoder_model, location_mel_file):
        # Read HifiGan Config
        output_location = vocoder_config["output_location"]
        vocoder_args = argparse.Namespace(
            checkpoint_file=vocoder_config["checkpoint_file"],
            output_dir=output_location,
            input_mels_dir=location_mel_file,
        )

        # Get preloaded parameters
        h = self.h
        generator = self.generator

        inference(
            vocoder_args,
            loaded_vocoder_model,
            h,
            generator,
        )

        return os.path.join(output_location, AUDIO_FILE_NAME)

    def syn_waveglow(self, vocoder_config, loaded_vocoder_model, location_mel_file):
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

        return os.path.join(output_location, AUDIO_FILE_NAME)

    # ---- GUI support (new in Phase 3) ------------------------------------

    def describe_controls(self):
        """Speaker list read from the currently loaded model's preprocessed_path -- closes
        gui_utils.py:355's leak of re-opening the FastSpeech2 preprocess.yaml directly just to
        get this (docs/REORG_PROPOSAL.md Sec5).

        The "controls" list (interchangeable-backend GUI refactor -- see chatterbox/synthesis/
        base.py's describe_controls() docstring for the general shape) mirrors exactly what
        gui_fastspeech2() used to hand-build directly from config_tts.yaml: a style chip grid
        (with the unnamed TOKEN13-16 placeholders hidden behind an "advanced" toggle), a style-
        intensity slider, pitch/energy/speed sliders, 5 "bias" sliders grouped behind the same
        advanced toggle as gui_control_bias used to gate, and a free-text StyleTag entry. gui/
        app.py's gui_generic_controls() renders one widget per entry in order and collects values
        into a dict keyed by "key" -- syn_fastspeech2() above reads that same dict by key."""
        speakers_location = os.path.join(self.configs[0]['path']['preprocessed_path'], "speakers.json")
        tts_model = self.tts_model_config
        default_args = tts_model["default_args"]

        controls = []

        if tts_model.get("gui_style_control", True):
            controls.append({
                "type": "chip_grid", "key": "style", "label_key": "style_label",
                "options": [*tts_model["gst_token_list"]],
                "default": default_args["gst_token_index"],
                "hidden_pattern": r"^TOKEN\d+$",
            })
            controls.append({
                "type": "slider", "key": "style_intensity", "label_key": "style_intensity_label",
                "min": 0.0, "max": 1.0, "resolution": 0.05, "default": default_args["style_intensity"],
            })

        controls.append({"type": "slider", "key": "pitch", "label_key": "pitch_label",
                          "min": -15.0, "max": 15.0, "resolution": 1.0,
                          "default": default_args["pitch_control"]})
        controls.append({"type": "slider", "key": "energy", "label_key": "energy_label",
                          "min": -20.0, "max": 20.0, "resolution": 1.0,
                          "default": default_args["energy_control"]})
        controls.append({"type": "slider", "key": "speed", "label_key": "speed_label",
                          "min": 0.5, "max": 1.5, "resolution": 0.1,
                          "default": default_args["duration_control"]})

        gui_control_bias = tts_model.get("gui_control_bias", False)
        controls.append({"type": "slider", "key": "pitch_bias", "label_key": "pitch_bias_label",
                          "min": -6.0, "max": 6.0, "resolution": 0.5,
                          "default": default_args["pitch_control_bias"], "advanced": not gui_control_bias})
        controls.append({"type": "slider", "key": "energy_bias", "label_key": "energy_bias_label",
                          "min": -5.0, "max": 5.0, "resolution": 1.0,
                          "default": default_args["energy_control_bias"], "advanced": not gui_control_bias})
        controls.append({"type": "slider", "key": "speed_bias", "label_key": "speed_bias_label",
                          "min": 0.5, "max": 1.5, "resolution": 0.1,
                          "default": default_args["duration_control_bias"], "advanced": not gui_control_bias})
        controls.append({"type": "slider", "key": "pause_bias", "label_key": "pause_bias_label",
                          "min": -2.0, "max": 2.0, "resolution": 0.1,
                          "default": default_args["pause_control_bias"], "advanced": not gui_control_bias})
        controls.append({"type": "slider", "key": "liaison_bias", "label_key": "liaison_bias_label",
                          "min": -2.0, "max": 2.0, "resolution": 0.1,
                          "default": default_args["liaison_control_bias"], "advanced": not gui_control_bias})

        if tts_model.get("gui_styleTag_control", False):
            controls.append({"type": "text", "key": "style_tag", "label_key": "styletag_label"})

        return {
            "speaker_list": text_pipeline.get_speaker_list(speakers_location),
            "default_speaker": default_args["speaker_id"],
            "controls": controls,
        }
