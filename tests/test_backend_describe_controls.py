"""Tests for FastSpeech2HifiGanBackend.describe_controls() (interchangeable-backend GUI refactor,
phase 3) -- verifies the generic "controls" schema it now emits mirrors what gui_fastspeech2()
used to hand-build directly from config_tts.yaml. No real model load needed: tts_model_config and
configs are set directly on a fresh instance, and text_pipeline.get_speaker_list() (real file I/O)
is monkeypatched.
"""
import pytest

from chatterbox.synthesis.backends.fastspeech2_hifigan.backend import FastSpeech2HifiGanBackend
import chatterbox.synthesis.backends.fastspeech2_hifigan.text_pipeline as text_pipeline


def _make_tts_model_config(**overrides):
    config = {
        "gst_token_list": {"NEUTRE": 1.0, "COLERE": 1.0, "TOKEN13": 1.0, "TOKEN14": 1.0},
        "gui_style_control": True,
        "gui_control_bias": False,
        "gui_styleTag_control": False,
        "default_args": {
            "gst_token_index": 0, "style_intensity": 1.0,
            "pitch_control": 0.0, "energy_control": 0.0, "duration_control": 1.0,
            "pitch_control_bias": 0.0, "energy_control_bias": 0.0,
            "duration_control_bias": 1.0, "pause_control_bias": 0.0, "liaison_control_bias": 0.0,
        },
    }
    config.update(overrides)
    return config


@pytest.fixture
def backend(monkeypatch):
    instance = FastSpeech2HifiGanBackend()
    instance.configs = ({"path": {"preprocessed_path": "fake"}},)
    monkeypatch.setattr(text_pipeline, "get_speaker_list", lambda path: {"NEB": 0, "DG": 1})
    return instance


def test_describe_controls_returns_speaker_list(backend):
    backend.tts_model_config = _make_tts_model_config()
    result = backend.describe_controls()
    assert result["speaker_list"] == {"NEB": 0, "DG": 1}


def test_describe_controls_style_chip_grid_has_hidden_pattern_for_placeholders(backend):
    backend.tts_model_config = _make_tts_model_config()
    controls = backend.describe_controls()["controls"]
    style_control = next(c for c in controls if c["key"] == "style")
    assert style_control["type"] == "chip_grid"
    assert style_control["options"] == ["NEUTRE", "COLERE", "TOKEN13", "TOKEN14"]
    assert style_control["default"] == 0
    assert style_control["hidden_pattern"] == r"^TOKEN\d+$"


def test_describe_controls_omits_style_controls_when_gui_style_control_false(backend):
    backend.tts_model_config = _make_tts_model_config(gui_style_control=False)
    controls = backend.describe_controls()["controls"]
    keys = {c["key"] for c in controls}
    assert "style" not in keys
    assert "style_intensity" not in keys


def test_describe_controls_bias_sliders_marked_advanced_when_gui_control_bias_false(backend):
    backend.tts_model_config = _make_tts_model_config(gui_control_bias=False)
    controls = backend.describe_controls()["controls"]
    bias_keys = {"pitch_bias", "energy_bias", "speed_bias", "pause_bias", "liaison_bias"}
    for control in controls:
        if control["key"] in bias_keys:
            assert control["advanced"] is True


def test_describe_controls_bias_sliders_not_advanced_when_gui_control_bias_true(backend):
    backend.tts_model_config = _make_tts_model_config(gui_control_bias=True)
    controls = backend.describe_controls()["controls"]
    bias_keys = {"pitch_bias", "energy_bias", "speed_bias", "pause_bias", "liaison_bias"}
    for control in controls:
        if control["key"] in bias_keys:
            assert control["advanced"] is False


def test_describe_controls_omits_style_tag_by_default(backend):
    backend.tts_model_config = _make_tts_model_config()
    controls = backend.describe_controls()["controls"]
    assert not any(c["key"] == "style_tag" for c in controls)


def test_describe_controls_includes_style_tag_when_enabled(backend):
    backend.tts_model_config = _make_tts_model_config(gui_styleTag_control=True)
    controls = backend.describe_controls()["controls"]
    style_tag_control = next(c for c in controls if c["key"] == "style_tag")
    assert style_tag_control["type"] == "text"
