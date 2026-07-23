"""Tests for PiperBackend.tts() -- no real voice weights needed (a fake _active_voice stands in
for PiperVoice, matching tests/test_backend_describe_controls.py's no-real-model-load pattern),
but piper-tts itself must be importable (tts() does `from piper.config import SynthesisConfig`,
a lightweight dataclass import, not a model load) -- guarded the same way
tests/test_export_xlsx.py guards its own optional openpyxl dependency.
"""
import os
import sys

import pytest

piper = pytest.importorskip("piper", reason="piper-tts not installed (optional dependency)")

from chatterbox.synthesis.backends.piper.backend import PiperBackend


class _FakeConfig:
    speaker_id_map = {}
    default_speaker_id = 0


class _FakeVoice:
    config = _FakeConfig()

    def synthesize_wav(self, text, wav_file, syn_config=None):
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 100)


def _make_backend_with_fake_voice():
    backend = PiperBackend()
    backend._active_voice = _FakeVoice()
    backend._active_model_config = {
        "default_args": {
            "length_scale": 1.0, "noise_scale": 0.667, "noise_w_scale": 0.8,
            "apply_custom_regex_rules": False,
        },
    }
    return backend


def _make_tts_config(tmp_path):
    return {
        "folder": str(tmp_path),
        "output_location": "output",
        "default_args": {
            "length_scale": 1.0, "noise_scale": 0.667, "noise_w_scale": 0.8,
            "apply_custom_regex_rules": False,
        },
    }


def test_tts_returns_output_dir_not_a_file_prefix(tmp_path):
    # Regression test: location_mel_file must be the output *directory*, matching FS2's own
    # tts() return value -- chatterbox/synth.py's needs_vocoder=False branch does
    # os.path.join(location_mel_file, "audio_file") itself. An earlier version of this backend
    # returned os.path.join(out_dir, "audio_file") here (a file-prefix, not a directory), which
    # synth.py then double-joined into a nonexistent .../audio_file/audio_file.wav path -- only
    # caught by a real --benchmark run on the Pi going through the real synth.py, not by this
    # backend's own tests in isolation (docs/context/CHANGELOG.md).
    backend = _make_backend_with_fake_voice()
    tts_config = _make_tts_config(tmp_path)

    location_mel_file, processed_text = backend.tts("Bonjour.", tts_config, None, False)

    assert location_mel_file == os.path.join(str(tmp_path), "output")
    # Mirrors chatterbox/synth.py's own needs_vocoder=False branch exactly.
    location_wav_file = os.path.join(location_mel_file, "audio_file")
    assert os.path.exists(location_wav_file + ".wav")


def test_tts_never_imports_flaubert(tmp_path):
    # Compare growth, not absolute absence: other test modules in the same pytest process may
    # already have imported something flaubert-named transitively (e.g. via FastSpeech2HifiGanBackend's
    # own module chain) before this test runs -- the actual claim is that calling
    # PiperBackend.tts() itself never *adds* one, not that the whole process is flaubert-free.
    before = {m for m in sys.modules if "flaubert" in m.lower()}

    backend = _make_backend_with_fake_voice()
    backend.tts("Bonjour.", _make_tts_config(tmp_path), None, False)

    after = {m for m in sys.modules if "flaubert" in m.lower()}
    assert after == before
