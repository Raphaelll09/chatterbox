""" from https://github.com/keithito/tacotron """
import re
from text import cleaners
from text.symbols import symbols, out_symbols, _all_pct
import numpy as np


# Mappings from symbol to numeric ID and vice versa:
_symbol_to_id = {s: i for i, s in enumerate(symbols)}
_id_to_symbol = {i: s for i, s in enumerate(symbols)}

# Mappings from out_symbol to numeric ID and vice versa:
_out_symbol_to_id = {s: i for i, s in enumerate(out_symbols)}

# Regular expression matching text enclosed in curly braces:
_curly_re = re.compile(r"(.*?)\{(.+?)\}(.*)")


def text_to_sequence(text, cleaner_names=["basic_cleaners"]):
    """Converts a string of text to a sequence of IDs corresponding to the symbols in the text.

    The text can optionally have ARPAbet sequences enclosed in curly braces embedded
    in it. For example, "Turn left on {HH AW1 S S T AH0 N} Street."

    Args:
      text: string to convert to a sequence
      cleaner_names: names of the cleaner functions to run the text through

    Returns:
      List of integers corresponding to the symbols in the text
    """
    sequence = []

    # Check for curly braces and treat their contents as ARPAbet:
    while len(text):
        m = _curly_re.match(text)

        if not m:
            sequence += _symbols_to_sequence(_clean_text(text, cleaner_names))
            break
        sequence += _symbols_to_sequence(_clean_text(m.group(1), cleaner_names))
        sequence += _arpabet_to_sequence(m.group(2))
        text = m.group(3)

    return sequence


def sequence_to_text(sequence):
    """Converts a sequence of IDs back to a string"""
    result = ""
    for symbol_id in sequence:
        if symbol_id in _id_to_symbol:
            s = _id_to_symbol[symbol_id]
            # Enclose ARPAbet back in curly braces:
            if len(s) > 1 and s[0] == "@":
                s = "{%s}" % s[1:]
            result += s
    return result.replace("}{", " ")


def _clean_text(text, cleaner_names):
    for name in cleaner_names:
        cleaner = getattr(cleaners, name)
        if not cleaner:
            raise Exception("Unknown cleaner: %s" % name)
        text = cleaner(text)
    return text


def _symbols_to_sequence(symbols):
    return [_symbol_to_id[s] for s in symbols if _should_keep_symbol(s)]


def _arpabet_to_sequence(text):
    return _symbols_to_sequence(["@" + s for s in text.split()])

def _find_pattern_indexes_in_batch(list_patterns, texts):
    index_utt_in_batch = []
    index_target_char_in_utt = []
    for patterns_data in list_patterns:
        pattern = patterns_data[0]
        index_in_pattern = int(patterns_data[1])
        index_pattern_in_symbols = text_to_sequence(pattern, ["basic_cleaners"])

        for i_batch, text in enumerate(texts):
            length_without_padding = (text == 0).nonzero() # 0 = index of padding
            if length_without_padding.numel():
                length_without_padding = length_without_padding[0]
            else:
                length_without_padding = len(text)
            start_pattern_indexes = [x+index_in_pattern for x in range(length_without_padding-len(index_pattern_in_symbols)+1) if np.all(text[x:x+len(index_pattern_in_symbols)].cpu().numpy() == index_pattern_in_symbols)]
            # Exclude First and last char (initial and final silence not impacted)
            try:
                start_pattern_indexes.remove(0)
            except ValueError:
                #print("That item does not exist")
                pass
            try:
                start_pattern_indexes.remove(length_without_padding-1)
            except ValueError:
                #print("That item does not exist")
                pass
            try:
                start_pattern_indexes.remove(length_without_padding-2)
            except ValueError:
                #print("That item does not exist")
                pass

            index_target_char_in_utt = np.concatenate([index_target_char_in_utt, start_pattern_indexes])
            for _ in range(len(start_pattern_indexes)):
                index_utt_in_batch = np.concatenate([index_utt_in_batch, [i_batch]])
    if len(index_target_char_in_utt)==0:
        return [index_utt_in_batch, index_target_char_in_utt]
    else:
        return [index_utt_in_batch.astype(int), index_target_char_in_utt.astype(int)]

def _should_keep_symbol(s):
    if s not in symbols:
        print("The Character: '{}' is not in the symbols list".format(s.encode('utf8', 'replace')))
        # log(">> Symbol error")
        # warnings.warn("The Character is not in the symbols list")
        # log("The Character: '{}' is not in the symbols list".format(s.encode('utf8', 'replace'))) 
    return s in _symbol_to_id and s != '_' 
    # return s in _symbol_to_id and s != "_" and s != "~"
