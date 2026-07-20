#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Benchmark routine: runs the fixed sentence set (benchmark/sentences_fr.jsonl)
through the exact same synthesis call as free-text mode
(audio_utils.syn_audio()), with each sentence's id/tag labelling its
profiling record. See README.md "Benchmark" for the sentence-set design.

Order: REF (anchor), then the file's remaining entries in order, then REF
again (run-to-run drift check) - repeated `repeats` times, with a fixed
silent pause between every synthesis call so the continuous power log in
profile/per_sample.csv has clear idle baselines to slice around.
"""
import json
import os
import time

import audio_utils

DEFAULT_SENTENCES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sentences_fr.jsonl")
PAUSE_S = 2.0


def load_sentences(path):
    sentences = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                sentences.append(json.loads(line))
    return sentences


def run_benchmark(tts_config, sentences_path=DEFAULT_SENTENCES_PATH, play=False, repeats=1, pause_s=PAUSE_S):
    sentences = load_sentences(sentences_path)
    if not sentences:
        raise ValueError("No sentences found in {}".format(sentences_path))

    ref = sentences[0]
    ordered = sentences + [ref]  # REF anchors both ends, for a drift check

    total_runs = repeats * len(ordered)
    run_index = 0
    for repeat_index in range(repeats):
        for sentence in ordered:
            run_index += 1
            print("[benchmark] {}/{} - {} ({})".format(
                run_index, total_runs, sentence["id"], sentence["tag"],
            ))
            audio_utils.syn_audio(
                False, tts_config, sentence["text"],
                sentence_id=sentence["id"],
                complexity_tag=sentence["tag"],
                play=play,
            )
            if run_index < total_runs:
                time.sleep(pause_s)
