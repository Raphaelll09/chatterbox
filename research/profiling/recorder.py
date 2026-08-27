#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-sentence timing recorder for the optional profiling subsystem.

One Recorder is created per top-level input line (one call to
audio_utils.syn_audio()). It only records time.monotonic() timestamps and
light metadata - no heavy work, no threads - so it can sit on the hot path
with negligible overhead. Energy/CPU numbers are joined offline from
per_sample.csv by profiling/join.py, not computed here.
"""
import contextlib
import json
import os
import time


class NullRecorder:
    """No-op recorder used when profiling is disabled. Keeps call sites
    (synthesis_modules.py, audio_utils.py) branch-free."""

    @contextlib.contextmanager
    def stage(self, name):
        yield

    def add(self, key, value):
        pass

    def set(self, **kwargs):
        pass

    def finalize(self):
        pass


class Recorder:
    def __init__(self, sentence_id, text, out_path, complexity_tag=None):
        self.sentence_id = sentence_id
        self.text = text
        self.complexity_tag = complexity_tag
        self.out_path = out_path

        self.t_synth_start = time.monotonic()
        self.timestamps = {}
        # Durations accumulate across calls: the "§" sub-utterance loop in
        # audio_utils.syn_audio() calls synthesis_modules.tts() - and so
        # stage("front_end")/stage("acoustic") - once per sub-utterance, so a
        # single sentence record must sum them rather than overwrite.
        self.durations = {}
        self.extra = {}
        # First-seen order of distinct stage names (Piper integration,
        # docs/context/CHANGELOG.md) -- generalizes finalize()'s output beyond the 4 names it used
        # to hardcode (front_end/acoustic/vocoder/write), so a backend with a different stage
        # shape (e.g. Piper's "synth") isn't silently dropped. Repeated stage() calls for the same
        # name (the "§" case above) don't re-append -- self.durations/self.timestamps already
        # collapse those into one entry per name, same as before.
        self.stage_order = []

    @contextlib.contextmanager
    def stage(self, name):
        t0 = time.monotonic()
        try:
            yield
        finally:
            t1 = time.monotonic()
            if name not in self.durations:
                self.stage_order.append(name)
            self.durations[name] = self.durations.get(name, 0.0) + (t1 - t0)
            self.timestamps["t_{}_end".format(name)] = t1

    def add(self, key, value):
        self.extra[key] = self.extra.get(key, 0) + value

    def set(self, **kwargs):
        self.extra.update(kwargs)

    def finalize(self):
        t_audio_write_end = self.timestamps.get("t_write_end")
        t_vocoder_end = self.timestamps.get("t_vocoder_end")
        t_acoustic_end = self.timestamps.get("t_acoustic_end")
        t_front_end_end = self.timestamps.get("t_front_end_end")

        audio_duration_s = self.extra.get("audio_duration_s")
        total_synth_ms = None
        rtf = None
        if t_audio_write_end is not None:
            total_synth_ms = (t_audio_write_end - self.t_synth_start) * 1000.0
            if audio_duration_s:
                rtf = (total_synth_ms / 1000.0) / audio_duration_s

        record = {
            "sentence_id": self.sentence_id,
            "text": self.text,
            "char_count": self.extra.get("char_count"),
            "word_count": self.extra.get("word_count"),
            "phoneme_count": self.extra.get("phoneme_count"),
            "complexity_tag": self.complexity_tag,
            "t_synth_start": self.t_synth_start,
            "t_front_end_end": t_front_end_end,
            "t_acoustic_end": t_acoustic_end,
            "t_vocoder_end": t_vocoder_end,
            "t_audio_write_end": t_audio_write_end,
            "front_end_ms": self.durations.get("front_end", 0.0) * 1000.0,
            "acoustic_ms": self.durations.get("acoustic", 0.0) * 1000.0,
            "vocoder_ms": self.durations.get("vocoder", 0.0) * 1000.0,
            "write_ms": self.durations.get("write", 0.0) * 1000.0,
            "total_synth_ms": total_synth_ms,
            "audio_duration_s": audio_duration_s,
            "n_samples": self.extra.get("n_samples"),
            "sample_rate": self.extra.get("sample_rate"),
            "rtf": rtf,
            # Generic, order-preserving stage list -- alongside (not replacing) the fixed FS2
            # fields above, which stay byte-identical for backward compatibility. join.py's
            # build_per_stage_results() reads this when present (any backend, including FS2 going
            # forward) and falls back to the fixed front_end/acoustic/vocoder/write chain only for
            # records written before this field existed (re-joining historical per_sentence.jsonl
            # files -- see join.py's own module docstring on that use case).
            "stages": [
                {
                    "name": name,
                    "t_end": self.timestamps.get("t_{}_end".format(name)),
                    "duration_ms": self.durations.get(name, 0.0) * 1000.0,
                }
                for name in self.stage_order
            ],
        }

        os.makedirs(os.path.dirname(self.out_path), exist_ok=True)
        with open(self.out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return record
