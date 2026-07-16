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
import json
import os
import platform
import subprocess
import sys
import time

from .recorder import NullRecorder, Recorder

_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_NULL_RECORDER = NullRecorder()
_current_recorder = contextvars.ContextVar("current_recorder", default=_NULL_RECORDER)

_enabled = os.environ.get("CHATTERBOX_PROFILE") == "1"
_output_dir = "profile"  # base dir; each session gets its own run_YYYYMMDD_HHMMSS/ under it
_run_dir = None
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


def get_run_dir():
    """The current session's per-run output directory (profile/run_.../), or
    None if no session has been started yet. per_sample.csv, per_sentence.jsonl,
    meta.json, and the join's output files all live here -- callers that need
    "the profiling output directory" (e.g. do_tts.py's --join/--export-xlsx)
    should use this, not the base dir set by set_output_dir()."""
    return _run_dir


def _read_governor():
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor") as f:
            return f.read().strip()
    except OSError:
        return None


def _read_calibration(base_dir):
    path = os.path.join(base_dir, "calibration.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _new_run_dir(base_dir, meta_extra=None, sample_hz=10, pmic_hz=10, core=3,
                  niceness=10, ina=True):
    """Create profile/run_YYYYMMDD_HHMMSS/, write its initial meta.json (the
    fields known at session-start time -- profiling/sampler.py separately
    patches in ina_detected/profiler_pid once it's actually probed the I2C
    bus), and point profile/latest at it. Isolates each run's per_sample.csv
    + per_sentence.jsonl from every other run's, instead of the previous
    single shared profile/ directory (overwritten sampler output vs
    forever-appended per_sentence.jsonl, which made the two impossible to
    join correctly after more than one run)."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_id = "run_" + stamp
    run_dir = os.path.join(base_dir, run_id)
    # Second-resolution timestamps collide if two sessions start in the same
    # wall-clock second (e.g. a script launching several short do_tts.py
    # invocations back to back) - disambiguate rather than silently reusing
    # (and clobbering) an existing run's directory.
    suffix = 2
    while os.path.exists(run_dir):
        run_id = "run_{}_{}".format(stamp, suffix)
        run_dir = os.path.join(base_dir, run_id)
        suffix += 1
    os.makedirs(run_dir)

    meta = {
        "run_id": run_id,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sample_hz": sample_hz,
        "pmic_hz": pmic_hz,
        "core": core,
        "niceness": niceness,
        "ina_requested": ina,
        "governor": _read_governor(),
        "calibration": _read_calibration(base_dir),
    }
    if meta_extra:
        meta.update(meta_extra)
    try:
        with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except OSError:
        pass

    _update_latest_pointer(base_dir, run_id)
    return run_dir


def _update_latest_pointer(base_dir, run_id):
    """Best-effort profile/latest -> profile/run_.../ symlink, so `python3 -m
    profiling.join` can default to the most recent run without an explicit
    --profile-dir. Falls back to a plain text pointer file when symlinks
    aren't available (e.g. Windows without developer mode / permissions) --
    profiling/join.py's default-dir resolution checks both."""
    latest_link = os.path.join(base_dir, "latest")
    try:
        if os.path.islink(latest_link) or os.path.exists(latest_link):
            os.remove(latest_link)
        os.symlink(run_id, latest_link, target_is_directory=True)
    except OSError:
        try:
            with open(latest_link + ".txt", "w", encoding="utf-8") as f:
                f.write(run_id)
        except OSError:
            pass


def start_session(core=3, niceness=10, sample_hz=10, pmic_hz=10, ina=True, meta_extra=None):
    """Create this session's per-run output directory and, on Linux, launch
    the background sampler as a subprocess into it. The run directory (and
    its meta.json) are created regardless of platform, so per-sentence
    timing records (which don't need the sampler) are still run-isolated on
    a non-Linux dev checkout -- only the sampler subprocess itself is
    Linux-only (the sysfs/vcgencmd sources it reads don't exist elsewhere).

    ina=True (default) makes the sampler auto-detect the INA226 amp-branch
    monitor at startup; absence is not an error, it just leaves the
    ina_bus_v/ina_current_a/ina_power_w columns empty. Pass ina=False to
    skip the I2C probe entirely.

    meta_extra: optional dict merged into the run's meta.json (e.g. do_tts.py
    passes {"play": args.play, "repeats": args.repeats} for --benchmark)."""
    global _sampler_proc, _run_dir
    if not _enabled or _sampler_proc is not None:
        return
    os.makedirs(_output_dir, exist_ok=True)
    _run_dir = _new_run_dir(
        _output_dir, meta_extra=meta_extra, sample_hz=sample_hz, pmic_hz=pmic_hz,
        core=core, niceness=niceness, ina=ina,
    )

    if platform.system() != "Linux":
        print("[profiling] background sampler needs sysfs/vcgencmd (Linux-only); "
              "skipping it. Per-sentence timing marks are still recorded, in {}.".format(_run_dir))
        return

    out_path = os.path.join(_run_dir, "per_sample.csv")
    pid_file = os.path.join(_run_dir, "sampler.pid")

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
    """Stop the sampler subprocess (if running). Deliberately does *not*
    clear get_run_dir() -- callers (do_tts.py's --join/--export-xlsx, which
    run after the try/finally that calls this) need to keep pointing at the
    just-finished run's directory. It's only reset when a *new* session
    starts."""
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
    # _run_dir is set by start_session(), which do_tts.py always calls before
    # any synthesis when profiling is enabled; _output_dir is a defensive
    # fallback only (e.g. a caller that begins recording without a session).
    out_path = os.path.join(_run_dir or _output_dir, "per_sentence.jsonl")
    return Recorder(sentence_id, text, out_path, complexity_tag=complexity_tag)


def set_current(recorder):
    """Publish the active recorder so nested calls (e.g. inside
    synthesis_modules.syn_fastspeech2) can reach it via current() without
    threading it through every function signature."""
    _current_recorder.set(recorder if recorder is not None else _NULL_RECORDER)


def current():
    return _current_recorder.get()
