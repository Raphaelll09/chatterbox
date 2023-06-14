#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jul 21 14:29:50 2022

@author: lengletm
"""
import audio_utils
import gui_utils

keys = {
    "Emmanuelle": [
        [
            ("F", "f"), ("S", "s"), ("CH", "s^"), ("U", "y"), ("OU", "u"), ("▶", "play_and_clear", ["TTS_CONFIG", "ent_text_input", "entry_text_keyboard"]), ("C", "clear", ["ent_text_input", "entry_text_keyboard"])
        ],
        [
            ("V", "v"), ("Z", "z"), ("J", "z^"), ("I", "i"), ("O", "o"), ("/", "suppr", ["ent_text_input", "entry_text_keyboard"])
        ],
        [
            ("P", "p"), ("T", "t"), ("K", "k"), ("Y", "j"), ("EU", "x^"), ("ON", "o~")
        ],
        [
            ("B", "b"), ("D", "d"), ("G", "g"), ("R", "r"), ("É", "e"), ("IN", "e~")
        ],
        [
            ("M", "m"), ("N", "n"), ("L", "l"), (",", "}, {"), ("A", "a"), ("AN", "a~")
        ],
    ]
}

def play_and_clear(args):
    is_gui=True
    tts_global_conf=args[0]
    # ~ audio_utils.syn_audio(is_gui, tts_global_conf)
    audio_utils.syn_audio(is_gui, tts_global_conf, gui_control=gui_utils.get_gui_controls())
    # ~ args[1].delete(0, 'end')
    # ~ args[2]["text"] = ""
    
def clear(args):
    args[0].delete(0, 'end')
    args[1]['state'] = 'normal'
    args[1].delete(0, 'end')
    args[1]['state'] = 'readonly'

def suppr(args):
    # Suppr in main window
    suppr_phon_in_entry(args[0])

    # Suppr in keyboard window
    # Entry Version
    args[1]['state'] = 'normal'
    suppr_phon_in_entry(args[1])
    args[1]['state'] = 'readonly'
        
def suppr_phon_in_entry(entry):
    current_input = entry.get()
    nbr_spaces = 0
    char_to_suppr = 0
    len_string = len(current_input)
    have_suppr = False
    for char in current_input[::-1]:
        if char == ' ':
            nbr_spaces += 1
            if nbr_spaces > 1:
                entry.delete(len_string-char_to_suppr, 'end')
                have_suppr = True
                break
        char_to_suppr += 1

    # If suppress when only on phone
    if not have_suppr:
        entry.delete(0, 'end')
        
def suppr_phon_in_label(label):
    current_input = label.cget("text")
    nbr_spaces = 0
    char_to_suppr = 1
    len_string = len(current_input)
    have_suppr = False
    for char in current_input[::-1]:
        if char == ' ':
            nbr_spaces += 1
            if nbr_spaces > 1:
                label["text"] = current_input[:len_string-char_to_suppr]
                have_suppr = True
                break
        char_to_suppr += 1

    # If suppress when only on phone
    if not have_suppr:
        label["text"] = ""
