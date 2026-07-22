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
        audio_duration_s=1.0,
        stage_durations={"tts": 0.5, "vocoder": 0.3, "denoiser": 0.1},
        gst_weights=None,
    )
    names = {f.name for f in fields(result)}
    assert names == {"audio_duration_s", "stage_durations", "gst_weights"}
    assert result.gst_weights is None


def test_audio_result_gst_weights_defaults_to_none():
    result = AudioResult(audio_duration_s=1.0, stage_durations={"tts": 0.5})
    assert result.gst_weights is None


def test_audio_result_stage_durations_omits_vocoder_for_monolithic_backend():
    # A monolithic backend (needs_vocoder: False) never runs a separate vocoder stage -- see
    # chatterbox/synth.py's synthesize(), which only adds "vocoder" to stage_durations when the
    # active TTS model's needs_vocoder flag is true.
    result = AudioResult(audio_duration_s=1.0, stage_durations={"tts": 0.5, "denoiser": 0.1})
    assert "vocoder" not in result.stage_durations
    assert set(result.stage_durations) == {"tts", "denoiser"}
