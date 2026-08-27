#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piper-side text preprocessing.

Deliberately does NOT call text_pipeline.parse_params_from_text() for tag parsing, even though
that function's STYLE/STYLE_INTENSITY/STYLE_TAG handling would have been reusable as-is (no
FS2-specific config dependency there) -- its SPEAKER=... branch requires the (preprocess_config,
model_config, train_config) tuple FastSpeech2 loads (to resolve a name against FS2's own
speakers.json), which Piper doesn't have and shouldn't fake. Piper voices carry their own,
differently-shaped per-voice speaker map (PiperVoice.config.speaker_id_map -- confirmed live on
the Pi during Phase B: {} for single-speaker siwis, {"jessica": 0, "pierre": 1} for upmc), so
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


def prepare(text_to_syn, tts_config):
    """Returns (clean_text, tag_speaker_name) -- text cleanup plus whatever <SPEAKER=...> tag name
    was found (or None), ready for PiperBackend._resolve_speaker() (backend.py) to resolve against
    either the new multi-checkpoint speakers: list or the legacy per-voice speaker_id_map. Speaker
    resolution itself moved to backend.py (interchangeable-backend GUI refactor, Piper voice
    unification) since it now needs `self` to swap self._active_voice across checkpoints -- this
    function stays a pure text transform with no backend-instance state."""
    text_to_syn, speaker_name, style, style_intensity, style_tag = _parse_tags(text_to_syn)

    for tag_name, value in (("STYLE", style), ("STYLE_INTENSITY", style_intensity),
                             ("STYLE_TAG", style_tag)):
        if value is not None:
            logger.debug("Piper: discarding %s=%r tag (not supported by this backend)",
                         tag_name, value)

    # Opt-in, default False -- see module docstring: parse_pronunciation_mistakes() can inject
    # FS2's "{phonetic}" bracket syntax (custom_regex_rules.csv/url_regex_rules.csv), which
    # Piper's phonemizer would mispronounce as literal text. trim_punctuation_mistakes() alone is
    # always safe (plain whitespace/punctuation cleanup, confirmed by reading it) and always runs.
    if tts_config["default_args"].get("apply_custom_regex_rules", False):
        text_to_syn = text_pipeline.parse_pronunciation_mistakes(text_to_syn)
    text_to_syn = text_pipeline.trim_punctuation_mistakes(text_to_syn)

    # NOTE: this used to also prepend ". " here for default_args.prepend_leading_pause (English
    # Piper's "first word is always mispronounced" report) -- confirmed a complete no-op (piper-
    # tts's bundled espeak-ng silently discards a bare leading "." with nothing before it), and a
    # follow-up fix attempt in backend.py (priming with a real leading word, then cropping it back
    # off) was also abandoned after real statistical testing showed it made things worse, not
    # better. See docs/research/CHANGELOG.md's 2026-08-20 entries and backend.py's own module
    # comment for the full investigation -- no working fix exists yet, this function stays a pure
    # text transform with nothing prepended.
    return text_to_syn, speaker_name
