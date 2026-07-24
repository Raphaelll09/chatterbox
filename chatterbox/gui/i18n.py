#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal string table (cc_prompt_gui_refactor.md Phase 1 item 10). The GUI's labels used to be a
hardcoded mix of French and English literals scattered across chatterbox/gui/app.py (e.g.
"Synthèse"/"Durée audio" next to "Speaker :"/"Pitch (semitones):") -- this module gives them one
consistent home instead.

"fr" and "en" are both populated (English Piper voice + live language menu, docs/context/
CHANGELOG.md) -- the app-bar's "Langue" entry is a real submenu built from config_tts.yaml's
GUI_config.languages, switching locale via set_locale() below and reloading the GUI window with
that language's default TTS model (chatterbox/gui/app.py's create_gui()/_run_gui_session()).
"""

_LOCALE = "fr"

STRINGS = {
    "fr": {
        "tts_label": "TTS :",
        "vocoder_label": "Vocodeur :",
        "synthesize_button": "Synthèse",
        # Shortened from "Texte à saisir" -- real-hardware feedback: in landscape, that label's
        # own (unweighted) column width left too little of the row's remaining width for the
        # Synthèse button, which rendered clipped ("nthè"). A shorter label leaves the weighted
        # entry/button columns more room.
        "input_text_label": "Saisie",
        "replay_button": "Rejouer",  # was "Lire" -- real-hardware feedback: ambiguous/redundant
                                     # with the keyboards' own "▶" play button, which
                                     # re-synthesizes; this button only replays the last audio.
        "put_away_button": "Mettre en veille",
        "settings_button": "Réglages",
        "speaker_label": "Locuteur :",
        "styletag_label": "StyleTag :",
        "style_label": "Style :",
        "advanced_styles_toggle": "Styles avancés",
        "advanced_controls_toggle": "Contrôles avancés",
        "style_intensity_label": "Intensité du style :",
        "pitch_label": "Hauteur (demi-tons) :",
        "energy_label": "Énergie (dB) :",
        # "Vitesse" is really a duration multiplier (FastSpeech2's own d_control -- model/modules.py:
        # predicted_duration = ... * d_control -- and Piper's length_scale share this same "higher
        # = slower" direction, confirmed by reading FS2's code, not assumed), which reads backwards
        # against the label's own name -- confirmed as real user confusion on Piper's slider
        # (docs/context/CHANGELOG.md: default 1.0 sounds normal, the slider's top end sounds
        # "super slow", easy to read as broken rather than just unlabeled direction). One shared
        # label fixes it for both backends without changing FS2's own behavior/values.
        "speed_label": "Vitesse (+ = plus lent) :",
        "pitch_bias_label": "Biais de hauteur (demi-tons) :",
        "energy_bias_label": "Biais d'énergie (dB) :",
        "speed_bias_label": "Biais de vitesse (coef) :",
        "pause_bias_label": "Biais de pause :",
        "liaison_bias_label": "Biais de liaison :",
        # Piper backend controls (chatterbox/synthesis/backends/piper/backend.py's
        # describe_controls()) -- length_scale reuses speed_label above, these two are new.
        "variability_label": "Variabilité :",
        "phoneme_duration_variability_label": "Variabilité de durée des phonèmes :",
        "audio_duration_label": "Durée audio : {duration:.3f}s",
        # One generic template for every AudioResult.stage_durations entry (interchangeable-
        # backend GUI refactor -- replaces the old tts_duration_label/vocoder_duration_label/
        # denoiser_duration_label, which were textually identical except the stage name) --
        # {name} is the stage's display name (app.py's _STAGE_DISPLAY_NAMES, "TTS"/"Vocodeur"/
        # "Denoiser" today, falling back to the raw stage key for one a future backend adds).
        "stage_duration_label": "Durée {name} : {duration:.3f}s | {percent:.0f}% de la durée audio",
        "synthesis_duration_label": "Durée Totale Synthèse : {duration:.3f}s | {percent:.0f}% de la durée audio",
        "error_label": "Erreur : {error}",
        "gst_weights_title": "\nPoids GST\n",
        "menu_settings": "Paramètres",
        "menu_about": "À propos",
        "menu_theme": "Thème (bientôt)",
        "menu_language": "Langue",
        "about_title": "À propos de Chatterbox",
        "keyboard_mode_text": "Texte",
        "keyboard_mode_phonemes": "Phonèmes",
        "keyboard_space": "Espace",
        "keyboard_backspace": "Effacer",
        "keyboard_clear_all": "Tout effacer",
        "keyboard_layout_label": "Disposition clavier :",
        "menu_toggle_audio_info": "Afficher les données de synthèse",
        "orientation_label": "Orientation :",
        "orientation_auto": "Auto",
        "orientation_portrait": "Portrait",
        "orientation_landscape": "Paysage",
        "about_body": "Chatterbox\nSynthèse vocale embarquée (FastSpeech 2 + HiFi-GAN)\n"
                       "Raspberry Pi 5 -- démonstrateur pour la communication alternative (AAC)",
        "loading_model_label": "Chargement du modèle…",
    },
    "en": {
        "tts_label": "TTS:",
        "vocoder_label": "Vocoder:",
        "synthesize_button": "Synthesize",
        "input_text_label": "Input",
        "replay_button": "Replay",
        "put_away_button": "Put away",
        "settings_button": "Settings",
        "speaker_label": "Speaker:",
        "styletag_label": "StyleTag:",
        "style_label": "Style:",
        "advanced_styles_toggle": "Advanced styles",
        "advanced_controls_toggle": "Advanced controls",
        "style_intensity_label": "Style intensity:",
        "pitch_label": "Pitch (semitones):",
        "energy_label": "Energy (dB):",
        "speed_label": "Speed (+ = slower):",
        "pitch_bias_label": "Pitch bias (semitones):",
        "energy_bias_label": "Energy bias (dB):",
        "speed_bias_label": "Speed bias (coef):",
        "pause_bias_label": "Pause bias:",
        "liaison_bias_label": "Liaison bias:",
        "variability_label": "Variability:",
        "phoneme_duration_variability_label": "Phoneme duration variability:",
        "audio_duration_label": "Audio duration: {duration:.3f}s",
        "stage_duration_label": "{name} duration: {duration:.3f}s | {percent:.0f}% of audio duration",
        "synthesis_duration_label": "Total synthesis duration: {duration:.3f}s | {percent:.0f}% of audio duration",
        "error_label": "Error: {error}",
        "gst_weights_title": "\nGST weights\n",
        "menu_settings": "Settings",
        "menu_about": "About",
        "menu_theme": "Theme (soon)",
        "menu_language": "Language",
        "about_title": "About Chatterbox",
        "keyboard_mode_text": "Text",
        "keyboard_mode_phonemes": "Phonemes",
        "keyboard_space": "Space",
        "keyboard_backspace": "Backspace",
        "keyboard_clear_all": "Clear all",
        "keyboard_layout_label": "Keyboard layout:",
        "menu_toggle_audio_info": "Show synthesis data",
        "orientation_label": "Orientation:",
        "orientation_auto": "Auto",
        "orientation_portrait": "Portrait",
        "orientation_landscape": "Landscape",
        "about_body": "Chatterbox\nEmbedded neural TTS (FastSpeech 2 + HiFi-GAN)\n"
                      "Raspberry Pi 5 -- augmentative and alternative communication (AAC) demonstrator",
        "loading_model_label": "Loading model…",
    },
}


def set_locale(code):
    """Switches the active locale used by t() below. `code` must already be a key of STRINGS
    (config_tts.yaml's GUI_config.languages is expected to only ever offer configured codes) --
    an unconfigured code is a configuration error, not something to silently fall back from."""
    global _LOCALE
    if code not in STRINGS:
        raise ValueError("Unknown locale {!r} -- STRINGS has {}".format(code, sorted(STRINGS)))
    _LOCALE = code


def get_locale():
    return _LOCALE


def t(key, **kwargs):
    """Looks up `key` in the active locale's table and formats it with `kwargs`. A missing key is
    a programming error (typo'd key), not something to swallow silently -- let the KeyError
    surface."""
    template = STRINGS[_LOCALE][key]
    return template.format(**kwargs) if kwargs else template
