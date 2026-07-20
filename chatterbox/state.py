#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jul 21 14:29:50 2022

@author: lengletm
"""

def update_selected_tts(index_button):
    global TTS_INDEX
    TTS_INDEX = index_button-1

def update_selected_vocoder(index_button):
    global VOCODER_INDEX
    VOCODER_INDEX = index_button-1