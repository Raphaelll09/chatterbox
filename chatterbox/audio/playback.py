#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audio playback -- platform branch (Windows: simpleaudio, falling back to sounddevice/soundfile;
other platforms: pydub.playback.play). Split out of audio_utils.py in Phase 3
(docs/REORG_PROPOSAL.md). See docs/context/ARCHITECTURE.md "Platform-specific playback" -- keep
both paths in sync when editing.

AUDIO_EXAMPLE holds the most recently synthesized clip so play_audio() can be called with no
arguments -- used both right after synthesis (chatterbox/cli.py) and by the GUI's standalone
"Play" replay button (chatterbox/gui/app.py), which is wired as a zero-argument Tkinter command
callback and can't easily be changed to pass the clip explicitly.
"""
import platform

current_os = platform.system()
if current_os == "Windows":
    try:
        import simpleaudio as sa
        _HAS_SIMPLEAUDIO = True
    except ImportError:
        import sounddevice as sd
        _HAS_SIMPLEAUDIO = False
else:
    from pydub.playback import play

AUDIO_EXAMPLE = None


def play_audio():
    """Play the clip most recently stashed in AUDIO_EXAMPLE."""
    current_os = platform.system()
    if current_os == "Windows": # memory issue on Windows
        # Extract raw audio data from the AudioSegment
        audio_data = AUDIO_EXAMPLE.raw_data

        # Set up the wave parameters needed for audio playback
        num_channels = AUDIO_EXAMPLE.channels
        bytes_per_sample = AUDIO_EXAMPLE.sample_width
        sample_rate = AUDIO_EXAMPLE.frame_rate

        if _HAS_SIMPLEAUDIO:
            wave_obj = sa.WaveObject(audio_data, num_channels, bytes_per_sample, sample_rate)
            play_obj = wave_obj.play()
            play_obj.wait_done()
            play_obj.stop()
        else:
            import numpy as np
            dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
            dtype = dtype_map.get(bytes_per_sample, np.int16)
            audio_np = np.frombuffer(audio_data, dtype=dtype)
            if num_channels > 1:
                audio_np = audio_np.reshape(-1, num_channels)
            sd.play(audio_np, samplerate=sample_rate)
            sd.wait()
    else:
        play(AUDIO_EXAMPLE)
