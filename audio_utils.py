#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jul 21 14:29:50 2022

@author: lengletm
"""
import os
import time
import codecs
import math
import json
import shutil
# import tempfile
import platform

# Get the current OS
current_os = platform.system() 
# Optionally, you can print the OS
if current_os == "Windows":
    import simpleaudio as sa

import noisereduce as nr
import numpy as np

from scipy.signal import butter,filtfilt
from scipy.io import wavfile, loadmat
from pydub import AudioSegment
from pydub.playback import play

import gui_utils
import tts_utils
import synthesis_modules

def syn_audio(use_gui, tts_config, txt_input="", gui_control=None):
    """Synthesize text with input text
    Uses global variables set during models loading
    """
    global AUDIO_EXAMPLE

    # Get global parameters
    TTS_INDEX = getattr(tts_utils, "TTS_INDEX")
    VOCODER_INDEX = getattr(tts_utils, "VOCODER_INDEX")
    
    if use_gui:
        canvas_circle, canvas_circle_figure = gui_utils.get_canvas_circle()
        gui_utils.update_circle_color("yellow", canvas_circle, canvas_circle_figure)

        ent_text_input = getattr(gui_utils, "ent_text_input")
        text_to_syn = ent_text_input.get()
    else:
        text_to_syn = txt_input

    # Debug Synthesis with empty input
    if text_to_syn == "":
        return
    
    if tts_config["GUI_config"]["online_phon_input"]:
        # Online phonetic input
        text_to_syn = "{{{}}}.".format(text_to_syn)

    # Use default punctuation if not given in text
    # Trim start and end spaces
    text_to_syn = text_to_syn.strip(' ')
    _punctuation = list("[]§«»¬~!'(),.:;?#")
    if text_to_syn[0] not in _punctuation:
        text_to_syn = "{}{}".format(tts_config["default_start_punctuation"], text_to_syn)
    if text_to_syn[-1] not in _punctuation:
        text_to_syn = "{}{}".format(text_to_syn, tts_config["default_end_punctuation"])

    # TTS generates mel
    start_tts = time.time()

    # Concat sub utterances for subtitles
    if tts_config["subtitles"]["create_file"]:
        input_text_subtitles = ''
        processed_input_text_subtitles = ''
        duration_by_symbol_subtitles = []

        duration_by_frame = tts_config["subtitles"]["duration_by_frame"]["hop_length"] / tts_config["subtitles"]["duration_by_frame"]["sampling_rate"]

    # Parse Multiple utterances with "§"
    sub_utterance_separator = '|'
    sub_utterance_pct = '§'
    first_end_of_utt = text_to_syn.find(sub_utterance_separator)
    if first_end_of_utt > 1:
        text_to_syn_splitted = text_to_syn.split(sub_utterance_separator)
        # print(text_to_syn_splitted)
        for index_sub_utt, sub_utt in enumerate(text_to_syn_splitted):

            # # With default sub-utterance pct
            # if index_sub_utt == 0:
            #     sub_utt = "{}{}".format(sub_utt, sub_utterance_pct)
            # elif index_sub_utt != (len(text_to_syn_splitted)-1):
            #     sub_utt = "{}{}{}".format(sub_utterance_pct, sub_utt, sub_utterance_pct)
            # elif index_sub_utt == (len(text_to_syn_splitted)-1) and sub_utt.strip(' ') == "":
            #     continue
            # else:
            #     sub_utt = "{}{}".format(sub_utterance_pct,sub_utt)

            # With linking pct
            if index_sub_utt > 0:
                sub_utt = "{}{}".format(linking_pct, sub_utt)
                linking_utt = True
            else:
                linking_utt = False

            linking_pct = sub_utt[-1]

            location_mel_file, processed_sub_text = synthesis_modules.tts(sub_utt, tts_config['tts_models'][TTS_INDEX], gui_control, linking_utt)

            if tts_config["subtitles"]["create_file"]:
                sub_duration_by_symbol = (np.load(os.path.join(location_mel_file, 'audio_file_duration.npy')) * duration_by_frame).tolist()
                duration_by_symbol_subtitles += sub_duration_by_symbol
                input_text_subtitles = "{}{}".format(input_text_subtitles, sub_utt[1:])
                processed_input_text_subtitles = "{}{}".format(processed_input_text_subtitles, processed_sub_text)

            shape_mel = tuple(np.fromfile(os.path.join(location_mel_file, 'audio_file.WAVEGLOW'), count = 2, dtype = np.int32))
            shape_au = tuple(np.fromfile(os.path.join(location_mel_file, 'audio_file.AU'), count = 4, dtype = np.int32))
            au_len = shape_au[0]
            if index_sub_utt == 0:
                mel_len = shape_mel[0]
                mel_dim = shape_mel[1]

                
                au_len_concat = au_len
                au_dim = shape_au[1]
                au_num = shape_au[2]
                au_den = shape_au[3]

                mel_file_concat = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.WAVEGLOW'),offset=8,dtype=np.float32,shape=shape_mel))
                au_file_concat = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.AU'),offset=16,dtype=np.float32,shape=(au_len, au_dim)))
            else:
                mel_file_sub_utt = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.WAVEGLOW'),offset=8,dtype=np.float32,shape=shape_mel))
                au_file_sub_utt = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.AU'),offset=16,dtype=np.float32,shape=(au_len, au_dim)))

                mel_file_concat = np.concatenate((mel_file_concat, mel_file_sub_utt))
                au_file_concat = np.concatenate((au_file_concat, au_file_sub_utt))

                mel_len += shape_mel[0]
                au_len_concat += au_len
        
        fp = open(os.path.join(location_mel_file, 'audio_file.WAVEGLOW'), 'wb')
        fp.write(np.asarray((mel_len, mel_dim), dtype=np.int32))
        fp.write(mel_file_concat.copy(order='C'))
        fp.close()

        fp = open(os.path.join(location_mel_file, 'audio_file.AU'), 'wb')
        fp.write(np.asarray((au_len_concat, au_dim, au_num, au_den), dtype=np.int32))
        fp.write(au_file_concat.copy(order='C'))
        fp.close()
    else:
        location_mel_file, processed_text_to_syn = synthesis_modules.tts(text_to_syn, tts_config['tts_models'][TTS_INDEX], gui_control, False)

        if tts_config["subtitles"]["create_file"]:
            duration_by_symbol_subtitles = (np.load(os.path.join(location_mel_file, 'audio_file_duration.npy')) * duration_by_frame).tolist()
            input_text_subtitles = text_to_syn[1:]
            processed_input_text_subtitles = processed_text_to_syn
    
    if tts_config["subtitles"]["create_file"]:
        duration_by_frame = tts_config["subtitles"]["duration_by_frame"]["hop_length"] / tts_config["subtitles"]["duration_by_frame"]["sampling_rate"]

        write_duration_alignements(input_text_subtitles, processed_input_text_subtitles, duration_by_symbol_subtitles)
        write_subtitles(input_text_subtitles, processed_input_text_subtitles, duration_by_symbol_subtitles, tts_config["subtitles"]["max_nbr_char"])

    end_tts = time.time()
    
    # Vocoder generates wav
    start_vocoder = time.time()
    location_wav_file = synthesis_modules.vocoder(location_mel_file, tts_config['vocoder_models'][VOCODER_INDEX])
    end_vocoder = time.time()

    # Denoise signal
    start_denoise = time.time()
    if tts_config["use_denoiser"]:
        # Denoising
        rate, data = wavfile.read("{}.wav".format(location_wav_file))
        # perform noise reduction
        # reduced_noise = nr.reduce_noise(
        #     y=data, 
        #     sr=rate, 
        #     prop_decrease=0.7, 
        #     stationary=True, 
        #     n_fft=512, 
        #     n_std_thresh_stationary=1.5, 
        #     chunk_size=600000, 
        #     # freq_mask_smooth_hz=5000
        # )
        reduced_noise = nr.reduce_noise(
            y=data, 
            sr=rate, 
            prop_decrease=1, 
        )
        wavfile.write("{}.wav".format(location_wav_file), rate, reduced_noise)

    if tts_config["visual_smoothing"]["activate"]:
        shape_au = tuple(np.fromfile(os.path.join(location_mel_file, 'audio_file.AU'), count = 4, dtype = np.int32))
        au_len = shape_au[0]
        au_dim = shape_au[1]
        au_num = shape_au[2]
        au_den = shape_au[3]
        au_data = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.AU'),offset=16,dtype=np.float32,shape=(au_len, au_dim)))
        for i_au in range(6): # 6 first parameters are for the head movements
            au_data[:, i_au] = butter_lowpass_filter(au_data[:, i_au], tts_config["visual_smoothing"]["cutoff"], au_num/au_den, 1) # cutoff = tts_config["visual_smoothing"]["cutoff"]Hz / order = 1

        fp = open(os.path.join(location_mel_file, 'audio_file.AU'), 'wb')
        fp.write(np.asarray((au_len, au_dim, au_num, au_den), dtype=np.int32))
        fp.write(au_data.copy(order='C'))
        fp.close()

    end_denoise = time.time()

    # Patch for .AU
    path_au = os.path.join(tts_config['tts_models'][TTS_INDEX]["folder"], tts_config['tts_models'][TTS_INDEX]["output_location"], "audio_file.AU")
    if os.path.exists(path_au):
        # Copy file in a platform-independent way
        shutil.copy(path_au, "./")  # Copy to current directory
    
    # Update audio infos
    AUDIO_EXAMPLE = AudioSegment.from_wav("{}.wav".format(location_wav_file))
    audio_duration = len(AUDIO_EXAMPLE)/1000
    tts_inference_duration = end_tts-start_tts
    vocoder_inference_duration = end_vocoder-start_vocoder
    denoiser_inference_duration = end_denoise-start_denoise
    
    if use_gui:
        gui_utils.update_circle_color("green", canvas_circle, canvas_circle_figure)
        gui_utils.update_audio_infos(audio_duration, tts_inference_duration, vocoder_inference_duration, denoiser_inference_duration)
        
        path_gst_weights = os.path.join(tts_config['tts_models'][TTS_INDEX]["folder"], tts_config['tts_models'][TTS_INDEX]["output_location"], "audio_file_styleTag_gst_weight.mat")
        if os.path.exists(path_gst_weights):
            GST_weights = loadmat(path_gst_weights)['styleTag_gst_weight']
            gui_utils.update_GST_infos(GST_weights)
    else:
        print("TTS duration: {:.3f}s | {:.0f}% of audio".format(end_tts-start_tts, 100*(end_tts-start_tts)/audio_duration))
        print("Vocoder duration: {:.3f}s | {:.0f}% of audio".format(end_vocoder-start_vocoder, 100*(end_vocoder-start_vocoder)/audio_duration))
        print("Denoise duration: {:.3f}s | {:.0f}% of audio".format(end_denoise-start_denoise, 100*(end_denoise-start_denoise)/audio_duration))
    
    # Play Audio
    # play(AUDIO_EXAMPLE)
    play_audio()
    gui_utils.update_circle_color("gray", canvas_circle, canvas_circle_figure)
    
def play_audio():
    """play generated audio
    """
    # Play Audio
    # Get the current OS
    current_os = platform.system() 
    # Optionally, you can print the OS
    if current_os == "Windows": # memory issue on Windows
        # Extract raw audio data from the AudioSegment
        audio_data = AUDIO_EXAMPLE.raw_data
        
        # Set up the wave parameters needed for simpleaudio
        num_channels = AUDIO_EXAMPLE.channels
        bytes_per_sample = AUDIO_EXAMPLE.sample_width
        sample_rate = AUDIO_EXAMPLE.frame_rate

        # Create a WaveObject using the raw data and the audio parameters
        wave_obj = sa.WaveObject(audio_data, num_channels, bytes_per_sample, sample_rate)
        
        # Play the audio
        play_obj = wave_obj.play()
        play_obj.wait_done()
        play_obj.stop()
    else:
        play(AUDIO_EXAMPLE)

def butter_lowpass_filter(data, cutoff, fs, order):
    nyq = 0.5 * fs  # Nyquist Frequency

    normal_cutoff = cutoff / nyq
    # Get the filter coefficients 
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    y = filtfilt(b, a, data)
    return y

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