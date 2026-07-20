#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Subtitle (.vtt) and duration-alignment (.json) file writers. Split out of audio_utils.py in
Phase 3 (docs/REORG_PROPOSAL.md) -- no model state, just the synthesized text/duration arrays
syn_audio() already has in hand.
"""
import codecs
import json
import math

import numpy as np


def write_duration_alignements(input_text_subtitles, processed_input_text_subtitles, duration_by_symbol_subtitles):
    # Data to be written
    alignment = {
        "input_text": input_text_subtitles,
        "pre_processed_input_text": processed_input_text_subtitles,
        "duration_by_symbol_pre_processed_input": duration_by_symbol_subtitles,
    }
    json_object = json.dumps(alignment)

    # Writing to sample.json
    with open("audio_file_duration_alignment.json", "w") as outfile:
        outfile.write(json_object)

    return alignment


def write_subtitles(input_text, preprocessed_input_text, duration_by_symbol, max_nbr_char):
    fp_subtitle = codecs.open("audio_file.fr.vtt", "w", "utf-8")
    fp_subtitle.write('WEBVTT\n\n')

    if len(preprocessed_input_text) <= max_nbr_char:
        duration_sub_utt = np.sum(duration_by_symbol)
        fp_subtitle.write('{} --> {}\n'.format(convert_seconds_to_datetime(0), convert_seconds_to_datetime(duration_sub_utt)))
        fp_subtitle.write("{}\n\n".format(input_text.strip()))
    else:
        separators_indexes = find_separators_subtitles(preprocessed_input_text, max_nbr_char)
        onset_duration = 0
        onset_index = 0
        for separator_index in separators_indexes:
            duration_sub_utt = np.sum(duration_by_symbol[onset_index:separator_index+1])
            fp_subtitle.write('{} --> {}\n'.format(convert_seconds_to_datetime(onset_duration), convert_seconds_to_datetime(onset_duration + duration_sub_utt)))
            fp_subtitle.write("{}\n\n".format(preprocessed_input_text[onset_index:separator_index+1].strip()))

            onset_duration += duration_sub_utt
            onset_index = separator_index+1

        print(separators_indexes)

    fp_subtitle.close()

    return fp_subtitle


def find_separators_subtitles(input_text, max_nbr_char):
    assert (len(input_text) > max_nbr_char)

    separators = ",.?!:;§~¬"
    separators_indexes = []

    for _, letter in enumerate(separators):
        separators_indexes += findOccurrences(input_text, letter)

    # sort and delete successive chars
    separators_indexes.sort(reverse=True)
    trimmed_separators = [separators_indexes[0]]
    last_index = separators_indexes[0]
    for sub_index in separators_indexes[1:]:
        if sub_index != last_index-1:
            trimmed_separators += [sub_index]
        last_index = sub_index

    trimmed_separators.sort()

    # Cut closer to the max number of char
    separators_subtitltes = []
    remaining_char = len(input_text)
    count_sub_utt = 0
    while (remaining_char > max_nbr_char):
        count_sub_utt += 1
        index_min = np.argmin(abs(np.array(trimmed_separators)-count_sub_utt*max_nbr_char))
        separators_subtitltes += [trimmed_separators[index_min]]
        remaining_char -= trimmed_separators[index_min] + 1

    separators_subtitltes += [len(input_text)-1]

    return separators_subtitltes


def findOccurrences(s, ch):
    return [i for i, letter in enumerate(s) if letter == ch]


def convert_seconds_to_datetime(duration):
    duration_h = math.floor(duration/3600)
    duration_min = math.floor((duration - duration_h*3600)/60)
    duration_s = math.floor(duration - duration_h*3600 - duration_min*60)
    duration_ms = round((duration - duration_h*3600 - duration_min*60 - duration_s)*1000)

    duration_datetime = "{:02d}:{:02d}:{:02d}.{:03d}".format(duration_h, duration_min, duration_s, duration_ms)
    return duration_datetime
