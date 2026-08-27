#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The L1/L3 instrumentation seam.

This module exists so that the runtime package (L1 -- everything needed to make
the demonstrator speak) never imports the research package (L3 --
``research/``: profiling, benchmarking, power measurement). Before it existed,
``chatterbox/synth.py``, ``chatterbox/cli.py`` and both backends imported
``tools.monitoring.profiling`` at module scope, which meant deleting the
research tree did not merely disable profiling -- it made the runtime
package *unimportable*. See ``docs/release/STRUCTURE_AUDIT.md`` Sec4.

How it works
------------
Every profiling call site in L1 imports *this* module (conventionally as
``profiling``) and calls through it. By default every function here is inert,
which is exactly the shipped default (``config_tts.yaml``:
``profiling.enabled: false``).

``research/profiling/__init__.py`` calls :func:`install` on itself at import
time. From that moment the functions below delegate to the real implementation.
L1 therefore depends on this module only; the arrow from L3 to L1 is the
permitted direction.

    L1  chatterbox.synth  ->  chatterbox.instrumentation      (always)
    L3  research.profiling ->  chatterbox.instrumentation.install()  (when present)

Keeping this contract
---------------------
The API below is the *entire* surface L1 uses. If you add a profiling call in
L1, add the corresponding passthrough here -- do not import ``research.*`` from
``chatterbox.*``. ``scripts/check_layers.py`` and
``tests/test_layer_boundary.py`` enforce this mechanically.
"""
import contextlib


class NullRecorder:
    """No-op per-sentence recorder, returned by :func:`begin_sentence` and
    :func:`current` whenever no real implementation is installed.

    Mirrors the real recorder's surface (``research/profiling/recorder.py``)
    exactly, so call sites stay branch-free -- they never test whether
    profiling is on.
    """

    @contextlib.contextmanager
    def stage(self, name):
        yield

    def add(self, key, value):
        pass

    def set(self, **kwargs):
        pass

    def finalize(self):
        pass


_NULL_RECORDER = NullRecorder()

# The installed implementation (the research.profiling module itself), or None.
_impl = None


def install(impl):
    """Register the real profiling implementation.

    Called by ``research/profiling/__init__.py`` at the end of its own import.
    ``impl`` is expected to provide the module-level functions mirrored below.
    """
    global _impl
    _impl = impl


def is_installed():
    """True once a real implementation has been installed. Intended for
    diagnostics and tests, not for branching on the hot path."""
    return _impl is not None


# ---- Session control (called from chatterbox/cli.py) ----------------------


def enable():
    if _impl is not None:
        _impl.enable()


def is_enabled():
    return _impl.is_enabled() if _impl is not None else False


def set_output_dir(path):
    if _impl is not None:
        _impl.set_output_dir(path)


def start_session(**kwargs):
    if _impl is not None:
        return _impl.start_session(**kwargs)
    return None


def start_session_at(*args, **kwargs):
    if _impl is not None:
        return _impl.start_session_at(*args, **kwargs)
    return None


def stop_session(*args, **kwargs):
    if _impl is not None:
        return _impl.stop_session(*args, **kwargs)
    return None


def get_run_dir():
    return _impl.get_run_dir() if _impl is not None else None


# ---- Per-sentence recording (called from synth.py and both backends) ------


def begin_sentence(text, complexity_tag=None, sentence_id=None):
    if _impl is None:
        return _NULL_RECORDER
    return _impl.begin_sentence(
        text, complexity_tag=complexity_tag, sentence_id=sentence_id
    )


def set_current(recorder):
    if _impl is not None:
        _impl.set_current(recorder)


def current():
    return _impl.current() if _impl is not None else _NULL_RECORDER
