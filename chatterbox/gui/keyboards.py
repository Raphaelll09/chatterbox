#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jul 21 14:29:50 2022

@author: lengletm
"""
import chatterbox.gui.app as app
import chatterbox.gui.input as ginput

# A 2-tuple key ("LABEL", "phon") inserts "phon " into the text (chatterbox/gui/app.py's
# _keyboard_emit); a 3-tuple ("LABEL", "func_name", [args]) calls keyboards.<func_name>.
#
# Right column, rows 1-4: was the ":D / :p / :( / :O" GST mood shortcuts (play_and_clear_with_style,
# removed 2026-08-28 -- real-hardware feedback). Now punctuation: "?" "!" "." ";" insert the mark
# literally. In Phonemes mode synth.py wraps only the phone runs in {}, so these land OUTSIDE the
# braces and drive intonation (FastSpeech2 _punctuation includes all of them) instead of being fed
# to the phone-symbol lookup. The "," key changed from "}, {" (a manual brace break-out) to a
# plain "," for the same reason -- the wrap is smart about punctuation now.
keys = {
    "Emmanuelle": [
        [
            ("F", "f"), ("S", "s"), ("CH", "s^"), ("U", "y"), ("OU", "u"), ("▶", "play_and_clear", ["TTS_CONFIG", "ent_text_input", "entry_text_keyboard"]), ("C", "clear", ["ent_text_input", "entry_text_keyboard"])
        ],
        [
            ("V", "v"), ("Z", "z"), ("J", "z^"), ("I", "i"), ("O", "o"), ("/", "suppr", ["ent_text_input", "entry_text_keyboard"]), ("?", "?")
        ],
        [
            ("P", "p"), ("T", "t"), ("K", "k"), ("Y", "j"), ("EU", "x^"), ("ON", "o~"), ("!", "!")
        ],
        [
            ("B", "b"), ("D", "d"), ("G", "g"), ("R", "r"), ("É", "e"), ("IN", "e~"), (".", ".")
        ],
        [
            ("M", "m"), ("N", "n"), ("L", "l"), (",", ","), ("A", "a"), ("AN", "a~"), (";", ";")
        ],
    ]
}

def play_and_clear(args):
    # Name kept for the keys["Emmanuelle"] table, but this no longer clears the chatbox
    # (real-hardware feedback 2026-08-28: clearing on ▶ wiped the phrase so the user couldn't
    # replay it, and behaved differently from the "Synthèse" button and the Texte keyboard's own
    # ▶ -- neither of which clear). Explicit clearing stays on the "C" key (clear()) and the "/"
    # key (suppr()). args is ignored -- kept in the table entry so create_keyboard()'s special-key
    # path still has something to resolve.
    app.dispatch(ginput.Action.SPEAK)

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
