"""Tests for PiperBackend.describe_controls() -- mirrors tests/test_backend_describe_controls.py's
pattern (no real model load, no pretrained weights): _active_voice/_active_model_config are set
directly on a fresh instance. Covers Finding #2 from the Phase B plan (speaker_list is a dict
{name: id}, matching FastSpeech2HifiGanBackend's own real shape, not base.py's list-of-str
docstring) and the no-style-control invariant Finding #4 depends on.
"""
from chatterbox.synthesis.backends.piper.backend import PiperBackend


class _FakeConfig:
    def __init__(self, speaker_id_map, default_speaker_id=0):
        self.speaker_id_map = speaker_id_map
        self.default_speaker_id = default_speaker_id


class _FakeVoice:
    def __init__(self, speaker_id_map=None, default_speaker_id=0):
        self.config = _FakeConfig(speaker_id_map or {}, default_speaker_id)


def _make_model_config(**default_args_overrides):
    default_args = {
        "length_scale": 1.0,
        "noise_scale": 0.667,
        "noise_w_scale": 0.8,
        "apply_custom_regex_rules": False,
    }
    default_args.update(default_args_overrides)
    return {"default_args": default_args}


def _make_backend(speaker_id_map=None, default_speaker_id=0, **model_config_overrides):
    backend = PiperBackend()
    backend._active_voice = _FakeVoice(speaker_id_map, default_speaker_id)
    backend._active_model_config = _make_model_config(**model_config_overrides)
    return backend


def test_single_speaker_voice_omits_speaker_list():
    backend = _make_backend(speaker_id_map={})  # siwis/tom shape
    result = backend.describe_controls()
    assert "speaker_list" not in result
    assert "default_speaker" not in result


def test_multi_speaker_voice_returns_speaker_list_as_dict():
    backend = _make_backend(speaker_id_map={"jessica": 0, "pierre": 1}, default_speaker_id=0)
    result = backend.describe_controls()
    assert result["speaker_list"] == {"jessica": 0, "pierre": 1}
    assert result["default_speaker"] == 0


def test_no_style_control_ever_declared():
    for speaker_map in ({}, {"jessica": 0, "pierre": 1}):
        backend = _make_backend(speaker_id_map=speaker_map)
        controls = backend.describe_controls()["controls"]
        keys = {c["key"] for c in controls}
        assert "style" not in keys
        assert "style_intensity" not in keys


def test_controls_use_model_config_defaults():
    backend = _make_backend(length_scale=1.3, noise_scale=0.5, noise_w_scale=0.9)
    controls = backend.describe_controls()["controls"]
    by_key = {c["key"]: c for c in controls}
    assert by_key["length_scale"]["default"] == 1.3
    assert by_key["noise_scale"]["default"] == 0.5
    assert by_key["noise_w_scale"]["default"] == 0.9
    assert by_key["noise_scale"]["advanced"] is True
    assert by_key["noise_w_scale"]["advanced"] is True
