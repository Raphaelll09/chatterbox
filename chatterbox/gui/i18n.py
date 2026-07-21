#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal string table (cc_prompt_gui_refactor.md Phase 1 item 10). The GUI's labels used to be a
hardcoded mix of French and English literals scattered across chatterbox/gui/app.py (e.g.
"Synthèse"/"Durée audio" next to "Speaker :"/"Pitch (semitones):") -- this module gives them one
consistent home instead.

Only "fr" is populated today, matching the end users (French AAC users) -- the app-bar's "Langue"
entry is a visible-but-disabled stub (see create_gui()'s menubar) until a real second locale table
exists to switch to. Add an "en" dict with the same keys under STRINGS to make that switch
meaningful; t() itself doesn't need to change.
"""

_LOCALE = "fr"

STRINGS = {
    "fr": {
        "tts_label": "TTS :",
        "vocoder_label": "Vocodeur :",
        "synthesize_button": "Synthèse",
        "input_text_label": "Texte à saisir",
        "replay_button": "Lire",
        "put_away_button": "Mettre en veille",
        "settings_button": "Réglages",
        "speaker_label": "Locuteur :",
        "styletag_label": "StyleTag :",
        "style_label": "Style :",
        "advanced_styles_toggle": "Styles avancés",
        "style_intensity_label": "Intensité du style :",
        "pitch_label": "Hauteur (demi-tons) :",
        "energy_label": "Énergie (dB) :",
        "speed_label": "Vitesse (coef) :",
        "pitch_bias_label": "Biais de hauteur (demi-tons) :",
        "energy_bias_label": "Biais d'énergie (dB) :",
        "speed_bias_label": "Biais de vitesse (coef) :",
        "pause_bias_label": "Biais de pause :",
        "liaison_bias_label": "Biais de liaison :",
        "audio_duration_label": "Durée audio : {duration:.3f}s",
        "tts_duration_label": "Durée TTS : {duration:.3f}s | {percent:.0f}% de la durée audio",
        "vocoder_duration_label": "Durée Vocodeur : {duration:.3f}s | {percent:.0f}% de la durée audio",
        "denoiser_duration_label": "Durée Denoiser : {duration:.3f}s | {percent:.0f}% de la durée audio",
        "synthesis_duration_label": "Durée Totale Synthèse : {duration:.3f}s | {percent:.0f}% de la durée audio",
        "error_label": "Erreur : {error}",
        "gst_weights_title": "\nPoids GST\n",
        "menu_about": "À propos",
        "menu_theme": "Thème (bientôt)",
        "menu_language": "Langue (bientôt)",
        "about_title": "À propos de Chatterbox",
        "keyboard_mode_text": "Texte",
        "keyboard_mode_phonemes": "Phonèmes",
        "keyboard_space": "Espace",
        "keyboard_backspace": "Effacer",
        "menu_toggle_audio_info": "Afficher les données de synthèse",
        "about_body": "Chatterbox\nSynthèse vocale embarquée (FastSpeech 2 + HiFi-GAN)\n"
                       "Raspberry Pi 5 -- démonstrateur pour la communication alternative (AAC)",
    },
}


def t(key, **kwargs):
    """Looks up `key` in the active locale's table and formats it with `kwargs`. A missing key is
    a programming error (typo'd key), not something to swallow silently -- let the KeyError
    surface."""
    template = STRINGS[_LOCALE][key]
    return template.format(**kwargs) if kwargs else template
