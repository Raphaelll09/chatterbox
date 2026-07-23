#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piper-side text preprocessing.

Deliberately does NOT call text_pipeline.parse_params_from_text() for tag parsing, even though
that function's STYLE/STYLE_INTENSITY/STYLE_TAG handling would have been reusable as-is (no
FS2-specific config dependency there) -- its SPEAKER=... branch requires the (preprocess_config,
model_config, train_config) tuple FastSpeech2 loads (to resolve a name against FS2's own
speakers.json), which Piper doesn't have and shouldn't fake. Piper voices carry their own,
differently-shaped per-voice speaker map (PiperVoice.config.speaker_id_map -- confirmed live on
the Pi during Phase B: {} for single-speaker siwis/tom, {"jessica": 0, "pierre": 1} for upmc), so
_parse_tags() below re-implements just the same bracket-scanning shape (up to 4 tags, same
SPEAKER=/STYLE=/STYLE_INTENSITY=/STYLE_TAG= substring syntax users already know from the FS2 path)
against that instead.

text_pipeline.trim_punctuation_mistakes() is reused unconditionally below -- genuinely orthographic
whitespace/punctuation cleanup, confirmed safe by reading it. text_pipeline.parse_pronunciation_
mistakes() is NOT safe to reuse unconditionally, despite the substitution *mechanism* (regex
replace) being generic: confirmed live during Phase B that the *data* it substitutes in
(custom_regex_rules.csv, url_regex_rules.csv, and part of symbols_regex_rules.csv) is heavily
laden with FS2's own "{phonetic}" bracket syntax -- e.g. every single url_regex_rules.csv entry,
and custom_regex_rules.csv's "test|{t e^ s t}" turning the word "test" into literal
"{t e^ s t}" in the output text. Piper's own espeak-ng-based phonemizer has no notion of that
syntax and would mispronounce the literal braces/phone-codes as French orthography, not skip or
interpret them -- a silent quality bug, not a crash, which is why it wasn't caught by inspecting
the function's code alone (the regex-substitution *shape* is fine; the substituted *values*
aren't). apply_custom_regex_rules therefore defaults to **False** in config_tts.yaml's Piper
entries (opt-in only, for the A/B comparison cc_prompt_piper_backend.md's B.3 step 2 actually
wants -- "whether the custom regex rules help or hurt Piper" -- not a safe-by-default cleanup
pass).
"""
import logging

import chatterbox.synthesis.backends.fastspeech2_hifigan.text_pipeline as text_pipeline

logger = logging.getLogger(__name__)


def _parse_tags(text):
    """Strips up to 4 <TAG=value[;TAG=value]> blocks from text, same syntax as
    text_pipeline.parse_params_from_text() (mirrored deliberately, see module docstring -- not the
    FS2-only "bare <STYLE_NAME>" shorthand, which has no meaning for Piper's empty gst_token_list).
    Returns (clean_text, speaker_name, style, style_intensity, style_tag) -- style/style_intensity/
    style_tag are always just logged-and-discarded by prepare() below, never applied."""
    speaker = None
    style = None
    style_intensity = None
    style_tag = None

    for _ in range(4):
        open_bracket = text.find('<')
        close_bracket = text.find('>')
        if open_bracket < 0 or close_bracket < 0:
            break

        index_semicolon = text.find(';', open_bracket, close_bracket)
        index_speaker = text.find('SPEAKER=', open_bracket, close_bracket)
        index_style = text.find('STYLE=', open_bracket, close_bracket)
        index_style_intensity = text.find('STYLE_INTENSITY=', open_bracket, close_bracket)
        index_style_tag = text.find('STYLE_TAG=', open_bracket, close_bracket)

        if index_speaker >= 0:
            end = index_semicolon if index_semicolon > index_speaker else close_bracket
            speaker = text[index_speaker + 8:end].strip()
        if index_style >= 0:
            end = index_semicolon if index_semicolon > index_style else close_bracket
            style = text[index_style + 6:end].strip()
        if index_style_intensity >= 0:
            end = index_semicolon if index_semicolon > index_style_intensity else close_bracket
            style_intensity = text[index_style_intensity + 16:end].strip()
        if index_style_tag >= 0:
            end = index_semicolon if index_semicolon > index_style_tag else close_bracket
            style_tag = text[index_style_tag + 10:end].strip()

        text = (text[:open_bracket] + text[close_bracket + 1:]).strip()

    return text, speaker, style, style_intensity, style_tag


def prepare(text_to_syn, tts_config, gui_control, active_voice):
    """Returns (clean_text, speaker_id) ready for PiperVoice.synthesize_wav().

    active_voice is the loaded PiperVoice whose .config.speaker_id_map (possibly empty, for a
    single-speaker voice) resolves any <SPEAKER=...> tag or the GUI's speaker chip/dropdown
    selection. speaker_id falls back to active_voice.config.default_speaker_id when neither is
    present -- SynthesisConfig itself also defaults speaker_id to None, which piper-tts then reads
    as "use the model's own default", so this fallback is a documentation aid, not load-bearing.
    """
    text_to_syn, speaker_name, style, style_intensity, style_tag = _parse_tags(text_to_syn)

    for tag_name, value in (("STYLE", style), ("STYLE_INTENSITY", style_intensity),
                             ("STYLE_TAG", style_tag)):
        if value is not None:
            logger.debug("Piper: discarding %s=%r tag (not supported by this backend)",
                         tag_name, value)

    speaker_map = active_voice.config.speaker_id_map
    speaker_id = active_voice.config.default_speaker_id

    if gui_control is not None and "speaker" in gui_control and speaker_map:
        speaker_id = gui_control["speaker"]

    if speaker_name is not None:
        if speaker_map and speaker_name in speaker_map:
            speaker_id = speaker_map[speaker_name]
        else:
            logger.debug("Piper: <SPEAKER=%s> not found in this voice's speaker map, ignoring",
                         speaker_name)

    # Opt-in, default False -- see module docstring: parse_pronunciation_mistakes() can inject
    # FS2's "{phonetic}" bracket syntax (custom_regex_rules.csv/url_regex_rules.csv), which
    # Piper's phonemizer would mispronounce as literal text. trim_punctuation_mistakes() alone is
    # always safe (plain whitespace/punctuation cleanup, confirmed by reading it) and always runs.
    if tts_config["default_args"].get("apply_custom_regex_rules", False):
        text_to_syn = text_pipeline.parse_pronunciation_mistakes(text_to_syn)
    text_to_syn = text_pipeline.trim_punctuation_mistakes(text_to_syn)

    return text_to_syn, speaker_id
