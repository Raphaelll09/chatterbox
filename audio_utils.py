#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jul 21 14:29:50 2022

@author: lengletm
"""
import os
import time
import noisereduce as nr
import numpy as np
from scipy.signal import butter,filtfilt
from scipy.io import wavfile
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
    _punctuation = list("[]§«»¬~!'(),.:;?#")
    if text_to_syn[0] not in _punctuation:
        text_to_syn = "{}{}".format(tts_config["default_start_punctuation"], text_to_syn)
    if text_to_syn[-1] not in _punctuation:
        text_to_syn = "{}{}".format(text_to_syn, tts_config["default_end_punctuation"])

    # TTS generates mel
    start_tts = time.time()

    # Parse Multiple utterances with "§"
    first_end_of_utt = text_to_syn.find('§')
    if first_end_of_utt > 0:
        text_to_syn_splitted = text_to_syn.split('§')
        for index_sub_utt, sub_utt in enumerate(text_to_syn_splitted):
            if index_sub_utt == 0:
                sub_utt = "{}§".format(sub_utt)
            if index_sub_utt != len(text_to_syn_splitted):
                sub_utt = "§{}§".format(sub_utt)
            else:
                sub_utt = "§{}".format(sub_utt)

            location_mel_file = synthesis_modules.tts(sub_utt, tts_config['tts_models'][TTS_INDEX], gui_control)

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
        location_mel_file = synthesis_modules.tts(text_to_syn, tts_config['tts_models'][TTS_INDEX], gui_control)
    
    end_tts = time.time()
    
    # Vocoder generates wav
    start_vocoder = time.time()
    location_wav_file = synthesis_modules.vocoder(location_mel_file, tts_config['vocoder_models'][VOCODER_INDEX])
    end_vocoder = time.time()

    # Denoise signal
    start_denoise = time.time()
    if tts_config["use_denoiser"]:
        # Copy noised version
        #cmd = "cp {}.wav {}_noise.wav".format(location_wav_file, location_wav_file)
        #os.system(cmd)

        # Denoising
        rate, data = wavfile.read("{}.wav".format(location_wav_file))
        # perform noise reduction
        reduced_noise = nr.reduce_noise(
            y=data, 
            sr=rate, 
            prop_decrease=0.7, 
            stationary=True, 
            n_fft=512, 
            n_std_thresh_stationary=1.5, 
            chunk_size=600000, 
            # freq_mask_smooth_hz=5000
        )
        wavfile.write("{}.wav".format(location_wav_file), rate, reduced_noise)

    if tts_config["use_smoothing"]:
        shape_au = tuple(np.fromfile(os.path.join(location_mel_file, 'audio_file.AU'), count = 4, dtype = np.int32))
        au_len = shape_au[0]
        au_dim = shape_au[1]
        au_num = shape_au[2]
        au_den = shape_au[3]
        au_data = np.copy(np.memmap(os.path.join(location_mel_file, 'audio_file.AU'),offset=16,dtype=np.float32,shape=(au_len, au_dim)))
        for i_au in range(6): # 6 first parameters are for the head movements
            au_data[:, i_au] = butter_lowpass_filter(au_data[:, i_au], 3, au_num/au_den, 1) # cutoff = 3Hz / order = 1

        fp = open(os.path.join(location_mel_file, 'audio_file.AU'), 'wb')
        fp.write(np.asarray((au_len, au_dim, au_num, au_den), dtype=np.int32))
        fp.write(au_data.copy(order='C'))
        fp.close()

    end_denoise = time.time()

    # Patch for .AU
    path_au = os.path.join(tts_config['tts_models'][TTS_INDEX]["folder"], tts_config['tts_models'][TTS_INDEX]["output_location"], "audio_file.AU")
    if os.path.exists(path_au):
        cmd = "cp {} ./".format(path_au)
        os.system(cmd)
    
    # Update audio infos
    AUDIO_EXAMPLE = AudioSegment.from_wav("{}.wav".format(location_wav_file))
    audio_duration = len(AUDIO_EXAMPLE)/1000
    tts_inference_duration = end_tts-start_tts
    vocoder_inference_duration = end_vocoder-start_vocoder
    denoiser_inference_duration = end_denoise-start_denoise
    
    if use_gui:
        gui_utils.update_audio_infos(audio_duration, tts_inference_duration, vocoder_inference_duration, denoiser_inference_duration)
    else:
        print("TTS duration: {:.3f}s | {:.0f}% of audio".format(end_tts-start_tts, 100*(end_tts-start_tts)/audio_duration))
        print("Vocoder duration: {:.3f}s | {:.0f}% of audio".format(end_vocoder-start_vocoder, 100*(end_vocoder-start_vocoder)/audio_duration))
        print("Denoise duration: {:.3f}s | {:.0f}% of audio".format(end_denoise-start_denoise, 100*(end_denoise-start_denoise)/audio_duration))
    
    # Play Audio
    play(AUDIO_EXAMPLE)
    
def play_audio():
    """play generated audio
    """
    # Play Audio
    play(AUDIO_EXAMPLE)

def butter_lowpass_filter(data, cutoff, fs, order):
    nyq = 0.5 * fs  # Nyquist Frequency

    normal_cutoff = cutoff / nyq
    # Get the filter coefficients 
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    y = filtfilt(b, a, data)
    return y