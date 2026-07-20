#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Text-side of the FastSpeech2+HiFi-GAN backend: the inline control-tag mini-language
(<SPEAKER=...>, <STYLE=...>, {phonetic}, ...), pronunciation/punctuation cleanup, and the regex
rule files. Split out of synthesis_modules.py in Phase 3 (docs/REORG_PROPOSAL.md) -- these don't
touch the loaded model's *weights*, but parse_params_from_text() and preprocess_styleTag() do need
the loaded model's config/FlauBERT state, passed in explicitly by the caller (backend.py) rather
than fetched via getattr() off a globals module. Fixes two config-reopening leaks along the way
(see docs/REORG_PROPOSAL.md Sec5/Sec7): the original parse_params_from_text() re-read
preprocess.yaml from disk from scratch every time a <SPEAKER=...> tag was used, instead of reusing
the already-loaded config -- the exact same leak gui_utils.py:355 had for the GUI's speaker list.
"""
import os
import re
import json

import numpy as np

import chatterbox.config.paths as paths

regex_file = str(paths.CUSTOM_REGEX_RULES)
symbols_regex_file = str(paths.SYMBOLS_REGEX_RULES)
url_regex_file = str(paths.URL_REGEX_RULES)

# Rule files never change during a run -- parse each once and reuse, instead
# of re-opening/re-reading them on every synthesis call.
_symbols_regex_rules = None
_custom_regex_rules = None
_url_regex_rules = None
_speaker_list_cache = {}


def _get_symbols_regex_rules():
    global _symbols_regex_rules
    if _symbols_regex_rules is None:
        with open(symbols_regex_file, encoding="utf-8") as f:
            _symbols_regex_rules = [line.strip().rsplit("|", 1) for line in f]
    return _symbols_regex_rules


def _get_custom_regex_rules():
    global _custom_regex_rules
    if _custom_regex_rules is None:
        with open(regex_file, encoding="utf-8") as f:
            _custom_regex_rules = [line.strip().split("|") for line in f]
    return _custom_regex_rules


def _get_url_regex_rules():
    global _url_regex_rules
    if _url_regex_rules is None:
        with open(url_regex_file, encoding="utf-8") as f:
            _url_regex_rules = [line.strip().rsplit("|", 1) for line in f]
    return _url_regex_rules


def get_speaker_list(speakers_location):
    """Public (was _get_speaker_list) -- now called across module boundaries by backend.py's
    describe_controls(), not just from within this file."""
    if speakers_location not in _speaker_list_cache:
        with open(speakers_location, "r") as f:
            _speaker_list_cache[speakers_location] = json.load(f)
    return _speaker_list_cache[speakers_location]


def parse_params_from_text(text, tts_config, configs):
    """configs is the (preprocess_config, model_config, train_config) tuple the backend already
    has loaded -- passed in explicitly so a <SPEAKER=name> tag resolves against the already-loaded
    config instead of re-reading preprocess.yaml from disk on every call (the leak fixed in
    Phase 3, see the module docstring)."""
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
        speakers_location = os.path.join(configs[0]['path']['preprocessed_path'], "speakers.json")
        speaker_list = get_speaker_list(speakers_location)

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

    # Normalize "smart" apostrophes to the straight one the model's symbol set expects
    # (FastSpeech2/text/symbols.py's _punctuation only has U+0027) -- a direct substitution,
    # not routed through symbols_regex_rules.csv, since that loop pads replacements with
    # spaces and would break elisions like "qu'il" into "qu ' il".
    text_to_syn = text_to_syn.replace("’", "'").replace("‘", "'")

    # Spell url and mail
    text_to_syn = re.sub(r"(https?\:[^ \,]+)", do_adr, text_to_syn, flags=re.IGNORECASE) # url https?
    text_to_syn = re.sub(r"(www.[^ \,]+)", do_adr, text_to_syn, flags=re.IGNORECASE) # url www.
    text_to_syn = re.sub(r"([^ \@]+\@[\w\d]+\.[^ \,]+)", do_adr, text_to_syn, flags=re.IGNORECASE) # mail

    # Symbols are replace regardless of their surrounding
    for parts in _get_symbols_regex_rules():
        text_to_syn = re.sub(parts[0], " {} ".format(parts[1]), text_to_syn, flags=re.IGNORECASE)

    # other regex are replaced only as isolated words
    for parts in _get_custom_regex_rules():
        ortho = '([ \"\',?;.:!§\\(\\)\\[\\]])(' + parts[0] + ')([ \"\',?;.:!§\\(\\)\\[\\]])' # \p{P} does not seem to work
        phonetic = r'\1{}\3'.format(parts[1])

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

    for parts in _get_url_regex_rules():
        url = re.sub(parts[0], " {} ".format(parts[1]), url, flags=re.IGNORECASE)

    return f"{url}"


def preprocess_styleTag(styleTags, use_styleTag_encoder, flaubert_model, flaubert_tokenizer):
    """flaubert_model/flaubert_tokenizer are the backend's already-loaded instances, passed in
    explicitly instead of fetched via getattr(loading_modules, ...) (pre-Phase-3 pattern)."""
    if styleTags == '':
        return None

    # output format: adjectif1,adjectif2,...
    split_styleTags = styleTags.split(',')

    # Strip spaces from each element and join them back together
    trimmed_styleTag = ','.join([styleTag.strip() for styleTag in split_styleTags])

    if use_styleTag_encoder:
        from dataset import load_free_styleTags_embedding
        return np.array([load_free_styleTags_embedding(trimmed_styleTag, flaubert_model, flaubert_tokenizer)])
    else:
        print("StyleTag Encoder not supported by this model.")
        return None
