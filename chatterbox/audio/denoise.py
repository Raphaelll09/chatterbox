#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Noise reduction wrapper. Extracted from an inline block in audio_utils.py's syn_audio() in
Phase 3 (docs/REORG_PROPOSAL.md) -- same noisereduce call, now a standalone function.
"""
import noisereduce as nr


def denoise(data, rate):
    # data = nr.reduce_noise(
    #     y=data,
    #     sr=rate,
    #     prop_decrease=0.7,
    #     stationary=True,
    #     n_fft=512,
    #     n_std_thresh_stationary=1.5,
    #     chunk_size=600000,
    #     # freq_mask_smooth_hz=5000
    # )
    return nr.reduce_noise(
        y=data,
        sr=rate,
        prop_decrease=1,
    )
