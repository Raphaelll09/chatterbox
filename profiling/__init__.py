#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional profiling subsystem for embedded_tts.

Off by default (zero files written, near-no-op marks) - enable with the
CHATTERBOX_PROFILE=1 env var, `do_tts.py --profile`, or `profiling.enabled:
true` in config_tts.yaml. See README.md "Profiling" for the output files,
the shared time.monotonic() clock design, and the PMIC calibration
procedure.

Three components share one clock:
- start_session()/stop_session(): background PMIC/CPU/thermal sampler
  (profiling/sampler.py), run as its own OS process, writing
  profile/per_sample.csv.
- begin_sentence()/set_current()/current(): per-sentence timing recorder
  (profiling/recorder.py) used from audio_utils.py and synthesis_modules.py,
  appending to profile/per_sentence.jsonl.
- profiling/join.py: offline script joining the two into
  profile/per_sentence_results.csv and profile/per_stage_results.csv.
"""
import atexit
import contextvars
import os
import platform
import subprocess
import sys

from .recorder import NullRecorder, Recorder

_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_NULL_RECORDER = NullRecorder()
_current_recorder = contextvars.ContextVar("current_recorder", default=_NULL_RECORDER)

_enabled = os.environ.get("CHATTERBOX_PROFILE") == "1"
_output_dir = "profile"
_sampler_proc = None
_sentence_counter = 0


def enable():
    global _enabled
    _enabled = True


def is_enabled():
    return _enabled


def set_output_dir(path):
    global _output_dir
    _output_dir = path


def start_session(core=3, niceness=10, sample_hz=10, pmic_hz=10, ina=True):
    """Launch the background sampler as a subprocess. No-op if disabled or
    not on Linux (the sysfs/vcgencmd sources it reads don't exist elsewhere,
    e.g. on a Windows dev checkout).

    ina=True (default) makes the sampler auto-detect the INA226 amp-branch
    monitor at startup; absence is not an error, it just leaves the
    ina_bus_v/ina_current_a/ina_power_w columns empty. Pass ina=False to
    skip the I2C probe entirely."""
    global _sampler_proc
    if not _enabled or _sampler_proc is not None:
        return
    if platform.system() != "Linux":
        print("[profiling] background sampler needs sysfs/vcgencmd (Linux-only); "
              "skipping it. Per-sentence timing marks are still recorded.")
        return

    os.makedirs(_output_dir, exist_ok=True)
    out_path = os.path.join(_output_dir, "per_sample.csv")
    pid_file = os.path.join(_output_dir, "sampler.pid")

    _sampler_proc = subprocess.Popen(
        [
            sys.executable, "-m", "profiling.sampler",
            "--out", out_path,
            "--sample-hz", str(sample_hz),
            "--pmic-hz", str(pmic_hz),
            "--core", str(core),
            "--nice", str(niceness),
            "--pid-file", pid_file,
            "--ina" if ina else "--no-ina",
        ],
        cwd=_PACKAGE_ROOT,
    )
    atexit.register(stop_session)


def stop_session(timeout=5):
    global _sampler_proc
    if _sampler_proc is None:
        return
    _sampler_proc.terminate()
    try:
        _sampler_proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _sampler_proc.kill()
        _sampler_proc.wait(timeout=timeout)
    _sampler_proc = None


def begin_sentence(text, complexity_tag=None, sentence_id=None):
    """Start a new per-sentence recorder, or a no-op one when disabled.

    sentence_id defaults to an auto-incrementing counter (free-text mode,
    where there's no natural id); callers with a natural id (e.g. the
    benchmark routine's "REF"/"A1"/...) can pass one explicitly."""
    global _sentence_counter
    if not _enabled:
        return _NULL_RECORDER
    if sentence_id is None:
        _sentence_counter += 1
        sentence_id = _sentence_counter
    out_path = os.path.join(_output_dir, "per_sentence.jsonl")
    return Recorder(sentence_id, text, out_path, complexity_tag=complexity_tag)


def set_current(recorder):
    """Publish the active recorder so nested calls (e.g. inside
    synthesis_modules.syn_fastspeech2) can reach it via current() without
    threading it through every function signature."""
    _current_recorder.set(recorder if recorder is not None else _NULL_RECORDER)


def current():
    return _current_recorder.get()
