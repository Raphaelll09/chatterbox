#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audio playback -- platform branch (Windows: simpleaudio, falling back to sounddevice/soundfile;
other platforms: a direct ffplay subprocess, see "Interruptible playback" below). Split out of
audio_utils.py in Phase 3
(docs/research/history/REORG_PROPOSAL.md). See docs/ARCHITECTURE.md "Platform-specific playback" -- keep
both paths in sync when editing.

AUDIO_EXAMPLE holds the most recently synthesized clip so play_audio() can be called with no
arguments -- used both right after synthesis (chatterbox/cli.py) and by the GUI's standalone
"Play" replay button (chatterbox/gui/app.py), which is wired as a zero-argument Tkinter command
callback and can't easily be changed to pass the clip explicitly.

play_audio() also runs the amp handshake from chatterbox-powerd_spec_v0.1.md Sec6 ("Playback
contract") around the actual platform playback -- see _play_raw()/get_client() below. That
handshake is a true no-op whenever chatterbox-powerd isn't reachable (any PC dev checkout, or a Pi
before powerd is set up), so this file's behavior is unchanged there.

Interruptible playback (input-row phase, landscape-refactor plan, Stop button): _play_raw() records
a zero-arg "stop" callable in _current_stop_fn for whichever platform backend is actually playing,
then blocks on that backend's own wait call. stop_audio() (called from the GUI's Tk thread while
_play_raw() blocks on the worker thread) just invokes it. Read/write of a single reference is
atomic under the GIL, matching how chatterbox/gui/app.py's own `busy` flag is shared across threads
elsewhere in this codebase without a separate lock. On Linux/Pi, pydub.playback.play() wraps a
BLOCKING subprocess.call() to ffplay with no handle to interrupt it -- replaced here with a direct
subprocess.Popen() (export to a temp wav first, ffplay needs a file/pipe, not raw pydub data) so
Stop can .terminate() it; no new dependency, ffmpeg/ffplay was already required for pydub itself.
"""
import platform
import sys
import tempfile
import time

from chatterbox.config import paths as cb_paths
from chatterbox.power import config as power_config
from chatterbox.power.client import get_client

current_os = platform.system()
if current_os == "Windows":
    try:
        import simpleaudio as sa
        _HAS_SIMPLEAUDIO = True
    except ImportError:
        import sounddevice as sd
        _HAS_SIMPLEAUDIO = False
else:
    import os
    import subprocess

AUDIO_EXAMPLE = None

# Set by _play_raw() right before its platform-specific blocking wait, cleared right after --
# stop_audio() below is the only intended caller, from a different thread while _play_raw() blocks.
_current_stop_fn = None

_amp_timing_cache = None


def stop_audio():
    """Interrupts whatever _play_raw() is currently blocked on, if anything -- a no-op if nothing
    is playing. Safe to call from the Tk thread while _play_raw() blocks on the worker thread (see
    module docstring)."""
    stop_fn = _current_stop_fn
    if stop_fn is not None:
        stop_fn()


def _get_amp_timing():
    """Lazily load+cache the amp: settle_ms/preroll_ms/tail_ms knobs from user_prefs.yaml. Pure,
    validated config load (chatterbox/power/config.py) -- never raises, falls back to defaults."""
    global _amp_timing_cache
    if _amp_timing_cache is None:
        cfg, _warnings = power_config.load_config(str(cb_paths.USER_PREFS_PATH))
        _amp_timing_cache = cfg["amp"]
    return _amp_timing_cache


def play_audio():
    """Amp-on -> await ack -> settle+pre-roll -> play -> tail -> amp-off, wrapping _play_raw()
    below. Best-effort throughout: if powerd is unreachable, request_amp() returns False
    immediately (no blocking) and this reduces to exactly _play_raw() -- "audio is more important
    than the 0.33 W" (spec Sec6)."""
    client = get_client()
    timing = _get_amp_timing()

    acked = client.request_amp(True)
    if acked:
        time.sleep((timing["settle_ms"] + timing["preroll_ms"]) / 1000.0)
    elif client.is_connected():
        # Connected to powerd but this specific request didn't ack in time -- worth a log (unlike
        # "no powerd running at all", which client.py already logged once at connect time).
        print("[playback] amp_on not acked in time -- playing anyway (powerd's watchdog/DARK "
              "force-off remain the safety net)", file=sys.stderr)

    _play_raw()

    if acked:
        time.sleep(timing["tail_ms"] / 1000.0)
    client.request_amp(False)


def _play_raw():
    """The actual platform playback of AUDIO_EXAMPLE. Each branch records a stop callable into
    _current_stop_fn immediately before its own blocking wait, and clears it (via `finally`, so an
    exception mid-playback doesn't leave a stale stop_fn pointing at an already-finished clip)
    right after."""
    global _current_stop_fn
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
            _current_stop_fn = play_obj.stop
            try:
                play_obj.wait_done()
            finally:
                _current_stop_fn = None
            play_obj.stop()
        else:
            import numpy as np
            dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
            dtype = dtype_map.get(bytes_per_sample, np.int16)
            audio_np = np.frombuffer(audio_data, dtype=dtype)
            if num_channels > 1:
                audio_np = audio_np.reshape(-1, num_channels)
            sd.play(audio_np, samplerate=sample_rate)
            _current_stop_fn = sd.stop
            try:
                sd.wait()
            finally:
                _current_stop_fn = None
    else:
        # Direct ffplay invocation (not pydub.playback.play(), which shells out to ffplay via a
        # BLOCKING subprocess.call() with no handle to interrupt it -- module docstring). ffplay
        # needs a file, not raw pydub data, so export to a temp wav first; -nodisp/-autoexit keep
        # it a pure audio player (no video window, process exits on its own once playback ends).
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            AUDIO_EXAMPLE.export(tmp_path, format="wav")
            proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp_path])
            _current_stop_fn = proc.terminate
            try:
                proc.wait()
            finally:
                _current_stop_fn = None
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
