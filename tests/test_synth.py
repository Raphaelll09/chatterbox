"""Tests for chatterbox/synth.py. Deliberately minimal -- synthesize()'s real pipeline needs
loaded FastSpeech2/HiFi-GAN models (same reasoning tests/test_benchmark.py already documents for
not faking chatterbox.cli.syn_audio's real pipeline); real-pipeline correctness for this refactor
is covered by the manual real-weights smoke test in docs/gui/GUI.md instead. This file covers what
*is* safely testable without models: the empty-input guard (returns before touching any backend)
and AudioResult's shape.
"""
from dataclasses import fields

from chatterbox.synth import AudioResult, synthesize

_MINIMAL_TTS_CONFIG = {
    "GUI_config": {"online_phon_input": False},
    "default_start_punctuation": ".",
    "default_end_punctuation": ".",
}


def test_synthesize_returns_none_for_empty_string():
    assert synthesize("", 0, 0, _MINIMAL_TTS_CONFIG) is None


def test_synthesize_returns_none_for_whitespace_only():
    assert synthesize("    ", 0, 0, _MINIMAL_TTS_CONFIG) is None


def test_audio_result_field_shape():
    result = AudioResult(
        audio_duration_s=1.0, tts_duration_s=0.5, vocoder_duration_s=0.3,
        denoiser_duration_s=0.1, gst_weights=None,
    )
    names = {f.name for f in fields(result)}
    assert names == {
        "audio_duration_s", "tts_duration_s", "vocoder_duration_s",
        "denoiser_duration_s", "gst_weights",
    }
    assert result.gst_weights is None


def test_audio_result_gst_weights_defaults_to_none():
    result = AudioResult(audio_duration_s=1.0, tts_duration_s=0.5, vocoder_duration_s=0.3, denoiser_duration_s=0.1)
    assert result.gst_weights is None
